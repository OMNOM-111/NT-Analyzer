"""Throwaway audit script: compute real demo (paper) per-strategy metrics
from runtime executions using the project's own performance reconstruction.

Run:
    python -m tools.research.audit_active_strategies_20260531
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import performance as perf
from app import ops


def fnum(x):
    try:
        return float(x or 0.0)
    except (TypeError, ValueError):
        return 0.0


def max_drawdown(pnls):
    """Max drawdown of cumulative equity curve (sequence order = trade order)."""
    peak = 0.0
    cum = 0.0
    mdd = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return mdd


def summarize(trades):
    pnls = [fnum(t.get("pnl")) for t in trades]
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    net = sum(pnls)
    gross_win = sum(wins)
    gross_loss = sum(losses)
    pf = (gross_win / abs(gross_loss)) if gross_loss else (float("inf") if gross_win else 0.0)
    wr = (len(wins) / n * 100.0) if n else 0.0
    avg = (net / n) if n else 0.0
    avg_win = (gross_win / len(wins)) if wins else 0.0
    avg_loss = (gross_loss / len(losses)) if losses else 0.0
    return {
        "trades": n,
        "net": round(net, 2),
        "winrate": round(wr, 1),
        "pf": (round(pf, 3) if pf != float("inf") else "inf"),
        "avg_trade": round(avg, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "gross_win": round(gross_win, 2),
        "gross_loss": round(gross_loss, 2),
        "max_dd": round(max_drawdown(pnls), 2),
    }


def daily_breakdown(trades):
    days = defaultdict(float)
    daycount = defaultdict(int)
    for t in trades:
        d = str(t.get("date_pt") or "")
        days[d] += fnum(t.get("pnl"))
        daycount[d] += 1
    out = []
    for d in sorted(days):
        out.append({"date": d, "net": round(days[d], 2), "trades": daycount[d]})
    return out


def strat_key(t):
    cell = str(t.get("cell") or perf._extract_cell(
        t.get("strategy_name"), t.get("strategy_class"), t.get("strategy_id")) or "")
    cls = str(t.get("strategy_class") or "")
    sid = str(t.get("strategy_id") or "")
    name = str(t.get("strategy_name") or "")
    return (cell, cls, sid, name)


def run_period(label, period, frm, to):
    resolved, trades, dedupe, alln = perf._closed_trades_for_request(
        period=period, from_date=frm, to_date=to, account_name=None)
    print(f"\n{'='*90}\nPERIOD {label}: {resolved['from']} .. {resolved['to']}  "
          f"(all_closed={alln}, in_period={len(trades)})")
    # group
    groups = defaultdict(list)
    unmapped = []
    for t in trades:
        if t.get("unmapped"):
            unmapped.append(t)
        groups[strat_key(t)].append(t)

    rows = []
    for key, ts in groups.items():
        s = summarize(ts)
        rows.append((key, s, ts))
    rows.sort(key=lambda r: r[1]["net"])

    for key, s, ts in rows:
        cell, cls, sid, name = key
        instruments = sorted({str(t.get("instrument_root") or t.get("instrument") or "") for t in ts})
        dirs = defaultdict(int)
        for t in ts:
            dirs[str(t.get("direction") or "")] += 1
        db = daily_breakdown(ts)
        active_days = len(db)
        worst = sorted(db, key=lambda d: d["net"])[:3]
        best = sorted(db, key=lambda d: d["net"], reverse=True)[:3]
        print(f"\n  --- CELL {cell or '?'} | {name or cls} | id={sid}")
        print(f"      class={cls}  instruments={instruments}  dirs={dict(dirs)}")
        print(f"      {json.dumps(s, ensure_ascii=False)}")
        print(f"      active_days={active_days}")
        print(f"      worst_days={[ (d['date'], d['net'], d['trades']) for d in worst]}")
        print(f"      best_days={[ (d['date'], d['net'], d['trades']) for d in best]}")
        print(f"      daily={[ (d['date'], d['net'], d['trades']) for d in db]}")

    if unmapped:
        us = summarize(unmapped)
        print(f"\n  --- UNMAPPED (account-level, no strategy) ---")
        print(f"      {json.dumps(us, ensure_ascii=False)}")
        ub = daily_breakdown(unmapped)
        print(f"      daily={[ (d['date'], d['net'], d['trades']) for d in ub]}")

    return rows


def main():
    # Sample one trade to inspect fields
    _, trades, _, _ = perf._closed_trades_for_request(period="custom", from_date="2026-05-01", to_date="2026-05-31")
    if trades:
        print("SAMPLE TRADE KEYS:", sorted(trades[0].keys()))
        print("SAMPLE TRADE:", json.dumps({k: trades[0].get(k) for k in (
            "date_pt","time_pt","pnl","gross_pnl","commission","direction","quantity",
            "instrument","instrument_root","strategy_class","strategy_id","strategy_name",
            "cell","unmapped","strategy_attribution_confidence","exit_reason")}, ensure_ascii=False, indent=2))
    # full month
    run_period("MONTH 2026-05", "custom", "2026-05-01", "2026-05-31")
    # last 7+ days
    run_period("LAST7 2026-05-24..31", "custom", "2026-05-24", "2026-05-31")
    # wider: year to be safe
    run_period("YTD 2026", "custom", "2026-01-01", "2026-05-31")


if __name__ == "__main__":
    main()
