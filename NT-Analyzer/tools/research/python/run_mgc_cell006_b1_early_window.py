"""Focused validation for MGC CELL-006 B1 early-window candidate.

The candidate is intentionally close to the already validated MGC B1/VWAP
transfer family, but not a duplicate of an occupied cell:

  - CELL-004 uses stop20 over 06:00-10:00 PT.
  - This runner validates a narrower 06:00-08:00 PT profile for CELL-006.

This keeps the search small and evidence-driven: full sweep over adjacent
parameters, then Full/IS/OOS/stress/current validation for the survivors.
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
TIMEFRAME = 5
CELL_ID = "CELL-006"

FROM_FULL = "2024-01-01T00:00:00Z"
TO_FULL = "2025-12-31T23:59:59Z"
FROM_IS = "2024-01-01T00:00:00Z"
TO_IS = "2024-12-31T23:59:59Z"
FROM_OOS = "2025-01-01T00:00:00Z"
TO_OOS = "2025-12-31T23:59:59Z"

CSV_FIELDS = [
    "variant", "stage", "job_id", "status", "from_utc", "to_utc",
    "trade_count", "trades_per_day", "active_days", "active_days_pct",
    "gross_net", "commission_total", "adj_net", "adj_pf", "adj_dd",
    "win_pct", "avg_trade", "max_consecutive_losses",
    "slippage_ticks", "round_turn_commission", "trade_start", "trade_end",
    "min_stop", "max_stop", "rr", "min_adx", "min_volume",
    "pullback_lookback", "entry_offset",
]


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
            raise TimeoutError(f"timeout waiting for jobs: {sorted(remaining)}")
        for job_id in list(remaining):
            if job_state(job_id) in {"done", "failed", "cancelled"}:
                remaining.remove(job_id)
        now = time.time()
        if remaining and now - last_print >= 30:
            print(f"waiting: {len(remaining)} MGC CELL-006 B1 jobs pending/running", flush=True)
            last_print = now
        if remaining:
            time.sleep(interval_s)


def current_window() -> Tuple[str, str]:
    front = RL.resolve_front_contract(ROOT)
    start = str(front.get("data_first") or "2026-03-22")
    end = str(front.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    return f"{start}T00:00:00Z", f"{end}T23:59:59Z"


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
        "TradeEndTime": 800,
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
        "MinStopTicks": 20,
        "MaxStopTicks": 20,
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
        "RoundTurnCommission": RL.fee_for(ROOT),
        "SlippageTicks": 1,
    })
    return params


def make_variant(name: str, **overrides: Any) -> Variant:
    params = base_params()
    params.update(overrides)
    return Variant(name=name, params=params)


def variants() -> List[Variant]:
    return [
        make_variant("c006_stop20_0600_0800"),
        make_variant("c006_stop18_0600_0800", MinStopTicks=18, MaxStopTicks=18),
        make_variant("c006_stop22_0600_0800", MinStopTicks=22, MaxStopTicks=22),
        make_variant("c006_stop20_0600_0730", TradeEndTime=730),
        make_variant("c006_stop20_0600_0830", TradeEndTime=830),
        make_variant("c006_stop20_vf14_0600_0800", MinVolumeFactor=1.4),
        make_variant("c006_stop20_adx24_0600_0800", MinAdx=24.0),
        make_variant("c006_stop20_rr32_0600_0800", RewardRiskRatio=3.2),
        make_variant("c006_stop20_rr38_0600_0800", RewardRiskRatio=3.8),
        make_variant("c006_stop20_eo1_0600_0800", EntryOffsetTicks=1),
        make_variant("c006_stop20_eo3_0600_0800", EntryOffsetTicks=3),
    ]


def submit_job(
    *,
    variant: Variant,
    stage: str,
    from_utc: str,
    to_utc: str,
    slippage_ticks: int = 1,
    fee: float = 1.90,
) -> Dict[str, Any]:
    params = dict(variant.params)
    params["SlippageTicks"] = slippage_ticks
    params["RoundTurnCommission"] = fee
    body = RL.build_job_body(
        class_name=CLASS_NAME,
        instrument=INSTRUMENT,
        params=params,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=TIMEFRAME,
        slippage_ticks=slippage_ticks,
        role=ROLE,
        session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = str(resp.get("job_id") or "") if code == 201 and isinstance(resp, dict) else ""
    print(f"submit {stage:18s} {variant.name:34s} code={code} job={job_id or resp}", flush=True)
    return {
        "stage": stage,
        "variant": variant.name,
        "params": params,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "slippage_ticks": slippage_ticks,
        "round_turn_commission": fee,
        "code": code,
        "response": resp,
        "job_id": job_id,
    }


def trades_from_report(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = report.get("result") or {}
    trades = result.get("trades")
    if isinstance(trades, list):
        return [t for t in trades if isinstance(t, dict)]
    directory = Path(str(report.get("_dir") or ""))
    p = directory / "trades.json"
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return [t for t in raw if isinstance(t, dict)]
        if isinstance(raw, dict) and isinstance(raw.get("trades"), list):
            return [t for t in raw["trades"] if isinstance(t, dict)]
    return []


def weekdays(from_utc: str, to_utc: str) -> int:
    from datetime import date, timedelta

    start = date.fromisoformat(from_utc[:10])
    end = date.fromisoformat(to_utc[:10])
    total = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            total += 1
        cur += timedelta(days=1)
    return total


def trade_qty(trade: Dict[str, Any]) -> float:
    try:
        return max(1.0, abs(float(trade.get("quantity") or 1.0)))
    except Exception:
        return 1.0


def max_consecutive_losses(pnls: Iterable[float]) -> int:
    best = 0
    cur = 0
    for pnl in pnls:
        if pnl < 0.0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def summarize(submission: Dict[str, Any]) -> Dict[str, Any]:
    job_id = str(submission.get("job_id") or "")
    report = RL.read_job_report(job_id) if job_id else None
    params = submission.get("params") or {}
    row = {
        "variant": submission.get("variant"),
        "stage": submission.get("stage"),
        "job_id": job_id,
        "status": job_state(job_id) if job_id else "missing",
        "from_utc": submission.get("from_utc"),
        "to_utc": submission.get("to_utc"),
        "slippage_ticks": submission.get("slippage_ticks"),
        "round_turn_commission": submission.get("round_turn_commission"),
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
    if not report or "result" not in report:
        row.update({"trade_count": 0, "adj_net": 0.0, "adj_pf": 0.0, "adj_dd": 0.0})
        return row

    fee = float(submission.get("round_turn_commission") or 0.0)
    trades = trades_from_report(report)
    gross_pnls = [float(t.get("pnl_currency") or 0.0) for t in trades]
    pnls = [gross - fee * trade_qty(t) for gross, t in zip(gross_pnls, trades)]
    gross_profit = sum(p for p in pnls if p > 0.0)
    gross_loss = abs(sum(p for p in pnls if p < 0.0))
    adj_pf = gross_profit / gross_loss if gross_loss > 0.0 else (math.inf if gross_profit > 0.0 else 0.0)
    equity = 0.0
    peak = 0.0
    dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    active_days = {
        str(t.get("entry_time_utc") or t.get("exit_time_utc") or "")[:10]
        for t in trades
        if t.get("entry_time_utc") or t.get("exit_time_utc")
    }
    day_count = weekdays(str(row.get("from_utc")), str(row.get("to_utc")))
    count = len(pnls)
    adj_net = sum(pnls)
    row.update({
        "trade_count": count,
        "trades_per_day": round(count / day_count, 4) if day_count else 0.0,
        "active_days": len(active_days),
        "active_days_pct": round(len(active_days) / day_count * 100.0, 4) if day_count else 0.0,
        "gross_net": round(sum(gross_pnls), 6),
        "commission_total": round(sum(fee * trade_qty(t) for t in trades), 6),
        "adj_net": round(adj_net, 6),
        "adj_pf": round(adj_pf, 6) if math.isfinite(adj_pf) else 999.0,
        "adj_dd": round(dd, 6),
        "win_pct": round((sum(1 for p in pnls if p > 0.0) / count * 100.0) if count else 0.0, 4),
        "avg_trade": round(adj_net / count, 6) if count else 0.0,
        "max_consecutive_losses": max_consecutive_losses(pnls),
    })
    return row


def row_score(row: Dict[str, Any]) -> float:
    trades = float(row.get("trade_count") or 0.0)
    net = float(row.get("adj_net") or 0.0)
    pf = float(row.get("adj_pf") or 0.0)
    dd = abs(float(row.get("adj_dd") or 0.0))
    if trades <= 0 or net <= 0.0:
        return -999999.0 + net - dd
    return net + min(pf, 3.0) * 120.0 + min(trades, 80.0) * 2.0 - dd * 0.35


def gate_decision(rows_by_stage: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    full = rows_by_stage.get("Full") or {}
    is_row = rows_by_stage.get("IS") or {}
    oos = rows_by_stage.get("OOS") or {}
    slip2 = rows_by_stage.get("StressSlip2") or {}
    fee240 = rows_by_stage.get("StressFee240") or {}
    combined = rows_by_stage.get("StressSlip2Fee240") or {}
    current = rows_by_stage.get("CurrentContract") or {}
    gates = {
        "full_net_positive": float(full.get("adj_net") or 0.0) > 0.0,
        "full_pf_ge_1_35": float(full.get("adj_pf") or 0.0) >= 1.35,
        "max_dd_pct_15": RL.max_drawdown_within_budget(float(full.get("adj_dd") or 0.0)),
        "full_trades_ge_30": int(full.get("trade_count") or 0) >= 30,
        "is_net_positive": float(is_row.get("adj_net") or 0.0) > 0.0,
        "oos_net_positive": float(oos.get("adj_net") or 0.0) > 0.0,
        "oos_pf_ge_1_25": float(oos.get("adj_pf") or 0.0) >= 1.25,
        "stress_slip2_positive": float(slip2.get("adj_net") or 0.0) > 0.0,
        "stress_fee240_positive": float(fee240.get("adj_net") or 0.0) > 0.0,
        "stress_combined_positive": float(combined.get("adj_net") or 0.0) > 0.0,
        "current_nonnegative": float(current.get("adj_net") or 0.0) >= 0.0,
    }
    current_trades = int(current.get("trade_count") or 0)
    ready_pass = all(gates.values()) and current_trades >= 1
    candidate_pass = all(gates.values())
    warnings = []
    if candidate_pass and current_trades < 1:
        warnings.append("current_contract_sparse_zero_trades")
    return {
        "ready_pass": ready_pass,
        "candidate_pass": candidate_pass,
        "decision": "paper_ready" if ready_pass else ("paper_candidate" if candidate_pass else "research_only"),
        "failed_gates": [key for key, ok in gates.items() if not ok],
        "warnings": warnings,
        "gates": gates,
    }


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def summary_md(bundle: Path, decisions: List[Dict[str, Any]], smoke_rows: List[Dict[str, Any]]) -> str:
    lines = [
        "# MGC CELL-006 B1 Early Window Validation",
        "",
        f"- Bundle: `{bundle}`",
        f"- Class used for research jobs: `{CLASS_NAME}`",
        f"- Instrument: `{INSTRUMENT}`",
        f"- Timeframe: `{TIMEFRAME} Minute`",
        f"- Session template: `{SESSION_TEMPLATE}`",
        "- Hypothesis: narrower 06:00-08:00 PT short-only B1/VWAP pullback reduces late-window noise while preserving the proven MGC B1 edge.",
        "",
        "## Full Sweep",
        "",
        "| Rank | Variant | Trades | Adj Net | Adj PF | Adj DD | Win % |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for idx, row in enumerate(sorted(smoke_rows, key=row_score, reverse=True), start=1):
        lines.append(
            f"| {idx} | `{row.get('variant')}` | {int(row.get('trade_count') or 0)} | "
            f"{float(row.get('adj_net') or 0.0):.2f} | {float(row.get('adj_pf') or 0.0):.2f} | "
            f"{float(row.get('adj_dd') or 0.0):.2f} | {float(row.get('win_pct') or 0.0):.2f} |"
        )
    lines += ["", "## Decisions", ""]
    for dec in decisions:
        full = (dec.get("rows") or {}).get("Full", {})
        oos = (dec.get("rows") or {}).get("OOS", {})
        combined = (dec.get("rows") or {}).get("StressSlip2Fee240", {})
        current = (dec.get("rows") or {}).get("CurrentContract", {})
        lines += [
            f"### `{dec.get('variant')}`",
            "",
            f"- Verdict: **{dec.get('decision')}**",
            f"- Full: `{float(full.get('adj_net') or 0.0):.2f}` / PF `{float(full.get('adj_pf') or 0.0):.2f}` / DD `{float(full.get('adj_dd') or 0.0):.2f}` / trades `{int(full.get('trade_count') or 0)}`",
            f"- OOS: `{float(oos.get('adj_net') or 0.0):.2f}` / PF `{float(oos.get('adj_pf') or 0.0):.2f}`",
            f"- Stress slip2+fee240: `{float(combined.get('adj_net') or 0.0):.2f}` / PF `{float(combined.get('adj_pf') or 0.0):.2f}`",
            f"- Current contract: `{int(current.get('trade_count') or 0)}` trades / `{float(current.get('adj_net') or 0.0):.2f}`",
        ]
        failed = dec.get("failed_gates") or []
        if failed:
            lines.append(f"- Failed gates: `{', '.join(failed)}`")
        warnings = dec.get("warnings") or []
        if warnings:
            lines.append(f"- Warnings: `{', '.join(warnings)}`")
        lines.append("")
    return "\n".join(lines)


def main(argv: List[str]) -> int:
    top_n = 3
    if "--top" in argv:
        top_n = int(argv[argv.index("--top") + 1])

    bundle = RL.DATA / "research" / f"mgc_cell006_b1_early_window_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)

    vars_ = variants()
    by_name = {v.name: v for v in vars_}
    smoke_submissions = [
        submit_job(variant=v, stage="FullSweep", from_utc=FROM_FULL, to_utc=TO_FULL)
        for v in vars_
    ]
    (bundle / "full_sweep_submissions.json").write_text(
        json.dumps(smoke_submissions, indent=2, ensure_ascii=False), encoding="utf-8")
    wait_for_jobs([s.get("job_id") for s in smoke_submissions if s.get("job_id")])
    smoke_rows = [summarize(s) for s in smoke_submissions]
    smoke_rows.sort(key=row_score, reverse=True)
    (bundle / "full_sweep_rows.json").write_text(json.dumps(smoke_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(bundle / "full_sweep_rows.csv", smoke_rows)

    selected = [
        str(r["variant"]) for r in smoke_rows
        if float(r.get("adj_net") or 0.0) > 0.0
        and float(r.get("adj_pf") or 0.0) >= 1.35
        and RL.max_drawdown_within_budget(float(r.get("adj_dd") or 0.0))
        and int(r.get("trade_count") or 0) >= 30
    ][:top_n]
    print("top full sweep rows:", flush=True)
    for row in smoke_rows[:8]:
        print(
            f"  {row['variant']}: trades={row['trade_count']} "
            f"net={float(row.get('adj_net') or 0.0):.2f} "
            f"pf={float(row.get('adj_pf') or 0.0):.2f} "
            f"dd={float(row.get('adj_dd') or 0.0):.2f}",
            flush=True,
        )
    print(f"selected for validation: {selected}", flush=True)

    cur_from, cur_to = current_window()
    stage_defs = [
        ("Full", FROM_FULL, TO_FULL, 1, RL.fee_for(ROOT)),
        ("IS", FROM_IS, TO_IS, 1, RL.fee_for(ROOT)),
        ("OOS", FROM_OOS, TO_OOS, 1, RL.fee_for(ROOT)),
        ("StressSlip2", FROM_FULL, TO_FULL, 2, RL.fee_for(ROOT)),
        ("StressFee240", FROM_FULL, TO_FULL, 1, RL.fee_stress(ROOT)),
        ("StressSlip2Fee240", FROM_FULL, TO_FULL, 2, RL.fee_stress(ROOT)),
        ("CurrentContract", cur_from, cur_to, 1, RL.fee_for(ROOT)),
    ]
    validation_submissions: List[Dict[str, Any]] = []
    for name in selected:
        variant = by_name[name]
        for stage, from_utc, to_utc, slip, fee in stage_defs:
            validation_submissions.append(submit_job(
                variant=variant,
                stage=stage,
                from_utc=from_utc,
                to_utc=to_utc,
                slippage_ticks=slip,
                fee=fee,
            ))
    (bundle / "validation_submissions.json").write_text(
        json.dumps(validation_submissions, indent=2, ensure_ascii=False), encoding="utf-8")
    wait_for_jobs([s.get("job_id") for s in validation_submissions if s.get("job_id")])
    validation_rows = [summarize(s) for s in validation_submissions]
    (bundle / "validation_rows.json").write_text(
        json.dumps(validation_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(bundle / "validation_rows.csv", validation_rows)

    decisions: List[Dict[str, Any]] = []
    for name in selected:
        rows_by_stage = {str(r.get("stage")): r for r in validation_rows if r.get("variant") == name}
        decision = gate_decision(rows_by_stage)
        decision.update({
            "variant": name,
            "class_name": CLASS_NAME,
            "wrapper_class": "B1EarlyWindowMGC5mC006",
            "cell_id": CELL_ID,
            "locked_parameters": by_name[name].params,
            "timeframe": f"{TIMEFRAME} Minute",
            "rows": rows_by_stage,
        })
        decisions.append(decision)
    decisions.sort(
        key=lambda d: (
            bool(d.get("ready_pass")),
            float((d.get("rows") or {}).get("Full", {}).get("adj_net") or 0.0),
            float((d.get("rows") or {}).get("OOS", {}).get("adj_pf") or 0.0),
        ),
        reverse=True,
    )
    summary = {
        "bundle": str(bundle),
        "cell_id": CELL_ID,
        "class_name": CLASS_NAME,
        "wrapper_class": "B1EarlyWindowMGC5mC006",
        "root_family": ROOT,
        "strategy_family": "mgc_b1_transfer",
        "instrument": INSTRUMENT,
        "session_template": SESSION_TEMPLATE,
        "timeframe": f"{TIMEFRAME} Minute",
        "hypothesis": "Short-only B1/VWAP pullback, MGC 06:00-08:00 PT, 20-tick stop, RR 3.5.",
        "selected": selected,
        "decisions": decisions,
    }
    (bundle / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (bundle / "decisions.json").write_text(json.dumps(decisions, indent=2, ensure_ascii=False), encoding="utf-8")
    (bundle / "summary.md").write_text(summary_md(bundle, decisions, smoke_rows), encoding="utf-8")

    print("decisions:", flush=True)
    for d in decisions:
        full = (d.get("rows") or {}).get("Full", {})
        oos = (d.get("rows") or {}).get("OOS", {})
        combo = (d.get("rows") or {}).get("StressSlip2Fee240", {})
        failed = ",".join(d.get("failed_gates") or [])
        print(
            f"  {d['variant']}: {d['decision']} full={float(full.get('adj_net') or 0.0):.2f}/"
            f"PF{float(full.get('adj_pf') or 0.0):.2f} oosPF={float(oos.get('adj_pf') or 0.0):.2f} "
            f"combo={float(combo.get('adj_net') or 0.0):.2f} failed={failed or '-'}",
            flush=True,
        )
    return 0 if any(d.get("candidate_pass") for d in decisions) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
