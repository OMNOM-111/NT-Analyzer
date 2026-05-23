"""Targeted MGC CELL-004 Session VWAP Reclaim branch optimization."""
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


ROOT = "MGC"
INSTRUMENT = "MGC 06-26"
SESSION_TEMPLATE = "Nymex Metals RTH1"
LONG_CLASS = "NTAMgcVwapReclaimScalperLongBranch"
SHORT_CLASS = "NTAMgcVwapReclaimScalperShortBranch"
BUNDLE_NAME = "mgc_cell004_vwap_reclaim_opt"
FROM_FULL = "2024-01-01T00:00:00Z"
TO_FULL = "2025-12-31T23:59:59Z"

CSV_FIELDS = [
    "variant", "job_id", "status", "class_name", "direction",
    "trade_count", "adj_net", "adj_pf", "adj_dd", "win_pct",
    "trade_end", "or_minutes", "vwap_distance", "impulse_ticks",
    "stop_min", "stop_max", "rr", "volume_factor",
]


@dataclass(frozen=True)
class Variant:
    name: str
    class_name: str
    direction: str
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
            print(f"waiting: {len(remaining)} CELL-004 reclaim jobs still pending/running")
            last_print = now
        if remaining:
            time.sleep(interval_s)
    return states


def base_params(direction: str) -> Dict[str, Any]:
    return {
        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": RL.margin_for(ROOT),
        "MaxContractsByCapital": 10,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "InstrumentName": ROOT,
        "ContractName": INSTRUMENT,
        "SessionTemplateName": SESSION_TEMPLATE,
        "BaseTimeframeSeconds": 60,
        "EnableLong": direction == "long",
        "EnableShort": direction == "short",
        "TradeStartTime": 600,
        "TradeEndTime": 930,
        "ForceFlatTime": 1245,
        "OpeningRangeStartTime": 600,
        "OpeningRangeMinutes": 10,
        "EmaFastPeriod": 9,
        "EmaSlowPeriod": 34,
        "AtrPeriod": 14,
        "AdxPeriod": 14,
        "MinAdx": 0.0,
        "VolumeSmaPeriod": 20,
        "MinVolumeFactor": 0.8,
        "MinBodyRangePct": 0.35,
        "MinCloseLocationPct": 0.55,
        "VwapMode": "TypicalPrice",
        "VwapDistanceThresholdTicks": 12,
        "VwapSlopeLookback": 8,
        "MinVwapSlopeTicks": 0.5,
        "VwapReclaimBufferTicks": 1,
        "VwapChopBandTicks": 3,
        "VwapCrossLookback": 12,
        "MaxVwapCrosses": 5,
        "MinEmaSpreadTicks": 1,
        "ImpulseLookbackBars": 4,
        "MinImpulseMoveTicks": 12,
        "MinOpeningRangeTicks": 4,
        "MaxOpeningRangeTicks": 80,
        "OpeningRangeBreakBufferTicks": 1,
        "MaxBarsAfterImpulse": 18,
        "PullbackLookbackBars": 6,
        "MinPullbackDepthTicks": 3,
        "MaxPullbackDepthTicks": 24,
        "PullbackMaxDistanceFromVwapTicks": 10,
        "PullbackTouchEmaTicks": 3,
        "MaxBarsAfterPullback": 6,
        "UseDeltaFilter": False,
        "UseImbalanceFilter": False,
        "DeltaVolumeFactor": 1.25,
        "AtrStopMult": 0.45,
        "StopMinTicks": 8,
        "StopMaxTicks": 16,
        "StopBeyondPullbackTicks": 2,
        "RewardRiskRatio": 1.8,
        "BreakEvenTriggerR": 0.8,
        "TrailMode": "HalfStop",
        "TrailTriggerR": 1.1,
        "TimeStopBars": 5,
        "MinProgressR": 0.25,
        "EntryOffsetTicks": 1,
        "EntryTimeoutBars": 2,
        "RiskPerTradePct": 0.35,
        "UserMaxContracts": 1,
        "MaxOpenPositions": 1,
        "DailyLossLimit": 80.0,
        "WeeklyLossLimit": 200.0,
        "MaxTradesPerDay": 4,
        "HardMaxTradesPerDay": 6,
        "MaxConsecutiveLosses": 4,
        "PauseAfterConsecutiveLosses": 3,
        "PauseMinutesAfterLosses": 10,
        "RoundTurnCommission": RL.fee_for(ROOT),
        "SlippageTicks": 1,
    }


def variant(direction: str, **overrides: Any) -> Variant:
    params = base_params(direction)
    params.update(overrides)
    class_name = LONG_CLASS if direction == "long" else SHORT_CLASS
    name = (
        f"c004_reclaim_{direction}_te{params['TradeEndTime']}_or{params['OpeningRangeMinutes']}"
        f"_vd{params['VwapDistanceThresholdTicks']}_imp{params['MinImpulseMoveTicks']}"
        f"_s{params['StopMinTicks']}_{params['StopMaxTicks']}_rr{str(params['RewardRiskRatio']).replace('.', '')}"
    )
    return Variant(name=name, class_name=class_name, direction=direction, params=params)


def full_variants() -> List[Variant]:
    out: List[Variant] = []
    stop_sets: Tuple[Tuple[int, int, float], ...] = ((8, 14, 1.4), (8, 16, 1.8), (10, 20, 1.5))
    for direction in ("long", "short"):
        for trade_end in (930, 1240):
            for or_minutes in (5, 10):
                for vwap_distance in (8, 12):
                    for impulse_ticks in (8, 12):
                        for stop_min, stop_max, rr in stop_sets:
                            out.append(variant(
                                direction,
                                TradeEndTime=trade_end,
                                OpeningRangeMinutes=or_minutes,
                                VwapDistanceThresholdTicks=vwap_distance,
                                MinImpulseMoveTicks=impulse_ticks,
                                StopMinTicks=stop_min,
                                StopMaxTicks=stop_max,
                                RewardRiskRatio=rr,
                            ))
    return out


def submit_job(v: Variant, from_utc: str, to_utc: str, slippage_ticks: int = 1) -> Tuple[int, Dict[str, Any]]:
    body = RL.build_job_body(
        class_name=v.class_name,
        instrument=INSTRUMENT,
        params=v.params,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=1,
        slippage_ticks=slippage_ticks,
        role="smoke",
        session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    return RL.post("/api/jobs", body)


def adjusted_metrics(report: Dict[str, Any], fee: float) -> Dict[str, float]:
    result = report.get("result") or {}
    metrics = result.get("metrics") or {}
    trades = result.get("trades") or []
    gross_profit = 0.0
    gross_loss = 0.0
    net = 0.0
    for trade in trades:
        qty = max(1.0, abs(float(trade.get("quantity") or 1.0)))
        pnl = float(trade.get("pnl_currency") or 0.0) - fee * qty
        net += pnl
        if pnl >= 0.0:
            gross_profit += pnl
        else:
            gross_loss += abs(pnl)
    if not trades:
        try:
            net = float(metrics.get("net_profit_after_commission") or result.get("net_profit_after_commission") or 0.0)
        except Exception:
            net = 0.0
    pf = gross_profit / gross_loss if gross_loss > 0.0 else (math.inf if gross_profit > 0.0 else 0.0)
    if not trades:
        try:
            pf = float(metrics.get("profit_factor_after_commission") or result.get("profit_factor_after_commission") or 0.0)
        except Exception:
            pf = 0.0
    try:
        dd = float(metrics.get("max_drawdown_after_commission") or result.get("max_drawdown_after_commission") or metrics.get("max_drawdown") or 0.0)
    except Exception:
        dd = 0.0
    try:
        win_pct = float(metrics.get("win_pct_after_commission") or metrics.get("winning_pct") or 0.0)
    except Exception:
        win_pct = 0.0
    return {"trade_count": float(len(trades) or metrics.get("trade_count") or 0), "adj_net": net, "adj_pf": pf, "adj_dd": dd, "win_pct": win_pct}


def row_from_report(v: Variant, job_id: str, status: str) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "variant": v.name,
        "job_id": job_id,
        "status": status,
        "class_name": v.class_name,
        "direction": v.direction,
        "trade_count": 0,
        "adj_net": 0.0,
        "adj_pf": 0.0,
        "adj_dd": 0.0,
        "win_pct": 0.0,
        "trade_end": v.params.get("TradeEndTime"),
        "or_minutes": v.params.get("OpeningRangeMinutes"),
        "vwap_distance": v.params.get("VwapDistanceThresholdTicks"),
        "impulse_ticks": v.params.get("MinImpulseMoveTicks"),
        "stop_min": v.params.get("StopMinTicks"),
        "stop_max": v.params.get("StopMaxTicks"),
        "rr": v.params.get("RewardRiskRatio"),
        "volume_factor": v.params.get("MinVolumeFactor"),
    }
    report = RL.read_job_report(job_id)
    if not report or status != "done":
        return row
    m = adjusted_metrics(report, float(v.params.get("RoundTurnCommission") or RL.fee_for(ROOT)))
    row.update(m)
    row["trade_count"] = int(row["trade_count"])
    row["adj_net"] = round(float(row["adj_net"]), 2)
    row["adj_pf"] = round(float(row["adj_pf"]), 6) if math.isfinite(float(row["adj_pf"])) else "inf"
    row["adj_dd"] = round(float(row["adj_dd"]), 2)
    row["win_pct"] = round(float(row["win_pct"]), 4)
    return row


def write_rows(bundle: Path, name: str, rows: List[Dict[str, Any]]) -> None:
    (bundle / f"{name}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    with (bundle / f"{name}.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    bundle = RL.DATA / "research" / f"{BUNDLE_NAME}_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    variants = full_variants()
    print(f"bundle: {bundle}")
    print(f"full variants: {len(variants)}")

    manifest: List[Dict[str, Any]] = []
    for v in variants:
        code, resp = submit_job(v, FROM_FULL, TO_FULL, 1)
        job_id = resp.get("job_id") if code == 201 else None
        print(f"submit full {v.name:72s} code={code} job={job_id or resp}")
        manifest.append({"variant": v.name, "class_name": v.class_name, "direction": v.direction, "job_id": job_id, "code": code, "params": v.params, "response": resp})
    (bundle / "manifest_full_submit.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    states = wait_for_jobs([m["job_id"] for m in manifest if m.get("job_id")])
    by_name = {v.name: v for v in variants}
    rows: List[Dict[str, Any]] = []
    for m in manifest:
        job_id = m.get("job_id")
        status = states.get(job_id, "submit_failed") if job_id else "submit_failed"
        rows.append(row_from_report(by_name[m["variant"]], job_id or "", status))
    write_rows(bundle, "full_rows", rows)

    top = sorted(rows, key=lambda r: float(r.get("adj_net") or 0.0), reverse=True)[:15]
    print("top full rows:")
    for row in top:
        print(
            f"  {row['variant']}: trades={row['trade_count']} net={float(row['adj_net']):.2f} "
            f"pf={row['adj_pf']} dd={float(row['adj_dd']):.2f}"
        )

    candidates = [
        r for r in rows
        if r.get("status") == "done"
        and int(r.get("trade_count") or 0) >= 30
        and float(r.get("adj_net") or 0.0) > 0.0
        and float(r.get("adj_pf") if r.get("adj_pf") != "inf" else 999.0) >= 1.15
    ]
    candidates = sorted(candidates, key=lambda r: float(r.get("adj_net") or 0.0), reverse=True)
    (bundle / "decisions.json").write_text(json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"candidates selected: {len(candidates)}")
    return 0 if candidates else 1


if __name__ == "__main__":
    raise SystemExit(main())
