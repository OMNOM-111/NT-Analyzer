"""One backtest product, two ways of reaching NinjaTrader.

The browser posts to /api/jobs and reads the report API, wherever the run
happens. Development drops the job in the queue beside it; a server hands the
same canonical job to the enrolled Connector and files the answer as the same
report. If that difference ever reached the page, the two would drift into two
backtests with two status models and two reports.

These tests hold three lines: the transport is chosen by where the code runs,
the payload that crosses to the device is a strict projection with no way to
name arbitrary code, and what comes back is the canonical report schema with an
honest account of what it does and does not contain.
"""
from __future__ import annotations

import json
import os
import time

import pytest

from app import connector_backtest
from app import runtime_env


def _job_doc(**overrides):
    doc = {
        "schema_version": "0.1",
        "job_id": "ui_20260828T000000000Z",
        "kind": "historical_backtest",
        "instrument": "MNQ SEP26",
        "created_at_utc": "2026-08-28T00:00:00Z",
        "timeframe": {"bars_period_type": "Minute", "value": 5},
        "period": {"from_utc": "2026-08-20T00:00:00Z", "to_utc": "2026-08-22T00:00:00Z"},
        "execution": {"calculate": "OnBarClose", "order_fill_resolution": "High",
                      "slippage_ticks": 1, "commission_template": "None"},
        "risk_profile": {"mode": "informational"},
        "strategy": {"class_name": "NTAMnqMicroOrbOpenScalp",
                     "parameters": {"AtrStopMult": 0.3}},
    }
    doc.update(overrides)
    return doc


# --------------------------------------------------------------------------- #
# Where the transport is decided.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("environment", ["canary", "production"])
def test_a_server_routes_the_job_through_the_connector(environment, monkeypatch):
    monkeypatch.setattr(runtime_env, "deployment_environment", lambda: environment)
    assert connector_backtest.routes_through_connector() is True


def test_development_keeps_its_local_queue(monkeypatch):
    """A Development machine has NinjaTrader beside it, and an enrolled
    Connector of its own is not a reason to send work over a network to the
    same computer."""
    monkeypatch.setattr(runtime_env, "deployment_environment",
                        lambda: runtime_env.DEVELOPMENT)
    assert connector_backtest.routes_through_connector() is False


# --------------------------------------------------------------------------- #
# What is allowed to cross to the device.
# --------------------------------------------------------------------------- #
def test_the_payload_is_a_projection_not_a_pass_through():
    """Only named fields travel, so nothing extra can ride along with a job."""
    doc = _job_doc(origin={"user_id": 1647145559, "session": "secret"},
                   portfolio={"cell_id": "CELL-012"})
    payload = connector_backtest.command_payload(doc)
    assert payload["command"] == "run_backtest"
    assert set(payload["job"]) <= set(connector_backtest.JOB_FIELDS) | {"strategy", "risk_profile"}
    assert "origin" not in payload["job"]
    assert "portfolio" not in payload["job"]
    assert payload["job"]["instrument"] == "MNQ SEP26"


@pytest.mark.parametrize("class_name", [
    "NinjaTrader.NinjaScript.Strategies.Evil",   # namespace-qualified type
    "../../../Windows/System32/evil",            # path traversal
    "C:\\\\Temp\\\\evil.dll",                    # file reference
    "Strategy; DROP TABLE",                      # expression-ish
    "St",                                        # below the length floor
    "",                                          # absent
    "a" * 128,                                   # oversized
])
def test_a_strategy_can_only_be_named_as_a_plain_class(class_name):
    """The device resolves the name through its own whitelist as well; this is
    the outer gate, and it exists so nothing path-like or type-like is even
    offered to it."""
    doc = _job_doc(strategy={"class_name": class_name, "parameters": {}})
    with pytest.raises(connector_backtest.BacktestDispatchError):
        connector_backtest.command_payload(doc)


def test_strategy_parameters_must_be_bounded_scalars():
    doc = _job_doc(strategy={"class_name": "NTAMnqMicroOrbOpenScalp",
                             "parameters": {"nested": {"a": 1}}})
    with pytest.raises(connector_backtest.BacktestDispatchError):
        connector_backtest.command_payload(doc)

    doc = _job_doc(strategy={
        "class_name": "NTAMnqMicroOrbOpenScalp",
        "parameters": {f"p{i}": i for i in range(connector_backtest.MAX_PARAMETERS + 1)},
    })
    with pytest.raises(connector_backtest.BacktestDispatchError):
        connector_backtest.command_payload(doc)


def test_a_job_without_a_strategy_is_refused():
    with pytest.raises(connector_backtest.BacktestDispatchError):
        connector_backtest.command_payload({"job_id": "x"})


# --------------------------------------------------------------------------- #
# What comes back.
# --------------------------------------------------------------------------- #
def _safe_result():
    return {
        "run_hash": "abc123",
        "started_at_utc": "2026-08-28T00:00:10Z",
        "finished_at_utc": "2026-08-28T00:00:24Z",
        "duration_ms": 14000,
        "source": {"execution_source": "ninjatrader",
                   "ninjatrader_version": "8.1.8.2",
                   "machine": "VMNINJA"},
        "metrics": {"trade_count": 2, "net_profit": 1.0, "profit_factor": 1.18},
        "trades": [{"trade_no": 1, "direction": "short", "pnl_currency": -5.5},
                   {"trade_no": 2, "direction": "short", "pnl_currency": 6.5}],
        "verification_warnings": ["strategy.activate: ok"],
    }


def test_the_result_is_the_canonical_report_schema(tmp_path):
    """The report API, the reports table and the drawer must not need to know
    where the run happened."""
    doc = connector_backtest.materialize(tmp_path, _job_doc(), _safe_result())
    assert doc["job_id"] == "ui_20260828T000000000Z"
    assert doc["metrics"]["trade_count"] == 2
    assert len(doc["trades"]) == 2
    assert doc["source"]["execution_source"] == "ninjatrader"
    assert doc["source"]["machine"] == "VMNINJA"
    written = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert written["metrics"] == doc["metrics"]
    assert json.loads((tmp_path / "trades.json").read_text(encoding="utf-8")) == doc["trades"]


def test_the_missing_price_series_is_declared_not_faked():
    """NinjaTrader ran on historical bars this server does not hold. Drawing
    the chart from the live market-data channel would show a picture that does
    not belong to the run it claims to show, so the report says so instead.
    """
    doc = connector_backtest.result_document(_job_doc(), _safe_result())
    assert doc["artifacts"]["price_series"] == "not_transferred"
    assert "не передавался" in doc["artifacts"]["price_series_reason"]
    assert "bars" not in doc


def test_the_returned_trade_list_is_bounded():
    """A device cannot enlarge the report by sending more trades than the
    result channel was sized for."""
    result = _safe_result()
    result["trades"] = [{"trade_no": i} for i in range(connector_backtest.MAX_TRADES_IN_RESULT + 50)]
    doc = connector_backtest.result_document(_job_doc(), result)
    assert len(doc["trades"]) == connector_backtest.MAX_TRADES_IN_RESULT


# --------------------------------------------------------------------------- #
# Status stays the status a report already understands.
# --------------------------------------------------------------------------- #
def test_a_job_moves_between_canonical_status_directories(tmp_path):
    jobs_root = tmp_path / "jobs"
    pending = jobs_root / "pending" / "ui_1"
    pending.mkdir(parents=True)
    (pending / "job.json").write_text(json.dumps(_job_doc()), encoding="utf-8")

    running = connector_backtest.move_job(pending, jobs_root, "running")
    assert running == jobs_root / "running" / "ui_1"
    assert connector_backtest.locate(jobs_root, "ui_1") == ("running", running)

    done = connector_backtest.move_job(running, jobs_root, "done")
    assert done == jobs_root / "done" / "ui_1"


def test_an_unknown_status_is_refused(tmp_path):
    jobs_root = tmp_path / "jobs"
    job = jobs_root / "pending" / "ui_1"
    job.mkdir(parents=True)
    with pytest.raises(connector_backtest.BacktestDispatchError):
        connector_backtest.move_job(job, jobs_root, "leased")


def test_a_failed_dispatch_does_not_leave_the_job_waiting(tmp_path):
    """A job left pending against a device that will never be told about it is
    a queue that is not a queue."""
    jobs_root = tmp_path / "jobs"
    pending = jobs_root / "pending" / "ui_1"
    pending.mkdir(parents=True)
    (pending / "job.json").write_text(json.dumps(_job_doc()), encoding="utf-8")

    failed = connector_backtest.fail_job(jobs_root, "ui_1", "Connector не подключён")
    assert failed == jobs_root / "failed" / "ui_1"
    result = json.loads((failed / "result.json").read_text(encoding="utf-8"))
    assert "Connector" in result["error"]
    assert result["trades"] == []


# --------------------------------------------------------------------------- #
# A job is running only when the device says it started.
# --------------------------------------------------------------------------- #
def _queued(tmp_path):
    jobs_root = tmp_path / "jobs"
    pending = jobs_root / "pending" / "ui_1"
    pending.mkdir(parents=True)
    (pending / "job.json").write_text(
        json.dumps(_job_doc(job_id="ui_1")), encoding="utf-8")
    return jobs_root


def test_accepted_does_not_make_a_job_look_like_it_is_running(tmp_path):
    """"Accepted" is the device confirming it has the work. A Connector that
    goes quiet right after must not leave an operator watching a run that never
    started."""
    jobs_root = _queued(tmp_path)
    out = connector_backtest.settle(jobs_root, "ui_1", "accepted", {})
    assert out["action"] == "acknowledged"
    assert connector_backtest.locate(jobs_root, "ui_1")[0] == "pending"


def test_running_from_the_device_moves_the_job(tmp_path):
    jobs_root = _queued(tmp_path)
    out = connector_backtest.settle(jobs_root, "ui_1", "running", {})
    assert out["action"] == "started"
    assert connector_backtest.locate(jobs_root, "ui_1")[0] == "running"


def test_a_second_running_report_is_not_a_transition(tmp_path):
    jobs_root = _queued(tmp_path)
    connector_backtest.settle(jobs_root, "ui_1", "running", {})
    out = connector_backtest.settle(jobs_root, "ui_1", "running", {})
    assert out["action"] == "noop"
    assert connector_backtest.locate(jobs_root, "ui_1")[0] == "running"


# --------------------------------------------------------------------------- #
# One result, one report.
# --------------------------------------------------------------------------- #
def test_a_retried_identical_result_produces_one_report(tmp_path):
    """submit_result is retried after a network failure. One job must not end
    up with two reports or two terminal transitions."""
    jobs_root = _queued(tmp_path)
    first = connector_backtest.settle(jobs_root, "ui_1", "completed", _safe_result())
    assert first["action"] == "completed"
    done = jobs_root / "done" / "ui_1"
    stamp = (done / "result.json").read_text(encoding="utf-8")

    again = connector_backtest.settle(jobs_root, "ui_1", "completed", _safe_result())
    assert again["action"] == "duplicate"
    assert (done / "result.json").read_text(encoding="utf-8") == stamp


def test_a_conflicting_second_result_is_refused_not_written(tmp_path):
    """Two different outcomes for one run is not settled by picking one."""
    jobs_root = _queued(tmp_path)
    connector_backtest.settle(jobs_root, "ui_1", "completed", _safe_result())
    done = jobs_root / "done" / "ui_1"
    stamp = (done / "result.json").read_text(encoding="utf-8")

    other = _safe_result()
    other["metrics"] = {"trade_count": 99, "net_profit": 999.0}
    with pytest.raises(connector_backtest.ConflictingResultError):
        connector_backtest.settle(jobs_root, "ui_1", "completed", other)
    assert (done / "result.json").read_text(encoding="utf-8") == stamp


def test_a_late_result_never_resurrects_a_cancelled_job(tmp_path):
    """The operator cancelled it. A result that arrives afterwards does not get
    to reopen the question."""
    jobs_root = _queued(tmp_path)
    connector_backtest.move_job(
        jobs_root / "pending" / "ui_1", jobs_root, "cancelled")
    out = connector_backtest.settle(jobs_root, "ui_1", "completed", _safe_result())
    assert out["action"] == "stays_cancelled"
    assert connector_backtest.locate(jobs_root, "ui_1")[0] == "cancelled"
    assert not (jobs_root / "done" / "ui_1").exists()


def test_a_result_for_an_unknown_job_is_ignored(tmp_path):
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir()
    assert connector_backtest.settle(
        jobs_root, "ui_missing", "completed", _safe_result())["action"] == "unknown_job"


# --------------------------------------------------------------------------- #
# Large runs cross the 16 KiB channel deterministically.
# --------------------------------------------------------------------------- #
def test_a_truncated_trade_list_says_so_with_numbers():
    """A strategy can produce thousands of trades. Keeping the first N quietly
    would show a real trade count that is not the run's, and every metric read
    beside it would look sound."""
    result = _safe_result()
    result["trades"] = [{"trade_no": i} for i in range(50)]
    result["trades_total"] = 4321
    result["trades_truncated"] = True
    doc = connector_backtest.result_document(_job_doc(), result)
    assert doc["trade_transfer"] == {
        "trades_total": 4321, "trades_transferred": 50, "trades_truncated": True,
    }


def test_truncation_is_inferred_even_if_the_device_forgets_to_flag_it():
    result = _safe_result()
    result["trades"] = [{"trade_no": i} for i in range(10)]
    result["trades_total"] = 900
    doc = connector_backtest.result_document(_job_doc(), result)
    assert doc["trade_transfer"]["trades_truncated"] is True


def test_a_complete_small_run_is_not_marked_truncated():
    doc = connector_backtest.result_document(_job_doc(), _safe_result())
    assert doc["trade_transfer"] == {
        "trades_total": 2, "trades_transferred": 2, "trades_truncated": False,
    }


def test_a_dishonest_total_below_the_rows_cannot_hide_trades():
    result = _safe_result()
    result["trades_total"] = 0
    doc = connector_backtest.result_document(_job_doc(), result)
    assert doc["trade_transfer"]["trades_total"] == 2


# --------------------------------------------------------------------------- #
# Cancel.
# --------------------------------------------------------------------------- #
def test_the_cancel_command_names_only_the_job():
    payload = connector_backtest.cancel_payload("ui_1")
    assert payload == {"command": "cancel_backtest", "job": {"job_id": "ui_1"}}


# --------------------------------------------------------------------------- #
# The device side, asserted on its source.
#
# A Strategy Analyzer run takes seconds to minutes. Executing it on the command
# loop would mean the one command an operator needs while it runs -- cancel --
# could not be read until the run they wanted to stop had already finished.
# --------------------------------------------------------------------------- #
def _executor_source():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    return (root / "bridge" / "src" / "Runtime"
            / "ConnectorBacktestExecutor.cs").read_text(encoding="utf-8")


def _processor_source():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    return (root / "bridge" / "src" / "Runtime"
            / "RuntimeCommandProcessor.cs").read_text(encoding="utf-8")


def test_the_command_loop_does_not_wait_for_a_backtest():
    processor = _processor_source()
    block = processor[processor.index('if (command == "run_backtest")'):]
    block = block[: block.index('if (command == "resubscribe_market_data")')]
    assert "_backtests.Start(cid, ExtractJobObject(rawJson));" in block
    assert "return true;" in block
    # Started on a background task, not awaited on the consumer.
    assert "Task.Factory.StartNew" in _executor_source()


def test_one_backtest_at_a_time_with_an_honest_refusal():
    """The Strategy Analyzer is not safe to drive concurrently, and inventing
    concurrency to look faster would produce results nobody could trust."""
    source = _executor_source()
    assert "another backtest is already running on this installation" in source
    assert "_active.Count > 0" in source


def test_a_redelivered_run_is_not_a_second_execution():
    source = _executor_source()
    assert "_active.ContainsKey(jobId)" in source
    assert "backtest already running for this job" in source
    assert "_finished.Contains(jobId)" in source


def test_running_is_reported_only_once_the_runner_started():
    source = _executor_source()
    started = source.index('"running",')
    invoked = source.index("_runner.Run(")
    assert started < invoked, "running must be reported immediately before the run"
    assert "strategy analyzer started" in source


def test_a_strategy_is_resolved_only_through_the_whitelist():
    source = _executor_source()
    assert "_loader.Resolve(className)" in source
    assert "strategy is not whitelisted" in source


def test_cancel_targets_one_job_and_is_idempotent():
    source = _executor_source()
    cancel = source[source.index("public void Cancel("):]
    cancel = cancel[: cancel.index("private string BuildSafeResult")]
    assert "_active.TryGetValue(jobId, out record)" in cancel
    assert "no active backtest for this job" in cancel
    assert "record.Cancellation.Cancel()" in cancel
    # A repeat, or a job that already finished, is a plain success -- not an
    # error the operator has to interpret.
    assert "rejected" not in cancel.split("cancel job_id missing")[1]


def test_a_cancelled_run_never_reports_success():
    """The runner may still finish on its way out; that is not a completion."""
    source = _executor_source()
    assert "record.CancelRequested || record.Cancellation.IsCancellationRequested" in source
    assert "backtest cancelled before completion" in source


def test_a_failed_run_cleans_up_its_state():
    source = _executor_source()
    finally_block = source[source.index("            finally\n            {"):]
    finally_block = finally_block[: finally_block.index("// ---")]
    assert "_active.Remove(record.JobId)" in finally_block
    assert "record.Cancellation.Dispose()" in finally_block


def test_shutdown_cancels_and_drains_active_runs():
    """NinjaTrader must never be left closing under a live Strategy Analyzer."""
    source = _executor_source()
    stop = source[source.index("public void Stop()"):]
    stop = stop[: stop.index("// ---")]
    assert "run.Cancellation.Cancel()" in stop
    assert "run.Execution?.Wait(" in stop
    assert "_backtests.Stop();" in _processor_source()


def test_the_payload_is_bounded_before_it_is_sent():
    """A large successful backtest must not become a transport error."""
    source = _executor_source()
    assert "MaxSafeResultBytes" in source
    assert "Encoding.UTF8.GetByteCount" in source
    # Rows are dropped, never counts: the report may say fewer trades were
    # transferred, never that fewer happened.
    assert '["trades_total"] = total' in source
    assert '["trades_truncated"] = total > transferred.Count' in source


def test_no_projected_field_can_trip_the_command_validator():
    """The transport refuses a payload containing certain names anywhere.

    The stored job nests risk_profile.margin_source.source, and a projection
    that copied the block wholesale was rejected on arrival -- a dispatch that
    failed for a reason nothing in the job itself made visible. The projection
    flattens it instead, and this walks the result so the next field with an
    awkward nested name is caught here rather than in Production.
    """
    from app import connector_protocol

    forbidden = {"password", "broker_password", "token", "secret",
                 "api_key", "source", "code"}
    doc = _job_doc(risk_profile={
        "schema_version": "0.1", "mode": "informational", "currency": "USD",
        "starting_capital": 5000.0, "intraday_only": True, "status": "ok",
        "margin_source": {"broker": "", "source": "", "fetched_at_utc": ""},
        "instrument_margins": {},
    })
    payload = connector_backtest.command_payload(doc)

    def walk(value, path=""):
        if isinstance(value, dict):
            for key, item in value.items():
                assert str(key).lower() not in forbidden, f"{path}.{key}"
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(payload)
    # And the run still knows its capital.
    assert payload["job"]["risk_profile"]["starting_capital"] == 5000.0
    assert "margin_source" not in payload["job"]["risk_profile"]

    # The real validator accepts it.
    connector_protocol._safe_payload(payload)


# --------------------------------------------------------------------------- #
# A pending job means something.
# --------------------------------------------------------------------------- #
def test_a_dispatched_job_carries_proof_of_its_command(tmp_path):
    """Otherwise a pending job is ambiguous: waiting for a device that has it,
    or waiting for nothing at all."""
    job_dir = tmp_path / "ui_1"
    job_dir.mkdir()
    connector_backtest.record_dispatch(
        job_dir, command_id="cmd_abc", connection_id="conn_x",
        idempotency_key="backtest:ui_1", queued_at_utc="2026-08-28T03:00:00Z")
    record = connector_backtest.dispatch_record(job_dir)
    assert record["command_id"] == "cmd_abc"
    assert record["transport"] == "production_connector"


def test_a_job_queued_before_dispatch_existed_is_closed_with_its_reason(tmp_path):
    """It will never run -- nothing was told about it and nothing will be.
    Leaving it pending shows a queue that cannot explain why it is not moving,
    and deleting it would erase that the operator ever asked."""
    jobs_root = tmp_path / "jobs"
    legacy = jobs_root / "pending" / "ui_legacy"
    legacy.mkdir(parents=True)
    (legacy / "job.json").write_text(json.dumps(_job_doc(job_id="ui_legacy")),
                                     encoding="utf-8")
    stale = time.time() - connector_backtest.UNDISPATCHED_RECOVERY_GRACE_SEC - 1
    os.utime(legacy / "job.json", (stale, stale))

    recovered = connector_backtest.recover_undispatched(jobs_root)
    assert recovered == ["ui_legacy"]
    assert connector_backtest.locate(jobs_root, "ui_legacy")[0] == "cancelled"
    result = json.loads(
        (jobs_root / "cancelled" / "ui_legacy" / "result.json").read_text(encoding="utf-8"))
    assert "legacy pre-dispatch job" in result["error"]


def test_a_fresh_ui_job_is_not_misclassified_as_legacy_before_dispatch(tmp_path):
    """create_job writes pending before queue_command can write dispatch.json.

    The recovery sweep runs inside that interval.  A real Production UI job
    used to cancel itself here before NinjaTrader ever received a command.
    """
    jobs_root = tmp_path / "jobs"
    fresh = jobs_root / "pending" / "ui_fresh"
    fresh.mkdir(parents=True)
    (fresh / "job.json").write_text(json.dumps(_job_doc(job_id="ui_fresh")),
                                    encoding="utf-8")

    assert connector_backtest.recover_undispatched(jobs_root) == []
    assert connector_backtest.locate(jobs_root, "ui_fresh")[0] == "pending"


def test_a_dispatched_job_is_never_swept(tmp_path):
    """A job the device is holding is not stale, however long it takes."""
    jobs_root = tmp_path / "jobs"
    live = jobs_root / "pending" / "ui_live"
    live.mkdir(parents=True)
    (live / "job.json").write_text(json.dumps(_job_doc(job_id="ui_live")),
                                   encoding="utf-8")
    connector_backtest.record_dispatch(
        live, command_id="cmd_live", connection_id="conn_x",
        idempotency_key="backtest:ui_live", queued_at_utc="2026-08-28T03:00:00Z")

    assert connector_backtest.recover_undispatched(jobs_root) == []
    assert connector_backtest.locate(jobs_root, "ui_live")[0] == "pending"


def test_dispatch_uses_a_delivery_ttl_the_protocol_accepts():
    """A backtest can run for minutes, but the command TTL is a delivery
    window, not a budget for the run: once the device accepts the work the run
    is bounded by its own cancellation token. Asking for longer than the
    protocol allows simply refused the command, and the job failed before
    NinjaTrader ever heard about it.
    """
    from pathlib import Path

    from app import connector_protocol
    from app import server as server_mod

    text = Path(server_mod.__file__).read_text(encoding="utf-8")
    block = text[text.index("def _dispatch_backtest_to_connector("):]
    block = block[: block.index("def _connector_is_the_runtime_transport")]
    assert "expires_in_sec=connector_protocol.MAX_COMMAND_TTL_SEC," in block
    assert "expires_in_sec=900" not in block
    assert connector_protocol.MAX_COMMAND_TTL_SEC >= 60
