"""Shared constants/builders for NTAMicroMnqScalpPilot research."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Tuple

import research_lib as RL

CLASS_NAME = "NTAMicroMnqScalpPilot"

ROOTS = ["MNQ", "MES", "MYM", "M2K"]

PERIODS: List[Tuple[str, str, str]] = [
    ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z"),
    ("IS", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"),
    ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z"),
    ("Q1_2024", "2024-01-01T00:00:00Z", "2024-03-31T23:59:59Z"),
    ("Q2_2024", "2024-04-01T00:00:00Z", "2024-06-30T23:59:59Z"),
    ("Q3_2024", "2024-07-01T00:00:00Z", "2024-09-30T23:59:59Z"),
    ("Q4_2024", "2024-10-01T00:00:00Z", "2024-12-31T23:59:59Z"),
    ("Q1_2025", "2025-01-01T00:00:00Z", "2025-03-31T23:59:59Z"),
    ("Q2_2025", "2025-04-01T00:00:00Z", "2025-06-30T23:59:59Z"),
    ("Q3_2025", "2025-07-01T00:00:00Z", "2025-09-30T23:59:59Z"),
    ("Q4_2025", "2025-10-01T00:00:00Z", "2025-12-31T23:59:59Z"),
]

SMOKE_PERIOD = ("Smoke", "2026-03-12T00:00:00Z", "2026-04-24T23:59:59Z")

MODULES: Dict[str, Dict[str, bool]] = {
    "ALL": {
        "EnableVwapReclaim": True,
        "EnableEmaMomentum": True,
        "EnableMicroOrb": True,
        "EnableFailedBreakout": True,
    },
    "VWAP_RECLAIM": {
        "EnableVwapReclaim": True,
        "EnableEmaMomentum": False,
        "EnableMicroOrb": False,
        "EnableFailedBreakout": False,
    },
    "EMA_MOMENTUM": {
        "EnableVwapReclaim": False,
        "EnableEmaMomentum": True,
        "EnableMicroOrb": False,
        "EnableFailedBreakout": False,
    },
    "MICRO_ORB": {
        "EnableVwapReclaim": False,
        "EnableEmaMomentum": False,
        "EnableMicroOrb": True,
        "EnableFailedBreakout": False,
    },
    "FAILED_BREAKOUT": {
        "EnableVwapReclaim": False,
        "EnableEmaMomentum": False,
        "EnableMicroOrb": False,
        "EnableFailedBreakout": True,
    },
}


def contracts_for_roots(roots: Iterable[str]) -> List[str]:
    out: List[str] = []
    for root in roots:
        c = RL.resolve_front_contract(root)
        if "skip_reason" not in c:
            out.append(str(c["instrument"]))
    return out


def contracts_for_period(root: str, from_utc: str, to_utc: str) -> List[str]:
    start = datetime.fromisoformat(from_utc.replace("Z", "+00:00")).date()
    end = datetime.fromisoformat(to_utc.replace("Z", "+00:00")).date()
    rows = [
        r for r in RL.load_instruments()
        if r.get("root") == root and r.get("has_minute_data")
        and r.get("data_first") and r.get("data_last")
    ]
    out = []
    for r in rows:
        data_first = date.fromisoformat(str(r["data_first"])[:10])
        data_last = date.fromisoformat(str(r["data_last"])[:10])
        if data_last >= start and data_first <= end:
            out.append(r)
    out.sort(key=lambda r: (r.get("data_first") or "", r.get("data_last") or "", r.get("instrument") or ""))
    return [str(r["instrument"]) for r in out]


def scalp_params(root: str, module: str = "ALL") -> Dict[str, Any]:
    p: Dict[str, Any] = {
        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": RL.margin_for(root),
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "RiskPerTradePct": 0.35,
        "MaxDailyLossPct": 3.0,
        "MaxDailyLossUsd": 60.0,
        "MaxWeeklyLossUsd": 150.0,
        "MaxDailyProfitPct": 0.0,
        "MaxTradesPerDay": 20,
        "HardMaxTradesPerDay": 25,
        "MaxConsecutiveLosses": 3,
        "PauseAfterConsecutiveLosses": 2,
        "PauseMinutesAfterLosses": 15,
        "UserMaxContracts": 1,
        "MaxOpenPositions": 1,
        "RoundTurnCommission": 1.90,
        "SlippageTicks": 1,
        "UseSetupModeFilter": False,
        "EnableLong": True,
        "EnableShort": True,
        "EmaFastPeriod": 9,
        "EmaMidPeriod": 21,
        "EmaSlowPeriod": 50,
        "AtrPeriod": 14,
        "AdxPeriod": 14,
        "MinAdx": 0.0,
        "VolumeSmaPeriod": 20,
        "MinVolumeFactor": 0.8,
        "PullbackLookback": 3,
        "RequireSlowTrend": False,
        "AtrStopMult": 0.35,
        "MinStopTicks": 8,
        "MaxStopTicks": 16,
        "RewardRiskRatio": 1.25,
        "MoveToBreakevenAtR": 0.7,
        "TrailAfterR": 1.0,
        "UseTimeStop": True,
        "TimeStopBars": 3,
        "MinProgressR": 0.30,
        "EntryTimeoutBars": 2,
        "EntryOffsetTicks": 1,
        "TradeStartTime": 635,
        "TradeEndTime": 830,
        "UseSecondTradeWindow": True,
        "SecondTradeStartTime": 1030,
        "SecondTradeEndTime": 1200,
        "ForceFlatTime": 1245,
        "NewsBlackoutTimes": "",
        "NewsBlackoutWindowMin": 5,
        "OrbStartTime": 630,
        "OrbDurationMinutes": 3,
        "OrbBreakoutBuffer": 1,
        "OrbRetestBars": 5,
        "OrbFailedLookback": 3,
        "EmaImpulseLookback": 3,
    }
    p.update(MODULES[module])
    return p


def trading_weekdays(from_utc: str, to_utc: str) -> int:
    start = datetime.fromisoformat(from_utc.replace("Z", "+00:00")).date()
    end = datetime.fromisoformat(to_utc.replace("Z", "+00:00")).date()
    n = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return max(1, n)
