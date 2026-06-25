"""Stage 2 final-decision engine tests (pure classifier).

Run from NT-Analyzer/ root:
    python -m tests.test_final_decision
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import final_decision as fd  # noqa: E402

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


@case("MNQ same-bar artifact -> final_reject (C015 shape)")
def t01() -> None:
    v = fd.classify_final("CELL-015", acceptance_pnl=617.38,
                          highfill_trades=344, highfill_net=3137.0,
                          tickreplay_trades=8, tickreplay_net=75.5,
                          runtime_trades=156, runtime_net=-388.4)
    assert v["decision"] == "final_reject", v
    assert v["trade_population_collapsed"] is True, v
    assert v["relaunch_allowed"] is False, v


@case("tick-replay negative + collapse -> final_reject (C017 shape)")
def t02() -> None:
    v = fd.classify_final("CELL-017", acceptance_pnl=79.1,
                          highfill_trades=120, highfill_net=432.5,
                          tickreplay_trades=6, tickreplay_net=-22.0,
                          runtime_trades=25, runtime_net=-127.5)
    assert v["decision"] == "final_reject", v
    assert v["trade_population_collapsed"] is True, v


@case("tiny sample both sides -> observation (MGC shape)")
def t03() -> None:
    v = fd.classify_final("CELL-001", acceptance_pnl=None,
                          highfill_trades=3, highfill_net=16.0,
                          tickreplay_trades=0, tickreplay_net=0.0,
                          runtime_trades=3, runtime_net=-72.6,
                          tickreplay_data_ok=False)
    assert v["decision"] == "observation", v
    assert v["trade_population_collapsed"] is False, v


@case("surviving tick edge + clean runtime -> relaunch")
def t04() -> None:
    v = fd.classify_final("CELL-X", acceptance_pnl=500.0,
                          highfill_trades=120, highfill_net=600.0,
                          tickreplay_trades=90, tickreplay_net=420.0,
                          runtime_trades=70, runtime_net=85.0,
                          critical_mismatches=0)
    assert v["decision"] == "relaunch", v
    assert v["relaunch_allowed"] is True, v


@case("surviving tick edge vetoed by critical mismatch")
def t05() -> None:
    v = fd.classify_final("CELL-X", acceptance_pnl=500.0,
                          highfill_trades=120, highfill_net=600.0,
                          tickreplay_trades=90, tickreplay_net=420.0,
                          runtime_trades=70, runtime_net=85.0,
                          critical_mismatches=2)
    assert v["decision"] != "relaunch", v
    assert v["relaunch_allowed"] is False, v


@case("surviving tick edge but negative runtime -> needs_work")
def t06() -> None:
    v = fd.classify_final("CELL-Y", acceptance_pnl=500.0,
                          highfill_trades=120, highfill_net=600.0,
                          tickreplay_trades=90, tickreplay_net=420.0,
                          runtime_trades=70, runtime_net=-150.0)
    assert v["decision"] == "needs_work", v


@case("no population collapse, no runtime -> observation not final_reject")
def t07() -> None:
    # High-fill and tick-replay both small; nothing proven.
    v = fd.classify_final("CELL-Z", acceptance_pnl=None,
                          highfill_trades=10, highfill_net=50.0,
                          tickreplay_trades=8, tickreplay_net=-5.0,
                          runtime_trades=4, runtime_net=-10.0)
    assert v["decision"] == "observation", v
    assert v["trade_population_collapsed"] is False, v


def main() -> int:
    for fn in (t01, t02, t03, t04, t05, t06, t07):
        fn()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for name, err in FAILED:
            print(f"\n--- {name} ---\n{err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
