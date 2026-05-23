"""Validate the final deployed MGC CELL-005 wrapper class.

This runner intentionally tests B1Volume14MGC5mC005 itself, not the generic
research carrier with parameter overrides. Base stages use wrapper defaults;
stress stages override only slippage and/or commission assumptions.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402

CLASS_NAME = "B1Volume14MGC5mC005"
ROOT = "MGC"
INSTRUMENT = "MGC 06-26"
SESSION_TEMPLATE = "Nymex Metals RTH1"
ROLE = "smoke"

FROM_FULL = "2024-01-01T00:00:00Z"
TO_FULL = "2025-12-31T23:59:59Z"
FROM_IS = "2024-01-01T00:00:00Z"
TO_IS = "2024-12-31T23:59:59Z"
FROM_OOS = "2025-01-01T00:00:00Z"
TO_OOS = "2025-12-31T23:59:59Z"

CSV_FIELDS = [
    "stage", "job_id", "status", "from_utc", "to_utc", "trade_count",
    "gross_net", "commission_total", "adj_net", "adj_pf", "adj_dd",
    "win_pct", "avg_trade", "slippage_ticks", "round_turn_commission",
    "trade_start", "trade_end", "min_stop", "max_stop", "rr", "min_adx",
    "min_volume", "pullback_lookback", "entry_offset",
]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def job_state(job_id: str) -> Optional[str]:
    jobs = RL.jobs_root()
    for subdir in ("done", "failed", "cancelled", "running", "pending"):
        if (jobs / subdir / job_id).is_dir():
            return subdir
    quarantine = jobs / "failed" / ".quarantine" / job_id
    if quarantine.is_dir():
        return "failed_quarantined"
    return None


def wait_for_jobs(job_ids: Iterable[str], timeout_s: int = 10800, interval_s: int = 4) -> Dict[str, str]:
    remaining = set(job_ids)
    states: Dict[str, str] = {}
    deadline = time.time() + timeout_s
    last_print = 0.0
    while remaining:
        if time.time() > deadline:
            raise TimeoutError(f"timeout waiting for jobs: {sorted(remaining)}")
        for job_id in list(remaining):
            state = job_state(job_id)
            if state in {"done", "failed", "failed_quarantined", "cancelled"}:
                states[job_id] = state
                remaining.remove(job_id)
        now = time.time()
        if remaining and now - last_print >= 30:
            print(f"waiting: {len(remaining)} wrapper validation jobs still pending/running")
            last_print = now
        if remaining:
            time.sleep(interval_s)
    return states


def current_window() -> Tuple[str, str]:
    front = RL.resolve_front_contract(ROOT)
    start = str(front.get("data_first") or "2026-03-22")
    end = str(front.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    return f"{start}T00:00:00Z", f"{end}T23:59:59Z"


def stages() -> List[Tuple[str, str, str, int, Dict[str, Any]]]:
    current_from, current_to = current_window()
    return [
        ("full", FROM_FULL, TO_FULL, 1, {}),
        ("is_2024", FROM_IS, TO_IS, 1, {}),
        ("oos_2025", FROM_OOS, TO_OOS, 1, {}),
        ("stress_slip2", FROM_FULL, TO_FULL, 2, {"SlippageTicks": 2}),
        ("stress_fee240", FROM_FULL, TO_FULL, 1, {"RoundTurnCommission": 2.40}),
        ("stress_slip2_fee240", FROM_FULL, TO_FULL, 2, {"SlippageTicks": 2, "RoundTurnCommission": 2.40}),
        ("current_mgc0626", current_from, current_to, 1, {}),
    ]


def submit_job(params: Dict[str, Any], from_utc: str, to_utc: str, slippage_ticks: int) -> Tuple[int, Dict[str, Any]]:
    body = RL.build_job_body(
        class_name=CLASS_NAME,
        instrument=INSTRUMENT,
        params=params,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=5,
        slippage_ticks=slippage_ticks,
        role=ROLE,
        session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    return RL.post("/api/jobs", body)


def trade_quantity(trade: Dict[str, Any]) -> float:
    try:
        return max(1.0, abs(float(trade.get("quantity") or 1.0)))
    except Exception:
        return 1.0


def adjusted_metrics(report: Dict[str, Any], fee: float) -> Dict[str, Any]:
    result = report.get("result") or {}
    metrics = result.get("metrics") or {}
    trades = result.get("trades") or []
    if not isinstance(trades, list):
        trades = []

    adjusted_pnls: List[float] = []
    gross_net = 0.0
    commission_total = 0.0
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        quantity = trade_quantity(trade)
        gross = float(trade.get("pnl_currency") or 0.0)
        commission = fee * quantity
        adjusted_pnls.append(gross - commission)
        gross_net += gross
        commission_total += commission

    if not adjusted_pnls:
        trade_count = int(metrics.get("trade_count") or 0)
        gross_net = float(metrics.get("net_profit") or 0.0)
        commission_total = trade_count * fee

    gross_profit = sum(pnl for pnl in adjusted_pnls if pnl > 0.0)
    gross_loss = sum(pnl for pnl in adjusted_pnls if pnl < 0.0)
    adj_net = sum(adjusted_pnls) if adjusted_pnls else gross_net - commission_total
    adj_pf = gross_profit / abs(gross_loss) if gross_loss < 0.0 else (999.0 if gross_profit > 0.0 else 0.0)
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for pnl in adjusted_pnls:
        equity += pnl
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    count = len(adjusted_pnls) if adjusted_pnls else int(metrics.get("trade_count") or 0)
    wins = sum(1 for pnl in adjusted_pnls if pnl > 0.0)
    return {
        "trade_count": count,
        "gross_net": round(gross_net, 6),
        "commission_total": round(commission_total, 6),
        "adj_net": round(adj_net, 6),
        "adj_pf": round(adj_pf, 6),
        "adj_dd": round(drawdown, 6),
        "win_pct": round(wins / count * 100.0, 4) if count else 0.0,
        "avg_trade": round(adj_net / count, 6) if count else 0.0,
    }


def final_parameters(report: Dict[str, Any], submitted_params: Dict[str, Any]) -> Dict[str, Any]:
    result = report.get("result") or {}
    context = result.get("context") or {}
    strategy = context.get("strategy") or {}
    params = strategy.get("final_parameters") or submitted_params
    return params if isinstance(params, dict) else submitted_params


def row_from_report(entry: Dict[str, Any]) -> Dict[str, Any]:
    job_id = str(entry.get("job_id") or "")
    report = RL.read_job_report(job_id)
    if not report or "result" not in report:
        return {"stage": entry.get("stage"), "job_id": job_id, "status": job_state(job_id) or "missing"}
    job = report.get("job") or {}
    params = final_parameters(report, entry.get("params") or {})
    execution = job.get("execution") or {}
    fee = float(params.get("RoundTurnCommission") or entry.get("params", {}).get("RoundTurnCommission") or 1.90)
    row = {
        "stage": entry.get("stage"),
        "job_id": job_id,
        "status": job_state(job_id) or "unknown",
        "from_utc": (job.get("period") or {}).get("from_utc"),
        "to_utc": (job.get("period") or {}).get("to_utc"),
        "slippage_ticks": execution.get("slippage_ticks", params.get("SlippageTicks")),
        "round_turn_commission": fee,
        "trade_start": params.get("TradeStartTime"),
        "trade_end": params.get("TradeEndTime"),
        "min_stop": params.get("MinStopTicks"),
        "max_stop": params.get("MaxStopTicks"),
        "rr": params.get("RewardRiskRatio"),
        "min_adx": params.get("MinAdx"),
        "min_volume": params.get("MinVolumeFactor"),
        "pullback_lookback": params.get("PullbackLookback"),
        "entry_offset": params.get("EntryOffsetTicks"),
    }
    row.update(adjusted_metrics(report, fee))
    return row


def gates(rows_by_stage: Dict[str, Dict[str, Any]]) -> Dict[str, bool]:
    full = rows_by_stage.get("full", {})
    oos = rows_by_stage.get("oos_2025", {})
    is_2024 = rows_by_stage.get("is_2024", {})
    slip = rows_by_stage.get("stress_slip2", {})
    fee = rows_by_stage.get("stress_fee240", {})
    combined = rows_by_stage.get("stress_slip2_fee240", {})
    current = rows_by_stage.get("current_mgc0626", {})
    return {
        "full_net_positive": float(full.get("adj_net") or 0.0) > 0.0,
        "full_pf_ge_1_35": float(full.get("adj_pf") or 0.0) >= 1.35,
        "full_trades_ge_30": int(full.get("trade_count") or 0) >= 30,
        "full_dd_within_300": abs(float(full.get("adj_dd") or 0.0)) <= 300.0,
        "is_net_positive": float(is_2024.get("adj_net") or 0.0) > 0.0,
        "oos_net_positive": float(oos.get("adj_net") or 0.0) > 0.0,
        "oos_pf_ge_1_25": float(oos.get("adj_pf") or 0.0) >= 1.25,
        "stress_slip2_positive": float(slip.get("adj_net") or 0.0) > 0.0,
        "stress_fee240_positive": float(fee.get("adj_net") or 0.0) > 0.0,
        "combined_stress_positive": float(combined.get("adj_net") or 0.0) > 0.0,
        "current_representative": int(current.get("trade_count") or 0) >= 1,
    }


def main() -> int:
    bundle = RL.PROJECT_ROOT / "data" / "research" / f"mgc_cell005_wrapper_validation_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)

    manifest: List[Dict[str, Any]] = []
    job_ids: List[str] = []
    for stage, from_utc, to_utc, slippage_ticks, params in stages():
        code, response = submit_job(params, from_utc, to_utc, slippage_ticks)
        job_id = str(response.get("job_id") or "")
        entry = {
            "stage": stage,
            "params": params,
            "code": code,
            "response": response,
            "job_id": job_id,
        }
        manifest.append(entry)
        if code not in (200, 201, 202) or not job_id:
            print(f"submit failed {stage}: code={code} response={response}")
            (bundle / "manifest_submit.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            return 2
        job_ids.append(job_id)
        print(f"submitted {stage}: {job_id}")

    (bundle / "manifest_submit.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    wait_for_jobs(job_ids)

    rows = [row_from_report(entry) for entry in manifest]
    rows_by_stage = {str(row.get("stage")): row for row in rows}
    gate_map = gates(rows_by_stage)
    decision = {
        "class_name": CLASS_NAME,
        "passed": all(gate_map.values()),
        "gates": gate_map,
        "rows": rows_by_stage,
    }

    (bundle / "rows.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    with (bundle / "rows.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in CSV_FIELDS})
    (bundle / "decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")

    print(f"bundle={bundle}")
    for row in rows:
        print(
            f"{row.get('stage')}: trades={row.get('trade_count')} "
            f"adj={row.get('adj_net')} pf={row.get('adj_pf')} dd={row.get('adj_dd')} "
            f"job={row.get('job_id')}"
        )
    failed = [name for name, ok in gate_map.items() if not ok]
    print(f"passed={decision['passed']} failed={failed}")
    return 0 if decision["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

