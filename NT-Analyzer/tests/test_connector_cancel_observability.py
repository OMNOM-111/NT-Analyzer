"""A cancel that found nothing is not a cancel.

Both outcomes used to arrive as a bare success, so a run that carried on to
completion produced an audit trail indistinguishable from a clean
cancellation. That ambiguity hid a real Production defect for a release: the
job showed `done` with a full 48,252-trade result 153 seconds after the token
was supposedly set, and nothing on the server said which of the two had
happened.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import connector_backtest
from app import server as server_mod


BRIDGE = Path(__file__).resolve().parent.parent / "bridge" / "src"


def _executor_source() -> str:
    return (BRIDGE / "Runtime" / "ConnectorBacktestExecutor.cs").read_text("utf-8")


# --------------------------------------------------------------------------- #
# The key that ties a run to its cancellation.
# --------------------------------------------------------------------------- #
def test_both_commands_address_the_run_by_the_same_canonical_job_id():
    """Start keys the registry by job_id and Cancel looks it up by job_id.

    Neither may drift onto the connector command_id, the idempotency key or a
    spool record id -- a mismatch there would answer every cancel with
    "nothing to cancel" while the run continued.
    """
    job_doc = {
        "schema_version": "0.1",
        "job_id": "ui_20260829T053453936Z",
        "kind": "backtest",
        "instrument": "MNQ SEP26",
        "created_at_utc": "2026-08-29T05:34:53Z",
        "strategy": {"class_name": "SampleMACrossOver", "parameters": {}},
        "timeframe": {"bars_period_type": "Minute", "value": 1},
        "period": {"from_utc": "2023-08-28T00:00:00Z",
                   "to_utc": "2026-08-28T00:00:00Z"},
        "execution": {},
    }
    run = connector_backtest.command_payload(job_doc)
    cancel = connector_backtest.cancel_payload(job_doc["job_id"])

    assert run["job"]["job_id"] == cancel["job"]["job_id"] == job_doc["job_id"]
    # Both nest under the same key, because the device reads exactly one path.
    assert set(cancel) == {"command", "job"}
    assert "job" in run

    src = _executor_source()
    start = src[src.index("public void Start("):src.index("private bool TryResolveStrategy")]
    cancel_src = src[src.index("public void Cancel("):src.index("// ---", src.index("public void Cancel("))]
    assert '(string)(job?["job_id"])' in start
    assert '(string)(job?["job_id"])' in cancel_src
    assert "_active[jobId] = record" in start
    assert "_active.TryGetValue(jobId, out record)" in cancel_src
    for wrong in ("commandId,", "idempotency", "spool"):
        assert f"_active[{wrong}" not in src


def test_the_processor_extracts_the_job_the_same_way_for_both_commands():
    src = (BRIDGE / "Runtime" / "RuntimeCommandProcessor.cs").read_text("utf-8")
    assert '_backtests.Start(cid, ExtractJobObject(rawJson))' in src
    assert '_backtests.Cancel(cid, ExtractJobObject(rawJson))' in src
    assert 'envelope["job"] as JObject' in src


# --------------------------------------------------------------------------- #
# FOUND vs NOT FOUND must be distinguishable.
# --------------------------------------------------------------------------- #
def test_the_device_says_whether_it_had_the_run():
    src = _executor_source()
    start = src.index("public void Cancel(")
    cancel = src[start:src.index("// ---", start)]
    for field in ("target_job_id", "active_run_found", "cancellation_requested",
                  "active_count", "already_finished", "executor_state"):
        assert f'["{field}"]' in cancel, field
    # Only the job the caller already named is echoed back: no other run's
    # id and no workspace data. Checked on the emitted keys, not on prose.
    emitted = {line.split('"')[1] for line in cancel.splitlines()
               if line.strip().startswith('["') and "] =" in line}
    assert emitted == {"target_job_id", "active_run_found",
                       "cancellation_requested", "active_count",
                       "already_finished", "executor_state"}, emitted
    assert "_active.Keys" not in cancel


def test_a_cancel_that_found_its_run_is_recorded_as_such(monkeypatch):
    events = []
    monkeypatch.setattr(server_mod.observability, "event",
                        lambda *a, **k: events.append((a, k)))
    server_mod._record_cancel_outcome("ui_1", {"safe_result": {
        "target_job_id": "ui_1", "active_run_found": True,
        "cancellation_requested": True, "active_count": 1,
        "executor_state": "running",
    }})
    assert events and events[0][0][1] == "backtest_cancel_requested_on_device"
    assert events[0][1]["severity"] == "info"
    assert events[0][1]["payload"]["cancellation_requested"] is True


def test_a_cancel_that_found_nothing_is_not_reported_as_a_cancellation(monkeypatch):
    """The exact shape of the Production defect."""
    events = []
    monkeypatch.setattr(server_mod.observability, "event",
                        lambda *a, **k: events.append((a, k)))
    server_mod._record_cancel_outcome("ui_1", {"safe_result": {
        "target_job_id": "ui_1", "active_run_found": False,
        "cancellation_requested": False, "active_count": 0,
        "executor_state": "running",
    }})
    assert events and events[0][0][1] == "backtest_cancel_target_not_found"
    assert events[0][1]["severity"] == "warning"


def test_a_run_found_but_not_cancellable_is_also_not_a_cancellation(monkeypatch):
    """The token could not be set because the run ended in between. That is
    still not a run that was asked to stop."""
    events = []
    monkeypatch.setattr(server_mod.observability, "event",
                        lambda *a, **k: events.append((a, k)))
    server_mod._record_cancel_outcome("ui_1", {"safe_result": {
        "active_run_found": True, "cancellation_requested": False,
        "executor_state": "run_ended_before_cancel",
    }})
    assert events[0][0][1] == "backtest_cancel_target_not_found"


def test_cancelling_twice_reports_the_same_thing_twice(monkeypatch):
    events = []
    monkeypatch.setattr(server_mod.observability, "event",
                        lambda *a, **k: events.append((a, k)))
    body = {"safe_result": {"active_run_found": True,
                            "cancellation_requested": True}}
    server_mod._record_cancel_outcome("ui_1", body)
    server_mod._record_cancel_outcome("ui_1", body)
    assert [e[0][1] for e in events] == [
        "backtest_cancel_requested_on_device"] * 2


def test_a_cancel_result_never_moves_the_canonical_job(monkeypatch, tmp_path):
    """Only the run's own terminal result may change the job's state."""
    moved = []
    monkeypatch.setattr(connector_backtest, "settle",
                        lambda *a, **k: moved.append(a) or {"action": "x"})
    monkeypatch.setattr(server_mod.observability, "event", lambda *a, **k: None)
    server_mod._settle_connector_backtest({
        "idempotency_key": "cancel-backtest:ui_1",
        "status": "completed",
        "safe_result": {"active_run_found": True, "cancellation_requested": True},
    })
    assert moved == [], "a cancel ack is not an outcome for the run"


# --------------------------------------------------------------------------- #
# The race must reach the audit.
# --------------------------------------------------------------------------- #
def test_the_race_outcome_is_audited():
    """It was computed and then dropped: the audit only logged started /
    completed / failed, so `cancel_race_completed_before_abort_boundary` went
    nowhere and the race could not be told apart from a failed cancel."""
    src = Path(server_mod.__file__).read_text(encoding="utf-8")
    block = src[src.index("def _settle_connector_backtest("):]
    block = block[: block.index("def _record_cancel_outcome(")]
    assert "cancel_race_completed_before_abort_boundary" in block
    assert '"cancelled",' in block


def test_only_the_runners_own_verdict_can_make_a_job_cancelled(tmp_path):
    """Not the request, and not the device having acknowledged one."""
    root = tmp_path / "jobs"
    d = root / "cancel_requested" / "ui_1"
    d.mkdir(parents=True)
    (d / "job.json").write_text(json.dumps({"job_id": "ui_1"}), encoding="utf-8")

    # An acknowledgement is not an outcome.
    assert connector_backtest.settle(root, "ui_1", "accepted", {})["status"] \
        == "cancel_requested"
    # A completed run is honestly done, with the race named.
    out = connector_backtest.settle(root, "ui_1", "completed", {
        "metrics": {"trade_count": 48252}, "trades": [], "trades_total": 48252,
        "execution_details": {"execution_source": "ninjatrader"},
    })
    assert out["action"] == "cancel_race_completed_before_abort_boundary"
    assert out["status"] == "done"


def test_the_registry_is_cleared_only_when_the_task_actually_ends():
    src = _executor_source()
    finally_block = src[src.index("            finally\n            {"):]
    finally_block = finally_block[: finally_block.index("// ---")]
    assert "_active.Remove(record.JobId)" in finally_block
    assert "_finished.Add(record.JobId)" in finally_block
    assert "record.Cancellation.Dispose()" in finally_block
