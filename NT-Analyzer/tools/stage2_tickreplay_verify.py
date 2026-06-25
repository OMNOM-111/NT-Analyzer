"""Stage 2 tick-replay verification harness.

Closes the MNQ same-bar / High-fill optimism question by re-running each paused
strategy through NinjaTrader Tick Replay. The ONLY changed variable versus the
existing honest High-fill rerun is ``execution.is_tick_replay`` false -> true:

  * Calculate stays OnBarClose  -> signal generation is unchanged.
  * OrderFillResolution stays High, slippage/commission unchanged.
  * IsTickReplay=true makes NinjaTrader resolve intrabar fills from real
    historical ticks instead of OHLC path assumptions, so a stop and a distant
    target can no longer both fill inside the same bar.

If the backtest edge collapses under tick replay, the same-bar optimism is
proven and the strategy is final_reject with evidence. If it survives, the
strategy keeps its edge under honest fills.

Submits by cloning the representative done job, flipping the flag, and staging
into the live bridge queue (pending/.staging -> pending, atomic rename). The
running NinjaTrader picks it up automatically.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import jobqueue as jq  # noqa: E402
from app import ops  # noqa: E402

# Representative High-fill rerun job per cell (slip 2, RT commission 1.90).
REP_JOBS: Dict[str, str] = {
    "CELL-001": "s2b_c001_s2_f190_20260616T221155434Z",
    "CELL-002": "s2b_c002_s2_f190_20260616T221156927Z",
    "CELL-003": "s2b_c003_s2_f190_20260616T221158468Z",
    "CELL-004": "s2b_c004_s2_f190_20260616T221200025Z",
    "CELL-005": "s2b_c005_s2_f190_20260616T221201561Z",
    # C015 MUST use the contract-aligned s2c_ job (s2_c015 has the 06-26 bug).
    "CELL-015": "s2c_c015_s2_f190_20260616T221433340Z",
    "CELL-016": "s2_c016_s2_f190_20260616T220932373Z",
    "CELL-017": "s2_c017_s2_f190_20260616T220934001Z",
    "CELL-018": "s2_c018_s2_f190_20260616T220935519Z",
}


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _find_done_job(job_id: str) -> Optional[Path]:
    loc = jq.find_job_dir(job_id)
    if loc:
        return loc[1]
    return None


def _resolve_rep_job(cell_id: str) -> Optional[Path]:
    """Find the representative High-fill done job for a cell. Prefer the pinned
    (contract-aligned) id; only fall back to a prefix scan if it is missing."""
    pinned = REP_JOBS.get(cell_id)
    if pinned:
        d = _find_done_job(pinned)
        if d:
            return d
    digits = cell_id.split("-")[-1]
    done = jq.jobs_dir() / "done"
    # Prefer the contract-aligned s2c_ variant, then any s2*_f190 High-fill job.
    for pattern in (f"s2c_c{digits}_s2_f190*", f"*c{digits}_s2_f190*"):
        for jd in sorted(done.glob(pattern)):
            if (jd / "job.json").exists():
                return jd
    return None


def submit_tickreplay(cell_id: str) -> Optional[str]:
    rep = _resolve_rep_job(cell_id)
    if rep is None:
        print(f"  [{cell_id}] no representative High-fill job found; skipping")
        return None
    job = json.loads((rep / "job.json").read_text(encoding="utf-8"))
    new_id = f"s2tr_{cell_id.replace('CELL-', 'c').lower()}_tr_{_utc_stamp()}"
    job["job_id"] = new_id
    job["created_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    execu = job.setdefault("execution", {})
    execu["is_tick_replay"] = True            # the ONLY changed variable
    execu["role"] = "smoke"                    # diagnostic, bypass research gate
    origin = job.setdefault("origin", {})
    origin.update({
        "stage2_tickreplay_verification": True,
        "cloned_from": rep.name,
        "isolated_variable": "is_tick_replay false->true",
        "purpose": "verify MNQ same-bar/High-fill optimism with real intrabar ticks",
    })

    jobs_dir = jq.jobs_dir()
    staging = jobs_dir / "pending" / ".staging" / new_id
    pending = jobs_dir / "pending" / new_id
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    staging.rename(pending)   # atomic publish; watcher now sees a complete dir
    print(f"  [{cell_id}] queued {new_id} (tick replay, cloned {rep.name})")
    return new_id


def _job_state_and_dir(job_id: str) -> Tuple[str, Optional[Path]]:
    loc = jq.find_job_dir(job_id)
    if not loc:
        return "missing", None
    return loc[0], loc[1]


def poll(job_ids: List[str], timeout_s: int = 2400, interval_s: int = 15) -> Dict[str, Dict[str, Any]]:
    """Block until every job reaches a terminal state or timeout."""
    deadline = time.time() + timeout_s
    results: Dict[str, Dict[str, Any]] = {}
    pending = set(job_ids)
    while pending and time.time() < deadline:
        for jid in list(pending):
            state, jdir = _job_state_and_dir(jid)
            if state in ("done", "failed", "cancelled") and jdir is not None:
                results[jid] = _collect(jid, state, jdir)
                pending.discard(jid)
        if pending:
            time.sleep(interval_s)
    for jid in pending:
        state, jdir = _job_state_and_dir(jid)
        results[jid] = {"job_id": jid, "state": "timeout/" + state}
    return results


def _collect(job_id: str, state: str, jdir: Path) -> Dict[str, Any]:
    result = ops._read_json(jdir / "result.json", {})
    metrics = result.get("metrics") or {}
    ctx = result.get("context") or {}
    execu = ctx.get("execution") or {}
    return {
        "job_id": job_id,
        "state": state,
        "instrument": ctx.get("instrument"),
        "is_tick_replay": execu.get("is_tick_replay"),
        "order_fill_resolution": execu.get("order_fill_resolution"),
        "trade_count": metrics.get("trade_count"),
        "net_profit": metrics.get("net_profit"),
        "gross_profit": metrics.get("gross_profit"),
        "gross_loss": metrics.get("gross_loss"),
        "winning_pct": metrics.get("winning_pct"),
        "profit_factor": metrics.get("profit_factor"),
        "max_drawdown": metrics.get("max_drawdown"),
        "warnings_count": len(result.get("verification_warnings") or []),
        "run_hash": result.get("run_hash"),
    }


def main(argv: List[str]) -> int:
    cells = argv or list(REP_JOBS.keys())
    print(f"Submitting tick-replay verification for: {cells}")
    submitted: List[str] = []
    for cell in cells:
        jid = submit_tickreplay(cell)
        if jid:
            submitted.append(jid)
    if not submitted:
        print("nothing submitted")
        return 1
    print(f"\nWaiting for {len(submitted)} jobs to complete...")
    results = poll(submitted)
    out = jq.project_root() / "data" / "research" / "runtime_mismatch_repair_20260616" / "tickreplay_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"created_at_utc": datetime.now(timezone.utc).isoformat(),
                               "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults -> {out}")
    for jid, r in results.items():
        print(f"  {jid}: state={r.get('state')} trades={r.get('trade_count')} net={r.get('net_profit')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
