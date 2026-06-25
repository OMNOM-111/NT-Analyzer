"""Stage 2 mismatch diagnostic engine tests (pure functions).

Run from NT-Analyzer/ root:
    python -m tests.test_mismatch_report
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import mismatch_report as m  # noqa: E402
from app import performance as perf  # noqa: E402

PASSED: List[str] = []
FAILED: List[Tuple[str, str]] = []


def case(name: str):
    def deco(fn):
        def wrap():
            try:
                fn()
                PASSED.append(name)
                print(f"  PASS  {name}")
            except Exception as e:
                FAILED.append((name, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"))
                print(f"  FAIL  {name}: {e}")
        return wrap
    return deco


@case("cell digits extraction")
def t01() -> None:
    assert m._cell_digits("CELL-015") == "015"
    assert m._cell_digits("015") == "015"
    assert m._cell_digits(None) == ""


@case("same-bar fill detection flags High-fill optimism")
def t02() -> None:
    # 4 of 5 trades open+close in the same minute with positive ticks.
    trades = [
        {"entry_time_utc": "2026-05-13T13:36:00Z", "exit_time_utc": "2026-05-13T13:36:00Z", "pnl_ticks": 38, "pnl_currency": 19.0},
        {"entry_time_utc": "2026-05-13T13:37:00Z", "exit_time_utc": "2026-05-13T13:37:00Z", "pnl_ticks": 38, "pnl_currency": 19.0},
        {"entry_time_utc": "2026-05-13T13:38:00Z", "exit_time_utc": "2026-05-13T13:38:30Z", "pnl_ticks": 38, "pnl_currency": 19.0},
        {"entry_time_utc": "2026-05-13T13:40:00Z", "exit_time_utc": "2026-05-13T13:40:10Z", "pnl_ticks": 38, "pnl_currency": 19.0},
        {"entry_time_utc": "2026-05-13T13:45:00Z", "exit_time_utc": "2026-05-13T13:55:00Z", "pnl_ticks": -20, "pnl_currency": -10.0},
    ]
    s = m.same_bar_fill_stats(trades, bar_seconds=60)
    assert s["trades"] == 5, s
    assert s["same_bar_fills"] == 4, s
    assert s["same_bar_winners"] == 4, s
    assert s["same_bar_fraction"] == 0.8, s
    assert s["optimistic_fill_suspected"] is True, s


@case("same-bar detection stays calm on realistic holds")
def t03() -> None:
    trades = [
        {"entry_time_utc": "2026-05-13T13:36:00Z", "exit_time_utc": "2026-05-13T13:50:00Z", "pnl_ticks": 12},
        {"entry_time_utc": "2026-05-13T14:00:00Z", "exit_time_utc": "2026-05-13T14:09:00Z", "pnl_ticks": -8},
    ]
    s = m.same_bar_fill_stats(trades)
    assert s["same_bar_fills"] == 0, s
    assert s["optimistic_fill_suspected"] is False, s


@case("decision: insufficient sample -> observation")
def t04() -> None:
    d = m.decide("CELL-016", runtime_pnl=-93.1, scored_trades=24,
                 after_best=1902.0, after_worst=1671.0,
                 same_bar={"optimistic_fill_suspected": True, "same_bar_fraction": 0.91},
                 critical_mismatches=0)
    assert d["decision"] == "observation", d
    assert d["relaunch_allowed"] is False, d


@case("decision: positive backtest + negative runtime + same-bar -> needs_work")
def t05() -> None:
    d = m.decide("CELL-015", runtime_pnl=-388.4, scored_trades=156,
                 after_best=3137.0, after_worst=2906.0,
                 same_bar={"optimistic_fill_suspected": True, "same_bar_fraction": 0.91},
                 critical_mismatches=1)
    assert d["decision"] == "needs_work", d
    assert d["relaunch_allowed"] is False, d
    assert "fill model" in d["reason"], d


@case("decision: surviving edge with clean runtime -> relaunch_candidate, gated by criticals")
def t06() -> None:
    clean = {"optimistic_fill_suspected": False, "same_bar_fraction": 0.1}
    d = m.decide("CELL-XYZ", runtime_pnl=120.0, scored_trades=80,
                 after_best=400.0, after_worst=120.0, same_bar=clean, critical_mismatches=0)
    assert d["decision"] == "relaunch_candidate", d
    assert d["relaunch_allowed"] is True, d
    # A single critical mismatch must veto the relaunch even if the edge survives.
    d2 = m.decide("CELL-XYZ", runtime_pnl=120.0, scored_trades=80,
                  after_best=400.0, after_worst=120.0, same_bar=clean, critical_mismatches=1)
    assert d2["relaunch_allowed"] is False, d2


@case("criteria matrix covers every operator dimension and flags 3-way contract drift")
def t07() -> None:
    profile = {
        "current_contract": "MNQ 06-26", "instrument": "MNQ 06-26",
        "trade_window_pt": "06:35-08:30",
        "locked_parameters": {"SessionTemplateName": "CME US Index Futures RTH",
                              "RewardRiskRatio": 4.0, "TradeStartTime": 635, "TradeEndTime": 830,
                              "MinStopTicks": 4, "MaxStopTicks": 10},
        "test_period": {"from_utc": "2024-01-01T00:00:00Z", "to_utc": "2025-12-31T23:59:59Z"},
    }
    job = {
        "instrument": "MNQ 09-26",
        "timeframe": {"bars_period_type": "Minute", "value": 1},
        "period": {"from_utc": "2026-05-13T00:00:00Z", "to_utc": "2026-06-16T22:00:00Z"},
        "strategy": {"parameters": {"TradeStartTime": 635, "TradeEndTime": 830,
                                    "RewardRiskRatio": 4.0, "MinStopTicks": 4, "MaxStopTicks": 10,
                                    "SessionTemplateName": "CME US Index Futures RTH"}},
        "execution": {"session_template": "CME US Index Futures RTH", "timezone": "UTC",
                      "order_fill_resolution": "High", "calculate": "OnBarClose",
                      "is_tick_replay": False, "slippage_ticks": 2, "round_turn_commission": 1.9},
    }
    rfacts = {
        "traded_contracts": ["MNQ SEP26"],
        "observed_pt_window": "06:35-08:29",
        "categories": {"normal": 156, "unmatched": 2, "account_level": 4},
        "attributed_exec_pct": 0.74, "rows_with_iid_pct": 0.0,
        "distinct_runtime_instance_ids": 0,
        "account_rejected_orders": 88, "account_partial_fills": 3,
        "runtime_commission_seen": False, "runtime_slippage_note": "n/a",
        "concurrent_strategies": "shared book",
    }
    sb = {"optimistic_fill_suspected": True, "same_bar_fraction": 0.91,
          "same_bar_fills": 313, "same_bar_winners": 300, "trades": 344, "same_bar_avg_ticks": 38.0}
    crit = m.compare_conditions(profile, job, rfacts, sb)
    names = {c["criterion"] for c in crit}
    for required in ("trading_windows", "session_template", "timezone_pacific", "fill_model",
                     "execution_granularity", "commission", "slippage", "rollover_contract",
                     "instrument_root", "strategy_parameters", "stop_target_logic",
                     "order_handling", "rejected_orders", "partial_fills", "unmatched_exits",
                     "account_level_collisions", "strategy_attribution",
                     "runtime_instance_mapping", "demo_vs_historical_period"):
        assert required in names, (required, names)
    by = {c["criterion"]: c for c in crit}
    # 3-way contract drift (profile 06-26 / backtest 09-26 / runtime SEP26) is a mismatch.
    assert by["rollover_contract"]["status"] == m.STATUS_MISMATCH, by["rollover_contract"]
    # session template matches between profile and backtest.
    assert by["session_template"]["status"] == m.STATUS_MATCH, by["session_template"]
    # UTC backtest timezone vs PT windows is a mismatch.
    assert by["timezone_pacific"]["status"] == m.STATUS_MISMATCH, by["timezone_pacific"]
    # same-bar optimism makes the fill model a critical mismatch.
    assert by["fill_model"]["status"] == m.STATUS_MISMATCH, by["fill_model"]
    assert by["fill_model"]["severity"] == m.SEV_CRITICAL, by["fill_model"]
    # instrument root matches (both MNQ).
    assert by["instrument_root"]["status"] == m.STATUS_MATCH, by["instrument_root"]


@case("attribution breakdown rolls up only normal trades by day/week/cycle")
def t08() -> None:
    trades = [
        {"date_pt": "2026-05-13", "category": "normal", "pnl": 10.0, "cell_id": "015",
         "trading_cycle_id": "CYCLE-A", "strategy_class": "X", "entry_strategy_class": "X"},
        {"date_pt": "2026-05-14", "category": "normal", "pnl": -4.0, "cell_id": "015",
         "trading_cycle_id": "CYCLE-A", "strategy_class": "X", "entry_strategy_class": "X"},
        {"date_pt": "2026-05-14", "category": "account_level", "pnl": 999.0, "cell_id": "015",
         "trading_cycle_id": "", "strategy_class": "X", "entry_strategy_class": "X"},
    ]
    b = m.attribution_breakdown(trades)
    assert b["categories"] == {"normal": 2, "account_level": 1}, b
    # account_level PnL (999) must NOT pollute any rollup.
    assert b["scored_per_day"] == {"2026-05-13": 10.0, "2026-05-14": -4.0}, b
    assert b["scored_per_cycle"] == {"CYCLE-A": 6.0}, b
    assert len(b["trades"]) == 3, b  # all trades still listed for traceability


def main() -> int:
    for fn in (t01, t02, t03, t04, t05, t06, t07, t08):
        fn()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for name, err in FAILED:
            print(f"\n--- {name} ---\n{err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
