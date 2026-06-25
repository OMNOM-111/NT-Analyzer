"""Research MGC CELL-004 long-only VWAP pullback continuation carrier.

The first pass intentionally avoids new trading logic.  It uses the compiled
VWAPPullbackMGC5mV1 wrapper as a carrier over NTAMicroSessionEdgeExplorer and
overrides only NinjaScript parameters at job submission time:
SetupMode=VwapPullback, EnableLong=true, EnableShort=false.

Outputs a reproducible bundle under data/research/mgc_cell004_long_pullback_<ts>/.
"""
from __future__ import annotations

import csv
import json
import math
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402

CLASS_NAME = "VWAPPullbackMGC5mV1"
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

MIN_FREQ_TRADES = 120
TARGET_FREQ_TRADES = 180
BUNDLE_NAME = "mgc_cell004_long_pullback"

CSV_FIELDS = [
    "stage", "variant", "job_id", "status", "from_utc", "to_utc",
    "trade_count", "trade_days", "trades_per_active_day",
    "median_trades_per_active_day", "pct_active_days_with_2plus_trades",
    "gross_net", "commission_total", "adj_net", "adj_pf", "adj_dd",
    "win_pct", "avg_trade", "slippage_ticks", "round_turn_commission",
    "trade_start", "trade_end", "use_second_window", "second_start",
    "second_end", "min_stop", "max_stop", "rr", "min_adx",
    "min_volume", "pullback_lookback", "entry_offset", "daily_bias",
    "block_longs_when_daily_bearish", "max_trades_per_day",
]


@dataclass(frozen=True)
class Variant:
    name: str
    params: Dict[str, Any]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def job_state(job_id: str) -> Optional[str]:
    jobs = RL.jobs_root()
    for subdir in ("done", "failed", "cancelled", "running", "pending"):
        if (jobs / subdir / job_id).is_dir():
            return subdir
    if (jobs / "failed" / ".quarantine" / job_id).is_dir():
        return "failed"
    return None


def wait_for_jobs(job_ids: Iterable[str], timeout_s: int = 14400, interval_s: int = 4) -> Dict[str, str]:
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
            print(f"waiting: {len(remaining)} CELL-004 jobs still pending/running")
            last_print = now
        if remaining:
            time.sleep(interval_s)
    return states


def base_params() -> Dict[str, Any]:
    params = RL.base_risk_params(ROOT)
    params.update({
        "SetupMode": "VwapPullback",
        "EnableLong": True,
        "EnableShort": False,
        "TradeStartTime": 600,
        "TradeEndTime": 930,
        "UseSecondTradeWindow": False,
        "SecondTradeStartTime": 1030,
        "SecondTradeEndTime": 1200,
        "ForceFlatTime": 1245,
        "MinAdx": 20.0,
        "MinVolumeFactor": 1.10,
        "PullbackLookback": 3,
        "MinStopTicks": 12,
        "MaxStopTicks": 12,
        "RewardRiskRatio": 2.5,
        "EntryOffsetTicks": 1,
        "EntryTimeoutBars": 2,
        "MaxTradesPerDay": 4,
        "UseDailyBiasFilter": False,
        "BlockShortsWhenDailyBullish": True,
        "BlockLongsWhenDailyBearish": True,
        "RoundTurnCommission": 1.90,
        "SlippageTicks": 1,
    })
    return params


def variant(name: str, **overrides: Any) -> Variant:
    params = base_params()
    params.update(overrides)
    return Variant(name=name, params=params)


def full_variants() -> List[Variant]:
    variants: List[Variant] = []
    for trade_end in (830, 930, 1000):
        for use_second in (False, True):
            for min_adx, min_volume in ((18.0, 1.05), (20.0, 1.10), (22.0, 1.20), (24.0, 1.30)):
                variants.append(variant(
                    f"c004_te{trade_end}_sw{int(use_second)}_adx{int(min_adx)}_vf{str(min_volume).replace('.', '')}_s12_rr25_e1",
                    TradeEndTime=trade_end,
                    UseSecondTradeWindow=use_second,
                    MinAdx=min_adx,
                    MinVolumeFactor=min_volume,
                    MinStopTicks=12,
                    MaxStopTicks=12,
                    RewardRiskRatio=2.5,
                    EntryOffsetTicks=1,
                ))

    for stop_ticks in (10, 12, 14, 16):
        for rr in (2.0, 2.5, 3.0):
            for entry_offset in (1, 2):
                variants.append(variant(
                    f"c004_core_stop{stop_ticks}_rr{str(rr).replace('.', '')}_e{entry_offset}",
                    TradeEndTime=930,
                    UseSecondTradeWindow=True,
                    MinAdx=20.0,
                    MinVolumeFactor=1.10,
                    MinStopTicks=stop_ticks,
                    MaxStopTicks=stop_ticks,
                    RewardRiskRatio=rr,
                    EntryOffsetTicks=entry_offset,
                ))

    for min_adx, min_volume, stop_ticks, rr in (
        (18.0, 1.05, 10, 2.0),
        (18.0, 1.10, 12, 2.0),
        (20.0, 1.05, 14, 2.5),
        (20.0, 1.20, 16, 2.5),
        (22.0, 1.10, 14, 3.0),
        (24.0, 1.05, 16, 3.0),
    ):
        variants.append(variant(
            f"c004_bias_adx{int(min_adx)}_vf{str(min_volume).replace('.', '')}_s{stop_ticks}_rr{str(rr).replace('.', '')}",
            TradeEndTime=1000,
            UseSecondTradeWindow=True,
            MinAdx=min_adx,
            MinVolumeFactor=min_volume,
            MinStopTicks=stop_ticks,
            MaxStopTicks=stop_ticks,
            RewardRiskRatio=rr,
            EntryOffsetTicks=1,
            UseDailyBiasFilter=True,
            BlockLongsWhenDailyBearish=True,
        ))
    return variants


def current_window() -> Tuple[str, str]:
    front = RL.resolve_front_contract(ROOT)
    start = str(front.get("data_first") or "2026-03-22")
    end = str(front.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    return f"{start}T00:00:00Z", f"{end}T23:59:59Z"


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


def median_int(values: List[int]) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2:
        return float(values[mid])
    return (values[mid - 1] + values[mid]) / 2.0


def adjusted_metrics(report: Dict[str, Any], fee: float) -> Dict[str, Any]:
    result = report.get("result") or {}
    metrics = result.get("metrics") or {}
    trades = result.get("trades") or []
    if not isinstance(trades, list):
        trades = []

    pnls: List[float] = []
    gross_net = 0.0
    commission_total = 0.0
    active_days: Counter[str] = Counter()
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        qty = trade_quantity(trade)
        gross = float(trade.get("pnl_currency") or 0.0)
        commission = fee * qty
        pnls.append(gross - commission)
        gross_net += gross
        commission_total += commission
        day = str(trade.get("entry_time_utc") or trade.get("exit_time_utc") or "")[:10]
        if day:
            active_days[day] += 1

    if not pnls:
        trade_count = int(metrics.get("trade_count") or 0)
        gross_net = float(metrics.get("net_profit") or 0.0)
        commission_total = trade_count * fee

    gross_profit = sum(pnl for pnl in pnls if pnl > 0.0)
    gross_loss = sum(pnl for pnl in pnls if pnl < 0.0)
    adj_net = sum(pnls) if pnls else gross_net - commission_total
    adj_pf = gross_profit / abs(gross_loss) if gross_loss < 0.0 else (math.inf if gross_profit > 0.0 else 0.0)
    equity = 0.0
    peak = 0.0
    dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        dd = min(dd, equity - peak)

    count = len(pnls) if pnls else int(metrics.get("trade_count") or 0)
    wins = sum(1 for pnl in pnls if pnl > 0.0)
    daily_counts = list(active_days.values())
    trade_days = len(daily_counts)
    pct_2plus = (sum(1 for value in daily_counts if value >= 2) / trade_days * 100.0) if trade_days else 0.0
    return {
        "trade_count": count,
        "trade_days": trade_days,
        "trades_per_active_day": round(count / trade_days, 6) if trade_days else 0.0,
        "median_trades_per_active_day": round(median_int(daily_counts), 6),
        "pct_active_days_with_2plus_trades": round(pct_2plus, 6),
        "gross_net": round(gross_net, 6),
        "commission_total": round(commission_total, 6),
        "adj_net": round(adj_net, 6),
        "adj_pf": round(adj_pf, 6) if math.isfinite(adj_pf) else 999.0,
        "adj_dd": round(dd, 6),
        "win_pct": round(wins / count * 100.0, 4) if count else 0.0,
        "avg_trade": round(adj_net / count, 6) if count else 0.0,
    }


def final_parameters(report: Dict[str, Any], fallback_params: Dict[str, Any]) -> Dict[str, Any]:
    result = report.get("result") or {}
    context = result.get("context") or {}
    strategy = context.get("strategy") or {}
    params = strategy.get("final_parameters") or ((report.get("job") or {}).get("strategy") or {}).get("parameters")
    return params if isinstance(params, dict) else fallback_params


def row_from_report(stage: str, name: str, job_id: str, report: Optional[Dict[str, Any]], fallback_params: Dict[str, Any]) -> Dict[str, Any]:
    if not report or "result" not in report:
        return {"stage": stage, "variant": name, "job_id": job_id, "status": job_state(job_id) or "missing"}
    job = report.get("job") or {}
    params = final_parameters(report, fallback_params)
    execution = job.get("execution") or {}
    fee = float(params.get("RoundTurnCommission") or fallback_params.get("RoundTurnCommission") or 1.90)
    row = {
        "stage": stage,
        "variant": name,
        "job_id": job_id,
        "status": job_state(job_id) or "unknown",
        "from_utc": (job.get("period") or {}).get("from_utc"),
        "to_utc": (job.get("period") or {}).get("to_utc"),
        "slippage_ticks": execution.get("slippage_ticks", params.get("SlippageTicks")),
        "round_turn_commission": fee,
        "trade_start": params.get("TradeStartTime"),
        "trade_end": params.get("TradeEndTime"),
        "use_second_window": params.get("UseSecondTradeWindow"),
        "second_start": params.get("SecondTradeStartTime"),
        "second_end": params.get("SecondTradeEndTime"),
        "min_stop": params.get("MinStopTicks"),
        "max_stop": params.get("MaxStopTicks"),
        "rr": params.get("RewardRiskRatio"),
        "min_adx": params.get("MinAdx"),
        "min_volume": params.get("MinVolumeFactor"),
        "pullback_lookback": params.get("PullbackLookback"),
        "entry_offset": params.get("EntryOffsetTicks"),
        "daily_bias": params.get("UseDailyBiasFilter"),
        "block_longs_when_daily_bearish": params.get("BlockLongsWhenDailyBearish"),
        "max_trades_per_day": params.get("MaxTradesPerDay"),
    }
    row.update(adjusted_metrics(report, fee))
    return row


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in CSV_FIELDS})


def score_full(row: Dict[str, Any]) -> float:
    net = float(row.get("adj_net") or 0.0)
    pf = float(row.get("adj_pf") or 0.0)
    dd = abs(float(row.get("adj_dd") or 0.0))
    trades = int(row.get("trade_count") or 0)
    active_rate = float(row.get("trades_per_active_day") or 0.0)
    pct_2plus = float(row.get("pct_active_days_with_2plus_trades") or 0.0)
    freq_bonus = min(trades, TARGET_FREQ_TRADES) * 2.0 + active_rate * 30.0 + pct_2plus
    if net <= 0.0 or pf < 1.0:
        return net - dd + freq_bonus * 0.2
    return net + 160.0 * pf + freq_bonus - 0.5 * dd


def select_candidates(rows: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    eligible = [
        row for row in rows
        if row.get("status") == "done"
        and float(row.get("adj_net") or 0.0) > 0.0
        and float(row.get("adj_pf") or 0.0) >= 1.20
        and abs(float(row.get("adj_dd") or 0.0)) <= 500.0
        and int(row.get("trade_count") or 0) >= MIN_FREQ_TRADES
    ]
    if not eligible:
        eligible = [
            row for row in rows
            if row.get("status") == "done"
            and float(row.get("adj_net") or 0.0) > 0.0
            and float(row.get("adj_pf") or 0.0) >= 1.10
            and int(row.get("trade_count") or 0) > 67
        ]
    eligible.sort(key=score_full, reverse=True)
    return eligible[:limit]


def stage_plan(params: Dict[str, Any]) -> List[Tuple[str, str, str, int, Dict[str, Any]]]:
    cur_from, cur_to = current_window()
    return [
        ("is_2024", FROM_IS, TO_IS, 1, dict(params)),
        ("oos_2025", FROM_OOS, TO_OOS, 1, dict(params)),
        ("stress_slip2", FROM_FULL, TO_FULL, 2, {**params, "SlippageTicks": 2}),
        ("stress_fee240", FROM_FULL, TO_FULL, 1, {**params, "RoundTurnCommission": 2.40}),
        ("stress_slip2_fee240", FROM_FULL, TO_FULL, 2, {**params, "SlippageTicks": 2, "RoundTurnCommission": 2.40}),
        ("current_mgc0626", cur_from, cur_to, 1, dict(params)),
    ]


def gates(full: Dict[str, Any], stages: Dict[str, Dict[str, Any]]) -> Dict[str, bool]:
    is_2024 = stages.get("is_2024") or {}
    oos = stages.get("oos_2025") or {}
    slip = stages.get("stress_slip2") or {}
    fee = stages.get("stress_fee240") or {}
    combined = stages.get("stress_slip2_fee240") or {}
    current = stages.get("current_mgc0626") or {}
    return {
        "full_net_positive": float(full.get("adj_net") or 0.0) > 0.0,
        "full_pf_ge_1_35": float(full.get("adj_pf") or 0.0) >= 1.35,
        "full_trade_count_ge_120": int(full.get("trade_count") or 0) >= MIN_FREQ_TRADES,
        "full_trade_count_ge_existing_mgc": int(full.get("trade_count") or 0) > 67,
        "full_frequency_target_180": int(full.get("trade_count") or 0) >= TARGET_FREQ_TRADES,
        "max_dd_pct_15": RL.max_drawdown_within_budget(float(full.get("adj_dd") or 0.0)),
        "is_net_positive": float(is_2024.get("adj_net") or 0.0) > 0.0,
        "oos_net_positive": float(oos.get("adj_net") or 0.0) > 0.0,
        "oos_pf_ge_1_25": float(oos.get("adj_pf") or 0.0) >= 1.25,
        "stress_slip2_positive": float(slip.get("adj_net") or 0.0) > 0.0,
        "stress_fee240_positive": float(fee.get("adj_net") or 0.0) > 0.0,
        "combined_stress_positive": float(combined.get("adj_net") or 0.0) > 0.0,
        "current_representative": int(current.get("trade_count") or 0) >= 1 and float(current.get("adj_net") or 0.0) >= 0.0,
    }


def load_resume_bundle(argv: List[str]) -> Optional[Path]:
    if len(argv) == 3 and argv[1] == "--resume-bundle":
        return Path(argv[2]).resolve()
    if len(argv) != 1:
        raise SystemExit("usage: run_mgc_cell004_long_pullback_carrier.py [--resume-bundle PATH]")
    return None


def main(argv: List[str]) -> int:
    resume_bundle = load_resume_bundle(argv)
    bundle = resume_bundle or (RL.DATA / "research" / f"{BUNDLE_NAME}_{utc_stamp()}")
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}")
    variants = full_variants()
    print(f"full variants: {len(variants)}")

    if resume_bundle:
        submitted = json.loads((bundle / "manifest_full_submit.json").read_text(encoding="utf-8"))
        print(f"resuming submitted full jobs: {len(submitted)}")
    else:
        submitted: List[Dict[str, Any]] = []
        for var in variants:
            code, response = submit_job(var.params, FROM_FULL, TO_FULL, int(var.params.get("SlippageTicks") or 1))
            job_id = str(response.get("job_id") or "") if isinstance(response, dict) else ""
            print(f"submit full {var.name:58s} code={code} job={job_id or response}")
            submitted.append({"stage": "full", "variant": var.name, "params": var.params, "code": code, "response": response, "job_id": job_id})
        (bundle / "manifest_full_submit.json").write_text(json.dumps(submitted, indent=2, ensure_ascii=False), encoding="utf-8")

    full_job_ids = [entry["job_id"] for entry in submitted if entry.get("job_id")]
    wait_for_jobs(full_job_ids)

    full_rows: List[Dict[str, Any]] = []
    params_by_variant = {var.name: var.params for var in variants}
    for entry in submitted:
        job_id = str(entry.get("job_id") or "")
        report = RL.read_job_report(job_id)
        full_rows.append(row_from_report("full", str(entry["variant"]), job_id, report, params_by_variant[str(entry["variant"])]))
    full_rows.sort(key=score_full, reverse=True)
    (bundle / "full_rows.json").write_text(json.dumps(full_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(bundle / "full_rows.csv", full_rows)

    print("top full rows:")
    for row in full_rows[:15]:
        print(
            f"  {row['variant']}: trades={row.get('trade_count')} days={row.get('trade_days')} "
            f"tpad={float(row.get('trades_per_active_day') or 0.0):.2f} "
            f"2plus={float(row.get('pct_active_days_with_2plus_trades') or 0.0):.1f}% "
            f"net={float(row.get('adj_net') or 0.0):.2f} pf={float(row.get('adj_pf') or 0.0):.2f} "
            f"dd={float(row.get('adj_dd') or 0.0):.2f}"
        )

    candidates = select_candidates(full_rows)
    print(f"candidates selected: {len(candidates)}")
    stress_submit: List[Dict[str, Any]] = []
    for candidate in candidates:
        name = str(candidate["variant"])
        params = params_by_variant[name]
        for stage, from_utc, to_utc, slippage_ticks, stage_params in stage_plan(params):
            code, response = submit_job(stage_params, from_utc, to_utc, slippage_ticks)
            job_id = str(response.get("job_id") or "") if isinstance(response, dict) else ""
            print(f"submit {stage:20s} {name:58s} code={code} job={job_id or response}")
            stress_submit.append({"stage": stage, "variant": name, "params": stage_params, "code": code, "response": response, "job_id": job_id})
    (bundle / "manifest_stress_submit.json").write_text(json.dumps(stress_submit, indent=2, ensure_ascii=False), encoding="utf-8")

    stress_job_ids = [entry["job_id"] for entry in stress_submit if entry.get("job_id")]
    if stress_job_ids:
        wait_for_jobs(stress_job_ids)

    stress_rows: List[Dict[str, Any]] = []
    for entry in stress_submit:
        job_id = str(entry.get("job_id") or "")
        report = RL.read_job_report(job_id)
        stress_rows.append(row_from_report(str(entry["stage"]), str(entry["variant"]), job_id, report, entry["params"]))
    (bundle / "stress_rows.json").write_text(json.dumps(stress_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(bundle / "stress_rows.csv", stress_rows)

    stress_by_variant: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for row in stress_rows:
        stress_by_variant.setdefault(str(row.get("variant")), {})[str(row.get("stage"))] = row
    full_by_variant = {str(row.get("variant")): row for row in full_rows}

    decisions: List[Dict[str, Any]] = []
    for candidate in candidates:
        name = str(candidate["variant"])
        gate_map = gates(full_by_variant[name], stress_by_variant.get(name, {}))
        decisions.append({
            "variant": name,
            "ready_pass": all(gate_map.values()),
            "gates": gate_map,
            "full": full_by_variant[name],
            "stages": stress_by_variant.get(name, {}),
            "locked_parameters": params_by_variant[name],
        })
    decisions.sort(key=lambda item: score_full(item["full"]), reverse=True)
    (bundle / "decisions.json").write_text(json.dumps(decisions, indent=2, ensure_ascii=False), encoding="utf-8")
    (bundle / "manifest.json").write_text(json.dumps({
        "bundle": str(bundle),
        "class_name": CLASS_NAME,
        "instrument": INSTRUMENT,
        "session_template": SESSION_TEMPLATE,
        "role": ROLE,
        "frequency_notes": {
            "existing_ready_mgc_trade_counts": [67, 57, 58],
            "minimum_for_selection": MIN_FREQ_TRADES,
            "soft_target": TARGET_FREQ_TRADES,
        },
        "full_submitted": submitted,
        "candidates": candidates,
        "stress_submitted": stress_submit,
        "decisions": decisions,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    winners = [decision for decision in decisions if decision.get("ready_pass")]
    if winners:
        print("READY CARRIER WINNERS:")
        for winner in winners:
            full = winner["full"]
            print(
                f"  {winner['variant']}: trades={full.get('trade_count')} days={full.get('trade_days')} "
                f"net={float(full.get('adj_net') or 0.0):.2f} pf={float(full.get('adj_pf') or 0.0):.2f} "
                f"dd={float(full.get('adj_dd') or 0.0):.2f}"
            )
        return 0

    print("no ready carrier winner in this sweep")
    for decision in decisions:
        failed = [key for key, ok in decision["gates"].items() if not ok]
        full = decision["full"]
        print(
            f"  {decision['variant']} failed: {', '.join(failed)}; "
            f"full trades={full.get('trade_count')} net={full.get('adj_net')} pf={full.get('adj_pf')} dd={full.get('adj_dd')}"
        )
    return 0 if decisions else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
