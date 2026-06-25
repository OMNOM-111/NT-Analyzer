"""Quick RTH-window pivot for Engine #4 NTAMnqOvernightSettlementBreakoutC019.

Same class, but trade window shifted to RTH 06:30-12:30 PT. Tests whether
"continuation past prior RTH settlement" works during NY cash rather than
overnight. Settlement anchor = prior day 13:00 PT close (captured by the
class on the last RTH bar before 13:00 PT each day). When trades happen
the next 06:30 PT open, this becomes effectively a gap-continuation /
gap-trend signal vs. prior settlement.
"""
from __future__ import annotations
import argparse
import json
import math
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402

CLASS_NAME = "NTAMnqOvernightSettlementBreakoutC019"
ROOT = "MNQ"
INSTRUMENT = "MNQ 06-26"
SESSION_TEMPLATE = "CME US Index Futures RTH"
BARS_PERIOD_VALUE = 15
BASE_TF_SECONDS = 900

SMOKE = ("Smoke", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z")
FEE_BASE = max(1.90, RL.fee_for(ROOT))


def base_params() -> Dict[str, Any]:
    return {
        "InstrumentName": ROOT,
        "ContractName": INSTRUMENT,
        "SessionTemplateName": SESSION_TEMPLATE,
        "BaseTimeframeSeconds": BASE_TF_SECONDS,
        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": RL.margin_for(ROOT),
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "EnableLong": True,
        "EnableShort": True,
        # RTH window 06:30-12:30 PT (linear, NOT wrapping).
        "TradeStartTime": 630,
        "TradeEndTime": 1230,
        "ForceFlatTime": 1245,
        # Prior RTH close print time PT.
        "SettlementTimePT": 1300,
        "MinPointsFromSettlement": 8.0,
        "MaxPointsFromSettlement": 200.0,
        "BreakoutLookback": 4,
        "AdxPeriod": 14, "MinAdxTrend": 18.0,
        "RsiPeriod": 14, "RsiLongMin": 50.0, "RsiShortMax": 50.0,
        "AtrPeriod": 14,
        "VolumeSmaPeriod": 20, "VolCeilingFactor": 5.0, "VolMinFactor": 0.40,
        "MinBarRangeTicks": 4, "MaxBarRangeTicks": 600,
        "StopBufferPoints": 2.0, "MinStopPoints": 6.0, "MaxStopPoints": 20.0,
        "AtrStopMult": 1.4,
        "RewardRiskRatio": 2.0, "MinTargetPoints": 8.0,
        "MoveToBreakevenAtR": 0.8, "BreakevenPlusTicks": 2,
        "UseTrailingStop": True, "TrailAfterR": 1.2, "TrailDistanceTicks": 16,
        "UseTimeStop": True, "TimeStopBars": 10, "MinProgressR": 0.40,
        "RiskPerTradePct": 0.60, "UserMaxContracts": 1, "MaxOpenPositions": 1,
        "MaxDailyLossUsd": 120.0, "MaxWeeklyLossUsd": 300.0,
        "MaxTradesPerDay": 3, "HardMaxTradesPerDay": 4,
        "MaxConsecutiveLosses": 5, "PauseAfterConsecutiveLosses": 3,
        "PauseMinutesAfterLosses": 60,
        "RoundTurnCommission": FEE_BASE, "SlippageTicks": 1,
    }


def candidate(label: str, **overrides: Any) -> Dict[str, Any]:
    p = base_params()
    p.update(overrides)
    return {"label": label, "params": p}


def candidates() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for lb in [3, 5, 8]:
        for adx in [12.0, 22.0]:
            for rr in [1.8, 2.5]:
                for (mn, mx, am) in [(6.0, 16.0, 1.2), (8.0, 24.0, 1.6)]:
                    label = f"lb{lb:02d}_adx{int(adx):02d}_rr{int(rr*10):03d}_st{int(mn):02d}{int(mx):02d}"
                    out.append(candidate(label, BreakoutLookback=lb, MinAdxTrend=adx,
                                         RewardRiskRatio=rr, MinStopPoints=mn,
                                         MaxStopPoints=mx, AtrStopMult=am))
    return out


def submit_job(bundle: Path, label: str, params: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(params)
    body = RL.build_job_body(
        class_name=CLASS_NAME, instrument=INSTRUMENT, params=p,
        from_utc=SMOKE[1], to_utc=SMOKE[2],
        bars_period_type="Minute", bars_period_value=BARS_PERIOD_VALUE,
        slippage_ticks=1, role="smoke",
        session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    code, resp = RL.post("/api/jobs", body)
    jid = resp.get("job_id") if code == 201 and isinstance(resp, dict) else None
    row = {"label": label, "code": code, "job_id": jid, "params": p, "fee": FEE_BASE}
    print(f"submit {label:36s} code={code} job={jid or resp}", flush=True)
    return row


def job_state(job_id: str) -> Optional[str]:
    base = RL.jobs_root()
    for s in ("done", "failed", "cancelled", "running", "pending"):
        if (base / s / job_id).is_dir(): return s
    return None


def wait_for(rows: List[Dict[str, Any]]) -> None:
    rem = {str(r["job_id"]) for r in rows if r.get("job_id")}
    last = 0.0
    while rem:
        for j in list(rem):
            if job_state(j) in {"done", "failed", "cancelled"}: rem.remove(j)
        now = time.time()
        if now - last >= 30 and rem:
            print(f"waiting: {len(rem)} jobs", flush=True); last = now
        time.sleep(3)


def trades_from(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = report.get("result") or {}
    t = result.get("trades")
    if isinstance(t, list): return t
    d = Path(str(report.get("_dir") or ""))
    p = d / "trades.json"
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list): return raw
        if isinstance(raw, dict) and isinstance(raw.get("trades"), list): return raw["trades"]
    return []


def summarize(row: Dict[str, Any]) -> Dict[str, Any]:
    jid = str(row.get("job_id") or "")
    report = RL.read_job_report(jid) if jid else None
    if not report:
        return {"label": row["label"], "trades": 0, "net": 0.0, "pf": 0.0, "dd": 0.0}
    trades = trades_from(report)
    fee = float(row.get("fee") or 0.0)
    pnls = [float(t.get("pnl_currency") or 0.0) - fee * max(1.0, abs(float(t.get("quantity") or 1))) for t in trades]
    gp = sum(p for p in pnls if p > 0); gl = abs(sum(p for p in pnls if p < 0))
    pf = gp / gl if gl > 0 else (math.inf if gp > 0 else 0.0)
    eq = 0.0; peak = 0.0; dd = 0.0
    for p in pnls:
        eq += p; peak = max(peak, eq); dd = min(dd, eq - peak)
    return {"label": row["label"], "trades": len(trades), "net": round(sum(pnls), 2),
            "pf": pf, "dd": round(dd, 2),
            "wr": round((sum(1 for p in pnls if p > 0) / len(pnls) * 100) if pnls else 0, 1)}


def main() -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle = RL.DATA / "research" / f"mnq_cell019_rth_gap_continuation_{ts}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)
    rows = [submit_job(bundle, c["label"], c["params"]) for c in candidates()]
    wait_for(rows)
    sums = [summarize(r) for r in rows]
    sums.sort(key=lambda s: s["net"], reverse=True)
    print("\nResults (sorted by net):", flush=True)
    for s in sums:
        pfs = "inf" if s["pf"] == math.inf else f"{s['pf']:.3f}"
        print(f"  {s['label']:36s} trades={s['trades']:>4} net={s['net']:>9.2f} pf={pfs:>7} dd={s['dd']:>9.2f} wr={s['wr']:>5.1f}%", flush=True)
    (bundle / "smoke_rows.json").write_text(json.dumps(sums, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
