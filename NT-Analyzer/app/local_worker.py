"""Recoverable local worker queue for heavy backend tasks.

The HTTP server should enqueue work and return quickly. A separate process can
claim queued rows from the SQLite WAL durable DB, execute bounded task kinds and
persist terminal status. The NinjaTrader bridge file queue remains unchanged.
"""
from __future__ import annotations

import multiprocessing
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from . import durable


_WORKER_LOCK = threading.Lock()
_PROCESS: Optional[multiprocessing.Process] = None
_WORKER_ID = "api-" + secrets.token_hex(4)
DEFAULT_INTERVAL_SEC = 2.0


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


def list_jobs(status: str = "", limit: int = 100) -> Dict[str, Any]:
    return {
        "jobs": durable.list_worker_jobs(_root(), status=status, limit=limit),
        "counts": durable.worker_job_counts(_root()),
    }


def cancel(worker_job_id: str) -> Dict[str, Any]:
    row = durable.request_worker_cancel(_root(), worker_job_id)
    if row is None:
        return {"ok": False, "reason": "not_found", "worker_job_id": worker_job_id}
    return {"ok": True, "job": row}


def _execute(job: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(job.get("kind") or "")
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    if kind == "durable_sweep":
        from . import jobqueue
        return jobqueue.sync_durable_index()
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
            path = root / "data" / "runtime" / name
            indexed.append(durable.record_telemetry_file(root, name=name, path=path, updated_at_utc=_now_iso()))
        return {"ok": bool(rotation.get("ok", True)), "rotation": rotation, "indexed": indexed}
    if kind == "sleep":
        seconds = max(0.0, min(5.0, float(payload.get("seconds") or 0.0)))
        time.sleep(seconds)
        return {"ok": True, "slept": seconds}
    if kind == "fail":
        raise RuntimeError(str(payload.get("message") or "worker job failed"))
    if kind == "noop":
        return {"ok": True}
    raise RuntimeError(f"unknown worker job kind: {kind}")


def run_once(*, worker_id: str = "") -> Optional[Dict[str, Any]]:
    root = _root()
    durable.sweep_stale_worker_jobs(root)
    job = durable.claim_worker_job(root, worker_id=worker_id or _WORKER_ID)
    if not job:
        return None
    if int(job.get("cancel_requested") or 0):
        durable.request_worker_cancel(root, str(job["worker_job_id"]))
        return durable.get_worker_job(root, str(job["worker_job_id"]))
    try:
        result = _execute(job)
    except Exception as exc:  # noqa: BLE001 - persisted as job failure
        return durable.fail_worker_job(root, str(job["worker_job_id"]), str(exc))
    return durable.finish_worker_job(root, str(job["worker_job_id"]), result)


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


def start_background_worker(interval_sec: float = DEFAULT_INTERVAL_SEC) -> bool:
    """Start the local worker process if it is not already alive."""
    global _PROCESS
    with _WORKER_LOCK:
        if _PROCESS is not None and _PROCESS.is_alive():
            return False
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
        return True


def stop_background_worker(timeout_sec: float = 3.0) -> None:
    global _PROCESS
    with _WORKER_LOCK:
        proc = _PROCESS
        _PROCESS = None
    if proc is None:
        return
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=max(0.1, float(timeout_sec or 3.0)))


def status() -> Dict[str, Any]:
    proc = _PROCESS
    alive = bool(proc is not None and proc.is_alive())
    path = durable.db_path(_root())
    return {
        "worker_id": _WORKER_ID,
        "process_alive": alive,
        "pid": int(proc.pid or 0) if proc is not None else 0,
        "db_path": str(path),
        "counts": durable.worker_job_counts(_root()) if path.is_file() else {},
    }
