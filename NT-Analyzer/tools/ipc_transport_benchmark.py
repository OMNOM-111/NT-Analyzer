#!/usr/bin/env python3
"""Run localhost IPC transport benchmark and print a markdown table."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import market_data_ipc  # noqa: E402


def main() -> int:
    market_data_ipc.ensure_auth_token()
    result = market_data_ipc.benchmark_transports(iterations=300, payload_bytes=160)
    print(json.dumps(result, indent=2))
    print()
    print("| Transport | Status | Notes |")
    print("|---|---|---|")
    for name, row in (result.get("transports") or {}).items():
        if "events_per_sec" in row:
            note = f"{row['events_per_sec']} ev/s in {row['elapsed_sec']}s"
        else:
            note = str(row.get("notes") or row.get("status") or "")
        print(f"| {name} | {row.get('status', 'measured')} | {note} |")
    print()
    print(f"Selected default: **{result.get('selected_default')}** — {result.get('selection_reason')}")
    out = ROOT / "data" / "runtime" / "market_data_ipc_benchmark.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
