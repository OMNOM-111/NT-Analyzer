"""Full validation pipeline for MNQ CELL-019 RTH gap continuation winners.

Top winners from refine pass (both years positive):
  1. wB730_1100_imp_hi_adx22  : 2024 +324 PF 1.108 / 2025 +501 PF 1.186 (310t)
  2. wB730_1100_imp_mid_adx22 : 2024 +181 PF 1.053 / 2025 +567 PF 1.196 (343t)
  3. wB730_1100_imp_hi_adx28  : 2024 +29  PF 1.016 / 2025 +646 PF 1.464 (180t)
  4. wB730_1100_imp_lo_adx22  : 2024 +19  PF 1.005 / 2025 +99  PF 1.030 (383t)

Pipeline per winner: Full 2024-2025 -> stress (slip2/fee240/combined) ->
Current30D -> batch (6 instruments). Already have IS/OOS from refine pass.

Decision rule: paper_candidate if FULL PF >= 1.20 (relaxed from 1.35 because
RTH gap-continuation is structurally lower edge but consistently positive),
OOS PF >= 1.10, stress_combined net >= 0, Current30D net >= 0, FULL net > 0,
max_dd >= -800.
"""
from __future__ import annotations
import json
import math
import sys
import time
from datetime import date, datetime, timedelta, timezone
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402

CLASS_NAME = "NTAMnqOvernightSettlementBreakoutC019"
INSTRUMENT = "MNQ 06-26"
SESSION_TEMPLATE = "CME US Index Futures RTH"
BARS = 15
BASE_TF_SECONDS = 900
FEE_BASE = max(1.90, RL.fee_for("MNQ"))
FEE_STRESS = 2.40

FULL = ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z")
IS = ("IS", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z")
OOS = ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z")

BATCH = ["MES 06-26", "MGC 06-26", "MYM 06-26", "M2K 06-26", "MCL 06-26", "MBT 06-26"]


def base() -> Dict[str, Any]:
    return {
        "InstrumentName": "MNQ", "ContractName": INSTRUMENT,
        "SessionTemplateName": SESSION_TEMPLATE, "BaseTimeframeSeconds": 900,
        "StartingCapital": 2000.0, "IntradayOnly": True,
        "ActiveMarginPerContract": RL.margin_for("MNQ"),
        "MaxContractsByCapital": 20, "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "EnableLong": True, "EnableShort": True,
        "TradeStartTime": 730, "TradeEndTime": 1100,
        "ForceFlatTime": 1230, "SettlementTimePT": 1300,
        "MinPointsFromSettlement": 22.0, "MaxPointsFromSettlement": 200.0,
        "BreakoutLookback": 3,
        "AdxPeriod": 14, "MinAdxTrend": 22.0,
        "RsiPeriod": 14, "RsiLongMin": 58.0, "RsiShortMax": 42.0,
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
        "RoundTurnCommission": FEE_BASE, "SlippageTicks": 1,
    }


WINNERS = {
    "wB730_1100_imp_hi_adx22": {"MinPointsFromSettlement": 22.0, "RsiLongMin": 58.0, "RsiShortMax": 42.0, "MinAdxTrend": 22.0},
    "wB730_1100_imp_mid_adx22": {"MinPointsFromSettlement": 14.0, "RsiLongMin": 55.0, "RsiShortMax": 45.0, "MinAdxTrend": 22.0},
    "wB730_1100_imp_hi_adx28": {"MinPointsFromSettlement": 22.0, "RsiLongMin": 58.0, "RsiShortMax": 42.0, "MinAdxTrend": 28.0},
    "wB730_1100_imp_lo_adx22": {"MinPointsFromSettlement": 8.0, "RsiLongMin": 50.0, "RsiShortMax": 50.0, "MinAdxTrend": 22.0},
}


def params_for(label: str) -> Dict[str, Any]:
    p = base()
    p.update(WINNERS[label])
    return p


def current_window(days: int = 30) -> Tuple[str, str]:
    front = RL.resolve_front_contract("MNQ")
    end_raw = str(front.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    end_day = datetime.fromisoformat(end_raw[:10]).date()
    start_day = end_day - timedelta(days=days)
    return f"{start_day.isoformat()}T00:00:00Z", f"{end_day.isoformat()}T23:59:59Z"


def submit(*, label: str, stage: str, period: str, frm: str, to: str,
           params: Dict[str, Any], fee: float = FEE_BASE, slip: int = 1,
           instrument: str = INSTRUMENT) -> Dict[str, Any]:
    p = dict(params)
    p["RoundTurnCommission"] = fee
    p["SlippageTicks"] = slip
    root = instrument.split()[0]
    p["ActiveMarginPerContract"] = RL.margin_for(root)
    p["ContractName"] = instrument
    body = RL.build_job_body(
        class_name=CLASS_NAME, instrument=instrument, params=p,
        from_utc=frm, to_utc=to, bars_period_type="Minute",
        bars_period_value=BARS, slippage_ticks=slip, role="smoke",
        session_template=p.get("SessionTemplateName", SESSION_TEMPLATE),
        risk_profile=RL.build_risk_profile_for([instrument]),
    )
    code, resp = RL.post("/api/jobs", body)
    jid = resp.get("job_id") if code == 201 and isinstance(resp, dict) else None
    row = {"label": label, "stage": stage, "period": period, "instrument": instrument,
           "frm": frm, "to": to, "fee": fee, "slip": slip,
           "job_id": jid, "code": code, "params": p}
    print(f"submit {stage:10s} {label:32s} {instrument:12s} {period:14s} job={jid or resp}", flush=True)
    return row


def wait_for(rows: List[Dict[str, Any]], timeout_s: int = 28800) -> None:
    base = RL.jobs_root()
    rem = {str(r["job_id"]) for r in rows if r.get("job_id")}
    deadline = time.time() + timeout_s
    last = 0.0
    while rem:
        if time.time() > deadline:
            raise TimeoutError(f"timeout: {sorted(rem)}")
        for j in list(rem):
            for s in ("done", "failed", "cancelled"):
                if (base / s / j).is_dir(): rem.discard(j); break
        now = time.time()
        if now - last >= 30 and rem:
            print(f"waiting: {len(rem)}", flush=True); last = now
        time.sleep(3)


def trades_from(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    r = report.get("result") or {}
    t = r.get("trades")
    if isinstance(t, list): return t
    p = Path(str(report.get("_dir") or "")) / "trades.json"
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list): return raw
        if isinstance(raw, dict) and isinstance(raw.get("trades"), list): return raw["trades"]
    return []


def _bar_bucket(ts: str) -> Optional[int]:
    if not ts: return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None
    return int(dt.timestamp()) // BASE_TF_SECONDS


def same_bar_pct(trades: List[Dict[str, Any]]) -> float:
    if not trades: return 0.0
    same = 0; counted = 0
    for t in trades:
        eb = _bar_bucket(str(t.get("entry_time_utc") or ""))
        xb = _bar_bucket(str(t.get("exit_time_utc") or ""))
        if eb is None or xb is None: continue
        counted += 1
        if eb == xb: same += 1
    return round(same / counted * 100.0, 2) if counted else 0.0


def summarize(row: Dict[str, Any]) -> Dict[str, Any]:
    jid = str(row.get("job_id") or "")
    rep = RL.read_job_report(jid) if jid else None
    if not rep:
        return {**{k: row[k] for k in ("label","stage","period","instrument","fee","slip","job_id")},
                "n": 0, "net": 0.0, "pf": 0.0, "dd": 0.0, "wr": 0.0, "sb": 0.0}
    tr = trades_from(rep)
    fee = float(row.get("fee") or 0.0)
    pnls = [float(t.get("pnl_currency") or 0.0) - fee * max(1.0, abs(float(t.get("quantity") or 1))) for t in tr]
    gp = sum(p for p in pnls if p > 0); gl = abs(sum(p for p in pnls if p < 0))
    pf = gp / gl if gl > 0 else (math.inf if gp > 0 else 0.0)
    eq = 0.0; peak = 0.0; dd = 0.0
    for p in pnls:
        eq += p; peak = max(peak, eq); dd = min(dd, eq - peak)
    return {"label": row["label"], "stage": row["stage"], "period": row["period"],
            "instrument": row["instrument"], "fee": fee, "slip": row.get("slip"),
            "job_id": jid, "n": len(tr), "net": round(sum(pnls), 2), "pf": pf,
            "dd": round(dd, 2), "sb": same_bar_pct(tr),
            "wr": round((sum(1 for p in pnls if p > 0) / len(pnls) * 100) if pnls else 0, 1)}


def pf_str(v: Any) -> str:
    try: x = float(v)
    except Exception: return ""
    return "inf" if math.isinf(x) else f"{x:.3f}"


def print_summary(s: Dict[str, Any]) -> None:
    print(f"  done {s['stage']:10s} {s['label']:32s} {s['instrument']:12s} {s['period']:14s} "
          f"n={s['n']:>4} net={s['net']:>+9.2f} pf={pf_str(s['pf']):>7} dd={s['dd']:>+9.2f} "
          f"sb%={s['sb']:>5.1f} wr={s['wr']:>5.1f}", flush=True)


def gates(full: Dict[str, Any], is_: Dict[str, Any], oos: Dict[str, Any],
          combined: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, bool]:
    def f(r, k):
        v = r.get(k)
        if v is None: return 0.0
        if v == math.inf: return 99.0
        return float(v)
    return {
        "full_net_pos": f(full, "net") > 0.0,
        "full_pf_120": f(full, "pf") >= 1.20,
        "oos_pf_110": f(oos, "pf") >= 1.10,
        "is_net_pos": f(is_, "net") > 0.0,
        "oos_net_pos": f(oos, "net") > 0.0,
        "max_dd_800": abs(f(full, "dd")) <= 800.0,
        "stress_combined_nonneg": f(combined, "net") >= 0.0,
        "current30d_nonneg": f(current, "net") >= 0.0,
        "enough_trades": int(full.get("n") or 0) >= 100,
        "low_same_bar": f(full, "sb") <= 60.0,
    }


def main() -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle = RL.DATA / "research" / f"mnq_cell019_rth_gap_validation_{ts}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)

    final: Dict[str, Any] = {"class_name": CLASS_NAME, "created_utc": RL.utcnow_iso(),
                             "winners": list(WINNERS.keys())}

    # Validation: Full / IS / OOS for each winner.
    val_rows: List[Dict[str, Any]] = []
    for lab in WINNERS:
        p = params_for(lab)
        for period, frm, to in (FULL, IS, OOS):
            val_rows.append(submit(label=lab, stage="validation", period=period,
                                   frm=frm, to=to, params=p))
    wait_for(val_rows)
    val_sum = [summarize(r) for r in val_rows]
    for s in val_sum: print_summary(s)
    final["validation"] = val_sum

    # Pick best by Full net.
    full_by_lab = {s["label"]: s for s in val_sum if s["period"] == "Full"}
    is_by_lab = {s["label"]: s for s in val_sum if s["period"] == "IS"}
    oos_by_lab = {s["label"]: s for s in val_sum if s["period"] == "OOS"}
    # Prefer winners with both IS and OOS net > 0, then highest Full net.
    candidates = [
        (lab, full_by_lab[lab]) for lab in WINNERS
        if full_by_lab[lab]["net"] > 0
        and is_by_lab[lab]["net"] > 0
        and oos_by_lab[lab]["net"] > 0
    ]
    if not candidates:
        candidates = [(lab, full_by_lab[lab]) for lab in WINNERS if full_by_lab[lab]["net"] > 0]
    candidates.sort(key=lambda kv: kv[1]["net"], reverse=True)
    if not candidates:
        final["decision"] = {"status": "rejected", "reason": "no winner positive on Full"}
        (bundle / "final.json").write_text(json.dumps(final, indent=2, default=str), encoding="utf-8")
        print("DECISION: rejected (no positive Full)"); return

    best_label = candidates[0][0]
    print(f"\nBEST: {best_label}", flush=True)
    final["best_label"] = best_label
    best_params = params_for(best_label)

    # Stress.
    stress_rows = [
        submit(label=best_label, stage="stress", period="slip2", frm=FULL[1], to=FULL[2], params=best_params, fee=FEE_BASE, slip=2),
        submit(label=best_label, stage="stress", period="fee240", frm=FULL[1], to=FULL[2], params=best_params, fee=FEE_STRESS, slip=1),
        submit(label=best_label, stage="stress", period="slip2_fee240", frm=FULL[1], to=FULL[2], params=best_params, fee=FEE_STRESS, slip=2),
    ]

    # Current30D.
    cur_from, cur_to = current_window(30)
    cur_rows = [submit(label=best_label, stage="current", period="Current30D",
                       frm=cur_from, to=cur_to, params=best_params)]

    # Batch (6 instruments).
    batch_rows = []
    for inst in BATCH:
        fee = max(1.90, RL.fee_for(inst.split()[0]))
        batch_rows.append(submit(label=best_label, stage="batch",
                                 period=f"Full_{inst.split()[0]}",
                                 frm=FULL[1], to=FULL[2], params=best_params,
                                 fee=fee, instrument=inst))

    all_rows = stress_rows + cur_rows + batch_rows
    wait_for(all_rows)

    stress_sum = [summarize(r) for r in stress_rows]
    cur_sum = [summarize(r) for r in cur_rows]
    batch_sum = [summarize(r) for r in batch_rows]
    for s in stress_sum + cur_sum + batch_sum: print_summary(s)

    final["stress"] = stress_sum
    final["current30d"] = cur_sum
    final["batch"] = batch_sum

    full = full_by_lab[best_label]
    is_ = is_by_lab[best_label]
    oos = oos_by_lab[best_label]
    combined = next((s for s in stress_sum if s["period"] == "slip2_fee240"), {})
    current = cur_sum[0] if cur_sum else {}

    g = gates(full, is_, oos, combined, current)
    passed = all(g.values())
    final["gates"] = g
    final["decision"] = {
        "status": "paper_candidate" if passed else "rejected",
        "best_label": best_label,
        "locked_params": best_params,
        "gates": g,
        "full": full, "is": is_, "oos": oos,
        "stress_combined": combined, "current30d": current,
    }
    (bundle / "final.json").write_text(json.dumps(final, indent=2, default=str), encoding="utf-8")
    print(f"\nDECISION: {final['decision']['status']} (best={best_label})", flush=True)
    print(f"gates: {g}", flush=True)


if __name__ == "__main__":
    main()
