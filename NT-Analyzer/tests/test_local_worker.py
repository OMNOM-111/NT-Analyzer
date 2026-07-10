from __future__ import annotations

import time
from pathlib import Path

from app import durable, local_worker


def _isolate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NT_ANALYZER_ROOT", str(tmp_path))
    monkeypatch.setenv("NT_ANALYZER_SQLITE_PATH", str(tmp_path / "durable.sqlite3"))


def test_local_worker_runs_queued_job_to_success(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    local_worker.enqueue("noop", job_id="wj_noop")

    row = local_worker.run_once(worker_id="test-worker")

    assert row is not None
    assert row["worker_job_id"] == "wj_noop"
    assert row["status"] == "succeeded"
    assert row["result"]["ok"] is True


def test_local_worker_persists_failure_without_blocking_queue(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    local_worker.enqueue("fail", {"message": "boom"}, job_id="wj_fail")
    local_worker.enqueue("noop", job_id="wj_after")

    failed = local_worker.run_once(worker_id="test-worker")
    succeeded = local_worker.run_once(worker_id="test-worker")

    assert failed["status"] == "failed"
    assert "boom" in failed["error"]
    assert succeeded["worker_job_id"] == "wj_after"
    assert succeeded["status"] == "succeeded"


def test_worker_cancel_and_stale_recovery(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    local_worker.enqueue("noop", job_id="wj_cancel")
    cancelled = local_worker.cancel("wj_cancel")
    assert cancelled["job"]["status"] == "cancelled"

    durable.enqueue_worker_job(
        tmp_path,
        worker_job_id="wj_stale",
        kind="noop",
        timeout_sec=1,
        payload={},
    )
    claimed = durable.claim_worker_job(tmp_path, worker_id="test", now=time.time() - 5)
    assert claimed["status"] == "running"
    assert durable.sweep_stale_worker_jobs(tmp_path, now=time.time() + 10) == 1
    assert durable.get_worker_job(tmp_path, "wj_stale")["status"] == "stale"
