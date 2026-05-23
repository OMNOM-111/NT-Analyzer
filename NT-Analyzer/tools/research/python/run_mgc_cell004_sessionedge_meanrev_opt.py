"""Targeted MGC CELL-004 SessionEdge VWAP mean-reversion optimization."""
from __future__ import annotations

import sys
from typing import Any, List

import run_mgc_cell004_long_pullback_carrier as carrier


carrier.CLASS_NAME = "VWAPPullbackMGC5mV1"
carrier.BUNDLE_NAME = "mgc_cell004_sessionedge_meanrev_opt"
carrier.MIN_FREQ_TRADES = 30
carrier.TARGET_FREQ_TRADES = 60


def variant(name: str, **overrides: Any) -> carrier.Variant:
    params = carrier.base_params()
    params.update({
        "SetupMode": "VwapMeanReversion",
        "EnableLong": True,
        "EnableShort": True,
        "TradeStartTime": 600,
        "TradeEndTime": 1000,
        "ForceFlatTime": 1245,
        "UseSecondTradeWindow": False,
        "MinAdx": 0.0,
        "MinVolumeFactor": 0.8,
        "PullbackLookback": 1,
        "MinStopTicks": 10,
        "MaxStopTicks": 30,
        "RewardRiskRatio": 1.5,
        "MoveToBreakevenAtR": 0.0,
        "TrailAfterR": 0.0,
        "EntryOffsetTicks": 1,
        "EntryTimeoutBars": 2,
        "MeanRevExtensionAtr": 1.5,
        "MeanRevTargetVwap": True,
        "MaxTradesPerDay": 6,
        "MaxConsecutiveLosses": 10,
        "UserMaxContracts": 1,
        "RiskPerTradePct": 1.0,
    })
    params.update(overrides)
    return carrier.Variant(name=name, params=params)


def full_variants() -> List[carrier.Variant]:
    out: List[carrier.Variant] = []
    for direction, toggles in (
        ("short", {"EnableLong": False, "EnableShort": True}),
        ("long", {"EnableLong": True, "EnableShort": False}),
    ):
        for trade_end in (900, 1000, 1130, 1240):
            for ext in (1.1, 1.5, 1.8):
                for stop_ticks in (10, 16, 24):
                    out.append(variant(
                        f"c004_mr_{direction}_te{trade_end}_ext{str(ext).replace('.', '')}_s{stop_ticks}_vwap",
                        **toggles,
                        TradeEndTime=trade_end,
                        MeanRevExtensionAtr=ext,
                        MeanRevTargetVwap=True,
                        MinStopTicks=stop_ticks,
                        MaxStopTicks=stop_ticks,
                    ))

    for direction, toggles in (
        ("short", {"EnableLong": False, "EnableShort": True}),
        ("long", {"EnableLong": True, "EnableShort": False}),
    ):
        for ext in (1.1, 1.5, 1.8):
            for stop_ticks in (12, 18, 24):
                for rr in (1.2, 1.5, 2.0):
                    out.append(variant(
                        f"c004_mr_{direction}_rr_te1240_ext{str(ext).replace('.', '')}_s{stop_ticks}_rr{str(rr).replace('.', '')}",
                        **toggles,
                        TradeEndTime=1240,
                        MeanRevExtensionAtr=ext,
                        MeanRevTargetVwap=False,
                        MinStopTicks=stop_ticks,
                        MaxStopTicks=stop_ticks,
                        RewardRiskRatio=rr,
                    ))
    return out


carrier.full_variants = full_variants


if __name__ == "__main__":
    raise SystemExit(carrier.main(sys.argv))
