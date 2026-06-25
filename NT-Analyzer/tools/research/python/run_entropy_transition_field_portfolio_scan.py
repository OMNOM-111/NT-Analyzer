"""Cross-instrument research for NTAEntropyTransitionFieldPilot.

The first stage deliberately does not choose a cell. It runs one original
state-transition strategy family across the portfolio micro roots, ranks the
carriers by after-cost metrics, then can validate the strongest rows through
full / IS / OOS / stress windows.
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


CLASS_NAME = "NTAEntropyTransitionFieldPilot"
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
    "window", "min_samples", "neutral_ticks", "return_bucket",
    "body_threshold", "vol_lookback", "vol_low", "vol_high", "use_time",
    "min_forecast", "min_prob", "max_entropy", "min_edge", "cost_multiple",
    "shrinkage", "use_consensus", "consensus_window", "consensus_samples",
    "consensus_prob", "consensus_entropy", "consensus_edge", "field_mode",
    "rr", "stop_sigma", "min_stop", "max_stop", "max_hold_bars", "direction",
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
            print(f"waiting: {len(remaining)} entropy transition jobs pending/running", flush=True)
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
    params: Dict[str, Any] = {
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
        "StateWindow": 260,
        "MinStateSamples": 6,
        "NeutralMoveTicks": 1.0,
        "ReturnBucketTicks": 4.0,
        "BodyBalanceThreshold": 0.25,
        "VolumeLookback": 30,
        "VolumeLowFactor": 0.75,
        "VolumeHighFactor": 1.50,
        "UseTimeState": True,
        "MinForecastTicks": 2.0,
        "MinDirectionalProbability": 0.58,
        "MaxEntropy": 0.88,
        "MinEdgeScore": 0.70,
        "CostMultiple": 1.00,
        "MinBarsBetweenEntries": 1,
        "ShrinkageSamples": 0.0,
        "UseConsensusField": False,
        "ConsensusWindow": 1040,
        "ConsensusMinStateSamples": 20,
        "ConsensusMinDirectionalProbability": 0.58,
        "ConsensusMaxEntropy": 0.92,
        "ConsensusMinEdgeScore": 0.40,
        "FieldMode": 0,
        "MinStopTicks": 6,
        "MaxStopTicks": 80,
        "StopSigmaMult": 1.40,
        "RewardRiskRatio": 1.25,
        "MoveToBreakevenAtR": 0.80,
        "TrailAfterR": 1.60,
        "MaxHoldBars": 12,
    }

    if root == "MNQ":
        params.update({"ReturnBucketTicks": 8.0, "MinForecastTicks": 3.0, "MinStopTicks": 10, "MaxStopTicks": 110})
    elif root in {"MGC", "MCL"}:
        params.update({"ReturnBucketTicks": 8.0, "MinForecastTicks": 4.0, "MinStopTicks": 10, "MaxStopTicks": 120})
    elif root in {"MBT"}:
        params.update({
            "TradeStartTime": 0, "TradeEndTime": 1320, "ForceFlatTime": 1325,
            "ReturnBucketTicks": 25.0, "MinForecastTicks": 10.0,
            "MinStopTicks": 30, "MaxStopTicks": 300,
        })
    elif root in {"MET"}:
        params.update({
            "TradeStartTime": 0, "TradeEndTime": 1320, "ForceFlatTime": 1325,
            "ReturnBucketTicks": 15.0, "MinForecastTicks": 6.0,
            "MinStopTicks": 20, "MaxStopTicks": 220,
        })
    elif root in {"M6A", "M6B", "M6E", "M6J"}:
        params.update({"ReturnBucketTicks": 3.0, "MinForecastTicks": 1.5, "MinStopTicks": 5, "MaxStopTicks": 70})

    return params


def make_variant(root: str, name: str, **overrides: Any) -> Variant:
    params = base_params(root)
    params.update(overrides)
    return Variant(name=name, params=params)


def variants_for(root: str) -> List[Variant]:
    return [
        make_variant(root, "base_w260_ms06_p58_e88_rr125"),
        make_variant(root, "loose_w180_ms04_p55_e95_rr110", StateWindow=180, MinStateSamples=4, MinDirectionalProbability=0.55, MaxEntropy=0.95, MinEdgeScore=0.45, RewardRiskRatio=1.10, MaxHoldBars=10),
        make_variant(root, "strict_w390_ms08_p62_e80_rr140", StateWindow=390, MinStateSamples=8, MinDirectionalProbability=0.62, MaxEntropy=0.80, MinEdgeScore=1.00, RewardRiskRatio=1.40),
        make_variant(root, "dense_notime_w260_ms05_p56_e92", MinStateSamples=5, UseTimeState=False, MinDirectionalProbability=0.56, MaxEntropy=0.92, MinEdgeScore=0.55),
        make_variant(root, "fast_field_w120_ms04_p56_hold06", StateWindow=120, MinStateSamples=4, MinDirectionalProbability=0.56, MaxEntropy=0.90, MaxHoldBars=6, RewardRiskRatio=1.05),
        make_variant(root, "deep_field_w520_ms10_p60_e86", StateWindow=520, MinStateSamples=10, MinDirectionalProbability=0.60, MaxEntropy=0.86, MinEdgeScore=0.85, RewardRiskRatio=1.30),
        make_variant(root, "morning_w260_ms06_p58", TradeStartTime=635, TradeEndTime=1000, MinStateSamples=6, MinDirectionalProbability=0.58),
        make_variant(root, "midday_w260_ms06_p58", TradeStartTime=900, TradeEndTime=1230, MinStateSamples=6, MinDirectionalProbability=0.58),
        make_variant(root, "long_only_w260_ms05_p57", EnableShort=False, MinStateSamples=5, MinDirectionalProbability=0.57, MaxEntropy=0.90),
        make_variant(root, "short_only_w260_ms05_p57", EnableLong=False, MinStateSamples=5, MinDirectionalProbability=0.57, MaxEntropy=0.90),
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
    print(f"submit {stage:14s} {spec.root:4s} {variant.name:34s} code={code} job={job_id or resp}", flush=True)
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
        "window": p.get("StateWindow"),
        "min_samples": p.get("MinStateSamples"),
        "neutral_ticks": p.get("NeutralMoveTicks"),
        "return_bucket": p.get("ReturnBucketTicks"),
        "body_threshold": p.get("BodyBalanceThreshold"),
        "vol_lookback": p.get("VolumeLookback"),
        "vol_low": p.get("VolumeLowFactor"),
        "vol_high": p.get("VolumeHighFactor"),
        "use_time": p.get("UseTimeState"),
        "min_forecast": p.get("MinForecastTicks"),
        "min_prob": p.get("MinDirectionalProbability"),
        "max_entropy": p.get("MaxEntropy"),
        "min_edge": p.get("MinEdgeScore"),
        "cost_multiple": p.get("CostMultiple"),
        "shrinkage": p.get("ShrinkageSamples"),
        "use_consensus": p.get("UseConsensusField"),
        "consensus_window": p.get("ConsensusWindow"),
        "consensus_samples": p.get("ConsensusMinStateSamples"),
        "consensus_prob": p.get("ConsensusMinDirectionalProbability"),
        "consensus_entropy": p.get("ConsensusMaxEntropy"),
        "consensus_edge": p.get("ConsensusMinEdgeScore"),
        "field_mode": p.get("FieldMode"),
        "rr": p.get("RewardRiskRatio"),
        "stop_sigma": p.get("StopSigmaMult"),
        "min_stop": p.get("MinStopTicks"),
        "max_stop": p.get("MaxStopTicks"),
        "max_hold_bars": p.get("MaxHoldBars"),
        "direction": direction,
    }


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def rank_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(r: Dict[str, Any]) -> Tuple[float, float, float, float, float]:
        trades = float(r.get("trade_count") or 0)
        pf = float(r.get("adj_pf") or 0.0)
        dd = abs(float(r.get("adj_dd") or 0.0))
        return (
            1.0 if trades >= 20 else 0.0,
            float(r.get("adj_net") or -1e9),
            1.0 if pf >= 1.15 else 0.0,
            pf,
            -dd,
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


def params_from_smoke_row(row: Dict[str, Any]) -> Dict[str, Any]:
    root = str(row.get("root") or "")
    params = base_params(root)
    field_map = {
        "StateWindow": "window",
        "MinStateSamples": "min_samples",
        "NeutralMoveTicks": "neutral_ticks",
        "ReturnBucketTicks": "return_bucket",
        "BodyBalanceThreshold": "body_threshold",
        "VolumeLookback": "vol_lookback",
        "VolumeLowFactor": "vol_low",
        "VolumeHighFactor": "vol_high",
        "UseTimeState": "use_time",
        "MinForecastTicks": "min_forecast",
        "MinDirectionalProbability": "min_prob",
        "MaxEntropy": "max_entropy",
        "MinEdgeScore": "min_edge",
        "CostMultiple": "cost_multiple",
        "ShrinkageSamples": "shrinkage",
        "UseConsensusField": "use_consensus",
        "ConsensusWindow": "consensus_window",
        "ConsensusMinStateSamples": "consensus_samples",
        "ConsensusMinDirectionalProbability": "consensus_prob",
        "ConsensusMaxEntropy": "consensus_entropy",
        "ConsensusMinEdgeScore": "consensus_edge",
        "FieldMode": "field_mode",
        "RewardRiskRatio": "rr",
        "StopSigmaMult": "stop_sigma",
        "MinStopTicks": "min_stop",
        "MaxStopTicks": "max_stop",
        "MaxHoldBars": "max_hold_bars",
        "TradeStartTime": "trade_start",
        "TradeEndTime": "trade_end",
        "RiskPerTradePct": "risk_pct",
    }
    for param, key in field_map.items():
        value = row.get(key)
        if value not in ("", None):
            params[param] = value
    direction = str(row.get("direction") or "both")
    if direction == "long":
        params["EnableLong"], params["EnableShort"] = True, False
    elif direction == "short":
        params["EnableLong"], params["EnableShort"] = False, True
    else:
        params["EnableLong"], params["EnableShort"] = True, True
    return params


def variant_from_row(row: Dict[str, Any]) -> Variant:
    return Variant(name=str(row.get("variant") or "selected"), params=params_from_smoke_row(row))


def run_validation(bundle: Path, smoke_rows: List[Dict[str, Any]], top_unique_roots: int = 3) -> List[Dict[str, Any]]:
    specs, _ = resolve_instruments()
    spec_by_root = {s.root: s for s in specs}
    selected: List[Dict[str, Any]] = []
    seen_roots = set()
    for row in smoke_rows:
        root = str(row.get("root") or "")
        if root in seen_roots or root not in spec_by_root:
            continue
        if int(row.get("trade_count") or 0) < 10:
            continue
        seen_roots.add(root)
        selected.append(row)
        if len(selected) >= top_unique_roots:
            break

    submissions: List[Dict[str, Any]] = []
    for row in selected:
        spec = spec_by_root[str(row["root"])]
        variant = variant_from_row(row)
        submissions.extend([
            submit_job(spec=spec, variant=variant, stage="Full2024_2025", from_utc=FROM_FULL, to_utc=TO_FULL),
            submit_job(spec=spec, variant=variant, stage="IS2024", from_utc=FROM_IS, to_utc=TO_IS),
            submit_job(spec=spec, variant=variant, stage="OOS2025", from_utc=FROM_OOS, to_utc=TO_OOS),
            submit_job(spec=spec, variant=variant, stage="StressSlip2", from_utc=FROM_FULL, to_utc=TO_FULL, slippage_ticks=2),
            submit_job(spec=spec, variant=variant, stage="StressFee", from_utc=FROM_FULL, to_utc=TO_FULL, fee=RL.fee_stress(spec.root)),
        ])
        cur_from, cur_to = current_window(spec.root)
        submissions.append(submit_job(spec=spec, variant=variant, stage="CurrentFront", from_utc=cur_from, to_utc=cur_to))

    (bundle / "validation_selected.json").write_text(json.dumps(selected, indent=2), encoding="utf-8")
    (bundle / "validation_submissions.json").write_text(json.dumps(submissions, indent=2), encoding="utf-8")
    wait_for_jobs([s["job_id"] for s in submissions if s.get("job_id")])
    rows = rank_rows([row_from_submission(s) for s in submissions])
    write_csv(bundle / "validation_rows.csv", rows)
    (bundle / "validation_rows.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return rows


def write_summary(bundle: Path, smoke_rows: List[Dict[str, Any]], validation_rows: List[Dict[str, Any]], top: int) -> None:
    lines = [
        "# Entropy Transition Field Portfolio Scan",
        "",
        f"- Bundle: `{bundle}`",
        f"- Class: `{CLASS_NAME}`",
        f"- Smoke period: `{FROM_SMOKE}` .. `{TO_SMOKE}`",
        f"- Roots: `{', '.join(ROOTS)}`",
        "",
        "## Smoke Top",
        "",
        "| Rank | Root | Instrument | Variant | Trades | Adj Net | PF | DD | Win % |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in smoke_rows[: max(1, top)]:
        lines.append(
            f"| {r['rank']} | `{r['root']}` | `{r['instrument']}` | `{r['variant']}` | "
            f"{r['trade_count']} | {float(r['adj_net']):.2f} | {float(r['adj_pf']):.2f} | "
            f"{float(r['adj_dd']):.2f} | {float(r['win_pct']):.2f} |"
        )

    if validation_rows:
        lines.extend([
            "",
            "## Validation Rows",
            "",
            "| Rank | Stage | Root | Variant | Trades | Adj Net | PF | DD | Win % |",
            "|---:|---|---|---|---:|---:|---:|---:|---:|",
        ])
        for r in validation_rows:
            lines.append(
                f"| {r['rank']} | `{r['stage']}` | `{r['root']}` | `{r['variant']}` | "
                f"{r['trade_count']} | {float(r['adj_net']):.2f} | {float(r['adj_pf']):.2f} | "
                f"{float(r['adj_dd']):.2f} | {float(r['win_pct']):.2f} |"
            )

    (bundle / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (bundle / "summary.json").write_text(json.dumps({
        "bundle": str(bundle),
        "smoke_top": smoke_rows[: max(1, top)],
        "validation_rows": validation_rows,
    }, indent=2), encoding="utf-8")
    print("\n".join(lines), flush=True)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=12, help="Number of top smoke rows to print")
    ap.add_argument("--validate", action="store_true", help="Run full/IS/OOS/stress validation for top unique roots")
    ap.add_argument("--top-unique-roots", type=int, default=3)
    args = ap.parse_args(argv)

    bundle = RL.PROJECT_ROOT / "data" / "research" / f"entropy_transition_field_scan_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    smoke_rows = run_smoke(bundle)
    validation_rows: List[Dict[str, Any]] = []
    if args.validate:
        validation_rows = run_validation(bundle, smoke_rows, top_unique_roots=max(1, args.top_unique_roots))
    write_summary(bundle, smoke_rows, validation_rows, args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
