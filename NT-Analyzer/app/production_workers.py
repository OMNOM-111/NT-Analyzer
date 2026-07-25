"""PostgreSQL-backed, horizontally safe Production worker runtime.

Development keeps using :mod:`app.local_worker`.  This module is deliberately
Production-only: queue state, leases, retries, quotas, rate limits and
idempotency live in authoritative PostgreSQL and never fall back to SQLite.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import signal
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

from .production_storage import (
    Scope,
    StorageConflictError,
    StorageConstraintError,
    StorageError,
    StorageUnavailableError,
    get_client,
)
from .production_storage.core import PostgresClient, _jsonb


DEFAULT_WORKER_CLASSES: Dict[str, Dict[str, int]] = {
    "interactive_ai": {
        "max_concurrency": 4, "max_payload_bytes": 65536,
        "default_timeout_sec": 900, "max_queued": 100, "max_running": 2,
    },
    "chart": {
        "max_concurrency": 4, "max_payload_bytes": 524288,
        "default_timeout_sec": 180, "max_queued": 80, "max_running": 2,
    },
    "telemetry": {
        "max_concurrency": 2, "max_payload_bytes": 131072,
        "default_timeout_sec": 300, "max_queued": 200, "max_running": 2,
    },
    "maintenance": {
        "max_concurrency": 1, "max_payload_bytes": 65536,
        "default_timeout_sec": 300, "max_queued": 40, "max_running": 1,
    },
}

KIND_WORKER_CLASS = {
    "ai_orchestrator": "interactive_ai",
    "chart_batch": "chart",
    "telemetry_index": "telemetry",
    "durable_sweep": "maintenance",
    # Deterministic diagnostic handlers used by failure/load acceptance.
    "noop": "maintenance",
    "sleep": "maintenance",
    "fail": "maintenance",
}

_SAFE_KIND = re.compile(r"^[a-z][a-z0-9_.:-]{1,79}$")
_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{7,159}$")
_SAFE_OPERATION = re.compile(r"^[a-z][a-z0-9_.:-]{1,99}$")
_QUEUE: Optional["ProductionQueue"] = None
_QUEUE_LOCK = threading.RLock()


class ProductionQueueError(StorageError):
    code = "production_queue_error"


class QueueQuotaExceeded(ProductionQueueError):
    code = "queue_quota_exceeded"


class QueuePayloadTooLarge(ProductionQueueError):
    code = "queue_payload_too_large"


class QueueIdempotencyConflict(ProductionQueueError):
    code = "queue_idempotency_conflict"


class QueueLeaseLost(ProductionQueueError):
    code = "queue_lease_lost"


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False, default=str,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProductionQueueError("Worker payload is not valid canonical JSON.") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )
    return ""


def _clean_error(value: Any) -> str:
    text = " ".join(str(value or "worker failed").replace("\x00", " ").split())
    return text[:1000]


def _row_job(row: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    out = dict(row)
    document = out.get("document") if isinstance(out.get("document"), dict) else {}
    out["payload"] = dict(document.get("payload") or {})
    out["result"] = dict(document.get("result") or {})
    out["request_hash"] = str(document.get("request_hash") or "")
    out["worker_job_id"] = str(out.get("job_id") or "")
    storage_status = str(out.get("status") or "")
    out["queue_status"] = storage_status
    out["status"] = {
        "completed": "succeeded",
        "dead_letter": "failed",
        "review": "stale",
    }.get(storage_status, storage_status)
    out["error"] = str(out.get("last_error") or "")
    for key in (
        "created_at", "updated_at", "available_at", "started_at", "finished_at",
        "leased_until", "heartbeat_at",
    ):
        if isinstance(out.get(key), datetime):
            out[key + "_utc"] = _iso(out[key])
    out["queued_at_utc"] = str(out.get("created_at_utc") or "")
    if out.get("lease_token") is not None:
        out["lease_token"] = str(out["lease_token"])
    return out


def public_job(row: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return queue state without payload, result contents or tenant identity."""
    if not row:
        return None
    return {
        "worker_job_id": str(row.get("worker_job_id") or row.get("job_id") or ""),
        "kind": str(row.get("kind") or ""),
        "worker_class": str(row.get("worker_class") or ""),
        "status": str(row.get("status") or ""),
        "queue_status": str(row.get("queue_status") or row.get("status") or ""),
        "priority": int(row.get("priority") or 0),
        "attempts": int(row.get("attempts") or 0),
        "max_attempts": int(row.get("max_attempts") or 0),
        "cancel_requested": bool(row.get("cancel_requested")),
        "dangerous": bool(row.get("dangerous")),
        "payload_bytes": int(row.get("payload_bytes") or 0),
        "result_bytes": int(row.get("result_bytes") or 0),
        "queued_at_utc": str(row.get("created_at_utc") or _iso(row.get("created_at"))),
        "started_at_utc": str(row.get("started_at_utc") or _iso(row.get("started_at"))),
        "finished_at_utc": str(row.get("finished_at_utc") or _iso(row.get("finished_at"))),
        "updated_at_utc": str(row.get("updated_at_utc") or _iso(row.get("updated_at"))),
        "error": str(row.get("last_error") or "")[:240],
    }


class ProductionQueue:
    def __init__(self, client: PostgresClient) -> None:
        self.client = client
        self._defaults_ready = False
        self._defaults_lock = threading.Lock()

    def ensure_defaults(self) -> None:
        if self._defaults_ready:
            return
        with self._defaults_lock:
            if self._defaults_ready:
                return
            with self.client.transaction(Scope.global_service_scope()) as conn:
                for name, config in DEFAULT_WORKER_CLASSES.items():
                    conn.execute(
                        """
                        INSERT INTO sf_worker_classes(
                          worker_class,max_concurrency,max_payload_bytes,
                          default_timeout_sec,document
                        ) VALUES(%s,%s,%s,%s,%s)
                        ON CONFLICT(worker_class) DO NOTHING
                        """,
                        (
                            name, config["max_concurrency"], config["max_payload_bytes"],
                            config["default_timeout_sec"], _jsonb({"managed_default": True}),
                        ),
                    )
            self._defaults_ready = True

    def class_configs(self) -> Dict[str, Dict[str, Any]]:
        self.ensure_defaults()
        with self.client.transaction(Scope.global_service_scope(), read_only=True) as conn:
            rows = conn.execute(
                """SELECT worker_class,max_concurrency,max_payload_bytes,
                          default_timeout_sec,enabled
                   FROM sf_worker_classes ORDER BY worker_class"""
            ).fetchall()
        return {str(row["worker_class"]): dict(row) for row in rows}

    def enqueue(
        self,
        kind: str,
        payload: Optional[Mapping[str, Any]],
        *,
        scope: Scope,
        worker_class: str = "",
        priority: int = 100,
        max_attempts: int = 1,
        timeout_sec: int = 0,
        idempotency_key: str,
        job_id: str = "",
        dangerous: bool = False,
    ) -> Dict[str, Any]:
        self.ensure_defaults()
        clean_kind = str(kind or "").strip().lower()
        if not _SAFE_KIND.fullmatch(clean_kind):
            raise ProductionQueueError("Invalid Production worker kind.")
        expected_class = KIND_WORKER_CLASS.get(clean_kind)
        clean_class = str(worker_class or expected_class or "").strip().lower()
        if expected_class is None or clean_class != expected_class:
            raise ProductionQueueError("Worker kind is not assigned to this Production class.")
        key = str(idempotency_key or "").strip()
        if not _SAFE_KEY.fullmatch(key):
            raise ProductionQueueError("A safe 8..160 character idempotency key is required.")
        if not scope.workspace_id or scope.user_id <= 0 or scope.global_service:
            raise ProductionQueueError("Production jobs require a user/workspace scope.")
        clean_payload = dict(payload or {})
        payload_bytes = len(_canonical(clean_payload))
        requested_attempts = max(1, min(20, int(max_attempts or 1)))
        if dangerous:
            # Dangerous effects are admitted exactly once and never auto-retried.
            requested_attempts = 1
        requested_priority = max(0, min(1000, int(priority or 100)))
        identity = {
            "kind": clean_kind, "worker_class": clean_class,
            "payload": clean_payload, "dangerous": bool(dangerous),
        }
        request_hash = _sha256(identity)
        target_id = str(job_id or "").strip() or ("job_" + uuid.uuid4().hex)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{5,159}", target_id):
            raise ProductionQueueError("Invalid Production job id.")

        with self.client.transaction(scope) as conn:
            class_row = conn.execute(
                """SELECT max_payload_bytes,default_timeout_sec,enabled
                   FROM sf_worker_classes WHERE worker_class=%s""",
                (clean_class,),
            ).fetchone()
            if not class_row or not bool(class_row["enabled"]):
                raise ProductionQueueError("Production worker class is disabled.")
            if payload_bytes > int(class_row["max_payload_bytes"]):
                raise QueuePayloadTooLarge("Worker payload exceeds its class limit.")
            active_timeout = int(timeout_sec or class_row["default_timeout_sec"])
            active_timeout = max(1, min(86400, active_timeout))
            defaults = DEFAULT_WORKER_CLASSES[clean_class]
            conn.execute(
                """
                INSERT INTO sf_workspace_queue_quotas(
                  workspace_id,worker_class,max_queued,max_running,weight
                ) VALUES(%s,%s,%s,%s,1)
                ON CONFLICT(workspace_id,worker_class) DO NOTHING
                """,
                (
                    scope.workspace_id, clean_class,
                    defaults["max_queued"], defaults["max_running"],
                ),
            )
            quota = conn.execute(
                """SELECT max_queued,max_running FROM sf_workspace_queue_quotas
                   WHERE workspace_id=%s AND worker_class=%s FOR UPDATE""",
                (scope.workspace_id, clean_class),
            ).fetchone()
            existing = conn.execute(
                """SELECT * FROM sf_jobs
                   WHERE workspace_id=%s AND idempotency_key=%s""",
                (scope.workspace_id, key),
            ).fetchone()
            if existing:
                replay = _row_job(existing) or {}
                if not secrets.compare_digest(str(replay.get("request_hash") or ""), request_hash):
                    raise QueueIdempotencyConflict(
                        "Idempotency key was already used with another worker request."
                    )
                replay["idempotent_replay"] = True
                return replay
            queued = conn.execute(
                """SELECT count(*) AS count FROM sf_jobs
                   WHERE workspace_id=%s AND worker_class=%s AND status='queued'""",
                (scope.workspace_id, clean_class),
            ).fetchone()
            if int(queued["count"] or 0) >= int(quota["max_queued"]):
                raise QueueQuotaExceeded("Workspace queued-job quota exceeded.")
            document = {
                "schema_version": 1,
                "payload": clean_payload,
                "result": {},
                "request_hash": request_hash,
            }
            inserted = conn.execute(
                """
                INSERT INTO sf_jobs(
                  job_id,workspace_id,user_id,kind,status,idempotency_key,document,
                  worker_class,priority,max_attempts,timeout_sec,dangerous,payload_bytes
                ) VALUES(%s,%s,%s,%s,'queued',%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(workspace_id,idempotency_key) DO NOTHING
                RETURNING *
                """,
                (
                    target_id, scope.workspace_id, scope.user_id, clean_kind, key,
                    _jsonb(document), clean_class, requested_priority,
                    requested_attempts, active_timeout, bool(dangerous), payload_bytes,
                ),
            ).fetchone()
            if not inserted:
                raced = conn.execute(
                    "SELECT * FROM sf_jobs WHERE workspace_id=%s AND idempotency_key=%s",
                    (scope.workspace_id, key),
                ).fetchone()
                replay = _row_job(raced) or {}
                if not secrets.compare_digest(str(replay.get("request_hash") or ""), request_hash):
                    raise QueueIdempotencyConflict(
                        "Concurrent idempotency key conflict."
                    )
                replay["idempotent_replay"] = True
                return replay
        return _row_job(inserted) or {"job_id": target_id}

    def get(self, job_id: str, *, scope: Scope) -> Optional[Dict[str, Any]]:
        with self.client.transaction(scope, read_only=True) as conn:
            row = conn.execute("SELECT * FROM sf_jobs WHERE job_id=%s", (str(job_id),)).fetchone()
        return _row_job(row)

    def get_global(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self.client.transaction(Scope.global_service_scope(), read_only=True) as conn:
            row = conn.execute("SELECT * FROM sf_jobs WHERE job_id=%s", (str(job_id),)).fetchone()
        return _row_job(row)

    def list(self, *, scope: Scope, status: str = "", limit: int = 100) -> list[Dict[str, Any]]:
        capped = max(1, min(1000, int(limit or 100)))
        with self.client.transaction(scope, read_only=True) as conn:
            if status:
                rows = conn.execute(
                    """SELECT * FROM sf_jobs WHERE status=%s
                       ORDER BY updated_at DESC LIMIT %s""",
                    (str(status), capped),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM sf_jobs ORDER BY updated_at DESC LIMIT %s", (capped,),
                ).fetchall()
        return [_row_job(row) or {} for row in rows]

    def counts(self, *, scope: Scope) -> Dict[str, int]:
        with self.client.transaction(scope, read_only=True) as conn:
            rows = conn.execute(
                "SELECT status,count(*) AS count FROM sf_jobs GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def claim(self, worker_class: str, *, worker_id: str) -> Optional[Dict[str, Any]]:
        self.ensure_defaults()
        clean_class = str(worker_class or "").strip().lower()
        clean_worker = str(worker_id or "").strip()[:160]
        if clean_class not in DEFAULT_WORKER_CLASSES or not clean_worker:
            raise ProductionQueueError("Worker class and worker id are required.")
        lease_token = uuid.uuid4()
        with self.client.transaction(Scope.global_service_scope()) as conn:
            config = conn.execute(
                """SELECT max_concurrency,enabled FROM sf_worker_classes
                   WHERE worker_class=%s FOR UPDATE""",
                (clean_class,),
            ).fetchone()
            if not config or not bool(config["enabled"]):
                return None
            active = conn.execute(
                """SELECT count(*) AS count FROM sf_jobs
                   WHERE worker_class=%s AND status='running'""",
                (clean_class,),
            ).fetchone()
            if int(active["count"] or 0) >= int(config["max_concurrency"]):
                return None
            candidate = conn.execute(
                """
                SELECT j.job_id
                FROM sf_jobs j
                WHERE j.worker_class=%s AND j.status='queued'
                  AND j.cancel_requested=FALSE AND j.available_at<=clock_timestamp()
                  AND (
                    SELECT count(*) FROM sf_jobs running
                    WHERE running.workspace_id=j.workspace_id
                      AND running.worker_class=j.worker_class
                      AND running.status='running'
                  ) < COALESCE((
                    SELECT quota.max_running FROM sf_workspace_queue_quotas quota
                    WHERE quota.workspace_id=j.workspace_id
                      AND quota.worker_class=j.worker_class
                  ), 1)
                ORDER BY COALESCE((
                    SELECT state.last_claimed_at FROM sf_queue_workspace_state state
                    WHERE state.workspace_id=j.workspace_id
                      AND state.worker_class=j.worker_class
                  ), '-infinity'::timestamptz),
                  j.priority, j.available_at, j.created_at, j.job_id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                (clean_class,),
            ).fetchone()
            if not candidate:
                return None
            row = conn.execute(
                """
                UPDATE sf_jobs
                SET status='running',attempts=attempts+1,
                    started_at=clock_timestamp(),finished_at=NULL,
                    leased_until=clock_timestamp()
                      + (LEAST(timeout_sec,30) * interval '1 second'),
                    lease_owner=%s,lease_token=%s,heartbeat_at=clock_timestamp(),
                    updated_at=clock_timestamp(),last_error=''
                WHERE job_id=%s AND status='queued' AND cancel_requested=FALSE
                RETURNING *
                """,
                (clean_worker, lease_token, candidate["job_id"]),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                """
                INSERT INTO sf_job_attempts(
                  job_id,workspace_id,attempt,worker_id,lease_token
                ) VALUES(%s,%s,%s,%s,%s)
                """,
                (
                    row["job_id"], row["workspace_id"], row["attempts"],
                    clean_worker, lease_token,
                ),
            )
            conn.execute(
                """
                INSERT INTO sf_queue_workspace_state(
                  workspace_id,worker_class,last_claimed_at,served_count
                ) VALUES(%s,%s,clock_timestamp(),1)
                ON CONFLICT(workspace_id,worker_class) DO UPDATE SET
                  last_claimed_at=clock_timestamp(),
                  served_count=sf_queue_workspace_state.served_count+1
                """,
                (row["workspace_id"], clean_class),
            )
        return _row_job(row)

    def heartbeat(
        self, job_id: str, *, worker_id: str, lease_token: str,
        lease_sec: int = 30,
    ) -> bool:
        lease = max(1, min(60, int(lease_sec or 30)))
        with self.client.transaction(Scope.global_service_scope()) as conn:
            row = conn.execute(
                """
                UPDATE sf_jobs SET
                  heartbeat_at=clock_timestamp(),
                  leased_until=LEAST(
                    started_at + (timeout_sec * interval '1 second'),
                    clock_timestamp() + (%s * interval '1 second')
                  ),
                  updated_at=clock_timestamp()
                WHERE job_id=%s AND status='running' AND lease_owner=%s
                  AND lease_token=%s::uuid AND cancel_requested=FALSE
                  AND started_at + (timeout_sec * interval '1 second') > clock_timestamp()
                RETURNING attempts
                """,
                (lease, str(job_id), str(worker_id), str(lease_token)),
            ).fetchone()
            if row:
                conn.execute(
                    """UPDATE sf_job_attempts SET heartbeat_at=clock_timestamp()
                       WHERE job_id=%s AND attempt=%s AND lease_token=%s::uuid""",
                    (str(job_id), row["attempts"], str(lease_token)),
                )
        return bool(row)

    def cancel_requested(
        self, job_id: str, *, worker_id: str, lease_token: str,
    ) -> bool:
        with self.client.transaction(Scope.global_service_scope(), read_only=True) as conn:
            row = conn.execute(
                """SELECT status,cancel_requested,lease_owner,lease_token
                   FROM sf_jobs WHERE job_id=%s""",
                (str(job_id),),
            ).fetchone()
        return bool(
            not row
            or str(row["status"]) != "running"
            or str(row["lease_owner"] or "") != str(worker_id)
            or str(row["lease_token"] or "") != str(lease_token)
            or row["cancel_requested"]
        )

    def cancel(self, job_id: str, *, scope: Scope) -> Optional[Dict[str, Any]]:
        with self.client.transaction(scope) as conn:
            row = conn.execute(
                "SELECT * FROM sf_jobs WHERE job_id=%s FOR UPDATE", (str(job_id),),
            ).fetchone()
            if not row:
                return None
            if str(row["status"]) == "queued":
                row = conn.execute(
                    """UPDATE sf_jobs SET status='cancelled',cancel_requested=TRUE,
                         finished_at=clock_timestamp(),updated_at=clock_timestamp()
                       WHERE job_id=%s RETURNING *""",
                    (str(job_id),),
                ).fetchone()
            elif str(row["status"]) == "running":
                row = conn.execute(
                    """UPDATE sf_jobs SET cancel_requested=TRUE,updated_at=clock_timestamp()
                       WHERE job_id=%s RETURNING *""",
                    (str(job_id),),
                ).fetchone()
        return _row_job(row)

    def complete(
        self, job_id: str, result: Mapping[str, Any], *,
        worker_id: str, lease_token: str,
    ) -> Optional[Dict[str, Any]]:
        clean_result = dict(result or {})
        result_bytes = len(_canonical(clean_result))
        if result_bytes > 8 * 1024 * 1024:
            return self.fail(
                job_id, "worker result exceeds 8 MiB", worker_id=worker_id,
                lease_token=lease_token, error_class="result_too_large",
            )
        with self.client.transaction(Scope.global_service_scope()) as conn:
            current = conn.execute(
                """SELECT * FROM sf_jobs WHERE job_id=%s AND status='running'
                   AND lease_owner=%s AND lease_token=%s::uuid FOR UPDATE""",
                (str(job_id), str(worker_id), str(lease_token)),
            ).fetchone()
            if not current:
                return self.get_global(job_id)
            if current["cancel_requested"]:
                return self._finish_locked(
                    conn, current, status="cancelled", outcome="cancelled",
                    error="cancelled by request",
                )
            deadline = current["started_at"] + timedelta(seconds=int(current["timeout_sec"]))
            if deadline <= datetime.now(timezone.utc):
                return self._fail_locked(
                    conn, current, "worker execution timed out", "deadline_expired",
                )
            document = dict(current["document"] or {})
            document["result"] = clean_result
            row = conn.execute(
                """
                UPDATE sf_jobs SET status='completed',document=%s,result_bytes=%s,
                  finished_at=clock_timestamp(),updated_at=clock_timestamp(),
                  leased_until=NULL,lease_owner=NULL,lease_token=NULL,heartbeat_at=NULL,
                  last_error=''
                WHERE job_id=%s RETURNING *
                """,
                (_jsonb(document), result_bytes, current["job_id"]),
            ).fetchone()
            conn.execute(
                """UPDATE sf_job_attempts SET outcome='completed',
                     finished_at=clock_timestamp(),heartbeat_at=clock_timestamp()
                   WHERE job_id=%s AND attempt=%s""",
                (current["job_id"], current["attempts"]),
            )
        return _row_job(row)

    def _finish_locked(
        self, conn: Any, current: Mapping[str, Any], *,
        status: str, outcome: str, error: str,
    ) -> Dict[str, Any]:
        row = conn.execute(
            """
            UPDATE sf_jobs SET status=%s,finished_at=clock_timestamp(),
              updated_at=clock_timestamp(),leased_until=NULL,lease_owner=NULL,
              lease_token=NULL,heartbeat_at=NULL,last_error=%s
            WHERE job_id=%s RETURNING *
            """,
            (status, _clean_error(error), current["job_id"]),
        ).fetchone()
        conn.execute(
            """UPDATE sf_job_attempts SET outcome=%s,error_class=%s,
                 finished_at=clock_timestamp(),heartbeat_at=clock_timestamp()
               WHERE job_id=%s AND attempt=%s""",
            (outcome, outcome, current["job_id"], current["attempts"]),
        )
        return _row_job(row) or {}

    def _fail_locked(
        self, conn: Any, current: Mapping[str, Any], error: str, error_class: str,
    ) -> Dict[str, Any]:
        cancelled = bool(current["cancel_requested"])
        retry = bool(
            not cancelled
            and not current["dangerous"]
            and int(current["attempts"]) < int(current["max_attempts"])
        )
        if cancelled:
            status, outcome, delay = "cancelled", "cancelled", 0
        elif retry:
            status, outcome = "queued", "retry"
            delay = min(300, 2 ** max(0, int(current["attempts"]) - 1))
        else:
            status, outcome, delay = "dead_letter", "dead_letter", 0
        finished_sql = "NULL" if status == "queued" else "clock_timestamp()"
        row = conn.execute(
            f"""
            UPDATE sf_jobs SET status=%s,finished_at={finished_sql},
              available_at=clock_timestamp() + (%s * interval '1 second'),
              updated_at=clock_timestamp(),leased_until=NULL,lease_owner=NULL,
              lease_token=NULL,heartbeat_at=NULL,last_error=%s
            WHERE job_id=%s RETURNING *
            """,
            (status, delay, _clean_error(error), current["job_id"]),
        ).fetchone()
        conn.execute(
            """UPDATE sf_job_attempts SET outcome=%s,error_class=%s,
                 finished_at=clock_timestamp(),heartbeat_at=clock_timestamp()
               WHERE job_id=%s AND attempt=%s""",
            (outcome, str(error_class or "worker_error")[:120], current["job_id"], current["attempts"]),
        )
        return _row_job(row) or {}

    def fail(
        self, job_id: str, error: str, *, worker_id: str,
        lease_token: str, error_class: str = "worker_error",
    ) -> Optional[Dict[str, Any]]:
        with self.client.transaction(Scope.global_service_scope()) as conn:
            current = conn.execute(
                """SELECT * FROM sf_jobs WHERE job_id=%s AND status='running'
                   AND lease_owner=%s AND lease_token=%s::uuid FOR UPDATE""",
                (str(job_id), str(worker_id), str(lease_token)),
            ).fetchone()
            if not current:
                return self.get_global(job_id)
            return self._fail_locked(conn, current, error, error_class)

    def sweep_stale(self, *, limit: int = 1000) -> int:
        changed = 0
        with self.client.transaction(Scope.global_service_scope()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM sf_jobs
                WHERE status='running' AND (
                  leased_until < clock_timestamp()
                  OR started_at + (timeout_sec * interval '1 second') < clock_timestamp()
                )
                ORDER BY leased_until NULLS FIRST
                FOR UPDATE SKIP LOCKED LIMIT %s
                """,
                (max(1, min(10000, int(limit or 1000))),),
            ).fetchall()
            now = datetime.now(timezone.utc)
            for current in rows:
                deadline = current["started_at"] + timedelta(seconds=int(current["timeout_sec"]))
                reason = "deadline_expired" if deadline <= now else "lease_expired"
                self._fail_locked(conn, current, reason.replace("_", " "), reason)
                changed += 1
        return changed

    def metrics(self, *, scope: Optional[Scope] = None) -> Dict[str, Any]:
        active_scope = scope or Scope.global_service_scope()
        with self.client.transaction(active_scope, read_only=True) as conn:
            counts = conn.execute(
                """SELECT worker_class,status,count(*) AS count
                   FROM sf_jobs GROUP BY worker_class,status
                   ORDER BY worker_class,status"""
            ).fetchall()
            queue_age = conn.execute(
                """
                SELECT count(*) AS count,
                  COALESCE(max(EXTRACT(EPOCH FROM (clock_timestamp()-created_at))),0) AS max_age,
                  percentile_cont(ARRAY[0.5,0.95,0.99]) WITHIN GROUP (
                    ORDER BY EXTRACT(EPOCH FROM (clock_timestamp()-created_at))
                  ) AS percentiles
                FROM sf_jobs WHERE status='queued'
                """
            ).fetchone()
            payloads = conn.execute(
                """
                SELECT COALESCE(sum(payload_bytes),0) AS total,
                  COALESCE(max(payload_bytes),0) AS max_bytes,
                  percentile_cont(ARRAY[0.5,0.95,0.99]) WITHIN GROUP (
                    ORDER BY payload_bytes
                  ) AS percentiles
                FROM sf_jobs
                """
            ).fetchone()
            attempts = conn.execute(
                """
                SELECT count(*) AS count,
                  percentile_cont(ARRAY[0.5,0.95,0.99]) WITHIN GROUP (
                    ORDER BY attempts
                  ) AS percentiles
                FROM sf_jobs
                """
            ).fetchone()
            leases = conn.execute(
                """SELECT count(*) FILTER (WHERE status='running') AS active,
                          count(*) FILTER (
                            WHERE status='running' AND leased_until<clock_timestamp()
                          ) AS expired
                   FROM sf_jobs"""
            ).fetchone()
            fairness = conn.execute(
                """SELECT worker_class,min(served_count) AS minimum,
                          max(served_count) AS maximum,sum(served_count) AS total
                   FROM sf_queue_workspace_state GROUP BY worker_class
                   ORDER BY worker_class"""
            ).fetchall()

        def pct(row: Mapping[str, Any], key: str = "percentiles") -> Dict[str, float]:
            values = list(row.get(key) or [0, 0, 0])
            values += [0] * (3 - len(values))
            return {"p50": float(values[0] or 0), "p95": float(values[1] or 0), "p99": float(values[2] or 0)}

        grouped: Dict[str, Dict[str, int]] = {}
        for row in counts:
            grouped.setdefault(str(row["worker_class"]), {})[str(row["status"])] = int(row["count"])
        return {
            "counts": grouped,
            "queue_age_seconds": {
                "count": int(queue_age["count"] or 0),
                "max": float(queue_age["max_age"] or 0),
                **pct(queue_age),
            },
            "attempts": {"count": int(attempts["count"] or 0), **pct(attempts)},
            "leases": {
                "active": int(leases["active"] or 0),
                "expired": int(leases["expired"] or 0),
            },
            "payload_bytes": {
                "total": int(payloads["total"] or 0),
                "max": int(payloads["max_bytes"] or 0),
                **pct(payloads),
            },
            "fairness": [dict(row) for row in fairness],
        }


def get_queue() -> ProductionQueue:
    global _QUEUE
    with _QUEUE_LOCK:
        if _QUEUE is None:
            _QUEUE = ProductionQueue(get_client(production=True))
        return _QUEUE


def reset_for_tests() -> None:
    global _QUEUE
    with _QUEUE_LOCK:
        _QUEUE = None


def consume_rate_limit(
    subject: str, action_class: str, *, limit: int, period_sec: int = 60,
    client: Optional[PostgresClient] = None,
) -> Dict[str, Any]:
    clean_action = str(action_class or "").strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_.:-]{1,79}", clean_action):
        raise ProductionQueueError("Invalid shared rate-limit class.")
    active_limit = max(1, min(10_000_000, int(limit or 1)))
    period = max(1, min(3600, int(period_sec or 60)))
    now_epoch = time.time()
    start_epoch = math.floor(now_epoch / period) * period
    window = datetime.fromtimestamp(start_epoch, timezone.utc)
    expires = window + timedelta(seconds=period * 2)
    subject_hash = hashlib.sha256(str(subject or "anonymous").encode("utf-8")).hexdigest()
    active_client = client or get_client(production=True)
    with active_client.transaction(Scope.global_service_scope()) as conn:
        row = conn.execute(
            """
            INSERT INTO sf_rate_limit_buckets(
              subject_hash,action_class,window_started_at,request_count,expires_at
            ) VALUES(%s,%s,%s,1,%s)
            ON CONFLICT(subject_hash,action_class,window_started_at)
            DO UPDATE SET request_count=sf_rate_limit_buckets.request_count+1,
                          expires_at=EXCLUDED.expires_at
            RETURNING request_count
            """,
            (subject_hash, clean_action, window, expires),
        ).fetchone()
        conn.execute(
            "DELETE FROM sf_rate_limit_buckets WHERE expires_at<clock_timestamp()"
        )
    count = int(row["request_count"])
    retry_after = max(1, int(math.ceil(start_epoch + period - now_epoch)))
    return {
        "allowed": count <= active_limit,
        "count": count,
        "limit": active_limit,
        "retry_after": retry_after,
    }


def reserve_idempotency(
    *, scope: Scope, operation: str, key: str, request_hash: str,
    ttl_sec: int = 3600, client: Optional[PostgresClient] = None,
) -> Dict[str, Any]:
    clean_operation = str(operation or "").strip().lower()
    if not _SAFE_OPERATION.fullmatch(clean_operation) or not _SAFE_KEY.fullmatch(str(key or "")):
        raise ProductionQueueError("Invalid shared idempotency identity.")
    if not re.fullmatch(r"[0-9a-f]{64}", str(request_hash or "")):
        raise ProductionQueueError("Invalid idempotency request hash.")
    key_hash = hashlib.sha256(str(key).encode("utf-8")).hexdigest()
    expiry = datetime.now(timezone.utc) + timedelta(seconds=max(30, min(86400, int(ttl_sec))))
    active_client = client or get_client(production=True)
    with active_client.transaction(scope) as conn:
        inserted = conn.execute(
            """
            INSERT INTO sf_idempotency_keys(
              workspace_id,operation,key_hash,request_hash,state,expires_at
            ) VALUES(%s,%s,%s,%s,'reserved',%s)
            ON CONFLICT(workspace_id,operation,key_hash) DO NOTHING
            RETURNING *
            """,
            (scope.workspace_id, clean_operation, key_hash, request_hash, expiry),
        ).fetchone()
        row = inserted or conn.execute(
            """SELECT * FROM sf_idempotency_keys
               WHERE workspace_id=%s AND operation=%s AND key_hash=%s FOR UPDATE""",
            (scope.workspace_id, clean_operation, key_hash),
        ).fetchone()
        if str(row["request_hash"]) != str(request_hash):
            raise QueueIdempotencyConflict(
                "Idempotency key was used with a different request."
            )
    return {
        "reserved": bool(inserted),
        "replay": not bool(inserted),
        "state": str(row["state"]),
        "response": dict(row["response"] or {}),
    }


def complete_idempotency(
    *, scope: Scope, operation: str, key: str, request_hash: str,
    response: Mapping[str, Any], failed: bool = False,
    client: Optional[PostgresClient] = None,
) -> Dict[str, Any]:
    clean_operation = str(operation or "").strip().lower()
    key_hash = hashlib.sha256(str(key).encode("utf-8")).hexdigest()
    active_client = client or get_client(production=True)
    with active_client.transaction(scope) as conn:
        row = conn.execute(
            """
            UPDATE sf_idempotency_keys SET state=%s,response=%s,
              updated_at=clock_timestamp()
            WHERE workspace_id=%s AND operation=%s AND key_hash=%s
              AND request_hash=%s
            RETURNING *
            """,
            (
                "failed" if failed else "completed", _jsonb(dict(response or {})),
                scope.workspace_id, clean_operation, key_hash, request_hash,
            ),
        ).fetchone()
    if not row:
        raise QueueIdempotencyConflict("Idempotency reservation is missing or mismatched.")
    return {"state": str(row["state"]), "response": dict(row["response"] or {})}


def enqueue(
    kind: str, payload: Optional[Dict[str, Any]] = None, *, priority: int = 100,
    max_attempts: int = 1, timeout_sec: int = 300, user_id: Any = "",
    workspace_id: str = "", job_id: str = "", idempotency_key: str = "",
    dangerous: bool = False,
) -> Dict[str, Any]:
    scope = Scope(user_id=int(user_id or 0), workspace_id=str(workspace_id or ""))
    key = str(idempotency_key or job_id or "").strip()
    if not key:
        raise ProductionQueueError("Production enqueue requires an idempotency key.")
    return get_queue().enqueue(
        kind, payload or {}, scope=scope, priority=priority,
        max_attempts=max_attempts, timeout_sec=timeout_sec,
        idempotency_key=key, job_id=job_id, dangerous=dangerous,
    )


def enqueue_ai_message(
    message: str, *, request_id: str, conversation_id: str, agent: str,
    scope: Dict[str, Any], mirror_to_telegram: bool = True,
    source: str = "app",
    timeout_sec: int = 600,
) -> Dict[str, Any]:
    user_id = int(scope.get("user_id") or 0)
    workspace_id = str(scope.get("workspace_id") or "")
    request_key = str(request_id or "").strip()[:120]
    if not request_key:
        request_key = "air_" + secrets.token_hex(16)
    payload = {
        "message": str(message or "")[:6001],
        "request_id": request_key,
        "conversation_id": str(conversation_id or "default")[:160],
        "agent": str(agent or "")[:80],
        "source": str(source or "app")[:40],
        "mirror_to_telegram": bool(mirror_to_telegram),
        "scope": dict(scope or {}),
    }
    return enqueue(
        "ai_orchestrator", payload, priority=50, max_attempts=2,
        timeout_sec=max(30, min(1800, int(timeout_sec or 600))),
        user_id=user_id, workspace_id=workspace_id,
        idempotency_key=f"ai:{user_id}:{request_key}",
    )


def enqueue_chart_batch(
    requests: list[Dict[str, Any]], *, scope: Dict[str, Any],
    runtime_dir: str = "", timeout_sec: int = 60,
) -> Dict[str, Any]:
    from . import market_data
    user_id = int(scope.get("user_id") or 0)
    workspace_id = str(scope.get("workspace_id") or "")
    source_signature = market_data.snapshot_source_signature()
    identity = {
        "workspace_id": workspace_id,
        "requests": requests,
        "source_signature": source_signature,
    }
    key = "chart:" + _sha256(identity)[:40]
    payload = {
        "requests": [dict(row) for row in requests if isinstance(row, dict)][:64],
        "scope": dict(scope or {}),
        "runtime_dir": str(runtime_dir or ""),
        "source_signature": source_signature,
    }
    return enqueue(
        "chart_batch", payload, priority=80, max_attempts=2,
        timeout_sec=max(10, min(180, int(timeout_sec or 60))),
        user_id=user_id, workspace_id=workspace_id, idempotency_key=key,
    )


def get(job_id: str, *, workspace_id: str = "", user_id: Any = 0) -> Optional[Dict[str, Any]]:
    if not workspace_id:
        return None
    return get_queue().get(
        job_id, scope=Scope(user_id=int(user_id or 0), workspace_id=str(workspace_id)),
    )


def list_jobs(
    status: str = "", limit: int = 100, *, workspace_id: str = "", user_id: Any = 0,
) -> Dict[str, Any]:
    scope = Scope(user_id=int(user_id or 0), workspace_id=str(workspace_id or ""))
    rows = get_queue().list(scope=scope, status=status, limit=limit)
    return {"jobs": rows, "counts": get_queue().counts(scope=scope)}


def cancel(job_id: str, *, workspace_id: str = "", user_id: Any = 0) -> Dict[str, Any]:
    scope = Scope(user_id=int(user_id or 0), workspace_id=str(workspace_id or ""))
    row = get_queue().cancel(job_id, scope=scope)
    return (
        {"ok": True, "job": row}
        if row else {"ok": False, "reason": "not_found", "worker_job_id": str(job_id)}
    )


def run_once(worker_class: str, *, worker_id: str = "") -> Optional[Dict[str, Any]]:
    from . import local_worker

    active_worker = str(worker_id or f"worker-{os.getpid()}-{threading.get_ident()}")[:160]
    queue = get_queue()
    queue.sweep_stale(limit=100)
    job = queue.claim(worker_class, worker_id=active_worker)
    if not job:
        return None
    job_id = str(job["job_id"])
    lease_token = str(job["lease_token"])
    lease_stop = threading.Event()
    lease_lost = threading.Event()

    def cancelled() -> bool:
        return queue.cancel_requested(
            job_id, worker_id=active_worker, lease_token=lease_token,
        )

    def heartbeat() -> None:
        if queue.heartbeat(
            job_id, worker_id=active_worker, lease_token=lease_token,
        ):
            return
        lease_lost.set()
        if cancelled():
            raise local_worker.WorkerCancelled("cancelled by request")
        raise local_worker.WorkerTimedOut("Production worker lease lost")

    def keep_lease() -> None:
        while not lease_stop.wait(5.0):
            try:
                heartbeat()
            except Exception:
                lease_lost.set()
                return

    lease_thread = threading.Thread(
        target=keep_lease, name=f"production-lease-{job_id[:24]}", daemon=True,
    )
    lease_thread.start()
    try:
        result = local_worker._execute(job, heartbeat=heartbeat, cancelled=cancelled)
        if lease_lost.is_set():
            raise local_worker.WorkerTimedOut("Production worker lease lost")
        heartbeat()
        return queue.complete(
            job_id, result, worker_id=active_worker, lease_token=lease_token,
        )
    except local_worker.WorkerCancelled as exc:
        return queue.fail(
            job_id, str(exc), worker_id=active_worker, lease_token=lease_token,
            error_class="cancelled",
        )
    except local_worker.WorkerTimedOut as exc:
        return queue.fail(
            job_id, str(exc), worker_id=active_worker, lease_token=lease_token,
            error_class="timeout",
        )
    except Exception as exc:  # noqa: BLE001 - persisted without traceback/secrets
        return queue.fail(
            job_id, str(exc), worker_id=active_worker, lease_token=lease_token,
            error_class=type(exc).__name__,
        )
    finally:
        lease_stop.set()
        lease_thread.join(timeout=1.0)


class BackgroundAICoordinator:
    """Own the singleton legacy schedulers from the Production worker role.

    These schedulers still coordinate durable/local research state, but they
    must never run in every API process.  A PostgreSQL lease makes one worker
    instance authoritative and stops provider-facing threads if the lease is
    lost.
    """

    LEASE_NAME = "background-ai-coordinator"

    def __init__(self, client: PostgresClient) -> None:
        self.client = client
        host = os.uname().nodename if hasattr(os, "uname") else "host"
        self.owner_id = f"{host}:{os.getpid()}:background-ai"[:160]
        self.lease_token = ""
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.emitter = None
        self.active = False

    def _acquire(self, *, ttl_sec: int = 30) -> bool:
        token = str(uuid.uuid4())
        with self.client.transaction(Scope.global_service_scope()) as conn:
            row = conn.execute(
                """
                INSERT INTO sf_service_leases(
                  lease_name,owner_id,lease_token,leased_until
                ) VALUES(%s,%s,%s::uuid,
                         clock_timestamp()+(%s*interval '1 second'))
                ON CONFLICT(lease_name) DO UPDATE SET
                  owner_id=EXCLUDED.owner_id,lease_token=EXCLUDED.lease_token,
                  leased_until=EXCLUDED.leased_until,
                  heartbeat_at=clock_timestamp()
                WHERE sf_service_leases.leased_until < clock_timestamp()
                   OR sf_service_leases.owner_id=EXCLUDED.owner_id
                RETURNING lease_token
                """,
                (self.LEASE_NAME, self.owner_id, token, int(ttl_sec)),
            ).fetchone()
        if not row:
            return False
        self.lease_token = str(row["lease_token"])
        return True

    def _renew(self, *, ttl_sec: int = 30) -> bool:
        with self.client.transaction(Scope.global_service_scope()) as conn:
            row = conn.execute(
                """
                UPDATE sf_service_leases SET
                  leased_until=clock_timestamp()+(%s*interval '1 second'),
                  heartbeat_at=clock_timestamp()
                WHERE lease_name=%s AND owner_id=%s
                  AND lease_token=%s::uuid
                  AND leased_until >= clock_timestamp()
                RETURNING lease_name
                """,
                (
                    int(ttl_sec), self.LEASE_NAME, self.owner_id,
                    self.lease_token,
                ),
            ).fetchone()
        return bool(row)

    def _release(self) -> None:
        if not self.lease_token:
            return
        with self.client.transaction(Scope.global_service_scope()) as conn:
            conn.execute(
                """DELETE FROM sf_service_leases
                   WHERE lease_name=%s AND owner_id=%s
                     AND lease_token=%s::uuid""",
                (self.LEASE_NAME, self.owner_id, self.lease_token),
            )

    @staticmethod
    def _stop_components() -> None:
        from . import news_refresh, vitek
        from .ai_lab import chief_agent, stale_sweep

        chief_agent.stop_background_worker()
        vitek.stop_background_worker()
        news_refresh.stop_background_refresher()
        stale_sweep.stop_background_sweeper()

    def _lease_loop(self) -> None:
        from . import observability

        while not self.stop_event.wait(10.0):
            try:
                if self._renew(ttl_sec=30):
                    continue
            except StorageError:
                pass
            observability.event(
                "background_ai", "coordinator_lease_lost",
                severity="critical",
                payload={"owner": "worker", "action": "provider_threads_stopped"},
            )
            self.active = False
            self.stop_event.set()
            self._stop_components()
            return

    def start(self) -> bool:
        if self.active:
            return True
        if not self._acquire(ttl_sec=30):
            return False
        from . import news_refresh, observability, vitek
        from .ai_lab import chief_agent, stale_sweep

        try:
            stale_sweep.start_background_sweeper(interval_sec=1800, ttl_hours=6.0)
            news_refresh.start_background_refresher()
            chief_agent.start_background_worker(interval_sec=30)
            vitek.start_background_worker(interval_sec=1)
            self.stop_event.clear()
            self.active = True
            self.emitter = observability.HeartbeatEmitter(
                "background_ai", interval_sec=10,
                details=lambda: {"lease": "active", "scoped_ai": True},
            )
            self.emitter.start()
            self.thread = threading.Thread(
                target=self._lease_loop,
                name="sf-background-ai-lease", daemon=True,
            )
            self.thread.start()
            return True
        except Exception:
            self._stop_components()
            try:
                self._release()
            except StorageError:
                pass
            self.lease_token = ""
            self.active = False
            raise

    def stop(self) -> None:
        self.stop_event.set()
        self._stop_components()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=12.0)
        if self.emitter:
            self.emitter.stop()
        try:
            self._release()
        except StorageError:
            pass
        self.lease_token = ""
        self.active = False


class WorkerService:
    def __init__(self, classes: Iterable[str], *, poll_ms: int = 250) -> None:
        selected = list(dict.fromkeys(str(value).strip() for value in classes if str(value).strip()))
        if not selected or any(value not in DEFAULT_WORKER_CLASSES for value in selected):
            raise ProductionQueueError("At least one valid Production worker class is required.")
        self.classes = selected
        self.poll_sec = max(0.05, min(10.0, int(poll_ms or 250) / 1000.0))
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self.background_coordinator: Optional[BackgroundAICoordinator] = None

    def _loop(self, worker_class: str, slot: int) -> None:
        worker_id = f"{os.uname().nodename if hasattr(os, 'uname') else 'host'}:{os.getpid()}:{worker_class}:{slot}"
        while not self.stop_event.is_set():
            try:
                row = run_once(worker_class, worker_id=worker_id)
                if row is None:
                    self.stop_event.wait(self.poll_sec)
            except StorageUnavailableError:
                self.stop_event.wait(max(1.0, self.poll_sec))
            except StorageError:
                self.stop_event.wait(self.poll_sec)

    def start(self) -> int:
        configs = get_queue().class_configs()
        from . import runtime_env

        if (
            "maintenance" in self.classes
            and runtime_env.is_production()
            and runtime_env.environment_explicit()
        ):
            self.background_coordinator = BackgroundAICoordinator(
                get_queue().client,
            )
            self.background_coordinator.start()
        for worker_class in self.classes:
            config = configs[worker_class]
            requested_name = "STRATFORGE_WORKER_CONCURRENCY_" + worker_class.upper()
            requested = int(os.environ.get(requested_name) or config["max_concurrency"])
            concurrency = max(1, min(int(config["max_concurrency"]), requested))
            for slot in range(concurrency):
                thread = threading.Thread(
                    target=self._loop, args=(worker_class, slot),
                    name=f"sf-{worker_class}-{slot}", daemon=True,
                )
                thread.start()
                self.threads.append(thread)
        return len(self.threads)

    def stop(self, *, grace_sec: int = 60) -> bool:
        self.stop_event.set()
        if self.background_coordinator:
            self.background_coordinator.stop()
        deadline = time.monotonic() + max(1, min(600, int(grace_sec or 60)))
        for thread in self.threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        return not any(thread.is_alive() for thread in self.threads)


def readiness_status() -> Dict[str, Any]:
    try:
        queue = get_queue()
        configs = queue.class_configs()
        if set(configs) != set(DEFAULT_WORKER_CLASSES):
            return {"ok": False, "code": "worker_class_config_incomplete"}
        metrics = queue.metrics()
        if int(metrics["leases"]["expired"]) > 0:
            return {"ok": False, "code": "worker_lease_expired"}
        with queue.client.transaction(
            Scope.global_service_scope(), read_only=True,
        ) as conn:
            rows = conn.execute(
                """SELECT DISTINCT ON (service_role)
                         service_role,status,heartbeat_at,
                         EXTRACT(EPOCH FROM (
                           clock_timestamp()-heartbeat_at
                         )) AS age_sec
                   FROM sf_service_heartbeats
                   WHERE service_role IN ('worker','background_ai')
                   ORDER BY service_role,heartbeat_at DESC"""
            ).fetchall()
        services = {
            str(row["service_role"]): {
                "status": str(row["status"]),
                "age_sec": max(0.0, float(row.get("age_sec") or 0.0)),
            }
            for row in rows
        }
        for role in ("worker", "background_ai"):
            state = services.get(role)
            if state is None:
                return {
                    "ok": False, "code": f"{role}_heartbeat_missing",
                    "services": services,
                }
            if state["status"] != "healthy" or state["age_sec"] > 45.0:
                return {
                    "ok": False, "code": f"{role}_heartbeat_stale",
                    "services": services,
                }
        return {"ok": True, "code": "ok", "services": services}
    except StorageError:
        return {"ok": False, "code": "queue_unavailable"}
    except Exception:
        return {"ok": False, "code": "queue_schema_invalid"}


def status() -> Dict[str, Any]:
    ready = readiness_status()
    result: Dict[str, Any] = {
        "backend": "postgresql",
        "authoritative": True,
        "process_alive": bool(ready.get("ok")),
        "supervisor_alive": bool(ready.get("ok")),
        "max_concurrency": sum(
            row["max_concurrency"] for row in DEFAULT_WORKER_CLASSES.values()
        ),
        "readiness": ready,
    }
    if ready.get("ok"):
        result["metrics"] = get_queue().metrics()
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--classes", default=",".join(DEFAULT_WORKER_CLASSES),
        help="comma-separated Production worker classes",
    )
    parser.add_argument("--poll-ms", type=int, default=250)
    parser.add_argument("--shutdown-grace-sec", type=int, default=60)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    from . import observability, runtime_env, storage_router

    args = _parser().parse_args(argv)
    config = runtime_env.assert_startup_safe()
    if config.environment != runtime_env.PRODUCTION:
        raise SystemExit("Production workers refuse to run outside Production.")
    if config.deployment_role not in {"worker", "all-in-one"}:
        raise SystemExit("Production worker service requires deployment role worker/all-in-one.")
    storage_router.assert_production_storage_safe()
    classes = [value.strip() for value in str(args.classes).split(",") if value.strip()]
    service = WorkerService(classes, poll_ms=args.poll_ms)
    stopped = threading.Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        stopped.set()

    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(stop_signal, request_stop)
        except (AttributeError, OSError, ValueError):
            pass
    emitter = observability.HeartbeatEmitter(
        "worker", interval_sec=10,
        details=lambda: get_queue().metrics(),
    )
    count = service.start()
    emitter.start()
    print(f"[stratforge-worker] started threads={count} classes={','.join(classes)}")
    try:
        while not stopped.wait(1.0):
            pass
    finally:
        emitter.stop()
    graceful = service.stop(grace_sec=args.shutdown_grace_sec)
    print(f"[stratforge-worker] stopped graceful={str(graceful).lower()}")
    return 0 if graceful else 3


if __name__ == "__main__":
    raise SystemExit(main())
