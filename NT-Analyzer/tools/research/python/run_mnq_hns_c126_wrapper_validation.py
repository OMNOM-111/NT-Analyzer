"""Validate CELL-126 deploy wrapper defaults after the final NinjaTrader restart.

The promoted profile was selected through NTAMnqResearchHub Mode=HeadAndShouldersLive.
This script verifies that the deploy class itself is visible in the runtime
catalog and that its SetDefaults reproduce the promotion gates.
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import research_lib as RL  # noqa: E402
import run_mnq_cell020_session_edge_ladder as base  # noqa: E402


CLASS_NAME = "NTAMnqHeadShouldersDivergenceC126"
CELL_ID = "CELL-126"
PROFILE_ID = "mnq_head_shoulders_divergence_1m_c126_paper_v1"
INSTRUMENT = "MNQ 06-26"
SESSION_TEMPLATE = "CME US Index Futures ETH"
BARS_PERIOD_VALUE = 1
BASE_TF_SECONDS = 60
FEE_BASE = 1.90
FEE_STRESS = 2.40

FULL = ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z")
IS = ("IS", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z")
OOS = ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def current_window(days: int = 30) -> Tuple[str, str]:
    return base.current_window(days)


def refresh_catalog_or_fail() -> None:
    code, refresh = RL.post("/api/catalog/refresh", {})
    if code != 200 or not refresh.get("ok"):
        raise RuntimeError(f"catalog refresh failed: code={code} body={refresh}")
    code, catalog = RL.get("/api/catalog")
    strategies = catalog.get("strategies") or []
    names = {s.get("class_name") or s.get("name") for s in strategies if isinstance(s, dict)}
    if CLASS_NAME not in names:
        raise RuntimeError(
            f"{CLASS_NAME} is not visible in catalog after refresh. "
            "Restart NinjaTrader once, then rerun this script."
        )


def build_body(*, from_utc: str, to_utc: str, params: Dict[str, Any],
               slip: int) -> Dict[str, Any]:
    return {
        "class_name": CLASS_NAME,
        "instrument": INSTRUMENT,
        "bars_period_type": "Minute",
        "bars_period_value": BARS_PERIOD_VALUE,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "parameters": dict(params),
        "calculate": "OnBarClose",
        "is_tick_replay": False,
        "order_fill_resolution": "High",
        "slippage_ticks": slip,
        "commission": 0.0,
        "commission_template": "None",
        "session_template": SESSION_TEMPLATE,
        "timezone": "UTC",
        "role": "smoke",
        "risk_profile": RL.build_risk_profile_for([INSTRUMENT]),
    }


def submit_job(*, bundle: Path, label: str, period_label: str, from_utc: str,
               to_utc: str, fee: float, slip: int,
               params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    merged = dict(params or {})
    merged.setdefault("RoundTurnCommission", fee)
    body = build_body(from_utc=from_utc, to_utc=to_utc, params=merged, slip=slip)
    code, resp = RL.post("/api/jobs", body)
    job_id = resp.get("job_id") if code == 201 and isinstance(resp, dict) else None
    row = {
        "stage": "Wrapper",
        "label": label,
        "fam": "hns",
        "win": "c126",
        "period_label": period_label,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "fee": fee,
        "slip": slip,
        "code": code,
        "job_id": job_id,
        "response": resp,
        "params": dict(params or {}),
    }
    print(
        f"submit wrapper {label:28s} {period_label:16s} "
        f"params={row['params']} code={code} job={job_id or resp}",
        flush=True,
    )
    (bundle / "latest_submitted.json").write_text(
        json.dumps(row, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return row


def job_state(job_id: str) -> Optional[str]:
    return base.job_state(job_id)


def wait_for_jobs(rows: Iterable[Dict[str, Any]], timeout_s: int = 21600) -> None:
    remaining = {str(r["job_id"]) for r in rows if r.get("job_id")}
    deadline = time.time() + timeout_s
    last_print = 0.0
    while remaining:
        if time.time() > deadline:
            raise TimeoutError(f"timeout waiting for jobs: {sorted(remaining)}")
        for job_id in list(remaining):
            if job_state(job_id) in {"done", "failed", "cancelled"}:
                remaining.remove(job_id)
        now = time.time()
        if now - last_print >= 30 and remaining:
            print(f"waiting: {len(remaining)} C126 wrapper jobs still pending/running", flush=True)
            last_print = now
        time.sleep(3)


def collect_rows(bundle: Path, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    wait_for_jobs(rows)
    original_tf = base.BASE_TF_SECONDS
    base.BASE_TF_SECONDS = BASE_TF_SECONDS
    try:
        out: List[Dict[str, Any]] = []
        for row in rows:
            job_id = str(row.get("job_id") or "")
            report = RL.read_job_report(job_id) if job_id else None
            summary = base.summarize(row, report)
            out.append(summary)
            pf = summary.get("adj_pf")
            pf_s = "inf" if pf == math.inf else f"{float(pf or 0.0):.3f}"
            print(
                f"done   {row['label']:28s} {row['period_label']:16s} "
                f"trades={int(summary.get('trade_count') or 0):>4} "
                f"net={float(summary.get('adj_net') or 0.0):>9.2f} "
                f"pf={pf_s:>7s} dd={float(summary.get('max_drawdown') or 0.0):>9.2f} "
                f"sb%={float(summary.get('same_bar_pct') or 0.0):>5.1f}",
                flush=True,
            )
            (bundle / "validation_rows.json").write_text(
                json.dumps(out, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        return out
    finally:
        base.BASE_TF_SECONDS = original_tf


def by_period(rows: List[Dict[str, Any]], period_label: str) -> Dict[str, Any]:
    for row in rows:
        if row.get("period_label") == period_label:
            return row
    return {}


def main() -> int:
    refresh_catalog_or_fail()
    bundle = RL.PROJECT_ROOT / "data" / "research" / f"mnq_hns_c126_wrapper_validation_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)

    current_from, current_to = current_window(30)
    plan = [
        ("c126_defaults", FULL[0], FULL[1], FULL[2], FEE_BASE, 1, {}),
        ("c126_defaults", IS[0], IS[1], IS[2], FEE_BASE, 1, {}),
        ("c126_defaults", OOS[0], OOS[1], OOS[2], FEE_BASE, 1, {}),
        ("c126_stress_slip2", "StressSlip2", FULL[1], FULL[2], FEE_BASE, 2, {"SlippageTicks": 2}),
        ("c126_stress_fee240", "StressFee240", FULL[1], FULL[2], FEE_STRESS, 1, {"RoundTurnCommission": FEE_STRESS}),
        (
            "c126_stress_slip2_fee240",
            "StressSlip2Fee240",
            FULL[1],
            FULL[2],
            FEE_STRESS,
            2,
            {"RoundTurnCommission": FEE_STRESS, "SlippageTicks": 2},
        ),
        ("c126_defaults", "Current30D", current_from, current_to, FEE_BASE, 1, {}),
    ]

    print(f"bundle: {bundle}", flush=True)
    submissions = [
        submit_job(
            bundle=bundle,
            label=label,
            period_label=period,
            from_utc=frm,
            to_utc=to,
            fee=fee,
            slip=slip,
            params=params,
        )
        for label, period, frm, to, fee, slip, params in plan
    ]
    (bundle / "validation_submissions.json").write_text(
        json.dumps(submissions, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    rows = collect_rows(bundle, submissions)
    full = by_period(rows, "Full")
    is_ = by_period(rows, "IS")
    oos = by_period(rows, "OOS")
    stress_combined = by_period(rows, "StressSlip2Fee240")
    current = by_period(rows, "Current30D")
    gate_values = base.gates(full, is_, oos, stress_combined, current)
    failed = [key for key, value in gate_values.items() if not value]

    decision = {
        "cell_id": CELL_ID,
        "profile_id": PROFILE_ID,
        "class_name": CLASS_NAME,
        "instrument": INSTRUMENT,
        "timeframe": "1 Minute",
        "decision": "paper_ready" if not failed else "blocked",
        "ready_pass": not failed,
        "failed_gates": failed,
        "gates": gate_values,
        "rows_by_period": {
            row.get("period_label"): row
            for row in rows
        },
    }
    (bundle / "decision.json").write_text(
        json.dumps(decision, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    summary = {
        "bundle": str(bundle),
        "ready_pass": not failed,
        "failed_gates": failed,
        "full": full,
        "is": is_,
        "oos": oos,
        "stress_combined": stress_combined,
        "current30d": current,
    }
    (bundle / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
