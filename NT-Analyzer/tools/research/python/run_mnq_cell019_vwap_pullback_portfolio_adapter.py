"""Portfolio-scan adapter for CELL-019 RTH VWAP pullback.

The original runner is smoke-only. This adapter normalizes it to the staged
portfolio interface used by the generic cross-instrument orchestrator:
Smoke -> Full / IS / OOS -> stress -> Current30D.
"""
from __future__ import annotations

import json
import math
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import research_lib as RL  # noqa: E402
import smoke_mnq_cell019_vwap_pullback as BASE  # noqa: E402


CLASS_NAME = BASE.CLASS_NAME
ROOT = "MNQ"
INSTRUMENT = BASE.INSTRUMENT
SESSION_TEMPLATE = BASE.SESSION_TEMPLATE
BARS_PERIOD_VALUE = BASE.BARS
BASE_TF_SECONDS = BASE.BASE_TF

FULL = ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z")
IS = ("IS", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z")
OOS = ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z")
SMOKE = ("Smoke", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z")

FEE_STRESS = 2.40


def candidates() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for label, overrides in BASE.VARIANTS:
        params = BASE.base()
        params.update(overrides)
        out.append({"label": label, "params": params})
    return out


def trades_from(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = report.get("result") or {}
    trades = result.get("trades")
    if isinstance(trades, list):
        return trades
    return BASE.trades_of(report)


def trade_qty(trade: Dict[str, Any]) -> float:
    try:
        return max(1.0, abs(float(trade.get("quantity") or 1.0)))
    except Exception:
        return 1.0


def adjusted_pnls(trades: Iterable[Dict[str, Any]], fee: float) -> List[float]:
    out: List[float] = []
    for trade in trades:
        out.append(float(trade.get("pnl_currency") or 0.0) - fee * trade_qty(trade))
    return out


def _bar_bucket(ts: str) -> Optional[int]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None
    return int(dt.timestamp()) // BASE_TF_SECONDS


def same_bar_pct(trades: List[Dict[str, Any]]) -> float:
    if not trades:
        return 0.0
    same = 0
    counted = 0
    for trade in trades:
        entry_bar = _bar_bucket(str(trade.get("entry_time_utc") or trade.get("entry_time") or ""))
        exit_bar = _bar_bucket(str(trade.get("exit_time_utc") or trade.get("exit_time") or ""))
        if entry_bar is None or exit_bar is None:
            continue
        counted += 1
        if entry_bar == exit_bar:
            same += 1
    return round(same / counted * 100.0, 2) if counted else 0.0


def weekdays(from_utc: str, to_utc: str) -> int:
    start = date.fromisoformat(from_utc[:10])
    end = date.fromisoformat(to_utc[:10])
    if end < start:
        return 0
    total = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            total += 1
        cur += timedelta(days=1)
    return total


def job_state(job_id: str) -> Optional[str]:
    base = RL.jobs_root()
    for state in ("done", "failed", "cancelled", "running", "pending"):
        if (base / state / job_id).is_dir():
            return state
    if (base / "failed" / ".quarantine" / job_id).is_dir():
        return "failed"
    return None


def wait_for_jobs(rows: List[Dict[str, Any]], timeout_s: int = 28800) -> None:
    remaining = {str(r["job_id"]) for r in rows if r.get("job_id")}
    deadline = time.time() + timeout_s
    last_print = 0.0
    while remaining:
        if time.time() > deadline:
            raise TimeoutError(f"timeout waiting for jobs: {sorted(remaining)}")
        for job_id in list(remaining):
            if job_state(job_id) in {"done", "failed", "cancelled"}:
                remaining.remove(job_id)
        now = time.time()
        if now - last_print >= 30 and remaining:
            print(f"waiting: {len(remaining)} vwap-pullback jobs still pending/running", flush=True)
            last_print = now
        time.sleep(3)


def max_consecutive_losses(pnls: Iterable[float]) -> int:
    best = 0
    cur = 0
    for pnl in pnls:
        if pnl < 0.0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def summarize(row: Dict[str, Any], report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = dict(row)
    out.pop("response", None)
    out.pop("params", None)
    if not report or "result" not in report:
        out.update({"status": job_state(str(row.get("job_id") or "")) or "missing", "trade_count": 0})
        return out

    trades = trades_from(report)
    fee = float(row.get("fee") or 0.0)
    pnls = adjusted_pnls(trades, fee)
    gross_profit = sum(p for p in pnls if p > 0.0)
    gross_loss = abs(sum(p for p in pnls if p < 0.0))
    adj_net = sum(pnls)
    adj_pf = gross_profit / gross_loss if gross_loss > 0.0 else (math.inf if gross_profit > 0.0 else 0.0)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    active_days = Counter(
        str(t.get("entry_time_utc") or t.get("exit_time_utc") or "")[:10]
        for t in trades
        if t.get("entry_time_utc") or t.get("exit_time_utc")
    )
    active_counts = list(active_days.values())
    total_days = weekdays(str(row.get("from_utc")), str(row.get("to_utc")))
    out.update({
        "status": job_state(str(row.get("job_id") or "")) or "unknown",
        "status_dir": report.get("_dir", ""),
        "trade_count": len(trades),
        "calendar_weekdays": total_days,
        "trades_per_day": round(len(trades) / total_days, 4) if total_days else 0.0,
        "active_days": len(active_counts),
        "trades_per_active_day": round(len(trades) / len(active_counts), 4) if active_counts else 0.0,
        "adj_net": round(adj_net, 2),
        "adj_pf": adj_pf,
        "win_rate": round((sum(1 for p in pnls if p > 0.0) / len(pnls) * 100.0) if pnls else 0.0, 2),
        "avg_trade_after_commission": round(adj_net / len(pnls), 2) if pnls else 0.0,
        "max_drawdown": round(max_dd, 2),
        "max_consecutive_losses": max_consecutive_losses(pnls),
        "same_bar_pct": same_bar_pct(trades),
        "gross_profit_after_commission": round(gross_profit, 2),
        "gross_loss_after_commission": round(gross_loss, 2),
    })
    return out


def collect_rows(bundle: Path, rows: List[Dict[str, Any]], filename: str) -> List[Dict[str, Any]]:
    wait_for_jobs(rows)
    summaries: List[Dict[str, Any]] = []
    for row in rows:
        job_id = str(row.get("job_id") or "")
        report = RL.read_job_report(job_id) if job_id else None
        summary = summarize(row, report)
        summaries.append(summary)
        pf = summary.get("adj_pf")
        pf_s = "inf" if pf == math.inf else f"{float(pf or 0.0):.3f}"
        print(
            f"done   {row['stage']:10s} {row['label']:32s} {row.get('instrument', 'MNQ 06-26'):12s} {row['period_label']:14s} "
            f"trades={int(summary.get('trade_count') or 0):>4} "
            f"net={float(summary.get('adj_net') or 0.0):>9.2f} "
            f"pf={pf_s:>7s} dd={float(summary.get('max_drawdown') or 0.0):>9.2f} "
            f"sb%={float(summary.get('same_bar_pct') or 0.0):>5.1f}",
            flush=True,
        )
        (bundle / filename).write_text(json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8")
    return summaries


def score(row: Dict[str, Any]) -> float:
    net = float(row.get("adj_net") or 0.0)
    pf = float(row.get("adj_pf") or 0.0)
    dd = abs(float(row.get("max_drawdown") or 0.0))
    trades = int(row.get("trade_count") or 0)
    if trades <= 0:
        return -999999.0
    pf_capped = min(pf, 3.0) if not math.isinf(pf) else 3.0
    return net + pf_capped * 120.0 + min(trades, 600) * 0.5 - dd * 0.4


def pick_smoke(rows: List[Dict[str, Any]], limit: int) -> List[str]:
    eligible = [
        row for row in rows
        if int(row.get("trade_count") or 0) >= 6
        and float(row.get("adj_net") or 0.0) > 0.0
    ]
    if not eligible:
        eligible = [row for row in rows if int(row.get("trade_count") or 0) > 0]
    eligible.sort(key=score, reverse=True)
    return [str(row["label"]) for row in eligible[:limit]]


def gates(full: Dict[str, Any], is_: Dict[str, Any], oos: Dict[str, Any],
          stress_combined: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, bool]:
    def f(row: Dict[str, Any], key: str) -> float:
        value = row.get(key)
        if value is None:
            return 0.0
        if value == math.inf:
            return 99.0
        return float(value)

    return {
        "full_net_pos": f(full, "adj_net") > 0.0,
        "full_pf_135": f(full, "adj_pf") >= 1.35,
        "oos_pf_125": f(oos, "adj_pf") >= 1.25,
        "max_dd_pct_15": RL.max_drawdown_within_budget(f(full, "max_drawdown")),
        "stress_combined_nonneg": f(stress_combined, "adj_net") >= 0.0,
        "current30d_nonneg": f(current, "adj_net") >= 0.0,
        "enough_trades": int(full.get("trade_count") or 0) >= 30,
        "is_net_pos": f(is_, "adj_net") > 0.0,
        "low_same_bar": f(full, "same_bar_pct") <= 50.0,
    }