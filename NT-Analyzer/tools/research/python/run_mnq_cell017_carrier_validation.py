"""Full validation for MNQ CELL-017 locked carrier params (TradeStartTime=1246)."""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402

CLASS_NAME = "NTAMicroMnqScalpPilot"
ROOT = "MNQ"
INSTRUMENT = "MNQ 06-26"
ROLE = "smoke"

LOCKED: Dict[str, Any] = {
    "StartingCapital": 2000.0,
    "IntradayOnly": True,
    "ActiveMarginPerContract": 100.0,
    "MaxContractsByCapital": 20,
    "InstrumentStatus": "allowed",
    "MarginSourceBroker": "NinjaTrader",
    "RiskPerTradePct": 0.35,
    "MaxDailyLossPct": 3.0,
    "MaxDailyLossUsd": 60.0,
    "MaxWeeklyLossUsd": 150.0,
    "MaxDailyProfitPct": 0.0,
    "MaxTradesPerDay": 12,
    "HardMaxTradesPerDay": 16,
    "MaxConsecutiveLosses": 3,
    "PauseAfterConsecutiveLosses": 2,
    "PauseMinutesAfterLosses": 15,
    "UserMaxContracts": 1,
    "MaxOpenPositions": 1,
    "RoundTurnCommission": 1.9,
    "SlippageTicks": 1,
    "UseSetupModeFilter": True,
    "SetupMode": "VwapPullbackScalp",
    "EnableLong": True,
    "EnableShort": False,
    "EnableVwapReclaim": True,
    "EnableEmaMomentum": False,
    "EnableMicroOrb": False,
    "EnableFailedBreakout": False,
    "EmaFastPeriod": 9,
    "EmaMidPeriod": 21,
    "EmaSlowPeriod": 50,
    "AtrPeriod": 14,
    "AdxPeriod": 14,
    "MinAdx": 0.0,
    "VolumeSmaPeriod": 20,
    "MinVolumeFactor": 0.7,
    "PullbackLookback": 4,
    "RequireSlowTrend": False,
    "AtrStopMult": 0.3,
    "MinStopTicks": 4,
    "MaxStopTicks": 10,
    "RewardRiskRatio": 2.0,
    "MoveToBreakevenAtR": 0.7,
    "TrailAfterR": 1.0,
    "UseTimeStop": True,
    "TimeStopBars": 3,
    "MinProgressR": 0.3,
    "EntryTimeoutBars": 2,
    "EntryOffsetTicks": 0,
    "TradeStartTime": 1246,
    "TradeEndTime": 1300,
    "UseSecondTradeWindow": False,
    "SecondTradeStartTime": 1030,
    "SecondTradeEndTime": 1200,
    "ForceFlatTime": 1305,
    "NewsBlackoutTimes": "",
    "NewsBlackoutWindowMin": 5,
    "OrbStartTime": 630,
    "OrbDurationMinutes": 3,
    "OrbBreakoutBuffer": 1,
    "OrbRetestBars": 5,
    "OrbFailedLookback": 3,
    "EmaImpulseLookback": 3,
}

FROM_FULL = "2024-01-01T00:00:00Z"
TO_FULL = "2025-12-31T23:59:59Z"
FROM_IS = "2024-01-01T00:00:00Z"
TO_IS = "2024-12-31T23:59:59Z"
FROM_OOS = "2025-01-01T00:00:00Z"
TO_OOS = "2025-12-31T23:59:59Z"

CSV_FIELDS = [
    "stage", "job_id", "status", "trade_count", "adj_net", "adj_pf", "adj_dd",
    "slippage_ticks", "round_turn_commission", "trade_start",
]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def job_state(job_id: str) -> Optional[str]:
    jobs = RL.jobs_root()
    for subdir in ("done", "failed", "cancelled", "running", "pending"):
        if (jobs / subdir / job_id).is_dir():
            return subdir
    return None


def wait_for_jobs(job_ids: Iterable[str], timeout_s: int = 10800) -> None:
    remaining = set(job_ids)
    deadline = time.time() + timeout_s
    while remaining:
        if time.time() > deadline:
            raise TimeoutError(f"timeout: {sorted(remaining)}")
        for job_id in list(remaining):
            if job_state(job_id) in {"done", "failed", "cancelled"}:
                remaining.remove(job_id)
        if remaining:
            time.sleep(4)


def current_window(days: int = 30) -> Tuple[str, str]:
    front = RL.resolve_front_contract(ROOT)
    end_raw = str(front.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    end_day = datetime.fromisoformat(end_raw[:10]).date()
    start_day = end_day - timedelta(days=days)
    return f"{start_day.isoformat()}T00:00:00Z", f"{end_day.isoformat()}T23:59:59Z"


def metrics(job_id: str, fee: float) -> Dict[str, Any]:
    report = RL.read_job_report(job_id) or {}
    trades = (report.get("result") or {}).get("trades") or []
    pnls = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        qty = max(1.0, abs(float(trade.get("quantity") or 1.0)))
        pnls.append(float(trade.get("pnl_currency") or 0.0) - fee * qty)
    gp = sum(p for p in pnls if p > 0)
    gl = sum(p for p in pnls if p < 0)
    net = sum(pnls)
    pf = gp / abs(gl) if gl < 0 else (999.0 if gp > 0 else 0.0)
    eq = peak = dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return {
        "trade_count": len(pnls),
        "adj_net": round(net, 2),
        "adj_pf": round(pf, 4),
        "adj_dd": round(dd, 2),
    }


def submit(stage: str, from_utc: str, to_utc: str, slip: int, overrides: Dict[str, Any]) -> str:
    params = dict(LOCKED)
    params.update(overrides)
    body = RL.build_job_body(
        class_name=CLASS_NAME,
        instrument=INSTRUMENT,
        params=params,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=1,
        slippage_ticks=slip,
        role=ROLE,
        session_template=RL.session_for(ROOT),
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = str(resp.get("job_id") or "")
    print(f"submitted {stage}: {job_id} code={code}")
    if code not in (200, 201, 202) or not job_id:
        raise RuntimeError(resp)
    return job_id


def gates(rows: Dict[str, Dict[str, Any]]) -> Dict[str, bool]:
    full = rows["full"]
    return {
        "full_net_positive": full["adj_net"] > 0,
        "full_pf_ge_1_35": full["adj_pf"] >= 1.35,
        "full_trades_ge_30": full["trade_count"] >= 30,
        "max_dd_pct_15": RL.max_drawdown_within_budget(full["adj_dd"]),
        "is_net_positive": rows["is_2024"]["adj_net"] > 0,
        "oos_net_positive": rows["oos_2025"]["adj_net"] > 0,
        "oos_pf_ge_1_25": rows["oos_2025"]["adj_pf"] >= 1.25,
        "stress_slip2_positive": rows["stress_slip2"]["adj_net"] > 0,
        "stress_fee240_positive": rows["stress_fee240"]["adj_net"] > 0,
        "stress_combined_positive": rows["stress_slip2_fee240"]["adj_net"] > 0,
        "current30_nonnegative": rows["current30d"]["adj_net"] >= 0,
    }


def main() -> int:
    bundle = RL.PROJECT_ROOT / "data" / "research" / f"mnq_cell017_carrier_validation_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    cur_from, cur_to = current_window()
    plan = [
        ("full", FROM_FULL, TO_FULL, 1, {}),
        ("is_2024", FROM_IS, TO_IS, 1, {}),
        ("oos_2025", FROM_OOS, TO_OOS, 1, {}),
        ("stress_slip2", FROM_FULL, TO_FULL, 2, {"SlippageTicks": 2}),
        ("stress_fee240", FROM_FULL, TO_FULL, 1, {"RoundTurnCommission": 2.40}),
        ("stress_slip2_fee240", FROM_FULL, TO_FULL, 2, {"SlippageTicks": 2, "RoundTurnCommission": 2.40}),
        ("current30d", cur_from, cur_to, 1, {}),
    ]
    jobs = {stage: submit(stage, f, t, slip, ov) for stage, f, t, slip, ov in plan}
    wait_for_jobs(jobs.values())
    rows: Dict[str, Dict[str, Any]] = {}
    for stage, job_id in jobs.items():
        fee = 2.40 if "fee240" in stage else 1.9
        row = {"stage": stage, "job_id": job_id, "status": job_state(job_id)}
        row.update(metrics(job_id, fee))
        row["trade_start"] = 1246
        rows[stage] = row
    g = gates(rows)
    decision = {"trade_start": 1246, "passed": all(g.values()), "gates": g, "rows": rows}
    (bundle / "decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
    with (bundle / "rows.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=CSV_FIELDS)
        w.writeheader()
        for row in rows.values():
            w.writerow({k: row.get(k) for k in CSV_FIELDS})
    print(json.dumps(decision, indent=2))
    print(f"bundle={bundle}")
    return 0 if decision["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
