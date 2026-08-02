"""Structured, redacted operational telemetry for Development and Production.

The module deliberately keeps request metrics in-process and stores only
low-cardinality service/alert state in PostgreSQL. Prompts, tokens, cookies,
Telegram payloads, market bars and absolute client paths are never copied into
operational logs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from . import runtime_env
from .production_storage import Scope, StorageError, get_client
from .production_storage.core import _jsonb


_LOCK = threading.RLock()
_HTTP_COUNTS: Dict[str, int] = defaultdict(int)
_HTTP_LATENCIES_MS: deque[float] = deque(maxlen=4096)
_COMPONENT_COUNTS: Dict[str, int] = defaultdict(int)
_LOCAL_HEARTBEATS: Dict[str, Dict[str, Any]] = {}
_SECRET_KEY = re.compile(
    r"(?:^|[_-])(?:token|secret|password|cookie|authorization|api[_-]?key|"
    r"private[_-]?key|pairing|enrollment|csrf|session[_-]?id)(?:$|[_-])",
    re.IGNORECASE,
)
_SAFE_COUNT_KEYS = {
    "input_tokens", "output_tokens", "cached_input_tokens", "total_tokens",
    "max_output_tokens", "cache_miss_tokens", "request_count", "token_count",
}
REQUIRED_PRODUCTION_SERVICE_ROLES = ("api", "worker", "telegram", "background_ai")
_BEARER = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_TOKENISH = re.compile(r"\b(?:sfc_v1_|sf_session_|ghp_|sk-)[A-Za-z0-9._-]{8,}\b")
_WINDOWS_PATH = re.compile(r"(?i)\b[A-Z]:\\[^\r\n\t\"']+")
_UNIX_PRIVATE_PATH = re.compile(r"(?<![A-Za-z0-9])/(?:home|root|Users)/[^\s\"']+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _instance_id() -> str:
    try:
        configured = runtime_env.deployment_config().instance_id
    except Exception:
        configured = ""
    host = re.sub(r"[^A-Za-z0-9.-]+", "-", socket.gethostname()).strip("-")
    return str(configured or f"local-{host or 'host'}-{os.getpid()}")[:160]


def redact(value: Any, *, key: str = "", depth: int = 0) -> Any:
    """Return a bounded JSON-safe value without secrets, PII-heavy text or paths."""
    if depth > 7:
        return "[depth-limit]"
    clean_key = str(key or "").strip().lower()
    if clean_key not in _SAFE_COUNT_KEYS and _SECRET_KEY.search(clean_key):
        return "[redacted]"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in {float("inf"), float("-inf")} else None
    if isinstance(value, Mapping):
        return {
            str(name)[:100]: redact(item, key=str(name), depth=depth + 1)
            for name, item in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple, set)):
        return [redact(item, depth=depth + 1) for item in list(value)[:100]]
    text = " ".join(str(value).replace("\x00", " ").split())[:2000]
    text = _BEARER.sub("[authorization-redacted]", text)
    text = _TOKENISH.sub("[token-redacted]", text)
    if runtime_env.is_production():
        text = _WINDOWS_PATH.sub("[private-path]", text)
        text = _UNIX_PRIVATE_PATH.sub("[private-path]", text)
    return text


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False, default=str,
    ).encode("utf-8")


def event(
    component: str,
    event_type: str,
    *,
    severity: str = "info",
    payload: Optional[Mapping[str, Any]] = None,
    workspace_id: str = "",
    user_id: int = 0,
    fingerprint: str = "",
) -> str:
    """Emit one safe event and persist only the Production operational index."""
    safe_component = re.sub(r"[^a-z0-9_.:-]+", "_", str(component).lower())[:80] or "app"
    safe_type = re.sub(r"[^a-z0-9_.:-]+", "_", str(event_type).lower())[:120] or "event"
    level = str(severity or "info").lower()
    if level not in {"info", "warning", "critical"}:
        level = "warning"
    clean = redact(dict(payload or {}))
    identity = fingerprint or hashlib.sha256(
        _canonical({"component": safe_component, "event_type": safe_type, "workspace_id": workspace_id})
    ).hexdigest()
    event_id = "ope_" + uuid.uuid4().hex
    row = {
        "timestamp_utc": _now(), "event_id": event_id,
        "component": safe_component, "event_type": safe_type,
        "severity": level, "payload": clean,
    }
    with _LOCK:
        _COMPONENT_COUNTS[f"{safe_component}:{safe_type}:{level}"] += 1
    # Production service logs are JSON and secret-safe. Development stays quiet
    # unless explicitly requested so existing local console workflows remain readable.
    if runtime_env.is_production() or os.environ.get("STRATFORGE_STRUCTURED_LOG_STDOUT") == "1":
        print(json.dumps(row, ensure_ascii=False, separators=(",", ":")), flush=True)
    if runtime_env.is_production() and runtime_env.environment_explicit():
        try:
            scope = Scope.global_service_scope()
            with get_client().transaction(scope) as conn:
                persisted = conn.execute(
                    """
                    INSERT INTO sf_operational_events(
                      event_id,workspace_id,user_id,component,event_type,severity,fingerprint,payload
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (fingerprint) WHERE status='open' DO UPDATE SET
                      severity=EXCLUDED.severity,payload=EXCLUDED.payload,
                      updated_at=clock_timestamp()
                    RETURNING event_id
                    """,
                    (
                        event_id, str(workspace_id or "") or None, int(user_id or 0) or None,
                        safe_component, safe_type, level, identity, _jsonb(clean),
                    ),
                ).fetchone()
                if persisted:
                    event_id = str(persisted["event_id"])
        except StorageError:
            # Telemetry must never turn a successful user request into a failure.
            pass
    return event_id


def record_http(method: str, path: str, status: int, elapsed_ms: float) -> None:
    route = str(path or "/").split("?", 1)[0]
    # Collapse IDs to keep metric cardinality bounded.
    route = re.sub(r"/(?:[A-Za-z]+_)?[A-Za-z0-9-]{12,}(?=/|$)", "/:id", route)
    family = f"{str(method).upper()} {route[:160]} {int(status) // 100}xx"
    with _LOCK:
        _HTTP_COUNTS[family] += 1
        _HTTP_LATENCIES_MS.append(max(0.0, min(float(elapsed_ms), 600_000.0)))


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def metrics() -> Dict[str, Any]:
    with _LOCK:
        latencies = list(_HTTP_LATENCIES_MS)
        counts = dict(_HTTP_COUNTS)
        components = dict(_COMPONENT_COUNTS)
    return {
        "http": {
            "requests": sum(counts.values()), "families": counts,
            "latency_ms": {
                "p50": round(_percentile(latencies, 0.50), 3),
                "p95": round(_percentile(latencies, 0.95), 3),
                "p99": round(_percentile(latencies, 0.99), 3),
                "max": round(max(latencies) if latencies else 0.0, 3),
                "samples": len(latencies),
            },
        },
        "events": components,
    }


def heartbeat(
    service_role: str,
    *,
    instance_id: str = "",
    status: str = "healthy",
    details: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    role = re.sub(r"[^a-z0-9_.:-]+", "_", str(service_role).lower())[:80]
    instance = str(instance_id or _instance_id())[:160]
    state = status if status in {"starting", "healthy", "degraded", "stopping", "failed"} else "degraded"
    clean = redact(dict(details or {}))
    public = {
        "service_role": role, "instance_id": instance, "status": state,
        "heartbeat_at_utc": _now(), "details": clean,
    }
    if runtime_env.is_production() and runtime_env.environment_explicit():
        with get_client().transaction(Scope.global_service_scope()) as conn:
            conn.execute(
                """
                INSERT INTO sf_service_heartbeats(service_role,instance_id,status,document)
                VALUES(%s,%s,%s,%s)
                ON CONFLICT(service_role,instance_id) DO UPDATE SET
                  status=EXCLUDED.status,heartbeat_at=clock_timestamp(),document=EXCLUDED.document
                """,
                (role, instance, state, _jsonb(clean)),
            )
    else:
        with _LOCK:
            _LOCAL_HEARTBEATS[f"{role}:{instance}"] = dict(public)
    return public


class HeartbeatEmitter:
    """Small supervised heartbeat loop shared by API/worker/Telegram roles."""

    def __init__(self, role: str, *, interval_sec: float = 10.0, details=None) -> None:
        self.role = str(role)
        self.interval_sec = max(2.0, min(float(interval_sec), 60.0))
        self.details = details
        self.instance_id = _instance_id()
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def _details(self) -> Dict[str, Any]:
        try:
            value = self.details() if callable(self.details) else self.details
            return dict(value or {})
        except Exception as exc:
            return {"details_error": exc.__class__.__name__}

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        heartbeat(self.role, instance_id=self.instance_id, status="starting", details=self._details())
        self.thread = threading.Thread(target=self._run, name=f"sf-heartbeat-{self.role}", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval_sec):
            try:
                heartbeat(self.role, instance_id=self.instance_id, details=self._details())
            except StorageError:
                pass

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=max(2.0, self.interval_sec + 1.0))
        try:
            heartbeat(self.role, instance_id=self.instance_id, status="stopping", details=self._details())
        except StorageError:
            pass


def service_status(*, stale_after_sec: int = 45) -> Dict[str, Any]:
    threshold = max(5, min(int(stale_after_sec), 3600))
    if not (runtime_env.is_production() and runtime_env.environment_explicit()):
        with _LOCK:
            rows = list(_LOCAL_HEARTBEATS.values())
        return {"services": rows, "stale_after_sec": threshold, "production": False}
    with get_client().transaction(Scope.global_service_scope(), read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT ON (service_role) service_role,instance_id,status,
              heartbeat_at,document,
              EXTRACT(EPOCH FROM (clock_timestamp()-heartbeat_at)) AS age_sec
            FROM sf_service_heartbeats
            ORDER BY service_role,heartbeat_at DESC
            """
        ).fetchall()
    services = []
    for source in rows:
        age = max(0.0, float(source.get("age_sec") or 0.0))
        services.append({
            "service_role": str(source["service_role"]),
            "instance_id": str(source["instance_id"]),
            "status": str(source["status"]),
            "heartbeat_at_utc": source["heartbeat_at"].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "age_sec": round(age, 3), "fresh": age <= threshold,
            "details": redact(dict(source.get("document") or {})),
        })
    return {"services": services, "stale_after_sec": threshold, "production": True}


def dashboard() -> Dict[str, Any]:
    result = {"ok": True, "generated_at_utc": _now(), "metrics": metrics()}
    try:
        result["service_health"] = service_status()
        if runtime_env.is_production() and runtime_env.environment_explicit():
            with get_client().transaction(Scope.global_service_scope(), read_only=True) as conn:
                result["queues"] = dict(conn.execute(
                    """
                    SELECT
                      (SELECT count(*) FROM sf_jobs WHERE status='queued') AS jobs_queued,
                      (SELECT count(*) FROM sf_jobs WHERE status='running') AS jobs_running,
                      (SELECT count(*) FROM sf_telegram_updates WHERE status='queued') AS telegram_inbox,
                      (SELECT count(*) FROM sf_telegram_outbox WHERE status='queued') AS telegram_outbox,
                      (SELECT count(*) FROM sf_jobs WHERE status='dead_letter') AS jobs_dead_letter,
                      (SELECT count(*) FROM sf_telegram_updates WHERE status='dead_letter') AS telegram_inbox_dead_letter,
                      (SELECT count(*) FROM sf_telegram_outbox WHERE status='dead_letter') AS telegram_outbox_dead_letter,
                      (SELECT count(*) FROM sf_operational_events WHERE status='open' AND severity='critical') AS critical_alerts
                    """
                ).fetchone())
                result["connectors"] = dict(conn.execute(
                    """
                    SELECT count(*) FILTER (WHERE status='online') AS online,
                           count(*) FILTER (WHERE status='offline') AS offline,
                           count(*) FILTER (WHERE status IN ('revoked','blocked','failed')) AS blocked
                    FROM sf_connector_installations
                    """
                ).fetchone())
                result["connector_sessions"] = dict(conn.execute(
                    """
                    SELECT
                      count(*) FILTER (
                        WHERE revoked_at IS NULL
                          AND expires_at>clock_timestamp()
                      ) AS active,
                      count(*) FILTER (
                        WHERE revoked_at IS NULL
                          AND expires_at<=clock_timestamp()
                      ) AS expired,
                      count(*) FILTER (WHERE revoked_at IS NOT NULL) AS revoked
                    FROM sf_connector_sessions
                    """
                ).fetchone())
                result["ai_usage"] = dict(conn.execute(
                    """
                    SELECT
                      count(*) FILTER (
                        WHERE occurred_at>=date_trunc('day',clock_timestamp())
                          AND status IN ('success','error')
                      ) AS billed_requests_today,
                      COALESCE(sum(cost_usd) FILTER (
                        WHERE occurred_at>=date_trunc('day',clock_timestamp())
                          AND status IN ('success','error')
                      ),0) AS cost_today_usd,
                      count(*) FILTER (WHERE status='blocked') AS blocked_total
                    FROM sf_ai_usage_events
                    """
                ).fetchone())
                result["alerts"] = [
                    dict(row) for row in conn.execute(
                        """
                        SELECT event_id,component,event_type,severity,status,
                               payload,occurred_at,updated_at
                        FROM sf_operational_events
                        WHERE status='open'
                        ORDER BY
                          CASE severity WHEN 'critical' THEN 0
                                        WHEN 'warning' THEN 1 ELSE 2 END,
                          occurred_at DESC
                        LIMIT 100
                        """
                    ).fetchall()
                ]
    except StorageError:
        result["ok"] = False
        result["storage"] = {"ok": False, "code": "storage_unavailable"}
    return redact(result)


def _alert_fingerprint(service_role: str, condition: str) -> str:
    return hashlib.sha256(
        f"service:{service_role}:{condition}".encode("utf-8")
    ).hexdigest()


def _resolve_alert(fingerprint: str) -> str:
    if not (runtime_env.is_production() and runtime_env.environment_explicit()):
        return ""
    with get_client().transaction(Scope.global_service_scope()) as conn:
        row = conn.execute(
            """UPDATE sf_operational_events
               SET status='resolved',updated_at=clock_timestamp()
               WHERE fingerprint=%s AND status='open'
               RETURNING event_id""",
            (fingerprint,),
        ).fetchone()
    return str(row["event_id"]) if row else ""


def _notify_service_alert(service_role: str, condition: str, *,
                          resolved: bool = False, incident_id: str = "") -> None:
    if not (runtime_env.is_production() and runtime_env.environment_explicit()):
        return
    try:
        from . import production_telegram

        state = "восстановлен" if resolved else "неготов"
        production_telegram.enqueue_text(
            f"⚠️ <b>Production service {state}</b>\n"
            f"Role: <code>{service_role}</code>\n"
            f"Condition: <code>{condition}</code>",
            dedupe_key=(
                f"service-alert:{service_role}:{condition}:"
                f"{'resolved' if resolved else 'open'}:{incident_id or 'legacy'}"
            ),
        )
    except Exception:
        pass


def evaluate_alerts(*, stale_after_sec: int = 45) -> Dict[str, Any]:
    raised = []
    resolved = []
    status = service_status(stale_after_sec=stale_after_sec)
    services = {
        str(row.get("service_role") or ""): row
        for row in status.get("services") or []
    }
    expected_roles = (
        REQUIRED_PRODUCTION_SERVICE_ROLES
        if status.get("production") else tuple(services)
    )
    for role in expected_roles:
        row = services.get(role)
        missing_fp = _alert_fingerprint(role, "heartbeat_missing")
        stale_fp = _alert_fingerprint(role, "heartbeat_stale")
        if row is None:
            event_id = event(
                "service", "heartbeat_missing", severity="critical",
                payload={"service_role": role}, fingerprint=missing_fp,
            )
            raised.append(event_id)
            _notify_service_alert(
                role, "heartbeat_missing", incident_id=event_id,
            )
            resolved_id = _resolve_alert(stale_fp)
            if resolved_id:
                resolved.append(resolved_id)
                _notify_service_alert(
                    role, "heartbeat_stale", resolved=True,
                    incident_id=resolved_id,
                )
            continue
        unhealthy = (
            not row.get("fresh")
            or row.get("status") in {"degraded", "failed", "stopping"}
        )
        if unhealthy:
            event_id = event(
                "service", "heartbeat_stale", severity="critical",
                payload={
                    "service_role": role,
                    "instance_id": row.get("instance_id"),
                    "age_sec": row.get("age_sec"), "status": row.get("status"),
                },
                fingerprint=stale_fp,
            )
            raised.append(event_id)
            _notify_service_alert(
                role, "heartbeat_stale", incident_id=event_id,
            )
            resolved_id = _resolve_alert(missing_fp)
            if resolved_id:
                resolved.append(resolved_id)
                _notify_service_alert(
                    role, "heartbeat_missing", resolved=True,
                    incident_id=resolved_id,
                )
            continue
        for condition, fingerprint in (
            ("heartbeat_missing", missing_fp),
            ("heartbeat_stale", stale_fp),
        ):
            resolved_id = _resolve_alert(fingerprint)
            if resolved_id:
                resolved.append(resolved_id)
                _notify_service_alert(
                    role, condition, resolved=True, incident_id=resolved_id,
                )
    if status.get("production"):
        with get_client().transaction(Scope.global_service_scope(), read_only=True) as conn:
            queue = dict(conn.execute(
                """SELECT
                     (SELECT count(*) FROM sf_jobs
                        WHERE status='dead_letter') AS job_dead_letters,
                     (SELECT count(*) FROM sf_telegram_updates
                        WHERE status='dead_letter') AS telegram_update_dead_letters,
                     (SELECT count(*) FROM sf_telegram_outbox
                        WHERE status='dead_letter') AS telegram_outbox_dead_letters,
                     COALESCE((SELECT EXTRACT(EPOCH FROM
                       (clock_timestamp()-min(created_at))) FROM sf_jobs
                       WHERE status='queued'),0) AS oldest_job_queued_sec,
                     COALESCE((SELECT EXTRACT(EPOCH FROM
                       (clock_timestamp()-min(received_at))) FROM sf_telegram_updates
                       WHERE status='queued'),0) AS oldest_telegram_update_sec,
                     COALESCE((SELECT EXTRACT(EPOCH FROM
                       (clock_timestamp()-min(created_at))) FROM sf_telegram_outbox
                       WHERE status='queued'),0) AS oldest_telegram_outbox_sec"""
            ).fetchone())
        operational_conditions = (
            ("job_dead_letter", int(queue.get("job_dead_letters") or 0) > 0,
             "critical", {"count": int(queue.get("job_dead_letters") or 0)}),
            ("telegram_update_dead_letter", int(queue.get("telegram_update_dead_letters") or 0) > 0,
             "warning", {"count": int(queue.get("telegram_update_dead_letters") or 0)}),
            ("telegram_outbox_dead_letter", int(queue.get("telegram_outbox_dead_letters") or 0) > 0,
             "critical", {"count": int(queue.get("telegram_outbox_dead_letters") or 0)}),
            ("job_queue_slo", float(queue.get("oldest_job_queued_sec") or 0) > 300,
             "warning", {"oldest_age_sec": float(queue.get("oldest_job_queued_sec") or 0)}),
            ("telegram_update_queue_slo", float(queue.get("oldest_telegram_update_sec") or 0) > 120,
             "warning", {"oldest_age_sec": float(queue.get("oldest_telegram_update_sec") or 0)}),
            ("telegram_outbox_queue_slo", float(queue.get("oldest_telegram_outbox_sec") or 0) > 120,
             "critical", {"oldest_age_sec": float(queue.get("oldest_telegram_outbox_sec") or 0)}),
        )
        for condition, active, severity, payload in operational_conditions:
            fingerprint = _alert_fingerprint("operations", condition)
            if active:
                event_id = event(
                    "operations", condition, severity=severity,
                    payload=payload, fingerprint=fingerprint,
                )
                raised.append(event_id)
                _notify_service_alert(
                    "operations", condition, incident_id=event_id,
                )
            else:
                resolved_id = _resolve_alert(fingerprint)
                if resolved_id:
                    resolved.append(resolved_id)
                    _notify_service_alert(
                        "operations", condition, resolved=True,
                        incident_id=resolved_id,
                    )
    return {
        "ok": True, "raised": raised, "resolved": resolved,
        "service_health": status,
    }


def sweep_retention(*, limit: int = 5000) -> Dict[str, int]:
    if not (runtime_env.is_production() and runtime_env.environment_explicit()):
        return {}
    capped = max(1, min(int(limit), 100_000))
    tables = {
        # Retention time is not permission to discard active work or an open
        # incident. Clock drift, a prolonged outage, or a policy change must
        # never turn cleanup into a queue/alert loss mechanism.
        "telegram_updates": (
            "sf_telegram_updates", "status IN ('completed','dead_letter')",
        ),
        "telegram_outbox": (
            "sf_telegram_outbox", "status IN ('sent','dead_letter')",
        ),
        "ai_usage": ("sf_ai_usage_events", "TRUE"),
        "market_batches": ("sf_market_data_ingest_batches", "TRUE"),
        "operational_events": ("sf_operational_events", "status='resolved'"),
        "audit_events": ("sf_audit_events", "TRUE"),
    }
    removed: Dict[str, int] = {}
    with get_client().transaction(Scope.global_service_scope()) as conn:
        removed["ai_reservations"] = len(conn.execute(
            """WITH doomed AS (
                 SELECT ctid FROM sf_ai_reservations
                 WHERE expires_at<clock_timestamp() LIMIT %s
               ) DELETE FROM sf_ai_reservations target USING doomed
                 WHERE target.ctid=doomed.ctid RETURNING 1""",
            (capped,),
        ).fetchall())
        for name, (table, terminal_filter) in tables.items():
            row = conn.execute(
                f"""WITH doomed AS (
                       SELECT ctid FROM {table}
                       WHERE retention_until < clock_timestamp()
                         AND ({terminal_filter})
                       LIMIT %s
                     ) DELETE FROM {table} target USING doomed
                       WHERE target.ctid=doomed.ctid RETURNING 1""",
                (capped,),
            ).fetchall()
            removed[name] = len(row)
        bounded_cleanup = {
            "market_snapshots": """
                WITH doomed AS (
                  SELECT ctid FROM sf_market_data_snapshots
                  WHERE stale_after < clock_timestamp()-interval '7 days'
                  LIMIT %s
                ) DELETE FROM sf_market_data_snapshots target USING doomed
                  WHERE target.ctid=doomed.ctid RETURNING 1
            """,
            "market_subscriptions": """
                WITH doomed AS (
                  SELECT ctid FROM sf_market_data_subscriptions
                  WHERE (status='deleted' OR expires_at<clock_timestamp())
                    AND expires_at < clock_timestamp()-interval '7 days'
                  LIMIT %s
                ) DELETE FROM sf_market_data_subscriptions target USING doomed
                  WHERE target.ctid=doomed.ctid RETURNING 1
            """,
            "service_heartbeats": """
                WITH doomed AS (
                  SELECT ctid FROM sf_service_heartbeats
                  WHERE heartbeat_at < clock_timestamp()-interval '30 days'
                  LIMIT %s
                ) DELETE FROM sf_service_heartbeats target USING doomed
                  WHERE target.ctid=doomed.ctid RETURNING 1
            """,
            "service_leases": """
                WITH doomed AS (
                  SELECT ctid FROM sf_service_leases
                  WHERE leased_until < clock_timestamp()-interval '1 day'
                  LIMIT %s
                ) DELETE FROM sf_service_leases target USING doomed
                WHERE target.ctid=doomed.ctid RETURNING 1
            """,
            "connector_sessions": """
                WITH doomed AS (
                  SELECT ctid FROM sf_connector_sessions
                  WHERE (
                    revoked_at IS NOT NULL
                    AND revoked_at < clock_timestamp()-interval '90 days'
                  ) OR (
                    revoked_at IS NULL
                    AND expires_at < clock_timestamp()-interval '90 days'
                  )
                  LIMIT %s
                ) DELETE FROM sf_connector_sessions target USING doomed
                  WHERE target.ctid=doomed.ctid RETURNING 1
            """,
            "rate_limits": """
                WITH doomed AS (
                  SELECT ctid FROM sf_rate_limit_buckets
                  WHERE expires_at < clock_timestamp() LIMIT %s
                ) DELETE FROM sf_rate_limit_buckets target USING doomed
                  WHERE target.ctid=doomed.ctid RETURNING 1
            """,
            "idempotency": """
                WITH doomed AS (
                  SELECT ctid FROM sf_idempotency_keys
                  WHERE expires_at < clock_timestamp() LIMIT %s
                ) DELETE FROM sf_idempotency_keys target USING doomed
                  WHERE target.ctid=doomed.ctid RETURNING 1
            """,
        }
        for name, sql in bounded_cleanup.items():
            removed[name] = len(conn.execute(sql, (capped,)).fetchall())
    return removed


class OperationsMaintenanceError(StorageError):
    code = "operations_maintenance_unavailable"


def production_maintenance() -> Dict[str, Any]:
    """Evaluate service alerts and retention under an explicit Production role."""
    try:
        config = runtime_env.assert_startup_safe()
    except runtime_env.RuntimeEnvError as exc:
        raise OperationsMaintenanceError("Production maintenance configuration is invalid.") from exc
    if config.environment != runtime_env.PRODUCTION:
        raise OperationsMaintenanceError("Operations maintenance requires Production.")
    if config.deployment_role not in {"worker", "all-in-one"}:
        raise OperationsMaintenanceError("Operations maintenance requires worker role.")
    from . import storage_router

    storage_router.assert_production_storage_safe()
    alerts = evaluate_alerts()
    return {
        "ok": bool(alerts.get("ok")),
        "alerts_raised": len(alerts.get("raised") or []),
        "retention": sweep_retention(),
    }


def _main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard", action="store_true")
    parser.add_argument("--evaluate-alerts", action="store_true")
    parser.add_argument("--sweep-retention", action="store_true")
    parser.add_argument("--maintenance", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.maintenance:
            out = production_maintenance()
        elif args.sweep_retention:
            out = sweep_retention()
        elif args.evaluate_alerts:
            out = evaluate_alerts()
        else:
            out = dashboard()
        print(json.dumps(out, ensure_ascii=False, default=str, sort_keys=True))
        return 0
    except StorageError as exc:
        print(json.dumps({"ok": False, "code": exc.code}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
