"""Quick 30m TF probe of NTAMnqOvernightSettlementBreakoutC019 on RTH window.

Hypothesis: 15m RTH gap-continuation hits PF ceiling 1.15-1.20 with sb 64%.
At 30m bars the trade lives across multiple bars (kills same-bar artifact),
ADX/RSI smooth, breakout signal lower-frequency but higher-quality.

8 variants × 2 years = 16 jobs. Looking for PF >= 1.20, sb < 50%, net > 0.
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

CLASS_NAME = "NTAMnqOvernightSettlementBreakoutC019"
INSTRUMENT = "MNQ 06-26"
SESSION_TEMPLATE = "CME US Index Futures RTH"
BARS = 30
BASE_TF = 1800
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
        "TradeStartTime": 700, "TradeEndTime": 1130,
        "ForceFlatTime": 1230, "SettlementTimePT": 1300,
        "MinPointsFromSettlement": 20.0, "MaxPointsFromSettlement": 200.0,
        "BreakoutLookback": 3,
        "AdxPeriod": 14, "MinAdxTrend": 22.0,
        "RsiPeriod": 14, "RsiLongMin": 55.0, "RsiShortMax": 45.0,
        "AtrPeriod": 14, "VolumeSmaPeriod": 20,
        "VolCeilingFactor": 5.0, "VolMinFactor": 0.40,
        "MinBarRangeTicks": 8, "MaxBarRangeTicks": 1200,
        "StopBufferPoints": 2.0, "MinStopPoints": 8.0, "MaxStopPoints": 24.0,
        "AtrStopMult": 1.2,
        "RewardRiskRatio": 2.0, "MinTargetPoints": 10.0,
        "MoveToBreakevenAtR": 0.8, "BreakevenPlusTicks": 2,
        "UseTrailingStop": True, "TrailAfterR": 1.2, "TrailDistanceTicks": 20,
        "UseTimeStop": True, "TimeStopBars": 6, "MinProgressR": 0.40,
        "RiskPerTradePct": 0.60, "UserMaxContracts": 1, "MaxOpenPositions": 1,
        "MaxDailyLossUsd": 120.0, "MaxWeeklyLossUsd": 300.0,
        "MaxTradesPerDay": 2, "HardMaxTradesPerDay": 3,
        "MaxConsecutiveLosses": 5, "PauseAfterConsecutiveLosses": 3,
        "PauseMinutesAfterLosses": 60,
        "RoundTurnCommission": FEE, "SlippageTicks": 1,
    }


# 2 impulse × 2 ADX × 2 RR = 8 variants
VARIANTS = []
for imp in (14.0, 20.0):
    for adx in (20.0, 25.0):
        for rr in (1.8, 2.2):
            lab = f"imp{int(imp):02d}_adx{int(adx):02d}_rr{int(rr*10):02d}"
            ov = {"MinPointsFromSettlement": imp, "MinAdxTrend": adx, "RewardRiskRatio": rr}
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
    print(f"submit {label:24s} {period_label} job={jid or resp}", flush=True)
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
    r = report.get("result") or {}
    t = r.get("trades")
    return t if isinstance(t, list) else []


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
    bundle = RL.DATA / "research" / f"mnq_cell019_rth_gap_30m_probe_{ts}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)

    rows: List[Dict[str, Any]] = []
    for lab, ov in VARIANTS:
        for pl, frm, to in PERIODS:
            rows.append(submit_job(lab, pl, frm, to, ov))
    wait_for(rows)
    sums = [summarize(r) for r in rows]
    for s in sums:
        print(f"  done {s['label']:24s} {s['period']} n={s['n']:>4} net={s['net']:>+9.2f} pf={s['pf']:>7} dd={s['dd']:>+9.2f} sb%={s['sb']:>5.1f} wr={s['wr']:>5.1f}", flush=True)

    by_lab: Dict[str, Dict[str, Any]] = {}
    for s in sums:
        by_lab.setdefault(s["label"], {})[s["period"]] = s
    print("\nBOTH-YEARS-POSITIVE:", flush=True)
    found = False
    for lab, p in by_lab.items():
        y24 = p.get("2024", {}); y25 = p.get("2025", {})
        if (y24.get("net") or 0) > 0 and (y25.get("net") or 0) > 0:
            found = True
            print(f"  {lab:24s} 2024 n={y24.get('n')} net={y24.get('net'):>+8.2f} pf={y24.get('pf')} sb%={y24.get('sb')} | 2025 n={y25.get('n')} net={y25.get('net'):>+8.2f} pf={y25.get('pf')} sb%={y25.get('sb')}", flush=True)
    if not found:
        print("  (none)", flush=True)
    (bundle / "summary.json").write_text(json.dumps(sums, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
