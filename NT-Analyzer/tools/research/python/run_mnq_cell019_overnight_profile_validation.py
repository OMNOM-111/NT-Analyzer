"""Validate one focused MNQ CELL-019 overnight candidate.

The candidate is the existing high-frequency MNQ scalp carrier shifted into the
free early-morning planner gap:

    CELL-019, 03:00-05:55 PT, force-flat 05:59 PT.

This is deliberately before the current MGC 06:00 PT and MNQ 06:35 PT starts.
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
import run_mnq_cell019_overnight_session as OVERNIGHT  # noqa: E402


CELL_ID = "CELL-019"
PROFILE_ID = "mnq_overnight_allmodules_1m_c019_candidate_v1"
VARIANT_NAME = "all_both_0300_0555_s4_10_rr40_v07"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def select_variant() -> OVERNIGHT.EVENING.Variant:
    for variant in OVERNIGHT.build_variants():
        if variant.name == VARIANT_NAME:
            return variant
    raise RuntimeError(f"variant not found: {VARIANT_NAME}")


def main() -> int:
    bundle = RL.PROJECT_ROOT / "data" / "research" / f"mnq_cell019_overnight_profile_validation_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)

    variant = select_variant()
    current_from, current_to = OVERNIGHT.EVENING.current_window(30)
    plan = [
        ("Full", OVERNIGHT.EVENING.FULL[1], OVERNIGHT.EVENING.FULL[2], 1, RL.fee_for(OVERNIGHT.EVENING.ROOT)),
        ("IS", OVERNIGHT.EVENING.IS[1], OVERNIGHT.EVENING.IS[2], 1, RL.fee_for(OVERNIGHT.EVENING.ROOT)),
        ("OOS", OVERNIGHT.EVENING.OOS[1], OVERNIGHT.EVENING.OOS[2], 1, RL.fee_for(OVERNIGHT.EVENING.ROOT)),
        ("StressSlip2", OVERNIGHT.EVENING.FULL[1], OVERNIGHT.EVENING.FULL[2], 2, RL.fee_for(OVERNIGHT.EVENING.ROOT)),
        ("StressFee240", OVERNIGHT.EVENING.FULL[1], OVERNIGHT.EVENING.FULL[2], 1, 2.40),
        ("StressSlip2Fee240", OVERNIGHT.EVENING.FULL[1], OVERNIGHT.EVENING.FULL[2], 2, 2.40),
        ("Current30D", current_from, current_to, 1, RL.fee_for(OVERNIGHT.EVENING.ROOT)),
    ]

    print(f"bundle: {bundle}", flush=True)
    print(f"profile: {PROFILE_ID} variant={variant.name}", flush=True)
    submissions: List[Dict[str, Any]] = [
        OVERNIGHT.EVENING.submit_job(variant, stage, from_utc, to_utc, slip, fee)
        for stage, from_utc, to_utc, slip, fee in plan
    ]
    (bundle / "validation_submissions.json").write_text(
        json.dumps(submissions, indent=2),
        encoding="utf-8",
    )

    OVERNIGHT.EVENING.wait_for_jobs([s.get("job_id") for s in submissions if s.get("job_id")])
    rows = [OVERNIGHT.EVENING.row_from_submission(s) for s in submissions]
    rows_by_stage = {r["stage"]: r for r in rows}
    gate_values = OVERNIGHT.EVENING.gates(rows_by_stage)
    failed = [key for key, value in gate_values.items() if not value]

    with (bundle / "validation_rows.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OVERNIGHT.EVENING.CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (bundle / "validation_rows.json").write_text(
        json.dumps(rows, indent=2),
        encoding="utf-8",
    )

    decision = {
        "cell_id": CELL_ID,
        "profile_id": PROFILE_ID,
        "display_name": OVERNIGHT.EVENING.DISPLAY_NAME,
        "class_name": OVERNIGHT.EVENING.CLASS_NAME,
        "instrument": OVERNIGHT.EVENING.INSTRUMENT,
        "session_template": OVERNIGHT.EVENING.SESSION_TEMPLATE,
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
        "display_name": OVERNIGHT.EVENING.DISPLAY_NAME,
        "class_name": OVERNIGHT.EVENING.CLASS_NAME,
        "instrument": OVERNIGHT.EVENING.INSTRUMENT,
        "session_template": OVERNIGHT.EVENING.SESSION_TEMPLATE,
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
