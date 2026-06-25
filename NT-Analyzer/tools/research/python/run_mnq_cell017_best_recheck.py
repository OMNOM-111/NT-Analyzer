"""Recheck the best CELL-017 free-window candidate.

This runner exists to verify the suspicious trade-count collapse observed in
the combined stress job for `all_both_1246_1325_s4_10_rr40_v07`.
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
import run_mnq_cell017_free_window_sweep as FREE  # noqa: E402


VARIANT_NAME = "all_both_1246_1325_s4_10_rr40_v07"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def select_variant() -> FREE.BASE.Variant:
    for variant in FREE.build_variants():
        if variant.name == VARIANT_NAME:
            return variant
    raise RuntimeError(f"variant not found: {VARIANT_NAME}")


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FREE.CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    bundle = RL.PROJECT_ROOT / "data" / "research" / f"mnq_cell017_best_recheck_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    variant = select_variant()

    plan = [
        ("Full", FREE.BASE.FULL[1], FREE.BASE.FULL[2], 1, RL.fee_for(FREE.BASE.ROOT)),
        ("StressSlip2Fee240", FREE.BASE.FULL[1], FREE.BASE.FULL[2], 2, 2.40),
        ("StressSlip2Fee240Repeat", FREE.BASE.FULL[1], FREE.BASE.FULL[2], 2, 2.40),
    ]
    print(f"bundle: {bundle}", flush=True)
    print(f"variant: {variant.name}", flush=True)
    submissions = [
        FREE.BASE.submit_job(variant, stage, from_utc, to_utc, slip, fee)
        for stage, from_utc, to_utc, slip, fee in plan
    ]
    (bundle / "submissions.json").write_text(json.dumps(submissions, indent=2), encoding="utf-8")
    FREE.BASE.wait_for_jobs([s.get("job_id") for s in submissions if s.get("job_id")])

    rows = [FREE.row_from_submission(s) for s in submissions]
    write_csv(bundle / "rows.csv", rows)
    (bundle / "rows.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    summary = {
        "bundle": str(bundle),
        "variant": variant.name,
        "rows": {r["stage"]: r for r in rows},
        "diagnosis": (
            "If repeated combined stress again has far fewer trades than Full, "
            "the collapse is reproducible and should be treated as risk-budget "
            "exhaustion under higher costs, not as a promotion pass."
        ),
    }
    (bundle / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
