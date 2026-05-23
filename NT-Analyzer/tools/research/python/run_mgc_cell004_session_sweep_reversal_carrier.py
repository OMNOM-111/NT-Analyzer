"""Research backup MGC CELL-004 Session Sweep Reversal carrier.

This uses the already compiled VWAPPullbackMGC5mV1 wrapper as a carrier over
NTAMicroSessionEdgeExplorer with SetupMode=FailedOrbReversal.  It is not the
final deploy identity; it is a fast evidence pass for the backup idea after the
long pullback continuation carrier failed full-period gates.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List

import run_mgc_cell004_long_pullback_carrier as carrier


carrier.BUNDLE_NAME = "mgc_cell004_session_sweep_reversal"
carrier.MIN_FREQ_TRADES = 80
carrier.TARGET_FREQ_TRADES = 140


def base_params() -> Dict[str, Any]:
    params = carrier.RL.base_risk_params(carrier.ROOT)
    params.update({
        "SetupMode": "FailedOrbReversal",
        "EnableLong": True,
        "EnableShort": True,
        "TradeStartTime": 600,
        "TradeEndTime": 1000,
        "UseSecondTradeWindow": True,
        "SecondTradeStartTime": 1030,
        "SecondTradeEndTime": 1200,
        "ForceFlatTime": 1245,
        "MinVolumeFactor": 1.0,
        "MinAdx": 0.0,
        "PullbackLookback": 3,
        "MinStopTicks": 12,
        "MaxStopTicks": 12,
        "RewardRiskRatio": 2.0,
        "EntryOffsetTicks": 1,
        "EntryTimeoutBars": 2,
        "MaxTradesPerDay": 4,
        "UseDailyBiasFilter": False,
        "BlockShortsWhenDailyBullish": False,
        "BlockLongsWhenDailyBearish": False,
        "OrbDurationMinutes": 30,
        "OrbBreakoutBuffer": 1,
        "OrbFailedLookback": 3,
        "RoundTurnCommission": 1.90,
        "SlippageTicks": 1,
    })
    return params


def variant(name: str, **overrides: Any) -> carrier.Variant:
    params = base_params()
    direction = str(overrides.pop("Direction", "both"))
    params["EnableLong"] = direction in {"long", "both"}
    params["EnableShort"] = direction in {"short", "both"}
    params.update(overrides)
    return carrier.Variant(name=name, params=params)


def full_variants() -> List[carrier.Variant]:
    out: List[carrier.Variant] = []
    for direction in ("long", "short", "both"):
        for trade_start, trade_end in ((600, 930), (600, 1000)):
            for orb_minutes in (15, 30):
                for failed_lookback in (2, 3, 4):
                    out.append(variant(
                        f"c004_sweep_{direction}_ts{trade_start}_te{trade_end}_or{orb_minutes}_lb{failed_lookback}_s12_rr20",
                        Direction=direction,
                        TradeStartTime=trade_start,
                        TradeEndTime=trade_end,
                        UseSecondTradeWindow=True,
                        OrbDurationMinutes=orb_minutes,
                        OrbFailedLookback=failed_lookback,
                        MinStopTicks=12,
                        MaxStopTicks=12,
                        RewardRiskRatio=2.0,
                        EntryOffsetTicks=1,
                    ))

    for direction in ("long", "short", "both"):
        for stop_ticks in (10, 12, 14, 16):
            for rr in (1.5, 2.0, 2.5):
                out.append(variant(
                    f"c004_sweep_core_{direction}_s{stop_ticks}_rr{str(rr).replace('.', '')}",
                    Direction=direction,
                    TradeStartTime=600,
                    TradeEndTime=1000,
                    UseSecondTradeWindow=True,
                    OrbDurationMinutes=30,
                    OrbFailedLookback=3,
                    MinStopTicks=stop_ticks,
                    MaxStopTicks=stop_ticks,
                    RewardRiskRatio=rr,
                    EntryOffsetTicks=1,
                ))
    return out


carrier.base_params = base_params
carrier.full_variants = full_variants


if __name__ == "__main__":
    raise SystemExit(carrier.main(sys.argv))