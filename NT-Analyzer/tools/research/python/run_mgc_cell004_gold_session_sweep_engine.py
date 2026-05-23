"""Research MGC CELL-004 gold-specific session sweep reversal engine.

This runner uses the concrete NTAMicroGoldSessionSweepReversalPilot class.  It
does not use the failed carrier paths: no VwapPullback and no generic OR-failure
mode.  The tested idea is a direct sweep-and-return of prior-session or opening
range levels with after-cost metrics recomputed from trades.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List

import run_mgc_cell004_long_pullback_carrier as carrier


carrier.CLASS_NAME = "NTAMicroGoldSessionSweepReversalPilot"
carrier.BUNDLE_NAME = "mgc_cell004_gold_session_sweep_engine"
carrier.MIN_FREQ_TRADES = 90
carrier.TARGET_FREQ_TRADES = 140


def base_params() -> Dict[str, Any]:
    fee = carrier.RL.fee_for(carrier.ROOT)
    params: Dict[str, Any] = {
        "InstrumentName": carrier.ROOT,
        "ContractName": carrier.INSTRUMENT,
        "SessionTemplateName": carrier.SESSION_TEMPLATE,
        "BaseTimeframeSeconds": 300,

        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": carrier.RL.margin_for(carrier.ROOT),
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",

        "EnableLong": True,
        "EnableShort": True,
        "AnchorMode": "Both",
        "TargetMode": "FixedRR",

        "TradeStartTime": 600,
        "TradeEndTime": 1000,
        "ForceFlatTime": 1245,
        "OpeningRangeStartTime": 600,
        "OpeningRangeMinutes": 30,

        "EmaFastPeriod": 9,
        "EmaSlowPeriod": 34,
        "AtrPeriod": 14,
        "AdxPeriod": 14,
        "VolumeSmaPeriod": 20,
        "MinAdx": 0.0,
        "MinVolumeFactor": 1.0,
        "MinBodyRangePct": 0.20,
        "MinCloseLocationPct": 0.55,
        "UseTrendFilter": False,
        "UseVwapSideFilter": True,
        "MinDistanceToVwapTicks": 4,

        "SweepDistanceTicks": 2,
        "ReturnInsideTicks": 1,
        "SweepMaxBarsToReturn": 3,
        "MinOpeningRangeTicks": 6,
        "MaxOpeningRangeTicks": 90,

        "StopBeyondSweepTicks": 2,
        "ClampStopToMaxTicks": True,
        "MinStopTicks": 12,
        "MaxStopTicks": 12,
        "AtrStopMult": 0.35,
        "RewardRiskRatio": 2.0,
        "EntryOffsetTicks": 1,
        "EntryTimeoutBars": 2,
        "MinTargetTicks": 8,
        "VwapTargetOffsetTicks": 1,
        "TimeStopBars": 6,
        "MinProgressR": 0.15,

        "RiskPerTradePct": 1.0,
        "UserMaxContracts": 1,
        "MaxOpenPositions": 1,
        "DailyLossLimit": 60.0,
        "WeeklyLossLimit": 150.0,
        "MaxTradesPerDay": 5,
        "HardMaxTradesPerDay": 7,
        "MaxConsecutiveLosses": 3,
        "PauseAfterConsecutiveLosses": 2,
        "PauseMinutesAfterLosses": 15,
        "RoundTurnCommission": fee,
        "SlippageTicks": 1,
    }
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
        for anchor in ("PriorSession", "OpeningRange", "Both"):
            for opening_minutes in (15, 30):
                out.append(variant(
                    f"c004_gs_{direction}_{anchor.lower()}_or{opening_minutes}_s12_rr20_fx",
                    Direction=direction,
                    AnchorMode=anchor,
                    TargetMode="FixedRR",
                    TradeEndTime=1000,
                    OpeningRangeMinutes=opening_minutes,
                    SweepDistanceTicks=2,
                    SweepMaxBarsToReturn=3,
                    MinStopTicks=12,
                    MaxStopTicks=12,
                    RewardRiskRatio=2.0,
                    MinVolumeFactor=1.0,
                    MinDistanceToVwapTicks=4,
                ))
                out.append(variant(
                    f"c004_gs_{direction}_{anchor.lower()}_or{opening_minutes}_s10_rr15_vwap",
                    Direction=direction,
                    AnchorMode=anchor,
                    TargetMode="VwapThenRR",
                    TradeEndTime=930,
                    OpeningRangeMinutes=opening_minutes,
                    SweepDistanceTicks=1,
                    SweepMaxBarsToReturn=2,
                    MinStopTicks=10,
                    MaxStopTicks=10,
                    RewardRiskRatio=1.5,
                    MinVolumeFactor=1.0,
                    MinDistanceToVwapTicks=2,
                ))
                out.append(variant(
                    f"c004_gs_{direction}_{anchor.lower()}_or{opening_minutes}_s14_rr25_fx",
                    Direction=direction,
                    AnchorMode=anchor,
                    TargetMode="FixedRR",
                    TradeEndTime=1000,
                    OpeningRangeMinutes=opening_minutes,
                    SweepDistanceTicks=4,
                    SweepMaxBarsToReturn=4,
                    MinStopTicks=14,
                    MaxStopTicks=14,
                    RewardRiskRatio=2.5,
                    MinVolumeFactor=1.05,
                    MinDistanceToVwapTicks=4,
                ))

    for direction in ("long", "short"):
        for anchor in ("OpeningRange", "Both"):
            for stop_ticks in (10, 12, 14, 16):
                for rr in (1.5, 2.0, 2.5):
                    out.append(variant(
                        f"c004_gs_core_{direction}_{anchor.lower()}_s{stop_ticks}_rr{str(rr).replace('.', '')}",
                        Direction=direction,
                        AnchorMode=anchor,
                        TargetMode="FixedRR",
                        TradeStartTime=600,
                        TradeEndTime=1000,
                        OpeningRangeMinutes=30,
                        SweepDistanceTicks=2,
                        SweepMaxBarsToReturn=3,
                        MinStopTicks=stop_ticks,
                        MaxStopTicks=stop_ticks,
                        RewardRiskRatio=rr,
                        MinVolumeFactor=1.0,
                        MinDistanceToVwapTicks=3,
                    ))

    return out


carrier.base_params = base_params
carrier.full_variants = full_variants


if __name__ == "__main__":
    raise SystemExit(carrier.main(sys.argv))