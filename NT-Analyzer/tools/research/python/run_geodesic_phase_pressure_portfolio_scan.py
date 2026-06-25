"""Cross-instrument research for NTAGeodesicPhasePressurePilot.

This is a first-stage research runner. It does not occupy a deploy cell by
itself: it scans the original path-geodesic pressure family across portfolio
micro roots, ranks after-cost smoke results, and can validate top roots through
Full / IS / OOS / stress windows.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402


CLASS_NAME = "NTAGeodesicPhasePressurePilot"
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
    "max_weekly_loss_pct", "max_strategy_dd_pct",
    "phase_lookback", "participation_lookback", "return_scale",
    "volume_log_cap", "torsion_decay", "inertia_blend", "min_arc",
    "min_inefficiency", "min_pressure", "min_coherence", "min_net",
    "min_forecast", "pressure_to_ticks", "cost_multiple", "polarity_mode",
    "rr", "stop_energy", "min_stop", "max_stop", "max_hold_bars",
    "direction",
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
            print(f"waiting: {len(remaining)} geodesic phase-pressure jobs pending/running", flush=True)
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
        "MaxWeeklyLossPct": 6.0,
        "MaxStrategyDrawdownPct": 15.0,
        "MaxTradesPerDay": 8,
        "UserMaxContracts": 5,
        "RoundTurnCommission": RL.fee_for(root),
        "SlippageTicks": 1,
        "EnableLong": True,
        "EnableShort": True,
        "TradeStartTime": 600,
        "TradeEndTime": 1230,
        "ForceFlatTime": 1325,
        "PhaseLookback": 14,
        "ParticipationLookback": 34,
        "ReturnScaleTicks": 8.0,
        "VolumeLogCap": 1.75,
        "TorsionDecay": 0.86,
        "InertiaBlend": 0.35,
        "MinArcTicks": 24.0,
        "MinPathInefficiency": 1.90,
        "MinPhasePressure": 0.45,
        "MinPressureCoherence": 0.24,
        "MinNetTicks": 0.0,
        "MinForecastTicks": 2.0,
        "PressureToForecastTicks": 9.0,
        "CostMultiple": 1.0,
        "PolarityMode": 0,
        "MinBarsBetweenEntries": 2,
        "MinStopTicks": 6,
        "MaxStopTicks": 120,
        "StopEnergyMult": 1.65,
        "RewardRiskRatio": 1.20,
        "MoveToBreakevenAtR": 0.90,
        "TrailAfterR": 1.80,
        "MaxHoldBars": 14,
    }

    if root == "MNQ":
        params.update({"ReturnScaleTicks": 10.0, "MinArcTicks": 35.0, "MinStopTicks": 10, "MaxStopTicks": 130})
    elif root in {"MGC", "MCL"}:
        params.update({"ReturnScaleTicks": 8.0, "MinArcTicks": 28.0, "MinStopTicks": 10, "MaxStopTicks": 150})
    elif root == "MBT":
        params.update({
            "TradeStartTime": 0, "TradeEndTime": 1320, "ForceFlatTime": 1325,
            "ReturnScaleTicks": 28.0, "MinArcTicks": 90.0,
            "MinStopTicks": 30, "MaxStopTicks": 340,
        })
    elif root == "MET":
        params.update({
            "TradeStartTime": 0, "TradeEndTime": 1320, "ForceFlatTime": 1325,
            "ReturnScaleTicks": 16.0, "MinArcTicks": 58.0,
            "MinStopTicks": 20, "MaxStopTicks": 240,
        })
    elif root in {"M6A", "M6B", "M6E", "M6J"}:
        params.update({"ReturnScaleTicks": 3.0, "MinArcTicks": 12.0, "MinStopTicks": 5, "MaxStopTicks": 80})

    return params


def make_variant(root: str, name: str, **overrides: Any) -> Variant:
    params = base_params(root)
    params.update(overrides)
    return Variant(name=name, params=params)


def variants_for(root: str) -> List[Variant]:
    return [
        make_variant(root, "base_phase14_mode0_both"),
        make_variant(root, "strict_pressure_phase18", PhaseLookback=18, MinPhasePressure=0.62, MinPressureCoherence=0.30, MinPathInefficiency=2.15, RewardRiskRatio=1.35),
        make_variant(root, "loose_dense_phase10", PhaseLookback=10, MinPhasePressure=0.32, MinPressureCoherence=0.18, MinPathInefficiency=1.50, RewardRiskRatio=1.05, MaxHoldBars=8),
        make_variant(root, "anti_net_relax_mode1", PolarityMode=1, MinNetTicks=2.0, MinPhasePressure=0.40, MinPathInefficiency=2.10, RewardRiskRatio=1.15),
        make_variant(root, "net_consensus_mode2", PolarityMode=2, MinNetTicks=2.0, MinPhasePressure=0.38, MinPressureCoherence=0.20, RewardRiskRatio=1.25),
        make_variant(root, "net_opposition_mode3", PolarityMode=3, MinNetTicks=2.0, MinPhasePressure=0.38, MinPressureCoherence=0.20, RewardRiskRatio=1.25),
        make_variant(root, "short_pressure_mode0", EnableLong=False, MinPhasePressure=0.38, MinPressureCoherence=0.20, RewardRiskRatio=1.20),
        make_variant(root, "long_pressure_mode0", EnableShort=False, MinPhasePressure=0.38, MinPressureCoherence=0.20, RewardRiskRatio=1.20),
        make_variant(root, "morning_phase_pressure", TradeStartTime=635, TradeEndTime=1000, MinPhasePressure=0.36, MinPressureCoherence=0.20),
        make_variant(root, "midday_phase_pressure", TradeStartTime=900, TradeEndTime=1230, MinPhasePressure=0.36, MinPressureCoherence=0.20),
        make_variant(root, "slow_memory_phase24", PhaseLookback=24, ParticipationLookback=55, TorsionDecay=0.92, MinPhasePressure=0.70, RewardRiskRatio=1.45, MaxHoldBars=20),
        make_variant(root, "fast_decay_phase08", PhaseLookback=8, TorsionDecay=0.72, MinPhasePressure=0.25, MinPressureCoherence=0.16, RewardRiskRatio=0.95, MaxHoldBars=6),
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
    print(f"submit {stage:14s} {spec.root:4s} {variant.name:28s} code={code} job={job_id or resp}", flush=True)
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
        "max_weekly_loss_pct": p.get("MaxWeeklyLossPct"),
        "max_strategy_dd_pct": p.get("MaxStrategyDrawdownPct"),
        "phase_lookback": p.get("PhaseLookback"),
        "participation_lookback": p.get("ParticipationLookback"),
        "return_scale": p.get("ReturnScaleTicks"),
        "volume_log_cap": p.get("VolumeLogCap"),
        "torsion_decay": p.get("TorsionDecay"),
        "inertia_blend": p.get("InertiaBlend"),
        "min_arc": p.get("MinArcTicks"),
        "min_inefficiency": p.get("MinPathInefficiency"),
        "min_pressure": p.get("MinPhasePressure"),
        "min_coherence": p.get("MinPressureCoherence"),
        "min_net": p.get("MinNetTicks"),
        "min_forecast": p.get("MinForecastTicks"),
        "pressure_to_ticks": p.get("PressureToForecastTicks"),
        "cost_multiple": p.get("CostMultiple"),
        "polarity_mode": p.get("PolarityMode"),
        "rr": p.get("RewardRiskRatio"),
        "stop_energy": p.get("StopEnergyMult"),
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
        "PhaseLookback": "phase_lookback",
        "ParticipationLookback": "participation_lookback",
        "ReturnScaleTicks": "return_scale",
        "VolumeLogCap": "volume_log_cap",
        "TorsionDecay": "torsion_decay",
        "InertiaBlend": "inertia_blend",
        "MinArcTicks": "min_arc",
        "MinPathInefficiency": "min_inefficiency",
        "MinPhasePressure": "min_pressure",
        "MinPressureCoherence": "min_coherence",
        "MinNetTicks": "min_net",
        "MinForecastTicks": "min_forecast",
        "PressureToForecastTicks": "pressure_to_ticks",
        "CostMultiple": "cost_multiple",
        "PolarityMode": "polarity_mode",
        "RewardRiskRatio": "rr",
        "StopEnergyMult": "stop_energy",
        "MinStopTicks": "min_stop",
        "MaxStopTicks": "max_stop",
        "MaxHoldBars": "max_hold_bars",
        "TradeStartTime": "trade_start",
        "TradeEndTime": "trade_end",
        "RiskPerTradePct": "risk_pct",
        "MaxWeeklyLossPct": "max_weekly_loss_pct",
        "MaxStrategyDrawdownPct": "max_strategy_dd_pct",
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
            submit_job(spec=spec, variant=variant, stage="StressCombined", from_utc=FROM_FULL, to_utc=TO_FULL, slippage_ticks=2, fee=RL.fee_stress(spec.root)),
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
        "# Geodesic Phase Pressure Portfolio Scan",
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

    lines.extend([
        "",
        "## Decision Rule",
        "",
        "Do not create a deploy wrapper or occupy a CELL unless Full/IS/OOS/stress pass the project gates.",
    ])
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

    bundle = RL.PROJECT_ROOT / "data" / "research" / f"geodesic_phase_pressure_scan_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    smoke_rows = run_smoke(bundle)
    validation_rows: List[Dict[str, Any]] = []
    if args.validate:
        validation_rows = run_validation(bundle, smoke_rows, top_unique_roots=max(1, args.top_unique_roots))
    write_summary(bundle, smoke_rows, validation_rows, args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
