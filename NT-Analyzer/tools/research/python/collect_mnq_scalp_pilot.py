"""Collect NTAMicroMnqScalpPilot bundle results and apply scalp gates.

Usage:
  python collect_mnq_scalp_pilot.py data/research/mnq_scalp_pilot_YYYY...
"""
from __future__ import annotations

import csv
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402
import mnq_scalp_pilot_lib as MS  # noqa: E402


def load_manifests(bundle: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in sorted(bundle.glob("*_manifest.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        out.extend(data.get("submitted") or [])
    return out


def poll_batches(batch_ids: List[str], timeout_s: int = 7200) -> None:
    end = time.time() + timeout_s
    while time.time() < end:
        pending = 0
        for bid in batch_ids:
            code, resp = RL.get(f"/api/batches/{bid}")
            if code != 200:
                pending += 1
                continue
            counts = resp.get("counts") or {}
            pending += int(counts.get("pending") or 0) + int(counts.get("running") or 0)
        print(f"pending/running jobs: {pending}")
        if pending == 0:
            return
        time.sleep(10)


def trade_qty(t: Dict[str, Any]) -> float:
    try:
        return max(1.0, abs(float(t.get("quantity") or 1.0)))
    except Exception:
        return 1.0


def adjusted_trade_pnl(t: Dict[str, Any], round_turn_commission: float) -> float:
    return float(t.get("pnl_currency") or 0.0) - round_turn_commission * trade_qty(t)


def max_consecutive_losses(trades: List[Dict[str, Any]], round_turn_commission: float) -> int:
    best = cur = 0
    for t in trades:
        pnl = adjusted_trade_pnl(t, round_turn_commission)
        if pnl < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def daily_stop_hits(trades: List[Dict[str, Any]], stop_usd: float = 60.0,
                    round_turn_commission: float = 0.0) -> int:
    by_day: Dict[str, float] = defaultdict(float)
    for t in trades:
        ts = str(t.get("exit_time_utc") or t.get("entry_time_utc") or "")
        day = ts[:10]
        if day:
            by_day[day] += adjusted_trade_pnl(t, round_turn_commission)
    return sum(1 for pnl in by_day.values() if pnl <= -abs(stop_usd))


def same_bar_stats(trades: List[Dict[str, Any]], round_turn_commission: float) -> Dict[str, float]:
    if not trades:
        return {"same_bar_pct": 0.0, "ambiguous_wins_pct": 0.0}
    same = [
        t for t in trades
        if t.get("entry_time_utc") and t.get("entry_time_utc") == t.get("exit_time_utc")
    ]
    same_wins = [t for t in same if adjusted_trade_pnl(t, round_turn_commission) > 0]
    wins = [t for t in trades if adjusted_trade_pnl(t, round_turn_commission) > 0]
    return {
        "same_bar_pct": round(len(same) / len(trades) * 100.0, 2),
        "ambiguous_wins_pct": round(len(same_wins) / max(1, len(wins)) * 100.0, 2),
    }


def adjusted_metrics(metrics: Dict[str, Any], trades: List[Dict[str, Any]],
                     round_turn_commission: float) -> Dict[str, float]:
    """Return after-commission metrics, deriving them when old result.json lacks them."""
    if metrics.get("net_profit_after_commission") is not None:
        return {
            "adj_net": float(metrics.get("net_profit_after_commission") or 0.0),
            "adj_pf": float(metrics.get("profit_factor_after_commission")
                            if metrics.get("profit_factor_after_commission") is not None
                            else metrics.get("profit_factor") or 0.0),
            "win_rate": float(metrics.get("win_pct_after_commission")
                              if metrics.get("win_pct_after_commission") is not None
                              else metrics.get("winning_pct") or 0.0),
            "max_drawdown": float(metrics.get("max_drawdown_after_commission")
                                  if metrics.get("max_drawdown_after_commission") is not None
                                  else metrics.get("max_drawdown") or 0.0),
        }

    pnls = [adjusted_trade_pnl(t, round_turn_commission) for t in trades]
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = sum(p for p in pnls if p < 0)
    adj_net = sum(pnls)
    adj_pf = gross_profit / abs(gross_loss) if gross_loss < 0 else (1.0 if gross_profit == 0 else 999.0)
    win_rate = (sum(1 for p in pnls if p > 0) / len(pnls) * 100.0) if pnls else 0.0

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)

    return {
        "adj_net": adj_net,
        "adj_pf": adj_pf,
        "win_rate": win_rate,
        "max_drawdown": max_dd,
    }


def sort_trades(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        trades,
        key=lambda t: str(t.get("entry_time_utc") or t.get("exit_time_utc") or ""),
    )


def public_row_from_trades(*, instrument: str, module: str, period_label: str,
                           job_id: str, batch_id: str, from_utc: str, to_utc: str,
                           trades: List[Dict[str, Any]], rt_commission: float,
                           contracts: List[str]) -> Dict[str, Any]:
    ordered = sort_trades(trades)
    days = MS.trading_weekdays(from_utc, to_utc)
    trade_count = len(ordered)
    adj = adjusted_metrics({}, ordered, rt_commission)
    active_dates = {
        str(t.get("entry_time_utc") or "")[:10]
        for t in ordered if t.get("entry_time_utc")
    }
    stop_hits = daily_stop_hits(ordered, round_turn_commission=rt_commission)
    sb = same_bar_stats(ordered, rt_commission)
    return {
        "instrument": instrument,
        "module": module,
        "period_label": period_label,
        "job_id": job_id,
        "batch_id": batch_id,
        "contracts": ",".join(sorted(set(contracts))),
        "trades": trade_count,
        "trade_count": trade_count,
        "trades_per_day": round(trade_count / days, 2),
        "active_days_pct": round(len(active_dates) / days * 100.0, 2),
        "adj_net": round(adj["adj_net"], 2),
        "adj_pf": round(adj["adj_pf"], 4),
        "win_rate": round(adj["win_rate"], 2),
        "avg_trade_after_commission": round(adj["adj_net"] / trade_count, 2) if trade_count else 0.0,
        "max_drawdown": round(float(adj["max_drawdown"]), 2),
        "max_consecutive_losses": max_consecutive_losses(ordered, rt_commission),
        "daily_stop_hits": stop_hits,
        "daily_stop_hit_pct": round(stop_hits / days * 100.0, 2),
        "same_bar_pct": sb["same_bar_pct"],
        "ambiguous_wins_pct": sb["ambiguous_wins_pct"],
        "from_utc": from_utc,
        "to_utc": to_utc,
    }


def _contract_expiry_key(instrument: str) -> tuple:
    """Sort key for contract by expiry: 'MNQ 03-26' -> (26, 3). Newer contracts sort larger."""
    parts = str(instrument).split()
    if len(parts) < 2 or "-" not in parts[1]:
        return (0, 0)
    try:
        mm, yy = parts[1].split("-")
        return (int(yy), int(mm))
    except Exception:
        return (0, 0)


def aggregate_contract_rows(raw_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate per-contract rows into canonical (root, module, period) rows.

    Bug fix (2026-05-06): the previous implementation flat-extended trade lists from every
    overlapping contract's back-data, inflating trade count and adj_net by N (number of
    contracts holding data in that window). Each per-contract job runs the SAME absolute
    [from_utc, to_utc] window using its own historical bars; for a 2-year window, all
    near-current contracts have continuous synthetic minute history covering the whole
    period, so flat-summing duplicates the same trades 5-9x.

    Honest fix: pick the SINGLE canonical contract per (root, module, period) — the
    latest expiry that covers the period — and use only its trades. This matches what
    an analyst would do manually and converges with a chained front-month proxy
    (verified for MICRO_ORB Full: latest=600/$443 vs chained=~700/$472).
    """
    groups: Dict[str, Dict[str, Any]] = {}
    for r in raw_rows:
        root = str(r["instrument"]).split()[0] if r.get("instrument") else ""
        key = "|".join([
            root,
            str(r.get("module") or ""),
            str(r.get("period_label") or ""),
            str(r.get("from_utc") or ""),
            str(r.get("to_utc") or ""),
        ])
        g = groups.setdefault(key, {
            "instrument": root,
            "module": r.get("module"),
            "period_label": r.get("period_label"),
            "from_utc": r.get("from_utc"),
            "to_utc": r.get("to_utc"),
            "candidates": [],
            "all_contracts": [],
        })
        g["candidates"].append(r)
        if r.get("instrument"):
            g["all_contracts"].append(r["instrument"])

    out = []
    for g in groups.values():
        candidates = g["candidates"]
        # Pick canonical contract: latest expiry (broadest historical data span).
        # Tiebreak: more trades (larger active sample).
        canonical = max(
            candidates,
            key=lambda r: (_contract_expiry_key(r.get("instrument") or ""),
                           len(r.get("_trades") or [])),
        )
        out.append(public_row_from_trades(
            instrument=g["instrument"],
            module=g["module"],
            period_label=g["period_label"],
            job_id=canonical.get("job_id") or "",
            batch_id=canonical.get("batch_id") or "",
            from_utc=g["from_utc"],
            to_utc=g["to_utc"],
            trades=canonical.get("_trades") or [],
            rt_commission=float(canonical.get("_rt_commission") or 0.0),
            contracts=[canonical.get("instrument") or ""],
        ))
    out.sort(key=lambda r: (r["instrument"], r["module"], r["period_label"]))
    return out


def classify(row: Dict[str, Any], oos_pf_by_key: Dict[str, Optional[float]]) -> str:
    if row["period_label"] != "Full":
        return ""
    key = f"{row['instrument']}|{row['module']}"
    oos_pf = oos_pf_by_key.get(key)
    if row["trade_count"] <= 0:
        return "REJECT"
    if row["adj_net"] <= 0 or (row["adj_pf"] or 0.0) < 1.0:
        return "REJECT"
    if oos_pf is not None and oos_pf < 1.0:
        return "REJECT"
    gates = [
        10.0 <= row["trades_per_day"] <= 20.0,
        (row["adj_pf"] or 0.0) >= 1.35,
        (oos_pf or 0.0) >= 1.25,
        row["win_rate"] >= 52.0,
        row["avg_trade_after_commission"] >= 1.50,
        RL.max_drawdown_within_budget(row["max_drawdown"]),
        row["max_consecutive_losses"] <= 5,
        row["daily_stop_hit_pct"] <= 5.0,
    ]
    if all(gates):
        return "KEEP_MAIN" if row["instrument"].startswith("MNQ") else "KEEP_COPY"
    if row["adj_net"] > 0 and (row["adj_pf"] or 0.0) >= 1.10:
        return "RESEARCH_ONLY"
    return "REJECT"


def confidence(row: Dict[str, Any], oos_pf: Optional[float]) -> int:
    score = 0
    if 10.0 <= row["trades_per_day"] <= 20.0:
        score += 20
    if (row["adj_pf"] or 0.0) >= 1.35:
        score += 20
    if (oos_pf or 0.0) >= 1.25:
        score += 20
    if row["win_rate"] >= 52.0:
        score += 15
    if row["avg_trade_after_commission"] >= 1.50:
        score += 10
    if RL.max_drawdown_within_budget(row["max_drawdown"]):
        score += 10
    if row["max_consecutive_losses"] <= 5:
        score += 5
    return score


def collect(bundle: Path) -> int:
    submissions = [s for s in load_manifests(bundle) if s.get("batch_id")]
    if not submissions:
        print(f"No batch manifests found in {bundle}")
        return 1
    poll_batches([s["batch_id"] for s in submissions])

    rows: List[Dict[str, Any]] = []
    for sub in submissions:
        bid = sub["batch_id"]
        code, batch = RL.get(f"/api/batches/{bid}")
        if code != 200:
            continue
        for child in batch.get("children") or []:
            jid = child.get("job_id")
            rep = RL.read_job_report(jid) if jid else None
            if not rep or "result" not in rep:
                continue
            result = rep["result"]
            ctx = result.get("context") or {}
            metrics = result.get("metrics") or {}
            trades = result.get("trades") or []
            params = (((result.get("context") or {}).get("strategy") or {}).get("final_parameters") or
                      ((rep.get("job") or {}).get("strategy") or {}).get("parameters") or {})
            try:
                rt_commission = float(params.get("RoundTurnCommission")
                                      if params.get("RoundTurnCommission") is not None
                                      else ((rep.get("job") or {}).get("execution") or {}).get("round_turn_commission") or 0.0)
            except Exception:
                rt_commission = 0.0
            instrument = ctx.get("instrument") or child.get("instrument") or ""
            period = ctx.get("period") or {}
            from_utc = period.get("from_utc") or sub.get("from_utc")
            to_utc = period.get("to_utc") or sub.get("to_utc")
            days = MS.trading_weekdays(from_utc, to_utc)
            trade_count = int(metrics.get("trade_count") or 0)
            adj = adjusted_metrics(metrics, trades, rt_commission)
            adj_net = adj["adj_net"]
            adj_pf = adj["adj_pf"]
            win_rate = adj["win_rate"]
            active_days = len({
                str(t.get("entry_time_utc") or "")[:10]
                for t in trades if t.get("entry_time_utc")
            })
            stop_hits = daily_stop_hits(trades, round_turn_commission=rt_commission)
            sb = same_bar_stats(trades, rt_commission)
            row = {
                "instrument": instrument,
                "module": sub.get("module"),
                "period_label": sub.get("period_label"),
                "job_id": jid,
                "batch_id": bid,
                "trades": trade_count,
                "trade_count": trade_count,
                "trades_per_day": round(trade_count / days, 2),
                "active_days_pct": round(active_days / days * 100.0, 2),
                "adj_net": round(adj_net, 2),
                "adj_pf": round(float(adj_pf or 0.0), 4),
                "win_rate": round(win_rate, 2),
                "avg_trade_after_commission": round(adj_net / trade_count, 2) if trade_count else 0.0,
                "max_drawdown": round(float(adj["max_drawdown"]), 2),
                "max_consecutive_losses": max_consecutive_losses(trades, rt_commission),
                "daily_stop_hits": stop_hits,
                "daily_stop_hit_pct": round(stop_hits / days * 100.0, 2),
                "same_bar_pct": sb["same_bar_pct"],
                "ambiguous_wins_pct": sb["ambiguous_wins_pct"],
                "from_utc": from_utc,
                "to_utc": to_utc,
                "_trades": trades,
                "_rt_commission": rt_commission,
            }
            rows.append(row)

    rows = aggregate_contract_rows(rows)

    oos_pf_by_key = {
        f"{r['instrument']}|{r['module']}": r["adj_pf"]
        for r in rows if r["period_label"] == "OOS"
    }
    for r in rows:
        key = f"{r['instrument']}|{r['module']}"
        r["oos_adj_pf"] = oos_pf_by_key.get(key)
        r["confidence_score"] = confidence(r, r["oos_adj_pf"])
        r["decision"] = classify(r, oos_pf_by_key)

    out_json = bundle / "mnq_scalp_results.json"
    out_json.write_text(json.dumps({"rows": rows}, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    cols = [
        "instrument", "module", "period_label", "contracts", "trades", "trades_per_day",
        "active_days_pct", "adj_net", "adj_pf", "oos_adj_pf", "win_rate",
        "avg_trade_after_commission", "max_drawdown", "max_consecutive_losses",
        "daily_stop_hits", "daily_stop_hit_pct", "same_bar_pct",
        "ambiguous_wins_pct", "confidence_score", "decision", "job_id",
    ]
    with (bundle / "mnq_scalp_results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    full_rows = [r for r in rows if r["period_label"] == "Full"]
    full_rows.sort(key=lambda r: (r["decision"] != "KEEP_MAIN",
                                  r["decision"] != "KEEP_COPY",
                                  -r["confidence_score"],
                                  -(r["adj_pf"] or 0.0)))
    lines = ["# NTAMicroMnqScalpPilot Results", ""]
    lines.append("| Instrument | Module | Trades/day | Adj PF | OOS Adj PF | Avg/trade | DD | Conf | Decision |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in full_rows[:40]:
        lines.append(
            f"| {r['instrument']} | {r['module']} | {r['trades_per_day']} | "
            f"{r['adj_pf']} | {r.get('oos_adj_pf')} | "
            f"{r['avg_trade_after_commission']} | {r['max_drawdown']} | "
            f"{r['confidence_score']} | {r['decision']} |"
        )
    (bundle / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out_json}")
    print(f"wrote {bundle / 'mnq_scalp_results.csv'}")
    print(f"wrote {bundle / 'summary.md'}")
    return 0


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    return collect(Path(argv[1]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
