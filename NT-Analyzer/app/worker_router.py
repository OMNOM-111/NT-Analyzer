"""Route worker operations to SQLite Development or PostgreSQL Production."""
from __future__ import annotations

from typing import Any, Dict, Optional

from . import local_worker, runtime_env


def _production() -> bool:
    """Route to the authoritative PostgreSQL worker in Production *and* Canary.

    Canary is a real, isolated server contour with its own PostgreSQL queue
    and its own separately supervised worker process; routing it through the
    Development-only SQLite queue here would leave Canary's declared
    PostgreSQL identity unused and would let an in-process consumer duplicate
    work against a real isolated ``worker-canary`` program.
    """
    return runtime_env.is_server_environment() and runtime_env.environment_explicit()


def enqueue(
    kind: str, payload: Optional[Dict[str, Any]] = None, *,
    priority: int = 100, max_attempts: int = 1, timeout_sec: int = 300,
    user_id: Any = "", workspace_id: str = "", job_id: str = "",
    idempotency_key: str = "", dangerous: bool = False,
) -> Dict[str, Any]:
    if _production():
        from . import production_workers
        return production_workers.enqueue(
            kind, payload, priority=priority, max_attempts=max_attempts,
            timeout_sec=timeout_sec, user_id=user_id, workspace_id=workspace_id,
            job_id=job_id, idempotency_key=idempotency_key,
            dangerous=dangerous,
        )
    return local_worker.enqueue(
        kind, payload, priority=priority, max_attempts=max_attempts,
        timeout_sec=timeout_sec, user_id=user_id, workspace_id=workspace_id,
        job_id=job_id,
    )


def list_jobs(
    status: str = "", limit: int = 100, *, workspace_id: str = "",
    user_id: Any = 0,
) -> Dict[str, Any]:
    if _production():
        from . import production_workers
        return production_workers.list_jobs(
            status=status, limit=limit, workspace_id=workspace_id, user_id=user_id,
        )
    return local_worker.list_jobs(status=status, limit=limit, workspace_id=workspace_id)


def get(
    worker_job_id: str, *, workspace_id: str = "", user_id: Any = 0,
) -> Optional[Dict[str, Any]]:
    if _production():
        from . import production_workers
        return production_workers.get(
            worker_job_id, workspace_id=workspace_id, user_id=user_id,
        )
    return local_worker.get(worker_job_id, workspace_id=workspace_id)


def cancel(
    worker_job_id: str, *, workspace_id: str = "", user_id: Any = 0,
) -> Dict[str, Any]:
    if _production():
        from . import production_workers
        return production_workers.cancel(
            worker_job_id, workspace_id=workspace_id, user_id=user_id,
        )
    return local_worker.cancel(worker_job_id, workspace_id=workspace_id)


def enqueue_ai_message(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    if _production():
        from . import production_workers
        return production_workers.enqueue_ai_message(*args, **kwargs)
    return local_worker.enqueue_ai_message(*args, **kwargs)


def enqueue_chart_batch(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    if _production():
        from . import production_workers
        return production_workers.enqueue_chart_batch(*args, **kwargs)
    return local_worker.enqueue_chart_batch(*args, **kwargs)


def start_background_worker(interval_sec: float = 2.0) -> bool:
    # Production workers are an independently supervised service.  Starting an
    # untracked in-process queue consumer from an HTTP request is forbidden.
    if _production():
        return False
    return local_worker.start_background_worker(interval_sec=interval_sec)


def stop_background_worker(timeout_sec: float = 3.0) -> None:
    if not _production():
        local_worker.stop_background_worker(timeout_sec=timeout_sec)


def status() -> Dict[str, Any]:
    if _production():
        from . import production_workers
        return production_workers.status()
    return local_worker.status()
