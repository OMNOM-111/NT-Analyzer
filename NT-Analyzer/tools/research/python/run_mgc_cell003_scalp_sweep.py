"""Search MGC CELL-003 using the already-compiled NTAMicroMnqScalpPilot engine.

The runner is intentionally evidence-first:
  1. submit a focused Full 2024-2025 sweep on MGC 06-26;
  2. recompute metrics from trades after RoundTurnCommission;
  3. stress only variants that clear minimum after-cost Full gates;
  4. write a bundle under data/research/mgc_cell003_scalp_sweep_<ts>/.

Jobs are submitted as role=smoke because the local backend still catalog-flags
Nymex Metals RTH1 as unsupported for research role; execution remains High fill,
slip>=1, commission_template=None, explicit RoundTurnCommission.
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

CLASS_NAME = "NTAMicroMnqScalpPilot"
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
    "stage", "variant", "job_id", "status", "instrument", "from_utc", "to_utc",
    "setup_mode", "direction", "trade_start", "trade_end", "use_second_window",
    "orb_start", "orb_minutes", "min_stop", "max_stop", "rr", "atr_stop",
    "min_adx", "min_volume", "use_time_stop", "time_stop_bars",
    "slippage_ticks", "round_turn_commission", "trade_count", "gross_net",
    "commission_total", "adj_net", "adj_pf", "adj_dd", "win_pct",
    "avg_trade", "same_bar_pct", "active_days", "trades_per_active_day",
]

SETUP_NAMES = {
    0: "VwapPullbackScalp",
    1: "OrbContinuationScalp",
    2: "OrbRetestScalp",
    3: "EmaImpulseScalp",
    4: "FailedOrbReversalScalp",
}

@dataclass(frozen=True)
class Variant:
    name: str
    params: Dict[str, Any]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def job_state(job_id: str) -> Optional[str]:
    base = RL.jobs_root()
    for sub in ("done", "failed", "cancelled", "running", "pending"):
        if (base / sub / job_id).is_dir():
            return sub
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
            print(f"waiting: {len(remaining)} jobs still pending/running")
            last_print = now
        if remaining:
            time.sleep(interval_s)
    return states


def trade_qty(trade: Dict[str, Any]) -> float:
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
    same_bar = 0
    active_days = set()
    gross_net = 0.0
    commission_total = 0.0
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        qty = trade_qty(trade)
        gross = float(trade.get("pnl_currency") or 0.0)
        commission = fee * qty
        pnls.append(gross - commission)
        gross_net += gross
        commission_total += commission
        if trade.get("entry_time_utc") == trade.get("exit_time_utc"):
            same_bar += 1
        day = str(trade.get("entry_time_utc") or trade.get("exit_time_utc") or "")[:10]
        if day:
            active_days.add(day)

    if not pnls:
        trade_count = int(metrics.get("trade_count") or 0)
        gross_net = float(metrics.get("net_profit") or 0.0)
        commission_total = trade_count * fee
        pnls = []

    gross_profit = sum(p for p in pnls if p > 0.0)
    gross_loss = sum(p for p in pnls if p < 0.0)
    adj_net = sum(pnls) if pnls else gross_net - commission_total
    adj_pf = gross_profit / abs(gross_loss) if gross_loss < 0.0 else (math.inf if gross_profit > 0.0 else 0.0)
    win_pct = (sum(1 for p in pnls if p > 0.0) / len(pnls) * 100.0) if pnls else 0.0

    equity = 0.0
    peak = 0.0
    dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        dd = min(dd, equity - peak)

    count = len(pnls) if pnls else int(metrics.get("trade_count") or 0)
    return {
        "trade_count": count,
        "gross_net": round(gross_net, 6),
        "commission_total": round(commission_total, 6),
        "adj_net": round(adj_net, 6),
        "adj_pf": round(adj_pf, 6) if math.isfinite(adj_pf) else 999.0,
        "adj_dd": round(dd, 6),
        "win_pct": round(win_pct, 4),
        "avg_trade": round(adj_net / count, 6) if count else 0.0,
        "same_bar_pct": round(same_bar / count * 100.0, 4) if count else 0.0,
        "active_days": len(active_days),
        "trades_per_active_day": round(count / len(active_days), 4) if active_days else 0.0,
    }


def base_params() -> Dict[str, Any]:
    return {
        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": 200.0,
        "MaxContractsByCapital": 10,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "RiskPerTradePct": 0.6,
        "MaxDailyLossPct": 3.0,
        "MaxDailyLossUsd": 60.0,
        "MaxWeeklyLossUsd": 150.0,
        "MaxDailyProfitPct": 0.0,
        "MaxTradesPerDay": 20,
        "HardMaxTradesPerDay": 25,
        "MaxConsecutiveLosses": 3,
        "PauseAfterConsecutiveLosses": 2,
        "PauseMinutesAfterLosses": 15,
        "UserMaxContracts": 1,
        "MaxOpenPositions": 1,
        "RoundTurnCommission": 1.90,
        "SlippageTicks": 1,
        "UseSetupModeFilter": True,
        "EnableVwapReclaim": False,
        "EnableEmaMomentum": False,
        "EnableMicroOrb": True,
        "EnableFailedBreakout": False,
        "EnableLong": False,
        "EnableShort": True,
        "EmaFastPeriod": 9,
        "EmaMidPeriod": 21,
        "EmaSlowPeriod": 50,
        "AtrPeriod": 14,
        "AdxPeriod": 14,
        "MinAdx": 0.0,
        "VolumeSmaPeriod": 20,
        "MinVolumeFactor": 0.8,
        "PullbackLookback": 3,
        "RequireSlowTrend": False,
        "AtrStopMult": 0.3,
        "MinStopTicks": 6,
        "MaxStopTicks": 12,
        "RewardRiskRatio": 1.5,
        "MoveToBreakevenAtR": 0.7,
        "TrailAfterR": 1.0,
        "UseTimeStop": True,
        "TimeStopBars": 3,
        "MinProgressR": 0.3,
        "EntryTimeoutBars": 2,
        "EntryOffsetTicks": 0,
        "TradeStartTime": 635,
        "TradeEndTime": 830,
        "UseSecondTradeWindow": True,
        "SecondTradeStartTime": 1030,
        "SecondTradeEndTime": 1200,
        "ForceFlatTime": 1245,
        "NewsBlackoutTimes": "",
        "NewsBlackoutWindowMin": 5,
        "OrbStartTime": 630,
        "OrbDurationMinutes": 3,
        "OrbBreakoutBuffer": 1,
        "OrbRetestBars": 5,
        "OrbFailedLookback": 3,
        "EmaImpulseLookback": 3,
    }


def with_direction(params: Dict[str, Any], direction: str) -> None:
    params["EnableLong"] = direction in {"long", "both"}
    params["EnableShort"] = direction in {"short", "both"}


def with_setup(params: Dict[str, Any], setup_mode: int) -> None:
    params["SetupMode"] = setup_mode
    params["EnableVwapReclaim"] = setup_mode == 0
    params["EnableEmaMomentum"] = setup_mode == 3
    params["EnableMicroOrb"] = setup_mode in {1, 2}
    params["EnableFailedBreakout"] = setup_mode == 4


def variant(name: str, **overrides: Any) -> Variant:
    params = base_params()
    direction = str(overrides.pop("Direction", "short"))
    setup_mode = int(overrides.pop("SetupMode", 1))
    with_direction(params, direction)
    with_setup(params, setup_mode)
    params.update(overrides)
    return Variant(name=name, params=params)


def full_variants() -> List[Variant]:
    out: List[Variant] = []
    idx = 0
    for setup_mode in (1, 2):
        for direction in ("short", "long"):
            for orb_start, trade_start, trade_end in ((600, 605, 830), (630, 635, 830), (600, 605, 1000)):
                for orb_minutes in (3, 5, 10):
                    for rr in (1.5, 2.0):
                        idx += 1
                        out.append(variant(
                            f"{idx:02d}_{SETUP_NAMES[setup_mode]}_{direction}_or{orb_start}_{orb_minutes}m_rr{str(rr).replace('.', '')}_to{trade_end}",
                            SetupMode=setup_mode,
                            Direction=direction,
                            OrbStartTime=orb_start,
                            TradeStartTime=trade_start,
                            TradeEndTime=trade_end,
                            OrbDurationMinutes=orb_minutes,
                            RewardRiskRatio=rr,
                            UseSecondTradeWindow=False,
                        ))
    # Focused variants around the initial promising gross ORB-cont branch.
    out.extend([
        variant("f01_orbcont_short_wide_stop_rr20", SetupMode=1, Direction="short", MinStopTicks=8, MaxStopTicks=16, RewardRiskRatio=2.0, UseTimeStop=False, UseSecondTradeWindow=False),
        variant("f02_orbcont_short_wide_stop_rr25", SetupMode=1, Direction="short", MinStopTicks=8, MaxStopTicks=16, RewardRiskRatio=2.5, UseTimeStop=False, UseSecondTradeWindow=False),
        variant("f03_orbcont_short_adx15_vol10", SetupMode=1, Direction="short", MinAdx=15.0, MinVolumeFactor=1.0, RewardRiskRatio=2.0, UseSecondTradeWindow=False),
        variant("f04_orbcont_short_vol12", SetupMode=1, Direction="short", MinVolumeFactor=1.2, RewardRiskRatio=2.0, UseSecondTradeWindow=False),
        variant("f05_orbretest_short_wide_stop_rr20", SetupMode=2, Direction="short", MinStopTicks=8, MaxStopTicks=16, RewardRiskRatio=2.0, UseTimeStop=False, UseSecondTradeWindow=False),
        variant("f06_orbretest_short_wide_stop_rr25", SetupMode=2, Direction="short", MinStopTicks=8, MaxStopTicks=16, RewardRiskRatio=2.5, UseTimeStop=False, UseSecondTradeWindow=False),
        variant("f07_orbcont_both_rr20", SetupMode=1, Direction="both", RewardRiskRatio=2.0, UseSecondTradeWindow=False),
        variant("f08_orbretest_both_rr20", SetupMode=2, Direction="both", RewardRiskRatio=2.0, UseSecondTradeWindow=False),
    ])
    return out


def submit_job(params: Dict[str, Any], from_utc: str, to_utc: str, slippage_ticks: int) -> Tuple[int, Dict[str, Any]]:
    body = RL.build_job_body(
        class_name=CLASS_NAME,
        instrument=INSTRUMENT,
        params=params,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=1,
        slippage_ticks=slippage_ticks,
        role=ROLE,
        session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    return RL.post("/api/jobs", body)


def row_from_report(stage: str, name: str, job_id: str, report: Optional[Dict[str, Any]], fallback_params: Dict[str, Any]) -> Dict[str, Any]:
    if not report or "result" not in report:
        return {"stage": stage, "variant": name, "job_id": job_id, "status": job_state(job_id) or "missing"}
    job = report.get("job") or {}
    result = report.get("result") or {}
    params = (((result.get("context") or {}).get("strategy") or {}).get("final_parameters") or
              ((job.get("strategy") or {}).get("parameters") or fallback_params))
    exec_ = (job.get("execution") or (result.get("context") or {}).get("execution") or {})
    fee = float(params.get("RoundTurnCommission") or fallback_params.get("RoundTurnCommission") or 1.90)
    metrics = adjusted_metrics(report, fee)
    direction = "both" if params.get("EnableLong") and params.get("EnableShort") else ("long" if params.get("EnableLong") else "short")
    setup_mode = int(params.get("SetupMode") or 0)
    return {
        "stage": stage,
        "variant": name,
        "job_id": job_id,
        "status": job_state(job_id) or "unknown",
        "instrument": (job.get("instrument") or (result.get("context") or {}).get("instrument") or INSTRUMENT),
        "from_utc": ((job.get("period") or {}).get("from_utc") or FROM_FULL),
        "to_utc": ((job.get("period") or {}).get("to_utc") or TO_FULL),
        "setup_mode": SETUP_NAMES.get(setup_mode, str(setup_mode)),
        "direction": direction,
        "trade_start": params.get("TradeStartTime"),
        "trade_end": params.get("TradeEndTime"),
        "use_second_window": params.get("UseSecondTradeWindow"),
        "orb_start": params.get("OrbStartTime"),
        "orb_minutes": params.get("OrbDurationMinutes"),
        "min_stop": params.get("MinStopTicks"),
        "max_stop": params.get("MaxStopTicks"),
        "rr": params.get("RewardRiskRatio"),
        "atr_stop": params.get("AtrStopMult"),
        "min_adx": params.get("MinAdx"),
        "min_volume": params.get("MinVolumeFactor"),
        "use_time_stop": params.get("UseTimeStop"),
        "time_stop_bars": params.get("TimeStopBars"),
        "slippage_ticks": exec_.get("slippage_ticks", params.get("SlippageTicks")),
        "round_turn_commission": fee,
        **metrics,
    }


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in CSV_FIELDS})


def score(row: Dict[str, Any]) -> float:
    net = float(row.get("adj_net") or 0.0)
    pf = float(row.get("adj_pf") or 0.0)
    dd = abs(float(row.get("adj_dd") or 0.0))
    trades = int(row.get("trade_count") or 0)
    avg = float(row.get("avg_trade") or 0.0)
    if net <= 0 or pf < 1.0:
        return net - dd
    return net * max(1.0, pf) + trades * 1.5 + avg * 30.0 - dd * 0.25


def select_candidates(rows: List[Dict[str, Any]], limit: int = 4) -> List[Dict[str, Any]]:
    eligible = [
        row for row in rows
        if row.get("status") == "done"
        and int(row.get("trade_count") or 0) >= 50
        and float(row.get("adj_net") or 0.0) > 0.0
        and float(row.get("adj_pf") or 0.0) >= 1.20
        and abs(float(row.get("adj_dd") or 0.0)) <= 300.0
    ]
    eligible.sort(key=score, reverse=True)
    return eligible[:limit]


def current_window() -> Tuple[str, str]:
    front = RL.resolve_front_contract(ROOT)
    start = str(front.get("data_first") or "2026-03-22")
    end = str(front.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    return f"{start}T00:00:00Z", f"{end}T23:59:59Z"


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


def gates(full: Dict[str, Any], stages: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "full_net_positive": float(full.get("adj_net") or 0.0) > 0.0,
        "full_pf_ge_1_35": float(full.get("adj_pf") or 0.0) >= 1.35,
        "full_trades_ge_50": int(full.get("trade_count") or 0) >= 50,
        "full_dd_le_300": abs(float(full.get("adj_dd") or 0.0)) <= 300.0,
        "is_net_positive": float((stages.get("is_2024") or {}).get("adj_net") or 0.0) > 0.0,
        "oos_pf_ge_1_25": float((stages.get("oos_2025") or {}).get("adj_pf") or 0.0) >= 1.25,
        "oos_net_positive": float((stages.get("oos_2025") or {}).get("adj_net") or 0.0) > 0.0,
        "stress_slip2_positive": float((stages.get("stress_slip2") or {}).get("adj_net") or 0.0) > 0.0,
        "stress_fee240_positive": float((stages.get("stress_fee240") or {}).get("adj_net") or 0.0) > 0.0,
        "combined_nonnegative": float((stages.get("stress_slip2_fee240") or {}).get("adj_net") or -999999.0) >= 0.0,
        "current_not_contradictory": int((stages.get("current_mgc0626") or {}).get("trade_count") or 0) >= 2,
    }


def main(argv: List[str]) -> int:
    bundle = RL.DATA / "research" / f"mgc_cell003_scalp_sweep_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}")

    variants = full_variants()
    submitted: List[Dict[str, Any]] = []
    for var in variants:
        code, resp = submit_job(var.params, FROM_FULL, TO_FULL, int(var.params.get("SlippageTicks") or 1))
        job_id = str(resp.get("job_id") or "") if isinstance(resp, dict) else ""
        print(f"submit full {var.name:55s} code={code} job={job_id or resp}")
        submitted.append({"stage": "full", "variant": var.name, "params": var.params, "code": code, "response": resp, "job_id": job_id})
    (bundle / "manifest_full_submit.json").write_text(json.dumps(submitted, indent=2, ensure_ascii=False), encoding="utf-8")

    full_job_ids = [row["job_id"] for row in submitted if row.get("job_id")]
    wait_for_jobs(full_job_ids)

    full_rows: List[Dict[str, Any]] = []
    params_by_variant = {var.name: var.params for var in variants}
    for sub in submitted:
        report = RL.read_job_report(str(sub.get("job_id") or ""))
        full_rows.append(row_from_report("full", str(sub["variant"]), str(sub.get("job_id") or ""), report, params_by_variant[str(sub["variant"])]))
    full_rows.sort(key=score, reverse=True)
    (bundle / "full_rows.json").write_text(json.dumps(full_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(bundle / "full_rows.csv", full_rows)

    print("top full rows:")
    for row in full_rows[:12]:
        print(f"  {row['variant']}: trades={row.get('trade_count')} net={float(row.get('adj_net') or 0.0):.2f} pf={float(row.get('adj_pf') or 0.0):.2f} dd={float(row.get('adj_dd') or 0.0):.2f} avg={float(row.get('avg_trade') or 0.0):.2f}")

    candidates = select_candidates(full_rows)
    print(f"candidates selected: {len(candidates)}")
    stress_submit: List[Dict[str, Any]] = []
    for cand in candidates:
        name = str(cand["variant"])
        params = params_by_variant[name]
        for stage, fr, to, slip, stage_params in stage_plan(params):
            code, resp = submit_job(stage_params, fr, to, slip)
            job_id = str(resp.get("job_id") or "") if isinstance(resp, dict) else ""
            print(f"submit {stage:18s} {name:55s} code={code} job={job_id or resp}")
            stress_submit.append({"stage": stage, "variant": name, "params": stage_params, "code": code, "response": resp, "job_id": job_id})
    (bundle / "manifest_stress_submit.json").write_text(json.dumps(stress_submit, indent=2, ensure_ascii=False), encoding="utf-8")

    stress_job_ids = [row["job_id"] for row in stress_submit if row.get("job_id")]
    if stress_job_ids:
        wait_for_jobs(stress_job_ids)

    stress_rows: List[Dict[str, Any]] = []
    for sub in stress_submit:
        report = RL.read_job_report(str(sub.get("job_id") or ""))
        stress_rows.append(row_from_report(str(sub["stage"]), str(sub["variant"]), str(sub.get("job_id") or ""), report, sub["params"]))
    (bundle / "stress_rows.json").write_text(json.dumps(stress_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(bundle / "stress_rows.csv", stress_rows)

    decisions: List[Dict[str, Any]] = []
    stress_by_variant: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for row in stress_rows:
        stress_by_variant.setdefault(str(row.get("variant")), {})[str(row.get("stage"))] = row
    full_by_variant = {str(row.get("variant")): row for row in full_rows}
    for cand in candidates:
        name = str(cand["variant"])
        gate_map = gates(full_by_variant[name], stress_by_variant.get(name, {}))
        decisions.append({
            "variant": name,
            "ready_pass": all(gate_map.values()),
            "gates": gate_map,
            "full": full_by_variant[name],
            "stages": stress_by_variant.get(name, {}),
            "locked_parameters": params_by_variant[name],
        })
    (bundle / "decisions.json").write_text(json.dumps(decisions, indent=2, ensure_ascii=False), encoding="utf-8")
    (bundle / "manifest.json").write_text(json.dumps({
        "bundle": str(bundle),
        "class_name": CLASS_NAME,
        "instrument": INSTRUMENT,
        "session_template": SESSION_TEMPLATE,
        "role": ROLE,
        "full_submitted": submitted,
        "candidates": candidates,
        "stress_submitted": stress_submit,
        "decisions": decisions,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    winners = [d for d in decisions if d.get("ready_pass")]
    if winners:
        print("READY WINNERS:")
        for win in winners:
            f = win["full"]
            print(f"  {win['variant']}: trades={f['trade_count']} net={f['adj_net']:.2f} pf={f['adj_pf']:.2f} dd={f['adj_dd']:.2f}")
        return 0

    print("no ready winner in this sweep")
    for dec in decisions:
        failed = [key for key, value in dec["gates"].items() if not value]
        print(f"  {dec['variant']} failed: {', '.join(failed)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
