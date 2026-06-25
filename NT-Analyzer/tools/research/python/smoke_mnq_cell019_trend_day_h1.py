"""Smoke probe Engine #6 RTH H1 trend-day bias continuation.

8 variants × 2 years = 16 jobs. Per project rules H1 same-bar is
structurally impossible (any meaningful stop/target distance exceeds
single H1 bar); looking for PF >= 1.25 cross-year positive.
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

CLASS_NAME = "NTAMnqRthTrendDayH1C019"
INSTRUMENT = "MNQ 06-26"
SESSION_TEMPLATE = "CME US Index Futures RTH"
BARS = 60
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
        "BiasEmaPeriod": 20,
        "Bar1RangeMinTicks": 16, "Bar1RangeMaxTicks": 400, "Bar1MinBodyToRange": 0.40,
        "RequirePriorDayAlignment": True,
        "AdxPeriod": 14, "MinAdxTrend": 18.0, "MaxAdxTrend": 60.0,
        "RsiPeriod": 14, "RsiLongMax": 72.0, "RsiShortMin": 28.0,
        "AtrPeriod": 14, "VolumeSmaPeriod": 20,
        "VolCeilingFactor": 5.0, "VolMinFactor": 0.40,
        "StopBufferPoints": 3.0, "MinStopPoints": 14.0, "MaxStopPoints": 50.0,
        "AtrStopMult": 1.0, "RewardRiskRatio": 1.4, "MinTargetPoints": 18.0,
        "MoveToBreakevenAtR": 0.7, "BreakevenPlusTicks": 4,
        "UseTrailingStop": True, "TrailAfterR": 1.0, "TrailDistanceTicks": 40,
        "UseTimeStop": False, "TimeStopBars": 4, "MinProgressR": 0.30,
        "RiskPerTradePct": 0.60, "UserMaxContracts": 1, "MaxOpenPositions": 1,
        "MaxDailyLossUsd": 120.0, "MaxWeeklyLossUsd": 300.0,
        "MaxTradesPerDay": 1, "HardMaxTradesPerDay": 1,
        "MaxConsecutiveLosses": 4, "PauseAfterConsecutiveLosses": 3,
        "PauseMinutesAfterLosses": 60,
        "RoundTurnCommission": FEE, "SlippageTicks": 1,
    }


# 2 align × 2 rr × 2 adx = 8 variants
VARIANTS = []
for align in (True, False):
    for rr in (1.3, 1.6):
        for adx in (16.0, 22.0):
            lab = f"al{int(align)}_rr{int(rr*10):02d}_adx{int(adx):02d}"
            ov = {"RequirePriorDayAlignment": align, "RewardRiskRatio": rr, "MinAdxTrend": adx}
            VARIANTS.append((lab, ov))


def submit_job(label: str, period_label: str, frm: str, to: str, ov: Dict[str, Any]) -> Dict[str, Any]:
    p = base(); p.update(ov)
    body = RL.build_job_body(
        class_name=CLASS_NAME, instrument=INSTRUMENT, params=p,
        from_utc=frm, to_utc=to, bars_period_type="Minute",
        bars_period_value=BARS, slippage_ticks=int(p["SlippageTicks"]),
        role="smoke", session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    code, resp = RL.post("/api/jobs", body)
    jid = resp.get("job_id") if code == 201 and isinstance(resp, dict) else None
    print(f"submit {label:20s} {period_label} job={jid or resp}", flush=True)
    return {"label": label, "period": period_label, "job_id": jid}


def wait_for(rows: List[Dict[str, Any]], timeout_s: int = 7200) -> None:
    root = RL.jobs_root()
    rem = {str(r["job_id"]) for r in rows if r.get("job_id")}
    deadline = time.time() + timeout_s
    last = 0.0
    while rem:
        if time.time() > deadline: raise TimeoutError(f"timeout: {sorted(rem)}")
        for j in list(rem):
            for st in ("done", "failed", "cancelled"):
                if (root / st / j).is_dir(): rem.discard(j); break
        now = time.time()
        if now - last >= 30 and rem:
            print(f"waiting: {len(rem)}", flush=True); last = now
        time.sleep(3)


def trades_of(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    p = Path(str(report.get("_dir") or "")) / "trades.json"
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list): return raw
        if isinstance(raw, dict) and isinstance(raw.get("trades"), list): return raw["trades"]
    return []


def sb_pct(trades: List[Dict[str, Any]]) -> float:
    if not trades: return 0.0
    same = 0; counted = 0
    for t in trades:
        e = t.get("entry_time_utc") or t.get("entry_time") or ""
        x = t.get("exit_time_utc") or t.get("exit_time") or ""
        if not e or not x: continue
        try:
            de = datetime.fromisoformat(e.replace("Z", "+00:00"))
            dx = datetime.fromisoformat(x.replace("Z", "+00:00"))
        except Exception: continue
        eb = int(de.timestamp()) // BASE_TF
        xb = int(dx.timestamp()) // BASE_TF
        counted += 1
        if eb == xb: same += 1
    return round(same / counted * 100.0, 1) if counted else 0.0


def summarize(row: Dict[str, Any]) -> Dict[str, Any]:
    rep = RL.read_job_report(row["job_id"]) or {}
    tr = trades_of(rep)
    pnls = [float(t.get("pnl_currency") or 0.0) - FEE * max(1.0, abs(float(t.get("quantity") or 1))) for t in tr]
    gp = sum(p for p in pnls if p > 0); gl = abs(sum(p for p in pnls if p < 0))
    pf = gp / gl if gl > 0 else (math.inf if gp > 0 else 0.0)
    eq = 0.0; peak = 0.0; dd = 0.0
    for p in pnls:
        eq += p; peak = max(peak, eq); dd = min(dd, eq - peak)
    wins = sum(1 for p in pnls if p > 0)
    wr = (wins / len(pnls) * 100.0) if pnls else 0.0
    return {"label": row["label"], "period": row["period"], "n": len(tr),
            "net": round(sum(pnls), 2),
            "pf": round(pf, 3) if not math.isinf(pf) else math.inf,
            "dd": round(dd, 2), "sb": sb_pct(tr), "wr": round(wr, 1)}


def main() -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle = RL.DATA / "research" / f"mnq_cell019_trend_day_h1_smoke_{ts}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)

    rows: List[Dict[str, Any]] = []
    for lab, ov in VARIANTS:
        for pl, frm, to in PERIODS:
            rows.append(submit_job(lab, pl, frm, to, ov))
    wait_for(rows)
    sums = [summarize(r) for r in rows]
    for s in sums:
        pfs = f"{s['pf']:.3f}" if not (isinstance(s['pf'], float) and math.isinf(s['pf'])) else "inf"
        print(f"  done {s['label']:20s} {s['period']} n={s['n']:>4} net={s['net']:>+9.2f} pf={pfs:>7} dd={s['dd']:>+9.2f} sb%={s['sb']:>5.1f} wr={s['wr']:>5.1f}", flush=True)

    by_lab: Dict[str, Dict[str, Any]] = {}
    for s in sums:
        by_lab.setdefault(s["label"], {})[s["period"]] = s
    print("\nBOTH-YEARS-POSITIVE:", flush=True)
    found = False
    for lab, p in by_lab.items():
        y24 = p.get("2024", {}); y25 = p.get("2025", {})
        if (y24.get("net") or 0) > 0 and (y25.get("net") or 0) > 0:
            found = True
            print(f"  {lab:20s} 2024 n={y24.get('n')} net={y24.get('net'):>+8.2f} pf={y24.get('pf')} sb={y24.get('sb')} | "
                  f"2025 n={y25.get('n')} net={y25.get('net'):>+8.2f} pf={y25.get('pf')} sb={y25.get('sb')}", flush=True)
    if not found:
        print("  (none)", flush=True)
    (bundle / "summary.json").write_text(json.dumps(sums, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
