"""Targeted MGC CELL-004 SessionEdge compression-breakout optimization."""
from __future__ import annotations

import sys
from typing import Any, List

import run_mgc_cell004_long_pullback_carrier as carrier


carrier.CLASS_NAME = "VWAPPullbackMGC5mV1"
carrier.BUNDLE_NAME = "mgc_cell004_sessionedge_compression_opt"
carrier.MIN_FREQ_TRADES = 30
carrier.TARGET_FREQ_TRADES = 60


def variant(name: str, **overrides: Any) -> carrier.Variant:
    params = carrier.base_params()
    params.update({
        "SetupMode": "CompressionBreakout",
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
        "RewardRiskRatio": 2.0,
        "MoveToBreakevenAtR": 0.0,
        "TrailAfterR": 0.0,
        "EntryOffsetTicks": 1,
        "EntryTimeoutBars": 2,
        "CompressionLookback": 30,
        "CompressionAtrPct": 0.30,
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
        ("both", {"EnableLong": True, "EnableShort": True}),
    ):
        for trade_end in (1000, 1240):
            for lookback in (20, 40):
                for atr_pct in (0.20, 0.30):
                    for stop_ticks in (12, 24):
                        for rr in (1.5, 2.0):
                            out.append(variant(
                                f"c004_cb_{direction}_te{trade_end}_lb{lookback}_pct{int(atr_pct * 100)}_s{stop_ticks}_rr{str(rr).replace('.', '')}",
                                **toggles,
                                TradeEndTime=trade_end,
                                CompressionLookback=lookback,
                                CompressionAtrPct=atr_pct,
                                MinStopTicks=stop_ticks,
                                MaxStopTicks=stop_ticks,
                                RewardRiskRatio=rr,
                            ))
    return out


carrier.full_variants = full_variants


if __name__ == "__main__":
    raise SystemExit(carrier.main(sys.argv))
