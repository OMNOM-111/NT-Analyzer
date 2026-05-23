"""Validate MGC CELL-003 5m candidates from the B1/VWAP-pullback family.

This is narrower than the earlier broad B1 clone sweep. It tests only variants
that are materially different from CELL-002's deployed lock and have enough
prior after-cost edge to deserve canonical validation.
"""
from __future__ import annotations

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

CLASS_NAME = "B1ShortOnlyMGC5mV2"
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
    "variant", "stage", "job_id", "status", "from_utc", "to_utc",
    "trade_count", "gross_net", "commission_total", "adj_net", "adj_pf",
    "adj_dd", "win_pct", "avg_trade", "slippage_ticks", "round_turn_commission",
    "trade_start", "trade_end", "min_stop", "max_stop", "rr", "min_adx",
    "min_volume", "pullback_lookback", "entry_offset",
]

@dataclass(frozen=True)
class Variant:
    name: str
    params: Dict[str, Any]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def job_state(job_id: str) -> Optional[str]:
    jobs = RL.jobs_root()
    for sub in ("done", "failed", "cancelled", "running", "pending"):
        if (jobs / sub / job_id).is_dir():
            return sub
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
            if state in {"done", "failed", "cancelled"}:
                states[job_id] = state
                remaining.remove(job_id)
        now = time.time()
        if remaining and now - last_print >= 30:
            print(f"waiting: {len(remaining)} validation jobs still pending/running")
            last_print = now
        if remaining:
            time.sleep(interval_s)
    return states


def base_params() -> Dict[str, Any]:
    params = RL.base_risk_params(ROOT)
    params.update({
        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": 200.0,
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "EnableLong": False,
        "EnableShort": True,
        "TradeStartTime": 600,
        "TradeEndTime": 1000,
        "UseSecondTradeWindow": False,
        "SecondTradeStartTime": 1030,
        "SecondTradeEndTime": 1200,
        "ForceFlatTime": 1245,
        "EmaFastPeriod": 50,
        "EmaSlowPeriod": 200,
        "AtrPeriod": 14,
        "AdxPeriod": 14,
        "MinAdx": 22.0,
        "VolumeSmaPeriod": 20,
        "MinVolumeFactor": 1.2,
        "PullbackLookback": 3,
        "UseDailyBiasFilter": False,
        "AtrStopMult": 0.75,
        "MinStopTicks": 12,
        "MaxStopTicks": 12,
        "RewardRiskRatio": 3.5,
        "MoveToBreakevenAtR": 0.8,
        "TrailAfterR": 1.2,
        "EntryTimeoutBars": 2,
        "EntryOffsetTicks": 2,
        "MaxDailyLossPct": 2.0,
        "MaxDailyProfitPct": 4.0,
        "MaxTradesPerDay": 4,
        "MaxConsecutiveLosses": 3,
        "UserMaxContracts": 5,
        "RoundTurnCommission": 1.90,
        "SlippageTicks": 1,
    })
    return params


def variant(name: str, **overrides: Any) -> Variant:
    params = base_params()
    params.update(overrides)
    return Variant(name, params)


def variants() -> List[Variant]:
    return [
        variant("cell003_vf14_filter", MinVolumeFactor=1.4),
        variant("cell003_stop20_0600_0800", TradeEndTime=800, MinStopTicks=20, MaxStopTicks=20),
        variant("cell003_stop20_0600_1000", MinStopTicks=20, MaxStopTicks=20),
        variant("cell003_stop24_rr30", MinStopTicks=24, MaxStopTicks=24, RewardRiskRatio=3.0),
        variant("cell003_adx26_vf14_0600_0730", TradeEndTime=730, MinAdx=26.0, MinVolumeFactor=1.4),
    ]


def current_window() -> Tuple[str, str]:
    front = RL.resolve_front_contract(ROOT)
    start = str(front.get("data_first") or "2026-03-22")
    end = str(front.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    return f"{start}T00:00:00Z", f"{end}T23:59:59Z"


def stages_for(params: Dict[str, Any]) -> List[Tuple[str, str, str, int, Dict[str, Any]]]:
    cur_from, cur_to = current_window()
    return [
        ("full", FROM_FULL, TO_FULL, 1, dict(params)),
        ("is_2024", FROM_IS, TO_IS, 1, dict(params)),
        ("oos_2025", FROM_OOS, TO_OOS, 1, dict(params)),
        ("stress_slip2", FROM_FULL, TO_FULL, 2, {**params, "SlippageTicks": 2}),
        ("stress_fee240", FROM_FULL, TO_FULL, 1, {**params, "RoundTurnCommission": 2.40}),
        ("stress_slip2_fee240", FROM_FULL, TO_FULL, 2, {**params, "SlippageTicks": 2, "RoundTurnCommission": 2.40}),
        ("current_mgc0626", cur_from, cur_to, 1, dict(params)),
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

    pnls: List[float] = []
    gross_net = 0.0
    commission_total = 0.0
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        qty = trade_quantity(trade)
        gross = float(trade.get("pnl_currency") or 0.0)
        commission = fee * qty
        pnls.append(gross - commission)
        gross_net += gross
        commission_total += commission

    if not pnls:
        trade_count = int(metrics.get("trade_count") or 0)
        gross_net = float(metrics.get("net_profit") or 0.0)
        commission_total = trade_count * fee
        pnls = []

    gross_profit = sum(pnl for pnl in pnls if pnl > 0.0)
    gross_loss = sum(pnl for pnl in pnls if pnl < 0.0)
    adj_net = sum(pnls) if pnls else gross_net - commission_total
    adj_pf = gross_profit / abs(gross_loss) if gross_loss < 0.0 else (999.0 if gross_profit > 0.0 else 0.0)
    equity = 0.0
    peak = 0.0
    dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    count = len(pnls) if pnls else int(metrics.get("trade_count") or 0)
    wins = sum(1 for pnl in pnls if pnl > 0.0)
    return {
        "trade_count": count,
        "gross_net": round(gross_net, 6),
        "commission_total": round(commission_total, 6),
        "adj_net": round(adj_net, 6),
        "adj_pf": round(adj_pf, 6),
        "adj_dd": round(dd, 6),
        "win_pct": round(wins / count * 100.0, 4) if count else 0.0,
        "avg_trade": round(adj_net / count, 6) if count else 0.0,
    }


def row_from_report(entry: Dict[str, Any]) -> Dict[str, Any]:
    job_id = str(entry.get("job_id") or "")
    report = RL.read_job_report(job_id)
    if not report or "result" not in report:
        return {
            "variant": entry.get("variant"),
            "stage": entry.get("stage"),
            "job_id": job_id,
            "status": job_state(job_id) or "missing",
        }
    job = report.get("job") or {}
    params = ((job.get("strategy") or {}).get("parameters") or entry.get("params") or {})
    exec_ = job.get("execution") or {}
    fee = float(params.get("RoundTurnCommission") or entry.get("params", {}).get("RoundTurnCommission") or 1.90)
    return {
        "variant": entry.get("variant"),
        "stage": entry.get("stage"),
        "job_id": job_id,
        "status": job_state(job_id) or "unknown",
        "from_utc": (job.get("period") or {}).get("from_utc"),
        "to_utc": (job.get("period") or {}).get("to_utc"),
        "slippage_ticks": exec_.get("slippage_ticks", params.get("SlippageTicks")),
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
        **adjusted_metrics(report, fee),
    }


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in CSV_FIELDS})


def gates(rows: Dict[str, Dict[str, Any]]) -> Dict[str, bool]:
    full = rows.get("full") or {}
    oos = rows.get("oos_2025") or {}
    slip = rows.get("stress_slip2") or {}
    fee = rows.get("stress_fee240") or {}
    combo = rows.get("stress_slip2_fee240") or {}
    current = rows.get("current_mgc0626") or {}
    return {
        "full_net_positive": float(full.get("adj_net") or 0.0) > 0.0,
        "full_pf_ge_1_35": float(full.get("adj_pf") or 0.0) >= 1.35,
        "full_trades_ge_30": int(full.get("trade_count") or 0) >= 30,
        "full_dd_within_300": abs(float(full.get("adj_dd") or 0.0)) <= 300.0,
        "is_net_positive": float((rows.get("is_2024") or {}).get("adj_net") or 0.0) > 0.0,
        "oos_net_positive": float(oos.get("adj_net") or 0.0) > 0.0,
        "oos_pf_ge_1_25": float(oos.get("adj_pf") or 0.0) >= 1.25,
        "stress_slip2_positive": float(slip.get("adj_net") or 0.0) > 0.0,
        "stress_fee240_positive": float(fee.get("adj_net") or 0.0) > 0.0,
        "combined_stress_positive": float(combo.get("adj_net") or 0.0) > 0.0,
        "current_representative": int(current.get("trade_count") or 0) >= 1,
    }


def score(decision: Dict[str, Any]) -> float:
    rows = decision["rows"]
    full = rows["full"]
    oos = rows["oos_2025"]
    combo = rows["stress_slip2_fee240"]
    current = rows["current_mgc0626"]
    return (
        float(full.get("adj_net") or 0.0)
        + 120.0 * float(full.get("adj_pf") or 0.0)
        + 0.7 * float(oos.get("adj_net") or 0.0)
        + 0.4 * float(combo.get("adj_net") or 0.0)
        + 20.0 * int(current.get("trade_count") or 0)
        - 0.4 * abs(float(full.get("adj_dd") or 0.0))
    )


def main() -> int:
    bundle = RL.DATA / "research" / f"mgc_cell003_b1_validation_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}")

    submitted: List[Dict[str, Any]] = []
    for var in variants():
        for stage, fr, to, slip, params in stages_for(var.params):
            code, resp = submit_job(params, fr, to, slip)
            job_id = str(resp.get("job_id") or "") if isinstance(resp, dict) else ""
            print(f"submit {var.name:32s} {stage:20s} code={code} job={job_id or resp}")
            submitted.append({
                "variant": var.name,
                "stage": stage,
                "params": params,
                "code": code,
                "response": resp,
                "job_id": job_id,
            })
    (bundle / "manifest_submit.json").write_text(json.dumps(submitted, indent=2, ensure_ascii=False), encoding="utf-8")

    job_ids = [entry["job_id"] for entry in submitted if entry.get("job_id")]
    wait_for_jobs(job_ids)

    rows = [row_from_report(entry) for entry in submitted]
    (bundle / "rows.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(bundle / "rows.csv", rows)

    by_variant: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for row in rows:
        by_variant.setdefault(str(row.get("variant")), {})[str(row.get("stage"))] = row

    decisions: List[Dict[str, Any]] = []
    for name, stage_rows in by_variant.items():
        gate_map = gates(stage_rows)
        decisions.append({
            "variant": name,
            "passed": all(gate_map.values()),
            "gates": gate_map,
            "rows": stage_rows,
            "locked_parameters": next(v.params for v in variants() if v.name == name),
        })
    decisions.sort(key=score, reverse=True)
    (bundle / "decisions.json").write_text(json.dumps(decisions, indent=2, ensure_ascii=False), encoding="utf-8")

    print("decision ranking:")
    for dec in decisions:
        full = dec["rows"].get("full", {})
        oos = dec["rows"].get("oos_2025", {})
        combo = dec["rows"].get("stress_slip2_fee240", {})
        current = dec["rows"].get("current_mgc0626", {})
        failed = [key for key, ok in dec["gates"].items() if not ok]
        print(
            f"  {dec['variant']}: pass={dec['passed']} full={float(full.get('adj_net') or 0):.2f}/PF{float(full.get('adj_pf') or 0):.2f}/DD{float(full.get('adj_dd') or 0):.2f} "
            f"oos={float(oos.get('adj_net') or 0):.2f}/PF{float(oos.get('adj_pf') or 0):.2f} "
            f"combo={float(combo.get('adj_net') or 0):.2f} current={int(current.get('trade_count') or 0)}tr/{float(current.get('adj_net') or 0):.2f} "
            f"failed={','.join(failed) if failed else '-'}"
        )
    return 0 if any(dec["passed"] for dec in decisions) else 1


if __name__ == "__main__":
    raise SystemExit(main())
