"""Phase A: runtime_env, dual-auth Google linking, staging test-auth, impersonation, admin-kill notice."""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, google_auth, runtime_env, test_auth
from app import server as server_mod
from app import telegram_service


@pytest.fixture()
def phase_a_store(tmp_path, monkeypatch):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    monkeypatch.setenv("NTA_DUAL_AUTH_REQUIRED", "1")
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(google_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(account_auth.secure_store, "_protect", lambda b: b)
    monkeypatch.setattr(account_auth.secure_store, "_unprotect", lambda b: b)
    monkeypatch.setattr(account_auth.secure_store, "available", lambda: True)
    monkeypatch.setattr(google_auth.secure_store, "_protect", lambda b: b)
    monkeypatch.setattr(google_auth.secure_store, "_unprotect", lambda b: b)
    (tmp_path / "data" / "integrations").mkdir(parents=True)
    (tmp_path / "data" / "audit").mkdir(parents=True)
    account_auth._write_doc({
        "version": 1,
        "users": [
            {
                "user_id": 999, "username": "owner", "first_name": "Owner",
                "role": "owner", "status": "active", "is_owner": True,
                "google_sub": "owner-google", "google_linked_at_utc": "2026-01-01T00:00:00Z",
            },
        ],
        "challenges": [],
        "sessions": [],
    })
    account_auth.set_auth_required(True)
    return tmp_path


def _token_row(user_id: int, token: str, csrf: str, **extra):
    row = {
        "session_id": "sess_" + token[:8],
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(),
        "csrf_token": csrf,
        "user_id": user_id,
        "created_at_utc": "2026-07-15T00:00:00Z",
        "expires_at": 4_000_000_000,
        "revoked": False,
        "device_id": "dev",
        "client": "Chrome",
        "machine": "PC",
        "ip": "127.0.0.1",
    }
    row.update(extra)
    return row


def _request(base: str, path: str, *, token: str = "", csrf: str = "", method: str = "GET", body=None):
    data = None
    headers = {"Origin": base}
    if token:
        headers["Cookie"] = f"{account_auth.SESSION_COOKIE}={token}"
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_runtime_env_blocks_test_auth_in_production(monkeypatch):
    monkeypatch.setenv("NTA_APP_ENV", "production")
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    with pytest.raises(runtime_env.RuntimeEnvError):
        runtime_env.assert_production_safe()
    monkeypatch.delenv("NTA_ENABLE_TEST_AUTH", raising=False)
    runtime_env.assert_production_safe()
    assert runtime_env.is_production()
    assert not runtime_env.test_auth_enabled()
    assert not runtime_env.impersonation_enabled()


def test_runtime_env_rejects_unknown_environment_and_prod_impersonation(monkeypatch):
    monkeypatch.setenv("NTA_APP_ENV", "prodution")
    with pytest.raises(runtime_env.RuntimeEnvError):
        runtime_env.assert_production_safe()

    monkeypatch.setenv("NTA_APP_ENV", "production")
    monkeypatch.setenv("NTA_ENABLE_IMPERSONATION", "1")
    with pytest.raises(runtime_env.RuntimeEnvError):
        runtime_env.assert_production_safe()

    monkeypatch.delenv("NTA_ENABLE_IMPERSONATION", raising=False)
    monkeypatch.setenv("NTA_DISABLE_RATE_LIMIT", "1")
    with pytest.raises(runtime_env.RuntimeEnvError):
        runtime_env.assert_production_safe()


def test_rate_limit_bypass_is_staging_only(monkeypatch):
    monkeypatch.setenv("NTA_DISABLE_RATE_LIMIT", "1")
    monkeypatch.setenv("NTA_APP_ENV", "production")
    assert runtime_env.rate_limits_disabled() is False
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    assert runtime_env.rate_limits_disabled() is True


def test_dual_auth_google_link_unique_and_needs_google(phase_a_store, monkeypatch):
    monkeypatch.setenv("NTA_GOOGLE_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setenv("NTA_GOOGLE_CLIENT_SECRET", "secret")
    user = account_auth.create_or_update_virtual_user(
        user_id=42, username="alice", first_name="Alice", google_linked=False, preset="no_google",
    )
    assert user["needs_google"] is True
    assert user["google_linked"] is False
    linked = account_auth.link_google_identity(42, google_sub="g-alice", google_email="alice@example.com")
    assert linked["user"]["google_linked"] is True
    assert linked["user"]["needs_google"] is False
    account_auth.create_or_update_virtual_user(
        user_id=43, username="bob", first_name="Bob", google_linked=False, preset="no_google",
    )
    with pytest.raises(account_auth.AccountAuthError) as exc:
        account_auth.link_google_identity(43, google_sub="g-alice", google_email="other@example.com")
    assert exc.value.status == 409


def test_admin_revoke_returns_session_admin_revoked_code(phase_a_store, monkeypatch):
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    user_token, user_csrf = "u" * 64, "v" * 48
    owner_token, owner_csrf = "o" * 64, "p" * 48
    account_auth.create_or_update_virtual_user(
        user_id=42, username="dev", first_name="Dev", google_linked=True, preset="demo",
    )
    doc = account_auth._read_doc()
    doc["sessions"] = [
        _token_row(999, owner_token, owner_csrf),
        _token_row(42, user_token, user_csrf, session_id="sess_user01"),
    ]
    account_auth._write_doc(doc)

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        ended = _request(
            base, "/api/auth/users/42/sessions", token=owner_token, csrf=owner_csrf,
            method="POST", body={"session_id": "sess_user01"},
        )
        assert ended["revoked"] == 1
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/auth/status", token=user_token)
        assert exc.value.code == 401
        payload = json.loads(exc.value.read().decode("utf-8"))
        assert payload["code"] == "session_admin_revoked"
        assert "администратором" in payload["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_staging_virtual_user_impersonation_and_return(phase_a_store, monkeypatch):
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    owner_token, owner_csrf = "o" * 64, "p" * 48
    doc = account_auth._read_doc()
    doc["sessions"] = [_token_row(999, owner_token, owner_csrf)]
    account_auth._write_doc(doc)

    created = test_auth.create_virtual_user(preset="demo", display_name="Virtual Demo")
    uid = int(created["user"]["user_id"])
    assert created["user"]["is_virtual"] is True

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        status = _request(base, "/api/auth/test/status", token=owner_token)
        assert status["enabled"] is True
        out = _request(
            base, "/api/owner/impersonate", token=owner_token, csrf=owner_csrf,
            method="POST", body={"user_id": uid},
        )
        assert out["impersonating"] is True
        # Cookie was set on response; pull from Set-Cookie via a follow-up using returned fields.
        # Re-read sessions: latest impersonation session for target.
        doc = account_auth._read_doc()
        imp = next(s for s in doc["sessions"] if int(s.get("user_id") or 0) == uid and not s.get("revoked"))
        assert int(imp.get("impersonator_owner_id") or 0) == 999
        
        # Verify HTTP API end_impersonation doesn't block the impersonated user (403).
        session = account_auth.start_impersonation(999, uid, ip="127.0.0.1")
        ended_http = _request(
            base, "/api/owner/impersonate/end", token=session["session_token"],
            csrf=session["csrf_token"], method="POST", body={}
        )
        assert ended_http["restored_owner"] is True
        assert ended_http["user"]["id"] == account_auth.user_uuid_for_legacy_id(999)
    finally:
        server.shutdown()
        server.server_close()


def test_impersonation_blocked_in_production(phase_a_store, monkeypatch):
    monkeypatch.setenv("NTA_APP_ENV", "production")
    monkeypatch.delenv("NTA_ENABLE_TEST_AUTH", raising=False)
    with pytest.raises(runtime_env.RuntimeEnvError):
        account_auth.start_impersonation(999, 42)


def test_active_sessions_overview_and_monitoring_shape(phase_a_store, monkeypatch):
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    account_auth.create_or_update_virtual_user(
        user_id=42, username="dev", first_name="Dev", google_linked=True, preset="demo",
    )
    owner_token, owner_csrf = "o" * 64, "p" * 48
    user_token, user_csrf = "u" * 64, "v" * 48
    doc = account_auth._read_doc()
    doc["sessions"] = [
        _token_row(999, owner_token, owner_csrf),
        _token_row(42, user_token, user_csrf),
    ]
    account_auth._write_doc(doc)
    overview = account_auth.active_sessions_overview(999)
    assert overview["count"] >= 2
    assert {row["user_id"] for row in overview["sessions"]} >= {999, 42}

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        mon = _request(base, "/api/owner/support/monitoring", token=owner_token)
        assert "users" in mon
        assert "auth_sessions" in mon
        assert "telemetry_note" in mon
        assert mon["runtime"]["app_env"] == "staging"
    finally:
        server.shutdown()
        server.server_close()


def test_google_migration_list(phase_a_store):
    account_auth.create_or_update_virtual_user(
        user_id=42, username="old", first_name="Old", google_linked=False, preset="no_google",
    )
    account_auth.create_or_update_virtual_user(
        user_id=43, username="new", first_name="New", google_linked=True, preset="demo",
    )
    out = account_auth.google_migration_users(999)
    assert out["pending_count"] >= 1
    assert any(row["user_id"] == 42 and not row["google_linked"] for row in out["without_google"])
