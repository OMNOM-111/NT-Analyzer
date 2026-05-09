"""Re-aggregate MnqScalpPilot bundle directly from filesystem (bypass API).

Reads each per-contract result.json from `jobs/done/`, picks the canonical
contract per (root, module, period) — the one with the latest expiry whose
historical data covers the full period — and emits an honest CSV/JSON/MD.

The previous aggregator flat-summed overlapping contracts' trade lists, which
inflated counts/net 5-9x. Each contract job uses the same absolute period
window but its own historical bar series; for 2-year windows, all near-current
contracts have continuous synthetic minute history covering the whole period
(the "lower" contracts just stop earlier, at their expiry). The canonical
view is the latest expiry — its trade count grows monotonically as a SUPERSET
of every earlier contract's trades.

Usage: python recollect_mnq_scalp_local.py <bundle_dir>
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import mnq_scalp_pilot_lib as MS  # noqa: E402

ROOT = HERE.parent.parent.parent  # NT-Analyzer/
JOBS_DONE = ROOT / "jobs" / "done"


def expiry_key(instrument: str) -> Tuple[int, int]:
    """'MNQ 03-26' -> (26, 3); newer contracts sort larger."""
    parts = str(instrument).split()
    if len(parts) < 2 or "-" not in parts[1]:
        return (0, 0)
    try:
        mm, yy = parts[1].split("-")
        return (int(yy), int(mm))
    except Exception:
        return (0, 0)


def root_of(instrument: str) -> str:
    return str(instrument).split()[0] if instrument else ""


def trade_qty(t: Dict[str, Any]) -> float:
    try:
        return max(1.0, abs(float(t.get("quantity") or 1.0)))
    except Exception:
        return 1.0


def adj_trade_pnl(t: Dict[str, Any], rtc: float) -> float:
    return float(t.get("pnl_currency") or 0.0) - rtc * trade_qty(t)


def adjusted_metrics(trades: List[Dict[str, Any]], rtc: float) -> Dict[str, float]:
    pnls = [adj_trade_pnl(t, rtc) for t in trades]
    gp = sum(p for p in pnls if p > 0)
    gl = sum(p for p in pnls if p < 0)
    adj_net = sum(pnls)
    adj_pf = gp / abs(gl) if gl < 0 else (1.0 if gp == 0 else 999.0)
    win = (sum(1 for p in pnls if p > 0) / len(pnls) * 100.0) if pnls else 0.0
    eq = peak = 0.0
    mdd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return {"adj_net": adj_net, "adj_pf": adj_pf, "win_rate": win, "max_drawdown": mdd}


def max_consec_losses(trades: List[Dict[str, Any]], rtc: float) -> int:
    best = cur = 0
    for t in trades:
        if adj_trade_pnl(t, rtc) < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def daily_stop_hits(trades: List[Dict[str, Any]], rtc: float, stop_usd: float = 60.0) -> int:
    by_day: Dict[str, float] = defaultdict(float)
    for t in trades:
        ts = str(t.get("exit_time_utc") or t.get("entry_time_utc") or "")
        day = ts[:10]
        if day:
            by_day[day] += adj_trade_pnl(t, rtc)
    return sum(1 for v in by_day.values() if v <= -abs(stop_usd))


def same_bar_pct(trades: List[Dict[str, Any]]) -> float:
    if not trades:
        return 0.0
    same = sum(
        1 for t in trades
        if t.get("entry_time_utc") and t.get("entry_time_utc") == t.get("exit_time_utc")
    )
    return round(same / len(trades) * 100.0, 2)


def read_jobs_for_batch(batch_id: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    pattern = f"{batch_id}__*"
    for d in sorted(JOBS_DONE.glob(pattern)):
        rp = d / "result.json"
        if not rp.exists():
            continue
        try:
            r = json.loads(rp.read_text(encoding="utf-8"))
        except Exception:
            continue
        ctx = r.get("context") or {}
        instrument = ctx.get("instrument") or ""
        period = ctx.get("period") or {}
        params = (ctx.get("strategy") or {}).get("final_parameters") or {}
        rtc = float(params.get("RoundTurnCommission") or 0.0)
        rows.append({
            "job_id": r.get("job_id") or d.name,
            "instrument": instrument,
            "from_utc": period.get("from_utc"),
            "to_utc": period.get("to_utc"),
            "rtc": rtc,
            "session_template": (ctx.get("execution") or {}).get("session_template"),
            "order_fill_resolution": (ctx.get("execution") or {}).get("order_fill_resolution"),
            "slippage_ticks": (ctx.get("execution") or {}).get("slippage_ticks"),
            "trades": r.get("trades") or [],
            "metrics": r.get("metrics") or {},
        })
    return rows


def public_row(*, root: str, module: str, period_label: str, sub: Dict[str, Any],
               canonical: Dict[str, Any], all_contracts: List[str]) -> Dict[str, Any]:
    rtc = canonical["rtc"]
    trades = sorted(
        canonical["trades"],
        key=lambda t: str(t.get("entry_time_utc") or t.get("exit_time_utc") or ""),
    )
    days = MS.trading_weekdays(sub["from_utc"], sub["to_utc"])
    adj = adjusted_metrics(trades, rtc)
    n = len(trades)
    active = len({str(t.get("entry_time_utc") or "")[:10]
                  for t in trades if t.get("entry_time_utc")})
    sh = daily_stop_hits(trades, rtc)
    return {
        "instrument": root,
        "module": module,
        "period_label": period_label,
        "canonical_contract": canonical["instrument"],
        "all_contracts": ",".join(sorted(set(all_contracts))),
        "trades": n,
        "trades_per_day": round(n / days, 2) if days else 0.0,
        "active_days_pct": round(active / days * 100.0, 2) if days else 0.0,
        "adj_net": round(adj["adj_net"], 2),
        "adj_pf": round(adj["adj_pf"], 4),
        "win_rate": round(adj["win_rate"], 2),
        "avg_trade_after_commission": round(adj["adj_net"] / n, 2) if n else 0.0,
        "max_drawdown": round(adj["max_drawdown"], 2),
        "max_consecutive_losses": max_consec_losses(trades, rtc),
        "daily_stop_hits": sh,
        "daily_stop_hit_pct": round(sh / days * 100.0, 2) if days else 0.0,
        "same_bar_pct": same_bar_pct(trades),
        "round_turn_commission": rtc,
        "session_template": canonical.get("session_template"),
        "order_fill_resolution": canonical.get("order_fill_resolution"),
        "slippage_ticks": canonical.get("slippage_ticks"),
        "from_utc": sub["from_utc"],
        "to_utc": sub["to_utc"],
        "job_id": canonical["job_id"],
    }


def classify(row: Dict[str, Any], oos_pf: Optional[float]) -> str:
    if row["period_label"] != "Full":
        return ""
    if row["trades"] <= 0 or row["adj_net"] <= 0 or (row["adj_pf"] or 0.0) < 1.0:
        return "REJECT"
    if oos_pf is not None and oos_pf < 1.0:
        return "REJECT"
    gates = [
        10.0 <= row["trades_per_day"] <= 20.0,
        (row["adj_pf"] or 0.0) >= 1.35,
        (oos_pf or 0.0) >= 1.25,
        row["win_rate"] >= 52.0,
        row["avg_trade_after_commission"] >= 1.50,
        abs(row["max_drawdown"]) <= 300.0,
        row["max_consecutive_losses"] <= 5,
        row["daily_stop_hit_pct"] <= 5.0,
    ]
    if all(gates):
        return "KEEP_MAIN" if row["instrument"].startswith("MNQ") else "KEEP_COPY"
    if row["adj_net"] > 0 and (row["adj_pf"] or 0.0) >= 1.10:
        return "RESEARCH_ONLY"
    return "REJECT"


def confidence(row: Dict[str, Any], oos_pf: Optional[float]) -> int:
    s = 0
    if 10.0 <= row["trades_per_day"] <= 20.0: s += 20
    if (row["adj_pf"] or 0.0) >= 1.35: s += 20
    if (oos_pf or 0.0) >= 1.25: s += 20
    if row["win_rate"] >= 52.0: s += 15
    if row["avg_trade_after_commission"] >= 1.50: s += 10
    if abs(row["max_drawdown"]) <= 300.0: s += 10
    if row["max_consecutive_losses"] <= 5: s += 5
    return s


def collect(bundle: Path) -> int:
    manifest_path = bundle / "full_manifest.json"
    if not manifest_path.exists():
        manifest_path = next(bundle.glob("*_manifest.json"), None)
    if not manifest_path or not manifest_path.exists():
        print(f"No manifest in {bundle}")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    submissions = [s for s in (manifest.get("submitted") or []) if s.get("batch_id")]
    print(f"Loaded {len(submissions)} submissions from {manifest_path.name}")

    rows: List[Dict[str, Any]] = []
    for i, sub in enumerate(submissions):
        bid = sub["batch_id"]
        per_contract = read_jobs_for_batch(bid)
        if not per_contract:
            continue
        # Pick canonical: latest expiry, tiebreak by trade count.
        canonical = max(
            per_contract,
            key=lambda r: (expiry_key(r["instrument"]), len(r["trades"])),
        )
        all_contracts = [r["instrument"] for r in per_contract]
        root = root_of(canonical["instrument"])
        rows.append(public_row(
            root=root, module=sub.get("module") or "", period_label=sub.get("period_label") or "",
            sub=sub, canonical=canonical, all_contracts=all_contracts,
        ))
        if (i+1) % 20 == 0:
            print(f"  processed {i+1}/{len(submissions)}")

    # Compute OOS PF lookup
    oos_pf_by_key = {f"{r['instrument']}|{r['module']}": r["adj_pf"]
                     for r in rows if r["period_label"] == "OOS"}
    for r in rows:
        key = f"{r['instrument']}|{r['module']}"
        r["oos_adj_pf"] = oos_pf_by_key.get(key)
        r["confidence_score"] = confidence(r, r["oos_adj_pf"])
        r["decision"] = classify(r, oos_pf_by_key.get(key))

    rows.sort(key=lambda r: (r["instrument"], r["module"], r["period_label"]))

    # Write outputs
    out_json = bundle / "mnq_scalp_results_HONEST.json"
    out_json.write_text(json.dumps({"rows": rows, "schema": "single-canonical-contract"},
                                   indent=2, ensure_ascii=False), encoding="utf-8")

    cols = [
        "instrument", "module", "period_label", "canonical_contract", "all_contracts",
        "trades", "trades_per_day", "active_days_pct", "adj_net", "adj_pf", "oos_adj_pf",
        "win_rate", "avg_trade_after_commission", "max_drawdown",
        "max_consecutive_losses", "daily_stop_hits", "daily_stop_hit_pct", "same_bar_pct",
        "round_turn_commission", "session_template", "order_fill_resolution",
        "slippage_ticks", "confidence_score", "decision", "from_utc", "to_utc", "job_id",
    ]
    csv_path = bundle / "mnq_scalp_results_HONEST.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # Summary MD: top Full rows ranked by adj_net then trades
    full = [r for r in rows if r["period_label"] == "Full"]
    full.sort(key=lambda r: (-(r["adj_net"] or 0.0), -(r["trades"] or 0)))
    md = ["# NTAMicroMnqScalpPilot — HONEST results (canonical-contract aggregation)", "",
          f"Bundle: `{bundle.name}`  ", f"Rows: {len(rows)}  ", "",
          "## Top Full results (ranked by adj_net, then trades)", "",
          "| Inst | Module | Canonical | Trades | T/d | Adj Net | Adj PF | OOS PF | Avg | DD | Win% | Conf | Decision |",
          "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in full[:30]:
        md.append(
            f"| {r['instrument']} | {r['module']} | {r['canonical_contract']} | {r['trades']} | "
            f"{r['trades_per_day']} | {r['adj_net']} | {r['adj_pf']} | "
            f"{r.get('oos_adj_pf') or '-'} | {r['avg_trade_after_commission']} | "
            f"{r['max_drawdown']} | {r['win_rate']} | {r['confidence_score']} | {r['decision']} |"
        )
    (bundle / "summary_HONEST.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"\nwrote {out_json.name}")
    print(f"wrote {csv_path.name}")
    print(f"wrote summary_HONEST.md")
    return 0


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    return collect(Path(argv[1]).resolve())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
