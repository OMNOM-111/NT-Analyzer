"""SetupMode-aware helpers for NTAMicroSessionEdgeExplorer.

Layered on top of research_lib.py. Provides:
 - SetupMode constant strings (must match C# enum names)
 - default parameter dicts per (family, mode)
 - family routing (which modes apply to which families)
"""
from __future__ import annotations

from typing import Dict, List, Tuple, Any

import research_lib as RL

# Must match the C# enum SessionEdgeSetupMode (string serialization).
MODE_VWAP_PB        = "VwapPullback"
MODE_ORB_CONT       = "OrbContinuation"
MODE_ORB_FAIL_REV   = "FailedOrbReversal"
MODE_VWAP_MEAN_REV  = "VwapMeanReversion"
MODE_COMPRESSION    = "CompressionBreakout"
MODE_ROLLING_VWAP   = "RollingVwapCrypto"

ALL_MODES = [MODE_VWAP_PB, MODE_ORB_CONT, MODE_ORB_FAIL_REV,
             MODE_VWAP_MEAN_REV, MODE_COMPRESSION, MODE_ROLLING_VWAP]

# Family -> list of (label, [roots], TradeStart_HHMM, TradeEnd_HHMM,
# ForceFlat_HHMM, [SetupMode...]).
# MNQ excluded — locked Pilot owns it.
FAMILIES: List[Tuple[str, List[str], int, int, int, List[str]]] = [
    # Index micros — full ORB and pullback toolkit. Skip MeanRev/Crypto.
    ("index_micros", ["MES", "MYM", "M2K"], 635, 1000, 1245,
        [MODE_VWAP_PB, MODE_ORB_CONT, MODE_ORB_FAIL_REV, MODE_COMPRESSION]),
    # Metals — pullback baseline + mean reversion (after opening spike).
    ("metals", ["MGC", "MHG", "SIL"], 600, 1000, 1245,
        [MODE_VWAP_PB, MODE_VWAP_MEAN_REV, MODE_COMPRESSION]),
    # Energy — pullback + compression breakout.
    ("energy", ["MCL", "MNG"], 600, 1000, 1245,
        [MODE_VWAP_PB, MODE_COMPRESSION, MODE_ORB_CONT]),
    # FX micros — looser windows + mean reversion.
    ("fx", ["M6A", "M6B", "M6E"], 100, 1000, 1245,
        [MODE_VWAP_PB, MODE_VWAP_MEAN_REV]),
    # Crypto — only rolling VWAP makes sense (24/7 + no RTH).
    ("crypto", ["MBT", "MET"], 0, 2200, 2245,
        [MODE_ROLLING_VWAP]),
]

DIRECTIONS = [
    ("shortonly", {"EnableLong": False, "EnableShort": True}),
    ("longonly",  {"EnableLong": True,  "EnableShort": False}),
    ("longshort", {"EnableLong": True,  "EnableShort": True}),
]


def setup_mode_defaults(mode: str, root: str) -> Dict[str, Any]:
    """Mode-specific parameter overrides on top of RL.base_risk_params(root)."""
    base: Dict[str, Any] = {
        # Indicator periods (Pilot defaults)
        "EmaFastPeriod": 50, "EmaSlowPeriod": 200,
        "AtrPeriod": 14, "AdxPeriod": 14, "VolumeSmaPeriod": 20,
        "AtrStopMult": 0.75,
        "MoveToBreakevenAtR": 0.8, "TrailAfterR": 1.2,
        "UseSecondTradeWindow": False, "UseDailyBiasFilter": False,
        # ORB defaults
        "OrbDurationMinutes": 30, "OrbBreakoutBuffer": 1, "OrbFailedLookback": 3,
        # MeanRev defaults
        "MeanRevExtensionAtr": 1.5, "MeanRevTargetVwap": True,
        # Compression defaults
        "CompressionLookback": 30, "CompressionAtrPct": 0.30,
        # RollingVwap defaults
        "RollingVwapBars": 288, "Use24hSession": False,
        # Setup mode
        "SetupMode": mode,
    }

    # Mode-specific overrides
    if mode == MODE_VWAP_PB:
        base.update({
            "MinAdx": 22.0, "MinVolumeFactor": 1.2, "PullbackLookback": 3,
            "MinStopTicks": 12, "MaxStopTicks": 12,
            "RewardRiskRatio": 3.5,
            "EntryOffsetTicks": 2, "EntryTimeoutBars": 2,
        })
    elif mode == MODE_ORB_CONT:
        base.update({
            "MinAdx": 0.0, "MinVolumeFactor": 1.0, "PullbackLookback": 1,
            "MinStopTicks": 8, "MaxStopTicks": 40,
            "RewardRiskRatio": 2.0,
            "EntryOffsetTicks": 1, "EntryTimeoutBars": 2,
            "OrbDurationMinutes": 30, "OrbBreakoutBuffer": 2,
        })
    elif mode == MODE_ORB_FAIL_REV:
        base.update({
            "MinAdx": 0.0, "MinVolumeFactor": 1.0, "PullbackLookback": 1,
            "MinStopTicks": 8, "MaxStopTicks": 30,
            "RewardRiskRatio": 1.8,
            "EntryOffsetTicks": 1, "EntryTimeoutBars": 2,
            "OrbDurationMinutes": 30, "OrbFailedLookback": 3,
        })
    elif mode == MODE_VWAP_MEAN_REV:
        base.update({
            "MinAdx": 0.0, "MinVolumeFactor": 1.0, "PullbackLookback": 1,
            "MinStopTicks": 8, "MaxStopTicks": 40,
            "RewardRiskRatio": 1.5,
            "EntryOffsetTicks": 1, "EntryTimeoutBars": 2,
            "MeanRevExtensionAtr": 1.5, "MeanRevTargetVwap": True,
        })
    elif mode == MODE_COMPRESSION:
        base.update({
            "MinAdx": 0.0, "MinVolumeFactor": 1.0, "PullbackLookback": 1,
            "MinStopTicks": 8, "MaxStopTicks": 30,
            "RewardRiskRatio": 2.0,
            "EntryOffsetTicks": 1, "EntryTimeoutBars": 2,
            "CompressionLookback": 30, "CompressionAtrPct": 0.30,
        })
    elif mode == MODE_ROLLING_VWAP:
        base.update({
            "MinAdx": 0.0, "MinVolumeFactor": 0.5, "PullbackLookback": 1,
            "MinStopTicks": 10, "MaxStopTicks": 60,
            "RewardRiskRatio": 1.8,
            "EntryOffsetTicks": 1, "EntryTimeoutBars": 2,
            "RollingVwapBars": 288, "Use24hSession": True,
            # Crypto-specific risk knobs
            "MaxTradesPerDay": 6,
        })
    return base


def family_session(root: str) -> str:
    return RL.session_for(root)
