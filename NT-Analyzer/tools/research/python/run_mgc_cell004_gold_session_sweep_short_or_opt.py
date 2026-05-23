"""Targeted short opening-range optimization for MGC CELL-004 sweep engine."""
from __future__ import annotations

import sys
from typing import Any, List

import run_mgc_cell004_gold_session_sweep_engine as engine


engine.carrier.BUNDLE_NAME = "mgc_cell004_gold_session_sweep_short_or_opt"
engine.carrier.MIN_FREQ_TRADES = 40
engine.carrier.TARGET_FREQ_TRADES = 80


def variant(name: str, **overrides: Any) -> engine.carrier.Variant:
    params = engine.base_params()
    params.update({
        "EnableLong": False,
        "EnableShort": True,
        "AnchorMode": "OpeningRange",
        "TargetMode": "FixedRR",
        "TradeStartTime": 600,
        "TradeEndTime": 1000,
        "ForceFlatTime": 1245,
        "MinAdx": 0.0,
        "MinVolumeFactor": 0.0,
        "MinBodyRangePct": 0.0,
        "MinCloseLocationPct": 0.0,
        "UseTrendFilter": False,
        "UseVwapSideFilter": False,
        "MinDistanceToVwapTicks": 0,
        "SweepDistanceTicks": 0,
        "ReturnInsideTicks": 0,
        "SweepMaxBarsToReturn": 8,
        "MinOpeningRangeTicks": 1,
        "MaxOpeningRangeTicks": 200,
        "StopBeyondSweepTicks": 1,
        "ClampStopToMaxTicks": True,
        "MinStopTicks": 8,
        "MaxStopTicks": 16,
        "AtrStopMult": 0.0,
        "RewardRiskRatio": 2.0,
        "EntryOffsetTicks": 0,
        "EntryTimeoutBars": 4,
        "MinTargetTicks": 6,
        "TimeStopBars": 0,
        "MinProgressR": 0.0,
        "RiskPerTradePct": 1.0,
        "UserMaxContracts": 1,
        "MaxOpenPositions": 1,
        "DailyLossLimit": 80.0,
        "WeeklyLossLimit": 200.0,
        "MaxTradesPerDay": 8,
        "HardMaxTradesPerDay": 12,
        "MaxConsecutiveLosses": 20,
        "PauseAfterConsecutiveLosses": 0,
    })
    params.update(overrides)
    return engine.carrier.Variant(name=name, params=params)


def full_variants() -> List[engine.carrier.Variant]:
    out: List[engine.carrier.Variant] = []
    for anchor in ("OpeningRange", "Both"):
        for opening_minutes in (15, 30, 45):
            for trade_end in (930, 1000, 1130, 1240):
                for rr in (1.5, 2.0, 2.5, 3.0):
                    out.append(variant(
                        f"c004_or_short_{anchor.lower()}_or{opening_minutes}_te{trade_end}_rr{str(rr).replace('.', '')}_loose",
                        AnchorMode=anchor,
                        OpeningRangeMinutes=opening_minutes,
                        TradeEndTime=trade_end,
                        RewardRiskRatio=rr,
                        UseVwapSideFilter=False,
                        TimeStopBars=0,
                    ))
                    out.append(variant(
                        f"c004_or_short_{anchor.lower()}_or{opening_minutes}_te{trade_end}_rr{str(rr).replace('.', '')}_vwap_ts6",
                        AnchorMode=anchor,
                        OpeningRangeMinutes=opening_minutes,
                        TradeEndTime=trade_end,
                        RewardRiskRatio=rr,
                        UseVwapSideFilter=True,
                        MinDistanceToVwapTicks=2,
                        TimeStopBars=6,
                        MinProgressR=0.15,
                    ))
    return out


engine.carrier.full_variants = full_variants


if __name__ == "__main__":
    raise SystemExit(engine.carrier.main(sys.argv))