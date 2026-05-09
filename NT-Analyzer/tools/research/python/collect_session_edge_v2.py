"""Collect Session-Edge v2 results into a research bundle.

Usage:
  python collect_session_edge_v2.py <bundle_dir>

Reads stage0 / stageA / stageB / stageD manifests in the bundle dir, polls each
batch via /api/batches/{id}, then for every job reads jobs/done/<job_id>/result.json
from disk, computes commission-adjusted metrics, applies acceptance gates, and
writes:
  all_tests.json
  all_tests.csv
  accepted_profiles.json
  paper_candidates.json
  rejected_profiles.json
  summary.md
  next_demo_plan.md
  hypothesis_matrix.md
  research_manifest.json
  all_jobs.json
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402

BUNDLE_VERSION = "session_edge_v2/1"
CLASS_NAME = "NTAMicroSessionEdgeExplorer"

# Acceptance gates (matches user spec).
GATE_MIN_TRADES_FULL = 40
GATE_MIN_TRADES_CURRENT = 20
GATE_OOS_PF_TARGET = 1.20
GATE_OOS_PF_FLOOR = 1.15  # if trades >= 100
GATE_OOS_HIGH_TRADES = 100
GATE_DD_MAX_REL = 1.0  # |dd| <= 1.0 * $2000 = $2000


# -------------------------------------------------------------------------
def adj_metrics(metrics: Dict[str, Any], rtc: float) -> Dict[str, Any]:
    tc = int(metrics.get("trade_count") or 0)
    gp = float(metrics.get("gross_profit") or 0.0)
    gl = float(metrics.get("gross_loss") or 0.0)
    np_ = float(metrics.get("net_profit") or 0.0)
    pf = metrics.get("profit_factor")
    dd = float(metrics.get("max_drawdown") or 0.0)
    wp = float(metrics.get("winning_pct") or 0.0)
    fees = rtc * tc
    adj_net = np_ - fees
    # Approximate adj PF by subtracting half-fee from each side:
    # winners on average pay half a roundturn, losers pay half. Coarse but stable.
    half = 0.5 * fees
    adj_pf = None
    if abs(gl - half) > 1e-9:
        adj_pf = (gp - half) / max(1e-9, abs(gl - half))
    return {
        "trade_count": tc, "gross_profit": gp, "gross_loss": gl,
        "net_profit": np_, "profit_factor": pf,
        "commission_assumed": fees, "round_turn_commission": rtc,
        "adj_net": adj_net, "adj_pf": adj_pf,
        "max_drawdown": dd, "winning_pct": wp,
    }


def classify(adj: Dict[str, Any], is_current_contract: bool) -> str:
    tc = adj["trade_count"]
    pf = adj["adj_pf"] or 0.0
    net = adj["adj_net"]
    dd = adj["max_drawdown"]
    if tc == 0:
        return "rejected_no_trades"
    if pf < 1.0:
        return "rejected_pf"
    if net <= 0:
        return "rejected_net"
    if abs(dd) > 2000.0 * GATE_DD_MAX_REL:
        return "rejected_dd"
    min_trades = GATE_MIN_TRADES_CURRENT if is_current_contract else GATE_MIN_TRADES_FULL
    if tc < min_trades:
        return "candidate_low_trades"
    pf_floor = GATE_OOS_PF_FLOOR if tc >= GATE_OOS_HIGH_TRADES else GATE_OOS_PF_TARGET
    if pf < pf_floor:
        return "candidate_pf"
    return "accepted"


def poll_until_done(batch_ids: List[str], timeout_s: int = 3600,
                    quiet_secs: int = 120) -> Dict[str, Any]:
    """Poll all batches until counts.pending+running == 0 for each.

    Tolerates hung jobs: if a batch has been stable (no progress) for
    `quiet_secs`, accept its current state and move on.
    """
    end = time.time() + timeout_s
    statuses: Dict[str, Any] = {bid: None for bid in batch_ids}
    last_change: Dict[str, float] = {bid: time.time() for bid in batch_ids}
    last_pending: Dict[str, int] = {bid: -1 for bid in batch_ids}
    while time.time() < end:
        all_done = True
        now = time.time()
        for bid in batch_ids:
            if statuses[bid] and statuses[bid].get("_complete"):
                continue
            code, resp = RL.get(f"/api/batches/{bid}")
            if code == 200:
                counts = resp.get("counts", {}) or {}
                pending = int(counts.get("pending", 0)) + int(counts.get("running", 0))
                if pending != last_pending[bid]:
                    last_pending[bid] = pending
                    last_change[bid] = now
                stale = (now - last_change[bid]) > quiet_secs
                resp["_complete"] = pending == 0 or stale
                statuses[bid] = resp
                if not resp["_complete"]:
                    all_done = False
            else:
                all_done = False
        if all_done:
            return statuses
        time.sleep(8)
    return statuses


# -------------------------------------------------------------------------
def collect(bundle_dir: Path) -> int:
    manifests = []
    for n in ("stage0_smoke_manifest.json", "stageA_manifest.json",
              "stageB_mgc_manifest.json", "stageD_manifest.json"):
        p = bundle_dir / n
        if p.exists():
            try:
                manifests.append((n, json.loads(p.read_text(encoding="utf-8"))))
            except Exception as e:
                print(f"WARN cannot read {n}: {e}")
    if not manifests:
        print(f"No manifests in {bundle_dir}")
        return 1

    # Index submissions by batch_id so we know context (mode/family/direction).
    sub_by_batch: Dict[str, Dict[str, Any]] = {}
    for mname, mdata in manifests:
        for s in mdata.get("submitted", []):
            bid = s.get("batch_id")
            if bid:
                sub_by_batch[bid] = {**s, "_manifest": mname}
    batch_ids = list(sub_by_batch.keys())
    print(f"Polling {len(batch_ids)} batches…")
    statuses = poll_until_done(batch_ids)

    all_tests: List[Dict[str, Any]] = []
    all_jobs: List[Dict[str, Any]] = []
    for bid, st in statuses.items():
        sub = sub_by_batch[bid]
        jobs = (st or {}).get("jobs", []) or (st or {}).get("children", []) or []
        for jb in jobs:
            jid = jb.get("id") or jb.get("job_id")
            if not jid:
                continue
            all_jobs.append({"batch_id": bid, "job_id": jid,
                             "status": jb.get("status")})
            rep = RL.read_job_report(jid)
            if not rep or "result" not in rep:
                continue
            ctx = rep["result"].get("context", {}) or {}
            metrics = rep["result"].get("metrics", {}) or {}
            execn = ctx.get("execution", {}) or {}
            instr = ctx.get("instrument") or jb.get("instrument") or "?"
            rtc = float(execn.get("round_turn_commission")
                        or sub["params"].get("RoundTurnCommission") or RL.RTC_FLOOR)
            adj = adj_metrics(metrics, rtc)
            is_current = bool(sub.get("current_contract_validation"))
            verdict = classify(adj, is_current)
            row = {
                "batch_id": bid, "job_id": jid,
                "manifest": sub.get("_manifest"),
                "name": sub.get("name"),
                "family": sub.get("family"),
                "mode": sub.get("mode") or sub["params"].get("SetupMode"),
                "direction": sub.get("direction"),
                "instrument": instr,
                "session_template": sub.get("session_template")
                                     or execn.get("session_template"),
                "from_utc": ctx.get("period", {}).get("from_utc"),
                "to_utc": ctx.get("period", {}).get("to_utc"),
                "slippage_ticks": execn.get("slippage_ticks"),
                "verdict": verdict,
                "is_current_contract": is_current,
                **adj,
                "parameters": sub["params"],
            }
            all_tests.append(row)

    # Write all_tests.{json,csv}
    (bundle_dir / "all_tests.json").write_text(
        json.dumps({"version": BUNDLE_VERSION, "tests": all_tests},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    csv_cols = ["family", "mode", "direction", "instrument", "verdict",
                "trade_count", "winning_pct", "adj_net", "adj_pf",
                "max_drawdown", "round_turn_commission", "from_utc", "to_utc",
                "session_template", "slippage_ticks", "batch_id", "job_id"]
    with (bundle_dir / "all_tests.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=csv_cols, extrasaction="ignore")
        w.writeheader()
        for r in all_tests:
            w.writerow(r)

    # Profile bucketing
    def to_profile(r: Dict[str, Any], status: str) -> Dict[str, Any]:
        pid_parts = [r["family"] or "fam", r["mode"] or "mode",
                     (r["direction"] or "ls"), r["instrument"].split()[0].lower(),
                     RL.utcnow_compact()]
        return {
            "profile_id": "se2_" + "_".join(pid_parts).replace(" ", "").lower(),
            "name": f"SessionEdge v2 {r['mode']} {r['direction']} {r['instrument']}",
            "strategy_class": CLASS_NAME,
            "instrument": r["instrument"],
            "session_template": r["session_template"],
            "family": r["family"], "mode": r["mode"], "direction": r["direction"],
            "from_utc": r["from_utc"], "to_utc": r["to_utc"],
            "metrics": {k: r[k] for k in
                        ("trade_count", "winning_pct", "adj_net", "adj_pf",
                         "net_profit", "profit_factor", "max_drawdown",
                         "round_turn_commission", "commission_assumed")},
            "status": status,
            "verdict_raw": r["verdict"],
            "is_current_contract": r["is_current_contract"],
            "evidence_job_ids": [r["job_id"]],
            "parameters": r["parameters"],
        }

    accepted = [to_profile(r, "paper_ready") for r in all_tests
                if r["verdict"] == "accepted" and (r["from_utc"] or "").startswith("2024")]
    candidates = [to_profile(r, "paper_candidate") for r in all_tests
                  if r["verdict"].startswith("candidate")]
    rejected = [to_profile(r, "rejected") for r in all_tests
                if r["verdict"].startswith("rejected")]

    (bundle_dir / "accepted_profiles.json").write_text(
        json.dumps({"profiles": accepted}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    (bundle_dir / "paper_candidates.json").write_text(
        json.dumps({"profiles": candidates}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    (bundle_dir / "rejected_profiles.json").write_text(
        json.dumps({"profiles": rejected}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    (bundle_dir / "all_jobs.json").write_text(
        json.dumps({"jobs": all_jobs}, indent=2, ensure_ascii=False),
        encoding="utf-8")

    # summary.md
    lines = [
        f"# Session-Edge v2 Bundle — {bundle_dir.name}",
        f"\nStrategy: `{CLASS_NAME}`  (NTAMicroVwapRiskPilot is locked, not modified)",
        f"\nTotal tests: **{len(all_tests)}**  •  accepted: **{len(accepted)}**  •  "
        f"candidates: **{len(candidates)}**  •  rejected: **{len(rejected)}**",
        "\n## By family / mode / instrument",
        "\n| Family | Mode | Direction | Instrument | Trades | Win% | AdjNet | AdjPF | DD | Verdict |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in sorted(all_tests, key=lambda r: (r["family"] or "", r["mode"] or "",
                                              r["instrument"], r["direction"] or "")):
        pf = r["adj_pf"]
        lines.append("| {f} | {m} | {d} | {i} | {tc} | {wp:.0f} | {an:+.0f} | "
                     "{pf} | {dd:.0f} | {v} |".format(
            f=r["family"], m=r["mode"], d=r["direction"], i=r["instrument"],
            tc=r["trade_count"], wp=r["winning_pct"], an=r["adj_net"],
            pf=("{:.2f}".format(pf) if pf is not None else "-"),
            dd=r["max_drawdown"], v=r["verdict"]))
    (bundle_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # hypothesis_matrix.md
    hm = ["# Hypothesis matrix (Session-Edge v2)\n",
          "| Family | Mode | Result so far |",
          "|---|---|---|"]
    by_fm: Dict[tuple, List[Dict]] = {}
    for r in all_tests:
        by_fm.setdefault((r["family"], r["mode"]), []).append(r)
    for (fam, mode), rows in sorted(by_fm.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        accepted_n = sum(1 for r in rows if r["verdict"] == "accepted")
        cand_n = sum(1 for r in rows if r["verdict"].startswith("candidate"))
        rej_n = sum(1 for r in rows if r["verdict"].startswith("rejected"))
        hm.append(f"| {fam} | {mode} | accepted={accepted_n}, "
                  f"candidate={cand_n}, rejected={rej_n} |")
    (bundle_dir / "hypothesis_matrix.md").write_text("\n".join(hm) + "\n", encoding="utf-8")

    # next_demo_plan.md
    plan = ["# Next demo plan\n",
            "## paper_ready (eligible for demo now)\n"]
    if not accepted:
        plan.append("_None — no profile passed all gates this round._\n")
    for p in accepted:
        plan.append(f"- **{p['profile_id']}** — {p['instrument']} "
                    f"{p['mode']}/{p['direction']} | "
                    f"trades={p['metrics']['trade_count']}, "
                    f"AdjNet={p['metrics']['adj_net']:+.0f}, "
                    f"AdjPF={p['metrics']['adj_pf']}")
    plan += ["\n## paper_candidate (need forward proof or current contract)\n"]
    for p in candidates:
        plan.append(f"- {p['profile_id']} — {p['instrument']} "
                    f"{p['mode']}/{p['direction']} ({p['verdict_raw']})")
    (bundle_dir / "next_demo_plan.md").write_text("\n".join(plan) + "\n", encoding="utf-8")

    # research_manifest.json
    (bundle_dir / "research_manifest.json").write_text(json.dumps({
        "version": BUNDLE_VERSION,
        "strategy_class": CLASS_NAME,
        "generated_utc": RL.utcnow_iso(),
        "counts": {"tests": len(all_tests), "accepted": len(accepted),
                   "candidates": len(candidates), "rejected": len(rejected),
                   "batches": len(batch_ids), "jobs": len(all_jobs)},
        "manifests_read": [m for m, _ in manifests],
        "notes": ("RoundTurnCommission is a project assumption "
                  "(NinjaTrader-side fee model), not an external prop-firm fee schedule. "
                  "Instrument universe comes from the local data/catalog/instrument_groups.json 'Micros' group."),
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nWrote bundle: {bundle_dir}")
    print(f"  tests={len(all_tests)} accepted={len(accepted)} "
          f"candidates={len(candidates)} rejected={len(rejected)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(collect(Path(sys.argv[1])))
