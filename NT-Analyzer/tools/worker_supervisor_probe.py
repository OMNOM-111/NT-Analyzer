#!/usr/bin/env python3
"""Kill the real worker process and verify supervised durable recovery."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    artifact_root = ROOT / ".artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="worker-crash-", dir=artifact_root)).resolve()
    production = stage.parent / (stage.name + "-production-guard")
    production.mkdir(parents=True, exist_ok=True)
    sentinel = production / "sentinel.bin"
    sentinel.write_bytes(b"production-must-not-change")
    os.environ.update({
        "NTA_APP_ENV": "staging",
        "NTA_DATA_ROOT": str(production),
        "NTA_STAGING_DATA_ROOT": str(stage),
        "NT_ANALYZER_ROOT": str(ROOT),
    })
    os.environ.pop("NT_ANALYZER_SQLITE_PATH", None)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from app import durable, local_worker  # pylint: disable=import-outside-toplevel

    job_id = "wj_supervisor_crash"
    started = time.perf_counter()
    old_pid = 0
    new_pid = 0
    final = {}
    try:
        local_worker.start_background_worker(interval_sec=0.2)
        local_worker.enqueue(
            "sleep", {"seconds": 1.5}, job_id=job_id,
            workspace_id="ws_recovery", user_id="9001",
            timeout_sec=4, max_attempts=2,
        )
        deadline = time.time() + 10
        while time.time() < deadline:
            row = durable.get_worker_job(None, job_id)
            proc = local_worker._PROCESS  # release probe intentionally inspects the child
            if row and row.get("status") == "running" and proc is not None and proc.is_alive():
                old_pid = int(proc.pid or 0)
                proc.terminate()
                proc.join(timeout=2)
                break
            time.sleep(0.05)
        deadline = time.time() + 15
        while time.time() < deadline:
            final = durable.get_worker_job(None, job_id) or {}
            proc = local_worker._PROCESS
            if proc is not None and proc.is_alive() and int(proc.pid or 0) != old_pid:
                new_pid = int(proc.pid or 0)
            if final.get("status") in {"succeeded", "failed", "cancelled", "stale"}:
                break
            time.sleep(0.1)
        elapsed_ms = (time.perf_counter() - started) * 1000
        status = local_worker.status()
        result = {
            "ok": bool(
                old_pid and new_pid and new_pid != old_pid
                and final.get("status") == "succeeded"
                and int(final.get("attempts") or 0) == 2
                and status.get("supervisor_alive")
                and sentinel.read_bytes() == b"production-must-not-change"
            ),
            "old_pid": old_pid,
            "new_pid": new_pid,
            "job_status": final.get("status"),
            "attempts": final.get("attempts"),
            "recovery_ms": round(elapsed_ms, 3),
            "supervisor_alive": status.get("supervisor_alive"),
            "production_guard_unchanged": sentinel.read_bytes() == b"production-must-not-change",
            "staging_data_root": str(stage),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    finally:
        local_worker.stop_background_worker()


if __name__ == "__main__":
    raise SystemExit(main())
