"""
NT-Analyzer — Phase 17 NinjaTrader runtime bridge.

Reads telemetry files written by the NinjaTrader-side RuntimeExporter
(part of NTAnalyzerBridge AddOn) and merges them with the registry
state from `app.ops`. Read-only. **No live trading control.**

Storage layout under <project_root>/data/runtime/ :
  heartbeat.json       — { timestamp_utc, ninja_version, machine, ... }
  strategies.json      — { generated_at_utc, strategies: [...] }
  executions.jsonl     — append-only fills (one JSON object per line;
                          dedupe prefers order_id + fill time + qty + price
                          when NT replays the same fill with a new execution_id).
                          Reads a large tail of this file so replay rows still
                          pair with originals for dedupe.
  orders.jsonl         — append-only order updates
  positions.json       — { account_name -> { instrument -> {...} } }
  errors.jsonl         — append-only NinjaTrader-side errors

Heartbeat is considered fresh if it is at most HEARTBEAT_MAX_AGE_SEC old.
If `data/runtime/` or `heartbeat.json` is missing the merged view
returns `runtime_detected=False`. Nothing crashes.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import statistics
import threading
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import ops, runtime_env
from . import strategy_families

HEARTBEAT_MAX_AGE_SEC = 60          # heartbeat older than this => stale
RUNTIME_DIR_NAME      = "runtime"
STRATEGY_HISTORY_FILE = "strategy_history.jsonl"
STRATEGY_DISPLAY_PREFS_FILE = "strategy_display_prefs.json"

# executions.jsonl / orders.jsonl can grow large. A small tail window drops older
# fills so NT restart replays no longer merge with their originals — inflating
# FIFO PnL in the UI. Prefer a generous tail (or unlimited via max_lines <= 0).
RUNTIME_EXEC_JSONL_MAX_LINES = 250_000
RUNTIME_ORDER_JSONL_MAX_LINES = 100_000
RUNTIME_JSONL_ROTATE_BYTES = 32 * 1024 * 1024
RUNTIME_JSONL_ROTATE_KEEP = 6
RUNTIME_JSONL_ROTATE_FILES = ("executions.jsonl", "orders.jsonl", "errors.jsonl")

_JSONL_CACHE: Dict[str, Tuple[Tuple[int, int, int], List[Dict[str, Any]]]] = {}
_JSONL_CACHE_ORDER: List[str] = []
_JSONL_CACHE_MAX_ENTRIES = 32
_ACTIVITY_VIEW_CACHE: Dict[Tuple[Any, ...], Tuple[List[Dict[str, Any]], Dict[str, Any]]] = {}
_ACTIVITY_VIEW_CACHE_ORDER: List[Tuple[Any, ...]] = []
_RUNTIME_CONTEXT = threading.local()
_ACTIVITY_VIEW_CACHE_MAX_ENTRIES = 24

# Subset of locked params we re-verify at runtime per Phase 17 spec.
B1_LOCKED_PARAMS_CHECK: Dict[str, Any] = {
    "EnableLong":          False,
    "EnableShort":         True,
    "TradeStartTime":      635,
    "TradeEndTime":        700,
    "MinStopTicks":        12,
    "MaxStopTicks":        12,
    "RewardRiskRatio":     3.5,
    "RiskPerTradePct":     2.0,
    "UserMaxContracts":    5,
    "RoundTurnCommission": 1.90,
    "SlippageTicks":       1,
}

PROFILE_RUNTIME_PARAM_SKIP = frozenset({
    # NinjaTrader's runtime exporter may omit enum/display-only properties.
    # Wrapper strategies still hard-lock these in SetDefaults, so absence here
    # should not create a false parameter mismatch.
    "SetupMode",
    "_session_template",
})

TRADE_WINDOW_PARAM_KEYS = (
    "TradeStartTime", "TradeEndTime",
    "UseSecondTradeWindow", "SecondTradeStartTime", "SecondTradeEndTime",
    "Use24hSession", "IntradayOnly",
)

_INACTIVE_SECOND_WINDOW_KEYS = frozenset({
    "SecondTradeStartTime", "SecondTradeEndTime",
})

_TIME_WINDOW_MISMATCH_KEYS = frozenset({
    "TradeStartTime", "TradeEndTime", "UseSecondTradeWindow",
    "SecondTradeStartTime", "SecondTradeEndTime", "ForceFlatTime",
})


def _truthy_param(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    s = str(v or "").strip().lower()
    return s in ("1", "true", "yes", "on")


def _parse_hhmm_param(v: Any) -> Optional[int]:
    """Parse HHMM int from bridge/profile values (635, \"06:35\", etc.)."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        n = int(v)
        return n if n > 0 else None
    s = str(v).strip()
    if not s:
        return None
    if ":" in s:
        parts = s.split(":", 1)
        try:
            hh = int(parts[0])
            mm = int(parts[1])
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                return hh * 100 + mm
        except (TypeError, ValueError):
            return None
    try:
        n = int(s)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _hhmm_to_display(hhmm: int) -> str:
    """HHMM int → zero-padded 12h clock with AM/PM (e.g. 635 → 06:35 AM)."""
    hhmm = int(hhmm)
    if hhmm <= 0:
        return ""
    hh24 = hhmm // 100
    mm = hhmm % 100
    period = "AM" if hh24 < 12 else "PM"
    hh12 = hh24 % 12 or 12
    return f"{hh12:02d}:{mm:02d} {period}"


_TRADE_WINDOW_RANGE_RE = re.compile(
    r"^(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})$"
)


def _build_trade_window_label_from_config(config: Any) -> str:
    """12h label from structured trade_window config."""
    if not isinstance(config, dict):
        return ""
    if config.get("use_24h"):
        return "круглосуточно"
    windows = config.get("windows") or []
    parts: List[str] = []
    for w in windows:
        if not isinstance(w, dict):
            continue
        start = int(w.get("start") or 0)
        end = int(w.get("end") or 0)
        if start > 0 and end > 0:
            parts.append(f"{_hhmm_to_display(start)} – {_hhmm_to_display(end)}")
    return " + ".join(parts)


def _reformat_trade_window_pt_label(label: str) -> str:
    """Parse legacy 24h profile strings into 12h AM/PM; return unchanged if unknown."""
    s = str(label or "").strip()
    if not s:
        return s
    if s.lower() == "круглосуточно":
        return s
    suffix = ""
    m_ann = re.search(r"\s*(\([^)]*\))\s*$", s)
    if m_ann:
        suffix = " " + m_ann.group(1).strip()
        s = s[:m_ann.start()].strip()
    s = re.sub(r"\s+PT\s*$", "", s, flags=re.IGNORECASE).strip()
    chunks = [c.strip() for c in re.split(r"\s*\+\s*", s) if c.strip()]
    if not chunks:
        return label
    out: List[str] = []
    for chunk in chunks:
        m = _TRADE_WINDOW_RANGE_RE.match(chunk)
        if not m:
            return label
        start = _parse_hhmm_param(m.group(1))
        end = _parse_hhmm_param(m.group(2))
        if not start or not end:
            return label
        out.append(f"{_hhmm_to_display(start)} – {_hhmm_to_display(end)}")
    return " + ".join(out) + suffix


def _build_trade_window_pt_from_params(params: Any) -> Optional[str]:
    """Human-readable PT entry window label (excludes ForceFlatTime)."""
    if not isinstance(params, dict):
        return None
    if _truthy_param(params.get("Use24hSession")):
        return "круглосуточно"
    return _build_trade_window_label_from_config(_extract_trade_window_config(params)) or None


def _extract_trade_window_config(params: Any) -> Dict[str, Any]:
    """Structured entry-window config for UI tint logic."""
    if not isinstance(params, dict):
        return {"windows": [], "use_24h": False, "intraday_only": True, "has_windows": False}
    use_24h = _truthy_param(params.get("Use24hSession"))
    intraday = params.get("IntradayOnly")
    intraday_only = True if intraday is None else _truthy_param(intraday)
    windows: List[Dict[str, int]] = []
    start = _parse_hhmm_param(params.get("TradeStartTime"))
    end = _parse_hhmm_param(params.get("TradeEndTime"))
    if start and end:
        windows.append({"start": start, "end": end})
    if _truthy_param(params.get("UseSecondTradeWindow")):
        s2 = _parse_hhmm_param(params.get("SecondTradeStartTime"))
        e2 = _parse_hhmm_param(params.get("SecondTradeEndTime"))
        if s2 and e2:
            windows.append({"start": s2, "end": e2})
    return {
        "windows": windows,
        "use_24h": use_24h,
        "intraday_only": intraday_only,
        "has_windows": bool(windows),
    }


def _merge_trade_window_params(*sources: Any) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for src in sources:
        if not isinstance(src, dict):
            continue
        for key in TRADE_WINDOW_PARAM_KEYS:
            if key in src and src[key] is not None and src[key] != "":
                merged[key] = src[key]
    return merged


def _resolve_trade_window_for_strategy(
        registry_hit: Optional[Dict[str, Any]],
        runtime_params: Any,
        profile_trade_window_pt: str = "") -> Dict[str, Any]:
    locked = (registry_hit or {}).get("locked_params") or {}
    merged = _merge_trade_window_params(locked, runtime_params or {})
    config = _extract_trade_window_config(merged)
    if config.get("use_24h"):
        label = "круглосуточно"
    elif config.get("has_windows"):
        label = _build_trade_window_label_from_config(config) or ""
    else:
        label = str(profile_trade_window_pt or "").strip()
        if not label:
            label = _build_trade_window_pt_from_params(merged) or ""
        elif label.lower() != "круглосуточно":
            label = _reformat_trade_window_pt_label(label)
    return {
        "trade_window_pt": label or None,
        "trade_window": config,
    }


def pt_now_hhmm(now: Optional[datetime] = None) -> int:
    """Current Pacific Time as HHMM (matches NinjaTrader PT strategies)."""
    dt = now or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        local = dt.astimezone(ZoneInfo("America/Los_Angeles"))
    except Exception:
        local = dt
    return local.hour * 100 + local.minute


def is_hhmm_in_trade_window(tod_hhmm: int, config: Any) -> Optional[bool]:
    """True/False when evaluable; None when no window data."""
    if not isinstance(config, dict):
        return None
    if config.get("use_24h"):
        return True
    windows = config.get("windows") or []
    if not windows:
        return None
    for w in windows:
        if not isinstance(w, dict):
            continue
        start = int(w.get("start") or 0)
        end = int(w.get("end") or 0)
        if start > 0 and end > 0 and start <= tod_hhmm <= end:
            return True
    return False


def _sanitize_runtime_locked_params(expected: Any) -> Dict[str, Any]:
    """Drop profile metadata keys before runtime param comparison."""
    if not isinstance(expected, dict):
        return {}
    out: Dict[str, Any] = {}
    for k, v in expected.items():
        key = str(k or "")
        if not key or key.startswith("_") or key in PROFILE_RUNTIME_PARAM_SKIP:
            continue
        if isinstance(v, (int, float, bool, str)):
            out[key] = v
    return out


def _runtime_params_lookup(runtime_params: Dict[str, Any], key: str) -> Any:
    rp = runtime_params or {}
    if key in rp:
        return rp.get(key)
    rp_lower = {str(k).lower(): v for k, v in rp.items()}
    return rp_lower.get(str(key).lower())


def _effective_use_second_trade_window(expected: Dict[str, Any],
                                       runtime_params: Dict[str, Any]) -> bool:
    """Second-window sub-params are validated only when the window is active."""
    act = _runtime_params_lookup(runtime_params, "UseSecondTradeWindow")
    if act is not None:
        return _truthy_param(act)
    return _truthy_param(expected.get("UseSecondTradeWindow"))


def _iter_locked_params_for_validation(expected: Dict[str, Any],
                                       runtime_params: Dict[str, Any]):
    sanitized = _sanitize_runtime_locked_params(expected)
    use_second = _effective_use_second_trade_window(sanitized, runtime_params)
    for k, v_exp in sanitized.items():
        if not use_second and k in _INACTIVE_SECOND_WINDOW_KEYS:
            continue
        yield k, v_exp


def _format_param_mismatch_value(key: str, value: Any) -> str:
    if value is None:
        return "—"
    if key in TRADE_WINDOW_PARAM_KEYS and key != "UseSecondTradeWindow" \
            and key not in ("Use24hSession", "IntradayOnly"):
        hhmm = _parse_hhmm_param(value)
        if hhmm:
            return _hhmm_to_display(hhmm)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _params_mismatch_recommendation(mismatches: List[Dict[str, Any]]) -> Optional[str]:
    if not mismatches:
        return None
    keys = {str(m.get("key") or "") for m in mismatches}
    if keys & _TIME_WINDOW_MISMATCH_KEYS:
        return (
            "Экземпляр в NinjaTrader, вероятно, создан до Time Window Audit. "
            "Удалите стратегию с графика и добавьте заново через Enable с locked-параметрами "
            "профиля (или вручную выставьте TradeEndTime/UseSecondTradeWindow и перезапустите)."
        )
    return (
        "Параметры в NinjaTrader отличаются от locked-профиля. "
        "Сверьте diff ниже и примените значения профиля перед paper/live."
    )


def _sanitize_command_params(params: Any) -> Dict[str, Any]:
    """Drop profile metadata keys before persisting runtime command params."""
    if not isinstance(params, dict):
        return {}
    out: Dict[str, Any] = {}
    for k, v in params.items():
        key = str(k or "")
        if not key or key.startswith("_") or key == "_session_template":
            continue
        if isinstance(v, (int, float, bool, str)):
            out[key] = v
    return out

LIVE_ACCOUNT_HINTS = ("live", "real", "production", "prod")
PAPER_ACCOUNT_HINTS = ("sim101", "sim ", "paper")
DEMO_ACCOUNT_HINTS  = ("demo",)

# Accounts that NinjaTrader exposes but are system/backtest pseudo-accounts —
# never shown in the "Торговля онлайн" dropdown and never selectable.
_SYSTEM_ACCOUNT_NAMES = frozenset({"backtest", "sim101", "playback101"})

STRATEGY_ID_ALIASES = {
    "b1_shortonly": "vwap_short_mnq_5m_v1",
    "vwappullbackmgc5mv1": "vwap_pullback_mgc_5m_v1",
    "b1stop24mgc5mc003": "mgc_b1_stop24_5m_c003",
    "b1stop20mgc5mc004": "mgc_b1_stop20_5m_c004",
    "ntamnqmicroorbopenscalp": "orb_open_scalp_mnq_1m_v1",
    "ntamnqmicroorbretestscalpc013": "ntamnqmicroorbretestscalpc013",
    "ntamnqfullsessionorbretestscalpc014": "ntamnqfullsessionorbretestscalpc014",
    "ntamnqliquiditysweepreversalc015": "ntamnqliquiditysweepreversalc015",
    "ntamnqopendriveshortscalpc016": "ntamnqopendriveshortscalpc016",
    "ntamnqpostactivescalpc017": "ntamnqpostactivescalpc017",
    "ntamnqdailyopenscalpc018": "ntamnqdailyopenscalpc018",
    "ntamnqheadshouldersdivergencec019": "ntamnqheadshouldersdivergencec019",
    "ntamnqheadshouldersdivergencec020": "ntamnqheadshouldersdivergencec020",
    "ntamnqprecashcompressionbreakoutc019": "ntamnqprecashcompressionbreakoutc019",
    "ntamnqpostclustersqueezebreakoutc019": "ntamnqpostclustersqueezebreakoutc019",
    "ntamnqpostclustervwapfadec019": "ntamnqpostclustervwapfadec019",
    "ntamnqovernightsettlementbreakoutc019": "ntamnqovernightsettlementbreakoutc019",
    "ntamnqovernightsettlementreversionc019": "ntamnqovernightsettlementreversionc019",
    "ntamnqrthvwappullbackc019": "ntamnqrthvwappullbackc019",
    "ntamnqrthtrenddayh1c019": "ntamnqrthtrenddayh1c019",
    "ntamnqrthorbretesth1c019": "ntamnqrthorbretesth1c019",
    "ntamnqrthgapgoh1c019": "ntamnqrthgapgoh1c019",
    "ntamnqresearchhub": "mnq_research_hub",
    "ntamnqsessionedgeenginec020": "mnq_research_hub",
    "ntamicrogoldsessionsweepreversalpilot": "ntamicrogoldsessionsweepreversalpilot",
    "ntamgclatemorningsweepc006": "ntamgclatemorningsweepc006",
}

STRATEGY_CLASS_METADATA = {
    "NTAMicroVwapRiskPilot": {
        "strategy_id": "vwap_short_mnq_5m_v1",
        "display_name": "VWAP Short MNQ 5m v1 c011",
        "legacy_strategy_ids": ["b1_shortonly"],
    },
    "VWAPPullbackMGC5mV1": {
        "strategy_id": "vwap_pullback_mgc_5m_v1",
        "display_name": "Scalping Gold MGC 5m v1 c001",
        "legacy_strategy_ids": ["vwappullbackmgc5mv1"],
    },
    "B1ShortOnlyMGC5mV2": {
        "strategy_id": "mgc_b1_short_5m_v2",
        "display_name": "B1 ShortOnly MGC 5m v2 c002",
        "legacy_strategy_ids": ["mgc_b1_shortonly_5m_v2"],
    },
    "B1Stop24MGC5mC003": {
        "strategy_id": "mgc_b1_stop24_5m_c003",
        "display_name": "B1 Stop24 MGC 5m c003",
        "legacy_strategy_ids": ["b1stop24mgc5mc003"],
    },
    "B1Stop20MGC5mC004": {
        "strategy_id": "mgc_b1_stop20_5m_c004",
        "display_name": "B1 Stop20 MGC 5m c004",
        "legacy_strategy_ids": ["b1stop20mgc5mc004"],
    },
    "PullbackMNQ5mV2": {
        "strategy_id": "pullback_mnq_5m_v2",
        "display_name": "Pullback MNQ 5m v2",
        "legacy_strategy_ids": [],
    },
    "NTAMicroVwapRiskExplorer": {
        "strategy_id": "vwap_risk_explorer_mgc_5m_v1",
        "display_name": "VWAP Risk Explorer MGC 5m v1",
        "legacy_strategy_ids": [],
    },
    "NTAMicroSessionEdgeExplorer": {
        "strategy_id": "session_edge_multi_5m_v2",
        "display_name": "Session Edge Multi 5m v2",
        "legacy_strategy_ids": [],
    },
    "NTAMicroMnqScalpPilot": {
        "strategy_id": "scalping_mnq_1m_v1",
        "display_name": "Scalping MNQ 1m v1",
        "legacy_strategy_ids": [],
    },
    "NTAMnqResearchHub": {
        "strategy_id": "mnq_research_hub",
        "display_name": "MNQ Research Hub",
        "legacy_strategy_ids": ["ntamnqsessionedgeenginec020"],
    },
    "NTAMnqHeadShouldersDivergenceC126": {
        "strategy_id": "ntamnqheadshouldersdivergencec126",
        "display_name": "HeadShoulders Divergence MNQ 1m v1 c126",
        "legacy_strategy_ids": [],
    },
    "NTAMnqHeadShouldersDivergenceC019": {
        "strategy_id": "ntamnqheadshouldersdivergencec019",
        "display_name": "HeadShoulders Divergence MNQ 1m v1 c019",
        "legacy_strategy_ids": [],
    },
    "NTAMnqHeadShouldersDivergenceC020": {
        "strategy_id": "ntamnqheadshouldersdivergencec020",
        "display_name": "HeadShoulders Divergence MNQ 1m v1 c020",
        "legacy_strategy_ids": [],
    },
    "NTAMnqSessionEdgeEngineC020": {
        "strategy_id": "mnq_research_hub",
        "display_name": "MNQ Research Hub (legacy C020 engine)",
        "legacy_strategy_ids": ["ntamnqresearchhub"],
    },
    "NTAMnqMicroOrbOpenScalp": {
        "strategy_id": "orb_open_scalp_mnq_1m_v1",
        "display_name": "Scalping MNQ 1m v1 c012",
        "legacy_strategy_ids": ["ntamnqmicroorbopenscalp"],
    },
    "NTAMnqMicroOrbRetestScalpC013": {
        "strategy_id": "ntamnqmicroorbretestscalpc013",
        "display_name": "Scalping Orb Retest MNQ 1m v1 c013",
        "legacy_strategy_ids": [],
    },
    "NTAMnqFullSessionOrbRetestScalpC014": {
        "strategy_id": "ntamnqfullsessionorbretestscalpc014",
        "display_name": "Scalping Full Session ORB Retest MNQ 1m v1 c014",
        "legacy_strategy_ids": [],
    },
    "NTAMnqLiquiditySweepReversalC015": {
        "strategy_id": "ntamnqliquiditysweepreversalc015",
        "display_name": "Scalping Open Pressure Stop MNQ 1m v1 c015",
        "legacy_strategy_ids": [],
    },
    "NTAMnqOpenDriveShortScalpC016": {
        "strategy_id": "ntamnqopendriveshortscalpc016",
        "display_name": "Scalping Open Drive Short MNQ 1m v1 c016",
        "legacy_strategy_ids": [],
    },
    "NTAMnqPostActiveScalpC017": {
        "strategy_id": "ntamnqpostactivescalpc017",
        "display_name": "Scalping Post-Active MNQ 1m v1 c017",
        "legacy_strategy_ids": [],
    },
    "NTAMnqDailyOpenScalpC018": {
        "strategy_id": "ntamnqdailyopenscalpc018",
        "display_name": "Scalping MNQ 1m v1 c018",
        "legacy_strategy_ids": [],
    },
    "NTAMnqPreCashCompressionBreakoutC019": {
        "strategy_id": "ntamnqprecashcompressionbreakoutc019",
        "display_name": "Compression Breakout MNQ 5m v1 c019",
        "legacy_strategy_ids": [],
    },
    "NTAMnqPostClusterSqueezeBreakoutC019": {
        "strategy_id": "ntamnqpostclustersqueezebreakoutc019",
        "display_name": "Post-Cluster Squeeze MNQ 15m v1 c019",
        "legacy_strategy_ids": [],
    },
    "NTAMnqPostClusterVwapFadeC019": {
        "strategy_id": "ntamnqpostclustervwapfadec019",
        "display_name": "Post-Cluster VWAP Fade MNQ 5m v1 c019",
        "legacy_strategy_ids": [],
    },
    "NTAMnqOvernightSettlementBreakoutC019": {
        "strategy_id": "ntamnqovernightsettlementbreakoutc019",
        "display_name": "Overnight Settlement Breakout MNQ 15m v1 c019",
        "legacy_strategy_ids": [],
    },
    "NTAMnqOvernightSettlementReversionC019": {
        "strategy_id": "ntamnqovernightsettlementreversionc019",
        "display_name": "Overnight Settlement Reversion MNQ 15m v1 c019",
        "legacy_strategy_ids": [],
    },
    "NTAMnqRthVwapPullbackC019": {
        "strategy_id": "ntamnqrthvwappullbackc019",
        "display_name": "RTH VWAP Pullback MNQ 15m v1 c019",
        "legacy_strategy_ids": [],
    },
    "NTAMnqRthTrendDayH1C019": {
        "strategy_id": "ntamnqrthtrenddayh1c019",
        "display_name": "RTH Trend Day H1 MNQ v1 c019",
        "legacy_strategy_ids": [],
    },
    "NTAMnqRthOrbRetestH1C019": {
        "strategy_id": "ntamnqrthorbretesth1c019",
        "display_name": "RTH ORB Retest H1 MNQ v1 c019",
        "legacy_strategy_ids": [],
    },
    "NTAMnqRthGapGoH1C019": {
        "strategy_id": "ntamnqrthgapgoh1c019",
        "display_name": "RTH Gap Go H1 MNQ v1 c019",
        "legacy_strategy_ids": [],
    },
    "NTAMicroGoldSessionSweepReversalPilot": {
        "strategy_id": "ntamicrogoldsessionsweepreversalpilot",
        "display_name": "Scalping Gold Session Sweep Reversal MGC 5m v1 c001",
        "legacy_strategy_ids": [],
    },
    "NTAMgcLateMorningSweepC006": {
        "strategy_id": "ntamgclatemorningsweepc006",
        "display_name": "Scalping Late Morning Sweep MGC 1m v1 c006",
        "legacy_strategy_ids": [],
    },
    "NTASessionVwapReclaimScalper": {
        "strategy_id": "ntasessionvwapreclaimscalper",
        "display_name": "Session VWAP Reclaim Scalper",
        "legacy_strategy_ids": [],
    },
    "NTACapitulationSnapbackPilot": {
        "strategy_id": "ntacapitulationsnapbackpilot",
        "display_name": "Capitulation Snapback Research Pilot",
        "legacy_strategy_ids": [],
    },
    "NTAMgcCapitulationSnapbackC007": {
        "strategy_id": "mgc_capitulation_snapback_5m_c007",
        "display_name": "Capitulation Snapback MGC 5m c007",
        "cell_id": "CELL-007",
        "legacy_strategy_ids": [],
    },
    "NTAEntropyTransitionFieldPilot": {
        "strategy_id": "ntaentropytransitionfieldpilot",
        "display_name": "Entropy Transition Field Research Pilot",
        "legacy_strategy_ids": [],
    },
    "NTAMnqEntropyTransitionFieldC127": {
        "strategy_id": "mnq_entropy_transition_field_5m_c127_paper_v1",
        "display_name": "Entropy Transition Field MNQ 5m c127",
        "cell_id": "CELL-127",
        "legacy_strategy_ids": [],
    },
    "NTAGeodesicPhasePressurePilot": {
        "strategy_id": "ntageodesicphasepressurepilot",
        "display_name": "Geodesic Phase Pressure Research Pilot",
        "legacy_strategy_ids": [],
    },
    "NTAnalyzerEveryNBarLong": {
        "strategy_id": "every_n_bar_long_generic_any_v1",
        "display_name": "Every N Bar Long Generic Any v1",
        "legacy_strategy_ids": [],
    },
    "StrategiyaUrovney": {
        "strategy_id": "levels_strategy_userdefined_v1",
        "display_name": "Levels Strategy UserDefined v1",
        "legacy_strategy_ids": [],
    },
}

_UNMAPPED_STRATEGY_MARKERS = frozenset({
    "", "short", "long", "entry", "exit", "target", "stop", "manual",
    "buy", "sell", "sellshort", "buytocover",
})

_LEGACY_SIGNAL_CLASS_MAP = {
    "capsnapl": "NTAMgcCapitulationSnapbackC007",
    "capsnaps": "NTAMgcCapitulationSnapbackC007",
    "entfieldl": "NTAMnqEntropyTransitionFieldC127",
    "entfields": "NTAMnqEntropyTransitionFieldC127",
    "gpp_long": "NTAGeodesicPhasePressurePilot",
    "gpp_short": "NTAGeodesicPhasePressurePilot",
}

_LEGACY_STRATEGY_ATTRIBUTIONS = (
    # Bridge builds before 1.2.2 exported old account-level fills with only
    # blank/Short strategy markers. These entries are limited to order/execution
    # ids whose bracket geometry can be tied back to a known deployed cell.
    {
        "account_name": "DEMO3369390",
        "date_pt": "2026-05-13",
        "instrument_root": "MGC",
        "strategy_classes": ("B1Stop20MGC5mC004",),
        "confidence": "exact",
        "source": "legacy_order_bracket: MGC 20 ticks / RR 3.5",
        "order_ids": frozenset({"43", "44", "45"}),
        "execution_ids": frozenset({"355476070233_1", "355476070267_1"}),
    },
    {
        "account_name": "DEMO3369390",
        "date_pt": "2026-05-13",
        "instrument_root": "MGC",
        "strategy_classes": ("B1Stop24MGC5mC003",),
        "confidence": "exact",
        "source": "legacy_order_bracket: MGC 24 ticks / RR 3.0",
        "order_ids": frozenset({"42", "46", "47"}),
        "execution_ids": frozenset({"355476070231_1", "355476070273_1"}),
    },
    {
        "account_name": "DEMO3369390",
        "date_pt": "2026-05-13",
        "instrument_root": "MGC",
        "strategy_classes": ("VWAPPullbackMGC5mV1", "B1ShortOnlyMGC5mV2"),
        "confidence": "ambiguous",
        "source": "legacy_order_bracket: MGC 12 ticks / RR 3.5 matches C001 and C002",
        "order_ids": frozenset({"40", "41", "48", "49", "50", "51"}),
        "execution_ids": frozenset({
            "355476070226_1", "355476070229_1",
            "355476070278_1", "355476070282_1",
        }),
    },
    {
        "account_name": "DEMO3369390",
        "date_pt": "2026-05-13",
        "instrument_root": "MNQ",
        "strategy_classes": ("NTAMnqMicroOrbOpenScalp", "NTAMnqMicroOrbRetestScalpC013"),
        "confidence": "ambiguous",
        "source": "legacy_order_bracket: MNQ ORB bracket matches C012 and C013",
        "order_ids": frozenset({"52", "53", "54", "55", "56", "57"}),
        "execution_ids": frozenset({
            "355476070312_1", "355476070315_1",
            "355476070331_1", "355476070337_1",
        }),
    },
    {
        "account_name": "DEMO3369390",
        "date_pt": "2026-05-14",
        "instrument_root": "MNQ",
        "strategy_classes": ("NTAMnqLiquiditySweepReversalC015", "NTAMnqOpenDriveShortScalpC016"),
        "confidence": "ambiguous",
        "source": "legacy_order_bracket: MNQ RR 4.0 before C016 stopped; C015 and C016 both active",
        "order_ids": frozenset({
            "64", "65", "66", "67", "68", "69", "72", "73", "74",
            "75", "76", "77", "78", "79", "80", "81", "82", "83",
            "84", "85", "86", "88", "89", "90", "91", "92", "93",
            "96", "97", "98", "99", "100", "101", "106", "107", "108",
            "112", "113", "114", "115", "116", "117", "118", "119",
            "120", "121", "122", "123", "125", "126", "127",
        }),
        "execution_ids": frozenset({
            "355476070430_1", "355476070433_1", "355476070448_1",
            "355476070454_1", "355476070494_1", "355476070503_1",
            "355476070520_1", "355476070523_1", "355476070538_1",
            "355476070544_1", "355476070572_1", "355476070581_1",
            "355476070598_1", "355476070609_1", "355476070630_1",
            "355476070639_1", "355476070656_1", "355476070667_1",
            "355476070694_1", "355476070697_1", "355476070712_1",
            "355476070717_1", "355476070770_1", "355476070782_1",
            "355476070814_1", "355476070817_1", "355476070835_1",
            "355476070841_1", "355476070866_1", "355476070875_1",
            "355476070892_1", "355476070901_1", "355476070921_1",
            "355476070930_1",
        }),
    },
    {
        "account_name": "DEMO3369390",
        "date_pt": "2026-05-14",
        "instrument_root": "MNQ",
        "strategy_classes": ("NTAMnqLiquiditySweepReversalC015",),
        "confidence": "exact",
        "source": "legacy_order_bracket: MNQ RR 4.0 after C016 stopped",
        "order_ids": frozenset({
            "129", "130", "131", "133", "134", "135",
            "136", "137", "138", "139", "140", "141", "142", "143",
        }),
        "execution_ids": frozenset({
            "355476070953_1", "355476070962_1", "355476070985_1",
            "355476070994_1", "355476071011_1", "355476071023_1",
            "355476071037_1", "355476071046_1",
        }),
    },
)

_FUTURES_MULTIPLIER = {
    "MES": 5.0, "MNQ": 2.0, "MYM": 0.5, "M2K": 5.0,
    "MGC": 10.0, "SIL": 1000.0, "SI": 5000.0, "MSI": 1000.0,
    "MCL": 100.0, "MNG": 1000.0, "MBT": 0.1, "MET": 0.1,
    "M6E": 12500.0, "M6B": 6250.0, "M6A": 10000.0,
    "M6J": 1250000.0, "M6C": 10000.0,
}


def canonical_strategy_id(strategy_id: Any) -> str:
    raw = str(strategy_id or "").strip().lower()
    return STRATEGY_ID_ALIASES.get(raw, raw)


def _normalize_runtime_strategy_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Return a canonicalized copy of a bridge runtime row.

    This keeps the UI stable while an older, still-running bridge DLL may be
    writing legacy IDs such as ``b1_shortonly`` into data/runtime/strategies.json.
    The bridge source is also canonicalized; this is only a read-time guard.
    """
    out = dict(row)
    cls = str(out.get("strategy_class") or out.get("class_name") or "").strip()
    meta = STRATEGY_CLASS_METADATA.get(cls)
    if meta:
        canonical_sid = str(meta["strategy_id"])
        display_name = str(meta["display_name"])
        out["strategy_id"] = canonical_sid
        out["stable_id"] = canonical_sid
        out["display_name"] = display_name
        out["strategy_name"] = display_name
        legacy_ids = list(out.get("legacy_strategy_ids") or [])
        for legacy_id in meta.get("legacy_strategy_ids") or []:
            if legacy_id not in {str(x) for x in legacy_ids}:
                legacy_ids.append(legacy_id)
        out["legacy_strategy_ids"] = legacy_ids
        params = out.get("params")
        if isinstance(params, dict):
            params = dict(params)
            params["Name"] = display_name
            out["params"] = params
        return out
    sid = out.get("strategy_id")
    if sid:
        out["strategy_id"] = canonical_strategy_id(sid)
        out.setdefault("stable_id", out["strategy_id"])
    return out


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def runtime_dir() -> Path:
    override = getattr(_RUNTIME_CONTEXT, "runtime_dir", "")
    if override:
        return Path(str(override))
    d = runtime_env.data_path(RUNTIME_DIR_NAME, project_root=ops._project_root())
    return d


@contextmanager
def runtime_dir_override(path: Any):
    previous = getattr(_RUNTIME_CONTEXT, "runtime_dir", "")
    _RUNTIME_CONTEXT.runtime_dir = str(path or "")
    try:
        yield
    finally:
        _RUNTIME_CONTEXT.runtime_dir = previous


def _path(name: str) -> Path:
    return runtime_dir() / name


# ---------------------------------------------------------------------------
# JSON / JSONL helpers
# ---------------------------------------------------------------------------

def _read_json(p: Path, default: Any = None) -> Any:
    if not p.is_file():
        return default
    try:
        with p.open("r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def _read_jsonl(p: Path, max_lines: Optional[int] = 5000) -> List[Dict[str, Any]]:
    if not p.is_file():
        return []
    normalized_max = int(max_lines or 0)
    try:
        st = p.stat()
        sig = (st.st_size, st.st_mtime_ns, normalized_max)
        key = str(p.resolve()) + f"|{normalized_max}"
        cached = _JSONL_CACHE.get(key)
        if cached and cached[0] == sig:
            try:
                _JSONL_CACHE_ORDER.remove(key)
            except ValueError:
                pass
            _JSONL_CACHE_ORDER.append(key)
            return [dict(r) if isinstance(r, dict) else r for r in cached[1]]
    except Exception:
        sig = None
        key = ""
    try:
        with p.open("r", encoding="utf-8-sig") as f:
            if max_lines is not None and max_lines > 0:
                lines = list(deque(f, maxlen=max_lines))
            else:
                lines = list(f)
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    if sig is not None:
        _JSONL_CACHE[key] = (sig, [dict(r) if isinstance(r, dict) else r for r in out])
        try:
            _JSONL_CACHE_ORDER.remove(key)
        except ValueError:
            pass
        _JSONL_CACHE_ORDER.append(key)
        while len(_JSONL_CACHE_ORDER) > _JSONL_CACHE_MAX_ENTRIES:
            old_key = _JSONL_CACHE_ORDER.pop(0)
            _JSONL_CACHE.pop(old_key, None)
    return out


def _jsonl_file_sig(name: str) -> Tuple[str, Optional[int], Optional[int]]:
    p = _path(name)
    try:
        st = p.stat()
    except OSError:
        return (str(p.resolve()), None, None)
    return (str(p.resolve()), st.st_size, st.st_mtime_ns)


def _clear_jsonl_cache_for(path: Path) -> None:
    try:
        prefix = str(path.resolve()) + "|"
    except Exception:
        prefix = str(path) + "|"
    for key in list(_JSONL_CACHE.keys()):
        if key.startswith(prefix):
            _JSONL_CACHE.pop(key, None)
            try:
                _JSONL_CACHE_ORDER.remove(key)
            except ValueError:
                pass
    _ACTIVITY_VIEW_CACHE.clear()
    _ACTIVITY_VIEW_CACHE_ORDER.clear()


def _runtime_rotation_stamp(now: Optional[datetime] = None) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _rotated_jsonl_files(path: Path) -> List[Path]:
    try:
        candidates = list(path.parent.glob(path.name + ".*.rotated"))
    except Exception:
        return []

    def sort_key(p: Path) -> Tuple[int, str]:
        try:
            return (p.stat().st_mtime_ns, p.name)
        except OSError:
            return (0, p.name)

    return sorted([p for p in candidates if p.is_file()], key=sort_key, reverse=True)


def rotate_runtime_jsonl_files(*, max_bytes: int = RUNTIME_JSONL_ROTATE_BYTES,
                               keep: int = RUNTIME_JSONL_ROTATE_KEEP,
                               names: Optional[Iterable[str]] = None,
                               now: Optional[datetime] = None) -> Dict[str, Any]:
    """Rotate large runtime JSONL ingress files without blocking readers.

    The NinjaTrader bridge can continue appending to the canonical file name;
    after a successful rename we create a fresh empty file in the same location.
    Rotation is best-effort because Windows file locks may temporarily block a
    rename while the bridge is writing.
    """
    rdir = runtime_dir()
    threshold = max(0, int(max_bytes or 0))
    retention = max(0, int(keep or 0))
    selected = tuple(names or RUNTIME_JSONL_ROTATE_FILES)
    result: Dict[str, Any] = {
        "ok": True,
        "runtime_dir": str(rdir),
        "max_bytes": threshold,
        "keep": retention,
        "files": [],
    }
    if not rdir.is_dir():
        return result

    stamp = _runtime_rotation_stamp(now)
    for raw_name in selected:
        safe_name = Path(str(raw_name or "")).name
        row: Dict[str, Any] = {
            "name": safe_name,
            "path": str(rdir / safe_name),
            "exists": False,
            "size": 0,
            "rotated": False,
            "pruned": [],
        }
        if not safe_name or safe_name != str(raw_name or "") or not safe_name.endswith(".jsonl"):
            row["error"] = "invalid_name"
            result["ok"] = False
            result["files"].append(row)
            continue
        path = rdir / safe_name
        try:
            st = path.stat()
        except OSError:
            result["files"].append(row)
            continue
        row["exists"] = True
        row["size"] = st.st_size
        try:
            if threshold > 0 and st.st_size >= threshold and st.st_size > 0:
                idx = 0
                rotated = path.with_name(f"{path.name}.{stamp}.rotated")
                while rotated.exists():
                    idx += 1
                    rotated = path.with_name(f"{path.name}.{stamp}.{idx}.rotated")
                os.replace(str(path), str(rotated))
                path.touch()
                _clear_jsonl_cache_for(path)
                row["rotated"] = True
                row["rotated_path"] = str(rotated)
            rotated_files = _rotated_jsonl_files(path)
            for stale in rotated_files[retention:]:
                try:
                    stale.unlink()
                    row["pruned"].append(str(stale))
                except OSError as exc:
                    row["prune_error"] = str(exc)
                    result["ok"] = False
        except OSError as exc:
            row["error"] = str(exc)
            result["ok"] = False
        result["files"].append(row)
    return result


def _clone_activity_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [dict(r) if isinstance(r, dict) else r for r in rows]


def _activity_cache_get(key: Tuple[Any, ...]) -> Optional[Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
    cached = _ACTIVITY_VIEW_CACHE.get(key)
    if cached is None:
        return None
    try:
        _ACTIVITY_VIEW_CACHE_ORDER.remove(key)
    except ValueError:
        pass
    _ACTIVITY_VIEW_CACHE_ORDER.append(key)
    rows, meta = cached
    return _clone_activity_rows(rows), dict(meta)


def _activity_cache_put(key: Tuple[Any, ...],
                        rows: List[Dict[str, Any]],
                        meta: Dict[str, Any]) -> None:
    _ACTIVITY_VIEW_CACHE[key] = (_clone_activity_rows(rows), dict(meta))
    try:
        _ACTIVITY_VIEW_CACHE_ORDER.remove(key)
    except ValueError:
        pass
    _ACTIVITY_VIEW_CACHE_ORDER.append(key)
    while len(_ACTIVITY_VIEW_CACHE_ORDER) > _ACTIVITY_VIEW_CACHE_MAX_ENTRIES:
        old_key = _ACTIVITY_VIEW_CACHE_ORDER.pop(0)
        _ACTIVITY_VIEW_CACHE.pop(old_key, None)


def _write_json_atomic(p: Path, data: Dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, p)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Heartbeat / freshness
# ---------------------------------------------------------------------------

def read_heartbeat() -> Dict[str, Any]:
    raw = _read_json(_path("heartbeat.json"), default=None)
    if not raw or not isinstance(raw, dict):
        return {"present": False, "fresh": False, "age_sec": None}
    ts = _parse_iso(raw.get("timestamp_utc"))
    age = None
    fresh = False
    if ts is not None:
        age = (_now_utc() - ts).total_seconds()
        fresh = age <= HEARTBEAT_MAX_AGE_SEC and age >= -5  # allow tiny clock skew
    return {
        "present": True,
        "fresh": bool(fresh),
        "age_sec": (round(age, 1) if age is not None else None),
        "timestamp_utc": raw.get("timestamp_utc"),
        "ninja_version": raw.get("ninja_version"),
        "machine": raw.get("machine"),
        "exporter_version": raw.get("exporter_version"),
    }


# ---------------------------------------------------------------------------
# Strategies / positions / orders / executions
# ---------------------------------------------------------------------------

def _classify_account_mode(account_name: str, declared_mode: Optional[str] = None) -> str:
    """paper | demo | live | playback | unknown."""
    if declared_mode:
        m = str(declared_mode).strip().lower()
        if m in ("paper", "live", "playback", "demo"):
            return m
    name = (account_name or "").strip().lower()
    if not name:
        return "unknown"
    if "playback" in name:
        return "playback"
    if any(h in name for h in PAPER_ACCOUNT_HINTS):
        return "paper"
    if any(h in name for h in DEMO_ACCOUNT_HINTS):
        return "demo"
    if any(h in name for h in LIVE_ACCOUNT_HINTS):
        return "live"
    return "unknown"


def _is_system_account(name: str) -> bool:
    """Backtest/Sim101/Playback101 are NT pseudo-accounts, not user accounts."""
    return (name or "").strip().lower() in _SYSTEM_ACCOUNT_NAMES


def read_strategies_raw() -> List[Dict[str, Any]]:
    raw = _read_json(_path("strategies.json"), default={})
    if not raw or not isinstance(raw, dict):
        return []
    items = raw.get("strategies") or []
    if not isinstance(items, list):
        return []
    # Defensive: even if a stale bridge build still exports Finalized/Terminated
    # ghost rows (objects that NT detached from Strategies tab but kept alive),
    # hide them so the UI is 1:1 with NinjaTrader. Heuristic: ghost rows have
    # state in {finalized, terminated}, enabled=False AND data_series_count==0.
    # Legitimate stopped instances keep their data series, so we let them through.
    GHOSTS = {"finalized", "terminated"}
    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        st  = str(it.get("state") or "").lower()
        dsc = it.get("data_series_count")
        if st in GHOSTS and not it.get("enabled") and (dsc == 0):
            continue
        out.append(_normalize_runtime_strategy_row(it))
    return out


def _strategy_class_for_strategy_id(strategy_id: Any) -> Optional[str]:
    raw = canonical_strategy_id(strategy_id)
    if not raw:
        return None
    for cls, meta in STRATEGY_CLASS_METADATA.items():
        if raw == str(meta.get("strategy_id") or "").lower():
            return cls
        if raw == cls.lower():
            return cls
        for legacy_id in meta.get("legacy_strategy_ids") or []:
            if raw == canonical_strategy_id(legacy_id):
                return cls
    return None


def _placeholder_strategy_value(value: Any) -> bool:
    return str(value or "").strip().lower() in _UNMAPPED_STRATEGY_MARKERS


def _legacy_strategy_class_from_signal_value(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    for token in re.split(r"[\s\.:|/#\\]+", text):
        cls = _LEGACY_SIGNAL_CLASS_MAP.get(token.lower())
        if cls:
            return cls
    return None


def _strategy_class_from_signal_value(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    legacy = _legacy_strategy_class_from_signal_value(text)
    if legacy:
        return legacy
    if text in STRATEGY_CLASS_METADATA:
        return text
    # NinjaScript entry signals are exported as ClassName.Long/Short. Keep the
    # parser narrow so a plain "Short" from old logs stays unmapped.
    for token in re.split(r"[\s\.:|/#\\]+", text):
        if token in STRATEGY_CLASS_METADATA:
            return token
        by_id = _strategy_class_for_strategy_id(token)
        if by_id:
            return by_id
    return _strategy_class_for_strategy_id(text)


def _strategy_class_from_activity_row(row: Dict[str, Any]) -> Optional[str]:
    for key in ("strategy_class", "class_name"):
        cls = _strategy_class_from_signal_value(row.get(key))
        if cls:
            return cls
    by_id = _strategy_class_for_strategy_id(row.get("strategy_id"))
    if by_id:
        return by_id
    for key in ("from_entry_signal", "order_name", "signal_name", "entry_signal"):
        cls = _strategy_class_from_signal_value(row.get(key))
        if cls:
            return cls
    return None


def _instrument_root(value: Any) -> str:
    text = str(value or "").strip().upper().lstrip("/")
    if not text:
        return ""
    token = text.split()[0]
    m = re.match(r"[A-Z0-9]+", token)
    return m.group(0) if m else token


def _row_pt_date(row: Dict[str, Any]) -> str:
    ts = _parse_iso(row.get("timestamp_utc"))
    if ts is None:
        return ""
    return ops._to_pt(ts).date().isoformat()


def _legacy_strategy_attribution_for_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    acct = str(row.get("account_name") or "").strip()
    day = _row_pt_date(row)
    root = _instrument_root(row.get("instrument"))
    if not acct or not day or not root:
        return None
    oid = str(row.get("order_id") or "").strip()
    eid = str(row.get("execution_id") or "").strip()
    if not oid and not eid:
        return None
    for spec in _LEGACY_STRATEGY_ATTRIBUTIONS:
        if acct != spec["account_name"]:
            continue
        if day != spec["date_pt"]:
            continue
        if root != spec["instrument_root"]:
            continue
        if (oid and oid in spec["order_ids"]) or (eid and eid in spec["execution_ids"]):
            return spec
    return None


def _strategy_candidate_payload(classes: Tuple[str, ...]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for cls in classes:
        meta = STRATEGY_CLASS_METADATA.get(cls) or {}
        out.append({
            "strategy_class": cls,
            "strategy_id": str(meta.get("strategy_id") or cls.lower()),
            "strategy_name": str(meta.get("display_name") or cls),
        })
    return out


def _apply_legacy_strategy_attributions(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out_rows: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        spec = _legacy_strategy_attribution_for_row(row)
        if spec is None:
            out_rows.append(row)
            continue

        out = dict(row)
        classes = tuple(str(c) for c in spec.get("strategy_classes") or () if str(c))
        out["_strategy_attribution_confidence"] = str(spec.get("confidence") or "")
        out["_strategy_attribution_source"] = str(spec.get("source") or "")
        out["_strategy_attribution_candidates"] = _strategy_candidate_payload(classes)

        if len(classes) == 1:
            cls = classes[0]
            meta = STRATEGY_CLASS_METADATA.get(cls) or {}
            sid = str(meta.get("strategy_id") or cls.lower())
            name = str(meta.get("display_name") or cls)
            if _placeholder_strategy_value(out.get("strategy_class")):
                out["strategy_class"] = cls
            if _placeholder_strategy_value(out.get("strategy_id")):
                out["strategy_id"] = sid
            if _placeholder_strategy_value(out.get("strategy_name")):
                out["strategy_name"] = name
        out_rows.append(out)
    return out_rows


def _same_instrument_root(a: Any, b: Any) -> bool:
    ra = _instrument_root(a)
    rb = _instrument_root(b)
    return bool(ra and rb and ra == rb)


def _activity_matches_strategy_row(row: Dict[str, Any],
                                   strat: Dict[str, Any],
                                   class_name: Optional[str] = None) -> bool:
    if class_name and str(strat.get("strategy_class") or "") != class_name:
        return False
    acct = str(row.get("account_name") or "").strip()
    if acct and not _same_text(strat.get("account_name"), acct):
        return False
    inst = row.get("instrument")
    if inst and not (
        _same_instrument_root(inst, strat.get("instrument"))
        or _same_instrument_root(inst, strat.get("contract_month"))
    ):
        return False
    return True


def _single_matching_runtime_strategy(row: Dict[str, Any],
                                      strategies: List[Dict[str, Any]],
                                      class_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    candidates = [
        s for s in strategies
        if isinstance(s, dict) and _activity_matches_strategy_row(row, s, class_name)
    ]
    return candidates[0] if len(candidates) == 1 else None


def _enrich_runtime_activity_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach canonical strategy fields to order/execution rows when possible.

    New NinjaScript signals include the concrete class in order_name or
    from_entry_signal. Old rows with only "Long"/"Short" remain unmapped unless
    there is exactly one active runtime strategy for that account+instrument.
    """
    strategies = read_strategies_raw()
    enriched: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out = dict(row)
        legacy_signal_class = None
        legacy_signal_value = ""
        for key in ("from_entry_signal", "order_name", "signal_name", "entry_signal"):
            legacy_signal_class = _legacy_strategy_class_from_signal_value(out.get(key))
            if legacy_signal_class:
                legacy_signal_value = str(out.get(key) or "").strip()
                break
        cls = _strategy_class_from_activity_row(out)
        match = _single_matching_runtime_strategy(out, strategies, cls) if strategies else None
        if cls:
            meta = STRATEGY_CLASS_METADATA.get(cls) or {}
            sid = str(meta.get("strategy_id") or canonical_strategy_id(out.get("strategy_id")))
            name = str(meta.get("display_name") or out.get("strategy_name") or "")
            if sid and _placeholder_strategy_value(out.get("strategy_id")):
                out["strategy_id"] = sid
            out["strategy_class"] = cls
            if name and _placeholder_strategy_value(out.get("strategy_name")):
                out["strategy_name"] = name
            cell_id = str(meta.get("cell_id") or "")
            if cell_id and not str(out.get("cell_id") or "").strip():
                out["cell_id"] = cell_id
            if legacy_signal_class == cls:
                if str(out.get("attribution_status") or "").strip().lower() in {"", "unresolved"}:
                    out["attribution_status"] = "resolved_legacy_signal"
                out["_strategy_attribution_confidence"] = "exact"
                out["_strategy_attribution_source"] = f"legacy_signal:{legacy_signal_value}"
        elif _placeholder_strategy_value(out.get("strategy_id")) and _placeholder_strategy_value(out.get("strategy_class")):
            match = _single_matching_runtime_strategy(out, strategies, None) if strategies else None
            if match is not None:
                cls = str(match.get("strategy_class") or "").strip() or None

        if match is not None:
            for src, dst in (
                ("runtime_instance_id", "runtime_instance_id"),
                ("strategy_id", "strategy_id"),
                ("strategy_class", "strategy_class"),
                ("strategy_name", "strategy_name"),
            ):
                v = match.get(src)
                if v is not None and (_placeholder_strategy_value(out.get(dst)) or dst == "runtime_instance_id"):
                    out[dst] = v
        if cls and "strategy_class" not in out:
            out["strategy_class"] = cls
        enriched.append(out)
    return enriched


def read_positions() -> Dict[str, Any]:
    raw = _read_json(_path("positions.json"), default={})
    if not isinstance(raw, dict):
        return {}
    return raw


def read_accounts() -> List[Dict[str, Any]]:
    """Return the list of NinjaTrader accounts known to the bridge.

    Primary source is `data/runtime/accounts.json` written by the bridge
    (see RuntimeTelemetryExporter.WriteAccounts). Falls back to deriving
    a minimal account list from `positions.json` keys when accounts.json
    is missing — useful when running the bridge from older builds.

    Each account dict carries:
      - account_name        (str)
      - account_mode        ("paper" | "playback" | "live" | "unknown")
      - is_live             (bool)
      - cash_value          (float | None)
      - buying_power        (float | None)
      - net_liquidation     (float | None)
      - realized_pnl        (float | None)
      - unrealized_pnl      (float | None)
      - currency            (str | None)
      - connection_status   (str | None)
    """
    raw = _read_json(_path("accounts.json"), default=None)
    items: List[Dict[str, Any]] = []
    if isinstance(raw, dict):
        lst = raw.get("accounts")
        if isinstance(lst, list):
            for r in lst:
                if not isinstance(r, dict):
                    continue
                items.append(_normalize_account(r))
    if not items:
        # fallback: derive from positions.json keys
        pos = read_positions()
        for name in pos.keys():
            items.append(_normalize_account({"account_name": name}))
    return items


def _normalize_account(r: Dict[str, Any]) -> Dict[str, Any]:
    name = str(r.get("account_name") or "").strip()
    declared = r.get("account_mode")
    mode = _classify_account_mode(name, declared if isinstance(declared, str) else None)

    def _f(v: Any) -> Optional[float]:
        try:
            if v is None or v == "":
                return None
            return float(v)
        except (TypeError, ValueError):
            return None

    cash_v   = _f(r.get("cash_value"))
    bp_v     = _f(r.get("buying_power"))
    nl_v     = _f(r.get("net_liquidation"))
    real_v   = _f(r.get("realized_pnl"))
    unreal_v = _f(r.get("unrealized_pnl"))

    raw_notes = r.get("availability_notes")
    avail_notes: List[str] = []
    if isinstance(raw_notes, list):
        avail_notes = [str(x) for x in raw_notes if x is not None]

    missing: List[str] = []
    if cash_v is None: missing.append("cash_value")
    if bp_v   is None: missing.append("buying_power")
    if nl_v   is None: missing.append("net_liquidation")
    next_action: Optional[str] = None
    if missing:
        next_action = (
            "NinjaTrader не отдал поля: " + ", ".join(missing) +
            ". Это нормально для некоторых брокер-провайдеров — "
            "баланс будет недоступен."
        )

    is_system = _is_system_account(name)
    is_live = (mode == "live")
    is_selectable = (mode in ("paper", "playback", "demo")) and not is_system
    hidden_reason: Optional[str] = (
        "system/backtest/playback account" if is_system else
        ("live account is read-only" if is_live else None))

    return {
        "account_name":            name,
        "display_name":            name,  # never decorated with mode suffix
        "account_mode":            mode,
        "is_live":                 is_live,
        "is_system":               is_system,
        "is_selectable_for_online": is_selectable,
        "control_allowed":         is_selectable,
        "hidden_reason":           hidden_reason,
        "cash_value":              cash_v,
        "buying_power":            bp_v,
        "net_liquidation":         nl_v,
        "realized_pnl":            real_v,
        "unrealized_pnl":          unreal_v,
        "currency":               (r.get("currency") or None),
        "connection_status":       (r.get("connection_status") or None),
        "availability_notes":      avail_notes,
        "next_action":             next_action,
    }


def _norm_filter(value: Optional[str]) -> str:
    return str(value or "").strip()


def _same_text(a: Any, b: Any) -> bool:
    return str(a or "").strip().lower() == str(b or "").strip().lower()


def _row_matches_strategy(row: Dict[str, Any],
                          strategy_id: Optional[str] = None,
                          class_name: Optional[str] = None,
                          runtime_instance_id: Optional[str] = None) -> bool:
    """Match runtime telemetry rows without dropping account-level fills.

    Bridge builds before the runtime-instance export often write a signal name
    such as ``Short`` or an empty string into executions/orders. Those rows are
    intentionally not treated as a strategy match here; callers that need the
    account picture should filter by account_name instead of strategy_id.
    """
    iid = _norm_filter(runtime_instance_id)
    if iid and str(row.get("runtime_instance_id") or "") != iid:
        return False

    sid = _norm_filter(strategy_id)
    if sid:
        row_sid = str(row.get("strategy_id") or "").strip()
        row_cls = str(row.get("strategy_class") or "").strip()
        row_name = str(row.get("strategy_name") or "").strip()
        sid_l = sid.lower()
        canonical_sid = canonical_strategy_id(sid)
        if not (
            row_sid and (
                row_sid.lower() == sid_l
                or canonical_strategy_id(row_sid) == canonical_sid
            )
            or row_cls and row_cls.lower() == sid_l
            or row_name and row_name.lower() == sid_l
        ):
            return False

    cls = _norm_filter(class_name)
    if cls and not _same_text(row.get("strategy_class"), cls):
        return False

    return True


def _row_matches_account_filters(row: Dict[str, Any],
                                 account_name: Optional[str] = None,
                                 instrument: Optional[str] = None) -> bool:
    acct = _norm_filter(account_name)
    if acct and not _same_text(row.get("account_name"), acct):
        return False
    inst = _norm_filter(instrument)
    if inst and not _same_text(row.get("instrument"), inst):
        return False
    return True


def _dedupe_text(v: Any) -> str:
    return str(v or "").strip()


def _dedupe_lower(v: Any) -> str:
    return _dedupe_text(v).lower()


def _dedupe_num(v: Any) -> Any:
    if v is None or v == "":
        return ""
    try:
        n = float(v)
    except Exception:
        return str(v)
    if math.isfinite(n) and abs(n - round(n)) < 1e-9:
        return int(round(n))
    return round(n, 10)


def _runtime_row_richness(row: Dict[str, Any]) -> int:
    """Prefer the duplicate row that contains the most strategy/order context."""
    fields = (
        "runtime_instance_id", "strategy_class", "strategy_name",
        "strategy_id", "order_action", "position_action", "role",
        "exit_reason", "market_position", "order_state", "order_type",
    )
    return sum(1 for k in fields if _dedupe_text(row.get(k)))


def _merge_runtime_duplicates(rows: List[Dict[str, Any]],
                              dedupe_key: Any) -> Dict[str, Any]:
    ordered = sorted(
        [r for r in rows if isinstance(r, dict)],
        key=lambda r: (
            _dedupe_text(r.get("timestamp_utc")) or "9999-99-99T99:99:99Z",
            -_runtime_row_richness(r),
        ),
    )
    base = dict(ordered[0]) if ordered else {}
    for row in sorted(ordered, key=_runtime_row_richness, reverse=True):
        for k, v in row.items():
            if _dedupe_text(base.get(k)):
                continue
            if _dedupe_text(v):
                base[k] = v
    if len(ordered) > 1:
        timestamps = [_dedupe_text(r.get("timestamp_utc")) for r in ordered if _dedupe_text(r.get("timestamp_utc"))]
        base["_dedupe_key"] = "|".join(str(x) for x in dedupe_key)
        base["_duplicate_count"] = len(ordered)
        base["_duplicates_ignored"] = len(ordered) - 1
        if timestamps:
            base["_first_seen_utc"] = min(timestamps)
            base["_latest_seen_utc"] = max(timestamps)
    return base


def _execution_dedupe_key(row: Dict[str, Any], idx: int) -> Tuple[Any, ...]:
    """Stable identity for one physical fill.

    ``execution_id`` is the most reliable identity key: NinjaTrader reuses the
    same ExecutionId when replaying historical fills after a restart, regardless
    of whether a new Order object was created for that replay. We therefore
    prefer ``execution_id`` over ``order_id``.

    ``order_id`` is NOT suitable as the primary key because
    ``_enrich_executions_from_orders`` may attach different order_ids to the
    live write vs each historical replay write of the same physical fill,
    which defeats deduplication.

    Fall-back chain: execution_id → order_fill (when no eid) → field tuple.
    """
    acct = _dedupe_lower(row.get("account_name"))
    eid = _dedupe_text(row.get("execution_id"))
    if eid:
        return ("execution_id", acct, eid)
    oid = _dedupe_text(row.get("order_id"))
    if oid:
        return (
            "order_fill",
            acct,
            oid,
            _dedupe_lower(row.get("instrument")),
            _dedupe_text(row.get("timestamp_utc")),
            _dedupe_num(row.get("quantity")),
            _dedupe_num(row.get("price")),
        )
    return (
        "execution_fallback",
        acct,
        _dedupe_lower(row.get("instrument")),
        _dedupe_text(row.get("timestamp_utc")),
        _dedupe_lower(row.get("order_action")),
        _dedupe_lower(row.get("market_position")),
        _dedupe_lower(row.get("position_action")),
        _dedupe_num(row.get("quantity")),
        _dedupe_num(row.get("price")),
        _dedupe_lower(row.get("strategy_id")),
        _dedupe_lower(row.get("strategy_class")),
    )


def _execution_identity_keys(row: Dict[str, Any], idx: int) -> List[Tuple[Any, ...]]:
    """All stable identities that can refer to the same physical fill.

    NinjaTrader replay can preserve ``execution_id`` while changing order
    fields, or preserve the order/fill fingerprint while assigning a new
    ``execution_id``. Treat either identity as sufficient to merge duplicates.
    """
    acct = _dedupe_lower(row.get("account_name"))
    keys: List[Tuple[Any, ...]] = []
    eid = _dedupe_text(row.get("execution_id"))
    if eid:
        keys.append(("execution_id", acct, eid))
    oid = _dedupe_text(row.get("order_id"))
    if oid:
        keys.append((
            "order_fill",
            acct,
            oid,
            _dedupe_lower(row.get("instrument")),
            _dedupe_text(row.get("timestamp_utc")),
            _dedupe_num(row.get("quantity")),
            _dedupe_num(row.get("price")),
        ))
    if keys:
        return keys
    return [_execution_dedupe_key(row, idx)]


def dedupe_executions(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    valid_rows = [r for r in rows if isinstance(r, dict)]
    groups: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    order: List[Tuple[Any, ...]] = []
    for idx, row in enumerate(valid_rows):
        key = _execution_dedupe_key(row, idx)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    def order_fill_identity(row: Dict[str, Any]) -> Optional[Tuple[Any, ...]]:
        for key in _execution_identity_keys(row, 0):
            if key and key[0] == "order_fill":
                return key
        return None

    def weak_group(group_rows: List[Dict[str, Any]]) -> bool:
        return not any(
            _dedupe_text(r.get("order_action"))
            or _dedupe_text(r.get("strategy_id"))
            or _dedupe_text(r.get("strategy_class"))
            for r in group_rows
        )

    # Secondary merge: if a replay row got a fresh execution_id but kept the
    # same order/fill fingerprint, merge only when one side is weak/blank.
    # This avoids collapsing separate same-price fills whose enriched order_id
    # fields can be cross-attached during old NinjaTrader replay exports.
    fill_owner: Dict[Tuple[Any, ...], Tuple[Any, ...]] = {}
    remove_keys: set[Tuple[Any, ...]] = set()
    for key in list(order):
        if key in remove_keys:
            continue
        fill_keys = {order_fill_identity(r) for r in groups[key]}
        fill_keys.discard(None)
        for fkey in fill_keys:
            owner = fill_owner.get(fkey)
            if owner is None or owner in remove_keys:
                fill_owner[fkey] = key
                continue
            if weak_group(groups[key]) or weak_group(groups[owner]):
                groups[owner].extend(groups[key])
                remove_keys.add(key)
                break

    order = [key for key in order if key not in remove_keys]
    deduped = [_merge_runtime_duplicates(groups[key], key) for key in order]
    kept_groups = [groups[key] for key in order]
    duplicate_rows = sum(max(0, len(v) - 1) for v in kept_groups)
    duplicate_groups = sum(1 for v in kept_groups if len(v) > 1)
    return deduped, {
        "raw_count": len(valid_rows),
        "deduped_count": len(deduped),
        "duplicate_count": duplicate_rows,
        "duplicate_groups": duplicate_groups,
        "mode": "order_fill+execution_id+fallback",
    }


def _order_dedupe_key(row: Dict[str, Any], idx: int) -> Tuple[Any, ...]:
    oid = _dedupe_text(row.get("order_id"))
    acct = _dedupe_lower(row.get("account_name"))
    if oid:
        return (
            "order_update", acct, oid,
            _dedupe_lower(row.get("order_state")),
            _dedupe_num(row.get("quantity")),
            _dedupe_num(row.get("filled")),
            _dedupe_num(row.get("limit_price")),
            _dedupe_num(row.get("stop_price")),
            _dedupe_num(row.get("avg_fill")),
        )
    return (
        "order_fallback", acct,
        _dedupe_lower(row.get("instrument")),
        _dedupe_text(row.get("timestamp_utc")),
        _dedupe_lower(row.get("order_state")),
        _dedupe_lower(row.get("order_action")),
        _dedupe_lower(row.get("order_type")),
        _dedupe_num(row.get("quantity")),
        _dedupe_num(row.get("filled")),
        _dedupe_num(row.get("limit_price")),
        _dedupe_num(row.get("stop_price")),
        _dedupe_num(row.get("avg_fill")),
        idx,
    )


def dedupe_order_updates(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    groups: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    order: List[Tuple[Any, ...]] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        key = _order_dedupe_key(row, idx)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    deduped = [_merge_runtime_duplicates(groups[key], key) for key in order]
    duplicate_rows = sum(max(0, len(v) - 1) for v in groups.values())
    duplicate_groups = sum(1 for v in groups.values() if len(v) > 1)
    return deduped, {
        "raw_count": len([r for r in rows if isinstance(r, dict)]),
        "deduped_count": len(deduped),
        "duplicate_count": duplicate_rows,
        "duplicate_groups": duplicate_groups,
        "mode": "order_update",
    }


def read_orders(strategy_id: Optional[str] = None,
                limit: int = 500,
                account_name: Optional[str] = None,
                runtime_instance_id: Optional[str] = None,
                class_name: Optional[str] = None,
                instrument: Optional[str] = None,
                dedupe: bool = True) -> List[Dict[str, Any]]:
    rows, _meta = read_orders_with_meta(
        strategy_id, limit,
        account_name=account_name,
        runtime_instance_id=runtime_instance_id,
        class_name=class_name,
        instrument=instrument,
        dedupe=dedupe,
    )
    return rows


def read_orders_with_meta(strategy_id: Optional[str] = None,
                          limit: int = 500,
                          account_name: Optional[str] = None,
                          runtime_instance_id: Optional[str] = None,
                          class_name: Optional[str] = None,
                          instrument: Optional[str] = None,
                          dedupe: bool = True) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cap = max(RUNTIME_ORDER_JSONL_MAX_LINES, max(int(limit or 500), 1) * 50)
    cache_key = (
        "orders",
        strategy_id or "",
        account_name or "",
        runtime_instance_id or "",
        class_name or "",
        instrument or "",
        int(limit or 500),
        bool(dedupe),
        cap,
        _jsonl_file_sig("orders.jsonl"),
        _jsonl_file_sig("strategies.json"),
    )
    cached = _activity_cache_get(cache_key)
    if cached is not None:
        return cached
    rows = _read_jsonl(_path("orders.jsonl"), max_lines=cap)
    rows = _enrich_runtime_activity_rows(rows)
    rows = _apply_legacy_strategy_attributions(rows)
    rows = [
        r for r in rows
        if isinstance(r, dict)
        and _row_matches_account_filters(r, account_name, instrument)
        and _row_matches_strategy(r, strategy_id, class_name, runtime_instance_id)
    ]
    if dedupe:
        rows, meta = dedupe_order_updates(rows)
    else:
        meta = {
            "raw_count": len(rows),
            "deduped_count": len(rows),
            "duplicate_count": 0,
            "duplicate_groups": 0,
            "mode": "off",
        }
    out = rows[-limit:]
    _activity_cache_put(cache_key, out, meta)
    return _clone_activity_rows(out), dict(meta)


def read_executions(strategy_id: Optional[str] = None,
                    limit: int = 1000,
                    account_name: Optional[str] = None,
                    runtime_instance_id: Optional[str] = None,
                    class_name: Optional[str] = None,
                    instrument: Optional[str] = None,
                    dedupe: bool = True) -> List[Dict[str, Any]]:
    rows, _meta = read_executions_with_meta(
        strategy_id, limit,
        account_name=account_name,
        runtime_instance_id=runtime_instance_id,
        class_name=class_name,
        instrument=instrument,
        dedupe=dedupe,
    )
    return rows


def read_executions_with_meta(strategy_id: Optional[str] = None,
                              limit: int = 1000,
                              account_name: Optional[str] = None,
                              runtime_instance_id: Optional[str] = None,
                              class_name: Optional[str] = None,
                              instrument: Optional[str] = None,
                              dedupe: bool = True) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cap = max(RUNTIME_EXEC_JSONL_MAX_LINES, max(int(limit or 1000), 1) * 50)
    cache_key = (
        "executions",
        strategy_id or "",
        account_name or "",
        runtime_instance_id or "",
        class_name or "",
        instrument or "",
        int(limit or 1000),
        bool(dedupe),
        cap,
        _jsonl_file_sig("executions.jsonl"),
        _jsonl_file_sig("orders.jsonl"),
        _jsonl_file_sig("strategies.json"),
    )
    cached = _activity_cache_get(cache_key)
    if cached is not None:
        return cached
    rows = _read_jsonl(_path("executions.jsonl"), max_lines=cap)
    rows = _enrich_runtime_activity_rows(rows)
    rows = [
        r for r in rows
        if isinstance(r, dict)
        and _row_matches_account_filters(r, account_name, instrument)
    ]
    rows = _enrich_executions_from_orders(rows)
    rows = _apply_legacy_strategy_attributions(rows)
    rows = [
        r for r in rows
        if isinstance(r, dict)
        and _row_matches_strategy(r, strategy_id, class_name, runtime_instance_id)
    ]
    if dedupe:
        rows, meta = dedupe_executions(rows)
    else:
        meta = {
            "raw_count": len(rows),
            "deduped_count": len(rows),
            "duplicate_count": 0,
            "duplicate_groups": 0,
            "mode": "off",
        }
    out = rows[-limit:]
    _activity_cache_put(cache_key, out, meta)
    return _clone_activity_rows(out), dict(meta)


def read_errors(limit: int = 200) -> List[Dict[str, Any]]:
    return _read_jsonl(_path("errors.jsonl"))[-limit:]


# ---------------------------------------------------------------------------
# Strategy display preferences
# ---------------------------------------------------------------------------

def _strategy_display_key(class_name: str) -> str:
    return str(class_name or "").strip()


def read_strategy_display_prefs() -> Dict[str, Any]:
    raw = _read_json(_path(STRATEGY_DISPLAY_PREFS_FILE), default={})
    hidden: set[str] = set()
    updated_at = None
    if isinstance(raw, dict):
        updated_at = raw.get("updated_at_utc")
        items = raw.get("hidden_classes")
        if isinstance(items, list):
            hidden.update(_strategy_display_key(str(x)) for x in items if _strategy_display_key(str(x)))
        legacy = raw.get("classes")
        if isinstance(legacy, dict):
            for cls, cfg in legacy.items():
                if isinstance(cfg, dict) and cfg.get("hidden"):
                    key = _strategy_display_key(str(cls))
                    if key:
                        hidden.add(key)
    return {
        "hidden_classes": sorted(hidden),
        "updated_at_utc": updated_at,
    }


def is_strategy_display_hidden(class_name: str) -> bool:
    key = _strategy_display_key(class_name)
    if not key:
        return False
    return key in set(read_strategy_display_prefs().get("hidden_classes") or [])


def set_strategy_display_hidden(class_name: str, hidden: bool) -> Dict[str, Any]:
    key = _strategy_display_key(class_name)
    if not key:
        raise ops.OpsError("class_name is required", 400)
    prefs = read_strategy_display_prefs()
    hidden_classes = set(prefs.get("hidden_classes") or [])
    if hidden:
        hidden_classes.add(key)
    else:
        hidden_classes.discard(key)
    out = {
        "hidden_classes": sorted(hidden_classes),
        "updated_at_utc": _now_utc().isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    _write_json_atomic(_path(STRATEGY_DISPLAY_PREFS_FILE), out)
    return {"ok": True, "class_name": key, "hidden": bool(hidden), "prefs": out}


# ---------------------------------------------------------------------------
# Runtime strategy history
# ---------------------------------------------------------------------------

def _history_row_matches(row: Dict[str, Any],
                         strategy_id: Optional[str] = None,
                         runtime_instance_id: Optional[str] = None,
                         class_name: Optional[str] = None) -> bool:
    if runtime_instance_id and str(row.get("runtime_instance_id") or "") != runtime_instance_id:
        return False
    if strategy_id and str(row.get("strategy_id") or "").lower() != strategy_id.lower():
        return False
    if class_name and str(row.get("strategy_class") or "").lower() != class_name.lower():
        return False
    return True


def read_strategy_history_events(limit: int = 500,
                                 strategy_id: Optional[str] = None,
                                 runtime_instance_id: Optional[str] = None,
                                 class_name: Optional[str] = None) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 500), 5000))
    rows = _read_jsonl(_path(STRATEGY_HISTORY_FILE), max_lines=max(5000, limit * 5))
    rows = [
        r for r in rows
        if isinstance(r, dict)
        and _history_row_matches(r, strategy_id, runtime_instance_id, class_name)
    ]
    return rows[-limit:]


def _duration_sec(start_iso: Optional[str], end_iso: Optional[str]) -> Optional[int]:
    start = _parse_iso(start_iso)
    end = _parse_iso(end_iso)
    if not start or not end:
        return None
    return max(0, int(round((end - start).total_seconds())))


def _history_session_seed(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "runtime_instance_id": str(row.get("runtime_instance_id") or ""),
        "strategy_id":        row.get("strategy_id") or "",
        "strategy_class":     row.get("strategy_class") or "",
        "strategy_name":      row.get("strategy_name") or "",
        "account_name":       row.get("account_name") or "",
        "account_mode":       row.get("account_mode") or "",
        "instrument":         row.get("instrument") or "",
        "timeframe":          row.get("timeframe") or "",
        "started_at_utc":     row.get("timestamp_utc"),
        "ended_at_utc":       None,
        "duration_sec":       None,
        "is_open":            True,
        "start_event":        row.get("event") or "started",
        "end_event":          None,
        "end_reason":         None,
        "last_event_utc":     row.get("timestamp_utc"),
        # Phase 24 — История tab: surface trades / pnl / params.
        "parameters":         row.get("params") or {},
        "trades_count":       row.get("session_trades_count"),
        "gross_pnl":          row.get("realized_pnl"),
    }


def _close_history_session(sess: Dict[str, Any], row: Dict[str, Any]) -> None:
    end_ts = row.get("timestamp_utc") or sess.get("last_event_utc") or sess.get("started_at_utc")
    sess["ended_at_utc"] = end_ts
    sess["duration_sec"] = _duration_sec(sess.get("started_at_utc"), end_ts)
    sess["is_open"] = False
    sess["end_event"] = row.get("event") or "stopped"
    sess["end_reason"] = row.get("reason") or None
    sess["last_event_utc"] = end_ts
    # Carry the most recent observable counters from the closing event.
    if row.get("session_trades_count") is not None:
        sess["trades_count"] = row.get("session_trades_count")
    if row.get("realized_pnl") is not None:
        sess["gross_pnl"] = row.get("realized_pnl")
    if row.get("params"):
        sess["parameters"] = row.get("params")


def _current_enabled_runtime_keys() -> set[str]:
    hb = read_heartbeat()
    if not (hb.get("present") and hb.get("fresh")):
        return set()
    keys: set[str] = set()
    for idx, row in enumerate(read_strategies_raw()):
        if not isinstance(row, dict) or not row.get("enabled"):
            continue
        keys.add(str(row.get("runtime_instance_id") or _make_runtime_instance_id(row, idx)))
    return keys


def _build_strategy_sessions(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    open_by_key: Dict[str, Dict[str, Any]] = {}
    sessions: List[Dict[str, Any]] = []
    current_enabled = _current_enabled_runtime_keys()
    now_iso = _now_utc().isoformat(timespec="seconds").replace("+00:00", "Z")

    for row in events:
        key = str(row.get("runtime_instance_id") or "")
        if not key:
            continue
        event = str(row.get("event") or "").lower()
        enabled = bool(row.get("enabled"))

        if event in ("observed_start", "started"):
            if enabled and key not in open_by_key:
                open_by_key[key] = _history_session_seed(row)
            elif key in open_by_key:
                open_by_key[key]["last_event_utc"] = row.get("timestamp_utc")
            continue

        if event == "state_changed":
            if enabled and key not in open_by_key:
                open_by_key[key] = _history_session_seed(row)
            elif not enabled and key in open_by_key:
                sess = open_by_key.pop(key)
                _close_history_session(sess, row)
                sessions.append(sess)
            elif key in open_by_key:
                open_by_key[key]["last_event_utc"] = row.get("timestamp_utc")
            continue

        if event in ("stopped", "disappeared", "exporter_stop"):
            if key in open_by_key:
                sess = open_by_key.pop(key)
                _close_history_session(sess, row)
                sessions.append(sess)
            continue

        if event == "observed" and key in open_by_key:
            open_by_key[key]["last_event_utc"] = row.get("timestamp_utc")

    # Phase 24 — for sessions still open, fold in live counters/params from
    # the current strategies.jsonl snapshot so the History tab can show
    # trades / pnl / params even before a stop event lands.
    snapshot_by_key: Dict[str, Dict[str, Any]] = {}
    for idx, srow in enumerate(read_strategies_raw()):
        if not isinstance(srow, dict):
            continue
        rk = str(srow.get("runtime_instance_id") or _make_runtime_instance_id(srow, idx))
        snapshot_by_key[rk] = srow

    for key, sess in list(open_by_key.items()):
        snap = snapshot_by_key.get(key) or {}
        if snap.get("params"):
            sess["parameters"] = snap.get("params")
        if snap.get("session_trades_count") is not None:
            sess["trades_count"] = snap.get("session_trades_count")
        if snap.get("realized_pnl") is not None:
            sess["gross_pnl"] = snap.get("realized_pnl")
        if key in current_enabled:
            sess["is_open"] = True
            sess["ended_at_utc"] = None
            sess["duration_sec"] = _duration_sec(sess.get("started_at_utc"), now_iso)
            sess["end_event"] = None
            sess["end_reason"] = "still_running"
        else:
            end_ts = sess.get("last_event_utc") or sess.get("started_at_utc")
            sess["is_open"] = False
            sess["ended_at_utc"] = end_ts
            sess["duration_sec"] = _duration_sec(sess.get("started_at_utc"), end_ts)
            sess["end_event"] = "missing_stop"
            sess["end_reason"] = "not in current fresh runtime snapshot"
        sessions.append(sess)

    sessions.sort(key=lambda s: str(s.get("started_at_utc") or ""))
    return sessions


def _current_snapshot_sessions(strategy_id: Optional[str],
                               runtime_instance_id: Optional[str],
                               class_name: Optional[str]) -> List[Dict[str, Any]]:
    hb = read_heartbeat()
    if not (hb.get("present") and hb.get("fresh")):
        return []
    out: List[Dict[str, Any]] = []
    now_iso = _now_utc().isoformat(timespec="seconds").replace("+00:00", "Z")
    for idx, row in enumerate(read_strategies_raw()):
        if not isinstance(row, dict) or not row.get("enabled"):
            continue
        r = dict(row)
        r["runtime_instance_id"] = str(
            r.get("runtime_instance_id") or _make_runtime_instance_id(r, idx))
        if not _history_row_matches(r, strategy_id, runtime_instance_id, class_name):
            continue
        start = r.get("timestamp_utc") or hb.get("timestamp_utc") or now_iso
        out.append({
            "runtime_instance_id": r.get("runtime_instance_id"),
            "strategy_id":        r.get("strategy_id") or "",
            "strategy_class":     r.get("strategy_class") or "",
            "strategy_name":      r.get("strategy_name") or "",
            "account_name":       r.get("account_name") or "",
            "account_mode":       r.get("account_mode") or "",
            "instrument":         r.get("instrument") or "",
            "timeframe":          r.get("timeframe") or "",
            "started_at_utc":     start,
            "ended_at_utc":       None,
            "duration_sec":       _duration_sec(start, now_iso),
            "is_open":            True,
            "start_event":        "current_snapshot",
            "end_event":          None,
            "end_reason":         "history file is not available yet",
            "last_event_utc":     r.get("timestamp_utc"),
            "source":             "current_snapshot_only",
            "parameters":         r.get("params") or {},
            "trades_count":       r.get("session_trades_count"),
            "gross_pnl":          r.get("realized_pnl"),
        })
    return out


def read_strategy_history(limit_events: int = 500,
                          limit_sessions: int = 200,
                          strategy_id: Optional[str] = None,
                          runtime_instance_id: Optional[str] = None,
                          class_name: Optional[str] = None) -> Dict[str, Any]:
    limit_events = max(1, min(int(limit_events or 500), 5000))
    limit_sessions = max(1, min(int(limit_sessions or 200), 1000))
    events = read_strategy_history_events(
        limit=max(limit_events, 5000),
        strategy_id=strategy_id,
        runtime_instance_id=runtime_instance_id,
        class_name=class_name,
    )
    sessions = _build_strategy_sessions(events)
    warnings: List[str] = []
    if not events:
        sessions = _current_snapshot_sessions(strategy_id, runtime_instance_id, class_name)
        if sessions:
            warnings.append(
                "strategy_history.jsonl is not available yet; showing current snapshot only")
    total_sec = sum(int(s.get("duration_sec") or 0) for s in sessions)
    active = [s for s in sessions if s.get("is_open")]
    return {
        "events": events[-limit_events:],
        "sessions": sessions[-limit_sessions:],
        "summary": {
            "sessions": len(sessions),
            "active_sessions": len(active),
            "total_duration_sec": total_sec,
        },
        "filters": {
            "strategy_id": strategy_id,
            "runtime_instance_id": runtime_instance_id,
            "class_name": class_name,
        },
        "warnings": warnings,
        "source": "strategy_history_jsonl" if events else "current_snapshot",
    }


def get_strategy_sessions(limit: int = 200) -> list:
    """Return closed+open strategy sessions for the History tab."""
    events = read_strategy_history_events(limit=limit * 10)
    sessions = _build_strategy_sessions(events)
    sessions.sort(key=lambda s: s.get("started_at_utc") or "", reverse=True)
    return sessions[:limit]


# ---------------------------------------------------------------------------
# Param validation
# ---------------------------------------------------------------------------

def _eq_loose(expected: Any, actual: Any) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        # accept "true"/"false" strings, 0/1
        def _b(x: Any) -> Optional[bool]:
            if isinstance(x, bool): return x
            if isinstance(x, (int, float)): return bool(x)
            if isinstance(x, str):
                xs = x.strip().lower()
                if xs in ("true", "1", "yes"): return True
                if xs in ("false", "0", "no"): return False
            return None
        be, ba = _b(expected), _b(actual)
        return be is not None and ba is not None and be == ba
    try:
        fe, fa = float(expected), float(actual)
        return math.isclose(fe, fa, rel_tol=1e-6, abs_tol=1e-6)
    except Exception:
        return str(expected).strip() == str(actual).strip()


def validate_params(strategy_id: str,
                    runtime_params: Dict[str, Any]) -> Dict[str, Any]:
    """Return {ok, mismatches:[{key,expected,actual}], checked:int}."""
    profile_hit = _profile_registry_hit_for_strategy(strategy_id)
    if profile_hit and profile_hit.get("locked_params"):
        expected = profile_hit.get("locked_params") or {}
    elif canonical_strategy_id(strategy_id) == "vwap_short_mnq_5m_v1":
        expected = B1_LOCKED_PARAMS_CHECK
    else:
        s = ops.get_strategy(strategy_id) or {}
        expected = s.get("locked_params") or {}
    return _validate_expected_params(expected, runtime_params)


def _validate_expected_params(expected: Dict[str, Any],
                              runtime_params: Dict[str, Any],
                              *,
                              source: str = "locked_profile") -> Dict[str, Any]:
    """Return {ok, mismatches:[{key,expected,actual}], checked:int}."""
    mismatches: List[Dict[str, Any]] = []
    rp = runtime_params or {}
    # Make case-insensitive lookup of runtime_params
    rp_lower = {str(k).lower(): v for k, v in rp.items()}
    checked = 0
    for k, v_exp in _iter_locked_params_for_validation(expected, rp):
        checked += 1
        v_act = rp.get(k, rp_lower.get(str(k).lower(), None))
        if v_act is None:
            mismatches.append({
                "key": k, "expected": v_exp, "actual": None,
                "expected_display": _format_param_mismatch_value(k, v_exp),
                "actual_display": "—",
                "reason": "missing", "source": source,
            })
            continue
        if not _eq_loose(v_exp, v_act):
            mismatches.append({
                "key": k, "expected": v_exp, "actual": v_act,
                "expected_display": _format_param_mismatch_value(k, v_exp),
                "actual_display": _format_param_mismatch_value(k, v_act),
                "reason": "value_mismatch", "source": source,
            })
    recommendation = _params_mismatch_recommendation(mismatches)
    return {
        "ok": len(mismatches) == 0,
        "mismatches": mismatches,
        "checked": checked,
        "source": source,
        "recommendation": recommendation,
        "mismatch_keys": [m["key"] for m in mismatches],
    }


# ---------------------------------------------------------------------------
# Today metrics from executions.jsonl
# ---------------------------------------------------------------------------

def _exec_to_pt_date(ts_utc_str: Optional[str]) -> Optional[str]:
    dt = _parse_iso(ts_utc_str)
    if dt is None:
        return None
    pt = ops._to_pt(dt)
    return pt.date().isoformat()


def _abs_qty(e: Dict[str, Any]) -> float:
    try:
        return abs(float(e.get("quantity") or 0))
    except Exception:
        return 0.0


def _exec_pnl(e: Dict[str, Any]) -> Optional[float]:
    """Realized PnL of an exit execution. Entries usually have pnl=0/None.
    We only sum exit fills."""
    p = e.get("realized_pnl")
    if p is None:
        p = e.get("pnl_currency")
    if p is None:
        return None
    try:
        return float(p)
    except Exception:
        return None


def _exec_side(e: Dict[str, Any]) -> int:
    action = str(e.get("order_action") or e.get("action") or "").lower()
    if "buy" in action:
        return 1
    if "sell" in action:
        return -1
    mp = str(e.get("market_position") or "").lower()
    if mp == "long":
        return 1
    if mp == "short":
        return -1
    return 0


def _exec_price(e: Dict[str, Any]) -> Optional[float]:
    try:
        price = float(e.get("price"))
    except Exception:
        return None
    return price if math.isfinite(price) else None


def _instrument_multiplier(instrument: Any) -> float:
    return _FUTURES_MULTIPLIER.get(_instrument_root(instrument), 1.0)


def _strategy_lot_identity(e: Dict[str, Any]) -> str:
    for key in ("runtime_instance_id", "strategy_class", "strategy_id"):
        value = str(e.get(key) or "").strip()
        if value and not _placeholder_strategy_value(value):
            return value.lower()
    return "__unmapped__"


def _fifo_closed_trades(execs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    lots_by_key: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    closed: List[Dict[str, Any]] = []
    ordered = sorted(execs, key=lambda e: str(e.get("timestamp_utc") or ""))
    for e in ordered:
        qty = _abs_qty(e)
        price = _exec_price(e)
        side = _exec_side(e)
        if qty <= 0.0 or price is None or side == 0:
            continue
        signed_qty = side * qty
        key = (
            str(e.get("account_name") or "").strip().lower(),
            _instrument_root(e.get("instrument")),
            _strategy_lot_identity(e),
        )
        lots = lots_by_key.setdefault(key, [])
        row_pnl = 0.0
        while abs(signed_qty) > 1e-9 and lots and math.copysign(1.0, lots[0]["qty"]) != math.copysign(1.0, signed_qty):
            lot = lots[0]
            close_qty = min(abs(signed_qty), abs(float(lot["qty"])))
            mult = _instrument_multiplier(e.get("instrument"))
            pnl = (
                (price - float(lot["price"])) * close_qty * mult
                if float(lot["qty"]) > 0
                else (float(lot["price"]) - price) * close_qty * mult
            )
            row_pnl += pnl
            closed.append({
                "timestamp_utc": e.get("timestamp_utc"),
                "account_name": e.get("account_name"),
                "instrument": e.get("instrument"),
                "quantity": close_qty,
                "entry_price": lot["price"],
                "exit_price": price,
                "pnl": pnl,
                "role": e.get("role") or e.get("position_action") or "exit",
                "exit_reason": e.get("exit_reason") or "",
                "slippage_ticks": e.get("slippage_ticks"),
            })
            lot_sign = 1.0 if float(lot["qty"]) > 0 else -1.0
            signed_sign = 1.0 if signed_qty > 0 else -1.0
            lot["qty"] = float(lot["qty"]) - lot_sign * close_qty
            signed_qty = signed_qty - signed_sign * close_qty
            if abs(float(lot["qty"])) <= 1e-9:
                lots.pop(0)
        if abs(row_pnl) > 1e-9:
            e["_estimated_pnl"] = row_pnl
        if abs(signed_qty) > 1e-9:
            lots.append({"qty": signed_qty, "price": price})
    return closed


def _order_fill_price(row: Dict[str, Any]) -> Optional[float]:
    for key in ("avg_fill", "limit_price", "stop_price"):
        try:
            value = float(row.get(key))
        except Exception:
            continue
        if math.isfinite(value) and value > 0:
            return value
    return None


def _order_side(row: Dict[str, Any]) -> int:
    action = str(row.get("order_action") or "").lower()
    if "buy" in action:
        return 1
    if "sell" in action:
        return -1
    return 0


def _fill_match_key(row: Dict[str, Any], price: float, side: int) -> Tuple[Any, ...]:
    return (
        str(row.get("account_name") or "").strip().lower(),
        _instrument_root(row.get("instrument")),
        round(float(price), 6),
        int(round(_abs_qty(row))),
        int(side),
    )


def _enrich_executions_from_orders(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Backfill execution context from filled order events.

    Some NinjaTrader account-level execution callbacks omit Order fields while
    the OrderUpdate stream still contains action/type/limit/stop/fill details.
    Matching by account + instrument + fill price + qty + side makes the old
    rows readable without inventing strategy attribution.
    """
    if not rows:
        return rows
    if not any(
        isinstance(r, dict) and (
            not _dedupe_text(r.get("order_action"))
            or not _dedupe_text(r.get("order_type"))
            or not _dedupe_text(r.get("order_id"))
        )
        for r in rows
    ):
        return rows

    raw_orders = _read_jsonl(_path("orders.jsonl"), max_lines=RUNTIME_ORDER_JSONL_MAX_LINES)
    if not raw_orders:
        return rows
    order_rows = _enrich_runtime_activity_rows(raw_orders)
    by_id: Dict[str, Dict[str, Any]] = {}
    by_fill: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for order in order_rows:
        if not isinstance(order, dict):
            continue
        state = str(order.get("order_state") or "").strip().lower()
        if state not in ("filled", "partfilled"):
            continue
        oid = _dedupe_text(order.get("order_id"))
        if oid:
            by_id[oid] = order
        price = _order_fill_price(order)
        side = _order_side(order)
        if price is None or side == 0:
            continue
        key = _fill_match_key(order, price, side)
        by_fill.setdefault(key, []).append(order)

    order_fields = (
        "order_id", "order_action", "order_type", "order_state",
        "order_name", "from_entry_signal",
        "limit_price", "stop_price", "avg_fill",
        "strategy_id", "strategy_class", "strategy_name", "runtime_instance_id",
    )
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        enriched = dict(row)
        match = None
        oid = _dedupe_text(enriched.get("order_id"))
        if oid:
            match = by_id.get(oid)
        if match is None:
            price = _exec_price(enriched)
            side = _exec_side(enriched)
            if price is not None and side != 0:
                bucket = by_fill.get(_fill_match_key(enriched, price, side)) or []
                if bucket:
                    match = bucket.pop(0)
        if match is not None:
            for key in order_fields:
                value = match.get(key)
                if not _dedupe_text(value):
                    continue
                if key in ("strategy_id", "strategy_class", "strategy_name", "runtime_instance_id"):
                    if _placeholder_strategy_value(enriched.get(key)):
                        enriched[key] = value
                elif not _dedupe_text(enriched.get(key)):
                    enriched[key] = value
        out.append(enriched)
    return out


def _exec_is_exit(e: Dict[str, Any]) -> bool:
    role = str(e.get("role") or e.get("position_action") or "").lower()
    if role in ("exit", "close", "stop", "target", "manual"):
        return True
    pnl = _exec_pnl(e)
    return pnl is not None and pnl != 0.0


def compute_runtime_today_metrics(strategy_id: str,
                                  on_date_pt: Optional[str] = None
                                  ) -> Dict[str, Any]:
    execs = read_executions(strategy_id, limit=10000)
    if on_date_pt is None:
        on_date_pt = ops._to_pt(_now_utc()).date().isoformat()
    today_execs = [e for e in execs if _exec_to_pt_date(e.get("timestamp_utc")) == on_date_pt]

    closed_trades = [
        t for t in _fifo_closed_trades(execs)
        if _exec_to_pt_date(t.get("timestamp_utc")) == on_date_pt
    ]
    exits = [e for e in today_execs if _exec_is_exit(e)] if not closed_trades else []
    gross_pnl = 0.0
    total_qty = 0.0
    wins = losses = 0
    slips_ticks: List[float] = []
    stop_hits = target_hits = 0

    metric_rows = closed_trades or exits
    for e in metric_rows:
        q = _abs_qty(e)
        total_qty += q
        p = (float(e.get("pnl") or 0.0) if closed_trades else (_exec_pnl(e) or 0.0))
        gross_pnl += p
        if p > 0: wins += 1
        elif p < 0: losses += 1
        st = e.get("slippage_ticks")
        if st is not None:
            try: slips_ticks.append(float(st))
            except Exception: pass
        reason = str(e.get("exit_reason") or e.get("role") or "").lower()
        if "stop" in reason: stop_hits += 1
        elif "target" in reason or "profit" in reason: target_hits += 1

    rtc = ops.ROUND_TURN_COMMISSION
    commission_est = rtc * total_qty
    adj_pnl = gross_pnl - commission_est
    median_slip = (statistics.median(slips_ticks) if slips_ticks else None)
    max_slip = (max(slips_ticks) if slips_ticks else None)

    return {
        "date_pt":              on_date_pt,
        "trades_count":         len(metric_rows),
        "total_qty":            int(round(total_qty)),
        "gross_pnl":            round(gross_pnl, 2),
        "commission_estimated": round(commission_est, 2),
        "adjusted_pnl":         round(adj_pnl, 2),
        "daily_win_count":      wins,
        "daily_loss_count":     losses,
        "median_slippage_ticks": (round(median_slip, 3) if median_slip is not None else None),
        "max_slippage_ticks":    (round(max_slip, 3) if max_slip is not None else None),
        "stop_hit_count":       stop_hits,
        "target_hit_count":     target_hits,
    }


# ---------------------------------------------------------------------------
# Merged view per strategy
# ---------------------------------------------------------------------------

def _stale_reason(hb: Dict[str, Any]) -> Optional[str]:
    if not hb.get("present"):
        return "no heartbeat.json"
    if not hb.get("fresh"):
        age = hb.get("age_sec")
        return f"heartbeat stale (age {age}s > {HEARTBEAT_MAX_AGE_SEC}s)"
    return None


def _find_runtime_for(strategy_id: str,
                      registry_strategy: Dict[str, Any],
                      raw_strategies: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    sid_l = strategy_id.lower()
    canonical_sid = canonical_strategy_id(strategy_id)
    cls = (registry_strategy.get("class_name") or "").lower()
    aliases = {str(x).lower() for x in registry_strategy.get("legacy_strategy_ids") or []}
    for r in raw_strategies:
        rsid = str(r.get("strategy_id") or "").lower()
        rcls = str(r.get("strategy_class") or "").lower()
        if rsid and (rsid == sid_l or canonical_strategy_id(rsid) == canonical_sid or rsid in aliases):
            return r
        if rcls and rcls == cls:
            return r
    return None


def merge_strategy_view(strategy_id: str,
                        selected_account: Optional[str] = None,
                        selected_instrument: Optional[str] = None,
                        selected_timeframe: Optional[str] = None) -> Dict[str, Any]:
    """Read-only merged view: registry + paper state + bridge runtime row.

    When the optional ``selected_*`` kwargs are provided (typically populated
    from the Trading Online right-panel selectors), a ``selection_diff``
    block is appended comparing UI choice vs the runtime strategy reported
    by the bridge. Paper/playback only — never gates live trading.
    """
    s = ops.get_strategy(strategy_id)
    if not s:
        return {"error": "strategy not found", "strategy_id": strategy_id}
    canonical_strategy_id = str(s.get("strategy_id") or strategy_id)
    states = ops.load_states()
    paper_state = (states.get(canonical_strategy_id) or {}).get("current_state", s["status"])
    hb = read_heartbeat()
    raw_list = read_strategies_raw()
    rt = _find_runtime_for(strategy_id, s, raw_list)

    warnings: List[str] = []
    errors: List[str] = []
    stale = _stale_reason(hb)
    if stale:
        warnings.append(stale)

    runtime_detected = bool(rt) and bool(hb.get("present")) and bool(hb.get("fresh"))
    runtime_enabled  = bool(rt and rt.get("enabled")) and runtime_detected
    account_name     = (rt or {}).get("account_name") or ""
    account_mode_raw = (rt or {}).get("account_mode")
    account_mode     = _classify_account_mode(account_name, account_mode_raw)

    # Live detection is read-only. Runtime control commands are hard-blocked
    # before they can reach the bridge.
    is_live = (account_mode == "live") or (account_mode_raw == "live")
    live_locked = is_live

    # Param validation
    runtime_params = (rt or {}).get("params") or {}
    pcheck = (validate_params(strategy_id, runtime_params)
              if runtime_detected and s["status"] != "rejected" and s["status"] != "archived"
              else {"ok": True, "mismatches": [], "checked": 0})
    if not pcheck["ok"]:
        errors.append(f"PARAM_MISMATCH: {len(pcheck['mismatches'])} key(s) differ")

    # Cross-state mismatch warnings
    mismatch_kind: Optional[str] = None
    if runtime_detected:
        if runtime_enabled and paper_state in ("paper_ready", "stopped_today",
                                               "paused", "risk_blocked"):
            warnings.append("Runtime enabled but not confirmed in NinjaTrader Strategies tab")
            mismatch_kind = "runtime_enabled_not_confirmed"
        if (not runtime_enabled) and paper_state == "paper_running":
            warnings.append("Runtime stopped outside NinjaTrader Strategies tab")
            mismatch_kind = "runtime_stopped_outside"

    # Rejected strategies must never be runtime-confirmed
    if s["status"] in ("rejected", "archived") and runtime_enabled:
        errors.append("Rejected/archived strategy is enabled at runtime — DISABLE in NinjaTrader immediately")

    if is_live:
        warnings.append("LIVE account detected — runtime control is disabled; telemetry is read-only")

    today = compute_runtime_today_metrics(strategy_id) if runtime_detected else {}

    can_confirm_runtime: Optional[str] = None
    if mismatch_kind == "runtime_enabled_not_confirmed" and account_mode in ("paper", "playback", "demo") \
       and s["status"] not in ("rejected", "archived") and pcheck["ok"]:
        can_confirm_runtime = "started"
    elif mismatch_kind == "runtime_stopped_outside" and account_mode in ("paper", "playback", "demo"):
        can_confirm_runtime = "stopped"

    out: Dict[str, Any] = {
        "strategy_id":      canonical_strategy_id,
        "registry_status":  s["status"],
        "paper_state":      paper_state,
        "runtime_detected": runtime_detected,
        "runtime_enabled":  runtime_enabled,
        "account_name":     account_name,
        "account_mode":     account_mode,
        "is_live":          is_live,
        "live_locked":      live_locked,
        "params_ok":        pcheck["ok"],
        "params_check":     pcheck,
        "runtime_warnings": warnings,
        "runtime_errors":   errors,
        "mismatch_kind":    mismatch_kind,
        "can_confirm_runtime": can_confirm_runtime,
        "heartbeat":        hb,
        "today":            today,
        "runtime":          (rt or None),
    }
    if (selected_account is not None or selected_instrument is not None
            or selected_timeframe is not None):
        out["selection_diff"] = compute_selection_diff(
            selected_account, selected_instrument, selected_timeframe, rt)
    return out


def merge_all_strategies() -> List[Dict[str, Any]]:
    return [merge_strategy_view(s["strategy_id"]) for s in ops.list_strategies()]


def _make_runtime_instance_id(r: Dict[str, Any], idx: int) -> str:
    """Stable unique identifier for a specific runtime strategy instance.

    If the bridge already wrote a ``runtime_instance_id`` field (Phase 19+
    bridge builds), we use it directly. Otherwise we compute a synthetic 16-char
    hex ID from the combination of account/class/instrument/name/index so that
    two copies of the same class on the same account are distinguishable.
    """
    existing = str(r.get("runtime_instance_id") or "").strip()
    if existing:
        return existing
    raw = (
        f"{r.get('account_name', '')}|"
        f"{r.get('strategy_class', '')}|"
        f"{r.get('instrument', '')}|"
        f"{r.get('strategy_name', '')}|"
        f"{idx}"
    )
    return "ri-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _contract_root(value: Any) -> str:
    s = str(value or "").strip().upper()
    m = re.match(r"^([A-Z0-9]+)", s)
    return m.group(1) if m else ""


def _read_strategy_profiles_for_runtime() -> List[Dict[str, Any]]:
    p = ops._project_root() / "data" / "profiles" / "strategies.json"
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), list):
        return []
    root = ops._project_root()
    return [
        strategy_families.apply_family_metadata(x, root)
        for x in data["profiles"]
        if isinstance(x, dict)
    ]


def _profile_runtime_classes(profile: Dict[str, Any]) -> set:
    out = set()
    for key in ("strategy_class", "deploy_strategy_class"):
        v = str(profile.get(key) or "").strip().lower()
        if v:
            out.add(v)
    for v in profile.get("runtime_strategy_classes") or []:
        s = str(v or "").strip().lower()
        if s:
            out.add(s)
    return out


def _profile_family_fields(profile: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "root_family": profile.get("root_family") or "",
        "strategy_family": profile.get("strategy_family") or "",
        "family_status": profile.get("family_status") or "",
        "family_role": profile.get("family_role") or "",
        "hub_class": profile.get("hub_class") or "",
        "new_research_allowed": bool(profile.get("new_research_allowed")),
    }


def _profile_registry_hit_for_runtime(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build a registry-like row from data/profiles for deploy wrappers.

    Some production-friendly NinjaScript classes wrap a research engine, e.g.
    VWAPPullbackMGC5mV1 wraps the SessionEdge MGC profile. The ops registry
    may not know these wrappers yet, but strategy profiles do. Use those aliases
    for runtime status and locked-parameter checks.
    """
    sid = str(r.get("strategy_id") or "").strip().lower()
    cls = str(r.get("strategy_class") or r.get("strategy_name") or "").strip().lower()
    root = _contract_root(r.get("instrument") or r.get("contract_month"))
    if not cls and not sid:
        return None
    for p in _read_strategy_profiles_for_runtime():
        p_root = _contract_root(p.get("instrument") or p.get("current_contract"))
        if root and p_root and root != p_root:
            continue
        runtime_sid = str(p.get("runtime_strategy_id") or "").strip().lower()
        canonical_sid = canonical_strategy_id(sid)
        if (cls and cls in _profile_runtime_classes(p)) or (runtime_sid and canonical_sid == canonical_strategy_id(runtime_sid)):
            return {
                **_profile_family_fields(p),
                "strategy_id": canonical_sid or canonical_strategy_id(runtime_sid) or cls,
                "display_name": p.get("name") or p.get("profile_id") or cls,
                "class_name": r.get("strategy_class") or p.get("deploy_strategy_class") or p.get("strategy_class"),
                "status": p.get("status") or "",
                "account_mode": "paper",
                "allowed_accounts": [],
                "instrument": p_root,
                "contract_month": p.get("current_contract") or p.get("instrument") or "",
                "locked_params": p.get("locked_parameters") or {},
                "trade_window_pt": str(p.get("trade_window_pt") or "").strip(),
                "validation_job_id": p.get("last_job_id") or "",
                "validation_summary": p.get("metrics") or {},
                "profile_id": p.get("profile_id") or "",
                "source": "strategy_profile",
            }
    return None


def _profile_registry_hit_for_strategy(strategy_id: str) -> Optional[Dict[str, Any]]:
    s = ops.get_strategy(strategy_id) or {}
    sid = canonical_strategy_id(strategy_id)
    cls = str(s.get("class_name") or "").strip().lower()
    root = _contract_root(s.get("contract_month") or s.get("instrument"))
    aliases = {sid}
    for value in s.get("legacy_strategy_ids") or []:
        alias = canonical_strategy_id(value)
        if alias:
            aliases.add(alias)
    if not cls and not aliases:
        return None
    for p in _read_strategy_profiles_for_runtime():
        p_root = _contract_root(p.get("instrument") or p.get("current_contract"))
        if root and p_root and root != p_root:
            continue
        runtime_sid = canonical_strategy_id(p.get("runtime_strategy_id"))
        stable_sid = canonical_strategy_id(p.get("stable_id"))
        profile_aliases = {
            canonical_strategy_id(v)
            for v in (p.get("legacy_strategy_ids") or [])
            if canonical_strategy_id(v)
        }
        if cls and cls in _profile_runtime_classes(p):
            match = True
        else:
            match = bool(
                (runtime_sid and runtime_sid in aliases) or
                (stable_sid and stable_sid in aliases) or
                (profile_aliases and aliases.intersection(profile_aliases))
            )
        if not match:
            continue
        return {
            **_profile_family_fields(p),
            "strategy_id": stable_sid or runtime_sid or sid or cls,
            "display_name": p.get("name") or p.get("profile_id") or cls,
            "class_name": p.get("deploy_strategy_class") or p.get("strategy_class") or s.get("class_name") or "",
            "status": p.get("status") or s.get("status") or "",
            "account_mode": "paper",
            "allowed_accounts": [],
            "instrument": p_root,
            "contract_month": p.get("current_contract") or p.get("instrument") or "",
            "locked_params": p.get("locked_parameters") or {},
            "trade_window_pt": str(p.get("trade_window_pt") or "").strip(),
            "validation_job_id": p.get("last_job_id") or "",
            "validation_summary": p.get("metrics") or {},
            "profile_id": p.get("profile_id") or "",
            "source": "strategy_profile",
        }
    return None


def _merge_registry_hits(primary: Optional[Dict[str, Any]],
                         profile_hit: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if primary and not profile_hit:
        return primary
    if profile_hit and not primary:
        return profile_hit
    if not primary and not profile_hit:
        return None
    merged = dict(primary or {})
    if profile_hit:
        if profile_hit.get("locked_params"):
            merged["locked_params"] = profile_hit.get("locked_params") or {}
        for key in ("display_name", "validation_job_id", "validation_summary", "profile_id",
                    "trade_window_pt"):
            if profile_hit.get(key):
                merged[key] = profile_hit.get(key)
        for key in ("strategy_id", "class_name", "instrument", "contract_month", "account_mode", "source"):
            if not merged.get(key) and profile_hit.get(key):
                merged[key] = profile_hit.get(key)
    return merged


def merge_all_runtime_strategies(
        selected_account: Optional[str] = None,
        selected_instrument: Optional[str] = None,
        selected_timeframe: Optional[str] = None,
        include_today_metrics: bool = False) -> List[Dict[str, Any]]:
    """Runtime-driven view: source of truth is ``strategies.json`` written by
    the NinjaTrader bridge, NOT the registry.

    Each raw bridge entry is enriched with registry/param info if a matching
    registry ``strategy_id`` exists. Entries unknown to the registry are still
    surfaced as a minimal view so the Trading Online page reflects what
    NinjaTrader actually has, without filtering.

    Every output entry has a unique ``runtime_instance_id`` so that two copies
    of the same strategy class on the same account can be distinguished both
    in the table and in stop/start commands.

    If ``strategies.json`` is empty/absent, returns []. Never invents entries.
    """
    raw_list = read_strategies_raw()
    hb = read_heartbeat()
    runtime_detected_global = bool(hb.get("present")) and bool(hb.get("fresh"))
    hidden_classes = set(read_strategy_display_prefs().get("hidden_classes") or [])
    out: List[Dict[str, Any]] = []

    # Bridge offline → strategies.json on disk is a stale snapshot from the last
    # NT session. Surfacing it would lie about what's actually running. Hide it.
    if not runtime_detected_global:
        return out

    for idx, r in enumerate(raw_list):
        if not isinstance(r, dict):
            continue
        r = dict(r)  # local copy — we'll mutate below

        # Assign stable instance ID before anything else.
        iid = _make_runtime_instance_id(r, idx)
        r["runtime_instance_id"] = iid

        sid = str(r.get("strategy_id") or "").strip()
        cls = str(r.get("strategy_class") or "").strip()
        display_key = _strategy_display_key(cls or sid)
        acct_name     = str(r.get("account_name") or "")
        acct_mode_raw = r.get("account_mode") if isinstance(r.get("account_mode"), str) else None
        acct_mode     = _classify_account_mode(acct_name, acct_mode_raw)

        profile_hit = _profile_registry_hit_for_runtime(r)
        registry_hit = _merge_registry_hits((ops.get_strategy(sid) if sid else None), profile_hit)

        warnings: List[str] = []
        errors: List[str] = []

        stale = _stale_reason(hb)
        if stale:
            warnings.append(stale)

        is_live = (acct_mode == "live")
        if is_live:
            warnings.append("LIVE account — read-only, no controls available")

        # Param check — informational only per Phase 19 spec.
        # Param mismatches must NOT block stop/start in the UI.
        runtime_params = r.get("params") or {}
        locked_params = _sanitize_command_params(
            registry_hit.get("locked_params") or {}) if registry_hit else {}
        if registry_hit and registry_hit.get("status") not in ("rejected", "archived"):
            param_source = str(registry_hit.get("source") or "locked_profile")
            pcheck = _validate_expected_params(
                locked_params, runtime_params, source=param_source)
            # Phase 19: param mismatch is info, not a hard error
            # (do NOT add to errors[] — that would block UI controls)
        else:
            pcheck = {
                "ok": True, "mismatches": [], "checked": 0,
                "source": "", "recommendation": None, "mismatch_keys": [],
            }

        if registry_hit and registry_hit.get("status") in ("rejected", "archived") \
                and r.get("enabled"):
            errors.append(
                "Rejected/archived strategy is enabled at runtime — "
                "DISABLE in NinjaTrader immediately")

        paper_state: Optional[str] = None
        today: Dict[str, Any] = {}
        if registry_hit:
            states = ops.load_states()
            paper_state = (states.get(sid) or {}).get(
                "current_state", registry_hit["status"])
            if include_today_metrics and r.get("enabled"):
                today = compute_runtime_today_metrics(sid)

        tw = _resolve_trade_window_for_strategy(
            registry_hit,
            runtime_params,
            str((registry_hit or {}).get("trade_window_pt") or ""),
        )

        view: Dict[str, Any] = {
            "runtime_instance_id":  iid,
            "strategy_id":          sid or cls.lower(),
            "display_name":         (registry_hit.get("display_name") if registry_hit
                                      else (r.get("strategy_name") or cls)),
            "registry_status":      registry_hit.get("status") if registry_hit else None,
            "profile_id":           registry_hit.get("profile_id") if registry_hit else "",
            "trade_window_pt":      tw.get("trade_window_pt"),
            "trade_window":         tw.get("trade_window"),
            "paper_state":          paper_state,
            "runtime_detected":     runtime_detected_global,
            "runtime_enabled":      bool(r.get("enabled")),
            "account_name":         acct_name,
            "account_mode":         acct_mode,
            "is_live":              is_live,
            "live_locked":          False,
            "locked_params":        locked_params,
            "params_ok":            pcheck["ok"],
            "params_check":         pcheck,
            "runtime_warnings":     warnings,
            "runtime_errors":       errors,
            "mismatch_kind":        None,
            "can_confirm_runtime":  None,
            "heartbeat":            hb,
            "today":                today,
            "runtime":              r,
            "source":               "runtime+registry" if registry_hit else "runtime_only",
            "display_key":          display_key,
            "display_hidden":       display_key in hidden_classes,
        }

        if (selected_account is not None or selected_instrument is not None
                or selected_timeframe is not None):
            view["selection_diff"] = compute_selection_diff(
                selected_account, selected_instrument, selected_timeframe, r)

        out.append(view)

    return out


def read_accounts_with_source() -> Dict[str, Any]:
    """Same as read_accounts() but reports where the data came from.

    `source` is one of:
      - "accounts_json"        — bridge-written accounts.json available & fresh
      - "accounts_json_stale"  — accounts.json present but >2 min behind heartbeat
      - "positions_fallback"   — derived from positions.json keys (no balances)
      - "empty"                — neither file present

    Returns ``next_action`` at the top level when the operator must take a
    deploy/install step (e.g. reinstall the bridge DLL). Paper/playback only.
    """
    raw = _read_json(_path("accounts.json"), default=None)
    items: List[Dict[str, Any]] = []
    source = "empty"
    next_action: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None
    exporter_version: Optional[str] = None
    if isinstance(raw, dict):
        lst = raw.get("accounts")
        if isinstance(lst, list):
            for r in lst:
                if isinstance(r, dict):
                    items.append(_normalize_account(r))
            if items:
                source = "accounts_json"
        if isinstance(raw.get("summary"), dict):
            summary = raw.get("summary")
        if isinstance(raw.get("exporter_version"), str):
            exporter_version = raw.get("exporter_version")
        # staleness check: accounts.json timestamp vs heartbeat timestamp
        if items:
            acc_ts = _parse_iso(raw.get("generated_at_utc")
                                or raw.get("timestamp_utc"))
            hb_raw = _read_json(_path("heartbeat.json"), default=None)
            hb_ts  = _parse_iso((hb_raw or {}).get("timestamp_utc")) if hb_raw else None
            if acc_ts is not None and hb_ts is not None:
                lag = (hb_ts - acc_ts).total_seconds()
                if lag > 120:
                    source = "accounts_json_stale"
    if not items:
        pos = read_positions()
        for name in pos.keys():
            items.append(_normalize_account({"account_name": name}))
        if items:
            source = "positions_fallback"
            next_action = (
                "Bridge DLL устарела (нет accounts.json). "
                "Закрыть NinjaTrader → запустить 01_INSTALL_BRIDGE.cmd → открыть NinjaTrader."
            )
    if not items and source == "empty":
        next_action = (
            "Bridge не записал accounts.json. Проверить, что NinjaTrader открыт "
            "и AddOn запустился (см. NTAnalyzerBridge.log)."
        )

    # Defensive: live accounts must always be flagged regardless of source.
    for a in items:
        if (a.get("account_mode") == "live") and not a.get("is_live"):
            a["is_live"] = True

    # online_accounts = only real user accounts that the UI can show/select
    online_accounts = [a for a in items if a.get("is_selectable_for_online")]

    warnings: List[str] = []
    if source == "accounts_json_stale":
        warnings.append(
            "accounts.json устарел относительно heartbeat (>2 мин). "
            "Балансы могут не отражать текущего состояния."
        )
    elif source == "positions_fallback":
        warnings.append(
            "accounts.json не найден — bridge ещё не пишет полные данные счетов. "
            "Список аккаунтов восстановлен из positions.json. Балансы недоступны."
        )
    elif source == "empty":
        warnings.append(
            "Bridge пока не отдал ни accounts.json, ни positions.json. "
            "Запустите NinjaTrader и проверьте, что AddOn активен."
        )
    out: Dict[str, Any] = {"accounts": items, "online_accounts": online_accounts,
                           "source": source,
                           "warnings": warnings, "next_action": next_action}
    if summary is not None:
        out["summary"] = summary
    if exporter_version is not None:
        out["exporter_version"] = exporter_version

    # Phase 19+ hotfix3: surface staleness so the UI can hide / mark stale
    # balances when NinjaTrader is closed and the bridge is no longer writing
    # accounts.json. The UI uses these to display an "NT OFFLINE" banner
    # instead of a stale (e.g. last-seen DEMO) balance card.
    now = _now_utc()
    acc_raw = _read_json(_path("accounts.json"), default=None) or {}
    acc_ts = _parse_iso(acc_raw.get("generated_at_utc")
                        or acc_raw.get("timestamp_utc"))
    hb_raw = _read_json(_path("heartbeat.json"), default=None) or {}
    hb_ts  = _parse_iso(hb_raw.get("timestamp_utc"))
    accounts_age_sec = (now - acc_ts).total_seconds() if acc_ts else None
    heartbeat_age_sec = (now - hb_ts).total_seconds() if hb_ts else None
    # Keep account online semantics aligned with read_heartbeat().
    bridge_online = bool(heartbeat_age_sec is not None
                         and heartbeat_age_sec <= HEARTBEAT_MAX_AGE_SEC
                         and heartbeat_age_sec >= -5)
    out["accounts_generated_at_utc"] = acc_raw.get("generated_at_utc") \
        or acc_raw.get("timestamp_utc")
    out["heartbeat_at_utc"] = hb_raw.get("timestamp_utc")
    out["accounts_age_sec"] = (round(accounts_age_sec, 1)
                               if accounts_age_sec is not None else None)
    out["heartbeat_age_sec"] = (round(heartbeat_age_sec, 1)
                                if heartbeat_age_sec is not None else None)
    out["bridge_online"] = bridge_online
    return out


# ---------------------------------------------------------------------------
# Health summary
# ---------------------------------------------------------------------------

def health() -> Dict[str, Any]:
    rdir = runtime_dir()
    hb = read_heartbeat()
    files = {}
    for name in ("heartbeat.json", "strategies.json", "executions.jsonl",
                 "orders.jsonl", "positions.json", "errors.jsonl",
                 STRATEGY_HISTORY_FILE, STRATEGY_DISPLAY_PREFS_FILE):
        p = rdir / name
        files[name] = {"exists": p.is_file(),
                       "size":  (p.stat().st_size if p.is_file() else 0)}
    errs = read_errors(20)
    return {
        "runtime_dir":   str(rdir),
        "runtime_dir_exists": rdir.is_dir(),
        "heartbeat":     hb,
        "files":         files,
        "recent_errors": errs[-20:],
        "exporter_ready": bool(hb.get("fresh")),
    }


# ---------------------------------------------------------------------------
# Journal auto-fill from runtime executions
# ---------------------------------------------------------------------------

def _journal_columns_default() -> List[str]:
    """Used when CSV is header-less (rare). Order matters."""
    return [
        "date_pt", "trading_day_number", "session_status",
        "trades_count", "total_qty", "gross_pnl", "commission_estimated",
        "adjusted_pnl", "cumulative_adjusted_pnl", "current_drawdown",
        "high_water_mark", "daily_win_count", "daily_loss_count",
        "median_slippage_ticks", "max_slippage_ticks",
        "stop_hit_count", "target_hit_count", "notes",
    ]


def journal_autofill(strategy_id: str,
                     on_date_pt: Optional[str] = None,
                     dry_run: bool = False) -> Dict[str, Any]:
    """Compute today's quantity-aware row from runtime executions and
    upsert into the daily journal CSV by `date_pt` (preserves manual
    edits on other rows). Returns {ok, action: created|updated|noop, row}.
    """
    s = ops.get_strategy(strategy_id)
    if not s:
        return {"ok": False, "error": "strategy not found"}
    csv_path = s.get("journal_csv_path") or ""
    if not csv_path:
        return {"ok": False, "error": "no journal_csv_path in registry"}
    p = Path(csv_path)

    metrics = compute_runtime_today_metrics(strategy_id, on_date_pt)
    if metrics["trades_count"] == 0:
        return {"ok": True, "action": "noop", "reason": "no trades today",
                "row": metrics, "csv_path": csv_path}

    # Compute cumulative / DD by reading existing journal up to (but not
    # including) today, then appending today's adjusted PnL.
    existing_rows: List[Dict[str, Any]] = []
    header: List[str] = []
    if p.is_file():
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try: header = next(reader)
            except StopIteration: header = []
            for row in reader:
                d = {header[i] if i < len(header) else f"col{i}": row[i]
                     for i in range(len(row))}
                existing_rows.append(d)
    else:
        header = _journal_columns_default()

    today = metrics["date_pt"]
    prior = [r for r in existing_rows if r.get("date_pt") and r.get("date_pt") != today]
    cum = 0.0; hwm = 0.0; dd = 0.0
    for r in prior:
        try:
            v = float(r.get("adjusted_pnl") or r.get("adj_pnl") or 0.0)
        except Exception:
            v = 0.0
        cum += v
        if cum > hwm: hwm = cum
        if (cum - hwm) < dd: dd = (cum - hwm)
    cum += metrics["adjusted_pnl"]
    if cum > hwm: hwm = cum
    if (cum - hwm) < dd: dd = (cum - hwm)

    new_row = {
        "date_pt":              today,
        "trading_day_number":   str(len(prior) + 1),
        "session_status":       "auto",
        "trades_count":         str(metrics["trades_count"]),
        "total_qty":            str(metrics["total_qty"]),
        "gross_pnl":            f"{metrics['gross_pnl']:.2f}",
        "commission_estimated": f"{metrics['commission_estimated']:.2f}",
        "adjusted_pnl":         f"{metrics['adjusted_pnl']:.2f}",
        "cumulative_adjusted_pnl": f"{cum:.2f}",
        "current_drawdown":     f"{dd:.2f}",
        "high_water_mark":      f"{hwm:.2f}",
        "daily_win_count":      str(metrics["daily_win_count"]),
        "daily_loss_count":     str(metrics["daily_loss_count"]),
        "median_slippage_ticks": ("" if metrics["median_slippage_ticks"] is None
                                  else f"{metrics['median_slippage_ticks']:.3f}"),
        "max_slippage_ticks":   ("" if metrics["max_slippage_ticks"] is None
                                 else f"{metrics['max_slippage_ticks']:.3f}"),
        "stop_hit_count":       str(metrics["stop_hit_count"]),
        "target_hit_count":     str(metrics["target_hit_count"]),
        "notes":                "auto-filled from runtime executions",
    }

    # ensure header includes all needed columns (extend if missing)
    extended_header = list(header) if header else _journal_columns_default()
    for k in new_row.keys():
        if k not in extended_header:
            extended_header.append(k)

    # rewrite all rows: header + (prior with extended cols) + (new today row)
    today_existing = [r for r in existing_rows if r.get("date_pt") == today]
    action = "updated" if today_existing else "created"

    if dry_run:
        return {"ok": True, "action": action + "_dry_run", "row": new_row,
                "csv_path": csv_path, "header": extended_header}

    out_rows = prior + [new_row]
    tmp = p.with_suffix(p.suffix + ".tmp")
    p.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(extended_header)
        for r in out_rows:
            w.writerow([r.get(c, "") for c in extended_header])
    os.replace(tmp, p)

    ops.audit_append("runtime/journal_autofill", strategy_id, "n/a", "n/a",
                     reason=f"{action} row date_pt={today} trades={metrics['trades_count']} "
                            f"adj={metrics['adjusted_pnl']:.2f}")
    return {"ok": True, "action": action, "row": new_row,
            "cumulative_adjusted_pnl": round(cum, 2),
            "current_drawdown": round(dd, 2),
            "csv_path": csv_path}


# ---------------------------------------------------------------------------
# Operator confirmations bound to runtime mismatch
# ---------------------------------------------------------------------------

def confirm_runtime(strategy_id: str, action: str, reason: str = "") -> Dict[str, Any]:
    """Bridge between runtime detection and Phase 16 state machine.

    - action="started": registry must allow paper start. Account must be
      paper/playback. Params must be OK. Drives state -> armed -> paper_running.
    - action="stopped": drives paper_running/paused -> stopped_today.
    """
    if action not in ("started", "stopped"):
        raise ops.OpsError("action must be 'started' or 'stopped'", 400)
    view = merge_strategy_view(strategy_id)
    if "error" in view:
        raise ops.OpsError(view["error"], 404)
    s = ops.get_strategy(strategy_id) or {}
    if s.get("status") in ("rejected", "archived"):
        raise ops.OpsError("rejected/archived strategy cannot be runtime-confirmed", 403)
    if view.get("account_mode") not in ("paper", "playback", "demo"):
        raise ops.OpsError(
            f"account_mode={view.get('account_mode')} not allowed for runtime confirm", 403)
    if action == "started":
        if not view.get("params_ok"):
            raise ops.OpsError("PARAM_MISMATCH — fix params in NinjaTrader before confirm", 409)
        states = ops.load_states()
        sid = str(s.get("strategy_id") or strategy_id)
        cur = (states.get(sid) or {}).get("current_state", s["status"])
        # auto-arm if paper_ready
        if cur == "paper_ready":
            ops.arm(strategy_id, reason or "runtime auto-arm")
        return ops.confirm_manual(strategy_id, "started",
                                  reason=reason or "runtime confirm started")
    else:
        return ops.confirm_manual(strategy_id, "stopped",
                                  reason=reason or "runtime confirm stopped")


# ---------------------------------------------------------------------------
# Phase 17b — command file protocol (UI → NT bridge)
# ---------------------------------------------------------------------------
#
# UI/backend appends commands to data/runtime/commands.jsonl.
# The C# AddOn (when implemented) reads new lines, executes paper-only
# Strategy.SetState(...) on Sim/Playback accounts, and appends a result
# line to data/runtime/command_results.jsonl. Live accounts are HARD-blocked
# at the Python layer here — backend refuses to even queue a command for
# a live account, so the bridge never sees one.

COMMANDS_FILE = "commands.jsonl"
COMMAND_RESULTS_FILE = "command_results.jsonl"

STRATEGY_RUNTIME_COMMANDS = ("enable_strategy", "disable_strategy")
ACCOUNT_RUNTIME_COMMANDS = ("reconnect_account",)
ALLOWED_COMMANDS = STRATEGY_RUNTIME_COMMANDS + ACCOUNT_RUNTIME_COMMANDS


def _is_paper_account(account_name: str) -> bool:
    """Treat unknown as NOT paper. Only explicit Sim/Playback/Paper/Demo names pass."""
    if not account_name:
        return False
    return _classify_account_mode(account_name) in ("paper", "playback", "demo")


def _resolve_account_mode_for_command(account_name: str) -> str:
    """Look up the bridge-declared account_mode (preferred) and fall back to
    name-hint classification. Returns 'paper'|'demo'|'playback'|'live'|'unknown'.
    Live accounts often have numeric names with no hint, so the bridge's
    declared mode (from NT Account.Provider) is the authoritative source."""
    if not account_name:
        return "unknown"
    declared: Optional[str] = None
    try:
        for a in read_accounts():
            if a.get("account_name") == account_name:
                declared = a.get("account_mode")
                break
    except Exception:
        declared = None
    return _classify_account_mode(account_name, declared)


def _default_connection_command_strategy_id(account_name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(account_name or "").strip()) or "account"
    return f"runtime_connection_reconnect__{safe}"


def _is_datafeed_connection_name(connection_name: str) -> bool:
    value = str(connection_name or "").strip().lower()
    return any(marker in value for marker in (
        "data feed", "datafeed", "датафид", "дата фид",
    ))


def submit_command(command: str,
                   strategy_id: str,
                   account_name: str,
                   quantity: int = 1,
                   reason: str = "",
                   operator: str = "ui",
                   class_name: str = "",
                   instrument: str = "",
                   contract_month: str = "",
                   timeframe: str = "",
                   runtime_instance_id: str = "",
                   params: Optional[Dict[str, Any]] = None,
                   connection_name: str = "") -> Dict[str, Any]:
    """Queue a command for the NT bridge (paper/playback/demo only).

    Hard rules:
      * command must be in ALLOWED_COMMANDS
      * account must classify as paper, playback or demo (NOT live/unknown)
      * if strategy_id matches a registry entry → registry archived/rejected
        launch block applies to enable_strategy. disable_strategy remains
        allowed so a frozen strategy can still be stopped from runtime.
      * reconnect_account targets the account connection only and therefore
        does not require a strategy instance/class.
      * runtime_instance_id (when provided) targets the exact strategy
        instance the UI selected; the bridge uses it to disambiguate
        multiple instances of the same class on the same account.
      * params (optional) is a dict of operator-chosen NinjaScript property
        overrides; persisted into the command record so the bridge can apply
        them.
    """
    if command not in ALLOWED_COMMANDS:
        raise ops.OpsError(f"command not allowed: {command}", 400)
    connection_command = command in ACCOUNT_RUNTIME_COMMANDS
    s = ops.get_strategy(strategy_id) if strategy_id else None
    if connection_command:
        canonical_sid = str(strategy_id or _default_connection_command_strategy_id(account_name))
        resolved_class = str(class_name or "").strip()
    else:
        if not strategy_id:
            raise ops.OpsError("strategy_id required", 400)
        canonical_sid = str((s or {}).get("strategy_id") or strategy_id)
        resolved_class = class_name or (s.get("class_name") if s else "")
        if not resolved_class:
            raise ops.OpsError("class_name required (catalog strategy)", 400)
    if command == "enable_strategy" and s and s.get("status") in ("rejected", "archived"):
        raise ops.OpsError("strategy is archived/rejected — launch refused", 403)
    if connection_command and _is_system_account(account_name):
        raise ops.OpsError(
            f"account '{account_name}' is a NinjaTrader system account — "
            "reconnect is not allowed", 403)
    if connection_command and _is_datafeed_connection_name(connection_name):
        raise ops.OpsError(
            "data-feed connections cannot be used for account reconnect", 403)
    acct_mode = _resolve_account_mode_for_command(account_name)
    if acct_mode == "unknown":
        raise ops.OpsError(
            f"account '{account_name}' could not be classified by name or bridge "
            "telemetry — refusing command for safety", 403)
    if acct_mode == "live":
        raise ops.OpsError(
            f"account '{account_name}' is live — runtime control is disabled", 403)
    try:
        qty = int(quantity)
    except Exception:
        qty = 1
    if qty < 1:
        qty = 1

    if command == "enable_strategy":
        expected_locked_params: Dict[str, Any] = {}
        hb = read_heartbeat()
        if hb.get("present") and hb.get("fresh"):
            raw_runtime: List[Dict[str, Any]] = []
            for idx, row in enumerate(read_strategies_raw()):
                if not isinstance(row, dict):
                    continue
                row_copy = dict(row)
                row_copy["runtime_instance_id"] = str(
                    row_copy.get("runtime_instance_id") or _make_runtime_instance_id(row_copy, idx))
                raw_runtime.append(row_copy)
            matched = _match_runtime_for_command({
                "runtime_instance_id": runtime_instance_id or "",
                "strategy_class": resolved_class,
                "account_name": account_name,
                "instrument": instrument or (s.get("instrument") if s else ""),
            }, raw_runtime)
            if matched is not None:
                profile_hit = _profile_registry_hit_for_runtime(matched)
                expected_hit = _merge_registry_hits(s, profile_hit) if s else profile_hit
                if expected_hit and expected_hit.get("status") not in ("rejected", "archived"):
                    expected_locked_params = _sanitize_command_params(
                        expected_hit.get("locked_params") or {})
                    pcheck = _validate_expected_params(
                        expected_locked_params,
                        matched.get("params") or {},
                    )
                    if not pcheck.get("ok"):
                        mismatches = pcheck.get("mismatches") or []
                        preview = ", ".join(
                            f"{m.get('key')}={m.get('actual')} (expected {m.get('expected')})"
                            for m in mismatches[:3]
                        )
                        if len(mismatches) > 3:
                            preview += f", ... +{len(mismatches) - 3}"
                        raise ops.OpsError(
                            "PARAM_MISMATCH — runtime instance params differ from locked profile: " +
                            preview,
                            409,
                        )
        if not expected_locked_params:
            profile_fallback = _profile_registry_hit_for_strategy(canonical_sid)
            if profile_fallback and profile_fallback.get("locked_params"):
                expected_locked_params = _sanitize_command_params(
                    profile_fallback.get("locked_params") or {})
            elif s and s.get("locked_params"):
                expected_locked_params = _sanitize_command_params(
                    s.get("locked_params") or {})
        final_params = dict(expected_locked_params)
        final_params.update(_sanitize_command_params(params or {}))
    else:
        final_params = _sanitize_command_params(params or {})

    now = _now_utc()
    cid = now.strftime("cmd-%Y%m%dT%H%M%S") + f"-{int(now.microsecond/1000):03d}"
    record = {
        "command_id": cid,
        "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": command,
        "strategy_id": canonical_sid,
        "strategy_class": resolved_class,
        "instrument": instrument or (s.get("instrument") if s else ""),
        "contract_month": contract_month or (s.get("contract_month") if s else ""),
        "timeframe": timeframe or "",
        "account_name": account_name,
        "quantity": qty,
        "operator": operator,
        "reason": reason or "",
        "params": final_params,
        "runtime_instance_id": runtime_instance_id or "",
        "connection_name": str(connection_name or "").strip(),
        "live_block_passed": True,
    }
    p = _path(COMMANDS_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    try:
        ops.audit_append(
            f"runtime_command:{command}",
            canonical_sid,
            (s.get("status", "") if s else "catalog"),
            (s.get("status", "") if s else "catalog"),
            by=operator,
            reason=f"account={account_name} qty={qty} cid={cid} {reason}",
        )
    except Exception:
        pass
    record["status"] = "queued"
    record["state"] = "waiting_for_bridge"
    record["timeout_sec"] = _CMD_DEFAULT_TIMEOUT_SEC
    return record


def read_commands(limit: int = 200) -> List[Dict[str, Any]]:
    return _read_jsonl(_path(COMMANDS_FILE), max_lines=limit)


def read_command_results(limit: int = 500) -> List[Dict[str, Any]]:
    """Tail-read `data/runtime/command_results.jsonl` written by the bridge.

    Paper/playback only — the bridge refuses to process commands for live
    accounts at the C# layer, but this reader is content-agnostic. Each row
    typically carries: command_id, timestamp_utc, status
    ("completed" | "failed" | "rejected"), message, strategy_id, optionally
    account_name and strategy_class. Malformed lines are silently skipped.
    Returns the most recent `limit` rows.
    """
    return _read_jsonl(_path(COMMAND_RESULTS_FILE), max_lines=limit)


# ---------------------------------------------------------------------------
# Phase 3 — instrument / timeframe normalization & selection diff
# ---------------------------------------------------------------------------

_MONTH_NAME_TO_NUM: Dict[str, str] = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}


def normalize_instrument(s: str) -> Tuple[str, str]:
    """Return ``(root_upper, "MM-YY")`` for an instrument descriptor.

    Paper/playback bridge contract — the bridge writes instrument names in
    one of: ``"MNQ JUN26"``, ``"MNQ 06-26"``, root-only ``"MNQ"`` or blank.
    Unknown shapes degrade to ``(input_upper_root_or_empty, "")`` rather
    than raising. Year is kept as the 2-digit form supplied by NinjaTrader.
    """
    if not s:
        return ("", "")
    raw = str(s).strip().upper()
    if not raw:
        return ("", "")
    # split on whitespace or '-' boundary; expiry token is the last segment
    # that contains digits or matches a month name.
    parts = raw.replace("\t", " ").split()
    if len(parts) == 1:
        # could be "MNQ" or "MNQ06-26" (rare). Try to detect digit suffix.
        token = parts[0]
        # check trailing "MMMYY" or "MM-YY"
        for i in range(1, len(token)):
            tail = token[i:]
            mm, yy = _parse_expiry_token(tail)
            if mm:
                return (token[:i], f"{mm}-{yy}")
        return (token, "")
    root = parts[0]
    expiry = " ".join(parts[1:])
    mm, yy = _parse_expiry_token(expiry)
    if not mm:
        return (root, "")
    return (root, f"{mm}-{yy}")


def _parse_expiry_token(tok: str) -> Tuple[str, str]:
    """Parse 'JUN26', 'JUN 26', '06-26', '06/26', '0626' -> ('06','26')."""
    if not tok:
        return ("", "")
    t = tok.strip().upper().replace(" ", "").replace("/", "-")
    # MM-YY
    if "-" in t:
        a, _, b = t.partition("-")
        if a.isdigit() and b.isdigit() and len(a) <= 2 and len(b) == 2:
            return (a.zfill(2), b)
    # MMMYY  (e.g. JUN26)
    if len(t) >= 5 and t[:3].isalpha() and t[3:].isdigit():
        mm = _MONTH_NAME_TO_NUM.get(t[:3])
        yy = t[3:]
        if mm and len(yy) == 2:
            return (mm, yy)
    # MMYY all digits
    if t.isdigit() and len(t) == 4:
        return (t[:2], t[2:])
    return ("", "")


def instruments_match(a: str, b: str) -> bool:
    """Loose match: equal root AND equal MM-YY (or one side has no expiry).

    Paper/playback only — used to bind UI-selected instrument to a runtime
    strategy reported by the bridge. A blank ``MM-YY`` on either side is
    treated as a wildcard (root-only descriptor matches a dated contract).
    """
    ra, ea = normalize_instrument(a)
    rb, eb = normalize_instrument(b)
    if not ra or not rb:
        return False
    if ra != rb:
        return False
    if not ea or not eb:
        return True
    return ea == eb


def normalize_timeframe(s: str) -> Tuple[str, int]:
    """Return ``(period_type_lower, value)`` for a timeframe descriptor.

    Paper/playback bridge contract — NinjaTrader exports ``"5 Minute"`` or
    ``"1 Hour"``; the legacy backtest UI uses ``"Minute/5"`` / ``"Hour/1"``.
    Both shapes (and blank) are accepted. Unknown -> ``("", 0)``.
    """
    if not s:
        return ("", 0)
    raw = str(s).strip()
    if not raw:
        return ("", 0)
    # "Minute/5"
    if "/" in raw:
        kind, _, val = raw.partition("/")
        try:
            return (kind.strip().lower(), int(val.strip()))
        except ValueError:
            return (kind.strip().lower(), 0)
    # "5 Minute"
    parts = raw.split()
    if len(parts) == 2:
        a, b = parts
        if a.isdigit():
            return (b.lower(), int(a))
        if b.isdigit():
            return (a.lower(), int(b))
    # bare "Minute" / "Day"
    if raw.isalpha():
        return (raw.lower(), 0)
    return ("", 0)


def timeframes_match(a: str, b: str) -> bool:
    """Loose timeframe match. Blank/unknown on either side -> True (graceful)
    because older bridge builds do not export ``timeframe`` at all.
    Paper/playback only — informational, never used to gate live trading.
    """
    na = normalize_timeframe(a)
    nb = normalize_timeframe(b)
    if not na[0] or not nb[0]:
        return True
    return na == nb


def compute_selection_diff(selected_account: Optional[str],
                           selected_instrument: Optional[str],
                           selected_timeframe: Optional[str],
                           runtime_strategy: Optional[Dict[str, Any]]
                           ) -> Dict[str, Any]:
    """Compare UI-selected (account, instrument, timeframe) against a runtime
    strategy row. Paper/playback only — the result is read-only diagnostics
    for the Trading Online tab and never affects live trading paths.

    The returned shape is stable so the UI can render badges deterministically.
    Account mismatch and instrument mismatch are blocking; timeframe is
    warning-only (the bridge does not always export it on older builds).
    """
    rt = runtime_strategy or {}
    rt_account    = str(rt.get("account_name") or "")
    rt_instrument = str(rt.get("instrument") or rt.get("contract_month") or "")
    rt_timeframe  = str(rt.get("timeframe") or "")

    sel_account    = (selected_account or "").strip()
    sel_instrument = (selected_instrument or "").strip()
    sel_timeframe  = (selected_timeframe or "").strip()

    acct_match = bool(sel_account) and (sel_account.lower() == rt_account.lower())
    inst_norm_match = instruments_match(sel_instrument, rt_instrument) \
        if sel_instrument and rt_instrument else False
    inst_exact = bool(sel_instrument) and (sel_instrument == rt_instrument)
    inst_match = inst_exact or inst_norm_match
    tf_match = timeframes_match(sel_timeframe, rt_timeframe)

    account_block = {
        "matches":   acct_match,
        "expected":  sel_account or None,
        "actual":    rt_account or None,
        "blocking":  (not acct_match) and bool(sel_account),
    }
    instrument_block = {
        "matches":          inst_match,
        "expected":         sel_instrument or None,
        "actual":           rt_instrument or None,
        "normalized_match": inst_norm_match,
        "blocking":         (not inst_match) and bool(sel_instrument),
    }
    timeframe_block = {
        "matches":   tf_match,
        "expected":  sel_timeframe or None,
        "actual":    rt_timeframe or None,
        "blocking":  False,  # never blocking — bridge may not export it
    }
    any_blocker = bool(account_block["blocking"] or instrument_block["blocking"])
    return {
        "account":     account_block,
        "instrument":  instrument_block,
        "timeframe":   timeframe_block,
        "any_blocker": any_blocker,
    }


# ---------------------------------------------------------------------------
# Phase 2 — command status state machine
# ---------------------------------------------------------------------------

_CMD_DEFAULT_TIMEOUT_SEC = 30
_BRIDGE_RUNTIME_GRACE_SEC = 5  # bridge reported done -> wait for telemetry tick


def _match_runtime_for_command(cmd: Dict[str, Any],
                               raw_strategies: List[Dict[str, Any]]
                               ) -> Optional[Dict[str, Any]]:
    """Match the runtime row that corresponds to ``cmd``.

    Preference order:
      1. Exact ``runtime_instance_id`` match (when the command carries one).
         This is the only correct way to disambiguate multiple instances of
         the same class on the same account.
      2. Loose ``(strategy_class, account_name, instrument)`` match, while
         skipping ghost rows (state in {Finalized, Terminated, ""}) so a
         dead instance doesn't shadow the live one.
    """
    cmd_iid = str(cmd.get("runtime_instance_id") or "")
    if cmd_iid:
        for r in raw_strategies:
            if isinstance(r, dict) and str(r.get("runtime_instance_id") or "") == cmd_iid:
                return r
        # explicit id given but not found — caller treats as no match
        return None

    GHOSTS = {"finalized", "terminated"}
    cmd_class = str(cmd.get("strategy_class") or "").lower()
    cmd_acct  = str(cmd.get("account_name") or "").lower()
    cmd_inst  = str(cmd.get("instrument") or "")
    for r in raw_strategies:
        if not isinstance(r, dict):
            continue
        rstate = str(r.get("state") or "").lower()
        rdsc   = r.get("data_series_count")
        if rstate in GHOSTS and not r.get("enabled") and (rdsc == 0):
            continue
        rcls = str(r.get("strategy_class") or "").lower()
        racct = str(r.get("account_name") or "").lower()
        rinst = str(r.get("instrument") or r.get("contract_month") or "")
        if cmd_class and rcls != cmd_class:
            continue
        if cmd_acct and racct != cmd_acct:
            continue
        if cmd_inst and rinst and not instruments_match(cmd_inst, rinst):
            continue
        return r
    return None


def _classify_rejected_message(message: str) -> str:
    """Map bridge rejection text to a stable Phase-2 sub-state."""
    m = (message or "").lower()
    if "not paper" in m or "not playback" in m or "live" in m:
        return "failed_account_mismatch"
    if "shortonly" in m or "param mismatch" in m:
        return "failed_param_mismatch"
    if "no '" in m and "instance" in m:
        return "failed_no_instance"
    if "no instance" in m or "not found" in m:
        return "failed_no_instance"
    return "failed_rejected"


def get_command_status(command_id: str,
                       timeout_sec: int = _CMD_DEFAULT_TIMEOUT_SEC
                       ) -> Dict[str, Any]:
    """Resolve the current state of a queued bridge command (paper/playback
    only — the backend refuses to queue live commands).

    Reads ``commands.jsonl``, ``command_results.jsonl``, ``heartbeat.json``
    and ``strategies.json`` from ``data/runtime/`` and returns a single dict
    suitable for rendering a status pill in the Trading Online UI. Never
    raises; missing/malformed inputs degrade to ``unknown_command`` /
    ``failed_bridge_offline`` states. See plan.md Phase 2 for the full state
    table.
    """
    cmds = read_commands(limit=2000)
    cmd: Optional[Dict[str, Any]] = None
    for c in cmds:
        if str(c.get("command_id") or "") == command_id:
            cmd = c
            break
    if cmd is None:
        return {
            "command_id":  command_id,
            "state":       "unknown_command",
            "reason":      "command_id not in commands.jsonl",
            "timeout_sec": int(timeout_sec),
        }

    submitted_at = _parse_iso(cmd.get("timestamp_utc"))
    elapsed_sec  = ((_now_utc() - submitted_at).total_seconds()
                    if submitted_at else 0.0)

    # bridge result lookup
    bridge_row: Optional[Dict[str, Any]] = None
    for r in read_command_results(limit=2000):
        if str(r.get("command_id") or "") == command_id:
            bridge_row = r  # take the latest match (results may dedupe)
    bridge_result: Optional[Dict[str, Any]] = None
    if bridge_row is not None:
        bridge_result = {
            "status":           str(bridge_row.get("status") or ""),
            "message":          str(bridge_row.get("message") or ""),
            "completed_at_utc": bridge_row.get("timestamp_utc")
                                or bridge_row.get("completed_at_utc"),
        }

    hb = read_heartbeat()
    hb_view = {
        "present":  bool(hb.get("present")),
        "fresh":    bool(hb.get("fresh")),
        "stale_sec": (hb.get("age_sec") if hb.get("present") else None),
    }

    cmd_kind = str(cmd.get("command") or "")
    raw_strats = read_strategies_raw() if cmd_kind in STRATEGY_RUNTIME_COMMANDS else []
    rt_match_raw = _match_runtime_for_command(cmd, raw_strats) if raw_strats else None
    runtime_match: Optional[Dict[str, Any]] = None
    if rt_match_raw is not None:
        runtime_match = {
            "strategy_class": rt_match_raw.get("strategy_class"),
            "account_name":   rt_match_raw.get("account_name"),
            "instrument":     rt_match_raw.get("instrument")
                              or rt_match_raw.get("contract_month"),
            "enabled":        bool(rt_match_raw.get("enabled")),
            "timestamp_utc":  rt_match_raw.get("timestamp_utc"),
        }
    account_match = next((
        {
            "account_name": row.get("account_name"),
            "account_mode": row.get("account_mode"),
            "connection_status": row.get("connection_status"),
        }
        for row in read_accounts()
        if str(row.get("account_name") or "") == str(cmd.get("account_name") or "")
    ), None)

    base: Dict[str, Any] = {
        "command_id":       command_id,
        "command":          cmd_kind,
        "strategy_id":      cmd.get("strategy_id"),
        "strategy_class":   cmd.get("strategy_class"),
        "account_name":     cmd.get("account_name"),
        "instrument":       cmd.get("instrument"),
        "timeframe":        cmd.get("timeframe"),
        "submitted_at_utc": cmd.get("timestamp_utc"),
        "elapsed_sec":      round(float(elapsed_sec), 2),
        "bridge_result":    bridge_result,
        "runtime_match":    runtime_match,
        "account_match":    account_match,
        "heartbeat":        hb_view,
        "connection_name":  cmd.get("connection_name") or "",
        "timeout_sec":      int(timeout_sec),
    }

    state = "waiting_for_bridge"
    reason = "no bridge_result yet — waiting for command_results.jsonl"

    if bridge_result is not None:
        bstatus = bridge_result["status"].lower()
        bmsg    = bridge_result["message"]
        if bstatus == "rejected":
            state  = _classify_rejected_message(bmsg)
            reason = bmsg or "command rejected by bridge"
        elif bstatus == "failed":
            state  = "failed_other"
            reason = bmsg or "bridge reported failure"
        elif bstatus == "completed":
            if (not hb_view["present"]) or (not hb_view["fresh"]):
                state = "failed_bridge_offline"
                reason = (
                    "bridge completed the command, but heartbeat is missing or stale; "
                    "runtime telemetry confirmation is not trusted"
                )
            elif cmd_kind == "enable_strategy":
                if runtime_match and runtime_match["enabled"]:
                    state  = "confirmed_running"
                    reason = "runtime strategy entry shows enabled=True"
                elif elapsed_sec > timeout_sec:
                    state  = "failed_no_runtime_confirmation"
                    reason = ("Bridge принял команду, но NinjaTrader не подтвердил "
                              "переход стратегии в Realtime в пределах таймаута. "
                              "Проверьте Strategies tab вручную.")
                else:
                    state  = "bridge_completed_awaiting_runtime"
                    reason = ("bridge completed; waiting up to "
                              f"{_BRIDGE_RUNTIME_GRACE_SEC}s for next telemetry tick")
            elif cmd_kind == "disable_strategy":
                if (runtime_match is None) or (not runtime_match["enabled"]):
                    state  = "confirmed_stopped"
                    reason = "runtime strategy entry missing or enabled=False"
                elif elapsed_sec > timeout_sec:
                    state  = "failed_no_runtime_confirmation"
                    reason = ("Bridge принял команду disable, но стратегия в "
                              "NinjaTrader всё ещё enabled=True после таймаута.")
                else:
                    state  = "bridge_completed_awaiting_runtime"
                    reason = ("bridge completed; waiting up to "
                              f"{_BRIDGE_RUNTIME_GRACE_SEC}s for next telemetry tick")
            elif cmd_kind == "reconnect_account":
                if account_match and str(account_match.get("connection_status") or "").strip().lower() == "connected":
                    state  = "confirmed_connected"
                    reason = "account connection_status is Connected"
                elif elapsed_sec > timeout_sec:
                    state  = "failed_no_runtime_confirmation"
                    reason = ("Bridge принял команду reconnect, но выбранный paper/demo "
                              "account не перешёл в Connected в пределах таймаута.")
                else:
                    state  = "bridge_completed_awaiting_runtime"
                    reason = ("bridge completed; waiting for accounts.json to report "
                              "connection_status=Connected")
            else:
                state  = "failed_other"
                reason = f"unknown command kind: {cmd_kind}"
        else:
            state  = "failed_other"
            reason = f"unrecognized bridge status: {bstatus}"
    else:
        if (not hb_view["present"]) or (not hb_view["fresh"]):
            state  = "failed_bridge_offline"
            reason = ("bridge heartbeat missing or stale — NinjaTrader may be "
                      "closed or NTAnalyzerBridge AddOn is not running")
        elif elapsed_sec >= timeout_sec:
            state  = "failed_timeout"
            reason = (f"no command_results.jsonl entry for command_id within "
                      f"{int(timeout_sec)}s — bridge processor not running or "
                      "DLL stale (run 01_INSTALL_BRIDGE.cmd)")
        else:
            state  = "waiting_for_bridge"
            reason = (f"awaiting bridge response ({int(elapsed_sec)}s of "
                      f"{int(timeout_sec)}s elapsed)")

    base["state"]  = state
    base["reason"] = reason
    return base


def get_command_statuses_since(since_ts: Optional[str] = None,
                               timeout_sec: int = _CMD_DEFAULT_TIMEOUT_SEC
                               ) -> List[Dict[str, Any]]:
    """Batch resolver: returns ``get_command_status`` for every command
    submitted at-or-after ``since_ts`` (ISO-8601 UTC). When ``since_ts`` is
    omitted, defaults to the last 30 minutes. Paper/playback only.
    """
    since_dt = _parse_iso(since_ts) if since_ts else None
    if since_dt is None:
        since_dt = _now_utc() - timedelta(minutes=30)
    out: List[Dict[str, Any]] = []
    for c in read_commands(limit=2000):
        cid = str(c.get("command_id") or "")
        if not cid:
            continue
        ts = _parse_iso(c.get("timestamp_utc"))
        if ts is None or ts < since_dt:
            continue
        out.append(get_command_status(cid, timeout_sec=timeout_sec))
    return out
