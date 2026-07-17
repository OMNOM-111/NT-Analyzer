"""Durable gap-recovery worker skeleton (not on the HTTP request path)."""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import runtime_env

_LOCK = threading.RLock()
_WORKER: Optional["GapRecoveryWorker"] = None


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _runtime_dir() -> Path:
    from . import runtime
    override = getattr(runtime._RUNTIME_CONTEXT, "runtime_dir", "")
    path = (
        Path(override) if override
        else runtime_env.data_path("runtime", project_root=_root())
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path() -> Path:
    return _runtime_dir() / "market_data_gap_recovery.jsonl"


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _audit(row: Dict[str, Any]) -> None:
    try:
        with log_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


class GapRecoveryWorker:
    def __init__(self, interval_sec: float = 2.0) -> None:
        self.interval_sec = interval_sec
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._queue: List[Dict[str, Any]] = []
        self.completed: List[Dict[str, Any]] = []

    def enqueue(self, job: Dict[str, Any]) -> str:
        job_id = str(job.get("job_id") or uuid.uuid4().hex)
        row = dict(job)
        row["job_id"] = job_id
        row["enqueued_at_utc"] = _iso()
        row["status"] = "queued"
        with _LOCK:
            self._queue.append(row)
        _audit({"kind": "enqueue", **row})
        return job_id

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="gap-recovery", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = None
            with _LOCK:
                if self._queue:
                    job = self._queue.pop(0)
            if job is None:
                self._stop.wait(self.interval_sec)
                continue
            self._run_job(job)

    def _run_job(self, job: Dict[str, Any]) -> None:
        job = dict(job)
        job["status"] = "running"
        job["started_at_utc"] = _iso()
        _audit({"kind": "start", **job})
        # Phase 10: recover from provider historical APIs. Until live entitlement
        # exists, mark jobs as simulated_fill only when fixture bars are supplied.
        recovered = list(job.get("fixture_bars") or [])
        job["recovered_bars"] = len(recovered)
        job["status"] = "completed" if recovered else "blocked_no_provider"
        job["finished_at_utc"] = _iso()
        with _LOCK:
            self.completed.append(job)
        _audit({"kind": "finish", **job})

    def status(self) -> Dict[str, Any]:
        with _LOCK:
            return {
                "queued": len(self._queue),
                "completed": len(self.completed),
                "last": list(self.completed)[-5:],
            }


def get_worker() -> GapRecoveryWorker:
    global _WORKER
    with _LOCK:
        if _WORKER is None:
            _WORKER = GapRecoveryWorker()
        return _WORKER


def start_background_worker(interval_sec: float = 2.0) -> GapRecoveryWorker:
    worker = get_worker()
    worker.interval_sec = interval_sec
    worker.start()
    return worker


def stop_background_worker() -> None:
    global _WORKER
    with _LOCK:
        worker = _WORKER
        _WORKER = None
    if worker is not None:
        worker.stop()
