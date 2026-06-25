"""One-shot: persist Stage 2 final decisions into strategy notes + summary.json."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import ops, final_decision as fd  # noqa: E402

doc = ops._read_json(ops._project_root() / "data" / "profiles" / "strategies.json", {})
prof = {str(p.get("cell_id")): p for p in (doc.get("profiles") or [])}

res = fd.generate()
written = []
for r in res["decisions"]:
    cell = r["cell_id"]
    p = prof.get(cell) or {}
    sid = p.get("stable_id") or p.get("runtime_strategy_id")
    if not sid:
        legacy = p.get("legacy_strategy_ids") or []
        sid = legacy[0] if legacy else None
    note = ("[Stage2 final 2026-06-16] decision={d}. HF {ht}tr/{hn}, "
            "tick-replay {tt}tr/{tn}, runtime {rt}tr/{rn}. {reason}").format(
        d=r["decision"], ht=r.get("highfill_trades"), hn=r.get("highfill_net"),
        tt=r.get("tickreplay_trades"), tn=r.get("tickreplay_net"),
        rt=r.get("runtime_trades"), rn=r.get("runtime_net"), reason=r["reason"])
    if sid:
        try:
            ops.append_note(sid, note, by="stage2_diagnostic")
            written.append((cell, sid, r["decision"], "noted"))
        except Exception as e:  # noqa: BLE001
            written.append((cell, sid, r["decision"], "ERR:" + str(e)))
    else:
        written.append((cell, None, r["decision"], "no_strategy_id"))

# summary.json
counts = {}
for r in res["decisions"]:
    counts[r["decision"]] = counts.get(r["decision"], 0) + 1
summary = {
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "audit_id": "runtime_backtest_mismatch_2026-06-16",
    "stage": "final",
    "verification_method": "current-contract tick-replay vs High-fill vs runtime strict fact",
    "fingerprint_status": "real (sha256 of bars.json) backfilled for all Stage 2 jobs; bridge computes natively going forward",
    "decision_counts": counts,
    "decisions": res["decisions"],
    "relaunch_approved_cells": [r["cell_id"] for r in res["decisions"] if r["relaunch_allowed"]],
    "notes_written": [{"cell": c, "strategy_id": s, "decision": d, "status": st} for c, s, d, st in written],
}
out = Path(res["out_dir"]) / "summary.json"
out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print("summary ->", out)
for w in written:
    print(" ", w)
print("decision_counts:", counts)
