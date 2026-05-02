"""
NT-Analyzer — Strategy Control Center / Paper Operations module.

Read-only metric calculations, persistent strategy registry, paper-state
machine, and a manual-workflow start/stop intent system. **No live trading
bridge control.** The bridge (NinjaTrader AddOn) only runs historical
backtests; therefore start/stop of a live or paper strategy in NinjaTrader
is exposed as a "manual intent" workflow with audit-log entries — the user
performs the actual enable/disable inside NinjaTrader and confirms it via
POST /api/ops/strategies/{id}/paper/confirm-manual.

Hard safety rules enforced in code:
  1. No transition to `live_running` from any API.
  2. Live-unlock endpoint always returns blocked while
     `live_unlock_token.json` is absent (and that token is not creatable
     from the API at all).
  3. Rejected / archived strategies cannot be armed.
  4. Adjusted PnL is always quantity-aware: gross - RTC * qty.
  5. Every state change is appended to an audit log.

Storage layout under <project_root>/data/ops/ :
  registry.json         — persistent registry of strategies (active+rejected)
  state.json            — current state per strategy_id
  audit_log.jsonl       — append-only audit log
  notes/<strategy>.md   — free-form operator notes (one per strategy)

Journal data is read live from the canonical CSV referenced in registry
(`PAPER_B1_SHORTONLY_DAILY_JOURNAL.csv`).
"""
from __future__ import annotations

import csv
import io
import json
import os
import statistics
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None  # type: ignore

# ---------------------------------------------------------------------------
# Constants — locked Phase 14R/15 baseline
# ---------------------------------------------------------------------------

ROUND_TURN_COMMISSION = 1.90  # USD per round-turn per contract

DAILY_LOSS_LIMIT     = -200.0
WEEKLY_LOSS_LIMIT    = -400.0
TRAILING_DD_LIMIT    = -300.0
CONSEC_LOSING_DAYS   = 4
SLIPPAGE_WARN_TICKS  = 1.5
LOWFREQ_WARN_TRADES  = 10
LOWFREQ_WARN_DAYS    = 90
PAPER_MIN_DAYS       = 60
PAPER_MIN_TRADES     = 25
REVIEW_PASS_PF       = 1.50
REVIEW_PASS_WIN      = 45.0
REVIEW_PASS_DD       = 300.0  # absolute USD
REVIEW_FAIL_PF       = 1.20
REVIEW_FAIL_DD       = 300.0  # absolute USD

ALLOWED_STATES = {
    "archived", "rejected", "paper_ready", "armed", "paper_running",
    "paused", "stopped_today", "risk_blocked", "paper_review_due",
    "paper_passed", "live_locked",
}

# state -> set of allowed next states (driven from ops API only).
# `live_running` is intentionally absent.
TRANSITIONS: Dict[str, set] = {
    "paper_ready":      {"armed"},
    "armed":            {"paper_running", "paper_ready", "stopped_today"},
    "paper_running":    {"stopped_today", "risk_blocked", "paused",
                         "paper_review_due"},
    "paused":           {"armed", "stopped_today"},
    "stopped_today":    {"paper_ready", "armed"},
    "risk_blocked":     {"paper_ready"},  # explicit operator clear
    "paper_review_due": {"paper_passed", "paper_ready"},
    "paper_passed":     {"live_locked"},   # still no live
    "live_locked":      set(),
    "archived":         set(),
    "rejected":         set(),
}

_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    env = os.environ.get("NT_ANALYZER_ROOT")
    if env:
        p = Path(env).resolve()
        if (p / "jobs").exists():
            return p
    return Path(__file__).resolve().parent.parent


def _ops_dir() -> Path:
    d = _project_root() / "data" / "ops"
    d.mkdir(parents=True, exist_ok=True)
    (d / "notes").mkdir(parents=True, exist_ok=True)
    return d


def registry_path() -> Path: return _ops_dir() / "registry.json"
def state_path()    -> Path: return _ops_dir() / "state.json"
def audit_path()    -> Path: return _ops_dir() / "audit_log.jsonl"
def live_unlock_path() -> Path: return _ops_dir() / "live_unlock_token.json"


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def _read_json(p: Path, default: Any) -> Any:
    if not p.is_file():
        return default
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json_atomic(p: Path, obj: Any) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_pt(dt_utc: datetime) -> datetime:
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    if ZoneInfo is not None:
        return dt_utc.astimezone(ZoneInfo("America/Los_Angeles"))
    return dt_utc - timedelta(hours=8)


def _paper_base_dir() -> Path:
    """Find PAPER_B1_SHORTONLY without depending on Cyrillic path literals."""
    root = _project_root().parent
    for p in root.rglob("PAPER_B1_SHORTONLY"):
        if p.is_dir() and (p / "PAPER_B1_SHORTONLY_PROFILE.json").is_file():
            return p
    return root / "PAPER_B1_SHORTONLY"


# ---------------------------------------------------------------------------
# Default registry (seeded if missing)
# ---------------------------------------------------------------------------

def _default_registry() -> Dict[str, Any]:
    base_docs = (_project_root().parent / "РАЗРАБОТКА СТРАТЕГИЙ"
                 / "PAPER_B1_SHORTONLY")
    base_docs = _paper_base_dir()
    return {
        "schema_version": "1.0",
        "generated_at_utc": _now_iso(),
        "strategies": [
            {
                "strategy_id":         "b1_shortonly",
                "display_name":        "B1 ShortOnly",
                "class_name":          "NTAMicroVwapRiskPilot",
                "status":              "paper_ready",
                "account_mode":        "paper",
                "allowed_accounts":    ["Sim101", "Playback101"],
                "instrument":          "MNQ",
                "contract_month":      "MNQ 06-26",
                "locked_params": {
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
                    "IntradayOnly":        True,
                    "StartingCapital":     2000,
                },
                "risk_profile": {
                    "max_daily_loss_usd":   DAILY_LOSS_LIMIT,
                    "max_weekly_loss_usd":  WEEKLY_LOSS_LIMIT,
                    "max_trailing_dd_usd":  TRAILING_DD_LIMIT,
                    "consec_losing_days":   CONSEC_LOSING_DAYS,
                    "user_max_contracts":   5,
                },
                "validation_job_id":     "ui_20260501T185820607Z",
                "validation_summary": {
                    "trades":     92,
                    "adj_net":    2738.30,
                    "adj_pf":     2.49,
                    "adj_dd":    -174.00,
                    "win_pct":    54.35,
                    "quarters":   "8/8",
                    "slip2_adj":  2285.30,
                },
                "paper_profile_path": str(base_docs / "PAPER_B1_SHORTONLY_PROFILE.json"),
                "runbook_path":       str(base_docs / "PAPER_B1_SHORTONLY_RUNBOOK.md"),
                "checklist_path":     str(base_docs / "PAPER_B1_SHORTONLY_CHECKLIST.md"),
                "journal_csv_path":   str(base_docs / "PAPER_B1_SHORTONLY_DAILY_JOURNAL.csv"),
                "journal_xlsx_path":  str(base_docs / "PAPER_B1_SHORTONLY_DAILY_JOURNAL.xlsx"),
                "archive_reason":     "",
                "created_at_utc":     _now_iso(),
                "updated_at_utc":     _now_iso(),
            },
            {
                "strategy_id":  "ntamicroorbpilot",
                "display_name": "NTAMicroOrbPilot (raw ORB)",
                "class_name":   "NTAMicroOrbPilot",
                "status":       "rejected",
                "account_mode": "live_locked",
                "allowed_accounts": [],
                "instrument":   "MNQ",
                "contract_month": "",
                "locked_params": {},
                "risk_profile": {},
                "validation_job_id": "ui_20260501T045202681Z",
                "validation_summary": {"adj_net": -679, "adj_pf": 0.39},
                "paper_profile_path": "",
                "runbook_path":       "",
                "checklist_path":     "",
                "journal_csv_path":   "",
                "journal_xlsx_path":  "",
                "archive_reason": "Phase 14R: negative across every regime n>=5; raw ORB has no edge on MNQ.",
                "created_at_utc": _now_iso(),
                "updated_at_utc": _now_iso(),
            },
            {
                "strategy_id":  "ntamicrovwapgapmirrorpilot",
                "display_name": "NTAMicroVwapGapMirrorPilot",
                "class_name":   "NTAMicroVwapGapMirrorPilot",
                "status":       "rejected",
                "account_mode": "live_locked",
                "allowed_accounts": [],
                "instrument":   "MNQ",
                "contract_month": "",
                "locked_params": {},
                "risk_profile": {},
                "validation_job_id": "",
                "validation_summary": {"adj_net": -111, "adj_pf": 0.87},
                "paper_profile_path": "", "runbook_path": "",
                "checklist_path": "", "journal_csv_path": "", "journal_xlsx_path": "",
                "archive_reason": "Phase 11 retraction + Phase 14R: long mirror does not survive honest fills.",
                "created_at_utc": _now_iso(),
                "updated_at_utc": _now_iso(),
            },
            {
                "strategy_id":  "ntamicrovwapmeanrevertpilot",
                "display_name": "NTAMicroVwapMeanRevertPilot (sym MR v0.1)",
                "class_name":   "NTAMicroVwapMeanRevertPilot",
                "status":       "rejected",
                "account_mode": "live_locked",
                "allowed_accounts": [],
                "instrument":   "MNQ",
                "contract_month": "",
                "locked_params": {},
                "risk_profile": {},
                "validation_job_id": "ui_20260501T194118515Z",
                "validation_summary": {"adj_net": -1225, "adj_pf": 0.0},
                "paper_profile_path": "", "runbook_path": "",
                "checklist_path": "", "journal_csv_path": "", "journal_xlsx_path": "",
                "archive_reason": "Phase 12C verdict + Phase 14R: symmetric MR v0.1 negative across regimes.",
                "created_at_utc": _now_iso(),
                "updated_at_utc": _now_iso(),
            },
        ],
    }


def _default_state(strategy_id: str, status: str) -> Dict[str, Any]:
    return {
        "strategy_id":     strategy_id,
        "current_state":   status,
        "manual_enabled":  False,
        "last_intent":     None,           # {"action": ..., "at_utc": ..., "by": ...}
        "intent_pending":  False,
        "armed_at_utc":    None,
        "running_since_utc": None,
        "stopped_at_utc":  None,
        "last_state_change_utc": _now_iso(),
        "last_review_at_utc": None,
    }


# ---------------------------------------------------------------------------
# Registry / state load
# ---------------------------------------------------------------------------

def load_registry() -> Dict[str, Any]:
    p = registry_path()
    if not p.is_file():
        reg = _default_registry()
        _write_json_atomic(p, reg)
        return reg
    reg = _read_json(p, _default_registry())
    if _repair_registry(reg):
        _write_json_atomic(p, reg)
    return reg


def _repair_registry(reg: Dict[str, Any]) -> bool:
    """Repair persisted paths from older mojibake registry seeds."""
    changed = False
    base_docs = _paper_base_dir()
    b1_paths = {
        "paper_profile_path": base_docs / "PAPER_B1_SHORTONLY_PROFILE.json",
        "runbook_path": base_docs / "PAPER_B1_SHORTONLY_RUNBOOK.md",
        "checklist_path": base_docs / "PAPER_B1_SHORTONLY_CHECKLIST.md",
        "journal_csv_path": base_docs / "PAPER_B1_SHORTONLY_DAILY_JOURNAL.csv",
        "journal_xlsx_path": base_docs / "PAPER_B1_SHORTONLY_DAILY_JOURNAL.xlsx",
    }
    for s in reg.get("strategies", []):
        if s.get("strategy_id") != "b1_shortonly":
            continue
        for key, value in b1_paths.items():
            text = str(value)
            if s.get(key) != text:
                s[key] = text
                changed = True
        if s.get("status") not in ("paper_ready", "paper_running", "armed", "paused", "stopped_today", "paper_review_due"):
            s["status"] = "paper_ready"
            changed = True
        if s.get("account_mode") != "paper":
            s["account_mode"] = "paper"
            changed = True
        rp = s.setdefault("risk_profile", {})
        aliases = {
            "daily_loss_limit": DAILY_LOSS_LIMIT,
            "weekly_loss_limit": WEEKLY_LOSS_LIMIT,
            "trailing_drawdown": TRAILING_DD_LIMIT,
            "consec_losing_days_pause": CONSEC_LOSING_DAYS,
            "median_slippage_warn_ticks": SLIPPAGE_WARN_TICKS,
        }
        for key, value in aliases.items():
            if rp.get(key) != value:
                rp[key] = value
                changed = True
        if changed:
            s["updated_at_utc"] = _now_iso()
    if changed:
        reg["repaired_at_utc"] = _now_iso()
    return changed


def load_states() -> Dict[str, Any]:
    p = state_path()
    reg = load_registry()
    states: Dict[str, Any] = _read_json(p, {})
    changed = False
    for s in reg["strategies"]:
        sid = s["strategy_id"]
        if sid not in states:
            states[sid] = _default_state(sid, s["status"])
            changed = True
    if changed:
        _write_json_atomic(p, states)
    return states


def get_strategy(strategy_id: str) -> Optional[Dict[str, Any]]:
    for s in load_registry()["strategies"]:
        if s["strategy_id"] == strategy_id:
            return s
    return None


def list_strategies() -> List[Dict[str, Any]]:
    reg = load_registry()
    states = load_states()
    out: List[Dict[str, Any]] = []
    for s in reg["strategies"]:
        sid = s["strategy_id"]
        st = states.get(sid, _default_state(sid, s["status"]))
        m = compute_metrics_safe(s)
        out.append({
            "strategy_id":  sid,
            "display_name": s["display_name"],
            "class_name":   s["class_name"],
            "status":       s["status"],
            "current_state": st["current_state"],
            "account_mode": s["account_mode"],
            "instrument":   s["instrument"],
            "contract_month": s.get("contract_month", ""),
            "validation_job_id": s.get("validation_job_id", ""),
            "validation_summary": s.get("validation_summary", {}),
            "archive_reason": s.get("archive_reason", ""),
            "today_adj_pnl": m.get("today_adj_pnl"),
            "cumulative_adj_pnl": m.get("cumulative_adj_pnl"),
            "drawdown":     m.get("current_drawdown"),
            "trades":       m.get("total_trades"),
            "win_pct":      m.get("win_pct"),
            "adj_pf":       m.get("adj_pf"),
            "risk_state":   m.get("risk_state"),
            "last_trade_pt": m.get("last_trade_pt"),
            "color":        _color_for(s["status"], st["current_state"], m),
        })
    return out


def _color_for(reg_status: str, current_state: str, m: Dict[str, Any]) -> str:
    if reg_status in ("archived", "rejected") or current_state in ("archived", "rejected", "live_locked"):
        return "gray"
    if current_state in ("risk_blocked", "paused", "stopped_today") or m.get("risk_state") == "breach":
        return "red"
    if current_state in ("armed", "paper_ready") or m.get("risk_state") == "warning":
        return "yellow"
    return "green"


# ---------------------------------------------------------------------------
# Journal / metrics (quantity-aware)
# ---------------------------------------------------------------------------

def _read_journal_csv(csv_path: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Returns (rows, warnings)."""
    warnings: List[str] = []
    if not csv_path:
        warnings.append("no journal csv configured")
        return [], warnings
    p = Path(csv_path)
    if not p.is_file():
        warnings.append(f"journal csv not found: {csv_path}")
        return [], warnings
    rows: List[Dict[str, Any]] = []
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            for raw in r:
                # Normalize numeric fields
                rec: Dict[str, Any] = dict(raw)
                for k in ("trades_count", "total_qty", "gross_pnl",
                          "daily_win_count", "daily_loss_count",
                          "max_favorable_trade", "max_adverse_trade",
                          "median_slippage_ticks", "max_slippage_ticks",
                          "stop_hit_count", "target_hit_count",
                          "manual_intervention", "platform_error",
                          "data_issue", "rule_violation",
                          "daily_stop_triggered", "weekly_stop_triggered",
                          "trailing_dd_stop_triggered"):
                    v = (rec.get(k) or "").strip()
                    rec[k] = (float(v) if v not in ("", None) else None)
                rows.append(rec)
    except Exception as e:
        warnings.append(f"journal read error: {e}")
    return rows, warnings


def _row_adj_pnl(row: Dict[str, Any]) -> Optional[float]:
    g = row.get("gross_pnl"); q = row.get("total_qty")
    if g is None or q is None:
        return None
    return float(g) - ROUND_TURN_COMMISSION * float(q)


def compute_metrics_safe(strategy: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return compute_metrics(strategy)
    except Exception as e:
        return {"error": f"metrics_failed: {e}", "warnings": [str(e)]}


def compute_metrics(strategy: Dict[str, Any]) -> Dict[str, Any]:
    if strategy.get("status") in ("archived", "rejected"):
        return {"status": strategy["status"], "warnings": [], "trading_days": 0,
                "total_trades": 0, "cumulative_adj_pnl": 0.0,
                "current_drawdown": 0.0, "win_pct": None, "adj_pf": None,
                "risk_state": "n/a"}

    rows, warnings = _read_journal_csv(strategy.get("journal_csv_path", ""))

    # Per-day adjusted pnl in chronological order
    days: List[Dict[str, Any]] = []
    for r in rows:
        adj = _row_adj_pnl(r)
        if adj is None:
            continue
        days.append({"date": r.get("date_pt"), "adj": adj,
                     "trades": int(r.get("trades_count") or 0),
                     "qty": int(r.get("total_qty") or 0),
                     "wins": int(r.get("daily_win_count") or 0),
                     "losses": int(r.get("daily_loss_count") or 0),
                     "median_slip": r.get("median_slippage_ticks")})
    days.sort(key=lambda d: d.get("date") or "")

    cum = 0.0; hwm = 0.0; dd = 0.0; max_dd = 0.0
    cum_series = []
    for d in days:
        cum += d["adj"]
        if cum > hwm: hwm = cum
        cd = cum - hwm
        if cd < dd: dd = cd  # trailing min
        if cd < max_dd: max_dd = cd
        cum_series.append({"date": d["date"], "cum": cum, "dd": cd})

    total_trades = sum(d["trades"] for d in days)
    pos_days = [d for d in days if d["adj"] > 0]
    neg_days = [d for d in days if d["adj"] < 0]
    gp = sum(d["adj"] for d in pos_days)
    gl = sum(d["adj"] for d in neg_days)
    adj_pf = (gp / abs(gl)) if gl < 0 else (None if gp == 0 else float("inf"))
    win_pct = (100.0 * len(pos_days) / len(days)) if days else None
    avg_trade = (cum / total_trades) if total_trades > 0 else None

    today_pt_date = _to_pt(datetime.now(timezone.utc)).date().isoformat()
    today = next((d for d in days if d["date"] == today_pt_date), None)
    today_adj = today["adj"] if today else None

    # weekly: last 5 trading days adj sum
    week_adj = sum(d["adj"] for d in days[-5:]) if days else 0.0

    # consec losing days
    cl = 0
    for d in reversed(days):
        if d["adj"] < 0: cl += 1
        else: break

    # slippage
    slips = [d["median_slip"] for d in days if d["median_slip"] is not None]
    median_slip = statistics.median(slips) if slips else None
    max_slip = max(slips) if slips else None

    last_trade_pt = None
    for d in reversed(days):
        if d["trades"] > 0:
            last_trade_pt = d["date"]
            break

    days_since_last = None
    if last_trade_pt:
        try:
            ld = datetime.fromisoformat(last_trade_pt).date()
            today_d = _to_pt(datetime.now(timezone.utc)).date()
            days_since_last = (today_d - ld).days
        except Exception:
            pass

    # Risk state
    risk_state = "ok"; risk_reasons: List[str] = []
    if today_adj is not None and today_adj <= DAILY_LOSS_LIMIT:
        risk_state = "breach"; risk_reasons.append("daily loss limit hit")
    if week_adj <= WEEKLY_LOSS_LIMIT:
        risk_state = "breach"; risk_reasons.append("weekly loss limit hit")
    if dd <= TRAILING_DD_LIMIT:
        risk_state = "breach"; risk_reasons.append("trailing DD limit hit")
    if cl >= CONSEC_LOSING_DAYS:
        risk_state = "breach"; risk_reasons.append(f"{cl} consecutive losing days")
    if median_slip is not None and median_slip > SLIPPAGE_WARN_TICKS and risk_state != "breach":
        risk_state = "warning"; risk_reasons.append("median slippage > 1.5 ticks")
    if (len(days) >= LOWFREQ_WARN_DAYS and total_trades < LOWFREQ_WARN_TRADES
            and risk_state != "breach"):
        risk_state = "warning"; risk_reasons.append("low frequency: <10 trades after 90 days")

    progress = {
        "trading_days_completed": len(days),
        "trading_days_target":    PAPER_MIN_DAYS,
        "trades_completed":       total_trades,
        "trades_target":          PAPER_MIN_TRADES,
        "review_due":             (len(days) >= PAPER_MIN_DAYS
                                    and total_trades >= PAPER_MIN_TRADES),
    }

    review = _evaluate_review(adj_pf, win_pct, max_dd, len(days), total_trades)

    return {
        "warnings":            warnings,
        "trading_days":        len(days),
        "total_trades":        total_trades,
        "cumulative_adj_pnl":  round(cum, 2),
        "high_water_mark":     round(hwm, 2),
        "current_drawdown":    round(dd, 2),
        "max_drawdown":        round(max_dd, 2),
        "today_adj_pnl":       (None if today_adj is None else round(today_adj, 2)),
        "weekly_adj_pnl":      round(week_adj, 2),
        "win_pct":             (None if win_pct is None else round(win_pct, 2)),
        "adj_pf":              (None if adj_pf in (None, float("inf")) else round(adj_pf, 2)),
        "avg_trade":           (None if avg_trade is None else round(avg_trade, 2)),
        "median_slippage_ticks": median_slip,
        "max_slippage_ticks":  max_slip,
        "active_days":         sum(1 for d in days if d["trades"] > 0),
        "trades_since_start":  total_trades,
        "days_since_last_trade": days_since_last,
        "consec_losing_days":  cl,
        "last_trade_pt":       last_trade_pt,
        "risk_state":          risk_state,
        "risk_reasons":        risk_reasons,
        "progress":            progress,
        "review":              review,
        "equity_curve":        cum_series,
    }


def _evaluate_review(pf: Optional[float], win: Optional[float],
                     max_dd: float, days: int, trades: int) -> Dict[str, Any]:
    abs_dd = abs(max_dd)
    pass_ok = (
        pf is not None and pf >= REVIEW_PASS_PF
        and win is not None and win >= REVIEW_PASS_WIN
        and abs_dd <= REVIEW_PASS_DD
        and days >= PAPER_MIN_DAYS and trades >= PAPER_MIN_TRADES
    )
    fail = (
        (pf is not None and pf < REVIEW_FAIL_PF)
        or abs_dd > REVIEW_FAIL_DD
        or (days >= LOWFREQ_WARN_DAYS and trades < LOWFREQ_WARN_TRADES)
    )
    if pass_ok:
        verdict = "pass"
    elif fail:
        verdict = "fail"
    elif days >= PAPER_MIN_DAYS and trades >= PAPER_MIN_TRADES:
        verdict = "review_due"
    else:
        verdict = "in_progress"
    return {
        "verdict": verdict,
        "thresholds": {
            "pass_pf": REVIEW_PASS_PF, "pass_win": REVIEW_PASS_WIN,
            "pass_dd": REVIEW_PASS_DD, "fail_pf": REVIEW_FAIL_PF,
            "fail_dd": REVIEW_FAIL_DD,
        },
    }


# ---------------------------------------------------------------------------
# Trades / journal accessors
# ---------------------------------------------------------------------------

def get_trades(strategy_id: str) -> Dict[str, Any]:
    """Read trades.json from the validation_job_id (read-only)."""
    s = get_strategy(strategy_id)
    if not s:
        return {"error": "not_found", "trades": []}
    job_id = s.get("validation_job_id") or ""
    if not job_id:
        return {"trades": [], "warnings": ["no validation_job_id"]}
    pr = _project_root()
    candidate = pr / "jobs" / "done" / job_id / "trades.json"
    if not candidate.is_file():
        return {"trades": [], "warnings": [f"trades.json not found at {candidate}"]}
    try:
        with candidate.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        return {"trades": [], "warnings": [f"trades.json read error: {e}"]}

    out: List[Dict[str, Any]] = []
    for t in raw[:5000]:
        q = float(t.get("quantity") or 0)
        gross = float(t.get("pnl_currency") or 0)
        adj = gross - ROUND_TURN_COMMISSION * q
        et = t.get("entry_time_utc"); xt = t.get("exit_time_utc")
        try: et_pt = _to_pt(datetime.fromisoformat(et.replace("Z", "+00:00"))).isoformat() if et else ""
        except Exception: et_pt = et or ""
        try: xt_pt = _to_pt(datetime.fromisoformat(xt.replace("Z", "+00:00"))).isoformat() if xt else ""
        except Exception: xt_pt = xt or ""
        out.append({
            "trade_no": t.get("trade_no"),
            "direction": t.get("direction"),
            "entry_pt": et_pt, "exit_pt": xt_pt,
            "entry_price": t.get("entry_price"), "exit_price": t.get("exit_price"),
            "quantity": q, "gross_pnl": gross,
            "commission_est": ROUND_TURN_COMMISSION * q,
            "adjusted_pnl": round(adj, 2),
        })
    return {"trades": out, "count": len(out), "source_job_id": job_id}


def get_journal(strategy_id: str) -> Dict[str, Any]:
    s = get_strategy(strategy_id)
    if not s:
        return {"error": "not_found", "rows": []}
    rows, warnings = _read_journal_csv(s.get("journal_csv_path", ""))
    # add adjusted_pnl per row
    enriched = []
    for r in rows:
        adj = _row_adj_pnl(r)
        rr = dict(r); rr["adjusted_pnl"] = (round(adj, 2) if adj is not None else None)
        enriched.append(rr)
    csv_p = s.get("journal_csv_path", "")
    cols: List[str] = []
    if rows:
        # collect ordered union
        seen: List[str] = []
        for r in rows:
            for k in r.keys():
                if k not in seen:
                    seen.append(k)
        cols = seen
    return {"rows": enriched, "count": len(enriched), "warnings": warnings,
            "csv_path": csv_p, "path": csv_p,
            "exists": bool(csv_p) and Path(csv_p).is_file(),
            "columns": cols,
            "xlsx_path": s.get("journal_xlsx_path", "")}


def append_journal_day(strategy_id: str, row: Dict[str, Any]) -> Dict[str, Any]:
    s = get_strategy(strategy_id)
    if not s:
        return {"ok": False, "error": "not_found"}
    csv_path = s.get("journal_csv_path") or ""
    if not csv_path:
        return {"ok": False, "error": "no_csv_path"}
    p = Path(csv_path)
    if not p.is_file():
        return {"ok": False, "error": f"csv missing: {csv_path}"}
    # read header from existing file
    with p.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
    if not header:
        return {"ok": False, "error": "csv has no header"}
    ordered = [str(row.get(h, "")) for h in header]
    with p.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(ordered)
    audit_append("journal/day", strategy_id, "n/a", "n/a",
                 reason=f"appended row date_pt={row.get('date_pt','')}")
    return {"ok": True, "appended_columns": header}


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def audit_append(action: str, strategy_id: str, prev: str, new: str,
                 *, by: str = "operator", reason: str = "",
                 account_mode: str = "") -> Dict[str, Any]:
    ts = _now_iso()
    entry = {
        "ts_utc":      ts,
        "timestamp_utc": ts,
        "action":      action,
        "strategy_id": strategy_id,
        "prev_state":  prev,
        "from_status": prev,
        "new_state":   new,
        "to_status":   new,
        "by":          by,
        "reason":      reason,
        "account_mode": account_mode,
    }
    with _LOCK:
        with audit_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_audit_log(limit: int = 200,
                   strategy_id: Optional[str] = None) -> List[Dict[str, Any]]:
    p = audit_path()
    if not p.is_file():
        return []
    out: List[Dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try: ent = json.loads(line)
            except Exception: continue
            if strategy_id and ent.get("strategy_id") != strategy_id: continue
            out.append(ent)
    return out[-limit:][::-1]


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def _note_path(strategy_id: str) -> Path:
    return _ops_dir() / "notes" / f"{strategy_id}.md"


def get_notes(strategy_id: str) -> Dict[str, Any]:
    p = _note_path(strategy_id)
    if not p.is_file():
        return {"strategy_id": strategy_id, "notes": ""}
    return {"strategy_id": strategy_id, "notes": p.read_text(encoding="utf-8")}


def append_note(strategy_id: str, text: str, by: str = "operator") -> Dict[str, Any]:
    if not text or not text.strip():
        return {"ok": False, "error": "empty_note"}
    p = _note_path(strategy_id)
    line = f"\n\n## {_now_iso()} — {by}\n\n{text.strip()}\n"
    with p.open("a", encoding="utf-8") as f:
        f.write(line)
    audit_append("notes/append", strategy_id, "n/a", "n/a", by=by,
                 reason=f"note len={len(text)}")
    return {"ok": True}


# ---------------------------------------------------------------------------
# State machine / paper workflow
# ---------------------------------------------------------------------------

class OpsError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg); self.status = status


def _save_states(states: Dict[str, Any]) -> None:
    _write_json_atomic(state_path(), states)


def _transition(strategy_id: str, new_state: str, *, reason: str,
                allow_rejected: bool = False) -> Dict[str, Any]:
    s = get_strategy(strategy_id)
    if not s:
        raise OpsError("strategy not found", 404)
    if not allow_rejected and s["status"] in ("archived", "rejected"):
        raise OpsError(f"strategy is {s['status']}; cannot transition", 403)
    if new_state not in ALLOWED_STATES:
        raise OpsError(f"unknown state: {new_state}", 400)
    states = load_states()
    st = states.setdefault(strategy_id, _default_state(strategy_id, s["status"]))
    cur = st["current_state"]
    if cur == new_state:
        return st
    allowed = TRANSITIONS.get(cur, set())
    if new_state not in allowed:
        raise OpsError(f"transition {cur} -> {new_state} not allowed", 409)
    st["current_state"] = new_state
    st["last_state_change_utc"] = _now_iso()
    if new_state == "armed":
        st["armed_at_utc"] = _now_iso(); st["intent_pending"] = True
    elif new_state == "paper_running":
        st["running_since_utc"] = _now_iso(); st["intent_pending"] = False
        st["manual_enabled"] = True
    elif new_state in ("stopped_today", "paused", "risk_blocked", "paper_review_due"):
        st["stopped_at_utc"] = _now_iso(); st["manual_enabled"] = False
        st["intent_pending"] = False
    _save_states(states)
    audit_append(f"transition/{new_state}", strategy_id, cur, new_state,
                 reason=reason, account_mode=s["account_mode"])
    return st


def arm(strategy_id: str, reason: str = "") -> Dict[str, Any]:
    s = get_strategy(strategy_id)
    if not s: raise OpsError("not found", 404)
    if s["status"] in ("archived", "rejected"):
        raise OpsError("rejected/archived strategies cannot be armed", 403)
    if s["account_mode"] not in ("paper", "sim"):
        raise OpsError(f"account_mode={s['account_mode']} forbidden for arm", 403)
    return _transition(strategy_id, "armed", reason=reason or "operator arm")


def start_intent(strategy_id: str, reason: str = "") -> Dict[str, Any]:
    """Records the operator's intent to start the strategy in NinjaTrader.
    Does NOT enable anything in NinjaTrader. Returns a manual checklist."""
    s = get_strategy(strategy_id)
    if not s: raise OpsError("not found", 404)
    if s["status"] in ("archived", "rejected"):
        raise OpsError("rejected/archived strategies cannot be started", 403)
    if s["account_mode"] == "live_locked":
        raise OpsError("live trading is locked", 403)
    states = load_states()
    st = states.setdefault(strategy_id, _default_state(strategy_id, s["status"]))
    if st["current_state"] not in ("armed",):
        raise OpsError(f"start-intent requires state=armed, current={st['current_state']}", 409)
    st["last_intent"] = {"action": "start", "at_utc": _now_iso(),
                         "reason": reason, "by": "operator"}
    st["intent_pending"] = True
    _save_states(states)
    audit_append("intent/start", strategy_id, st["current_state"], "armed",
                 reason=reason or "operator start intent",
                 account_mode=s["account_mode"])
    return {
        "ok": True,
        "intent": "start",
        "manual_checklist": _start_checklist(s),
        "next_action": "POST /api/ops/strategies/{id}/paper/confirm-manual "
                       "with body {\"action\":\"started\"} after enabling in NinjaTrader.",
    }


def confirm_manual(strategy_id: str, action: str, reason: str = "") -> Dict[str, Any]:
    if action not in ("started", "stopped"):
        raise OpsError("action must be 'started' or 'stopped'", 400)
    if action == "started":
        st = _transition(strategy_id, "paper_running", reason=reason or "manual start confirmed")
    else:
        st = _transition(strategy_id, "stopped_today", reason=reason or "manual stop confirmed")
    return {"ok": True, "state": st["current_state"]}


def stop_intent(strategy_id: str, reason: str = "") -> Dict[str, Any]:
    s = get_strategy(strategy_id)
    if not s: raise OpsError("not found", 404)
    states = load_states()
    st = states.setdefault(strategy_id, _default_state(strategy_id, s["status"]))
    if st["current_state"] not in ("paper_running", "paused", "armed"):
        raise OpsError(f"stop-intent invalid for state={st['current_state']}", 409)
    st["last_intent"] = {"action": "stop", "at_utc": _now_iso(),
                         "reason": reason, "by": "operator"}
    st["intent_pending"] = True
    _save_states(states)
    audit_append("intent/stop", strategy_id, st["current_state"], st["current_state"],
                 reason=reason or "operator stop intent",
                 account_mode=s["account_mode"])
    return {
        "ok": True,
        "intent": "stop",
        "manual_checklist": _stop_checklist(s),
        "next_action": "POST /api/ops/strategies/{id}/paper/confirm-manual "
                       "with body {\"action\":\"stopped\"} after disabling in NinjaTrader.",
    }


def pause(strategy_id: str, reason: str = "") -> Dict[str, Any]:
    return _transition(strategy_id, "paused", reason=reason or "operator pause")


def resume(strategy_id: str, reason: str = "") -> Dict[str, Any]:
    return _transition(strategy_id, "armed", reason=reason or "operator resume")


def stop_today(strategy_id: str, reason: str = "") -> Dict[str, Any]:
    return _transition(strategy_id, "stopped_today",
                       reason=reason or "operator stop_today")


def mark_paper_passed(strategy_id: str, reason: str = "") -> Dict[str, Any]:
    return _transition(strategy_id, "paper_passed",
                       reason=reason or "operator review pass")


def evaluate_review_due(strategy_id: str) -> Dict[str, Any]:
    """Auto-transition from paper_running -> paper_review_due when gates met."""
    s = get_strategy(strategy_id)
    if not s: raise OpsError("not found", 404)
    states = load_states()
    st = states.get(strategy_id) or _default_state(strategy_id, s["status"])
    if st["current_state"] != "paper_running":
        return {"transitioned": False, "current_state": st["current_state"]}
    m = compute_metrics_safe(s)
    p = m.get("progress") or {}
    if p.get("review_due"):
        st = _transition(strategy_id, "paper_review_due",
                         reason="auto: trading_days>=60 AND trades>=25")
        return {"transitioned": True, "current_state": st["current_state"]}
    return {"transitioned": False, "current_state": st["current_state"]}


def _start_checklist(s: Dict[str, Any]) -> List[str]:
    return [
        f"Open NinjaTrader 8 -> Strategies tab",
        f"Verify no live position open. Account = paper/sim only ({', '.join(s.get('allowed_accounts') or [])}).",
        f"Load strategy {s['class_name']} with template B1_ShortOnly_locked_v14R.",
        "Confirm every locked parameter matches PAPER_B1_SHORTONLY_PROFILE.json.",
        "Set Strategy state = Enabled.",
        "Verify the trading window 06:35-07:00 PT is current or upcoming.",
        "Confirm via POST /api/ops/strategies/{id}/paper/confirm-manual {\"action\":\"started\"}.",
    ]


def _stop_checklist(s: Dict[str, Any]) -> List[str]:
    return [
        "Open NinjaTrader 8 -> Strategies tab",
        f"Disable strategy {s['class_name']}.",
        "Verify all working orders are cancelled.",
        "Verify no open position remains (intraday strategy auto-flattens at close).",
        "Confirm via POST /api/ops/strategies/{id}/paper/confirm-manual {\"action\":\"stopped\"}.",
    ]


# ---------------------------------------------------------------------------
# Live lock
# ---------------------------------------------------------------------------

def live_lock_status() -> Dict[str, Any]:
    p = live_unlock_path()
    blocked_until = "paper-review passed AND manual unlock token written by user"
    return {
        "live_locked": True,  # phase 16: always locked
        "live_unlock_token_present": p.is_file(),
        "blocked_reason": "live trading is forbidden until paper-review passes",
        "blocked_until": blocked_until,
        "policy": "Phase 16 hard rule: no API path enables live trading.",
    }


def request_live_unlock(reason: str = "") -> Dict[str, Any]:
    audit_append("live/unlock-request", "*", "live_locked", "live_locked",
                 reason=reason or "operator requested live unlock")
    return {
        "ok": False,
        "live_unlock_granted": False,
        "blocked": True,
        "reason": "blocked until paper-review passed (Phase 16 hard rule)",
    }
