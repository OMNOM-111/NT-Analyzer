"""Collect job/report artifacts for a list of batch_ids and produce a
flat all_tests CSV/JSON suitable for downstream analysis.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent))
import research_lib as RL  # noqa: E402

CSV_FIELDS = [
    "batch_id", "job_id", "status", "instrument", "class_name",
    "session_template", "from_utc", "to_utc",
    "trades", "net_profit", "adjusted_net_profit", "profit_factor",
    "max_drawdown", "winning_trades", "losing_trades",
    "params_hash", "error_type", "error_message",
]


def flatten_one(batch_id: str, job_id: str) -> Dict[str, Any]:
    bundle = RL.read_job_report(job_id) or {}
    job = bundle.get("job", {}) or {}
    result = bundle.get("result", {}) or {}
    metrics = (result.get("metrics") or {})
    err = result.get("error") or {}
    out = {
        "batch_id": batch_id,
        "job_id": job_id,
        "status": ("done" if not err else "failed"),
        "instrument": job.get("instrument"),
        "class_name": (job.get("strategy") or {}).get("class_name"),
        "session_template": (job.get("execution") or {}).get("session_template"),
        "from_utc": (job.get("period") or {}).get("from_utc"),
        "to_utc": (job.get("period") or {}).get("to_utc"),
        "trades":              metrics.get("trade_count"),
        "net_profit":          metrics.get("net_profit"),
        "adjusted_net_profit": metrics.get("adjusted_net_profit") or metrics.get("net_profit"),
        "profit_factor":       metrics.get("profit_factor"),
        "max_drawdown":        metrics.get("max_drawdown"),
        "winning_trades":      metrics.get("winning_trades"),
        "losing_trades":       metrics.get("losing_trades"),
        "params_hash":         (job.get("strategy") or {}).get("parameters_hash"),
        "error_type":          err.get("error_type") if err else None,
        "error_message":       (err.get("message") or "")[:300] if err else None,
    }
    return out


def collect(batch_ids: List[str], out_dir: Path) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    raw: List[Dict[str, Any]] = []
    for bid in batch_ids:
        code, resp = RL.get(f"/api/batches/{bid}")
        if code != 200:
            print(f"[WARN] batch {bid}: HTTP {code}")
            continue
        children = resp.get("children") or resp.get("jobs") or []
        for ch in children:
            jid = ch.get("job_id") if isinstance(ch, dict) else ch
            row = flatten_one(bid, jid)
            rows.append(row)
            raw.append(RL.read_job_report(jid) or {"job_id": jid, "missing": True})
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_p = out_dir / "all_tests.csv"
    json_p = out_dir / "all_tests.json"
    with csv_p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in CSV_FIELDS})
    json_p.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (out_dir / "all_tests_raw.json").write_text(
        json.dumps(raw, indent=2), encoding="utf-8")
    return {"rows": len(rows), "csv": str(csv_p), "json": str(json_p)}


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: collect_research_results.py <out_dir> <batch_id> [batch_id ...]")
        return 2
    out_dir = Path(sys.argv[1])
    batch_ids = sys.argv[2:]
    info = collect(batch_ids, out_dir)
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
