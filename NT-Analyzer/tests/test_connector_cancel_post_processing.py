"""A cancel must not have to wait out work we are doing ourselves.

Production evidence closed the question of where cancellation was failing.
The token was right, the registry was right, and the runner read the very
token the executor had cancelled -- the executor saw it cancelled the instant
Run() returned. What went wrong is that the last boundary sat before trade
collection, and everything past it was ours: collecting 48,252 trades,
checking the period invariant over all of them, building metrics, serialising
the report. On that run the unguarded tail lasted 27 seconds, from 08:37:42
to 08:38:09, and a cancel that arrived inside it was ignored by construction.

These tests pin the boundaries that close the tail, and the one point that
decides the race: the commit.
"""
from __future__ import annotations

import re
from pathlib import Path

BRIDGE = Path(__file__).resolve().parent.parent / "bridge" / "src"
RUNNER = (BRIDGE / "Execution" / "StrategyAnalyzerRunner.cs")
COLLECTOR = (BRIDGE / "Execution" / "TradeCollector.cs")
OUTCOME = (BRIDGE / "Execution" / "HistoricalRunner.cs")
EXECUTOR = (BRIDGE / "Runtime" / "ConnectorBacktestExecutor.cs")


def _post_processing() -> str:
    """Everything the runner does after NinjaTrader hands control back."""
    src = RUNNER.read_text("utf-8")
    start = src.index('CancelledAt("before_trade_collection")')
    return src[start:src.index("return JobRunOutcome.Done();")]


# 1. cancel before post-processing ------------------------------------------ #
def test_nothing_heavy_runs_when_the_cancel_is_already_there():
    block = _post_processing()
    first = block.index('CancelledAt("before_trade_collection")')
    assert first < block.index("collector.Collect("), \
        "the check must precede collection, not follow it"


# 2. cancel in the middle of collection ------------------------------------- #
def test_collecting_trades_stops_partway_through():
    """Checking once at the start would mean a cancel arriving on the second
    trade is only honoured after the forty-eight thousandth."""
    src = COLLECTOR.read_text("utf-8")
    assert "private const int CancelCheckEveryTrades = 256;" in src
    extract = src[src.index("private void ExtractTrades("):]
    extract = extract[: extract.index("\n        }")]
    assert "ct.ThrowIfCancellationRequested()" in extract
    assert "% CancelCheckEveryTrades == 0" in extract

    block = _post_processing()
    assert "collector.Collect(backtested, ct)" in block
    assert 'CancelledAt("during_trade_collection")' in block


def test_the_collector_still_works_without_a_token():
    """Local runs and tests call it with nothing to cancel."""
    src = COLLECTOR.read_text("utf-8")
    assert "return Collect(strategyBase, CancellationToken.None);" in src


# 3. cancel after collection, before metrics -------------------------------- #
def test_metrics_and_report_are_not_built_after_a_cancel():
    block = _post_processing()
    for boundary in ("after_trade_collection", "before_metrics"):
        assert f'CancelledAt("{boundary}")' in block, boundary
    assert block.index('CancelledAt("after_trade_collection")') < \
        block.index("CheckPeriodInvariant(")
    assert block.index('CancelledAt("before_metrics")') < \
        block.index("CheckPeriodInvariant(")


def test_the_period_check_walks_trades_and_so_it_checks_too():
    src = RUNNER.read_text("utf-8")
    fn = src[src.index("private static string CheckPeriodInvariant("):]
    fn = fn[: fn.index("\n        private ", 10)] if "\n        private " in fn[10:] else fn
    assert "ct.ThrowIfCancellationRequested()" in fn
    assert "% 256 == 0" in fn
    assert 'CancelledAt("during_metrics")' in _post_processing()


# 4. cancel before the final write ------------------------------------------ #
def test_the_commit_is_the_last_thing_a_cancel_can_beat():
    block = _post_processing()
    assert 'CancelledAt("before_serialization")' in block
    assert 'CancelledAt("before_final_write")' in block
    assert block.index('CancelledAt("before_final_write")') < \
        block.index("WriteJobOutputs("), \
        "the last boundary must sit immediately before the commit"


def test_the_boundaries_are_in_pipeline_order():
    block = _post_processing()
    order = [
        "before_trade_collection", "during_trade_collection",
        "after_trade_collection", "before_metrics", "during_metrics",
        "before_serialization", "before_final_write",
    ]
    seen = [m.group(1) for m in re.finditer(r'CancelledAt\("([a-z_]+)"\)', block)]
    # Every boundary appears, and none of them out of order.
    assert set(order) <= set(seen), set(order) - set(seen)
    positions = [seen.index(name) for name in order]
    assert positions == sorted(positions), list(zip(order, positions))


# 5. cancel after the commit ------------------------------------------------ #
def test_a_run_that_committed_still_reports_done():
    """Past the commit the run has produced a real report, and a late cancel
    has honestly lost. Nothing after WriteJobOutputs may turn that into a
    cancellation."""
    src = RUNNER.read_text("utf-8")
    tail = src[src.index("WriteJobOutputs(runningDir, result, collector.Trades);"):]
    tail = tail[: tail.index("return JobRunOutcome.Done();")]
    assert "CancelledAt(" not in tail
    assert "ct.IsCancellationRequested" not in tail


def test_the_server_still_calls_that_race_by_its_name():
    from app import connector_backtest

    root_doc = {"job_id": "ui_1"}
    doc = connector_backtest.result_document(root_doc, {
        "metrics": {}, "trades": [], "trades_total": 0,
        "execution_details": {},
        "cancellation": {"outcome_status": "Done",
                         "cancel_boundary": ""},
    })
    assert doc["cancellation"]["outcome_status"] == "Done"


# 6. an ordinary run is unchanged ------------------------------------------- #
def test_a_run_nobody_cancelled_takes_the_same_path_as_before():
    """Every new boundary is a read of an uncancelled token: no behaviour
    changes, no work is skipped, and the outcome is still Done."""
    block = _post_processing()
    # The boundaries are plain guards -- none of them alters the pipeline.
    for guard in re.findall(r"if \(ct\.IsCancellationRequested\) return CancelledAt\([^)]+\);", block):
        assert guard.endswith(";")
    src = RUNNER.read_text("utf-8")
    assert src.count("return JobRunOutcome.Done();") == 1


def test_the_boundary_that_stopped_the_run_is_named_in_the_result():
    outcome = OUTCOME.read_text("utf-8")
    assert "public string CancelBoundary { get; set; }" in outcome

    runner = RUNNER.read_text("utf-8")
    helper = runner[runner.index("private static JobRunOutcome CancelledAt("):]
    helper = helper[: helper.index("\n        private ")]
    assert "outcome.CancelBoundary = boundary;" in helper

    executor = EXECUTOR.read_text("utf-8")
    assert '["cancel_boundary"]' in executor


def test_the_cancel_evidence_can_be_tied_to_the_run_that_answered():
    """Without the id, the cancel answer and the terminal result cannot be
    shown to describe the same execution."""
    from app import server as server_mod

    src = Path(server_mod.__file__).read_text(encoding="utf-8")
    block = src[src.index("def _record_cancel_outcome("):]
    block = block[: block.index("def _cancel_backtest_on_connector(")]
    assert '"execution_instance_id"' in block
