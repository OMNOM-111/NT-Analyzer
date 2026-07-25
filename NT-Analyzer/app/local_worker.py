"""Recoverable local worker queue for heavy backend tasks.

The HTTP server should enqueue work and return quickly. A separate process can
claim queued rows from the SQLite WAL durable DB, execute bounded task kinds and
persist terminal status. The NinjaTrader bridge file queue remains unchanged.
"""
from __future__ import annotations

import multiprocessing
import os
import secrets
import sqlite3
import threading
import time
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from . import durable


_WORKER_LOCK = threading.Lock()
_PROCESS: Optional[multiprocessing.Process] = None
_SUPERVISOR: Optional[threading.Thread] = None
_SUPERVISOR_STOP = threading.Event()
_WORKER_ID = "api-" + secrets.token_hex(4)
DEFAULT_INTERVAL_SEC = 2.0


class WorkerCancelled(RuntimeError):
    pass


class WorkerTimedOut(RuntimeError):
    pass


def _root() -> Path:
    env = os.environ.get("NT_ANALYZER_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def enqueue(kind: str, payload: Optional[Dict[str, Any]] = None, *,
            priority: int = 100, max_attempts: int = 1,
            timeout_sec: int = 300, user_id: Any = "",
            workspace_id: str = "", job_id: str = "") -> Dict[str, Any]:
    worker_job_id = str(job_id or "").strip() or ("wj_" + secrets.token_hex(12))
    return durable.enqueue_worker_job(
        _root(),
        worker_job_id=worker_job_id,
        kind=kind,
        payload=payload or {},
        priority=priority,
        max_attempts=max_attempts,
        timeout_sec=timeout_sec,
        user_id=user_id,
        workspace_id=workspace_id,
    )


def list_jobs(status: str = "", limit: int = 100, *,
              workspace_id: str = "") -> Dict[str, Any]:
    return {
        "jobs": durable.list_worker_jobs(
            _root(), status=status, limit=limit, workspace_id=workspace_id,
        ),
        "counts": durable.worker_job_counts(_root(), workspace_id=workspace_id),
    }


def get(worker_job_id: str, *, workspace_id: str = "") -> Optional[Dict[str, Any]]:
    """Read one worker job without allowing a cross-workspace lookup."""
    if not str(workspace_id or "").strip():
        return None
    return durable.get_worker_job(
        _root(), worker_job_id, workspace_id=str(workspace_id),
    )


def enqueue_ai_message(
    message: str,
    *,
    request_id: str,
    conversation_id: str,
    agent: str,
    scope: Dict[str, Any],
    mirror_to_telegram: bool = True,
    source: str = "app",
    timeout_sec: int = 600,
) -> Dict[str, Any]:
    """Idempotently queue one workspace-bound interactive AI turn."""
    clean_scope = dict(scope or {})
    user_id = str(clean_scope.get("user_id") or "").strip()
    workspace_id = str(clean_scope.get("workspace_id") or "").strip()
    rid = "".join(
        ch for ch in str(request_id or "").strip()
        if ch.isalnum() or ch in "_.:-"
    )[:120]
    if not user_id or not workspace_id:
        raise ValueError("AI worker job requires user_id and workspace_id")
    if not rid:
        rid = "air_" + secrets.token_hex(16)
    worker_job_id = "wj_ai_" + hashlib.sha256(
        f"{workspace_id}:{user_id}:{rid}".encode("utf-8")
    ).hexdigest()[:28]
    payload = {
        "message": str(message or "")[:6001],
        "request_id": rid,
        "conversation_id": str(conversation_id or "default")[:160],
        "agent": str(agent or "")[:80],
        "source": str(source or "app")[:40],
        "mirror_to_telegram": bool(mirror_to_telegram),
        "scope": clean_scope,
    }
    try:
        return enqueue(
            "ai_orchestrator", payload,
            priority=50, max_attempts=2,
            timeout_sec=max(30, min(1800, int(timeout_sec or 600))),
            user_id=user_id, workspace_id=workspace_id,
            job_id=worker_job_id,
        )
    except sqlite3.IntegrityError:
        existing = get(worker_job_id, workspace_id=workspace_id)
        if (not existing or str(existing.get("kind") or "") != "ai_orchestrator"
                or str(existing.get("user_id") or "") != user_id
                or str((existing.get("payload") or {}).get("request_id") or "") != rid):
            raise
        return existing


def enqueue_chart_batch(requests: list[Dict[str, Any]], *, scope: Dict[str, Any],
                        runtime_dir: str = "", timeout_sec: int = 60) -> Dict[str, Any]:
    """Queue a large chart batch; identical source/request pairs converge."""
    clean_scope = dict(scope or {})
    user_id = str(clean_scope.get("user_id") or "").strip()
    workspace_id = str(clean_scope.get("workspace_id") or "").strip()
    if not user_id or not workspace_id:
        raise ValueError("chart worker job requires user_id and workspace_id")
    from . import market_data, runtime_env
    production_mode = bool(
        runtime_env.is_production() and runtime_env.environment_explicit()
    )
    if production_mode:
        from . import market_data_ingestion
        remote_index = market_data_ingestion.workspace_snapshot_index(workspace_id)
        source_signature = str(remote_index.get("source_signature") or "remote-empty")
    else:
        source_signature = market_data.snapshot_source_signature()
    identity = json.dumps(
        {"workspace_id": workspace_id, "requests": requests,
         "source_signature": source_signature},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    )
    worker_job_id = "wj_chart_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:28]
    payload = {
        "requests": [dict(row) for row in requests if isinstance(row, dict)][:64],
        "scope": clean_scope,
        "runtime_dir": str(runtime_dir or ""),
        "source_signature": source_signature,
    }
    durable.prune_terminal_worker_jobs(
        _root(), kind="chart_batch", workspace_id=workspace_id, keep=3,
    )
    try:
        return enqueue(
            "chart_batch", payload, priority=80, max_attempts=2,
            timeout_sec=max(10, min(180, int(timeout_sec or 60))),
            user_id=user_id, workspace_id=workspace_id, job_id=worker_job_id,
        )
    except sqlite3.IntegrityError:
        existing = get(worker_job_id, workspace_id=workspace_id)
        if not existing or str(existing.get("kind") or "") != "chart_batch":
            raise
        return existing


def cancel(worker_job_id: str, *, workspace_id: str = "") -> Dict[str, Any]:
    row = durable.request_worker_cancel(
        _root(), worker_job_id, workspace_id=workspace_id,
    )
    if row is None:
        return {"ok": False, "reason": "not_found", "worker_job_id": worker_job_id}
    return {"ok": True, "job": row}


def _execute(job: Dict[str, Any], *, heartbeat=None, cancelled=None) -> Dict[str, Any]:
    heartbeat = heartbeat or (lambda: None)
    cancelled = cancelled or (lambda: False)
    if cancelled():
        raise WorkerCancelled("cancelled by request")
    heartbeat()
    kind = str(job.get("kind") or "")
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    if kind == "durable_sweep":
        from . import jobqueue
        result = jobqueue.sync_durable_index()
        heartbeat()
        return result
    if kind == "telemetry_index":
        # Rotate and index current JSONL runtime files without blocking API
        # requests that read charts/activity.
        root = _root()
        from . import runtime
        rotation = runtime.rotate_runtime_jsonl_files(
            max_bytes=int(payload.get("max_bytes") or runtime.RUNTIME_JSONL_ROTATE_BYTES),
            keep=int(payload.get("keep") or runtime.RUNTIME_JSONL_ROTATE_KEEP),
        )
        names = ("executions.jsonl", "orders.jsonl", "errors.jsonl")
        indexed = []
        for name in names:
            if cancelled():
                raise WorkerCancelled("cancelled by request")
            heartbeat()
            from . import runtime_env
            path = runtime_env.data_path("runtime", name, project_root=root)
            indexed.append(durable.record_telemetry_file(root, name=name, path=path, updated_at_utc=_now_iso()))
        return {"ok": bool(rotation.get("ok", True)), "rotation": rotation, "indexed": indexed}
    if kind == "ai_orchestrator":
        scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
        if (str(scope.get("workspace_id") or "") != str(job.get("workspace_id") or "")
                or str(scope.get("user_id") or "") != str(job.get("user_id") or "")):
            raise RuntimeError("AI worker scope does not match durable job ownership")
        if cancelled():
            raise WorkerCancelled("cancelled by request")
        from .ai_lab import chief_agent

        def on_thinking(_delta: str) -> None:
            if cancelled():
                raise WorkerCancelled("cancelled by request")
            heartbeat()

        result = chief_agent.handle_message(
            str(payload.get("message") or ""),
            source=str(payload.get("source") or "app")[:40],
            mirror_to_telegram=bool(payload.get("mirror_to_telegram", True)),
            conversation_id=str(payload.get("conversation_id") or "default"),
            agent=str(payload.get("agent") or ""),
            on_thinking=on_thinking,
            scope=scope,
            request_id=str(payload.get("request_id") or ""),
        )
        heartbeat()
        return result
    if kind == "chart_batch":
        scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
        if (str(scope.get("workspace_id") or "") != str(job.get("workspace_id") or "")
                or str(scope.get("user_id") or "") != str(job.get("user_id") or "")):
            raise RuntimeError("chart worker scope does not match durable job ownership")
        rows = payload.get("requests") if isinstance(payload.get("requests"), list) else []
        from . import market_data, market_data_ingestion, runtime, runtime_env
        from . import server as server_mod

        def calculate() -> Dict[str, Any]:
            production_mode = bool(
                runtime_env.is_production() and runtime_env.environment_explicit()
            )
            workspace_id = str(job.get("workspace_id") or "")
            snapshot_index = None if production_mode else market_data.read_snapshot_index()
            alerts_index = None if production_mode else market_data.read_alerts_index()
            connector_snapshot_index = (
                market_data_ingestion.workspace_snapshot_index(workspace_id)
                if production_mode else None
            )
            series = []
            for row in rows[:64]:
                if cancelled():
                    raise WorkerCancelled("cancelled by request")
                heartbeat()
                series.append(server_mod._market_bars_payload(
                    str(row.get("instrument") or ""),
                    str(row.get("timeframe") or "5m"),
                    int(row.get("limit") or 1500),
                    int(row.get("range_days") or 0),
                    str(row.get("from") or ""),
                    str(row.get("to") or ""),
                    register=False,
                    snapshot_index=snapshot_index,
                    alerts_index=alerts_index,
                    max_points=int(row.get("max_points") or 0),
                    workspace_id=workspace_id,
                    connector_snapshot_index=connector_snapshot_index,
                ))
            return {"series": series}

        runtime_dir = str(payload.get("runtime_dir") or "")
        if runtime_dir:
            with runtime.runtime_dir_override(runtime_dir):
                result = calculate()
        else:
            result = calculate()
        heartbeat()
        return result
    if kind == "sleep":
        seconds = max(0.0, min(5.0, float(payload.get("seconds") or 0.0)))
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if cancelled():
                raise WorkerCancelled("cancelled by request")
            heartbeat()
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        return {"ok": True, "slept": seconds}
    if kind == "fail":
        raise RuntimeError(str(payload.get("message") or "worker job failed"))
    if kind == "noop":
        return {"ok": True}
    raise RuntimeError(f"unknown worker job kind: {kind}")


def run_once(*, worker_id: str = "") -> Optional[Dict[str, Any]]:
    root = _root()
    active_worker_id = worker_id or _WORKER_ID
    durable.sweep_stale_worker_jobs(root)
    job = durable.claim_worker_job(root, worker_id=active_worker_id)
    if not job:
        return None
    job_id = str(job["worker_job_id"])

    def cancelled() -> bool:
        return durable.worker_cancel_requested(
            root, job_id, worker_id=active_worker_id,
        )

    def heartbeat() -> None:
        if durable.heartbeat_worker_job(
            root, job_id, worker_id=active_worker_id,
        ):
            return
        if cancelled():
            raise WorkerCancelled("cancelled by request")
        raise WorkerTimedOut("worker execution timed out")

    if int(job.get("cancel_requested") or 0):
        return durable.finalize_worker_cancel(
            root, job_id, worker_id=active_worker_id,
        )
    lease_stop = threading.Event()
    lease_lost = threading.Event()

    def keep_lease() -> None:
        while not lease_stop.wait(5.0):
            if not durable.heartbeat_worker_job(
                root, job_id, worker_id=active_worker_id,
            ):
                lease_lost.set()
                return

    lease_thread = threading.Thread(
        target=keep_lease,
        name=f"worker-lease-{job_id[:24]}",
        daemon=True,
    )
    lease_thread.start()
    try:
        result = _execute(job, heartbeat=heartbeat, cancelled=cancelled)
        if lease_lost.is_set():
            if cancelled():
                raise WorkerCancelled("cancelled by request")
            raise WorkerTimedOut("worker execution timed out")
        heartbeat()
    except WorkerCancelled:
        return durable.finalize_worker_cancel(
            root, job_id, worker_id=active_worker_id,
        )
    except WorkerTimedOut as exc:
        return durable.fail_worker_job(
            root, job_id, str(exc), worker_id=active_worker_id,
        )
    except Exception as exc:  # noqa: BLE001 - persisted as job failure
        return durable.fail_worker_job(
            root, job_id, str(exc), worker_id=active_worker_id,
        )
    finally:
        lease_stop.set()
        lease_thread.join(timeout=1.0)
    return durable.finish_worker_job(
        root, job_id, result, worker_id=active_worker_id,
    )


def _process_main(root: str, db: str, interval_sec: float) -> None:
    os.environ["NT_ANALYZER_ROOT"] = root
    os.environ["NT_ANALYZER_SQLITE_PATH"] = db
    while True:
        try:
            ran = run_once(worker_id="proc-" + str(os.getpid()))
            if ran is None:
                time.sleep(max(0.2, float(interval_sec or DEFAULT_INTERVAL_SEC)))
        except KeyboardInterrupt:
            return
        except Exception:
            time.sleep(max(1.0, float(interval_sec or DEFAULT_INTERVAL_SEC)))


def _spawn_process_locked(interval_sec: float) -> None:
    global _PROCESS
    root = str(_root())
    db = str(durable.db_path(_root()))
    ctx = multiprocessing.get_context("spawn")
    _PROCESS = ctx.Process(
        target=_process_main,
        args=(root, db, max(0.2, float(interval_sec or DEFAULT_INTERVAL_SEC))),
        name="nta-local-worker",
        daemon=True,
    )
    _PROCESS.start()


def _supervisor_loop(interval_sec: float) -> None:
    global _PROCESS
    while not _SUPERVISOR_STOP.wait(1.0):
        with _WORKER_LOCK:
            proc = _PROCESS
            if proc is None or proc.is_alive():
                continue
            proc.join(timeout=0.1)
            if _SUPERVISOR_STOP.is_set():
                return
            _spawn_process_locked(interval_sec)


def start_background_worker(interval_sec: float = DEFAULT_INTERVAL_SEC) -> bool:
    """Start and supervise the single durable worker process."""
    global _SUPERVISOR
    active_interval = max(0.2, float(interval_sec or DEFAULT_INTERVAL_SEC))
    started = False
    with _WORKER_LOCK:
        _SUPERVISOR_STOP.clear()
        if _PROCESS is None or not _PROCESS.is_alive():
            if _PROCESS is not None:
                _PROCESS.join(timeout=0.1)
            _spawn_process_locked(active_interval)
            started = True
        if _SUPERVISOR is None or not _SUPERVISOR.is_alive():
            _SUPERVISOR = threading.Thread(
                target=_supervisor_loop,
                args=(active_interval,),
                name="nta-worker-supervisor",
                daemon=True,
            )
            _SUPERVISOR.start()
    return started


def stop_background_worker(timeout_sec: float = 3.0) -> None:
    global _PROCESS, _SUPERVISOR
    _SUPERVISOR_STOP.set()
    with _WORKER_LOCK:
        proc = _PROCESS
        _PROCESS = None
        supervisor = _SUPERVISOR
        _SUPERVISOR = None
    if proc is not None and proc.is_alive():
        proc.terminate()
        proc.join(timeout=max(0.1, float(timeout_sec or 3.0)))
    if supervisor is not None and supervisor is not threading.current_thread():
        supervisor.join(timeout=max(0.1, float(timeout_sec or 3.0)))


def status() -> Dict[str, Any]:
    proc = _PROCESS
    alive = bool(proc is not None and proc.is_alive())
    path = durable.db_path(_root())
    return {
        "worker_id": _WORKER_ID,
        "process_alive": alive,
        "supervisor_alive": bool(_SUPERVISOR is not None and _SUPERVISOR.is_alive()),
        "pid": int(proc.pid or 0) if proc is not None else 0,
        "db_path": str(path),
        "counts": durable.worker_job_counts(_root()) if path.is_file() else {},
        "max_concurrency": 1,
    }
