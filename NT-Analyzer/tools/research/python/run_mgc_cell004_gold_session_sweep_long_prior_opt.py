"""Targeted long prior-session optimization for MGC CELL-004 sweep engine."""
from __future__ import annotations

import sys
from typing import Any, List

import run_mgc_cell004_gold_session_sweep_engine as engine


engine.carrier.BUNDLE_NAME = "mgc_cell004_gold_session_sweep_long_prior_opt"
engine.carrier.MIN_FREQ_TRADES = 30
engine.carrier.TARGET_FREQ_TRADES = 60


def variant(name: str, **overrides: Any) -> engine.carrier.Variant:
    params = engine.base_params()
    params.update({
        "EnableLong": True,
        "EnableShort": False,
        "AnchorMode": "PriorSession",
        "TargetMode": "FixedRR",
        "TradeStartTime": 600,
        "TradeEndTime": 1240,
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
        "RewardRiskRatio": 1.5,
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
    for trade_start, trade_end in ((500, 930), (500, 1000), (500, 1240), (600, 1000), (600, 1240)):
        for sweep_bars in (3, 5, 8, 12):
            for rr in (1.2, 1.5, 1.8, 2.0):
                out.append(variant(
                    f"c004_lp_ts{trade_start}_te{trade_end}_bars{sweep_bars}_rr{str(rr).replace('.', '')}_loose",
                    TradeStartTime=trade_start,
                    TradeEndTime=trade_end,
                    SweepMaxBarsToReturn=sweep_bars,
                    RewardRiskRatio=rr,
                    UseVwapSideFilter=False,
                    TimeStopBars=0,
                ))
                out.append(variant(
                    f"c004_lp_ts{trade_start}_te{trade_end}_bars{sweep_bars}_rr{str(rr).replace('.', '')}_vwap",
                    TradeStartTime=trade_start,
                    TradeEndTime=trade_end,
                    SweepMaxBarsToReturn=sweep_bars,
                    RewardRiskRatio=rr,
                    UseVwapSideFilter=True,
                    MinDistanceToVwapTicks=2,
                    TimeStopBars=6,
                    MinProgressR=0.15,
                ))

    for stop_ticks in (10, 12, 14, 16, 20, 24):
        for rr in (1.2, 1.5, 1.8, 2.0):
            out.append(variant(
                f"c004_lp_core_s{stop_ticks}_rr{str(rr).replace('.', '')}",
                TradeStartTime=600,
                TradeEndTime=1240,
                MinStopTicks=stop_ticks,
                MaxStopTicks=stop_ticks,
                RewardRiskRatio=rr,
                SweepMaxBarsToReturn=8,
                UseVwapSideFilter=False,
            ))
    return out


engine.carrier.full_variants = full_variants


if __name__ == "__main__":
    raise SystemExit(engine.carrier.main(sys.argv))