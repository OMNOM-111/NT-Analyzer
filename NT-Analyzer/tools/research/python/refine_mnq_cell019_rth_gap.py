"""Refinement sweep around winning Engine #4 RTH gap continuation variant.

Winner from prior sweep: lb=3, ADX>=22, RR=2.5, stop 6-16, AtrStopMult=1.2
PF 1.075 / 267 trades / net +$400 / dd -$490 (MNQ 2025).

This script tightens entry filters (RSI threshold, MinPointsFromSettlement,
VolMinFactor) and narrows trading window to first ~3 hours of RTH where the
gap impulse is strongest. Also tries reduced MaxTradesPerDay and tighter
trend filter (ADX>=25/28).
"""
from __future__ import annotations
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402

CLASS_NAME = "NTAMnqOvernightSettlementBreakoutC019"
INSTRUMENT = "MNQ 06-26"
SESSION_TEMPLATE = "CME US Index Futures RTH"
BARS = 15
FEE = max(1.90, RL.fee_for("MNQ"))


def base() -> Dict[str, Any]:
    return {
        "InstrumentName": "MNQ", "ContractName": INSTRUMENT,
        "SessionTemplateName": SESSION_TEMPLATE, "BaseTimeframeSeconds": 900,
        "StartingCapital": 2000.0, "IntradayOnly": True,
        "ActiveMarginPerContract": RL.margin_for("MNQ"),
        "MaxContractsByCapital": 20, "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "EnableLong": True, "EnableShort": True,
        "TradeStartTime": 630, "TradeEndTime": 1000,
        "ForceFlatTime": 1200, "SettlementTimePT": 1300,
        "MinPointsFromSettlement": 10.0, "MaxPointsFromSettlement": 200.0,
        "BreakoutLookback": 3,
        "AdxPeriod": 14, "MinAdxTrend": 22.0,
        "RsiPeriod": 14, "RsiLongMin": 50.0, "RsiShortMax": 50.0,
        "AtrPeriod": 14, "VolumeSmaPeriod": 20,
        "VolCeilingFactor": 5.0, "VolMinFactor": 0.40,
        "MinBarRangeTicks": 4, "MaxBarRangeTicks": 600,
        "StopBufferPoints": 2.0, "MinStopPoints": 6.0, "MaxStopPoints": 16.0,
        "AtrStopMult": 1.2,
        "RewardRiskRatio": 2.5, "MinTargetPoints": 8.0,
        "MoveToBreakevenAtR": 0.8, "BreakevenPlusTicks": 2,
        "UseTrailingStop": True, "TrailAfterR": 1.2, "TrailDistanceTicks": 16,
        "UseTimeStop": True, "TimeStopBars": 10, "MinProgressR": 0.40,
        "RiskPerTradePct": 0.60, "UserMaxContracts": 1, "MaxOpenPositions": 1,
        "MaxDailyLossUsd": 120.0, "MaxWeeklyLossUsd": 300.0,
        "MaxTradesPerDay": 2, "HardMaxTradesPerDay": 3,
        "MaxConsecutiveLosses": 5, "PauseAfterConsecutiveLosses": 3,
        "PauseMinutesAfterLosses": 60,
        "RoundTurnCommission": FEE, "SlippageTicks": 1,
    }


def cand(label: str, **overrides: Any) -> Dict[str, Any]:
    p = base(); p.update(overrides)
    return {"label": label, "params": p}


def variants() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # Dim 1: trade window (4 options).
    windows = [
        ("wA630_900",  {"TradeStartTime": 630,  "TradeEndTime": 900,  "ForceFlatTime": 1100}),
        ("wA630_1000", {"TradeStartTime": 630,  "TradeEndTime": 1000, "ForceFlatTime": 1200}),
        ("wB730_1100", {"TradeStartTime": 730,  "TradeEndTime": 1100, "ForceFlatTime": 1230}),
        ("wC630_1230", {"TradeStartTime": 630,  "TradeEndTime": 1230, "ForceFlatTime": 1245}),
    ]
    # Dim 2: MinPoints + RSI tightness pairing.
    impulse = [
        ("imp_lo",  {"MinPointsFromSettlement": 8.0,  "RsiLongMin": 50.0, "RsiShortMax": 50.0}),
        ("imp_mid", {"MinPointsFromSettlement": 14.0, "RsiLongMin": 55.0, "RsiShortMax": 45.0}),
        ("imp_hi",  {"MinPointsFromSettlement": 22.0, "RsiLongMin": 58.0, "RsiShortMax": 42.0}),
    ]
    # Dim 3: ADX strength.
    trend = [
        ("adx22", {"MinAdxTrend": 22.0}),
        ("adx28", {"MinAdxTrend": 28.0}),
    ]
    for (wl, wo) in windows:
        for (il, io) in impulse:
            for (tl, to) in trend:
                label = f"{wl}_{il}_{tl}"
                params = {**wo, **io, **to}
                out.append(cand(label, **params))
    return out


def submit(label: str, params: Dict[str, Any], year: str) -> Dict[str, Any]:
    frm = f"{year}-01-01T00:00:00Z"
    to = f"{year}-12-31T23:59:59Z"
    body = RL.build_job_body(
        class_name=CLASS_NAME, instrument=INSTRUMENT, params=params,
        from_utc=frm, to_utc=to, bars_period_type="Minute",
        bars_period_value=BARS, slippage_ticks=1, role="smoke",
        session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    code, resp = RL.post("/api/jobs", body)
    jid = resp.get("job_id") if code == 201 and isinstance(resp, dict) else None
    print(f"submit {year} {label:40s} code={code} job={jid or resp}", flush=True)
    return {"label": label, "year": year, "job_id": jid, "params": params}


def wait_for(rows: List[Dict[str, Any]]) -> None:
    base = RL.jobs_root()
    rem = {str(r["job_id"]) for r in rows if r.get("job_id")}
    last = 0.0
    while rem:
        for j in list(rem):
            for s in ("done", "failed", "cancelled"):
                if (base / s / j).is_dir():
                    rem.discard(j); break
        now = time.time()
        if now - last >= 30 and rem:
            print(f"waiting: {len(rem)} jobs", flush=True); last = now
        time.sleep(3)


def trades(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    r = report.get("result") or {}
    t = r.get("trades")
    if isinstance(t, list): return t
    p = Path(str(report.get("_dir") or "")) / "trades.json"
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list): return raw
        if isinstance(raw, dict) and isinstance(raw.get("trades"), list): return raw["trades"]
    return []


def summarize(row: Dict[str, Any]) -> Dict[str, Any]:
    jid = str(row.get("job_id") or "")
    rep = RL.read_job_report(jid) if jid else None
    if not rep:
        return {**row, "n": 0, "net": 0.0, "pf": 0.0, "dd": 0.0, "wr": 0.0}
    tr = trades(rep)
    pnls = [float(t.get("pnl_currency") or 0.0) - FEE * max(1.0, abs(float(t.get("quantity") or 1))) for t in tr]
    gp = sum(p for p in pnls if p > 0); gl = abs(sum(p for p in pnls if p < 0))
    pf = gp / gl if gl > 0 else (math.inf if gp > 0 else 0.0)
    eq = 0.0; peak = 0.0; dd = 0.0
    for p in pnls:
        eq += p; peak = max(peak, eq); dd = min(dd, eq - peak)
    return {"label": row["label"], "year": row["year"], "n": len(tr),
            "net": round(sum(pnls), 2), "pf": pf, "dd": round(dd, 2),
            "wr": round((sum(1 for p in pnls if p > 0) / len(pnls) * 100) if pnls else 0, 1)}


def main() -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle = RL.DATA / "research" / f"mnq_cell019_rth_gap_refine_{ts}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)

    vars_ = variants()
    print(f"variants: {len(vars_)} x 2 years = {len(vars_)*2} jobs", flush=True)

    rows: List[Dict[str, Any]] = []
    for v in vars_:
        rows.append(submit(v["label"], v["params"], "2024"))
        rows.append(submit(v["label"], v["params"], "2025"))
    wait_for(rows)

    sums = [summarize(r) for r in rows]
    by_label: Dict[str, Dict[str, Any]] = {}
    for s in sums:
        lab = s["label"]
        if lab not in by_label:
            by_label[lab] = {"label": lab, "2024": None, "2025": None}
        by_label[lab][s["year"]] = s

    combined: List[Dict[str, Any]] = []
    for lab, d in by_label.items():
        a = d["2024"] or {"n": 0, "net": 0.0, "pf": 0.0, "dd": 0.0}
        b = d["2025"] or {"n": 0, "net": 0.0, "pf": 0.0, "dd": 0.0}
        total_n = (a.get("n") or 0) + (b.get("n") or 0)
        total_net = (a.get("net") or 0.0) + (b.get("net") or 0.0)
        gp = max(0.0, (a.get("net") or 0.0)) + max(0.0, (b.get("net") or 0.0))
        # PF needs gross profit/loss across both years; use weighted approx via PF.
        # Rather than reconstruct, compute combined PF from individual pf*gl proxies:
        # For simplicity, take min(pf_2024, pf_2025).
        pfs = [a.get("pf") or 0.0, b.get("pf") or 0.0]
        pf_min = min(p for p in pfs if p > 0) if any(p > 0 for p in pfs) else 0.0
        combined.append({
            "label": lab, "n": total_n, "net": round(total_net, 2),
            "pf_2024": a.get("pf") or 0.0, "pf_2025": b.get("pf") or 0.0,
            "pf_min": pf_min,
            "net_2024": a.get("net") or 0.0, "net_2025": b.get("net") or 0.0,
            "n_2024": a.get("n") or 0, "n_2025": b.get("n") or 0,
            "wr_2024": a.get("wr") or 0.0, "wr_2025": b.get("wr") or 0.0,
            "dd_2024": a.get("dd") or 0.0, "dd_2025": b.get("dd") or 0.0,
        })

    combined.sort(key=lambda x: (x["net_2024"] > 0 and x["net_2025"] > 0, x["net"]), reverse=True)
    print("\nResults (combined, both years; flagged if both years positive):", flush=True)
    print(f"  {'label':40s} {'n24':>4} {'n25':>4} net24    net25    pf24   pf25   pfmin  bothPos", flush=True)
    both_positive: List[Dict[str, Any]] = []
    for c in combined:
        bp = (c["net_2024"] > 0 and c["net_2025"] > 0)
        flag = "*" if bp else " "
        if bp: both_positive.append(c)
        pf24s = "inf" if c["pf_2024"] == math.inf else f"{c['pf_2024']:.3f}"
        pf25s = "inf" if c["pf_2025"] == math.inf else f"{c['pf_2025']:.3f}"
        pfms = "inf" if c["pf_min"] == math.inf else f"{c['pf_min']:.3f}"
        print(f"  {flag} {c['label']:40s} {c['n_2024']:>4} {c['n_2025']:>4} "
              f"{c['net_2024']:>+8.2f} {c['net_2025']:>+8.2f} "
              f"{pf24s:>6} {pf25s:>6} {pfms:>6}", flush=True)

    (bundle / "combined.json").write_text(json.dumps(combined, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nBoth-years-positive variants: {len(both_positive)}", flush=True)
    for c in both_positive[:10]:
        print(f"  {c['label']}: net24={c['net_2024']:+.2f} net25={c['net_2025']:+.2f} pf_min={c['pf_min']:.3f}", flush=True)


if __name__ == "__main__":
    main()
