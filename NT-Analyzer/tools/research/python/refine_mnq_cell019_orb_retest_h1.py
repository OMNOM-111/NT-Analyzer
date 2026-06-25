"""Refine Engine #7 RTH H1 ORB-Retest.

Base: ob1_rt04_rr14 (OrBarsToDefine=1, RetestTol=4, RR=1.4) — best smoke cross-year.
Problem: 2025 PF=1.070, dd=-$812 (gate: PF>=1.35, dd>=-$300).

Sweep: ADX floor × MinOrRangeTicks × MaxStopPoints to:
  - Filter low-conviction days (ADX, OR size)
  - Reduce per-trade drawdown (stop cap)

11 variants × 2 years = 22 jobs.
Gate: PF>=1.25 both years AND dd>=-$300 in 2025.
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
import research_lib as RL  # noqa

CLASS_NAME = "NTAMnqRthOrbRetestH1C019"
INSTRUMENT  = "MNQ 06-26"
SESSION_TEMPLATE = "CME US Index Futures RTH"
BASE_TF = 3600
FEE = max(1.90, RL.fee_for("MNQ"))

PERIODS = [
    ("2024", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"),
    ("2025", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z"),
]


def base() -> Dict[str, Any]:
    return {
        "InstrumentName": "MNQ", "ContractName": INSTRUMENT,
        "SessionTemplateName": SESSION_TEMPLATE, "BaseTimeframeSeconds": BASE_TF,
        "StartingCapital": 2000.0, "IntradayOnly": True,
        "ActiveMarginPerContract": RL.margin_for("MNQ"),
        "MaxContractsByCapital": 20, "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "EnableLong": True, "EnableShort": True,
        "TradeStartTime": 730, "TradeEndTime": 1130, "ForceFlatTime": 1230,
        # Signal — anchored to smoke winner
        "BiasEmaPeriod": 20,
        "OrBarsToDefine": 1,
        "RetestToleranceTicks": 4,
        "MinOrRangeTicks": 16,
        "MaxOrRangeTicks": 400,
        # Confirm
        "AdxPeriod": 14, "MinAdxTrend": 18.0, "MaxAdxTrend": 60.0,
        "RsiPeriod": 14, "RsiLongMax": 75.0, "RsiShortMin": 25.0,
        # Filters
        "AtrPeriod": 14, "VolumeSmaPeriod": 20,
        "VolCeilingFactor": 5.0, "VolMinFactor": 0.30,
        # Orders
        "StopBufferPoints": 3.0, "MinStopPoints": 14.0, "MaxStopPoints": 50.0,
        "AtrStopMult": 1.0, "RewardRiskRatio": 1.4, "MinTargetPoints": 20.0,
        "MoveToBreakevenAtR": 0.7, "BreakevenPlusTicks": 4,
        "UseTrailingStop": True, "TrailAfterR": 1.0, "TrailDistanceTicks": 40,
        "UseTimeStop": False, "TimeStopBars": 4, "MinProgressR": 0.30,
        # Risk
        "RiskPerTradePct": 0.60, "UserMaxContracts": 1, "MaxOpenPositions": 1,
        "MaxDailyLossUsd": 120.0, "MaxWeeklyLossUsd": 300.0,
        "MaxTradesPerDay": 1, "HardMaxTradesPerDay": 1,
        "MaxConsecutiveLosses": 4, "PauseAfterConsecutiveLosses": 3,
        "PauseMinutesAfterLosses": 60,
        "RoundTurnCommission": FEE, "SlippageTicks": 1,
    }


# Sweep: ADX floor × MinOrRangeTicks × MaxStopPoints
# v00 = base reference (adx18, or16, stop50, rr1.4)
VARIANTS = [
    ("v00_base",           {"MinAdxTrend": 18.0, "MinOrRangeTicks": 16, "MaxStopPoints": 50.0, "RewardRiskRatio": 1.4}),
    ("v01_adx22",          {"MinAdxTrend": 22.0, "MinOrRangeTicks": 16, "MaxStopPoints": 50.0, "RewardRiskRatio": 1.4}),
    ("v02_adx26",          {"MinAdxTrend": 26.0, "MinOrRangeTicks": 16, "MaxStopPoints": 50.0, "RewardRiskRatio": 1.4}),
    ("v03_or24",           {"MinAdxTrend": 18.0, "MinOrRangeTicks": 24, "MaxStopPoints": 50.0, "RewardRiskRatio": 1.4}),
    ("v04_or32",           {"MinAdxTrend": 18.0, "MinOrRangeTicks": 32, "MaxStopPoints": 50.0, "RewardRiskRatio": 1.4}),
    ("v05_adx22_or24",     {"MinAdxTrend": 22.0, "MinOrRangeTicks": 24, "MaxStopPoints": 50.0, "RewardRiskRatio": 1.4}),
    ("v06_adx22_or32",     {"MinAdxTrend": 22.0, "MinOrRangeTicks": 32, "MaxStopPoints": 50.0, "RewardRiskRatio": 1.4}),
    ("v07_adx22_or24_s36", {"MinAdxTrend": 22.0, "MinOrRangeTicks": 24, "MaxStopPoints": 36.0, "RewardRiskRatio": 1.4}),
    ("v08_adx22_or24_s36_rr18", {"MinAdxTrend": 22.0, "MinOrRangeTicks": 24, "MaxStopPoints": 36.0, "RewardRiskRatio": 1.8}),
    ("v09_adx26_or24_s36", {"MinAdxTrend": 26.0, "MinOrRangeTicks": 24, "MaxStopPoints": 36.0, "RewardRiskRatio": 1.4}),
    ("v10_adx26_or32_s36", {"MinAdxTrend": 26.0, "MinOrRangeTicks": 32, "MaxStopPoints": 36.0, "RewardRiskRatio": 1.4}),
]


# ─────────────────────────────────────────────────────────────────────────────
def submit_job(
    label: str, period_label: str, frm: str, to: str, ov: Dict[str, Any]
) -> Dict[str, Any]:
    p = base()
    p.update(ov)
    body = RL.build_job_body(
        class_name=CLASS_NAME, instrument=INSTRUMENT, params=p,
        from_utc=frm, to_utc=to,
        bars_period_type="Minute", bars_period_value=BASE_TF // 60,
        slippage_ticks=int(p["SlippageTicks"]),
        role="research", session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    code, resp = RL.post("/api/jobs", body)
    jid = resp.get("job_id") if code == 201 and isinstance(resp, dict) else None
    print(f"submit {label:24s} {period_label} job={jid or resp}", flush=True)
    return {"label": label, "period": period_label, "job_id": jid}


def wait_for(rows: List[Dict[str, Any]], timeout_s: int = 7200) -> None:
    root = RL.jobs_root()
    rem = {str(r["job_id"]) for r in rows if r.get("job_id")}
    deadline = time.time() + timeout_s
    last = 0.0
    while rem:
        if time.time() > deadline:
            raise TimeoutError(f"timeout: {sorted(rem)}")
        for j in list(rem):
            for st in ("done", "failed", "cancelled"):
                if (root / st / j).is_dir():
                    rem.discard(j)
                    break
        now = time.time()
        if now - last >= 30 and rem:
            print(f"waiting: {len(rem)}", flush=True)
            last = now
        time.sleep(3)


def trades_of(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    p = Path(str(report.get("_dir") or "")) / "trades.json"
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict) and isinstance(raw.get("trades"), list):
            return raw["trades"]
    return []


def sb_pct(trades: List[Dict[str, Any]]) -> float:
    if not trades:
        return 0.0
    same = 0; counted = 0
    for t in trades:
        e = t.get("entry_time_utc") or t.get("entry_time") or ""
        x = t.get("exit_time_utc")  or t.get("exit_time")  or ""
        if not e or not x:
            continue
        try:
            de = datetime.fromisoformat(e.replace("Z", "+00:00"))
            dx = datetime.fromisoformat(x.replace("Z", "+00:00"))
        except Exception:
            continue
        eb = int(de.timestamp()) // BASE_TF
        xb = int(dx.timestamp()) // BASE_TF
        counted += 1
        if eb == xb:
            same += 1
    return round(same / counted * 100.0, 1) if counted else 0.0


def summarize(row: Dict[str, Any]) -> Dict[str, Any]:
    rep = RL.read_job_report(row["job_id"]) or {}
    tr = trades_of(rep)
    pnls = [
        float(t.get("pnl_currency") or 0.0)
        - FEE * max(1.0, abs(float(t.get("quantity") or 1)))
        for t in tr
    ]
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    pf = gp / gl if gl > 0 else (math.inf if gp > 0 else 0.0)
    eq = 0.0; peak = 0.0; dd = 0.0
    for p in pnls:
        eq += p; peak = max(peak, eq); dd = min(dd, eq - peak)
    wins = sum(1 for p in pnls if p > 0)
    wr = (wins / len(pnls) * 100.0) if pnls else 0.0
    return {
        "label": row["label"], "period": row["period"],
        "n": len(tr), "net": round(sum(pnls), 2),
        "pf": round(pf, 3) if not math.isinf(pf) else math.inf,
        "dd": round(dd, 2), "sb": sb_pct(tr), "wr": round(wr, 1),
    }


def main() -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle = RL.DATA / "research" / f"mnq_cell019_orb_retest_h1_refine_{ts}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"Engine #7 ORB-Retest H1 REFINE  bundle: {bundle}", flush=True)
    print(f"variants: {len(VARIANTS)}  years: {len(PERIODS)}  total_jobs: {len(VARIANTS)*len(PERIODS)}", flush=True)

    rows: List[Dict[str, Any]] = []
    for lab, ov in VARIANTS:
        for pl, frm, to in PERIODS:
            rows.append(submit_job(lab, pl, frm, to, ov))

    wait_for(rows)
    sums = [summarize(r) for r in rows]

    print("\n--- RESULTS ---", flush=True)
    for s in sums:
        pfs = f"{s['pf']:.3f}" if not (isinstance(s["pf"], float) and math.isinf(s["pf"])) else "inf"
        gate_dd = "OK " if RL.max_drawdown_within_budget(s["dd"]) else "DD!"
        gate_pf = "OK " if s["pf"] >= 1.25 else "PF!"
        print(
            f"  {s['label']:24s} {s['period']}  n={s['n']:>3}  "
            f"net={s['net']:>+9.2f}  pf={pfs:>7}  dd={s['dd']:>+9.2f}  "
            f"sb%={s['sb']:>5.1f}  wr={s['wr']:>5.1f}  [{gate_pf}|{gate_dd}]",
            flush=True,
        )

    # Cross-year gate: both positive PF, 2025 dd >= -300
    by_lab: Dict[str, Dict[str, Any]] = {}
    for s in sums:
        by_lab.setdefault(s["label"], {})[s["period"]] = s

    print("\nCROSS-YEAR GATE (both>0, 2025 dd>=-300, 2025 PF>=1.25):", flush=True)
    full_pass: List[str] = []
    partial_pass: List[str] = []
    for lab, p in by_lab.items():
        y24 = p.get("2024", {}); y25 = p.get("2025", {})
        net24 = y24.get("net") or 0; net25 = y25.get("net") or 0
        dd25  = y25.get("dd") or -9999
        pf24  = y24.get("pf") or 0; pf25 = y25.get("pf") or 0
        if net24 > 0 and net25 > 0:
            tag = f"  {lab:24s}  2024 n={y24.get('n'):>3} net={net24:>+8.2f} pf={pf24:.3f} dd={y24.get('dd'):>+8.2f}  |  2025 n={y25.get('n'):>3} net={net25:>+8.2f} pf={pf25:.3f} dd={dd25:>+8.2f}"
            if pf25 >= 1.25 and RL.max_drawdown_within_budget(dd25):
                full_pass.append(tag + "  *** GATE PASS ***")
            else:
                partial_pass.append(tag + f"  (pf25={pf25:.3f} dd25={dd25:.0f})")

    if full_pass:
        print("FULL PASS:", flush=True)
        for t in full_pass: print(t, flush=True)
    else:
        print("  (none pass all gates)", flush=True)
    if partial_pass:
        print("PARTIAL (both-years positive):", flush=True)
        for t in partial_pass: print(t, flush=True)

    (bundle / "summary.json").write_text(
        json.dumps(sums, indent=2, default=str), encoding="utf-8"
    )
    print(f"\nsaved: {bundle / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()
