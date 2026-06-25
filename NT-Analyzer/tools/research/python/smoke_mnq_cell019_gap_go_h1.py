"""Smoke probe Engine #9 RTH H1 Gap-and-Go Retest.

8 variants x 2 years = 16 jobs.
Sweep: gap size floor x retest tolerance x RR.
Goal: cross-year positive with materially lower 2025 drawdown than ORB engines.
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402

CLASS_NAME = "NTAMnqRthGapGoH1C019"
ROOT = "MNQ"
INSTRUMENT = "MNQ 06-26"
SESSION_TEMPLATE = "CME US Index Futures RTH"
BARS = 60
BASE_TF = 3600
FEE = max(1.90, RL.fee_for(ROOT))

PERIODS = [
    ("2024", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"),
    ("2025", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z"),
]


def base() -> Dict[str, Any]:
    return {
        "InstrumentName": ROOT,
        "ContractName": INSTRUMENT,
        "SessionTemplateName": SESSION_TEMPLATE,
        "BaseTimeframeSeconds": BASE_TF,
        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": RL.margin_for(ROOT),
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "EnableLong": True,
        "EnableShort": True,
        "TradeStartTime": 730,
        "TradeEndTime": 1130,
        "ForceFlatTime": 1230,
        "BiasEmaPeriod": 20,
        "GapMinPoints": 4.0,
        "GapMaxPoints": 100.0,
        "RetestToleranceTicks": 8,
        "AdxPeriod": 14,
        "MinAdxTrend": 16.0,
        "MaxAdxTrend": 60.0,
        "RsiPeriod": 14,
        "RsiLongMax": 78.0,
        "RsiShortMin": 22.0,
        "AtrPeriod": 14,
        "VolumeSmaPeriod": 20,
        "VolCeilingFactor": 6.0,
        "VolMinFactor": 0.20,
        "StopBufferPoints": 2.0,
        "MinStopPoints": 8.0,
        "MaxStopPoints": 20.0,
        "AtrStopMult": 0.5,
        "RewardRiskRatio": 2.0,
        "MinTargetPoints": 16.0,
        "MoveToBreakevenAtR": 1.0,
        "BreakevenPlusTicks": 2,
        "UseTrailingStop": True,
        "TrailAfterR": 1.5,
        "TrailDistanceTicks": 24,
        "UseTimeStop": False,
        "TimeStopBars": 3,
        "MinProgressR": 0.30,
        "RiskPerTradePct": 1.0,
        "UserMaxContracts": 1,
        "MaxOpenPositions": 1,
        "MaxDailyLossUsd": 80.0,
        "MaxWeeklyLossUsd": 200.0,
        "MaxTradesPerDay": 1,
        "HardMaxTradesPerDay": 1,
        "MaxConsecutiveLosses": 5,
        "PauseAfterConsecutiveLosses": 3,
        "PauseMinutesAfterLosses": 60,
        "RoundTurnCommission": FEE,
        "SlippageTicks": 1,
    }


VARIANTS = []
for gap_min in (4.0, 8.0):
    for retest_ticks in (4, 12):
        for rr in (1.6, 2.0):
            label = f"gp{int(gap_min):02d}_rt{retest_ticks:02d}_rr{int(rr * 10):02d}"
            overrides = {
                "GapMinPoints": gap_min,
                "RetestToleranceTicks": retest_ticks,
                "RewardRiskRatio": rr,
            }
            VARIANTS.append((label, overrides))


def submit_job(label: str, period_label: str, frm: str, to: str, ov: Dict[str, Any]) -> Dict[str, Any]:
    params = base()
    params.update(ov)
    body = RL.build_job_body(
        class_name=CLASS_NAME,
        instrument=INSTRUMENT,
        params=params,
        from_utc=frm,
        to_utc=to,
        bars_period_type="Minute",
        bars_period_value=BARS,
        slippage_ticks=int(params["SlippageTicks"]),
        role="smoke",
        session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    code, resp = RL.post("/api/jobs", body)
    jid = resp.get("job_id") if code == 201 and isinstance(resp, dict) else None
    print(f"submit {label:20s} {period_label} job={jid or resp}", flush=True)
    return {"label": label, "period": period_label, "job_id": jid, "response": resp, "code": code}


def wait_for(rows: List[Dict[str, Any]], timeout_s: int = 7200) -> None:
    root = RL.jobs_root()
    remaining = {str(r["job_id"]) for r in rows if r.get("job_id")}
    deadline = time.time() + timeout_s
    last = 0.0
    while remaining:
        if time.time() > deadline:
            raise TimeoutError(f"timeout: {sorted(remaining)}")
        for job_id in list(remaining):
            for state in ("done", "failed", "cancelled"):
                if (root / state / job_id).is_dir():
                    remaining.discard(job_id)
                    break
        now = time.time()
        if now - last >= 30 and remaining:
            print(f"waiting: {len(remaining)}", flush=True)
            last = now
        time.sleep(3)


def trades_of(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = Path(str(report.get("_dir") or "")) / "trades.json"
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict) and isinstance(raw.get("trades"), list):
            return raw["trades"]
    return []


def sb_pct(trades: List[Dict[str, Any]]) -> float:
    if not trades:
        return 0.0
    same = 0
    counted = 0
    for trade in trades:
        entry = trade.get("entry_time_utc") or trade.get("entry_time") or ""
        exit_ = trade.get("exit_time_utc") or trade.get("exit_time") or ""
        if not entry or not exit_:
            continue
        try:
            de = datetime.fromisoformat(entry.replace("Z", "+00:00"))
            dx = datetime.fromisoformat(exit_.replace("Z", "+00:00"))
        except Exception:
            continue
        eb = int(de.timestamp()) // BASE_TF
        xb = int(dx.timestamp()) // BASE_TF
        counted += 1
        if eb == xb:
            same += 1
    return round(same / counted * 100.0, 1) if counted else 0.0


def summarize(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row.get("job_id"):
        return {
            "label": row["label"],
            "period": row["period"],
            "n": 0,
            "net": 0.0,
            "pf": 0.0,
            "dd": 0.0,
            "sb": 0.0,
            "wr": 0.0,
            "error": row.get("response"),
        }
    report = RL.read_job_report(row["job_id"]) or {}
    trades = trades_of(report)
    pnls = [
        float(trade.get("pnl_currency") or 0.0)
        - FEE * max(1.0, abs(float(trade.get("quantity") or 1)))
        for trade in trades
    ]
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else (math.inf if gross_profit > 0 else 0.0)
    equity = 0.0
    peak = 0.0
    dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    wins = sum(1 for pnl in pnls if pnl > 0)
    wr = wins / len(pnls) * 100.0 if pnls else 0.0
    return {
        "label": row["label"],
        "period": row["period"],
        "n": len(trades),
        "net": round(sum(pnls), 2),
        "pf": round(pf, 3) if not math.isinf(pf) else math.inf,
        "dd": round(dd, 2),
        "sb": sb_pct(trades),
        "wr": round(wr, 1),
    }


def main() -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle = RL.DATA / "research" / f"mnq_cell019_gap_go_h1_smoke_{ts}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"Engine #9 Gap-Go H1 smoke  bundle: {bundle}", flush=True)
    print(
        f"class: {CLASS_NAME}  variants: {len(VARIANTS)}  years: {len(PERIODS)}  total_jobs: {len(VARIANTS) * len(PERIODS)}",
        flush=True,
    )
    rows: List[Dict[str, Any]] = []
    for label, overrides in VARIANTS:
        for period_label, frm, to in PERIODS:
            rows.append(submit_job(label, period_label, frm, to, overrides))
    failed = [row for row in rows if not row.get("job_id")]
    if failed:
        first = failed[0]
        raise RuntimeError(f"submission failed for {first['label']} {first['period']}: {first.get('response')}")
    wait_for(rows)
    sums = [summarize(row) for row in rows]
    print("\n--- RESULTS ---", flush=True)
    for summary in sums:
        pf_text = f"{summary['pf']:.3f}" if not (isinstance(summary["pf"], float) and math.isinf(summary["pf"])) else "inf"
        print(
            f"  {summary['label']:20s} {summary['period']}  n={summary['n']:>3}  "
            f"net={summary['net']:>+9.2f}  pf={pf_text:>7}  dd={summary['dd']:>+9.2f}  "
            f"sb%={summary['sb']:>5.1f}  wr={summary['wr']:>5.1f}",
            flush=True,
        )
    by_label: Dict[str, Dict[str, Any]] = {}
    for summary in sums:
        by_label.setdefault(summary["label"], {})[summary["period"]] = summary
    print("\nBOTH-YEARS-POSITIVE:", flush=True)
    found = False
    for label, periods in by_label.items():
        y24 = periods.get("2024", {})
        y25 = periods.get("2025", {})
        if (y24.get("net") or 0) > 0 and (y25.get("net") or 0) > 0:
            found = True
            print(
                f"  {label:20s}  2024 n={y24.get('n'):>3} net={y24.get('net'):>+8.2f} pf={y24.get('pf')} dd={y24.get('dd'):>+8.2f} sb={y24.get('sb')}%"
                f"  |  2025 n={y25.get('n'):>3} net={y25.get('net'):>+8.2f} pf={y25.get('pf')} dd={y25.get('dd'):>+8.2f} sb={y25.get('sb')}%",
                flush=True,
            )
    if not found:
        print("  (none)", flush=True)
    (bundle / "summary.json").write_text(json.dumps(sums, indent=2, default=str), encoding="utf-8")
    print(f"\nsaved: {bundle / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()