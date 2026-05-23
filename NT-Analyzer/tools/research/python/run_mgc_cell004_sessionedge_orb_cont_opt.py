"""Targeted MGC CELL-004 SessionEdge ORB-continuation optimization."""
from __future__ import annotations

import sys
from typing import Any, List, Tuple

import run_mgc_cell004_long_pullback_carrier as carrier


carrier.CLASS_NAME = "VWAPPullbackMGC5mV1"
carrier.BUNDLE_NAME = "mgc_cell004_sessionedge_orb_cont_opt"
carrier.MIN_FREQ_TRADES = 30
carrier.TARGET_FREQ_TRADES = 60


def variant(name: str, **overrides: Any) -> carrier.Variant:
    params = carrier.base_params()
    params.update({
        "SetupMode": "OrbContinuation",
        "EnableLong": True,
        "EnableShort": True,
        "TradeStartTime": 600,
        "TradeEndTime": 1000,
        "ForceFlatTime": 1245,
        "UseSecondTradeWindow": False,
        "MinAdx": 0.0,
        "MinVolumeFactor": 0.8,
        "PullbackLookback": 1,
        "MinStopTicks": 12,
        "MaxStopTicks": 24,
        "RewardRiskRatio": 1.5,
        "MoveToBreakevenAtR": 0.0,
        "TrailAfterR": 0.0,
        "EntryOffsetTicks": 1,
        "EntryTimeoutBars": 2,
        "OrbDurationMinutes": 30,
        "OrbBreakoutBuffer": 1,
        "OrbFailedLookback": 3,
        "MaxTradesPerDay": 6,
        "MaxConsecutiveLosses": 10,
        "UserMaxContracts": 1,
        "RiskPerTradePct": 1.0,
    })
    params.update(overrides)
    return carrier.Variant(name=name, params=params)


def full_variants() -> List[carrier.Variant]:
    out: List[carrier.Variant] = []
    stop_rr_pairs: Tuple[Tuple[int, float], ...] = ((12, 1.5), (12, 2.0), (24, 1.5))
    for direction, toggles in (
        ("short", {"EnableLong": False, "EnableShort": True}),
        ("long", {"EnableLong": True, "EnableShort": False}),
        ("both", {"EnableLong": True, "EnableShort": True}),
    ):
        for trade_end in (1000, 1240):
            for orb_minutes in (15, 30, 45):
                for buffer_ticks in (1, 2):
                    for stop_ticks, rr in stop_rr_pairs:
                        out.append(variant(
                            f"c004_orbc_{direction}_te{trade_end}_or{orb_minutes}_buf{buffer_ticks}_s{stop_ticks}_rr{str(rr).replace('.', '')}",
                            **toggles,
                            TradeEndTime=trade_end,
                            OrbDurationMinutes=orb_minutes,
                            OrbBreakoutBuffer=buffer_ticks,
                            MinStopTicks=stop_ticks,
                            MaxStopTicks=stop_ticks,
                            RewardRiskRatio=rr,
                        ))
    return out


carrier.full_variants = full_variants


if __name__ == "__main__":
    raise SystemExit(carrier.main(sys.argv))
