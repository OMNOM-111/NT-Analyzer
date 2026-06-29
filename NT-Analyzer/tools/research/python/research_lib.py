"""Shared helpers for session-edge research scripts.

Pure-Python, stdlib-only. Imports the NT-Analyzer project root by walking up
from this file. Talks to the backend over HTTP.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA = PROJECT_ROOT / "data"
BASE = "http://127.0.0.1:8765"


def _load_runtime_defaults() -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "starting_capital": 2000.0,
        "max_drawdown_pct": 0.15,
        "round_turn_commission": 1.90,
        "slippage_ticks": 1,
        "intraday_only": True,
        "order_fill_resolution": "High",
    }
    path = DATA / "governance" / "laws.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return defaults
    laws = payload.get("laws") if isinstance(payload, dict) else None
    if not isinstance(laws, list):
        return defaults
    by_key = {
        str(row.get("key") or ""): row
        for row in laws
        if isinstance(row, dict)
    }

    def law_value(key: str, fallback: Any) -> Any:
        row = by_key.get(key)
        return row.get("value") if isinstance(row, dict) and "value" in row else fallback

    defaults["starting_capital"] = float(law_value("starting_capital_usd", defaults["starting_capital"]))
    defaults["max_drawdown_pct"] = float(law_value("max_drawdown_pct", 15.0)) / 100.0
    defaults["round_turn_commission"] = float(law_value("round_turn_commission_floor_usd", defaults["round_turn_commission"]))
    defaults["slippage_ticks"] = int(law_value("slippage_ticks_floor", defaults["slippage_ticks"]))
    defaults["intraday_only"] = bool(law_value("intraday_only_default", defaults["intraday_only"]))
    defaults["order_fill_resolution"] = str(law_value("order_fill_resolution", defaults["order_fill_resolution"]))
    return defaults


RUNTIME_DEFAULTS = _load_runtime_defaults()


def _resolve_jobs_path(raw: Any) -> Optional[Path]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    p = Path(raw.strip()).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p.resolve()


def jobs_root() -> Path:
    env = os.environ.get("NT_ANALYZER_JOBS_DIR") or os.environ.get("NTA_JOBS_DIR")
    p = _resolve_jobs_path(env)
    if p is not None:
        return p

    cfg_env = os.environ.get("NT_ANALYZER_BRIDGE_CONFIG")
    if cfg_env:
        cfg_path = Path(cfg_env).expanduser()
    else:
        user_profile = Path(os.environ.get("USERPROFILE") or Path.home())
        cfg_path = user_profile / "Documents" / "NinjaTrader 8" / "bin" / "Custom" / "NTAnalyzerBridge.config.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return PROJECT_ROOT / "jobs"
    if not isinstance(cfg, dict):
        return PROJECT_ROOT / "jobs"
    cfg_project = cfg.get("project_root")
    if isinstance(cfg_project, str) and cfg_project.strip():
        try:
            if Path(cfg_project).expanduser().resolve() != PROJECT_ROOT.resolve():
                return PROJECT_ROOT / "jobs"
        except OSError:
            return PROJECT_ROOT / "jobs"
    return _resolve_jobs_path(cfg.get("jobs_dir")) or (PROJECT_ROOT / "jobs")


# ---------------------------------------------------------------------------
# Per-root reference data
# ---------------------------------------------------------------------------

# PROJECT BACKTEST ASSUMPTION — NOT an external prop-firm or broker fee schedule.
# These are the round-turn USD costs the NinjaTrader-side cost model uses for
# research backtests in this project (commission + exchange + NFA + clearing,
# rounded UP — over-charging is honest, under-charging is dishonest). They are
# *not* tied to local micro group, which in this project is only a local instrument
# playlist (the "Micros" group in data/catalog/instrument_groups.json), not a
# fee/margin/reset model.
ROUND_TURN_FEES: Dict[str, float] = {
    "MES": 1.04, "MNQ": 1.04, "MYM": 1.04, "M2K": 1.04,
    "MGC": 1.50, "MHG": 1.50, "SIL": 1.50,
    "MCL": 1.50, "MNG": 1.50,
    "M6A": 1.04, "M6B": 1.04, "M6E": 1.04,
    "MBT": 2.84, "MET": 0.94,
}

# Backend currently requires RoundTurnCommission >= project floor.
RTC_FLOOR = float(RUNTIME_DEFAULTS["round_turn_commission"])
SLIPPAGE_FLOOR = int(RUNTIME_DEFAULTS["slippage_ticks"])
DEFAULT_STARTING_CAPITAL = float(RUNTIME_DEFAULTS["starting_capital"])
MAX_DRAWDOWN_BUDGET_PCT = float(RUNTIME_DEFAULTS["max_drawdown_pct"])


def fee_for(root: str) -> float:
    """Honest fee = max(actual, backend floor)."""
    return max(ROUND_TURN_FEES.get(root, RTC_FLOOR), RTC_FLOOR)


def fee_stress(root: str) -> float:
    """Stress fee = actual * 1.25, never below floor+0.50."""
    return max(ROUND_TURN_FEES.get(root, RTC_FLOOR) * 1.25, RTC_FLOOR + 0.50)


# PROJECT BACKTEST ASSUMPTION — Active intraday margin per micro contract,
# USD. Used to set ActiveMarginPerContract so the strategy's position-sizing
# logic permits at least one contract from a $2000 StartingCapital. Not a
# broker margin schedule — a project-level conservative input.
ACTIVE_MARGIN: Dict[str, float] = {
    "MES": 50.0,  "MNQ": 100.0, "MYM": 50.0,  "M2K": 50.0,
    "MGC": 200.0, "MHG": 200.0, "SIL": 1000.0,
    "MCL": 100.0, "MNG": 100.0,
    "M6A": 50.0,  "M6B": 50.0,  "M6E": 50.0,
    "MBT": 100.0, "MET": 50.0,
}


def margin_for(root: str) -> float:
    return ACTIVE_MARGIN.get(root, 100.0)


def base_risk_params(root: str) -> Dict[str, Any]:
    """Risk-shell params that mirror the locked Pilot profile.

    Always set together to satisfy NTAMicroVwapRiskExplorer's position-sizing
    guard (which refuses to trade if MaxContractsByCapital == 0 or
    InstrumentStatus != "allowed"). Strategy-class agnostic — these names are
    common across the Pilot and Explorer forks.
    """
    return {
        "StartingCapital": DEFAULT_STARTING_CAPITAL,
        "IntradayOnly": bool(RUNTIME_DEFAULTS["intraday_only"]),
        "ActiveMarginPerContract": margin_for(root),
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "MaxDailyLossPct": 2.0,
        "MaxDailyProfitPct": 4.0,
        "MaxTradesPerDay": 4,
        "MaxConsecutiveLosses": 3,
        "UserMaxContracts": 5,
        "RoundTurnCommission": fee_for(root),
        "SlippageTicks": SLIPPAGE_FLOOR,
        # Indicator periods (Pilot defaults).
        "EmaFastPeriod": 50,
        "EmaSlowPeriod": 200,
        "AtrPeriod": 14,
        "AdxPeriod": 14,
        "VolumeSmaPeriod": 20,
        "AtrStopMult": 0.75,
        "MoveToBreakevenAtR": 0.8,
        "TrailAfterR": 1.2,
        "UseSecondTradeWindow": False,
        "SecondTradeStartTime": 1030,
        "SecondTradeEndTime": 1200,
        "UseDailyBiasFilter": False,
    }


# Root → TradingHours template mapping. Bridge uses TradingHours.Get(name) and
# fail-fasts if NT cannot resolve. Names are exactly as they appear in
# NinjaTrader 8\templates\TradingHours\*.xml.
SESSION_TEMPLATE_BY_ROOT: Dict[str, str] = {
    # CME index micros — only fully validated template.
    "MES": "CME US Index Futures RTH",
    "MYM": "CME US Index Futures RTH",
    "M2K": "CME US Index Futures RTH",
    "MNQ": "CME US Index Futures RTH",
    # COMEX metals.
    "MGC": "Nymex Metals RTH1",
    "SIL": "Nymex Metals RTH1",
    "MHG": "Nymex Metals RTH1",
    # NYMEX energy.
    "MCL": "Nymex Energy RTH",
    "MNG": "Nymex Energy RTH",
    # CME FX micros.
    "M6A": "CME FX Futures RTH",
    "M6B": "CME FX Futures RTH",
    "M6E": "CME FX Futures RTH",
    # Crypto — 24/7-ish.
    "MBT": "Cryptocurrency",
    "MET": "Cryptocurrency",
}


def session_for(root: str) -> str:
    return SESSION_TEMPLATE_BY_ROOT.get(root, "CME US Index Futures RTH")


# ---------------------------------------------------------------------------
# Contract resolver
# ---------------------------------------------------------------------------

def load_instruments() -> List[Dict[str, Any]]:
    p = DATA / "catalog" / "instruments.json"
    return json.loads(p.read_text(encoding="utf-8"))["instruments"]


def resolve_front_contract(root: str, prefer_after: str = "2026-04-01") -> Dict[str, Any]:
    """Pick the most useful contract symbol for `root`.

    Strategy (fixed 2026-05-05 — earlier version was picking *expired* fronts
    by maximizing data_first instead of data_last):
      1. Among contracts with has_minute_data, take the one with the *latest*
         data_last — that is the contract that is still receiving live bars
         and is therefore the actively-traded front. `prefer_after` is now a
         freshness sanity floor, not a tiebreaker for length-of-history.
      2. If no contract has data_last >= prefer_after, the root has no recent
         data — return the latest-data contract anyway with a `stale=True`
         flag, so the caller can decide.
      3. If no minute data at all, return {skip_reason: ...}.
    """
    rows = [r for r in load_instruments() if r.get("root") == root and r.get("has_minute_data")]
    if not rows:
        return {"root": root, "skip_reason": "no minute data in catalog"}
    rows_sorted = sorted(rows, key=lambda r: r.get("data_last") or "")
    chosen = rows_sorted[-1]
    stale = (chosen.get("data_last") or "") < prefer_after
    return {
        "root": root,
        "instrument": chosen["instrument"],
        "data_first": chosen.get("data_first"),
        "data_last": chosen.get("data_last"),
        "tick_size": chosen.get("tick_size"),
        "tick_value": chosen.get("tick_value"),
        "point_value": chosen.get("point_value"),
        "exchange": chosen.get("exchange"),
        "stale": stale,
    }


def resolve_many(roots: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    return {r: resolve_front_contract(r) for r in roots}


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib, no requests dep)
# ---------------------------------------------------------------------------

def _http(method: str, path: str, body: Optional[Dict[str, Any]] = None,
          timeout: int = 30) -> Tuple[int, Dict[str, Any]]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    last_error = None
    for attempt in range(3):
        req = urllib.request.Request(
            url=BASE + path, data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8")
                return r.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, {"_raw": raw}
        except (http.client.RemoteDisconnected, urllib.error.URLError, TimeoutError) as e:
            last_error = e
            if attempt < 2:
                time.sleep(1 + attempt)
                continue
    return 599, {"error": str(last_error) if last_error else "request failed"}


def get(path: str) -> Tuple[int, Dict[str, Any]]:
    return _http("GET", path)


def post(path: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    return _http("POST", path, body)


# ---------------------------------------------------------------------------
# Job / batch builders
# ---------------------------------------------------------------------------

def build_job_body(*, class_name: str, instrument: str, params: Dict[str, Any],
                   from_utc: str, to_utc: str,
                   bars_period_type: str = "Minute", bars_period_value: int = 5,
                   slippage_ticks: int = 1, role: str = "research",
                   session_template: Optional[str] = None,
                   risk_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    root = instrument.split()[0]
    if session_template is None:
        session_template = session_for(root)
    rtc = float(params.get("RoundTurnCommission") or fee_for(root))
    p = dict(params)
    p["RoundTurnCommission"] = rtc
    return {
        "class_name": class_name,
        "instrument": instrument,
        "bars_period_type": bars_period_type,
        "bars_period_value": bars_period_value,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "parameters": p,
        "calculate": "OnBarClose",
        "is_tick_replay": False,
        "order_fill_resolution": "High",
        "slippage_ticks": slippage_ticks,
        "commission": 0.0,
        "commission_template": "None",
        "session_template": session_template,
        "timezone": "UTC",
        "role": role,
        "risk_profile": risk_profile or {"starting_capital": DEFAULT_STARTING_CAPITAL,
                                         "max_position_size": 1,
                                         "fitness": "AdjustedNetProfit"},
    }


def build_risk_profile_for(roots_or_instruments: List[str]) -> Dict[str, Any]:
    """Build a populated risk_profile so backend's _inject_risk_profile_parameters
    writes correct ActiveMarginPerContract / MaxContractsByCapital /
    InstrumentStatus into strategy params (otherwise they get zeroed and the
    Explorer strategy refuses to trade).
    """
    starting_capital = DEFAULT_STARTING_CAPITAL
    inst_margins: Dict[str, Any] = {}
    for raw in roots_or_instruments:
        root = raw.split()[0]
        m = margin_for(root)
        max_c = max(1, int(starting_capital // m)) if m > 0 else 0
        inst_margins[raw] = {
            "root": root,
            "margin_type": "intraday",
            "margin_per_contract": m,
            "max_contracts_by_capital": max_c,
            "status": "allowed",
        }
    return {
        "schema_version": "0.1",
        "mode": "informational",
        "currency": "USD",
        "starting_capital": starting_capital,
        "intraday_only": bool(RUNTIME_DEFAULTS["intraday_only"]),
        "margin_source": {"broker": "NinjaTrader",
                          "source": "research_lib.ACTIVE_MARGIN",
                          "fetched_at_utc": utcnow_iso()},
        "instrument_margins": inst_margins,
        "status": "informational_only",
        "status_text": "Synthetic informational profile (research lib).",
    }


def submit_batch(*, name: str, class_name: str, instruments: List[str],
                 params: Dict[str, Any], from_utc: str, to_utc: str,
                 bars_period_type: str = "Minute", bars_period_value: int = 5,
                 slippage_ticks: int = 1, role: str = "research",
                 session_template: Optional[str] = None,
                 risk_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Submit one /api/batches request. All instruments share one session_template
    (use one batch per product family).
    """
    if session_template is None:
        # Infer from first instrument's root.
        session_template = session_for(instruments[0].split()[0])
    rtc = float(params.get("RoundTurnCommission")
                or fee_for(instruments[0].split()[0]))
    p = dict(params)
    p["RoundTurnCommission"] = rtc
    body = {
        "name": name,
        "class_name": class_name,
        "instruments": instruments,
        "bars_period_type": bars_period_type,
        "bars_period_value": bars_period_value,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "parameters": p,
        "calculate": "OnBarClose",
        "is_tick_replay": False,
        "order_fill_resolution": "High",
        "slippage_ticks": slippage_ticks,
        "commission": 0.0,
        "commission_template": "None",
        "session_template": session_template,
        "timezone": "UTC",
        "role": role,
        "risk_profile": risk_profile or build_risk_profile_for(instruments),
    }
    code, resp = post("/api/batches", body)
    return {"code": code, "request": body, "response": resp}


# ---------------------------------------------------------------------------
# Polling + collection
# ---------------------------------------------------------------------------

def poll_batch(batch_id: str, timeout_s: int = 1800,
               interval_s: int = 5) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        code, resp = get(f"/api/batches/{batch_id}")
        if code == 200:
            counts = resp.get("counts", {})
            pending = counts.get("pending", 0) + counts.get("running", 0)
            if pending == 0:
                return resp
            last = resp
        time.sleep(interval_s)
    return last or {}


def read_job_report(job_id: str) -> Optional[Dict[str, Any]]:
    """Read done/<id>/job.json + result.json from disk (faster than HTTP).

    Note: the live job tree may be redirected by bridge config `jobs_dir`;
    it is NOT stored under data/jobs/.
    """
    base = jobs_root()
    d = base / "done" / job_id
    if not d.exists():
        for sub in ("failed", "cancelled", "running", "pending"):
            d2 = base / sub / job_id
            if d2.exists():
                d = d2
                break
        else:
            quarantined = base / "failed" / ".quarantine" / job_id
            if quarantined.exists():
                d = quarantined
            else:
                return None
    out: Dict[str, Any] = {"job_id": job_id, "_dir": str(d)}
    for fn in ("job.json", "result.json"):
        p = d / fn
        if p.exists():
            try:
                out[fn[:-5]] = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                out[fn[:-5] + "_error"] = str(e)
    return out


# ---------------------------------------------------------------------------
# Promotion gates — max drawdown budget vs allocated starting capital
# ---------------------------------------------------------------------------

def starting_capital_from_params(params: Optional[Dict[str, Any]]) -> float:
    """Read allocated starting capital from job/strategy params."""
    if not params:
        return DEFAULT_STARTING_CAPITAL
    for key in ("StartingCapital", "starting_capital"):
        raw = params.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0.0:
            return value
    return DEFAULT_STARTING_CAPITAL


def max_drawdown_budget(starting_capital: Optional[float] = None) -> float:
    """Absolute USD budget for Full-period max drawdown gate."""
    cap = float(starting_capital if starting_capital is not None else DEFAULT_STARTING_CAPITAL)
    if cap <= 0.0:
        cap = DEFAULT_STARTING_CAPITAL
    return cap * MAX_DRAWDOWN_BUDGET_PCT


def max_drawdown_within_budget(
    drawdown: Any,
    starting_capital: Optional[float] = None,
) -> bool:
    """True when |drawdown| is within 15% of allocated starting capital."""
    try:
        dd = float(drawdown or 0.0)
    except (TypeError, ValueError):
        dd = 0.0
    return abs(dd) <= max_drawdown_budget(starting_capital)


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utcnow_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
