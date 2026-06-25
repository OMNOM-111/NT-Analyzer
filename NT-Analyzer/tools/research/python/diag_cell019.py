"""One-off diagnostic for CELL-019: widen window, disable filters, loosen
compression -> if this still yields zero trades, the entry engine has a hard
bug; if it trades, the smoke gates were simply too strict."""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402
import run_mnq_cell019_precash_compression_breakout as R  # noqa: E402


def main() -> None:
    p = R.base_params()
    # Wide-open window (all session), no filters, loose compression, no vol gate.
    p.update({
        "TradeStartTime": 0,
        "TradeEndTime": 2359,
        "ForceFlatTime": 2358,
        "UseSecondTradeWindow": False,
        "ConfirmMode": "ReclaimOrContinuation",
        "RequireVwapAgreement": False,
        "RequireEmaAgreement": False,
        "RequireEmaSlope": False,
        "MinVolumeFactor": 0.01,
        "VolExpansionFactor": 0.01,
        "MinCompressionRangeTicks": 2,
        "MaxCompressionRangeTicks": 200,
        "CompressionAtrMult": 10.0,
        "BreakoutBufferTicks": 1,
        "MinBarRangeTicks": 1,
        "MaxTradesPerDay": 50,
        "HardMaxTradesPerDay": 80,
        "MaxDailyLossUsd": 100000.0,
        "MaxWeeklyLossUsd": 100000.0,
        "MaxConsecutiveLosses": 20,
    })
    body = RL.build_job_body(
        class_name=R.CLASS_NAME,
        instrument=R.INSTRUMENT,
        params=p,
        from_utc="2025-11-01T00:00:00Z",
        to_utc="2025-11-30T23:59:59Z",
        bars_period_type="Minute",
        bars_period_value=R.BARS_PERIOD_VALUE,
        slippage_ticks=1,
        role="smoke",
        session_template=R.SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([R.INSTRUMENT]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = resp.get("job_id") if isinstance(resp, dict) else None
    print(f"submit diag code={code} job={job_id}", flush=True)
    if not job_id:
        print(f"resp={resp}")
        return
    base = RL.jobs_root()
    for _ in range(400):
        done = (base / "done" / job_id).is_dir()
        failed = (base / "failed" / job_id).is_dir()
        if done or failed:
            break
        time.sleep(3)
    report = RL.read_job_report(job_id)
    trades = R.trades_from(report) if report else []
    metrics = (report.get("result") or {}).get("metrics") if report else None
    print(f"DIAG trades={len(trades)} metrics={metrics}", flush=True)


if __name__ == "__main__":
    main()
