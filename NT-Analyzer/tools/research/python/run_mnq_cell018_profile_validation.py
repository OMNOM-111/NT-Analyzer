"""Validate the deployed MNQ CELL-018 profile only.

CELL-018 intentionally uses the already compiled NTAMicroMnqScalpPilot carrier
with locked profile parameters from the 2h daily-open search. This runner
replays the promotion backtest/stress plan for that exact profile without
launching the full parameter search again.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402
import run_mnq_2h_daily_search as DAILY  # noqa: E402


CELL_ID = "CELL-018"
PROFILE_ID = "mnq_daily_open_allmodules_2h_1m_c018_ready_v1"
VARIANT_NAME = "all_both_0635_0835_s4_10_rr40_v07"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def select_variant() -> DAILY.Variant:
    for variant in DAILY.build_variants():
        if variant.name == VARIANT_NAME:
            return variant
    raise RuntimeError(f"variant not found: {VARIANT_NAME}")


def main() -> int:
    bundle = RL.PROJECT_ROOT / "data" / "research" / f"mnq_cell018_profile_validation_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)

    variant = select_variant()
    current_from, current_to = DAILY.current_window(30)
    plan = [
        ("Full", DAILY.FULL[1], DAILY.FULL[2], 1, RL.fee_for(DAILY.ROOT)),
        ("IS", DAILY.IS[1], DAILY.IS[2], 1, RL.fee_for(DAILY.ROOT)),
        ("OOS", DAILY.OOS[1], DAILY.OOS[2], 1, RL.fee_for(DAILY.ROOT)),
        ("StressSlip2", DAILY.FULL[1], DAILY.FULL[2], 2, RL.fee_for(DAILY.ROOT)),
        ("StressFee240", DAILY.FULL[1], DAILY.FULL[2], 1, 2.40),
        ("StressSlip2Fee240", DAILY.FULL[1], DAILY.FULL[2], 2, 2.40),
        ("Current30D", current_from, current_to, 1, RL.fee_for(DAILY.ROOT)),
    ]

    print(f"bundle: {bundle}", flush=True)
    print(f"profile: {PROFILE_ID} variant={variant.name}", flush=True)
    submissions: List[Dict[str, Any]] = [
        DAILY.submit_job(variant, stage, from_utc, to_utc, slip, fee)
        for stage, from_utc, to_utc, slip, fee in plan
    ]
    (bundle / "validation_submissions.json").write_text(
        json.dumps(submissions, indent=2),
        encoding="utf-8",
    )

    DAILY.wait_for_jobs([s.get("job_id") for s in submissions if s.get("job_id")])
    rows = [DAILY.row_from_submission(s) for s in submissions]
    rows_by_stage = {r["stage"]: r for r in rows}
    gate_values = DAILY.gates(rows_by_stage)
    failed = [key for key, value in gate_values.items() if not value]

    with (bundle / "validation_rows.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DAILY.CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (bundle / "validation_rows.json").write_text(
        json.dumps(rows, indent=2),
        encoding="utf-8",
    )

    decision = {
        "cell_id": CELL_ID,
        "profile_id": PROFILE_ID,
        "class_name": DAILY.CLASS_NAME,
        "instrument": DAILY.INSTRUMENT,
        "variant": variant.name,
        "decision": "paper_ready" if not failed else "research_only",
        "ready_pass": not failed,
        "failed_gates": failed,
        "gates": gate_values,
        "locked_parameters": variant.params,
        "rows": rows_by_stage,
    }
    (bundle / "decision.json").write_text(
        json.dumps(decision, indent=2),
        encoding="utf-8",
    )
    summary = {
        "bundle": str(bundle),
        "cell_id": CELL_ID,
        "profile_id": PROFILE_ID,
        "class_name": DAILY.CLASS_NAME,
        "instrument": DAILY.INSTRUMENT,
        "ready_pass": not failed,
        "failed_gates": failed,
        "rows": rows_by_stage,
    }
    (bundle / "summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2), flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
