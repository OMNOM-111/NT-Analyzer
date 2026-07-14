"""Analysis pack builder.

Given a finished historical backtest job, compute the normalized averages and
growth percentages required by the AI performance board and arbitration:

- avg per day/week/month/quarter/year
- monthly/quarterly growth %, annualized, compounded
- trades per day/week/month, total
- years_tested
- pf, dd (after commission - inherited from backtest result)
- profitable months/quarters/years %
- stress_pass_flag (conservative None until a separate stress result is attached)
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .io_utils import read_json


def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _safe_div(a: float, b: float) -> Optional[float]:
    if not b:
        return None
    try:
        return a / b
    except ZeroDivisionError:
        return None


def _trade_pnl(t: Dict[str, Any]) -> float:
    for k in (
        "pnl_currency", "pnlCurrency", "profit_currency", "profitCurrency",
        "profit", "pnl", "net_profit", "netProfit", "ProfitCurrency",
    ):
        if k in t and t[k] is not None:
            try:
                return float(t[k])
            except (TypeError, ValueError):
                continue
    return 0.0


def _trade_qty(t: Dict[str, Any]) -> float:
    for k in ("quantity", "qty", "contracts", "Quantity"):
        if k in t and t[k] is not None:
            try:
                return max(1.0, abs(float(t[k])))
            except (TypeError, ValueError):
                continue
    return 1.0


def _trade_time(t: Dict[str, Any]) -> Optional[datetime]:
    for k in (
        "exit_time_utc", "exitTimeUtc", "exit_time", "exitTime", "time", "exit_utc",
        "entry_time_utc", "entryTimeUtc", "entry_time", "entryTime",
    ):
        if k in t and t[k]:
            dt = _parse_iso(str(t[k]))
            if dt:
                return dt
    return None


def _first_present(*values: Any) -> Any:
    for v in values:
        if v is not None:
            return v
    return None


def _round_turn_commission(job: Dict[str, Any]) -> float:
    execution = job.get("execution") if isinstance(job.get("execution"), dict) else {}
    strategy = job.get("strategy") if isinstance(job.get("strategy"), dict) else {}
    params = strategy.get("parameters") if isinstance(strategy.get("parameters"), dict) else {}
    for value in (
        execution.get("round_turn_commission"),
        params.get("RoundTurnCommission"),
    ):
        try:
            out = float(value or 0.0)
        except (TypeError, ValueError):
            out = 0.0
        if out > 0:
            return out
    return 0.0


def _profit_factor(values: List[float]) -> Optional[float]:
    gross_profit = sum(v for v in values if v > 0)
    gross_loss = abs(sum(v for v in values if v < 0))
    if gross_loss <= 0:
        return None if gross_profit <= 0 else float("inf")
    return gross_profit / gross_loss


def _max_drawdown(values: List[float]) -> float:
    cum = 0.0
    peak = 0.0
    mdd = 0.0
    for v in values:
        cum += v
        if cum > peak:
            peak = cum
        dd = cum - peak
        if dd < mdd:
            mdd = dd
    return mdd


def build(job_dir: Path, capital: float = 5000.0) -> Dict[str, Any]:
    """Build analysis pack from a done job directory.

    Accepts paths to either jobs/done/{job_id}/ or any directory containing
    job.json, result.json, trades.json.
    """
    job = read_json(job_dir / "job.json", default={}) or {}
    result = read_json(job_dir / "result.json", default={}) or {}
    trades = read_json(job_dir / "trades.json", default=[]) or []
    if isinstance(trades, dict) and "trades" in trades:
        trades = trades["trades"]
    if not isinstance(trades, list):
        trades = []

    period = job.get("period", {}) or {}
    from_dt = _parse_iso(period.get("from_utc") or job.get("from_utc"))
    to_dt = _parse_iso(period.get("to_utc") or job.get("to_utc"))
    rtc = _round_turn_commission(job)

    parsed: List[Dict[str, Any]] = []
    for t in trades:
        if not isinstance(t, dict):
            continue
        dt = _trade_time(t)
        if not dt:
            continue
        gross = _trade_pnl(t)
        adjusted = gross - (_trade_qty(t) * rtc if rtc > 0 else 0.0)
        parsed.append({"time": dt, "pnl": adjusted, "gross_pnl": gross})
    parsed.sort(key=lambda x: x["time"])

    if not parsed:
        return _empty_pack(job, result, capital, from_dt, to_dt)

    trades_total = len(parsed)
    first = parsed[0]["time"]
    last = parsed[-1]["time"]
    span_start = from_dt or first
    span_end = to_dt or last
    days = max(1.0, (span_end - span_start).total_seconds() / 86400.0)
    weeks = days / 7.0
    months = days / 30.4375
    quarters = days / 91.3125
    years = days / 365.25

    total_pnl = sum(p["pnl"] for p in parsed)
    gross_total_pnl = sum(p.get("gross_pnl", p["pnl"]) for p in parsed)

    by_day: Dict[str, float] = defaultdict(float)
    by_week: Dict[str, float] = defaultdict(float)
    by_month: Dict[str, float] = defaultdict(float)
    by_quarter: Dict[str, float] = defaultdict(float)
    by_year: Dict[str, float] = defaultdict(float)
    for p in parsed:
        d = p["time"]
        by_day[d.strftime("%Y-%m-%d")] += p["pnl"]
        iso = d.isocalendar()
        by_week[f"{iso[0]}-W{iso[1]:02d}"] += p["pnl"]
        by_month[d.strftime("%Y-%m")] += p["pnl"]
        by_quarter[f"{d.year}-Q{((d.month-1)//3)+1}"] += p["pnl"]
        by_year[str(d.year)] += p["pnl"]

    profitable_months_pct = _pct_positive(by_month)
    profitable_quarters_pct = _pct_positive(by_quarter)
    profitable_years_pct = _pct_positive(by_year)

    avg_per_day = total_pnl / days
    avg_per_week = total_pnl / weeks
    avg_per_month = total_pnl / months
    avg_per_quarter = total_pnl / quarters
    avg_per_year = total_pnl / years

    monthly_growth_pct = (avg_per_month / capital * 100.0) if capital else None
    quarterly_growth_pct = (avg_per_quarter / capital * 100.0) if capital else None
    annualized_growth_estimate_pct = (avg_per_year / capital * 100.0) if capital else None
    compounded = None
    if monthly_growth_pct is not None:
        try:
            compounded = ((1 + monthly_growth_pct / 100.0) ** 12 - 1) * 100.0
        except (OverflowError, ValueError):
            compounded = None

    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    adjusted_values = [p["pnl"] for p in parsed]
    pf = _profit_factor(adjusted_values) if rtc > 0 else _first_present(
        metrics.get("profit_factor"), summary.get("profit_factor"), summary.get("Profit Factor"),
        result.get("profit_factor"), result.get("pf"), result.get("ProfitFactor"),
    )
    dd = _max_drawdown(adjusted_values) if rtc > 0 else _first_present(
        metrics.get("max_drawdown"), summary.get("max_drawdown"), summary.get("Max. Drawdown"),
        result.get("max_drawdown"), result.get("dd"), result.get("MaxDrawdown"),
    )

    return {
        "schema_version": "0.1",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "job_id": job.get("job_id"),
        "capital": capital,
        "period": {
            "from_utc": span_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to_utc": span_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "days": days,
            "weeks": weeks,
            "months": months,
            "quarters": quarters,
            "years": years,
        },
        "totals": {
            "trades_total": trades_total,
            "net_pnl": total_pnl,
            "gross_net_pnl": gross_total_pnl,
            "round_turn_commission": rtc,
        },
        "averages": {
            "avg_per_day": avg_per_day,
            "avg_per_week": avg_per_week,
            "avg_per_month": avg_per_month,
            "avg_per_quarter": avg_per_quarter,
            "avg_per_year": avg_per_year,
        },
        "growth": {
            "monthly_growth_pct": monthly_growth_pct,
            "quarterly_growth_pct": quarterly_growth_pct,
            "annualized_growth_estimate_pct": annualized_growth_estimate_pct,
            "compounded_growth_estimate_pct": compounded,
        },
        "trade_density": {
            "trades_per_day": trades_total / days,
            "trades_per_week": trades_total / weeks,
            "trades_per_month": trades_total / months,
        },
        "stability": {
            "pf_after_commission": _maybe_float(pf),
            "dd_after_commission": _maybe_float(dd),
            "profitable_months_pct": profitable_months_pct,
            "profitable_quarters_pct": profitable_quarters_pct,
            "profitable_years_pct": profitable_years_pct,
        },
        "breakdown": {
            "by_month": dict(sorted(by_month.items())),
            "by_quarter": dict(sorted(by_quarter.items())),
            "by_year": dict(sorted(by_year.items())),
        },
        "stress_pass_flag": None,
        "years_tested": years,
    }


def _pct_positive(d: Dict[str, float]) -> Optional[float]:
    if not d:
        return None
    pos = sum(1 for v in d.values() if v > 0)
    return 100.0 * pos / len(d)


def _maybe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _empty_pack(job, result, capital, from_dt, to_dt) -> Dict[str, Any]:
    return {
        "schema_version": "0.1",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "job_id": job.get("job_id"),
        "capital": capital,
        "period": {
            "from_utc": from_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if from_dt else None,
            "to_utc": to_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if to_dt else None,
            "days": 0, "weeks": 0, "months": 0, "quarters": 0, "years": 0,
        },
        "totals": {"trades_total": 0, "net_pnl": 0.0},
        "averages": {k: 0.0 for k in ("avg_per_day", "avg_per_week", "avg_per_month", "avg_per_quarter", "avg_per_year")},
        "growth": {k: None for k in ("monthly_growth_pct", "quarterly_growth_pct", "annualized_growth_estimate_pct", "compounded_growth_estimate_pct")},
        "trade_density": {"trades_per_day": 0.0, "trades_per_week": 0.0, "trades_per_month": 0.0},
        "stability": {"pf_after_commission": None, "dd_after_commission": None, "profitable_months_pct": None, "profitable_quarters_pct": None, "profitable_years_pct": None},
        "breakdown": {"by_month": {}, "by_quarter": {}, "by_year": {}},
        "stress_pass_flag": None,
        "years_tested": 0.0,
        "empty": True,
    }


def project_to_experiment_analysis(pack: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten pack to the experiment.analysis subobject shape."""
    avg = pack.get("averages", {})
    grow = pack.get("growth", {})
    td = pack.get("trade_density", {})
    st = pack.get("stability", {})
    totals = pack.get("totals", {})
    return {
        "avg_per_day": avg.get("avg_per_day"),
        "avg_per_week": avg.get("avg_per_week"),
        "avg_per_month": avg.get("avg_per_month"),
        "avg_per_quarter": avg.get("avg_per_quarter"),
        "avg_per_year": avg.get("avg_per_year"),
        "monthly_growth_pct": grow.get("monthly_growth_pct"),
        "quarterly_growth_pct": grow.get("quarterly_growth_pct"),
        "annualized_growth_estimate_pct": grow.get("annualized_growth_estimate_pct"),
        "compounded_growth_estimate_pct": grow.get("compounded_growth_estimate_pct"),
        "trades_per_day": td.get("trades_per_day"),
        "trades_per_week": td.get("trades_per_week"),
        "trades_per_month": td.get("trades_per_month"),
        "trades_total": totals.get("trades_total"),
        "net_after_commission": totals.get("net_pnl"),
        "gross_net_pnl": totals.get("gross_net_pnl"),
        "years_tested": pack.get("years_tested"),
        "pf_after_commission": st.get("pf_after_commission"),
        "dd_after_commission": st.get("dd_after_commission"),
        "profitable_months_pct": st.get("profitable_months_pct"),
        "profitable_quarters_pct": st.get("profitable_quarters_pct"),
        "profitable_years_pct": st.get("profitable_years_pct"),
        "stress_pass_flag": pack.get("stress_pass_flag"),
    }
