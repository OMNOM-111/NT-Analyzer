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
PAPER_ACCOUNT_HINTS = ("sim101", "sim ", "playback", "paper", "demo")


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
    """paper | live | playback | unknown."""
    if declared_mode:
        m = str(declared_mode).strip().lower()
        if m in ("paper", "live", "playback"):
            return m
    name = (account_name or "").strip().lower()
    if not name:
        return "unknown"
    if any(h in name for h in PAPER_ACCOUNT_HINTS):
        return "paper" if "playback" not in name else "playback"
    if any(h in name for h in LIVE_ACCOUNT_HINTS):
        return "live"
    return "unknown"


def read_strategies_raw() -> List[Dict[str, Any]]:
    raw = _read_json(_path("strategies.json"), default={})
    if not raw or not isinstance(raw, dict):
        return []
    items = raw.get("strategies") or []
    if not isinstance(items, list):
        return []
    return items


def read_positions() -> Dict[str, Any]:
    raw = _read_json(_path("positions.json"), default={})
    if not isinstance(raw, dict):
        return {}
    return raw


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


def merge_strategy_view(strategy_id: str) -> Dict[str, Any]:
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

    # Live detection — purely informational, never controllable.
    is_live = (account_mode == "live") or (account_mode_raw == "live")
    live_locked = True  # always

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
            warnings.append("Runtime enabled but not confirmed in Control Center")
            mismatch_kind = "runtime_enabled_not_confirmed"
        if (not runtime_enabled) and paper_state == "paper_running":
            warnings.append("Runtime stopped outside Control Center")
            mismatch_kind = "runtime_stopped_outside"

    # Rejected strategies must never be runtime-confirmed
    if s["status"] in ("rejected", "archived") and runtime_enabled:
        errors.append("Rejected/archived strategy is enabled at runtime — DISABLE in NinjaTrader immediately")

    if is_live:
        warnings.append("LIVE account detected — read-only, no controls available")

    today = compute_runtime_today_metrics(strategy_id) if runtime_detected else {}

    can_confirm_runtime: Optional[str] = None
    if mismatch_kind == "runtime_enabled_not_confirmed" and account_mode in ("paper", "playback") \
       and s["status"] not in ("rejected", "archived") and pcheck["ok"]:
        can_confirm_runtime = "started"
    elif mismatch_kind == "runtime_stopped_outside" and account_mode in ("paper", "playback"):
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
    return out


def merge_all_strategies() -> List[Dict[str, Any]]:
    return [merge_strategy_view(s["strategy_id"]) for s in ops.list_strategies()]


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
    if view.get("is_live"):
        raise ops.OpsError("LIVE account detected — runtime confirm forbidden", 403)
    if view.get("account_mode") not in ("paper", "playback"):
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
    return _classify_account_mode(account_name) in ("paper", "playback")


def submit_command(command: str,
                   strategy_id: str,
                   account_name: str,
                   quantity: int = 1,
                   reason: str = "",
                   operator: str = "ui",
                   class_name: str = "",
                   instrument: str = "",
                   contract_month: str = "",
                   params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Queue a paper-only command for the NT bridge.

    Hard rules:
      * command must be in ALLOWED_COMMANDS
      * account must classify as paper or playback (NOT live, NOT unknown)
      * if strategy_id matches a registry entry → registry archived/rejected
        block applies. Otherwise (any class from the NT Strategies folder)
        we trust the operator and queue the command.
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
    if not _is_paper_account(account_name):
        raise ops.OpsError(
            f"account '{account_name}' is not classified as paper/playback — "
            "live account control is forbidden", 403)
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
        "account_name": account_name,
        "quantity": qty,
        "operator": operator,
        "reason": reason or "",
        "params": params or {},
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
    return record


def read_commands(limit: int = 200) -> List[Dict[str, Any]]:
    return _read_jsonl(_path(COMMANDS_FILE), max_lines=limit)


def read_command_results(limit: int = 200) -> List[Dict[str, Any]]:
    return _read_jsonl(_path(COMMAND_RESULTS_FILE), max_lines=limit)
