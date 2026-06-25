"""Cross-instrument research for NTACapitulationSnapbackPilot.

Phase 1 deliberately does not choose a cell. It runs one new strategy family
across the portfolio micro roots, then ranks instruments by after-cost metrics.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402


CLASS_NAME = "NTACapitulationSnapbackPilot"
ROOTS = ["MES", "MNQ", "MYM", "M2K", "MGC", "MCL", "M6A", "M6B", "M6E", "M6J", "MBT", "MET"]
TIMEFRAME = 5
ROLE = "smoke"

FROM_SMOKE = "2025-01-01T00:00:00Z"
TO_SMOKE = "2025-12-31T23:59:59Z"
FROM_FULL = "2024-01-01T00:00:00Z"
TO_FULL = "2025-12-31T23:59:59Z"
FROM_IS = "2024-01-01T00:00:00Z"
TO_IS = "2024-12-31T23:59:59Z"
FROM_OOS = "2025-01-01T00:00:00Z"
TO_OOS = "2025-12-31T23:59:59Z"

CSV_FIELDS = [
    "rank", "root", "instrument", "variant", "stage", "job_id", "status",
    "from_utc", "to_utc", "trade_count", "trades_per_day", "active_days",
    "gross_net", "commission_total", "adj_net", "adj_pf", "adj_dd",
    "win_pct", "avg_trade", "max_consecutive_losses", "slippage_ticks",
    "round_turn_commission", "trade_start", "trade_end", "risk_pct",
    "min_volume", "shock_atr", "extension_atr", "reclaim_fraction",
    "rr", "max_hold_bars", "direction", "max_adx", "confirm_body",
    "no_extreme_break", "reclaim_prev_open", "vwap_reclaim",
]


@dataclass(frozen=True)
class InstrumentSpec:
    root: str
    instrument: str
    session_template: str


@dataclass(frozen=True)
class Variant:
    name: str
    params: Dict[str, Any]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def job_state(job_id: str) -> Optional[str]:
    base = RL.jobs_root()
    for state in ("done", "failed", "cancelled", "running", "pending"):
        if (base / state / job_id).is_dir():
            return state
    if (base / "failed" / ".quarantine" / job_id).is_dir():
        return "failed"
    return None


def wait_for_jobs(job_ids: Iterable[str], timeout_s: int = 14400, interval_s: int = 4) -> None:
    remaining = {j for j in job_ids if j}
    deadline = time.time() + timeout_s
    last_print = 0.0
    while remaining:
        if time.time() > deadline:
            raise TimeoutError(f"timeout waiting for jobs: {sorted(remaining)[:10]}")
        for job_id in list(remaining):
            if job_state(job_id) in {"done", "failed", "cancelled"}:
                remaining.remove(job_id)
        now = time.time()
        if remaining and now - last_print >= 30:
            print(f"waiting: {len(remaining)} capitulation snapback jobs pending/running", flush=True)
            last_print = now
        if remaining:
            time.sleep(interval_s)


def current_window(root: str) -> Tuple[str, str]:
    front = RL.resolve_front_contract(root)
    start = str(front.get("data_first") or "2026-03-01")
    end = str(front.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    return f"{start}T00:00:00Z", f"{end}T23:59:59Z"


def resolve_instruments() -> Tuple[List[InstrumentSpec], List[Dict[str, Any]]]:
    specs: List[InstrumentSpec] = []
    skipped: List[Dict[str, Any]] = []
    for root in ROOTS:
        try:
            front = RL.resolve_front_contract(root)
            instrument = str(front.get("instrument") or front.get("symbol") or "")
            if not instrument:
                skipped.append({"root": root, "reason": "no_front_contract"})
                continue
            specs.append(InstrumentSpec(root=root, instrument=instrument, session_template=RL.session_for(root)))
        except Exception as exc:
            skipped.append({"root": root, "reason": str(exc)})
    return specs, skipped


def base_params(root: str) -> Dict[str, Any]:
    params = {
        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": RL.margin_for(root),
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "RiskPerTradePct": 1.0,
        "MaxDailyLossPct": 3.0,
        "MaxDailyProfitPct": 0.0,
        "MaxTradesPerDay": 8,
        "UserMaxContracts": 5,
        "RoundTurnCommission": RL.fee_for(root),
        "SlippageTicks": 1,
        "EnableLong": True,
        "EnableShort": True,
        "TradeStartTime": 600,
        "TradeEndTime": 1230,
        "ForceFlatTime": 1325,
        "AtrPeriod": 14,
        "AdxPeriod": 14,
        "EmaPeriod": 50,
        "VolumeSmaPeriod": 20,
        "MinAdx": 0.0,
        "MaxAdx": 100.0,
        "MinVolumeFactor": 1.8,
        "ShockAtrMult": 1.2,
        "ExtensionAtr": 0.9,
        "MinBodyFraction": 0.55,
        "ReclaimFraction": 0.35,
        "ExtremeLookbackBars": 12,
        "MinConfirmBodyFraction": 0.0,
        "RequireNoExtremeBreak": False,
        "RequireReclaimPrevOpen": False,
        "RequireVwapReclaim": False,
        "MinStopTicks": 8,
        "MaxStopTicks": 80,
        "StopBufferTicks": 2,
        "RewardRiskRatio": 1.25,
        "MoveToBreakevenAtR": 0.8,
        "TrailAfterR": 1.6,
        "MaxHoldBars": 18,
    }
    if root in {"MBT", "MET"}:
        params.update({"TradeStartTime": 0, "TradeEndTime": 1320, "ForceFlatTime": 1325, "MaxStopTicks": 300})
    if root in {"MGC", "MCL"}:
        params.update({"MinStopTicks": 10, "MaxStopTicks": 120})
    return params


def make_variant(root: str, name: str, **overrides: Any) -> Variant:
    params = base_params(root)
    params.update(overrides)
    return Variant(name=name, params=params)


def variants_for(root: str) -> List[Variant]:
    return [
        make_variant(root, "base_both_v18_sh120_ext09_rr125"),
        make_variant(root, "loose_both_v14_sh100_ext07_rr110", MinVolumeFactor=1.4, ShockAtrMult=1.0, ExtensionAtr=0.7, RewardRiskRatio=1.1),
        make_variant(root, "strict_both_v22_sh140_ext11_rr140", MinVolumeFactor=2.2, ShockAtrMult=1.4, ExtensionAtr=1.1, RewardRiskRatio=1.4),
        make_variant(root, "morning_both_v16_sh110_ext08_rr125", TradeStartTime=635, TradeEndTime=1000, MinVolumeFactor=1.6, ShockAtrMult=1.1, ExtensionAtr=0.8),
        make_variant(root, "midday_both_v18_sh120_ext09_rr125", TradeStartTime=900, TradeEndTime=1230),
        make_variant(root, "long_only_v16_sh110_ext08_rr120", EnableShort=False, MinVolumeFactor=1.6, ShockAtrMult=1.1, ExtensionAtr=0.8, RewardRiskRatio=1.2),
        make_variant(root, "short_only_v16_sh110_ext08_rr120", EnableLong=False, MinVolumeFactor=1.6, ShockAtrMult=1.1, ExtensionAtr=0.8, RewardRiskRatio=1.2),
        make_variant(root, "fast_exit_v18_rr100_hold08", RewardRiskRatio=1.0, MaxHoldBars=8),
        make_variant(root, "aggressive_risk15_v16_rr150", RiskPerTradePct=1.5, MinVolumeFactor=1.6, RewardRiskRatio=1.5, MaxTradesPerDay=10),
    ]


def submit_job(
    *,
    spec: InstrumentSpec,
    variant: Variant,
    stage: str,
    from_utc: str,
    to_utc: str,
    slippage_ticks: int = 1,
    fee: Optional[float] = None,
) -> Dict[str, Any]:
    params = dict(variant.params)
    params["SlippageTicks"] = slippage_ticks
    params["RoundTurnCommission"] = RL.fee_for(spec.root) if fee is None else fee
    body = RL.build_job_body(
        class_name=CLASS_NAME,
        instrument=spec.instrument,
        params=params,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=TIMEFRAME,
        slippage_ticks=slippage_ticks,
        role=ROLE,
        session_template=spec.session_template,
        risk_profile=RL.build_risk_profile_for([spec.instrument]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = str(resp.get("job_id") or "") if code == 201 and isinstance(resp, dict) else ""
    print(f"submit {stage:14s} {spec.root:4s} {variant.name:36s} code={code} job={job_id or resp}", flush=True)
    return {
        "stage": stage,
        "root": spec.root,
        "instrument": spec.instrument,
        "session_template": spec.session_template,
        "variant": variant.name,
        "params": params,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "slippage_ticks": slippage_ticks,
        "round_turn_commission": params["RoundTurnCommission"],
        "code": code,
        "response": resp,
        "job_id": job_id,
    }


def trades_from_report(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = report.get("result") or {}
    trades = result.get("trades")
    if isinstance(trades, list):
        return [t for t in trades if isinstance(t, dict)]
    p = Path(str(report.get("_dir") or "")) / "trades.json"
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [t for t in data if isinstance(t, dict)]
        except Exception:
            return []
    return []


def adjusted_metrics(report: Dict[str, Any], fee: float) -> Dict[str, Any]:
    trades = trades_from_report(report)
    if not trades:
        result = report.get("result") or {}
        raw = result.get("metrics") or {}
        return {
            "trade_count": int(raw.get("trade_count") or 0),
            "gross_net": float(raw.get("net_profit") or 0.0),
            "commission_total": 0.0,
            "adj_net": 0.0,
            "adj_pf": 0.0,
            "adj_dd": float(raw.get("max_drawdown") or 0.0),
            "win_pct": 0.0,
            "avg_trade": 0.0,
            "max_consecutive_losses": 0,
            "active_days": 0,
            "trades_per_day": 0.0,
        }

    adj_pnls: List[float] = []
    gross_net = 0.0
    commission_total = 0.0
    active_days = set()
    for t in trades:
        pnl = float(t.get("pnl_currency") or 0.0)
        qty = abs(int(float(t.get("quantity") or 1)))
        comm = fee * max(1, qty)
        gross_net += pnl
        commission_total += comm
        adj_pnls.append(pnl - comm)
        ts = str(t.get("exit_time_utc") or t.get("entry_time_utc") or "")[:10]
        if ts:
            active_days.add(ts)

    wins = [p for p in adj_pnls if p > 0]
    losses = [p for p in adj_pnls if p < 0]
    pf = sum(wins) / abs(sum(losses)) if losses else (999.0 if wins else 0.0)
    equity = 0.0
    peak = 0.0
    dd = 0.0
    max_loss_streak = 0
    cur_loss_streak = 0
    for p in adj_pnls:
        equity += p
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
        if p < 0:
            cur_loss_streak += 1
            max_loss_streak = max(max_loss_streak, cur_loss_streak)
        else:
            cur_loss_streak = 0

    return {
        "trade_count": len(adj_pnls),
        "gross_net": round(gross_net, 2),
        "commission_total": round(commission_total, 2),
        "adj_net": round(sum(adj_pnls), 2),
        "adj_pf": round(pf, 6),
        "adj_dd": round(dd, 2),
        "win_pct": round(100.0 * len(wins) / len(adj_pnls), 4),
        "avg_trade": round(sum(adj_pnls) / len(adj_pnls), 6),
        "max_consecutive_losses": max_loss_streak,
        "active_days": len(active_days),
        "trades_per_day": round(len(adj_pnls) / max(1, len(active_days)), 4),
    }


def row_from_submission(sub: Dict[str, Any]) -> Dict[str, Any]:
    job_id = sub.get("job_id") or ""
    report = RL.read_job_report(job_id) if job_id else None
    state = job_state(job_id) if job_id else "submit_failed"
    metrics = adjusted_metrics(report or {}, float(sub.get("round_turn_commission") or 0.0))
    p = sub.get("params") or {}
    direction = "both"
    if p.get("EnableLong") and not p.get("EnableShort"):
        direction = "long"
    elif p.get("EnableShort") and not p.get("EnableLong"):
        direction = "short"
    return {
        "rank": "",
        "root": sub.get("root"),
        "instrument": sub.get("instrument"),
        "variant": sub.get("variant"),
        "stage": sub.get("stage"),
        "job_id": job_id,
        "status": state,
        "from_utc": sub.get("from_utc"),
        "to_utc": sub.get("to_utc"),
        **metrics,
        "slippage_ticks": sub.get("slippage_ticks"),
        "round_turn_commission": sub.get("round_turn_commission"),
        "trade_start": p.get("TradeStartTime"),
        "trade_end": p.get("TradeEndTime"),
        "risk_pct": p.get("RiskPerTradePct"),
        "min_volume": p.get("MinVolumeFactor"),
        "shock_atr": p.get("ShockAtrMult"),
        "extension_atr": p.get("ExtensionAtr"),
        "reclaim_fraction": p.get("ReclaimFraction"),
        "rr": p.get("RewardRiskRatio"),
        "max_hold_bars": p.get("MaxHoldBars"),
        "direction": direction,
        "max_adx": p.get("MaxAdx"),
        "confirm_body": p.get("MinConfirmBodyFraction"),
        "no_extreme_break": p.get("RequireNoExtremeBreak"),
        "reclaim_prev_open": p.get("RequireReclaimPrevOpen"),
        "vwap_reclaim": p.get("RequireVwapReclaim"),
    }


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def rank_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(r: Dict[str, Any]) -> Tuple[float, float, float, float]:
        trades = float(r.get("trade_count") or 0)
        return (
            1.0 if trades >= 20 else 0.0,
            float(r.get("adj_net") or -1e9),
            float(r.get("adj_pf") or 0.0),
            -abs(float(r.get("adj_dd") or 0.0)),
        )
    ranked = sorted(rows, key=key, reverse=True)
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i
    return ranked


def run_smoke(bundle: Path) -> List[Dict[str, Any]]:
    specs, skipped = resolve_instruments()
    submissions: List[Dict[str, Any]] = []
    for spec in specs:
        for variant in variants_for(spec.root):
            submissions.append(submit_job(
                spec=spec,
                variant=variant,
                stage="Smoke2025",
                from_utc=FROM_SMOKE,
                to_utc=TO_SMOKE,
            ))

    (bundle / "skipped_instruments.json").write_text(json.dumps(skipped, indent=2), encoding="utf-8")
    (bundle / "smoke_submissions.json").write_text(json.dumps(submissions, indent=2), encoding="utf-8")
    wait_for_jobs([s["job_id"] for s in submissions if s.get("job_id")])
    rows = rank_rows([row_from_submission(s) for s in submissions])
    write_csv(bundle / "smoke_rows.csv", rows)
    (bundle / "smoke_rows.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return rows


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=8, help="Number of top smoke rows to print")
    args = ap.parse_args(argv)

    bundle = RL.PROJECT_ROOT / "data" / "research" / f"capitulation_snapback_portfolio_scan_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    rows = run_smoke(bundle)

    top = rows[: max(1, args.top)]
    lines = [
        "# Capitulation Snapback Portfolio Smoke",
        "",
        f"- Bundle: `{bundle}`",
        f"- Class: `{CLASS_NAME}`",
        f"- Period: `{FROM_SMOKE}` .. `{TO_SMOKE}`",
        f"- Roots: `{', '.join(ROOTS)}`",
        "",
        "| Rank | Root | Instrument | Variant | Trades | Adj Net | PF | DD | Win % |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in top:
        lines.append(
            f"| {r['rank']} | `{r['root']}` | `{r['instrument']}` | `{r['variant']}` | "
            f"{r['trade_count']} | {float(r['adj_net']):.2f} | {float(r['adj_pf']):.2f} | "
            f"{float(r['adj_dd']):.2f} | {float(r['win_pct']):.2f} |"
        )
    (bundle / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (bundle / "summary.json").write_text(json.dumps({"bundle": str(bundle), "top": top}, indent=2), encoding="utf-8")

    print("\n".join(lines), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
