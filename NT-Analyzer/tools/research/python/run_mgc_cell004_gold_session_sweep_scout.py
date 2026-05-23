"""Relaxed frequency scout for the MGC CELL-004 gold sweep engine."""
from __future__ import annotations

import sys
from typing import Any, List

import run_mgc_cell004_gold_session_sweep_engine as engine


engine.carrier.BUNDLE_NAME = "mgc_cell004_gold_session_sweep_scout"
engine.carrier.MIN_FREQ_TRADES = 40
engine.carrier.TARGET_FREQ_TRADES = 80


def variant(name: str, **overrides: Any) -> engine.carrier.Variant:
    params = engine.base_params()
    direction = str(overrides.pop("Direction", "both"))
    params["EnableLong"] = direction in {"long", "both"}
    params["EnableShort"] = direction in {"short", "both"}
    params.update({
        "TradeStartTime": 600,
        "TradeEndTime": 1240,
        "AnchorMode": "Both",
        "TargetMode": "FixedRR",
        "UseVwapSideFilter": False,
        "MinDistanceToVwapTicks": 0,
        "MinVolumeFactor": 0.0,
        "MinBodyRangePct": 0.0,
        "MinCloseLocationPct": 0.0,
        "SweepDistanceTicks": 0,
        "ReturnInsideTicks": 0,
        "SweepMaxBarsToReturn": 8,
        "MinOpeningRangeTicks": 1,
        "MaxOpeningRangeTicks": 200,
        "StopBeyondSweepTicks": 1,
        "EntryOffsetTicks": 0,
        "EntryTimeoutBars": 4,
        "MaxTradesPerDay": 20,
        "HardMaxTradesPerDay": 25,
        "MaxConsecutiveLosses": 20,
        "PauseAfterConsecutiveLosses": 0,
        "DailyLossLimit": 0.0,
        "WeeklyLossLimit": 0.0,
    })
    params.update(overrides)
    return engine.carrier.Variant(name=name, params=params)


def full_variants() -> List[engine.carrier.Variant]:
    out: List[engine.carrier.Variant] = []
    for direction in ("long", "short", "both"):
        for anchor in ("PriorSession", "OpeningRange", "Both"):
            for stop_ticks in (16, 24, 32, 40):
                out.append(variant(
                    f"c004_scout_{direction}_{anchor.lower()}_s{stop_ticks}_rr15",
                    Direction=direction,
                    AnchorMode=anchor,
                    MinStopTicks=8,
                    MaxStopTicks=stop_ticks,
                    RewardRiskRatio=1.5,
                    AtrStopMult=0.0,
                ))
    return out


engine.carrier.full_variants = full_variants


if __name__ == "__main__":
    raise SystemExit(engine.carrier.main(sys.argv))