"""Stage 2 rerun/comparison scaffold tests.

Run from NT-Analyzer/ root:
    python -m tests.test_rerun_compare
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import rerun_compare as rc  # noqa: E402

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


@case("rerun templates use current contract, High fill and slip/commission stress")
def t01() -> None:
    jobs = rc.build_rerun_job_templates(
        "CELL-015", "NTAMnqLiquiditySweepReversalC015",
        "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z")
    # 2 slippage x 2 commission = 4 stress jobs.
    assert len(jobs) == 4, jobs
    for j in jobs:
        assert j["instrument"] == "MNQ SEP26", j  # current contract, not 06-26
        assert j["execution"]["order_fill_resolution"] == "High", j
        assert j["execution"]["slippage_ticks"] in (2, 3), j
        assert j["execution"]["commission_template"] in rc.STRESS_COMMISSION_TEMPLATES, j
        assert j["execution"]["session_template"] == "CME US Index Futures RTH", j
        assert j["origin"]["stage2_rerun"] is True, j
    slips = sorted({j["execution"]["slippage_ticks"] for j in jobs})
    assert slips == [2, 3], slips


@case("unknown relaunch cell is rejected")
def t02() -> None:
    try:
        rc.build_rerun_job_templates("CELL-999", "X", "a", "b")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


@case("comparison flags destroyed edge when honest backtest is unprofitable")
def t03() -> None:
    old = {"metrics": {"trade_count": 156, "net_profit": 400.0, "winning_pct": 55.0, "profit_factor": 1.8}}
    runtime = {"scored_trade_count": 156, "pnl": -435.90, "win_rate": 21.8, "profit_factor_pct": -40.0}
    new = {"metrics": {"trade_count": 140, "net_profit": -210.0, "winning_pct": 30.0, "profit_factor": 0.7}}
    cmp = rc.build_comparison("C015", old, runtime, new)
    assert cmp["verdict"] == "edge_destroyed", cmp
    assert cmp["relaunch_allowed"] is False, cmp
    assert cmp["runtime"]["net_pnl"] == -435.90, cmp
    assert cmp["before"]["trades"] == 156, cmp
    assert cmp["deltas"]["net_pnl_after_vs_before"] == -610.0, cmp


@case("comparison needs enough scored trades before judging")
def t04() -> None:
    new = {"metrics": {"trade_count": 5, "net_profit": 50.0, "winning_pct": 60.0, "profit_factor": 2.0}}
    cmp = rc.build_comparison("C011", None, None, new)
    assert cmp["verdict"] == "insufficient", cmp
    assert cmp["relaunch_allowed"] is False, cmp


@case("comparison allows relaunch only when stressed edge survives")
def t05() -> None:
    new = {"metrics": {"trade_count": 80, "net_profit": 320.0, "winning_pct": 48.0, "profit_factor": 1.4}}
    runtime = {"scored_trade_count": 80, "pnl": 50.0, "win_rate": 45.0, "profit_factor_pct": 10.0}
    cmp = rc.build_comparison("C003", None, runtime, new)
    assert cmp["verdict"] == "edge_survives", cmp
    assert cmp["relaunch_allowed"] is True, cmp
    # runtime profit_factor derived from profit_factor_pct
    assert abs(cmp["runtime"]["profit_factor"] - 1.10) < 1e-9, cmp


def main() -> int:
    for fn in (t01, t02, t03, t04, t05):
        fn()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for name, err in FAILED:
            print(f"\n--- {name} ---\n{err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
