"""Research runner for MGC CELL-006 morning-range sweep fade (late free window).

Hypothesis (independent of failed SessionEdge modes):
  After existing gold profiles trade ~06:00-10:00 PT, the 06:00-10:00 opening
  range becomes the liquidity anchor.  In the free window 10:00-13:25 PT, fade
  brief sweeps beyond that range and target session VWAP (VwapThenRR / VwapOnly).

Carrier: NTAMicroGoldSessionSweepReversalPilot (gold-specific sweep engine).
"""
from __future__ import annotations

import csv
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402


CLASS_NAME = "NTAMicroGoldSessionSweepReversalPilot"
ROOT = "MGC"
CURRENT_CONTRACT = "MGC 06-26"
SESSION_TEMPLATE = RL.session_for(ROOT)
CELL_ID = "CELL-006"
DISPLAY_NAME = "MGC Late Morning Sweep Fade 1m v1 c006"
TIMEFRAME = 1

FULL = ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z")
IS = ("IS", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z")
OOS = ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z")

BASELINE_FAILED = {
    "variant": "failedorbreversal_long_1m_1030_1325_s12_rr18",
    "full_adj_net": -957.6,
    "full_adj_pf": 0.499869,
}

CSV_FIELDS = [
    "stage", "variant", "timeframe", "from_utc", "to_utc", "job_id",
    "trade_count", "trades_per_day", "active_days", "active_days_pct",
    "adj_net", "adj_pf", "adj_dd", "win_pct", "avg_trade",
    "max_consecutive_losses", "slippage_ticks", "round_turn_commission",
    "anchor_mode", "target_mode", "direction", "trade_start", "trade_end",
    "force_flat", "or_minutes", "rr", "min_stop", "max_stop", "min_volume",
]


@dataclass(frozen=True)
class Variant:
    name: str
    params: Dict[str, Any]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def current_window(days: Optional[int] = 60) -> Tuple[str, str]:
    front = RL.resolve_front_contract(ROOT)
    end_raw = str(front.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    end_day = datetime.fromisoformat(end_raw[:10]).date()
    start_day = date(2026, 1, 1) if days is None else end_day - timedelta(days=days)
    return f"{start_day.isoformat()}T00:00:00Z", f"{end_day.isoformat()}T23:59:59Z"


def job_state(job_id: str) -> Optional[str]:
    base = RL.jobs_root()
    for state in ("done", "failed", "cancelled", "running", "pending"):
        if (base / state / job_id).is_dir():
            return state
    if (base / "failed" / ".quarantine" / job_id).is_dir():
        return "failed"
    return None


def wait_for_jobs(job_ids: Iterable[str], timeout_s: int = 21600, interval_s: int = 4) -> None:
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
            print(f"waiting: {len(remaining)} MGC CELL-006 sweep jobs still pending/running", flush=True)
            last_print = now
        if remaining:
            time.sleep(interval_s)


def base_params() -> Dict[str, Any]:
    return {
        "InstrumentName": ROOT,
        "ContractName": CURRENT_CONTRACT,
        "SessionTemplateName": SESSION_TEMPLATE,
        "BaseTimeframeSeconds": TIMEFRAME * 60,

        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": RL.margin_for(ROOT),
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",

        "EnableLong": True,
        "EnableShort": True,
        "AnchorMode": "OpeningRange",
        "TargetMode": "VwapThenRR",

        "TradeStartTime": 1000,
        "TradeEndTime": 1325,
        "ForceFlatTime": 1330,
        "OpeningRangeStartTime": 600,
        "OpeningRangeMinutes": 240,

        "EmaFastPeriod": 9,
        "EmaSlowPeriod": 34,
        "AtrPeriod": 14,
        "AdxPeriod": 14,
        "VolumeSmaPeriod": 20,
        "MinAdx": 0.0,
        "MinVolumeFactor": 1.0,
        "MinBodyRangePct": 0.25,
        "MinCloseLocationPct": 0.55,
        "UseTrendFilter": False,
        "UseVwapSideFilter": True,
        "MinDistanceToVwapTicks": 3,

        "SweepDistanceTicks": 2,
        "ReturnInsideTicks": 1,
        "SweepMaxBarsToReturn": 3,
        "MinOpeningRangeTicks": 6,
        "MaxOpeningRangeTicks": 280,

        "StopBeyondSweepTicks": 2,
        "ClampStopToMaxTicks": True,
        "MinStopTicks": 10,
        "MaxStopTicks": 14,
        "AtrStopMult": 0.35,
        "RewardRiskRatio": 2.0,
        "EntryOffsetTicks": 1,
        "EntryTimeoutBars": 2,
        "MinTargetTicks": 8,
        "VwapTargetOffsetTicks": 1,
        "TimeStopBars": 8,
        "MinProgressR": 0.12,

        "RiskPerTradePct": 1.0,
        "UserMaxContracts": 1,
        "MaxOpenPositions": 1,
        "DailyLossLimit": 60.0,
        "WeeklyLossLimit": 150.0,
        "MaxTradesPerDay": 4,
        "HardMaxTradesPerDay": 6,
        "MaxConsecutiveLosses": 3,
        "PauseAfterConsecutiveLosses": 2,
        "PauseMinutesAfterLosses": 15,
        "RoundTurnCommission": RL.fee_for(ROOT),
        "SlippageTicks": 1,
    }


def make_variant(name: str, *, direction: str = "both", **overrides: Any) -> Variant:
    params = base_params()
    params["EnableLong"] = direction in {"long", "both"}
    params["EnableShort"] = direction in {"short", "both"}
    params.update(overrides)
    return Variant(name=name, params=params)


def full_variants() -> List[Variant]:
    """Focused grid — morning OR sweep fade with trade-producing parameter bands."""
    out: List[Variant] = []

    for direction in ("long", "short", "both"):
        for target in ("VwapThenRR", "VwapOnly", "FixedRR"):
            for stop, rr in ((10, 2.0), (12, 2.5)):
                out.append(make_variant(
                    f"msweep_{direction}_1000_1325_or240_{target.lower()}_s{stop}_rr{str(rr).replace('.', '')}",
                    direction=direction,
                    TradeStartTime=1000,
                    TradeEndTime=1325,
                    OpeningRangeStartTime=600,
                    OpeningRangeMinutes=240,
                    AnchorMode="OpeningRange",
                    TargetMode=target,
                    MinStopTicks=stop,
                    MaxStopTicks=stop,
                    RewardRiskRatio=rr,
                ))

    for direction in ("long", "short", "both"):
        for stop, rr in ((10, 2.0), (12, 2.0)):
            out.append(make_variant(
                f"msweep_{direction}_1000_1325_preopen30_{stop}_rr{str(rr).replace('.', '')}",
                direction=direction,
                TradeStartTime=1000,
                TradeEndTime=1325,
                OpeningRangeStartTime=930,
                OpeningRangeMinutes=30,
                AnchorMode="OpeningRange",
                TargetMode="VwapThenRR",
                MinStopTicks=stop,
                MaxStopTicks=stop,
                RewardRiskRatio=rr,
                MaxOpeningRangeTicks=90,
            ))

    for direction in ("long", "short"):
        out.append(make_variant(
            f"msweep_{direction}_1000_1325_prior_s10_rr20",
            direction=direction,
            AnchorMode="PriorSession",
            TargetMode="VwapThenRR",
            MinStopTicks=10,
            MaxStopTicks=12,
            RewardRiskRatio=2.0,
            UseVwapSideFilter=False,
            MinVolumeFactor=0.85,
        ))

    for direction in ("long", "short", "both"):
        out.append(make_variant(
            f"msweep_{direction}_1100_1300_or240_vwapthenrr_s10_rr20",
            direction=direction,
            TradeStartTime=1100,
            TradeEndTime=1300,
            OpeningRangeMinutes=240,
            TargetMode="VwapThenRR",
            MinStopTicks=10,
            MaxStopTicks=10,
            RewardRiskRatio=2.0,
            MaxTradesPerDay=3,
            HardMaxTradesPerDay=5,
        ))

    return out


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
        instrument=CURRENT_CONTRACT,
        params=params,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=TIMEFRAME,
        slippage_ticks=slippage_ticks,
        role="smoke",
        session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([CURRENT_CONTRACT]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = str(resp.get("job_id") or "") if code == 201 and isinstance(resp, dict) else ""
    print(f"submit {stage:16s} {variant.name:72s} code={code} job={job_id or resp}", flush=True)
    return {
        "stage": stage,
        "variant": variant.name,
        "timeframe": TIMEFRAME,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "slippage_ticks": slippage_ticks,
        "round_turn_commission": fee,
        "params": params,
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
    row = dict(submission)
    params = row.get("params") or {}
    row.update({
        "status": job_state(job_id) if job_id else "missing",
        "anchor_mode": params.get("AnchorMode"),
        "target_mode": params.get("TargetMode"),
        "direction": "both" if params.get("EnableLong") and params.get("EnableShort") else (
            "long" if params.get("EnableLong") else "short"
        ),
        "trade_start": params.get("TradeStartTime"),
        "trade_end": params.get("TradeEndTime"),
        "force_flat": params.get("ForceFlatTime"),
        "or_minutes": params.get("OpeningRangeMinutes"),
        "rr": params.get("RewardRiskRatio"),
        "min_stop": params.get("MinStopTicks"),
        "max_stop": params.get("MaxStopTicks"),
        "min_volume": params.get("MinVolumeFactor"),
    })
    if not report or "result" not in report:
        row.update({"trade_count": 0, "adj_net": 0.0, "adj_pf": 0.0, "adj_dd": 0.0})
        return row

    fee = float(row.get("round_turn_commission") or 0.0)
    trades = trades_from_report(report)
    pnls = [float(t.get("pnl_currency") or 0.0) - fee * trade_qty(t) for t in trades]
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
        "adj_net": round(adj_net, 6),
        "adj_pf": round(adj_pf, 6) if math.isfinite(adj_pf) else 999.0,
        "adj_dd": round(dd, 6),
        "win_pct": round((sum(1 for p in pnls if p > 0.0) / count * 100.0) if count else 0.0, 4),
        "avg_trade": round(adj_net / count, 6) if count else 0.0,
        "max_consecutive_losses": max_consecutive_losses(pnls),
    })
    return row


def score(row: Dict[str, Any]) -> float:
    trades = float(row.get("trade_count") or 0.0)
    net = float(row.get("adj_net") or 0.0)
    pf = float(row.get("adj_pf") or 0.0)
    dd = abs(float(row.get("adj_dd") or 0.0))
    avg = float(row.get("avg_trade") or 0.0)
    if trades <= 0:
        return -999999.0
    if net <= 0.0 or pf < 1.05:
        return -500000.0 + net - dd
    return net + min(pf, 3.0) * 140.0 + min(trades, 400.0) * 0.7 + avg * 25.0 - dd * 0.45


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def gate_decision(rows_by_stage: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    full = rows_by_stage.get("Full") or {}
    is_row = rows_by_stage.get("IS") or {}
    oos = rows_by_stage.get("OOS") or {}
    slip2 = rows_by_stage.get("StressSlip2") or {}
    fee240 = rows_by_stage.get("StressFee240") or {}
    combined = rows_by_stage.get("StressSlip2Fee240") or {}
    current30 = rows_by_stage.get("Current30D") or {}
    gates = {
        "full_net_positive": float(full.get("adj_net") or 0.0) > 0.0,
        "full_pf_ge_1_35": float(full.get("adj_pf") or 0.0) >= 1.35,
        "max_dd_pct_15": RL.max_drawdown_within_budget(float(full.get("adj_dd") or 0.0)),
        "full_trades_ge_40": int(full.get("trade_count") or 0) >= 40,
        "is_net_positive": float(is_row.get("adj_net") or 0.0) > 0.0,
        "oos_net_positive": float(oos.get("adj_net") or 0.0) > 0.0,
        "oos_pf_ge_1_25": float(oos.get("adj_pf") or 0.0) >= 1.25,
        "stress_slip2_positive": float(slip2.get("adj_net") or 0.0) > 0.0,
        "stress_fee240_positive": float(fee240.get("adj_net") or 0.0) > 0.0,
        "stress_combined_positive": float(combined.get("adj_net") or 0.0) > 0.0,
        "current30_nonnegative": float(current30.get("adj_net") or 0.0) >= 0.0,
    }
    return {
        "ready_pass": all(gates.values()),
        "decision": "paper_ready" if all(gates.values()) else "research_only",
        "failed_gates": [k for k, v in gates.items() if not v],
        "gates": gates,
    }


def main(argv: List[str]) -> int:
    top_n = 5
    if "--top" in argv:
        top_n = int(argv[argv.index("--top") + 1])
    only: List[str] = []
    if "--only" in argv:
        only = [x.strip() for x in argv[argv.index("--only") + 1].split(",") if x.strip()]

    bundle = RL.DATA / "research" / f"mgc_cell006_morning_sweep_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)
    print(f"hypothesis: morning OR sweep fade | carrier={CLASS_NAME} | baseline={BASELINE_FAILED}", flush=True)

    variants = full_variants()
    by_name = {v.name: v for v in variants}
    if only:
        variants = [by_name[name] for name in only]

    smoke_from, smoke_to = current_window(days=60)
    smoke_submissions = [
        submit_job(variant=v, stage="Smoke60D", from_utc=smoke_from, to_utc=smoke_to)
        for v in variants
    ]
    (bundle / "smoke_submissions.json").write_text(
        json.dumps(smoke_submissions, indent=2, ensure_ascii=False), encoding="utf-8")
    wait_for_jobs([s.get("job_id") for s in smoke_submissions if s.get("job_id")])
    smoke_rows = [summarize(s) for s in smoke_submissions]
    smoke_rows.sort(key=score, reverse=True)
    (bundle / "smoke_rows.json").write_text(json.dumps(smoke_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(bundle / "smoke_rows.csv", smoke_rows)

    selected = [r["variant"] for r in smoke_rows if score(r) > -499000.0][:top_n]
    if not selected and smoke_rows:
        selected = [smoke_rows[0]["variant"]]
    print("top smoke rows:", flush=True)
    for row in smoke_rows[:12]:
        print(
            f"  {row['variant']}: trades={row['trade_count']} "
            f"net={float(row.get('adj_net') or 0.0):.2f} pf={float(row.get('adj_pf') or 0.0):.2f} "
            f"dd={float(row.get('adj_dd') or 0.0):.2f}",
            flush=True,
        )
    print(f"selected for validation: {selected}", flush=True)

    stage_defs = [
        ("Full", FULL[1], FULL[2], 1, RL.fee_for(ROOT)),
        ("IS", IS[1], IS[2], 1, RL.fee_for(ROOT)),
        ("OOS", OOS[1], OOS[2], 1, RL.fee_for(ROOT)),
        ("StressSlip2", FULL[1], FULL[2], 2, RL.fee_for(ROOT)),
        ("StressFee240", FULL[1], FULL[2], 1, RL.fee_stress(ROOT)),
        ("StressSlip2Fee240", FULL[1], FULL[2], 2, RL.fee_stress(ROOT)),
        ("Current30D", *current_window(days=30), 1, RL.fee_for(ROOT)),
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
            "locked_parameters": by_name[name].params,
            "timeframe": TIMEFRAME,
            "rows": rows_by_stage,
        })
        decisions.append(decision)
    decisions.sort(
        key=lambda d: (
            bool(d.get("ready_pass")),
            float((d.get("rows") or {}).get("OOS", {}).get("adj_pf") or 0.0),
            float((d.get("rows") or {}).get("Full", {}).get("adj_net") or 0.0),
        ),
        reverse=True,
    )

    best = decisions[0] if decisions else {}
    best_full = (best.get("rows") or {}).get("Full", {})
    pivot = (
        "Pivot to 5m bars with tighter lunch window 11:00-12:30 and PriorSession+OR hybrid anchors."
        if not best.get("ready_pass")
        else "Compile NTAMgcLateMorningSweepC006 and run wrapper validation."
    )
    summary = {
        "bundle": str(bundle),
        "class_name": CLASS_NAME,
        "wrapper_class": "NTAMgcLateMorningSweepC006",
        "cell_id": CELL_ID,
        "display_name": DISPLAY_NAME,
        "instrument": CURRENT_CONTRACT,
        "session_template": SESSION_TEMPLATE,
        "hypothesis": "Fade liquidity sweeps beyond 06:00-10:00 opening range; target session VWAP in 10:00-13:25 PT free window.",
        "free_window_pt": "10:00-13:25",
        "force_flat_pt": "13:30",
        "baseline_failed_sessionedge": BASELINE_FAILED,
        "best_near_miss": {
            "variant": best.get("variant"),
            "decision": best.get("decision"),
            "failed_gates": best.get("failed_gates"),
            "full_adj_net": best_full.get("adj_net"),
            "full_adj_pf": best_full.get("adj_pf"),
            "full_adj_dd": best_full.get("adj_dd"),
            "full_trades": best_full.get("trade_count"),
        },
        "recommended_next_pivot": pivot,
        "selected": selected,
        "decisions": decisions,
    }
    (bundle / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (bundle / "decisions.json").write_text(json.dumps(decisions, indent=2, ensure_ascii=False), encoding="utf-8")

    print("decisions:", flush=True)
    for d in decisions:
        full = (d.get("rows") or {}).get("Full", {})
        oos = (d.get("rows") or {}).get("OOS", {})
        print(
            f"  {d['variant']}: {d['decision']} full_net={float(full.get('adj_net') or 0.0):.2f} "
            f"full_pf={float(full.get('adj_pf') or 0.0):.2f} oos_pf={float(oos.get('adj_pf') or 0.0):.2f} "
            f"failed={','.join(d.get('failed_gates') or [])}",
            flush=True,
        )
    return 0 if any(d.get("ready_pass") for d in decisions) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
