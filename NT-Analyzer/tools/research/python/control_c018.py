"""Control test: run a known-good strategy (C018) through the same bridge for
the same period, using its own SetDefaults (empty param overrides). If this
also returns 0 trades, the bridge/data is the problem, not CELL-019."""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402

CLASS = sys.argv[1] if len(sys.argv) > 1 else "NTAMnqDailyOpenScalpC018"
INSTRUMENT = "MNQ 06-26"
SESSION = "CME US Index Futures ETH"


def main() -> None:
    body = RL.build_job_body(
        class_name=CLASS,
        instrument=INSTRUMENT,
        params={},  # use strategy SetDefaults
        from_utc="2025-11-01T00:00:00Z",
        to_utc="2025-11-30T23:59:59Z",
        bars_period_type="Minute",
        bars_period_value=5,
        slippage_ticks=1,
        role="smoke",
        session_template=SESSION,
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = resp.get("job_id") if isinstance(resp, dict) else None
    print(f"submit control class={CLASS} code={code} job={job_id}", flush=True)
    if not job_id:
        print(f"resp={resp}")
        return
    base = RL.jobs_root()
    for _ in range(400):
        if (base / "done" / job_id).is_dir() or (base / "failed" / job_id).is_dir():
            break
        time.sleep(3)
    report = RL.read_job_report(job_id)
    metrics = (report.get("result") or {}).get("metrics") if report else None
    trades = (report.get("trades") if report else None) or []
    print(f"CONTROL trades={len(trades)} metrics={metrics}", flush=True)


if __name__ == "__main__":
    main()
