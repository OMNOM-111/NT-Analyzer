"""
NT-Analyzer — Phase 17 NinjaTrader runtime bridge.

Reads telemetry files written by the NinjaTrader-side RuntimeExporter
(part of NTAnalyzerBridge AddOn) and merges them with the registry
state from `app.ops`. Read-only. **No live trading control.**

Storage layout under <project_root>/data/runtime/ :
  heartbeat.json       — { timestamp_utc, ninja_version, machine, ... }
  strategies.json      — { generated_at_utc, strategies: [...] }
  executions.jsonl     — append-only fills (one JSON object per line)
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
import statistics
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import ops

HEARTBEAT_MAX_AGE_SEC = 60          # heartbeat older than this => stale
RUNTIME_DIR_NAME      = "runtime"

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

LIVE_ACCOUNT_HINTS = ("live", "real", "production", "prod")
PAPER_ACCOUNT_HINTS = ("sim101", "sim ", "paper")
DEMO_ACCOUNT_HINTS  = ("demo",)

# Accounts that NinjaTrader exposes but are system/backtest pseudo-accounts —
# never shown in the "Торговля онлайн" dropdown and never selectable.
_SYSTEM_ACCOUNT_NAMES = frozenset({"backtest", "sim101", "playback101"})


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def runtime_dir() -> Path:
    d = ops._project_root() / "data" / RUNTIME_DIR_NAME
    return d


def _path(name: str) -> Path:
    return runtime_dir() / name


# ---------------------------------------------------------------------------
# JSON / JSONL helpers
# ---------------------------------------------------------------------------

def _read_json(p: Path, default: Any = None) -> Any:
    if not p.is_file():
        return default
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _read_jsonl(p: Path, max_lines: int = 5000) -> List[Dict[str, Any]]:
    if not p.is_file():
        return []
    out: List[Dict[str, Any]] = []
    try:
        with p.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return []
    if max_lines and len(lines) > max_lines:
        lines = lines[-max_lines:]
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


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
        out.append(it)
    return out


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
    is_selectable = (mode in ("paper", "playback", "demo", "live")) and not is_system
    hidden_reason: Optional[str] = (
        "system/backtest/playback account" if is_system else None)

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


def read_orders(strategy_id: Optional[str] = None,
                limit: int = 500) -> List[Dict[str, Any]]:
    rows = _read_jsonl(_path("orders.jsonl"))
    if strategy_id:
        rows = [r for r in rows if str(r.get("strategy_id") or "") == strategy_id]
    return rows[-limit:]


def read_executions(strategy_id: Optional[str] = None,
                    limit: int = 1000) -> List[Dict[str, Any]]:
    rows = _read_jsonl(_path("executions.jsonl"))
    if strategy_id:
        rows = [r for r in rows if str(r.get("strategy_id") or "") == strategy_id]
    return rows[-limit:]


def read_errors(limit: int = 200) -> List[Dict[str, Any]]:
    return _read_jsonl(_path("errors.jsonl"))[-limit:]


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
    if strategy_id == "b1_shortonly":
        expected = B1_LOCKED_PARAMS_CHECK
    else:
        s = ops.get_strategy(strategy_id) or {}
        expected = s.get("locked_params") or {}
    mismatches: List[Dict[str, Any]] = []
    rp = runtime_params or {}
    # Make case-insensitive lookup of runtime_params
    rp_lower = {str(k).lower(): v for k, v in rp.items()}
    for k, v_exp in expected.items():
        if not isinstance(v_exp, (int, float, bool, str)):
            continue
        v_act = rp.get(k, rp_lower.get(str(k).lower(), None))
        if v_act is None:
            mismatches.append({"key": k, "expected": v_exp, "actual": None,
                               "reason": "missing"})
            continue
        if not _eq_loose(v_exp, v_act):
            mismatches.append({"key": k, "expected": v_exp, "actual": v_act,
                               "reason": "value_mismatch"})
    return {"ok": len(mismatches) == 0, "mismatches": mismatches,
            "checked": len(expected)}


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

    exits = [e for e in today_execs if _exec_is_exit(e)]
    gross_pnl = 0.0
    total_qty = 0.0
    wins = losses = 0
    slips_ticks: List[float] = []
    stop_hits = target_hits = 0

    for e in exits:
        q = _abs_qty(e)
        total_qty += q
        p = _exec_pnl(e) or 0.0
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
        "trades_count":         len(exits),
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
    cls = (registry_strategy.get("class_name") or "").lower()
    for r in raw_strategies:
        rsid = str(r.get("strategy_id") or "").lower()
        rcls = str(r.get("strategy_class") or "").lower()
        if rsid and rsid == sid_l:
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
    states = ops.load_states()
    paper_state = (states.get(strategy_id) or {}).get("current_state", s["status"])
    hb = read_heartbeat()
    raw_list = read_strategies_raw()
    rt = _find_runtime_for(strategy_id, s, raw_list)

    warnings: List[str] = []
    errors: List[str] = []
    stale = _stale_reason(hb)
    if stale:
        warnings.append(stale)

    runtime_detected = bool(rt) and bool(hb.get("present")) and bool(hb.get("fresh"))
    runtime_enabled  = bool(rt and rt.get("enabled"))
    account_name     = (rt or {}).get("account_name") or ""
    account_mode_raw = (rt or {}).get("account_mode")
    account_mode     = _classify_account_mode(account_name, account_mode_raw)

    # Live detection — informational only, account-agnostic control mode.
    is_live = (account_mode == "live") or (account_mode_raw == "live")
    live_locked = False  # account-agnostic: live and demo are controlled identically

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
        warnings.append("LIVE account detected — управление работает так же, как на demo/paper")

    today = compute_runtime_today_metrics(strategy_id) if runtime_detected else {}

    can_confirm_runtime: Optional[str] = None
    if mismatch_kind == "runtime_enabled_not_confirmed" and account_mode in ("paper", "playback", "demo", "live") \
       and s["status"] not in ("rejected", "archived") and pcheck["ok"]:
        can_confirm_runtime = "started"
    elif mismatch_kind == "runtime_stopped_outside" and account_mode in ("paper", "playback", "demo", "live"):
        can_confirm_runtime = "stopped"

    out: Dict[str, Any] = {
        "strategy_id":      strategy_id,
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


def merge_all_runtime_strategies(
        selected_account: Optional[str] = None,
        selected_instrument: Optional[str] = None,
        selected_timeframe: Optional[str] = None) -> List[Dict[str, Any]]:
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
    out: List[Dict[str, Any]] = []

    for idx, r in enumerate(raw_list):
        if not isinstance(r, dict):
            continue
        r = dict(r)  # local copy — we'll mutate below

        # Assign stable instance ID before anything else.
        iid = _make_runtime_instance_id(r, idx)
        r["runtime_instance_id"] = iid

        sid = str(r.get("strategy_id") or "").strip()
        cls = str(r.get("strategy_class") or "").strip()
        acct_name     = str(r.get("account_name") or "")
        acct_mode_raw = r.get("account_mode") if isinstance(r.get("account_mode"), str) else None
        acct_mode     = _classify_account_mode(acct_name, acct_mode_raw)

        registry_hit = ops.get_strategy(sid) if sid else None

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
        if registry_hit and r.get("enabled") and \
                registry_hit.get("status") not in ("rejected", "archived"):
            pcheck = validate_params(sid, runtime_params)
            # Phase 19: param mismatch is info, not a hard error
            # (do NOT add to errors[] — that would block UI controls)
        else:
            pcheck = {"ok": True, "mismatches": [], "checked": 0}

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
            if r.get("enabled"):
                today = compute_runtime_today_metrics(sid)

        view: Dict[str, Any] = {
            "runtime_instance_id":  iid,
            "strategy_id":          sid or cls.lower(),
            "registry_status":      registry_hit.get("status") if registry_hit else None,
            "paper_state":          paper_state,
            "runtime_detected":     runtime_detected_global,
            "runtime_enabled":      bool(r.get("enabled")),
            "account_name":         acct_name,
            "account_mode":         acct_mode,
            "is_live":              is_live,
            "live_locked":          False,
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
    # bridge is "online" only if heartbeat is fresh (<= 30s)
    bridge_online = bool(heartbeat_age_sec is not None and heartbeat_age_sec <= 30.0)
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
                 "orders.jsonl", "positions.json", "errors.jsonl"):
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
    if view.get("account_mode") not in ("paper", "playback", "demo", "live"):
        raise ops.OpsError(
            f"account_mode={view.get('account_mode')} not allowed for runtime confirm", 403)
    if action == "started":
        if not view.get("params_ok"):
            raise ops.OpsError("PARAM_MISMATCH — fix params in NinjaTrader before confirm", 409)
        states = ops.load_states()
        cur = (states.get(strategy_id) or {}).get("current_state", s["status"])
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

ALLOWED_COMMANDS = ("enable_strategy", "disable_strategy")


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
                   params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Queue a command for the NT bridge (account-agnostic).

    Hard rules:
      * command must be in ALLOWED_COMMANDS
      * account must classify as paper, playback, demo or live (NOT unknown)
      * if strategy_id matches a registry entry → registry archived/rejected
        block applies. Otherwise (any class from the NT Strategies folder)
        we trust the operator and queue the command.
      * runtime_instance_id (when provided) targets the exact strategy
        instance the UI selected; the bridge uses it to disambiguate
        multiple instances of the same class on the same account.
      * params (optional) is a dict of operator-chosen NinjaScript property
        overrides; persisted into the command record so the bridge can apply
        them.
    """
    if command not in ALLOWED_COMMANDS:
        raise ops.OpsError(f"command not allowed: {command}", 400)
    if not strategy_id:
        raise ops.OpsError("strategy_id required", 400)
    s = ops.get_strategy(strategy_id)
    resolved_class = class_name or (s.get("class_name") if s else "")
    if not resolved_class:
        raise ops.OpsError("class_name required (catalog strategy)", 400)
    if s and s.get("status") in ("rejected", "archived"):
        raise ops.OpsError("strategy is archived/rejected — command refused", 403)
    acct_mode = _resolve_account_mode_for_command(account_name)
    if acct_mode == "unknown":
        raise ops.OpsError(
            f"account '{account_name}' could not be classified by name or bridge "
            "telemetry — refusing command for safety", 403)
    try:
        qty = int(quantity)
    except Exception:
        qty = 1
    if qty < 1:
        qty = 1
    now = _now_utc()
    cid = now.strftime("cmd-%Y%m%dT%H%M%S") + f"-{int(now.microsecond/1000):03d}"
    record = {
        "command_id": cid,
        "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": command,
        "strategy_id": strategy_id,
        "strategy_class": resolved_class,
        "instrument": instrument or (s.get("instrument") if s else ""),
        "contract_month": contract_month or (s.get("contract_month") if s else ""),
        "timeframe": timeframe or "",
        "account_name": account_name,
        "quantity": qty,
        "operator": operator,
        "reason": reason or "",
        "params": params or {},
        "runtime_instance_id": runtime_instance_id or "",
        "live_block_passed": True,
    }
    p = _path(COMMANDS_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    try:
        ops.audit_append(
            f"runtime_command:{command}",
            strategy_id,
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

    raw_strats = read_strategies_raw()
    rt_match_raw = _match_runtime_for_command(cmd, raw_strats)
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

    base: Dict[str, Any] = {
        "command_id":       command_id,
        "command":          cmd.get("command"),
        "strategy_id":      cmd.get("strategy_id"),
        "strategy_class":   cmd.get("strategy_class"),
        "account_name":     cmd.get("account_name"),
        "instrument":       cmd.get("instrument"),
        "timeframe":        cmd.get("timeframe"),
        "submitted_at_utc": cmd.get("timestamp_utc"),
        "elapsed_sec":      round(float(elapsed_sec), 2),
        "bridge_result":    bridge_result,
        "runtime_match":    runtime_match,
        "heartbeat":        hb_view,
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
            cmd_kind = str(cmd.get("command") or "")
            if cmd_kind == "enable_strategy":
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
