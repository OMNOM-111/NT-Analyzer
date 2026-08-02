from __future__ import annotations

import json
from pathlib import Path

from app import durable, jobqueue


def test_sqlite_wal_initializes_and_records_job(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "durable.sqlite3"
    monkeypatch.setenv("NT_ANALYZER_SQLITE_PATH", str(db))

    assert durable.init(tmp_path) == db.resolve()
    with durable.connect(tmp_path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"

    durable.record_job(tmp_path, {
        "job_id": "job_1",
        "workspace_id": "ws_1",
        "user_id": "42",
        "status": "pending",
        "kind": "historical_backtest",
        "class_name": "SampleMACrossOver",
        "instrument": "MNQ 09-26",
        "timeframe": "5 Minute",
        "created_at_utc": "2026-07-10T00:00:00Z",
        "updated_at_utc": "2026-07-10T00:00:00Z",
    })

    row = durable.get_job(tmp_path, "job_1")
    assert row is not None
    assert row["workspace_id"] == "ws_1"
    assert row["status"] == "pending"


def test_jobqueue_durable_sweep_recovers_existing_queue_dirs(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "durable.sqlite3"
    monkeypatch.setenv("NT_ANALYZER_SQLITE_PATH", str(db))
    monkeypatch.setattr(jobqueue, "project_root", lambda: tmp_path)
    job_dir = tmp_path / "jobs" / "done" / "job_done"
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text(json.dumps({
        "job_id": "job_done",
        "created_at_utc": "2026-07-10T00:00:00Z",
        "kind": "historical_backtest",
        "instrument": "MNQ 09-26",
        "strategy": {"class_name": "SampleMACrossOver"},
        "timeframe": {"value": 5, "bars_period_type": "Minute"},
        "origin": {"workspace_id": "ws_recovered", "user_id": "77"},
    }), encoding="utf-8")
    (job_dir / "result.json").write_text(json.dumps({
        "status": "done",
        "finished_at_utc": "2026-07-10T00:01:00Z",
    }), encoding="utf-8")

    out = jobqueue.sync_durable_index()

    assert out["indexed"] == 1
    row = durable.get_job(tmp_path, "job_done")
    assert row is not None
    assert row["status"] == "done"
    assert row["workspace_id"] == "ws_recovered"
    assert row["timeframe"] == "5 Minute"
