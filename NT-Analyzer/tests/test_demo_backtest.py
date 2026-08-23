"""Demo backtest tier for free_preview users."""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, demo_backtest, permissions, subscriptions
from app import server as server_mod


@pytest.fixture()
def demo_store(tmp_path, monkeypatch):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(demo_backtest, "_root", lambda: tmp_path)
    monkeypatch.setattr(subscriptions, "_root", lambda: tmp_path)
    monkeypatch.setattr(account_auth.secure_store, "_protect", lambda b: b)
    monkeypatch.setattr(account_auth.secure_store, "_unprotect", lambda b: b)
    monkeypatch.setattr(account_auth.secure_store, "available", lambda: True)
    (tmp_path / "data" / "integrations").mkdir(parents=True)
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    (tmp_path / "jobs" / "done").mkdir(parents=True)
    monkeypatch.setattr("app.jobqueue.jobs_dir", lambda: tmp_path / "jobs")
    account_auth._write_doc({
        "version": 1,
        "users": [
            {"user_id": 999, "first_name": "Owner", "role": "owner", "status": "active", "is_owner": True},
            {"user_id": 42, "first_name": "Free", "role": "read_only", "status": "active", "is_owner": False, "ux_mode": "professional"},
        ],
        "challenges": [],
        "sessions": [],
    })
    account_auth.set_auth_required(True)
    return tmp_path


def _token_row(user_id, token, csrf):
    return {
        "session_id": "sess_" + token[:8],
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(),
        "csrf_token": csrf,
        "user_id": user_id,
        "created_at_utc": "2026-07-15T00:00:00Z",
        "expires_at": 4_000_000_000,
        "revoked": False,
        "device_id": "d", "client": "Chrome", "machine": "PC", "ip": "127.0.0.1",
    }


def _request(base, path, *, token="", csrf="", method="GET", body=None):
    headers = {"Origin": base}
    if token:
        headers["Cookie"] = f"{account_auth.SESSION_COOKIE}={token}"
    if csrf:
        headers["X-CSRF-Token"] = csrf
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_authenticated_baseline_unlocks_demo_backtest_nav():
    perm = permissions.resolve({"user_id": 1, "is_owner": False, "ux_mode": "professional"}, None)
    assert perm["free_preview"] is False
    assert perm["baseline_access"] is True
    assert perm["plan_id"] == "authenticated_basic"
    assert perm["capabilities"]["demo_backtest"] is True
    assert perm["capabilities"]["backtesting"] is False
    assert perm["nav"]["backtest"] is True
    assert perm["demo_tier"] is True
    assert "backtest" not in perm["locked_nav"]


def test_create_demo_backtest_writes_readable_job(demo_store):
    out = demo_backtest.create_demo_backtest(42, scenario_id="mnq_orb_90d", daily_limit=3)
    assert out["ok"] and out["demo"]
    assert out["remaining_today"] == 2
    from app import jobqueue
    full = jobqueue.read_job_full(out["job_id"])
    assert full and full["status"] == "done"
    assert full["result"]["metrics"]["trade_count"] > 0
    assert full["result"]["watermark"]


def test_demo_quota_and_http_endpoint(demo_store, monkeypatch):
    user_token, user_csrf = "u" * 64, "v" * 48
    doc = account_auth._read_doc()
    doc["sessions"] = [_token_row(42, user_token, user_csrf)]
    account_auth._write_doc(doc)

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        scenarios = _request(base, "/api/demo-backtests/scenarios", token=user_token)
        assert len(scenarios["scenarios"]) >= 3
        first = _request(
            base, "/api/demo-backtests", token=user_token, csrf=user_csrf,
            method="POST", body={"scenario_id": "mes_vwap_90d"},
        )
        assert first["job_id"].startswith("demo_")
        job = _request(base, f"/api/jobs/{first['job_id']}", token=user_token)
        assert job["status"] == "done"
        trades = _request(base, f"/api/jobs/{first['job_id']}/trades", token=user_token)
        assert (trades.get("trades") or trades.get("rows") or trades.get("items") or trades)
        # Exhaust quota
        _request(base, "/api/demo-backtests", token=user_token, csrf=user_csrf, method="POST", body={})
        _request(base, "/api/demo-backtests", token=user_token, csrf=user_csrf, method="POST", body={})
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/demo-backtests", token=user_token, csrf=user_csrf, method="POST", body={})
        assert exc.value.code == 429
    finally:
        server.shutdown()
        server.server_close()
