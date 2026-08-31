"""Performance Center tests.

Run from NT-Analyzer/ root:
    python -m tests.test_performance
"""
from __future__ import annotations

import json
import csv
import io
import os
import shutil
import sys
import tempfile
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import ops  # noqa: E402
from app import performance  # noqa: E402


PASSED: List[str] = []
FAILED: List[Tuple[str, str]] = []


def _now_iso(offset_sec: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_sec)).isoformat(timespec="seconds")


def _set_temp_root(tmp: Path):
    original_project_root = ops._project_root
    original_data_root = os.environ.get("NTA_DATA_ROOT")
    original_dev_root = os.environ.get("NTA_STAGING_DATA_ROOT")
    os.environ["NTA_DATA_ROOT"] = str(tmp / "data")
    os.environ["NTA_STAGING_DATA_ROOT"] = str(tmp / "development-data")
    ops._project_root = lambda: tmp  # type: ignore[assignment]
    (tmp / "data" / "runtime").mkdir(parents=True, exist_ok=True)
    (tmp / "data" / "ops").mkdir(parents=True, exist_ok=True)

    def restore() -> None:
        ops._project_root = original_project_root  # type: ignore[assignment]
        if original_data_root is None:
            os.environ.pop("NTA_DATA_ROOT", None)
        else:
            os.environ["NTA_DATA_ROOT"] = original_data_root
        if original_dev_root is None:
            os.environ.pop("NTA_STAGING_DATA_ROOT", None)
        else:
            os.environ["NTA_STAGING_DATA_ROOT"] = original_dev_root

    return restore


def _write_runtime(tmp: Path, strategies: List[Dict[str, Any]], executions: List[Dict[str, Any]]) -> None:
    rdir = tmp / "data" / "runtime"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "heartbeat.json").write_text(json.dumps({
        "timestamp_utc": _now_iso(-2),
        "exporter_version": "test",
    }), encoding="utf-8")
    (rdir / "accounts.json").write_text(json.dumps({
        "generated_at_utc": _now_iso(-2),
        "accounts": [{"account_name": "DEMO3369390", "account_mode": "demo"}],
    }), encoding="utf-8")
    (rdir / "strategies.json").write_text(json.dumps({
        "generated_at_utc": _now_iso(-2),
        "strategies": strategies,
    }), encoding="utf-8")
    (rdir / "executions.jsonl").write_text(
        "\n".join(json.dumps(row) for row in executions) + "\n",
        encoding="utf-8",
    )


def _iso_for_pt_date(date_pt: str, hh: int, mm: int) -> str:
    # Use noon-ish UTC offsets that are safely inside the requested PT date for tests.
    y, m, d = [int(x) for x in date_pt.split("-")]
    return datetime(y, m, d, hh + 8, mm, tzinfo=timezone.utc).isoformat(timespec="seconds")


def case(name: str):
    def deco(fn):
        def wrap():
            tmp = Path(tempfile.mkdtemp(prefix="performance_test_"))
            restore = _set_temp_root(tmp)
            try:
                fn(tmp)
                PASSED.append(name)
                print(f"  PASS  {name}")
            except AssertionError as e:
                FAILED.append((name, f"AssertionError: {e}\n{traceback.format_exc()}"))
                print(f"  FAIL  {name}: {e}")
            except Exception as e:
                FAILED.append((name, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"))
                print(f"  ERR   {name}: {e}")
            finally:
                restore()
                shutil.rmtree(tmp, ignore_errors=True)
        return wrap
    return deco


@case("t01: performance groups P/L after commission by strategy and instrument")
def t01(tmp: Path) -> None:
    today = ops._to_pt(datetime.now(timezone.utc)).date().isoformat()
    strategies = [
        {
            "account_name": "DEMO3369390",
            "account_mode": "demo",
            "strategy_id": "ntamnqliquiditysweepreversalc015",
            "strategy_class": "NTAMnqLiquiditySweepReversalC015",
            "strategy_name": "NTAMnqLiquiditySweepReversalC015",
            "instrument": "MNQ JUN26",
            "timeframe": "1 Minute",
            "enabled": True,
            "runtime_instance_id": "iid-c015",
            "params": {"RoundTurnCommission": 1.90},
        },
        {
            "account_name": "DEMO3369390",
            "account_mode": "demo",
            "strategy_id": "ntamnqopendriveshortscalpc016",
            "strategy_class": "NTAMnqOpenDriveShortScalpC016",
            "strategy_name": "NTAMnqOpenDriveShortScalpC016",
            "instrument": "MNQ JUN26",
            "timeframe": "1 Minute",
            "enabled": True,
            "runtime_instance_id": "iid-c016",
            "params": {"RoundTurnCommission": 1.90},
        },
        {
            "account_name": "DEMO3369390",
            "account_mode": "demo",
            "strategy_id": "b1stop24mgc5mc003",
            "strategy_class": "B1Stop24MGC5mC003",
            "strategy_name": "B1Stop24MGC5mC003",
            "instrument": "MGC JUN26",
            "timeframe": "5 Minute",
            "enabled": True,
            "runtime_instance_id": "iid-c003",
            "params": {"RoundTurnCommission": 1.90},
        },
    ]
    executions = [
        {"timestamp_utc": _iso_for_pt_date(today, 8, 30), "account_name": "DEMO3369390",
         "runtime_instance_id": "iid-c015", "strategy_class": "NTAMnqLiquiditySweepReversalC015",
         "strategy_id": "ntamnqliquiditysweepreversalc015", "instrument": "MNQ JUN26",
         "order_action": "Buy", "quantity": 1, "price": 100.0},
        {"timestamp_utc": _iso_for_pt_date(today, 8, 40), "account_name": "DEMO3369390",
         "runtime_instance_id": "iid-c015", "strategy_class": "NTAMnqLiquiditySweepReversalC015",
         "strategy_id": "ntamnqliquiditysweepreversalc015", "instrument": "MNQ JUN26",
         "order_action": "Sell", "quantity": 1, "price": 105.0},
        {"timestamp_utc": _iso_for_pt_date(today, 8, 35), "account_name": "DEMO3369390",
         "runtime_instance_id": "iid-c016", "strategy_class": "NTAMnqOpenDriveShortScalpC016",
         "strategy_id": "ntamnqopendriveshortscalpc016", "instrument": "MNQ JUN26",
         "order_action": "SellShort", "quantity": 1, "price": 100.0},
        {"timestamp_utc": _iso_for_pt_date(today, 8, 50), "account_name": "DEMO3369390",
         "runtime_instance_id": "iid-c016", "strategy_class": "NTAMnqOpenDriveShortScalpC016",
         "strategy_id": "ntamnqopendriveshortscalpc016", "instrument": "MNQ JUN26",
         "order_action": "BuyToCover", "quantity": 1, "price": 104.0},
        {"timestamp_utc": _iso_for_pt_date(today, 9, 10), "account_name": "DEMO3369390",
         "runtime_instance_id": "iid-c003", "strategy_class": "B1Stop24MGC5mC003",
         "strategy_id": "b1stop24mgc5mc003", "instrument": "MGC JUN26",
         "order_action": "Buy", "quantity": 1, "price": 2000.0},
        {"timestamp_utc": _iso_for_pt_date(today, 9, 30), "account_name": "DEMO3369390",
         "runtime_instance_id": "iid-c003", "strategy_class": "B1Stop24MGC5mC003",
         "strategy_id": "b1stop24mgc5mc003", "instrument": "MGC JUN26",
         "order_action": "Sell", "quantity": 1, "price": 2010.0},
    ]
    _write_runtime(tmp, strategies, executions)

    out = performance.build_performance_response(
        period="custom",
        from_date=today,
        to_date=today,
        account_name="DEMO3369390",
    )
    assert out["has_trades"] is True
    assert out["summary"]["trades"] == 3, out["summary"]
    assert out["summary"]["commission"] == 5.70, out["summary"]
    assert out["summary"]["pnl"] == 96.30, out["summary"]
    assert out["summary"]["win_rate"] == 66.7, out["summary"]
    assert out["summary"]["profit_factor_kind"] == "finite", out["summary"]

    strategies_by_cell = {row["cell"]: row for row in out["strategies"]}
    assert strategies_by_cell["003"]["pnl"] == 98.10, strategies_by_cell
    assert strategies_by_cell["015"]["pnl"] == 8.10, strategies_by_cell
    assert strategies_by_cell["016"]["pnl"] == -9.90, strategies_by_cell

    instruments = {row["instrument"]: row for row in out["instruments"]}
    assert instruments["MGC"]["pnl"] == 98.10, instruments
    assert instruments["MNQ"]["pnl"] == -1.80, instruments
    assert instruments["MGC"]["best_strategy"].startswith("003 "), instruments["MGC"]


@case("t01b: strategy totals aggregate across runtime instances")
def t01b_strategy_totals_merge_runtime_instances(tmp: Path) -> None:
    day = ops._to_pt(datetime.now(timezone.utc)).date().isoformat()
    strategies = [
        {
            "account_name": "DEMO3369390",
            "account_mode": "demo",
            "strategy_id": "ntamnqliquiditysweepreversalc015",
            "strategy_class": "NTAMnqLiquiditySweepReversalC015",
            "strategy_name": "NTAMnqLiquiditySweepReversalC015",
            "instrument": "MNQ JUN26",
            "timeframe": "1 Minute",
            "runtime_instance_id": "iid-c015-a",
            "params": {"RoundTurnCommission": 1.90},
        },
        {
            "account_name": "DEMO3369390",
            "account_mode": "demo",
            "strategy_id": "ntamnqliquiditysweepreversalc015",
            "strategy_class": "NTAMnqLiquiditySweepReversalC015",
            "strategy_name": "NTAMnqLiquiditySweepReversalC015",
            "instrument": "MNQ JUN26",
            "timeframe": "1 Minute",
            "runtime_instance_id": "iid-c015-b",
            "params": {"RoundTurnCommission": 1.90},
        },
    ]
    executions = [
        {"timestamp_utc": _iso_for_pt_date(day, 8, 30), "account_name": "DEMO3369390",
         "runtime_instance_id": "iid-c015-a", "strategy_class": "NTAMnqLiquiditySweepReversalC015",
         "strategy_id": "ntamnqliquiditysweepreversalc015", "instrument": "MNQ JUN26",
         "order_action": "Buy", "quantity": 1, "price": 100.0},
        {"timestamp_utc": _iso_for_pt_date(day, 8, 40), "account_name": "DEMO3369390",
         "runtime_instance_id": "iid-c015-a", "strategy_class": "NTAMnqLiquiditySweepReversalC015",
         "strategy_id": "ntamnqliquiditysweepreversalc015", "instrument": "MNQ JUN26",
         "order_action": "Sell", "quantity": 1, "price": 105.0},
        {"timestamp_utc": _iso_for_pt_date(day, 9, 30), "account_name": "DEMO3369390",
         "runtime_instance_id": "iid-c015-b", "strategy_class": "NTAMnqLiquiditySweepReversalC015",
         "strategy_id": "ntamnqliquiditysweepreversalc015", "instrument": "MNQ JUN26",
         "order_action": "SellShort", "quantity": 1, "price": 110.0},
        {"timestamp_utc": _iso_for_pt_date(day, 9, 40), "account_name": "DEMO3369390",
         "runtime_instance_id": "iid-c015-b", "strategy_class": "NTAMnqLiquiditySweepReversalC015",
         "strategy_id": "ntamnqliquiditysweepreversalc015", "instrument": "MNQ JUN26",
         "order_action": "BuyToCover", "quantity": 1, "price": 108.0},
    ]
    _write_runtime(tmp, strategies, executions)
    out = performance.build_performance_response(
        period="custom",
        from_date=day,
        to_date=day,
        account_name="DEMO3369390",
    )
    rows = [row for row in out["strategies"] if row["cell"] == "015"]
    assert len(rows) == 1, rows
    assert rows[0]["trades"] == 2, rows[0]
    assert rows[0]["pnl"] == 10.20, rows[0]
    assert rows[0]["runtime_instance_count"] == 2, rows[0]
    assert rows[0]["runtime_instance_ids"] == ["iid-c015-a", "iid-c015-b"], rows[0]


@case("t02: empty period returns zero P/L and no PF")
def t02(tmp: Path) -> None:
    today = ops._to_pt(datetime.now(timezone.utc)).date().isoformat()
    old = (ops._to_pt(datetime.now(timezone.utc)).date() - timedelta(days=10)).isoformat()
    _write_runtime(tmp, [], [{
        "timestamp_utc": _iso_for_pt_date(today, 8, 30),
        "account_name": "DEMO3369390",
        "strategy_id": "x",
        "strategy_class": "X001",
        "instrument": "MNQ JUN26",
        "role": "exit",
        "quantity": 1,
        "realized_pnl": 10.0,
    }])
    out = performance.build_performance_response(
        period="custom",
        from_date=old,
        to_date=old,
        account_name="DEMO3369390",
    )
    assert out["has_trades"] is False
    assert out["empty_message"] == "За выбранный период сделок нет."
    assert out["summary"]["pnl"] == 0.0
    assert out["summary"]["commission"] == 0.0
    assert out["summary"]["win_rate"] is None
    assert out["summary"]["profit_factor_kind"] == "none"


@case("t03: static Performance Center page and API route are wired")
def t03(tmp: Path) -> None:
    html = (ROOT / "legacy_viewer" / "static" / "performance.html").read_text(encoding="utf-8")
    js = (ROOT / "legacy_viewer" / "static" / "performance.js").read_text(encoding="utf-8")
    server = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    assert "ЦЕНТР ДОХОДНОСТИ" in html
    assert "Скачать все сделки" in html
    assert "/api/performance" in js
    assert 'period: "month"' in js
    assert 'if path == "/api/performance":' in server
    assert 'if path == "/api/performance/trades.csv":' in server


@case("t04: trades CSV export uses the unified live trade format")
def t04(tmp: Path) -> None:
    today = ops._to_pt(datetime.now(timezone.utc)).date().isoformat()
    strategies = [{
        "account_name": "DEMO3369390",
        "account_mode": "demo",
        "strategy_id": "ntamnqliquiditysweepreversalc015",
        "strategy_class": "NTAMnqLiquiditySweepReversalC015",
        "strategy_name": "NTAMnqLiquiditySweepReversalC015",
        "instrument": "MNQ JUN26",
        "runtime_instance_id": "iid-c015",
        "params": {"RoundTurnCommission": 1.90},
    }]
    executions = [
        {"timestamp_utc": _iso_for_pt_date(today, 8, 30), "account_name": "DEMO3369390",
         "runtime_instance_id": "iid-c015", "strategy_class": "NTAMnqLiquiditySweepReversalC015",
         "strategy_id": "ntamnqliquiditysweepreversalc015", "instrument": "MNQ JUN26",
         "order_action": "Buy", "quantity": 1, "price": 100.0,
         "order_id": "entry-1", "execution_id": "exec-entry-1"},
        {"timestamp_utc": _iso_for_pt_date(today, 8, 40), "account_name": "DEMO3369390",
         "runtime_instance_id": "iid-c015", "strategy_class": "NTAMnqLiquiditySweepReversalC015",
         "strategy_id": "ntamnqliquiditysweepreversalc015", "instrument": "MNQ JUN26",
         "order_action": "Sell", "quantity": 1, "price": 105.0,
         "order_id": "exit-1", "execution_id": "exec-exit-1", "exit_reason": "target"},
    ]
    _write_runtime(tmp, strategies, executions)

    filename, data = performance.build_trades_csv(
        period="custom",
        from_date=today,
        to_date=today,
        account_name="DEMO3369390",
    )
    assert filename.startswith("nta-trades-DEMO3369390-"), filename
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["trade_no"] == "1", row
    assert row["trade_id"].startswith("DEMO3369390|"), row
    assert row["direction"] == "long", row
    assert row["entry_order_id"] == "entry-1", row
    assert row["exit_order_id"] == "exit-1", row
    assert row["entry_execution_id"] == "exec-entry-1", row
    assert row["exit_execution_id"] == "exec-exit-1", row
    assert row["commission"] == "1.9", row
    assert row["pnl"] == "8.1", row
    assert row["exit_reason"] == "target", row


@case("t05: unmapped exit closing a mapped entry is account_level, excluded from strategy PnL")
def t05_entry_strategy_attribution_for_unmapped_exit(tmp: Path) -> None:
    day = "2026-05-21"
    executions = [
        {
            "timestamp_utc": _iso_for_pt_date(day, 8, 30),
            "account_name": "DEMO3369390",
            "runtime_instance_id": "iid-c015",
            "strategy_class": "NTAMnqLiquiditySweepReversalC015",
            "strategy_id": "ntamnqliquiditysweepreversalc015",
            "strategy_name": "NTAMnqLiquiditySweepReversalC015",
            "instrument": "MNQ JUN26",
            "order_action": "SellShort",
            "quantity": 1,
            "price": 19000.0,
            "order_id": "entry-c015-1",
            "execution_id": "entry-exec-c015-1",
        },
        {
            "timestamp_utc": _iso_for_pt_date(day, 8, 35),
            "account_name": "DEMO3369390",
            "runtime_instance_id": "",
            "strategy_class": "",
            "strategy_id": "Short",
            "strategy_name": "",
            "instrument": "MNQ JUN26",
            "order_action": "BuyToCover",
            "quantity": 1,
            "price": 18996.0,
            "order_id": "exit-c015-1",
            "execution_id": "exit-exec-c015-1",
        },
    ]
    _write_runtime(tmp, [], executions)

    _resolved, trades, _dedupe, _all_count = performance._closed_trades_for_request(
        period="custom",
        from_date=day,
        to_date=day,
        account_name="DEMO3369390",
    )
    assert len(trades) == 1, trades
    trade = trades[0]
    # Entry strategy labels are preserved for display/traceability...
    assert trade["unmapped"] is False, trade
    assert trade["strategy_class"] == "NTAMnqLiquiditySweepReversalC015", trade
    assert trade["strategy_id"] == "ntamnqliquiditysweepreversalc015", trade
    assert trade["runtime_instance_id"] == "iid-c015", trade
    assert trade["entry_strategy_class"] == "NTAMnqLiquiditySweepReversalC015", trade
    # ...but the exit is unmapped, so the pairing is account-level, not a clean
    # strategy trade (Stage 2 strict attribution).
    assert trade["category"] == performance.TRADE_CATEGORY_ACCOUNT_LEVEL, trade

    out = performance.build_performance_response(
        period="custom",
        from_date=day,
        to_date=day,
        account_name="DEMO3369390",
    )
    # Account net still sees the trade...
    assert out["summary"]["trades"] == 1, out["summary"]
    assert out["categories"]["counts"]["account_level"] == 1, out["categories"]
    # ...but strategy-level scoring excludes it entirely.
    assert out["strategy_summary"]["trades"] == 0, out["strategy_summary"]
    by_class = {row["strategy_class"]: row for row in out["strategies"]}
    strat = by_class["NTAMnqLiquiditySweepReversalC015"]
    assert strat["pnl"] == 0.0, strat
    assert strat["scored_trade_count"] == 0, strat
    assert strat["excluded_trade_count"] == 1, strat
    assert strat["category_breakdown"]["counts"]["account_level"] == 1, strat


@case("t06: multiple unmapped exits close mapped strategy lots FIFO")
def t06_multiple_unmapped_exits_close_strategy_lots_fifo(tmp: Path) -> None:
    day = "2026-05-21"
    executions = [
        {
            "timestamp_utc": _iso_for_pt_date(day, 8, 30),
            "account_name": "DEMO3369390",
            "runtime_instance_id": "iid-c012",
            "strategy_class": "NTAMnqMicroOrbOpenScalp",
            "strategy_id": "ntamnqmicroorbopenscalp",
            "strategy_name": "NTAMnqMicroOrbOpenScalp",
            "instrument": "MNQ JUN26",
            "order_action": "SellShort",
            "quantity": 1,
            "price": 100.0,
            "order_id": "entry-c012",
            "execution_id": "entry-exec-c012",
        },
        {
            "timestamp_utc": _iso_for_pt_date(day, 8, 31),
            "account_name": "DEMO3369390",
            "runtime_instance_id": "iid-c014",
            "strategy_class": "NTAMnqFullSessionOrbRetestScalpC014",
            "strategy_id": "ntamnqfullsessionorbretestscalpc014",
            "strategy_name": "NTAMnqFullSessionOrbRetestScalpC014",
            "instrument": "MNQ JUN26",
            "order_action": "SellShort",
            "quantity": 1,
            "price": 100.0,
            "order_id": "entry-c014",
            "execution_id": "entry-exec-c014",
        },
        {
            "timestamp_utc": _iso_for_pt_date(day, 8, 35),
            "account_name": "DEMO3369390",
            "runtime_instance_id": "",
            "strategy_class": "",
            "strategy_id": "Short",
            "strategy_name": "",
            "instrument": "MNQ JUN26",
            "order_action": "BuyToCover",
            "quantity": 1,
            "price": 101.0,
            "order_id": "exit-unmapped-1",
            "execution_id": "exit-exec-unmapped-1",
        },
        {
            "timestamp_utc": _iso_for_pt_date(day, 8, 36),
            "account_name": "DEMO3369390",
            "runtime_instance_id": "",
            "strategy_class": "",
            "strategy_id": "Short",
            "strategy_name": "",
            "instrument": "MNQ JUN26",
            "order_action": "BuyToCover",
            "quantity": 1,
            "price": 102.0,
            "order_id": "exit-unmapped-2",
            "execution_id": "exit-exec-unmapped-2",
        },
    ]
    _write_runtime(tmp, [], executions)

    _resolved, trades, _dedupe, _all_count = performance._closed_trades_for_request(
        period="custom",
        from_date=day,
        to_date=day,
        account_name="DEMO3369390",
    )
    assert len(trades) == 2, trades
    assert [t["strategy_class"] for t in trades] == [
        "NTAMnqMicroOrbOpenScalp",
        "NTAMnqFullSessionOrbRetestScalpC014",
    ], trades
    assert [t["unmapped"] for t in trades] == [False, False], trades
    assert [t["exit_order_id"] for t in trades] == ["exit-unmapped-1", "exit-unmapped-2"], trades
    # Unmapped exits closing mapped entries are account-level under strict policy.
    assert [t["category"] for t in trades] == [
        performance.TRADE_CATEGORY_ACCOUNT_LEVEL,
        performance.TRADE_CATEGORY_ACCOUNT_LEVEL,
    ], trades


@case("t07: clean same-strategy round trip is a normal, scored trade")
def t07_normal_round_trip(tmp: Path) -> None:
    day = "2026-05-21"
    base = {
        "account_name": "DEMO3369390",
        "runtime_instance_id": "iid-c015",
        "strategy_class": "NTAMnqLiquiditySweepReversalC015",
        "strategy_id": "ntamnqliquiditysweepreversalc015",
        "strategy_name": "NTAMnqLiquiditySweepReversalC015",
        "instrument": "MNQ JUN26",
    }
    executions = [
        {**base, "timestamp_utc": _iso_for_pt_date(day, 8, 30), "order_action": "SellShort",
         "quantity": 1, "price": 19000.0, "order_id": "e1", "execution_id": "ex1"},
        {**base, "timestamp_utc": _iso_for_pt_date(day, 8, 35), "order_action": "BuyToCover",
         "quantity": 1, "price": 18996.0, "order_id": "x1", "execution_id": "xe1"},
    ]
    _write_runtime(tmp, [], executions)
    _resolved, trades, _dedupe, _all = performance._closed_trades_for_request(
        period="custom", from_date=day, to_date=day, account_name="DEMO3369390")
    assert len(trades) == 1, trades
    assert trades[0]["category"] == performance.TRADE_CATEGORY_NORMAL, trades[0]
    out = performance.build_performance_response(
        period="custom", from_date=day, to_date=day, account_name="DEMO3369390")
    assert out["strategy_summary"]["trades"] == 1, out["strategy_summary"]
    by_class = {row["strategy_class"]: row for row in out["strategies"]}
    assert by_class["NTAMnqLiquiditySweepReversalC015"]["pnl"] == 6.10, by_class


@case("t08: same-root contract roll between entry and exit is rollover_mismatch")
def t08_rollover_mismatch(tmp: Path) -> None:
    day = "2026-05-21"
    base = {
        "account_name": "DEMO3369390",
        "runtime_instance_id": "iid-c015",
        "strategy_class": "NTAMnqLiquiditySweepReversalC015",
        "strategy_id": "ntamnqliquiditysweepreversalc015",
        "strategy_name": "NTAMnqLiquiditySweepReversalC015",
    }
    executions = [
        {**base, "instrument": "MNQ JUN26", "timestamp_utc": _iso_for_pt_date(day, 8, 30),
         "order_action": "SellShort", "quantity": 1, "price": 19000.0, "order_id": "e1", "execution_id": "ex1"},
        {**base, "instrument": "MNQ SEP26", "timestamp_utc": _iso_for_pt_date(day, 8, 35),
         "order_action": "BuyToCover", "quantity": 1, "price": 18996.0, "order_id": "x1", "execution_id": "xe1"},
    ]
    _write_runtime(tmp, [], executions)
    _resolved, trades, _dedupe, _all = performance._closed_trades_for_request(
        period="custom", from_date=day, to_date=day, account_name="DEMO3369390")
    assert len(trades) == 1, trades
    assert trades[0]["category"] == performance.TRADE_CATEGORY_ROLLOVER, trades[0]
    out = performance.build_performance_response(
        period="custom", from_date=day, to_date=day, account_name="DEMO3369390")
    assert out["strategy_summary"]["trades"] == 0, out["strategy_summary"]
    assert out["categories"]["counts"]["rollover_mismatch"] == 1, out["categories"]


@case("t09: opposing fills from different mapped strategies never cross-pair")
def t09_cross_strategy_unmatched(tmp: Path) -> None:
    day = "2026-05-21"
    executions = [
        {"account_name": "DEMO3369390", "runtime_instance_id": "iid-c015",
         "strategy_class": "NTAMnqLiquiditySweepReversalC015",
         "strategy_id": "ntamnqliquiditysweepreversalc015",
         "strategy_name": "NTAMnqLiquiditySweepReversalC015", "instrument": "MNQ JUN26",
         "timestamp_utc": _iso_for_pt_date(day, 8, 30), "order_action": "SellShort",
         "quantity": 1, "price": 19000.0, "order_id": "e1", "execution_id": "ex1"},
        {"account_name": "DEMO3369390", "runtime_instance_id": "iid-c016",
         "strategy_class": "NTAMnqOpenDriveShortScalpC016",
         "strategy_id": "ntamnqopendriveshortscalpc016",
         "strategy_name": "NTAMnqOpenDriveShortScalpC016", "instrument": "MNQ JUN26",
         "timestamp_utc": _iso_for_pt_date(day, 8, 35), "order_action": "BuyToCover",
         "quantity": 1, "price": 18996.0, "order_id": "x1", "execution_id": "xe1"},
    ]
    _write_runtime(tmp, [], executions)
    _resolved, trades, _dedupe, _all = performance._closed_trades_for_request(
        period="custom", from_date=day, to_date=day, account_name="DEMO3369390")
    # Each mapped strategy keeps its own FIFO book: a C016 buy must NOT close a
    # C015 short. Both positions stay open -> no contaminated closed trade.
    assert trades == [], trades
    out = performance.build_performance_response(
        period="custom", from_date=day, to_date=day, account_name="DEMO3369390")
    assert out["strategy_summary"]["trades"] == 0, out["strategy_summary"]


@case("t10: impossible multi-day FIFO pairing is unmatched")
def t10_multi_day_unmatched(tmp: Path) -> None:
    base = {
        "account_name": "DEMO3369390",
        "runtime_instance_id": "iid-c015",
        "strategy_class": "NTAMnqLiquiditySweepReversalC015",
        "strategy_id": "ntamnqliquiditysweepreversalc015",
        "strategy_name": "NTAMnqLiquiditySweepReversalC015",
        "instrument": "MNQ JUN26",
    }
    executions = [
        {**base, "timestamp_utc": _iso_for_pt_date("2026-05-14", 8, 30), "order_action": "SellShort",
         "quantity": 1, "price": 19000.0, "order_id": "e1", "execution_id": "ex1"},
        {**base, "timestamp_utc": _iso_for_pt_date("2026-05-20", 8, 35), "order_action": "BuyToCover",
         "quantity": 1, "price": 18996.0, "order_id": "x1", "execution_id": "xe1"},
    ]
    _write_runtime(tmp, [], executions)
    _resolved, trades, _dedupe, _all = performance._closed_trades_for_request(
        period="custom", from_date="2026-05-14", to_date="2026-05-20", account_name="DEMO3369390")
    assert len(trades) == 1, trades
    assert trades[0]["category"] == performance.TRADE_CATEGORY_UNMATCHED, trades[0]


@case("t11: trading_cycle_id mismatch downgrades a paired trade to unmatched")
def t11_cycle_mismatch(tmp: Path) -> None:
    day = "2026-05-21"
    base = {
        "account_name": "DEMO3369390",
        "runtime_instance_id": "iid-c015",
        "strategy_class": "NTAMnqLiquiditySweepReversalC015",
        "strategy_id": "ntamnqliquiditysweepreversalc015",
        "strategy_name": "NTAMnqLiquiditySweepReversalC015",
        "instrument": "MNQ JUN26",
    }
    executions = [
        {**base, "trading_cycle_id": "CYCLE-A", "timestamp_utc": _iso_for_pt_date(day, 8, 30),
         "order_action": "SellShort", "quantity": 1, "price": 19000.0, "order_id": "e1", "execution_id": "ex1"},
        {**base, "trading_cycle_id": "CYCLE-B", "timestamp_utc": _iso_for_pt_date(day, 8, 35),
         "order_action": "BuyToCover", "quantity": 1, "price": 18996.0, "order_id": "x1", "execution_id": "xe1"},
    ]
    _write_runtime(tmp, [], executions)
    _resolved, trades, _dedupe, _all = performance._closed_trades_for_request(
        period="custom", from_date=day, to_date=day, account_name="DEMO3369390")
    assert len(trades) == 1, trades
    assert trades[0]["category"] == performance.TRADE_CATEGORY_UNMATCHED, trades[0]
    assert trades[0]["entry_trading_cycle_id"] == "CYCLE-A", trades[0]
    assert trades[0]["exit_trading_cycle_id"] == "CYCLE-B", trades[0]


@case("t12: legacy C007/C127 signals resolve exact strategy attribution")
def t12_legacy_c007_c127_signal_attribution(tmp: Path) -> None:
    day = "2026-06-25"
    base = {
        "account_name": "DEMO3369390",
        "runtime_instance_id": "",
        "strategy_class": "",
        "strategy_id": "",
        "strategy_name": "",
        "attribution_status": "unresolved",
        "quantity": 1,
    }
    executions = [
        {**base, "timestamp_utc": _iso_for_pt_date(day, 8, 30),
         "instrument": "MGC AUG26", "order_action": "SellShort", "price": 4042.7,
         "order_name": "CapSnapS", "from_entry_signal": "",
         "order_id": "1716", "execution_id": "542849220920_1"},
        {**base, "timestamp_utc": _iso_for_pt_date(day, 8, 52),
         "instrument": "MGC AUG26", "order_action": "BuyToCover", "price": 4054.7,
         "order_name": "Stop loss", "from_entry_signal": "CapSnapS",
         "order_id": "1717", "execution_id": "542849220931_1"},
        {**base, "timestamp_utc": _iso_for_pt_date(day, 9, 5),
         "instrument": "MNQ SEP26", "order_action": "SellShort", "price": 29684.0,
         "order_name": "EntFieldS", "from_entry_signal": "",
         "order_id": "1719", "execution_id": "542849220948_1"},
        {**base, "timestamp_utc": _iso_for_pt_date(day, 9, 6),
         "instrument": "MNQ SEP26", "order_action": "BuyToCover", "price": 29713.25,
         "order_name": "Stop loss", "from_entry_signal": "EntFieldS",
         "order_id": "1720", "execution_id": "542849220958_1"},
    ]
    _write_runtime(tmp, [], executions)

    out = performance.build_performance_response(
        period="custom", from_date=day, to_date=day, account_name="DEMO3369390")
    assert out["summary"]["trades"] == 2, out["summary"]
    assert out["summary"]["pnl"] == -182.3, out["summary"]
    assert out["strategy_summary"]["trades"] == 2, out["strategy_summary"]
    assert out["categories"]["counts"]["normal"] == 2, out["categories"]
    assert out["categories"]["counts"]["unmapped"] == 0, out["categories"]

    by_class = {row["strategy_class"]: row for row in out["strategies"]}
    assert by_class["NTAMgcCapitulationSnapbackC007"]["pnl"] == -121.9, by_class
    assert by_class["NTAMnqEntropyTransitionFieldC127"]["pnl"] == -60.4, by_class


def main() -> int:
    for fn in (t01, t01b_strategy_totals_merge_runtime_instances, t02, t03, t04, t05_entry_strategy_attribution_for_unmapped_exit,
               t06_multiple_unmapped_exits_close_strategy_lots_fifo,
               t07_normal_round_trip, t08_rollover_mismatch, t09_cross_strategy_unmatched,
               t10_multi_day_unmatched, t11_cycle_mismatch,
               t12_legacy_c007_c127_signal_attribution):
        fn()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for name, err in FAILED:
            print(f"\n--- {name} ---\n{err}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
