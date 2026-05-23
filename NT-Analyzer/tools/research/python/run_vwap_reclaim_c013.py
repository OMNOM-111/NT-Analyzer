"""Run MNQ CELL-013 Session VWAP Reclaim validation.

This runner intentionally keeps the first pass small:
  - smoke on current MNQ front contract for long/short wrappers
  - Full / IS / OOS on the historical MNQ research contract
  - slip=2 and fee=2.40 stress on the best non-rejected direction

The strategy itself stays single-series. Jobs request High fill, no Tick Replay,
commission_template=None, and explicit RoundTurnCommission on strategy params.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402
import mnq_scalp_pilot_lib as MS  # noqa: E402


LONG_CLASS = "NTAMnqVwapReclaimScalperLongC013"
SHORT_CLASS = "NTAMnqVwapReclaimScalperShortC013"
CURRENT_CONTRACT = "MNQ 06-26"
SESSION_TEMPLATE = "CME US Index Futures RTH"

PERIODS = [
    ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z"),
    ("IS", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"),
    ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z"),
]

SMOKE = ("Smoke2026", "2026-03-12T00:00:00Z", "2026-05-11T23:59:59Z", CURRENT_CONTRACT)


def base_params(direction: str, *, fee: float = 1.90, slip: int = 1) -> Dict[str, Any]:
    return {
        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": 100.0,
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "InstrumentName": "MNQ",
        "ContractName": CURRENT_CONTRACT,
        "SessionTemplateName": SESSION_TEMPLATE,
        "BaseTimeframeSeconds": 60,
        "EnableLong": direction == "long",
        "EnableShort": direction == "short",
        "TradeStartTime": 635,
        "TradeEndTime": 830,
        "ForceFlatTime": 1245,
        "OpeningRangeStartTime": 630,
        "OpeningRangeMinutes": 5,
        "EmaFastPeriod": 9,
        "EmaSlowPeriod": 34,
        "AtrPeriod": 14,
        "AdxPeriod": 14,
        "MinAdx": 0.0,
        "VolumeSmaPeriod": 20,
        "MinVolumeFactor": 1.10,
        "MinBodyRangePct": 0.45,
        "MinCloseLocationPct": 0.60,
        "VwapMode": "TypicalPrice",
        "VwapDistanceThresholdTicks": 18,
        "VwapSlopeLookback": 8,
        "MinVwapSlopeTicks": 1.0,
        "VwapReclaimBufferTicks": 1,
        "VwapChopBandTicks": 4,
        "VwapCrossLookback": 12,
        "MaxVwapCrosses": 3,
        "MinEmaSpreadTicks": 2,
        "ImpulseLookbackBars": 4,
        "MinImpulseMoveTicks": 16,
        "MinOpeningRangeTicks": 8,
        "MaxOpeningRangeTicks": 80,
        "OpeningRangeBreakBufferTicks": 2,
        "MaxBarsAfterImpulse": 18,
        "PullbackLookbackBars": 6,
        "MinPullbackDepthTicks": 4,
        "MaxPullbackDepthTicks": 24,
        "PullbackMaxDistanceFromVwapTicks": 10,
        "PullbackTouchEmaTicks": 3,
        "MaxBarsAfterPullback": 6,
        "UseDeltaFilter": False,
        "UseImbalanceFilter": False,
        "DeltaVolumeFactor": 1.25,
        "AtrStopMult": 0.40,
        "StopMinTicks": 8,
        "StopMaxTicks": 18,
        "StopBeyondPullbackTicks": 2,
        "RewardRiskRatio": 1.60,
        "BreakEvenTriggerR": 0.80,
        "TrailMode": "HalfStop",
        "TrailTriggerR": 1.10,
        "TimeStopBars": 5,
        "MinProgressR": 0.25,
        "EntryOffsetTicks": 1,
        "EntryTimeoutBars": 2,
        "RiskPerTradePct": 0.35,
        "UserMaxContracts": 1,
        "MaxOpenPositions": 1,
        "DailyLossLimit": 60.0,
        "WeeklyLossLimit": 150.0,
        "MaxTradesPerDay": 6,
        "HardMaxTradesPerDay": 8,
        "MaxConsecutiveLosses": 3,
        "PauseAfterConsecutiveLosses": 2,
        "PauseMinutesAfterLosses": 15,
        "RoundTurnCommission": fee,
        "SlippageTicks": slip,
    }


def submit_one(bundle: Path, label: str, class_name: str, direction: str,
               from_utc: str, to_utc: str, instrument: str,
               *, fee: float = 1.90, slip: int = 1, role: str = "research") -> Dict[str, Any]:
    params = base_params(direction, fee=fee, slip=slip)
    body = RL.build_job_body(
        class_name=class_name,
        instrument=instrument,
        params=params,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=1,
        slippage_ticks=slip,
        role=role,
        session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([instrument]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = resp.get("job_id") if code == 201 else None
    row = {
        "label": label,
        "class_name": class_name,
        "direction": direction,
        "instrument": instrument,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "fee": fee,
        "slip": slip,
        "code": code,
        "job_id": job_id,
        "response": resp,
        "request": body,
    }
    print(f"submit {label:22s} {direction:5s} code={code} job={job_id or resp}")
    return row


def wait_job(job_id: str, timeout_s: int = 900) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        report = RL.read_job_report(job_id)
        if report and "result" in report:
            return report
        if report and ("error" in report or "cancelled" in str(report.get("_dir", ""))):
            return report
        time.sleep(2)
    return {"job_id": job_id, "timeout": True}


def metric(report: Dict[str, Any], key: str, default: float = 0.0) -> float:
    result = report.get("result") or {}
    metrics = result.get("metrics") or {}
    value = result.get(key, metrics.get(key, default))
    if isinstance(value, str) and value.lower() == "inf":
        return math.inf
    try:
        return float(value)
    except Exception:
        return default


def summarize(row: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    result = report.get("result") or {}
    trades = result.get("trades") or []
    gross_profit_adj = 0.0
    gross_loss_adj = 0.0
    adjusted_net = 0.0
    adjusted_trade_count = 0
    for trade in trades:
        qty = int(trade.get("quantity") or 1)
        pnl = float(trade.get("pnl_currency") or 0.0) - float(row.get("fee") or 0.0) * max(1, qty)
        adjusted_net += pnl
        adjusted_trade_count += 1
        if pnl >= 0.0:
            gross_profit_adj += pnl
        else:
            gross_loss_adj += abs(pnl)
    if adjusted_trade_count == 0:
        adjusted_net = metric(report, "net_profit_after_commission", metric(report, "net_profit", 0.0))
        adjusted_pf = metric(report, "profit_factor_after_commission", metric(report, "profit_factor", 0.0))
    else:
        adjusted_pf = gross_profit_adj / gross_loss_adj if gross_loss_adj > 0.0 else (math.inf if gross_profit_adj > 0.0 else 0.0)

    out = dict(row)
    out["status_dir"] = report.get("_dir", "")
    out["trade_count"] = adjusted_trade_count or int(metric(report, "trade_count", 0))
    out["adj_net"] = adjusted_net
    out["adj_pf"] = adjusted_pf
    out["max_drawdown"] = metric(report, "max_drawdown_after_commission", metric(report, "max_drawdown", 0.0))
    out["result"] = result
    return out


def run_and_collect(bundle: Path, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    for row in rows:
        job_id = row.get("job_id")
        if not job_id:
            summaries.append(row)
            continue
        report = wait_job(str(job_id))
        summary = summarize(row, report)
        summaries.append(summary)
        print(
            f"done {row['label']:22s} {row['direction']:5s} "
            f"trades={summary.get('trade_count')} net={summary.get('adj_net'):.2f} "
            f"pf={summary.get('adj_pf'):.3f} dd={summary.get('max_drawdown'):.2f}"
        )
        (bundle / "latest_summary.json").write_text(
            json.dumps(summaries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return summaries


def direction_passes(rows: List[Dict[str, Any]], direction: str) -> bool:
    by_label = {r["label"]: r for r in rows if r.get("direction") == direction}
    full = by_label.get("Full")
    oos = by_label.get("OOS")
    if not full or not oos:
        return False
    return (
        full.get("adj_net", 0.0) > 0.0
        and full.get("adj_pf", 0.0) >= 1.35
        and oos.get("adj_pf", 0.0) >= 1.25
        and abs(full.get("max_drawdown", 0.0)) <= 300.0
        and full.get("trade_count", 0) >= 20
    )


def aggregate_period(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"trade_count": 0, "adj_net": 0.0, "adj_pf": 0.0, "max_drawdown": 0.0}
    gross_profit = 0.0
    gross_loss = 0.0
    trade_count = 0
    adj_net = 0.0
    max_dd = 0.0
    for r in rows:
        result = r.get("result") or {}
        trades = result.get("trades") or []
        trade_count += int(r.get("trade_count") or 0)
        adj_net += float(r.get("adj_net") or 0.0)
        max_dd = min(max_dd, float(r.get("max_drawdown") or 0.0))
        if trades:
            for trade in trades:
                qty = int(trade.get("quantity") or 1)
                pnl = float(trade.get("pnl_currency") or 0.0) - float(r.get("fee") or 0.0) * max(1, qty)
                if pnl >= 0.0:
                    gross_profit += pnl
                else:
                    gross_loss += abs(pnl)
        else:
            metrics = result.get("metrics") or {}
            gross_profit += float(result.get("gross_profit_after_commission") or metrics.get("gross_profit") or 0.0)
            gross_loss += abs(float(result.get("gross_loss_after_commission") or metrics.get("gross_loss") or 0.0))
    pf = gross_profit / gross_loss if gross_loss > 0 else (math.inf if gross_profit > 0 else 0.0)
    return {"trade_count": trade_count, "adj_net": adj_net, "adj_pf": pf, "max_drawdown": max_dd}


def aggregate_validation(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    labels = sorted({str(r.get("label") or "") for r in rows})
    directions = sorted({str(r.get("direction") or "") for r in rows})
    for label in labels:
        for direction in directions:
            group = [r for r in rows if r.get("label") == label and r.get("direction") == direction]
            if not group:
                continue
            agg = aggregate_period(group)
            agg.update({
                "label": label,
                "direction": direction,
                "job_ids": [r.get("job_id") for r in group],
                "instruments": [r.get("instrument") for r in group],
            })
            out.append(agg)
    return out


def main() -> int:
    bundle = RL.DATA / "research" / f"vwap_reclaim_c013_{RL.utcnow_compact()}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}")

    smoke_rows = [
        submit_one(bundle, SMOKE[0], LONG_CLASS, "long", SMOKE[1], SMOKE[2], SMOKE[3], role="smoke"),
        submit_one(bundle, SMOKE[0], SHORT_CLASS, "short", SMOKE[1], SMOKE[2], SMOKE[3], role="smoke"),
    ]
    smoke = run_and_collect(bundle, smoke_rows)

    validation_rows: List[Dict[str, Any]] = []
    for label, fr, to in PERIODS:
        instruments = MS.contracts_for_period("MNQ", fr, to)
        for instrument in instruments:
            validation_rows.append(submit_one(bundle, label, LONG_CLASS, "long", fr, to, instrument))
            validation_rows.append(submit_one(bundle, label, SHORT_CLASS, "short", fr, to, instrument))
    validation_jobs = run_and_collect(bundle, validation_rows)
    validation = aggregate_validation(validation_jobs)
    print("aggregated validation:")
    for r in validation:
        print(
            f"  {r['label']:5s} {r['direction']:5s} trades={r['trade_count']} "
            f"net={r['adj_net']:.2f} pf={r['adj_pf']:.3f} dd={r['max_drawdown']:.2f}"
        )

    passed = [d for d in ("long", "short") if direction_passes(validation, d)]
    stress: List[Dict[str, Any]] = []
    if passed:
        # Prefer the direction with better Full adjusted net.
        full_by_dir = {
            r["direction"]: r for r in validation
            if r.get("label") == "Full" and r.get("direction") in passed
        }
        best_dir = max(passed, key=lambda d: full_by_dir.get(d, {}).get("adj_net", -999999.0))
        best_class = LONG_CLASS if best_dir == "long" else SHORT_CLASS
        stress_rows = []
        for instrument in MS.contracts_for_period("MNQ", PERIODS[0][1], PERIODS[0][2]):
            stress_rows.append(submit_one(bundle, "StressSlip2", best_class, best_dir, PERIODS[0][1], PERIODS[0][2], instrument, slip=2))
            stress_rows.append(submit_one(bundle, "StressFee240", best_class, best_dir, PERIODS[0][1], PERIODS[0][2], instrument, fee=2.40))
        stress_jobs = run_and_collect(bundle, stress_rows)
        stress = aggregate_validation(stress_jobs)
    else:
        best_dir = ""

    final = {
        "bundle": str(bundle),
        "smoke": smoke,
        "validation_jobs": validation_jobs,
        "validation": validation,
        "passed_directions_before_stress": passed,
        "best_direction": best_dir,
        "stress": stress,
    }
    (bundle / "summary.json").write_text(json.dumps(final, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"summary -> {bundle / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
