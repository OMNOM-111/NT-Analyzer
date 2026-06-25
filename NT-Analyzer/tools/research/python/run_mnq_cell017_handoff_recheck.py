"""Compare MNQ CELL-017 carrier windows: overlap 12:45 vs clean handoff 12:46."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402

CLASS_NAME = "NTAMicroMnqScalpPilot"
INSTRUMENT = "MNQ 06-26"
FROM_FULL = "2024-01-01T00:00:00Z"
TO_FULL = "2025-12-31T23:59:59Z"

BASE_PARAMS: Dict[str, Any] = {
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


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def job_state(job_id: str) -> Optional[str]:
    jobs = RL.jobs_root()
    for subdir in ("done", "failed", "cancelled", "running", "pending"):
        if (jobs / subdir / job_id).is_dir():
            return subdir
    return None


def wait_for_jobs(job_ids: Iterable[str], timeout_s: int = 7200) -> None:
    remaining = set(job_ids)
    deadline = time.time() + timeout_s
    while remaining:
        if time.time() > deadline:
            raise TimeoutError(f"timeout: {sorted(remaining)}")
        for job_id in list(remaining):
            state = job_state(job_id)
            if state in {"done", "failed", "cancelled"}:
                remaining.remove(job_id)
        if remaining:
            time.sleep(4)


def adj_row(job_id: str) -> Dict[str, Any]:
    report = RL.read_job_report(job_id) or {}
    result = report.get("result") or {}
    trades = result.get("trades") or []
    fee = 1.9
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
    params = ((result.get("context") or {}).get("strategy") or {}).get("final_parameters") or {}
    return {
        "job_id": job_id,
        "trade_start": params.get("TradeStartTime"),
        "trade_count": len(pnls),
        "adj_net": round(net, 2),
        "adj_pf": round(pf, 4),
        "adj_dd": round(dd, 2),
        "status": job_state(job_id),
    }


def submit_window(label: str, start: int) -> str:
    params = dict(BASE_PARAMS)
    params["TradeStartTime"] = start
    body = RL.build_job_body(
        class_name=CLASS_NAME,
        instrument=INSTRUMENT,
        params=params,
        from_utc=FROM_FULL,
        to_utc=TO_FULL,
        bars_period_type="Minute",
        bars_period_value=1,
        slippage_ticks=1,
        role="smoke",
        session_template=RL.session_for("MNQ"),
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = str(resp.get("job_id") or "")
    print(f"submitted {label} start={start}: code={code} job={job_id}")
    if code not in (200, 201, 202) or not job_id:
        raise RuntimeError(f"submit failed {label}: {resp}")
    return job_id


def main() -> int:
    bundle = RL.PROJECT_ROOT / "data" / "research" / f"mnq_cell017_handoff_recheck_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)

    jobs = {
        "overlap_1245": submit_window("overlap_1245", 1245),
        "clean_1246": submit_window("clean_1246", 1246),
    }
    wait_for_jobs(jobs.values())

    rows = {label: adj_row(job_id) for label, job_id in jobs.items()}
    better = "clean_1246" if rows["clean_1246"]["adj_net"] >= rows["overlap_1245"]["adj_net"] else "overlap_1245"
    summary = {"rows": rows, "recommended": better}
    (bundle / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"bundle={bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
