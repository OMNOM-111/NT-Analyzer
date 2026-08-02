#!/usr/bin/env python3
"""Exercise synchronous and SSE Orchestrator HTTP through the durable worker."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _post(base: str, path: str, body: dict) -> tuple[int, bytes, str]:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
            "Origin": base,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.status, response.read(), str(response.headers.get("Content-Type") or "")


def _get(base: str, path: str) -> tuple[int, dict]:
    with urllib.request.urlopen(base + path, timeout=30) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def main() -> int:
    artifacts = ROOT / ".artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="ai-http-", dir=artifacts)).resolve()
    production = stage.parent / (stage.name + "-production-guard")
    production.mkdir(parents=True, exist_ok=True)
    sentinel = production / "sentinel.bin"
    sentinel.write_bytes(b"production-must-not-change")
    os.environ.update({
        "NTA_APP_ENV": "staging",
        "NTA_DATA_ROOT": str(production),
        "NTA_STAGING_DATA_ROOT": str(stage),
        "NTA_TELEGRAM_CHAT_ID": "910000",
        "NT_ANALYZER_ROOT": str(ROOT),
    })
    os.environ.pop("NT_ANALYZER_SQLITE_PATH", None)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from app import account_auth, durable, local_worker  # pylint: disable=import-outside-toplevel
    from app import server as server_mod  # pylint: disable=import-outside-toplevel

    account_auth.ensure_owner(910000)
    account_auth.set_auth_required(False)
    local_worker.start_background_worker(interval_sec=0.2)
    httpd = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://{httpd.server_address[0]}:{httpd.server_address[1]}"
    try:
        body = {
            "message": "Виктор, покажи статус",
            "conversation_id": "C-DURABLE-HTTP",
            "agent": "vitek",
            "request_id": "probe:sync:one",
        }
        first_status, first_raw, first_type = _post(
            base, "/api/ai-lab/orchestrator/message", body,
        )
        replay_status, replay_raw, _ = _post(
            base, "/api/ai-lab/orchestrator/message", body,
        )
        first = json.loads(first_raw.decode("utf-8"))
        replay = json.loads(replay_raw.decode("utf-8"))
        stream_status, stream_raw, stream_type = _post(
            base,
            "/api/ai-lab/orchestrator/message/stream",
            {
                **body,
                "conversation_id": "C-DURABLE-SSE",
                "request_id": "probe:sse:one",
            },
        )
        stream_text = stream_raw.decode("utf-8")
        chart_status, chart = _get(
            base,
            "/api/ops/runtime/bars?instrument=MNQ&timeframe=5m&limit=20000",
        )
        batch_status, batch_raw, _ = _post(
            base,
            "/api/ops/runtime/bars/batch",
            {"requests": [{
                "instrument": "MGC", "timeframe": "5m",
                "limit": 20000, "max_points": 12000,
            }]},
        )
        batch = json.loads(batch_raw.decode("utf-8"))
        counts = durable.worker_job_counts(None)
        result = {
            "ok": bool(
                first_status == replay_status == stream_status == 200
                and "application/json" in first_type
                and "text/event-stream" in stream_type
                and first.get("ok") is True
                and replay.get("message", {}).get("message_id")
                == first.get("message", {}).get("message_id")
                and "event: final" in stream_text
                and "event: done" in stream_text
                and '"durable": true' in stream_text
                and chart_status == batch_status == 200
                and isinstance(chart.get("bars"), list)
                and isinstance(batch.get("series"), list)
                and counts.get("succeeded") == 4
                and sentinel.read_bytes() == b"production-must-not-change"
            ),
            "sync_status": first_status,
            "replay_status": replay_status,
            "same_message_id": replay.get("message", {}).get("message_id")
            == first.get("message", {}).get("message_id"),
            "sse_status": stream_status,
            "sse_final": "event: final" in stream_text,
            "sse_done": "event: done" in stream_text,
            "large_chart_status": chart_status,
            "large_chart_batch_status": batch_status,
            "worker_counts": counts,
            "production_guard_unchanged": sentinel.read_bytes()
            == b"production-must-not-change",
            "staging_data_root": str(stage),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)
        local_worker.stop_background_worker()


if __name__ == "__main__":
    raise SystemExit(main())
