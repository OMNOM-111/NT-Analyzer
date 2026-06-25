"""Regression tests for two production defects found in the technical audit.

Run from NT-Analyzer/ root:
    python -m tests.test_server_errors

Covers:
  1. Metrics / Performance / runtime must NOT crash when the IANA tz database
     (tzdata / ZoneInfo) is unavailable. `ops._to_pt` must fall back instead of
     raising ZoneInfoNotFoundError (which previously bubbled up and made
     compute_metrics_safe() silently return {"error": ...} with no metrics).
  2. GET /api/performance must return a clean HTTP 500 JSON body when an
     internal error occurs, instead of aborting the socket with a bare
     traceback (the old do_GET had no catch-all guard).
"""
from __future__ import annotations

import json
import sys
import threading
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import ops  # noqa: E402
from app import server as server_mod  # noqa: E402


# --------------------------------------------------------------------------
# Test harness
# --------------------------------------------------------------------------

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def case(name: str):
    def deco(fn):
        def wrap():
            try:
                fn()
                PASSED.append(name)
                print(f"  PASS  {name}")
            except AssertionError as e:
                FAILED.append((name, f"AssertionError: {e}\n{traceback.format_exc()}"))
                print(f"  FAIL  {name}: {e}")
            except Exception as e:  # noqa: BLE001
                FAILED.append((name, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"))
                print(f"  ERR   {name}: {e}")
        return wrap
    return deco


# --------------------------------------------------------------------------
# Defect 1 — tz database missing must not crash _to_pt
# --------------------------------------------------------------------------

@case("ops._to_pt falls back when ZoneInfo is unavailable")
def t01():
    sample = datetime(2026, 1, 15, 18, 0, 0, tzinfo=timezone.utc)
    saved = ops.ZoneInfo

    def _boom(*_a, **_k):  # simulate a system with no IANA tz database
        raise RuntimeError("no tz database found")

    ops.ZoneInfo = _boom  # type: ignore[assignment]
    try:
        result = ops._to_pt(sample)
    finally:
        ops.ZoneInfo = saved  # type: ignore[assignment]

    assert isinstance(result, datetime), type(result)
    # Fallback is the fixed -8h offset (DST-unaware, but must not raise).
    assert result.hour == 10, result
    assert result.tzinfo is not None, "fallback must stay tz-aware"


@case("ops._to_pt also tolerates ZoneInfo set to None")
def t02():
    saved = ops.ZoneInfo
    ops.ZoneInfo = None  # type: ignore[assignment]
    try:
        result = ops._to_pt(datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc))
    finally:
        ops.ZoneInfo = saved  # type: ignore[assignment]
    assert isinstance(result, datetime), type(result)
    assert result.hour == 4, result  # 12:00 UTC - 8h


# --------------------------------------------------------------------------
# Defect 2 — GET /api/performance returns 500 JSON, not a socket abort
# --------------------------------------------------------------------------

def _start_server() -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


@case("GET /api/performance returns HTTP 500 JSON on internal error")
def t03():
    saved = server_mod.performance.build_performance_response

    def _boom(*_a, **_k):
        raise RuntimeError("simulated internal failure")

    server_mod.performance.build_performance_response = _boom  # type: ignore[assignment]
    srv = _start_server()
    try:
        host, port = srv.server_address[0], srv.server_address[1]
        url = f"http://{host}:{port}/api/performance"
        status = None
        body = b""
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                status = resp.status
                body = resp.read()
        except urllib.error.HTTPError as e:
            # Expected path: a well-formed 500 response (NOT a dropped socket).
            status = e.code
            body = e.read()
    finally:
        srv.shutdown()
        srv.server_close()
        server_mod.performance.build_performance_response = saved  # type: ignore[assignment]

    assert status == 500, f"expected 500, got {status}"
    payload = json.loads(body.decode("utf-8"))
    assert "error" in payload, payload


@case("GET /api/health still works on a fresh server (sanity)")
def t04():
    srv = _start_server()
    try:
        host, port = srv.server_address[0], srv.server_address[1]
        url = f"http://{host}:{port}/api/health"
        with urllib.request.urlopen(url, timeout=5) as resp:
            status = resp.status
            payload = json.loads(resp.read().decode("utf-8"))
    finally:
        srv.shutdown()
        srv.server_close()
    assert status == 200, status
    assert payload.get("ok") is True, payload


@case("POST /api/ai-lab/run returns 409 JSON when runner busy")
def t05():
    import threading as th
    from app.ai_lab import runner as ai_runner

    saved = ai_runner.start

    def _busy(_args):
        raise ai_runner.RunnerBusy({
            "experiment_id": "EXP-busy-http",
            "status": "generating",
            "cancel_event": th.Event(),
        })

    ai_runner.start = _busy  # type: ignore[assignment]
    srv = _start_server()
    try:
        host, port = srv.server_address[0], srv.server_address[1]
        url = f"http://{host}:{port}/api/ai-lab/run"
        req = urllib.request.Request(
            url,
            data=json.dumps({"goal": "x", "dry_run": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        status = None
        body = b""
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
                body = resp.read()
        except urllib.error.HTTPError as e:
            status = e.code
            body = e.read()
    finally:
        srv.shutdown()
        srv.server_close()
        ai_runner.start = saved  # type: ignore[assignment]

    assert status == 409, f"expected 409, got {status}: {body!r}"
    payload = json.loads(body.decode("utf-8"))
    assert payload.get("busy") is True, payload
    assert payload.get("current", {}).get("experiment_id") == "EXP-busy-http"
    assert "cancel_event" not in payload.get("current", {})


# --------------------------------------------------------------------------

def main() -> int:
    tests = [t01, t02, t03, t04, t05]
    print(f"Running {len(tests)} server/tz regression tests:")
    for t in tests:
        t()
    print()
    print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        for name, msg in FAILED:
            print(f"\n--- {name} ---")
            print(msg)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
