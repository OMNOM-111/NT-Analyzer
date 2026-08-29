"""A cancel must never claim a stop that has not happened.

NinjaTrader's RunBacktest() takes no cancellation token and the platform
offers no supported way to preempt it, so there is a real stretch between
"the operator asked" and "the device stopped". These tests pin what the
server is allowed to say during that stretch, and how each race ends.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import connector_backtest


def _job_doc(job_id: str = "ui_1") -> dict:
    return {
        "schema_version": "0.1",
        "job_id": job_id,
        "kind": "backtest",
        "instrument": "MNQ SEP26",
        "created_at_utc": "2026-08-29T00:00:00Z",
        "strategy": {"class_name": "SampleMACrossOver", "parameters": {}},
        "timeframe": {"bars_period_type": "Minute", "value": 1},
        "period": {"from_utc": "2026-06-01T00:00:00Z",
                   "to_utc": "2026-08-29T00:00:00Z"},
        "execution": {},
    }


def _seed(tmp_path: Path, state: str, job_id: str = "ui_1") -> Path:
    root = tmp_path / "jobs"
    d = root / state / job_id
    d.mkdir(parents=True)
    (d / "job.json").write_text(json.dumps(_job_doc(job_id)), encoding="utf-8")
    return root


def _safe_result() -> dict:
    return {
        "metrics": {"trade_count": 12, "net_profit": 100.0},
        "trades": [],
        "trades_total": 12,
        "trades_truncated": True,
        "execution_details": {"execution_source": "ninjatrader",
                              "machine": "VMNINJA"},
    }


# 1. cancel before the device started -------------------------------------- #
def test_a_device_that_stopped_before_starting_makes_the_job_cancelled(tmp_path):
    root = _seed(tmp_path, "cancel_requested")
    out = connector_backtest.settle(root, "ui_1", "cancelled", {})
    assert out["action"] == "cancelled"
    assert out["status"] == "cancelled"
    assert (root / "cancelled" / "ui_1").is_dir()
    marker = json.loads(
        (root / "cancelled" / "ui_1" / "result.json").read_text("utf-8"))
    assert marker["status"] == "cancelled"
    assert "boundary" in marker["reason"]


# 2. cancel during the uninterruptible run --------------------------------- #
def test_the_run_starting_does_not_undo_a_pending_cancel(tmp_path):
    """The device reports running while a cancel is already in flight. That is
    not news that changes what the operator asked for."""
    root = _seed(tmp_path, "cancel_requested")
    out = connector_backtest.settle(root, "ui_1", "running", {})
    assert out["action"] == "noop"
    assert out["status"] == "cancel_requested"
    assert (root / "cancel_requested" / "ui_1").is_dir()
    assert not (root / "running" / "ui_1").exists()


def test_cancel_requested_then_cancelled_at_the_boundary(tmp_path):
    root = _seed(tmp_path, "cancel_requested")
    mid = connector_backtest.settle(root, "ui_1", "running", {})
    assert mid["status"] == "cancel_requested"
    out = connector_backtest.settle(root, "ui_1", "cancelled", {})
    assert out["status"] == "cancelled"


# 3. the run finished before any boundary ---------------------------------- #
def test_a_run_that_finished_first_is_done_not_a_fake_cancellation(tmp_path):
    """The honest outcome of losing the race. The result is real and is kept;
    presenting it as a cancellation would be a lie in the other direction."""
    root = _seed(tmp_path, "cancel_requested")
    out = connector_backtest.settle(root, "ui_1", "completed", _safe_result())
    assert out["action"] == "cancel_race_completed_before_abort_boundary"
    assert out["status"] == "done"
    assert (root / "done" / "ui_1" / "result.json").is_file()


# 4. asking twice ----------------------------------------------------------- #
def test_cancelling_twice_is_the_same_request(tmp_path, monkeypatch):
    from app import jobqueue

    root = _seed(tmp_path, "pending")
    monkeypatch.setattr(jobqueue, "jobs_dir", lambda: root)
    monkeypatch.setattr(connector_backtest, "routes_through_connector",
                        lambda: True)

    first = jobqueue.cancel_job("ui_1")
    assert first["action"] == "cancel_requested"
    assert first["status"] == "cancel_requested"
    assert (root / "cancel_requested" / "ui_1").is_dir()

    second = jobqueue.cancel_job("ui_1")
    assert second["action"] == "cancel_requested"
    assert second["status"] == "cancel_requested"
    assert len(list((root / "cancel_requested").iterdir())) == 1


def test_a_connector_job_is_never_declared_cancelled_by_the_server_alone(
        tmp_path, monkeypatch):
    """The defect this state exists to fix: pending does not mean the device
    has not started, so moving straight to cancelled claimed a stop that had
    not happened."""
    from app import jobqueue

    root = _seed(tmp_path, "pending")
    monkeypatch.setattr(jobqueue, "jobs_dir", lambda: root)
    monkeypatch.setattr(connector_backtest, "routes_through_connector",
                        lambda: True)
    out = jobqueue.cancel_job("ui_1")
    assert out["status"] != "cancelled"
    assert not (root / "cancelled").exists()


def test_a_local_job_still_cancels_the_way_it_always_did(tmp_path, monkeypatch):
    """Development runs its own NinjaTrader, where pending really does mean
    nothing has started. That path must not change."""
    from app import jobqueue

    root = _seed(tmp_path, "pending")
    monkeypatch.setattr(jobqueue, "jobs_dir", lambda: root)
    monkeypatch.setattr(connector_backtest, "routes_through_connector",
                        lambda: False)
    out = jobqueue.cancel_job("ui_1")
    assert out["action"] == "cancelled_immediately"
    assert (root / "cancelled" / "ui_1").is_dir()


# 5. a late result must not move the job illegally -------------------------- #
@pytest.mark.parametrize("late", ["completed", "failed", "rejected"])
def test_a_late_result_cannot_resurrect_a_confirmed_cancellation(tmp_path, late):
    root = _seed(tmp_path, "cancelled")
    out = connector_backtest.settle(root, "ui_1", late, _safe_result())
    assert out["action"] == "stays_cancelled"
    assert out["status"] == "cancelled"
    assert not (root / "done" / "ui_1").exists()


def test_a_late_cancelled_cannot_undo_a_finished_run(tmp_path):
    root = _seed(tmp_path, "done")
    out = connector_backtest.settle(root, "ui_1", "cancelled", {})
    assert out["action"] == "noop_terminal"
    assert out["status"] == "done"
    assert not (root / "cancelled" / "ui_1").exists()


# 6. the next backtest ------------------------------------------------------ #
def test_cancel_requested_is_a_state_the_whole_queue_knows():
    """Recovery after a restart, sweeps and lookups all walk QUEUE_SUBDIRS. A
    state missing from it would be invisible to every one of them."""
    from app import jobqueue

    assert "cancel_requested" in jobqueue.QUEUE_SUBDIRS
    assert jobqueue.QUEUE_SUBDIRS.index("cancel_requested") > \
        jobqueue.QUEUE_SUBDIRS.index("running")


def test_a_confirmed_cancellation_frees_the_queue_for_the_next_run(
        tmp_path, monkeypatch):
    from app import jobqueue

    root = _seed(tmp_path, "pending")
    monkeypatch.setattr(jobqueue, "jobs_dir", lambda: root)
    monkeypatch.setattr(connector_backtest, "routes_through_connector",
                        lambda: True)
    jobqueue.cancel_job("ui_1")
    connector_backtest.settle(root, "ui_1", "cancelled", {})

    assert not (root / "cancel_requested" / "ui_1").exists()
    assert connector_backtest.locate(root, "ui_1")[0] == "cancelled"


# The device's own vocabulary ---------------------------------------------- #
def test_cancelled_is_a_terminal_status_the_protocol_accepts():
    """It used to fall through the relay's switch into failed, so a run the
    operator stopped was shown to them as an error."""
    from app import connector_protocol

    text = Path(connector_protocol.__file__).read_text(encoding="utf-8")
    assert '"cancelled", "failed", "rejected"' in text
    assert ('terminal = status in {"completed", "cancelled", "failed", '
            '"rejected"}') in text

    root = Path(__file__).resolve().parent.parent
    cs = (root / "bridge" / "src" / "Connector"
          / "ConnectorClient.cs").read_text("utf-8")
    assert 'case "cancelled": status = "cancelled"; break;' in cs


def test_the_runner_decides_the_outcome_not_the_request():
    """A run that finished must report success even if a cancel arrived while
    it was finishing -- otherwise a complete, valid result is thrown away."""
    root = Path(__file__).resolve().parent.parent
    cs = (root / "bridge" / "src" / "Runtime"
          / "ConnectorBacktestExecutor.cs").read_text("utf-8")
    assert "outcome != null && outcome.Status == JobStatus.Cancelled" in cs
    assert "cancel_race_completed_before_abort_boundary" in cs
    assert ("if (record.CancelRequested || "
            "record.Cancellation.IsCancellationRequested)") not in cs


def test_progress_results_are_relayed_before_the_blocking_poll():
    """PollCommands blocks on a bounded long poll. Draining only after it left
    a running row in the spool for a whole poll window, long enough that a
    backtest could finish before the server learned it had started."""
    root = Path(__file__).resolve().parent.parent
    cs = (root / "bridge" / "src" / "Connector"
          / "ConnectorClient.cs").read_text("utf-8")
    body = cs[cs.index("FlushMarketData();"):]
    body = body[: body.index("backoffSeconds = 2;")]
    assert body.index("ReportRuntimeResults();") < body.index("PollCommands();")


def test_the_runner_stops_before_doing_work_it_no_longer_needs_to_do():
    """Collecting trades, building metrics and serialising the report are ours
    to skip -- the earliest supported point where a cancel saves anything."""
    root = Path(__file__).resolve().parent.parent
    rs = (root / "bridge" / "src" / "Execution"
          / "StrategyAnalyzerRunner.cs").read_text("utf-8")
    assert '"cancelled before trade collection"' in rs
    assert "stopped.CancelSeenBeforeTradeCollection = true;" in rs,         "the boundary must also say that it was the one that saw the cancel"
    assert rs.count("ct.IsCancellationRequested") >= 4
