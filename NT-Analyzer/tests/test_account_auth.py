from __future__ import annotations

import hashlib
import base64
import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, permissions, secure_store, subscriptions, workspaces
from app import server as server_mod
from app.production_storage import MigrationRunner
from app.production_storage.core import DocumentRepository


@pytest.fixture
def auth_store(monkeypatch, tmp_path):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(subscriptions, "_root", lambda: tmp_path)
    monkeypatch.setattr(workspaces, "_root", lambda: tmp_path)
    monkeypatch.setattr(secure_store, "available", lambda: True)
    monkeypatch.setattr(secure_store, "backend_name", lambda: "test DPAPI")
    monkeypatch.setattr(secure_store, "_protect", lambda value: value[::-1])
    monkeypatch.setattr(secure_store, "_unprotect", lambda value: value[::-1])
    with account_auth._RATE_LOCK:
        account_auth._LOGIN_RATE.clear()
    return tmp_path


def _api_recorder():
    calls = []

    def api(method, payload=None, **_kwargs):
        calls.append((method, payload or {}))
        return {}

    return calls, api


def test_dpapi_read_cache_is_isolated_and_refreshes_after_write(auth_store, monkeypatch) -> None:
    account_auth._clear_doc_cache()
    account_auth._write_doc({
        "version": 2,
        "users": [{"user_id": 42, "first_name": "Ada", "status": "active"}],
        "challenges": [],
        "sessions": [],
    })
    # Force the first read through the decryptor, then verify that concurrent
    # page requests can reuse only an immutable in-memory snapshot.
    account_auth._clear_doc_cache()
    original_unprotect = secure_store._unprotect
    decrypts = []

    def counting_unprotect(value):
        decrypts.append(True)
        return original_unprotect(value)

    monkeypatch.setattr(secure_store, "_unprotect", counting_unprotect)
    first = account_auth._read_doc()
    second = account_auth._read_doc()
    assert len(decrypts) == 1
    first["users"][0]["first_name"] = "Tampered"
    assert second["users"][0]["first_name"] == "Ada"
    assert account_auth._read_doc()["users"][0]["first_name"] == "Ada"

    updated = account_auth._read_doc()
    updated["users"][0]["first_name"] = "Grace"
    account_auth._write_doc(updated)
    assert account_auth._read_doc()["users"][0]["first_name"] == "Grace"
    assert len(decrypts) == 1


def test_new_account_activates_full_trial_after_contact_profile_and_terms(auth_store) -> None:
    account_auth.ensure_owner(999)
    login = account_auth.start_login(bot_username="StratForge_bot", ip="127.0.0.1")
    calls, api = _api_recorder()

    assert account_auth.process_update({"message": {
        "text": login["bot_url"].split("?start=", 1)[1].join(["/start ", ""]),
        "from": {"id": 42, "first_name": "Ada", "username": "ada"},
        "chat": {"id": 42, "type": "private"},
    }}, api_call=api, owner_chat_id="999")
    # The bot now offers one confirmation button; a contact is still accepted
    # (and still records the phone identity) but is no longer demanded.
    assert any((payload.get("reply_markup") or {}).get("inline_keyboard") for _method, payload in calls)

    assert account_auth.process_update({"message": {
        "contact": {"user_id": 42, "phone_number": "+15551234567"},
        "from": {"id": 42}, "chat": {"id": 42, "type": "private"},
    }}, api_call=api, owner_chat_id="999")
    assert account_auth.login_state(login["challenge_id"])["status"] == "awaiting_profile"

    # Terms acceptance is mandatory.
    with pytest.raises(account_auth.AccountAuthError):
        account_auth.complete_profile(login["challenge_id"], {
            "first_name": "Ada", "last_name": "Lovelace", "email": "ADA@example.com",
        }, api_call=api, owner_chat_id="999")

    state = account_auth.complete_profile(login["challenge_id"], {
        "first_name": "Ada", "last_name": "Lovelace", "email": "ADA@example.com",
        "accept_terms": True,
    }, api_call=api, owner_chat_id="999")
    assert state["status"] == "login_approved"
    registered = account_auth._user(account_auth._read_doc(), 42)
    assert registered["status"] == "active"
    assert registered["role"] == "full_control"
    assert registered["ux_mode"] == "professional"
    assert subscriptions.trial_access_for_user(42)["state"] == "active"

    result = account_auth.create_session_for_challenge(
        login["challenge_id"], ip="127.0.0.1", user_agent="pytest",
    )
    assert result["status"] == "authenticated"
    context = account_auth.authenticate_session(result["session_token"])
    assert context and context["user_id"] == 42
    assert account_auth.verify_csrf(context, result["csrf_token"])
    assert account_auth._user(account_auth._read_doc(), 42)["terms_accepted_at_utc"]

    raw = account_auth._store_path().read_bytes()
    assert b"ADA@example.com" not in raw
    assert b"15551234567" not in raw


def test_contact_must_belong_to_sender(auth_store) -> None:
    account_auth.ensure_owner(999)
    login = account_auth.start_login(bot_username="StratForge_bot", ip="127.0.0.1")
    _calls, api = _api_recorder()
    code = login["bot_url"].split("login_", 1)[1]
    account_auth.process_update({"message": {
        "text": f"/start login_{code}", "from": {"id": 42},
        "chat": {"id": 42, "type": "private"},
    }}, api_call=api, owner_chat_id="999")
    account_auth.process_update({"message": {
        "contact": {"user_id": 7, "phone_number": "+15551234567"},
        "from": {"id": 42}, "chat": {"id": 42, "type": "private"},
    }}, api_call=api, owner_chat_id="999")
    assert account_auth.login_state(login["challenge_id"])["status"] == "identity_mismatch"


def test_owner_contact_refresh_ignores_stale_phone_hash(auth_store) -> None:
    owner = account_auth.ensure_owner(999)
    doc = account_auth._read_doc()
    row = account_auth._user(doc, 999)
    row.update({
        "first_name": "Owner",
        "last_name": "Tester",
        "email": "owner@example.test",
        "phone_hash": account_auth._phone_hash("15550000000"),
    })
    account_auth._write_doc(doc)
    login = account_auth.start_login(bot_username="StratForge_bot", ip="127.0.0.1")
    calls, api = _api_recorder()

    assert owner and owner["is_owner"] is True
    assert account_auth.process_update({"message": {
        "text": f"/start login_{login['code']}",
        "from": {"id": 999, "first_name": "Owner", "username": "owner"},
        "chat": {"id": 999, "type": "private"},
    }}, api_call=api, owner_chat_id="999")
    assert account_auth.process_update({"message": {
        "contact": {"user_id": 999, "phone_number": "+15551234567"},
        "from": {"id": 999}, "chat": {"id": 999, "type": "private"},
    }}, api_call=api, owner_chat_id="999")

    assert account_auth.login_state(login["challenge_id"])["status"] == "login_approved"
    refreshed = account_auth._user(account_auth._read_doc(), 999)
    assert refreshed["phone_hash"] == account_auth._phone_hash("15551234567")
    texts = [payload.get("text", "") for method, payload in calls if method == "sendMessage"]
    assert not any("Номер не совпадает" in text for text in texts)


def test_manual_login_code_recovers_when_start_parameter_is_lost(auth_store) -> None:
    account_auth.ensure_owner(999)
    login = account_auth.start_login(bot_username="StratForge_bot", ip="127.0.0.1")
    calls, api = _api_recorder()

    assert login["code"] and login["manual_command"] == f"/login {login['code']}"
    assert account_auth.process_update({"message": {
        "text": f"/login {login['code']}",
        "from": {"id": 42, "first_name": "Ada", "username": "ada"},
        "chat": {"id": 42, "type": "private"},
    }}, api_call=api, owner_chat_id="999")

    # One tap replaces the mandatory contact request: the bot offers a
    # single inline confirmation button, not a contact keyboard.
    assert account_auth.login_state(login["challenge_id"])["status"] == "awaiting_confirm"
    assert any((payload.get("reply_markup") or {}).get("inline_keyboard") for _method, payload in calls)
    assert not any((payload.get("reply_markup") or {}).get("keyboard") for _method, payload in calls)


def test_canary_login_uses_environment_payload_and_marker(auth_store, monkeypatch) -> None:
    monkeypatch.setattr(
        account_auth.runtime_env,
        "deployment_environment",
        lambda: account_auth.runtime_env.CANARY,
    )
    account_auth.ensure_owner(999)
    login = account_auth.start_login(bot_username="StratForge_bot", ip="127.0.0.1")
    calls, api = _api_recorder()

    assert f"?start=canary_login_{login['code']}" in login["bot_url"]
    assert login["manual_command"] == f"/login [CANARY] {login['code']}"
    assert account_auth.process_update({"message": {
        "text": f"/start canary_login_{login['code']}",
        "from": {"id": 42, "first_name": "Ada", "username": "ada"},
        "chat": {"id": 42, "type": "private"},
    }}, api_call=api, owner_chat_id="999")

    assert account_auth.login_state(login["challenge_id"])["status"] == "awaiting_confirm"
    texts = [payload.get("text", "") for method, payload in calls if method == "sendMessage"]
    assert any(text.startswith("[CANARY] ") for text in texts)


def test_plain_start_gets_actionable_login_help(auth_store) -> None:
    account_auth.ensure_owner(999)
    calls, api = _api_recorder()

    assert account_auth.process_update({"message": {
        "text": "/start",
        "from": {"id": 42, "first_name": "Ada"},
        "chat": {"id": 42, "type": "private"},
    }}, api_call=api, owner_chat_id="999")

    texts = [payload.get("text", "") for method, payload in calls if method == "sendMessage"]
    assert any("/login" in text and "одноразовая" in text for text in texts)


def test_revocation_invalidates_all_sessions(auth_store) -> None:
    now = time.time()
    token = "x" * 64
    csrf = "y" * 48
    account_auth._write_doc({
        "version": 1,
        "users": [
            {"user_id": 999, "first_name": "Owner", "last_name": "One", "email": "owner@example.com", "role": "owner", "status": "active", "is_owner": True},
            {"user_id": 42, "first_name": "User", "last_name": "Two", "email": "user@example.com", "role": "full_control", "status": "active", "is_owner": False},
        ],
        "challenges": [],
        "sessions": [{"user_id": 42, "token_hash": hashlib.sha256(token.encode()).hexdigest(), "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(), "csrf_token": csrf, "expires_at": now + 3600, "revoked": False}],
    })
    assert account_auth.authenticate_session(token)
    account_auth.update_user(999, 42, revoke=True)
    assert account_auth.authenticate_session(token) is None


def test_owner_can_revoke_one_session_or_device_without_deleting_user(auth_store) -> None:
    now = time.time()
    token_a = "a" * 64
    token_b = "b" * 64
    csrf = "c" * 48
    account_auth._write_doc({
        "version": 1,
        "users": [
            {"user_id": 999, "first_name": "Owner", "last_name": "One", "email": "owner@example.com", "role": "owner", "status": "active", "is_owner": True},
            {"user_id": 42, "first_name": "User", "last_name": "Two", "email": "user@example.com", "role": "full_control", "status": "active", "is_owner": False},
        ],
        "challenges": [],
        "sessions": [
            {"session_id": "sess_A", "user_id": 42, "token_hash": hashlib.sha256(token_a.encode()).hexdigest(), "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(), "csrf_token": csrf, "expires_at": now + 3600, "created_at_utc": "2026-07-10T00:00:00Z", "device_id": "pc1", "revoked": False},
            {"session_id": "sess_B", "user_id": 42, "token_hash": hashlib.sha256(token_b.encode()).hexdigest(), "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(), "csrf_token": csrf, "expires_at": now + 3600, "created_at_utc": "2026-07-10T00:01:00Z", "device_id": "pc2", "revoked": False},
        ],
    })

    detail = account_auth.user_detail(999, 42)
    assert [row["session_id"] for row in detail["user"]["active_sessions"]] == ["sess_B", "sess_A"]

    out = account_auth.revoke_user_sessions(999, 42, session_id="sess_A")
    assert out["revoked"] == 1
    assert account_auth.authenticate_session(token_a) is None
    assert account_auth.authenticate_session(token_b) is not None

    out = account_auth.revoke_user_sessions(999, 42, device_id="pc2")
    assert out["revoked"] == 1
    assert account_auth.authenticate_session(token_b) is None
    assert account_auth.find_active_user(42) is not None


def test_owner_can_list_users_before_profile_is_completed(auth_store) -> None:
    account_auth.ensure_owner(999)

    result = account_auth.list_users(999)

    assert result["users"][0]["user_id"] == 999
    assert result["users"][0]["is_owner"] is True


def test_server_requires_session_and_csrf_even_on_localhost(auth_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    account_auth.set_auth_required(True)
    token = "s" * 64
    csrf = "c" * 48
    account_auth._write_doc({
        "version": 1,
        "users": [{"user_id": 999, "first_name": "Owner", "last_name": "One", "email": "owner@example.com", "role": "owner", "status": "active", "is_owner": True}],
        "challenges": [],
        "sessions": [{"user_id": 999, "token_hash": hashlib.sha256(token.encode()).hexdigest(), "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(), "csrf_token": csrf, "expires_at": time.time() + 3600, "revoked": False}],
    })
    srv = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True); thread.start()
    base = f"http://{srv.server_address[0]}:{srv.server_address[1]}"
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(base + "/api/health", timeout=5)
        assert exc.value.code == 401

        req = urllib.request.Request(base + "/api/health", headers={"Cookie": f"{account_auth.SESSION_COOKIE}={token}"})
        with urllib.request.urlopen(req, timeout=5) as response:
            assert response.status == 200

        no_csrf = urllib.request.Request(base + "/api/auth/logout", data=b"{}", method="POST", headers={
            "Content-Type": "application/json", "Cookie": f"{account_auth.SESSION_COOKIE}={token}",
            "Origin": base,
        })
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(no_csrf, timeout=5)
        assert exc.value.code == 403

        logout = urllib.request.Request(base + "/api/auth/logout", data=b"{}", method="POST", headers={
            "Content-Type": "application/json", "Cookie": f"{account_auth.SESSION_COOKIE}={token}",
            "Origin": base, "X-CSRF-Token": csrf,
        })
        with urllib.request.urlopen(logout, timeout=5) as response:
            assert response.status == 200
    finally:
        srv.shutdown(); srv.server_close()


def test_development_localhost_stale_cookie_falls_back_to_owner(auth_store, monkeypatch) -> None:
    monkeypatch.setenv("NTA_APP_ENV", "development")
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    account_auth.set_auth_required(True)
    account_auth._write_doc({
        "version": 1,
        "users": [{
            "user_id": 999, "first_name": "Owner", "last_name": "One",
            "email": "owner@example.com", "role": "owner",
            "status": "active", "is_owner": True, "ux_mode": "professional",
        }],
        "challenges": [],
        "sessions": [],
    })
    stale = "x" * 64
    srv = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True); thread.start()
    base = f"http://{srv.server_address[0]}:{srv.server_address[1]}"
    try:
        headers = {"Origin": base, "Cookie": f"{account_auth.SESSION_COOKIE}={stale}"}
        req = urllib.request.Request(base + "/api/auth/status", headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            status = json.loads(response.read().decode("utf-8"))
        assert status["authenticated"] is True
        assert status["source"] == "local"
        assert status["is_owner"] is True
        assert status["admin_capabilities"]["admin.view"] is True

        req = urllib.request.Request(base + "/api/health", headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            assert response.status == 200
    finally:
        srv.shutdown(); srv.server_close()


def test_server_rate_limits_authenticated_api_by_user_and_ip(auth_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    account_auth.set_auth_required(True)
    token = "r" * 64
    csrf = "c" * 48
    account_auth._write_doc({
        "version": 1,
        "users": [{"user_id": 999, "first_name": "Owner", "last_name": "One", "email": "owner@example.com", "role": "owner", "status": "active", "is_owner": True}],
        "challenges": [],
        "sessions": [{"user_id": 999, "token_hash": hashlib.sha256(token.encode()).hexdigest(), "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(), "csrf_token": csrf, "expires_at": time.time() + 3600, "revoked": False}],
    })
    with server_mod._API_RATE_LOCK:
        server_mod._API_RATE.clear()
    original = dict(server_mod._API_RATE_LIMITS)
    server_mod._API_RATE_LIMITS["read"] = 2
    srv = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True); thread.start()
    base = f"http://{srv.server_address[0]}:{srv.server_address[1]}"
    try:
        for _ in range(2):
            req = urllib.request.Request(base + "/api/health", headers={"Cookie": f"{account_auth.SESSION_COOKIE}={token}"})
            with urllib.request.urlopen(req, timeout=5) as response:
                assert response.status == 200
        req = urllib.request.Request(base + "/api/health", headers={"Cookie": f"{account_auth.SESSION_COOKIE}={token}"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 429
    finally:
        server_mod._API_RATE_LIMITS.clear()
        server_mod._API_RATE_LIMITS.update(original)
        with server_mod._API_RATE_LOCK:
            server_mod._API_RATE.clear()
        srv.shutdown(); srv.server_close()


def test_authenticated_auth_reads_use_read_bucket_while_mutations_stay_tight() -> None:
    handler = object.__new__(server_mod.Handler)
    assert handler._api_action_class("/api/auth/me", "GET") == "read"
    assert handler._api_action_class("/api/auth/session", "HEAD") == "read"
    assert handler._api_action_class("/api/ops/runtime/bars/batch", "POST") == "read"
    assert handler._api_action_class("/api/auth/logout", "POST") == "auth"


def _seed_owner_and_user(auth_store) -> None:
    account_auth._write_doc({
        "version": 1,
        "users": [
            {"user_id": 999, "first_name": "Owner", "last_name": "One", "email": "owner@example.com", "role": "owner", "status": "active", "is_owner": True},
            {"user_id": 42, "first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com", "role": "read_only", "status": "active", "is_owner": False},
        ],
        "challenges": [],
        "sessions": [],
    })


def test_block_and_unblock_user(auth_store) -> None:
    _seed_owner_and_user(auth_store)
    account_auth.set_user_status(999, 42, "blocked")
    assert account_auth.find_active_user(42) is None  # blocked account is inactive
    blocked = next(u for u in account_auth.list_users(999)["users"] if u["user_id"] == 42)
    assert blocked["status"] == "blocked" and blocked["blocked_at_utc"]

    account_auth.set_user_status(999, 42, "active")
    assert account_auth.find_active_user(42) is not None


def test_block_requires_owner_and_spares_owner(auth_store) -> None:
    _seed_owner_and_user(auth_store)
    with pytest.raises(account_auth.AccountAuthError) as exc:
        account_auth.set_user_status(42, 999, "blocked")  # non-owner actor
    assert exc.value.status == 403
    with pytest.raises(account_auth.AccountAuthError):
        account_auth.set_user_status(999, 999, "blocked")  # cannot block the owner


def test_delete_user_removes_row(auth_store) -> None:
    _seed_owner_and_user(auth_store)
    account_auth.delete_user(999, 42)
    ids = [u["user_id"] for u in account_auth.list_users(999)["users"]]
    assert 42 not in ids and 999 in ids
    with pytest.raises(account_auth.AccountAuthError):
        account_auth.delete_user(999, 999)  # owner is protected


def test_set_user_permission_override(auth_store) -> None:
    _seed_owner_and_user(auth_store)
    account_auth.set_user_permission(999, 42, "ai_lab", True)
    detail = account_auth.user_detail(999, 42)
    assert detail["user"]["permission_overrides"]["ai_lab"] is True
    # Clearing the override removes it.
    account_auth.set_user_permission(999, 42, "ai_lab", None)
    detail = account_auth.user_detail(999, 42)
    assert "ai_lab" not in detail["user"].get("permission_overrides", {})
    with pytest.raises(account_auth.AccountAuthError):
        account_auth.set_user_permission(999, 42, "not_a_capability", True)


def test_owner_grants_expiring_admin_capability_and_staff_cannot_delegate(auth_store) -> None:
    _seed_owner_and_user(auth_store)
    account_auth.set_user_admin_permission(
        999,
        42,
        "users.manage",
        True,
        expires_at_utc="2099-01-01T00:00:00Z",
    )
    detail = account_auth.user_detail(42, 42)
    grant = detail["user"]["admin_permission_grants"]["users.manage"]
    assert grant["enabled"] is True
    assert grant["expires_at_utc"] == "2099-01-01T00:00:00Z"
    assert permissions.resolve_admin_capabilities(detail["user"])["users.manage"] is True
    assert {row["user_id"] for row in account_auth.list_users(42)["users"]} == {42, 999}

    with pytest.raises(account_auth.AccountAuthError) as exc:
        account_auth.set_user_admin_permission(42, 42, "admin.view", True)
    assert exc.value.status == 403

    account_auth.set_user_admin_permission(999, 42, "users.manage", False)
    with pytest.raises(account_auth.AccountAuthError) as exc:
        account_auth.list_users(42)
    assert exc.value.status == 403


def test_admin_grant_rejects_invalid_enabled_and_expired_timestamp(auth_store) -> None:
    _seed_owner_and_user(auth_store)
    with pytest.raises(account_auth.AccountAuthError):
        account_auth.set_user_admin_permission(999, 42, "admin.view", "true")
    with pytest.raises(account_auth.AccountAuthError):
        account_auth.set_user_admin_permission(
            999, 42, "admin.view", True,
            expires_at_utc="2020-01-01T00:00:00Z",
        )


def test_record_login_history_and_throttle(auth_store) -> None:
    _seed_owner_and_user(auth_store)
    account_auth.record_login(42, source="telegram_mini_app", ip="203.0.113.9",
                              user_agent="TelegramBot", throttle_sec=0)
    detail = account_auth.user_detail(999, 42)
    hist = detail["user"]["login_history"]
    assert hist and hist[0]["source"] == "telegram_mini_app"
    assert hist[0]["ip"] == "203.0.•.•"  # masked
    # A throttled repeat does not add a second row.
    account_auth.record_login(42, source="telegram_mini_app", throttle_sec=3600)
    assert len(account_auth.user_detail(999, 42)["user"]["login_history"]) == 1


def test_auth_required_forced_on_when_remote_enabled(auth_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    cfg = auth_store / "data" / "integrations" / "telegram.remote-access.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    # Public Mini App exposed but desktop flag reset to false -> auth STILL required.
    cfg.write_text(json.dumps({"remote_enabled": True, "desktop_auth_required": False}), encoding="utf-8")
    assert account_auth.auth_required() is True
    # No remote access configured -> still defaults to required.
    cfg.write_text(json.dumps({"remote_enabled": False}), encoding="utf-8")
    assert account_auth.auth_required() is True
    # The test bypass is the only way off.
    monkeypatch.setenv("NTA_TEST_BYPASS_AUTH", "1")
    assert account_auth.auth_required() is False


def test_local_owner_keeps_professional_mode_and_full_capabilities(monkeypatch) -> None:
    monkeypatch.setattr(
        server_mod.workspaces, "context_for_user",
        lambda *args, **kwargs: {"workspaces": [], "active_workspace": {}, "active_membership": {}},
    )
    monkeypatch.setattr(
        server_mod.permissions, "resolve_for_user_id",
        lambda *args, **kwargs: {"capabilities": {}, "ux_mode": ""},
    )
    handler = server_mod.Handler.__new__(server_mod.Handler)
    context = handler._decorate_workspace_context({
        "user_id": 0, "is_owner": True, "role": "owner", "user": {},
    })
    assert context["active_workspace"]["workspace_id"] == "ws_local_owner"
    assert context["ux_mode"] == "professional"
    assert context["capabilities"]
    assert all(context["capabilities"].values())
    payload = handler._augment_permissions(context, {
        "authenticated": True, "is_owner": True, "user": {},
    })
    assert payload["ux_mode"] == "professional"
    assert payload["ux_pending"] is False
    assert all(payload["capabilities"].values())


def test_register_via_telegram_activates_full_trial(auth_store) -> None:
    account_auth.ensure_owner(999)
    calls, api = _api_recorder()
    out = account_auth.register_via_telegram(
        {"id": 42, "first_name": "Ada", "username": "ada"},
        email="ada@example.com", accept_terms=True, api_call=api, owner_chat_id="999")
    assert out["status"] == "active" and out["authenticated"] is True
    assert uuid.UUID(out["user"]["id"]) and out["user"]["status"] == "active"
    assert out["challenge_id"] == ""
    registered = account_auth.find_active_user(42)
    assert registered is not None
    assert registered["role"] == "full_control"
    assert registered["ux_mode"] == "professional"
    assert subscriptions.trial_access_for_user(42)["state"] == "active"

    # Terms acceptance is mandatory.
    with pytest.raises(account_auth.AccountAuthError):
        account_auth.register_via_telegram({"id": 43}, email="b@e.com", accept_terms=False, owner_chat_id="999")

    # The owner is recognised from initData and activates immediately.
    owner = account_auth.register_via_telegram(
        {"id": 999, "first_name": "Own"}, email="o@e.com", accept_terms=True, owner_chat_id="999")
    assert owner["authenticated"] is True and owner["user"]["is_owner"] is True

    # A blocked user cannot silently re-register.
    account_auth.set_user_status(999, 42, "blocked")
    with pytest.raises(account_auth.AccountAuthError) as exc:
        account_auth.register_via_telegram({"id": 42}, email="ada@example.com", accept_terms=True, owner_chat_id="999")
    assert exc.value.status == 403


def test_existing_account_email_is_not_overwritten_by_second_device(auth_store, monkeypatch) -> None:
    account_auth.ensure_owner(999)
    monkeypatch.setenv("NTA_DEVICE_LABEL", "PC1")
    account_auth.register_via_telegram(
        {"id": 42, "first_name": "Ada", "username": "ada"},
        email="pc1@example.com", accept_terms=True, owner_chat_id="999")
    # Activate pending account so a second device can re-register as returning user.
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        row = account_auth._user(doc, 42)
        row["status"] = "active"
        row["approved_at_utc"] = account_auth._now_iso()
        account_auth._write_doc(doc)
    monkeypatch.setenv("NTA_DEVICE_LABEL", "PC2")
    account_auth.register_via_telegram(
        {"id": 42, "first_name": "Ada", "username": "ada"},
        email="pc2@example.com", accept_terms=True, owner_chat_id="999")

    user = account_auth._user(account_auth._read_doc(), 42)
    assert user["email"] == "pc1@example.com"
    # Devices are no longer a second list on the user document; the account
    # keeps only the last-login metadata, and the e-mail of record is the one
    # the account registered with.
    assert user.get("devices") in (None, [])
    assert user["last_login_email"] == "pc2@example.com"


def test_foreign_dpapi_account_store_is_quarantined(auth_store, monkeypatch) -> None:
    path = account_auth._store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(account_auth._MAGIC + base64.b64encode(b"foreign-dpapi"))

    def fail_unprotect(_value):
        raise secure_store.SecureStoreError("foreign DPAPI")

    monkeypatch.setattr(secure_store, "_unprotect", fail_unprotect)

    doc = account_auth._read_doc()

    assert doc == account_auth._default_doc()
    assert not path.exists()
    assert list(path.parent.glob("accounts.dpapi.unreadable-*.bak"))
    assert (path.parent / "accounts.dpapi.recovery.json").is_file()


def test_uuid_backfill_keeps_legacy_account_and_session_references(auth_store) -> None:
    token = "x" * 64
    legacy = {
        "version": 2,
        "users": [{
            "user_id": 42,
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
            "role": "read_only",
            "status": "active",
            "is_owner": False,
            "created_at_utc": "2026-08-01T00:00:00Z",
        }],
        "challenges": [{"challenge_id": "legacy-challenge", "user_id": 42}],
        "sessions": [{
            "session_id": "sess_legacy",
            "user_id": 42,
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "expires_at": time.time() + 3600,
            "revoked": False,
        }],
    }
    path = account_auth._store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    encrypted = secure_store._protect(json.dumps(legacy).encode("utf-8"))
    path.write_bytes(account_auth._MAGIC + base64.b64encode(encrypted))

    migrated = account_auth._read_doc()
    user = migrated["users"][0]
    user_uuid = str(uuid.UUID(str(user["user_uuid"])))

    assert user["user_id"] == 42
    assert user["legacy_user_id"] == 42
    assert user["first_name"] == "Ada"
    assert user["last_name"] == "Lovelace"
    assert migrated["sessions"][0]["user_id"] == 42
    assert migrated["sessions"][0]["user_uuid"] == user_uuid
    assert migrated["challenges"][0]["user_uuid"] == user_uuid
    assert [(row["provider"], row["provider_subject"]) for row in migrated["auth_identities"]] == [
        ("telegram", "42"),
    ]
    assert account_auth.authenticate_session(token)["user_uuid"] == user_uuid
    assert account_auth._read_doc() == migrated
    assert path.with_name(path.name + ".identity-v2-backup").is_file()


def test_phase3_identity_expand_migration_is_non_destructive() -> None:
    migrations = {row["version"]: row for row in MigrationRunner.migrations()}

    assert 5 in migrations
    sql = str(migrations[5]["sql"]).lower()
    assert "drop " not in sql
    assert "create table if not exists sf_auth_identities" in sql
    assert "on conflict (provider, provider_subject)" in sql
    assert "update sf_users" in sql
    for table in (
        "sf_auth_sessions",
        "sf_workspaces",
        "sf_workspace_memberships",
        "sf_connector_installations",
        "sf_entitlements",
        "sf_audit_events",
    ):
        assert f"alter table {table}" in sql
    assert "'sf_audit_events', 'sf_artifacts'" in sql
    assert "sf_identity_dual_write_' || table_name" in sql
    assert "sf_identity_' || table_name || '_user_uuid_fk" in sql


def test_phase3_auth_storage_sync_dual_writes_uuid_identity() -> None:
    user_uuid = str(uuid.uuid4())
    identity_id = str(uuid.uuid4())

    class RecordingResult:
        def __init__(self, row=None) -> None:
            self.row = row

        def fetchone(self):
            return self.row

    class RecordingConnection:
        def __init__(self) -> None:
            self.calls = []

        def execute(self, statement, parameters=()):
            normalized = " ".join(str(statement).split())
            values = tuple(parameters or ())
            self.calls.append((normalized, values))
            if "INSERT INTO sf_auth_identities" in normalized:
                return RecordingResult({"user_uuid": user_uuid})
            return RecordingResult()

    document = {
        "users": [{
            "user_id": 42,
            "user_uuid": user_uuid,
            "status": "active",
            "is_owner": False,
        }],
        "auth_identities": [{
            "identity_id": identity_id,
            "user_uuid": user_uuid,
            "legacy_user_id": 42,
            "provider": "telegram",
            "provider_subject": "42",
            "linked_at_utc": "2026-08-02T00:00:00Z",
            "verified_at_utc": "2026-08-02T00:00:00Z",
            "metadata": {},
        }],
        "challenges": [{"challenge_id": "challenge_phase3", "user_id": 42, "user_uuid": user_uuid}],
        "sessions": [{
            "session_id": "sess_phase3",
            "user_id": 42,
            "user_uuid": user_uuid,
            "token_hash": hashlib.sha256(b"phase3").hexdigest(),
            "expires_at": time.time() + 3600,
        }],
    }
    connection = RecordingConnection()
    repository = object.__new__(DocumentRepository)

    repository._sync_auth(connection, document)

    user_insert = next(statement for statement in connection.calls if "INSERT INTO sf_users" in statement[0])
    identity_insert = next(statement for statement in connection.calls if "INSERT INTO sf_auth_identities" in statement[0])
    challenge_insert = next(statement for statement in connection.calls if "INSERT INTO sf_auth_challenges" in statement[0])
    session_insert = next(statement for statement in connection.calls if "INSERT INTO sf_auth_sessions" in statement[0])
    assert "user_uuid" in user_insert[0] and user_uuid in user_insert[1]
    assert "user_uuid" in identity_insert[0] and user_uuid in identity_insert[1]
    assert "user_uuid" in challenge_insert[0] and user_uuid in challenge_insert[1]
    assert "user_uuid" in session_insert[0] and user_uuid in session_insert[1]


def test_auth_document_reuses_mirror_uuids_instead_of_minting(auth_store) -> None:
    """Incomplete SQL UUID backfill must not mint colliding provider identities."""
    canonical = str(uuid.uuid4())
    identity_id = str(uuid.uuid4())

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return list(self._rows)

        def fetchone(self):
            return self._rows[0] if self._rows else None

    class FakeConnection:
        def execute(self, statement, parameters=()):
            sql = " ".join(str(statement).split())
            if "FROM sf_users" in sql:
                return FakeResult([{"user_id": 42, "user_uuid": canonical}])
            if "FROM sf_auth_identities" in sql:
                return FakeResult([{
                    "identity_id": identity_id,
                    "user_uuid": canonical,
                    "legacy_user_id": 42,
                    "provider": "telegram",
                    "provider_subject": "42",
                    "normalized_email": None,
                    "verified_at": None,
                    "linked_at": None,
                    "last_used_at": None,
                    "revoked_at": None,
                    "document": {"source": "phase3_backfill"},
                }])
            return FakeResult([])

    document = {
        "version": 2,
        "users": [{"user_id": 42, "status": "active", "is_owner": True}],
        "auth_identities": [],
        "challenges": [{"challenge_id": "login_challenge_1", "status": "created"}],
        "sessions": [],
    }
    DocumentRepository._reconcile_auth_document(
        object.__new__(DocumentRepository), FakeConnection(), document,
    )
    assert document["users"][0]["user_uuid"] == canonical
    assert document["users"][0]["legacy_user_id"] == 42
    assert len(document["auth_identities"]) == 1
    identity = document["auth_identities"][0]
    assert identity["identity_id"] == identity_id
    assert identity["user_uuid"] == canonical
    assert identity["provider"] == "telegram"
    assert identity["provider_subject"] == "42"


def test_phase3_auth_storage_sync_soft_revokes_unlinked_provider_identity(auth_store) -> None:
    user_uuid = str(uuid.uuid4())
    telegram_identity_id = str(uuid.uuid4())
    google_identity_id = str(uuid.uuid4())

    class RecordingResult:
        def fetchone(self):
            return {"user_uuid": user_uuid}

    class RecordingConnection:
        def __init__(self) -> None:
            self.calls = []

        def execute(self, statement, parameters=()):
            self.calls.append((" ".join(str(statement).split()), tuple(parameters or ())))
            return RecordingResult()

    account_auth._write_doc({
        "version": 3,
        "users": [
            {
                "user_id": 999, "legacy_user_id": 999,
                "user_uuid": str(uuid.uuid4()), "first_name": "Owner",
                "status": "active", "is_owner": True,
            },
            {
                "user_id": 42, "legacy_user_id": 42, "user_uuid": user_uuid,
                "first_name": "Ada", "status": "active", "is_owner": False,
                "google_sub": "google-ada",
            },
        ],
        "auth_identities": [
            {
                "identity_id": telegram_identity_id, "user_uuid": user_uuid,
                "legacy_user_id": 42, "provider": "telegram", "provider_subject": "42",
                "linked_at_utc": "2026-08-02T00:00:00Z", "metadata": {},
            },
            {
                "identity_id": google_identity_id, "user_uuid": user_uuid,
                "legacy_user_id": 42, "provider": "google", "provider_subject": "google-ada",
                "linked_at_utc": "2026-08-02T00:00:00Z", "metadata": {},
            },
        ],
        "challenges": [], "sessions": [],
    })
    account_auth.unlink_google_identity(999, 42)
    connection = RecordingConnection()

    object.__new__(DocumentRepository)._sync_auth(connection, account_auth._read_doc())

    revoke = next(
        (statement, values)
        for statement, values in connection.calls
        if "UPDATE sf_auth_identities" in statement and "revoked_at" in statement
    )
    assert "NOT (identity_id = ANY(%s))" in revoke[0]
    assert 42 in revoke[1][0]
    assert telegram_identity_id in revoke[1][1]
    assert google_identity_id not in revoke[1][1]


def test_phase3_public_user_uses_uuid_without_legacy_identity(auth_store) -> None:
    _seed_owner_and_user(auth_store)
    document = account_auth._read_doc()
    user = account_auth._user(document, 42)
    assert user is not None

    public = account_auth._public_user(user, include_contact=True)
    admin = next(row for row in account_auth.list_users(999)["users"] if row["user_id"] == 42)

    assert str(uuid.UUID(public["id"])) == public["id"]
    assert "user_id" not in public
    assert "legacy_user_id" not in public
    assert "telegram_user_id" not in public
    assert admin["user_id"] == 42
    assert admin["legacy_user_id"] == 42


def test_phase3_email_otp_login_activates_trial_then_reuses_identity(auth_store, monkeypatch) -> None:
    monkeypatch.setattr(account_auth, "email_auth_status", lambda: {"available": True})
    account_auth.ensure_owner(999)
    calls, api = _api_recorder()

    started = account_auth.start_email_auth("ada@example.com", ip="127.0.0.1")
    first_login = account_auth.verify_email_auth(
        started["challenge_id"], code=started["test_code"],
        profile={"first_name": "Ada", "last_name": "Lovelace", "accept_terms": True},
        ip="127.0.0.1", user_agent="pytest", api_call=api, owner_chat_id="999",
    )
    assert first_login["status"] == "authenticated"
    user_uuid = first_login["user"]["id"]

    returning = account_auth.start_email_auth("ADA@example.com", ip="127.0.0.1")
    authenticated = account_auth.verify_email_auth(
        returning["challenge_id"], code=returning["test_code"],
        ip="127.0.0.1", user_agent="pytest",
    )
    assert authenticated["status"] == "authenticated"
    assert authenticated["user"]["id"] == user_uuid
    assert account_auth.authenticate_session(authenticated["session_token"])["user_uuid"] == user_uuid


def test_phase3_google_login_activates_trial_then_reuses_identity(auth_store) -> None:
    account_auth.ensure_owner(999)
    calls, api = _api_recorder()

    first_login = account_auth.login_via_google_identity(
        google_sub="google-ada", google_email="ada@gmail.example", google_name="Ada Lovelace",
        email_verified=True, accept_terms=True, ip="127.0.0.1", user_agent="pytest",
        api_call=api, owner_chat_id="999",
    )
    assert first_login["status"] == "authenticated"
    user_uuid = first_login["user"]["id"]

    authenticated = account_auth.login_via_google_identity(
        google_sub="google-ada", google_email="ada@gmail.example", google_name="Ada Lovelace",
        email_verified=True, accept_terms=False, ip="127.0.0.1", user_agent="pytest",
    )
    assert authenticated["status"] == "authenticated"
    assert authenticated["user"]["id"] == user_uuid
    assert {row["provider"] for row in authenticated["user"]["linked_providers"]} == {"google"}


def test_phase3_same_email_does_not_merge_telegram_and_email_accounts(auth_store, monkeypatch) -> None:
    monkeypatch.setattr(account_auth, "email_auth_status", lambda: {"available": True})
    account_auth.ensure_owner(999)
    account_auth.register_via_telegram(
        {"id": 42, "first_name": "Ada", "username": "ada"},
        email="shared@example.com", accept_terms=True, owner_chat_id="999",
    )
    telegram_user = account_auth._user(account_auth._read_doc(), 42)
    assert telegram_user is not None

    started = account_auth.start_email_auth("shared@example.com", ip="127.0.0.1")
    email_login = account_auth.verify_email_auth(
        started["challenge_id"], code=started["test_code"],
        profile={"first_name": "Ada", "last_name": "Email", "accept_terms": True},
        ip="127.0.0.1", user_agent="pytest",
    )

    assert email_login["status"] == "authenticated"
    assert email_login["user"]["id"] != telegram_user["user_uuid"]
    identities = account_auth._read_doc()["auth_identities"]
    assert {(row["provider"], row["user_uuid"]) for row in identities if row["provider"] in {"telegram", "email"}} >= {
        ("telegram", telegram_user["user_uuid"]),
        ("email", email_login["user"]["id"]),
    }


def test_phase3_google_link_keeps_account_uuid_and_rejects_owned_subject(auth_store) -> None:
    _seed_owner_and_user(auth_store)
    user = account_auth._user(account_auth._read_doc(), 42)
    assert user is not None
    user_uuid = user["user_uuid"]
    session = account_auth.create_session_for_user(
        42, ip="127.0.0.1", user_agent="pytest", require_google=False,
    )

    linked = account_auth.link_google_identity(
        42, google_sub="google-ada", google_email="ada@gmail.example", google_name="Ada Lovelace",
    )

    assert linked["user"]["id"] == user_uuid
    assert account_auth.authenticate_session(session["session_token"])["user_uuid"] == user_uuid
    assert {row["provider"] for row in linked["user"]["linked_providers"]} == {"google", "telegram"}
    with pytest.raises(account_auth.AccountAuthError) as exc:
        account_auth.link_google_identity(
            999, google_sub="google-ada", google_email="owner@gmail.example",
        )
    assert exc.value.status == 409
    google_rows = [
        row for row in account_auth._read_doc()["auth_identities"]
        if row.get("provider") == "google" and row.get("provider_subject") == "google-ada"
    ]
    assert len(google_rows) == 1
    assert google_rows[0]["user_uuid"] == user_uuid


def test_phase3_email_link_otp_keeps_existing_account_uuid(auth_store, monkeypatch) -> None:
    monkeypatch.setattr(account_auth, "email_auth_status", lambda: {"available": True})
    _seed_owner_and_user(auth_store)
    user = account_auth._user(account_auth._read_doc(), 42)
    assert user is not None

    started = account_auth.start_email_auth(
        "ada.link@gmail.example", ip="127.0.0.1", purpose="link", actor_user_id=42,
    )
    linked = account_auth.verify_email_auth(
        started["challenge_id"], code=started["test_code"], ip="127.0.0.1",
        user_agent="pytest", actor_user_id=42,
    )

    assert linked["status"] == "linked"
    assert linked["user"]["id"] == user["user_uuid"]
    identities = account_auth._read_doc()["auth_identities"]
    assert any(
        row.get("provider") == "email"
        and row.get("provider_subject") == "ada.link@gmail.example"
        and row.get("user_uuid") == user["user_uuid"]
        for row in identities
    )


def test_phase3_unlink_google_rejects_last_usable_login(auth_store) -> None:
    _seed_owner_and_user(auth_store)
    pending = account_auth.login_via_google_identity(
        google_sub="google-only", google_email="only@gmail.example", google_name="Only Google",
        email_verified=True, accept_terms=True, ip="127.0.0.1", user_agent="pytest",
    )
    user_uuid = pending["user"]["id"]
    user = next(
        row for row in account_auth._read_doc()["users"] if row.get("user_uuid") == user_uuid
    )
    account_auth.set_user_status(999, user["user_id"], "active")

    with pytest.raises(account_auth.AccountAuthError) as exc:
        account_auth.unlink_google_identity(999, user["user_id"])

    assert exc.value.status == 409


def test_phase3_relinked_google_identity_clears_durable_revocation(auth_store) -> None:
    _seed_owner_and_user(auth_store)
    user = account_auth._user(account_auth._read_doc(), 42)
    assert user is not None
    account_auth.link_google_identity(
        42, google_sub="google-relink", google_email="relink@gmail.example",
    )
    account_auth.unlink_google_identity(999, 42)
    account_auth.link_google_identity(
        42, google_sub="google-relink", google_email="relink@gmail.example",
    )

    class RecordingResult:
        def __init__(self, row=None) -> None:
            self.row = row

        def fetchone(self):
            return self.row

    class RecordingConnection:
        def __init__(self) -> None:
            self.calls = []

        def execute(self, statement, parameters=()):
            normalized = " ".join(str(statement).split())
            values = tuple(parameters or ())
            self.calls.append((normalized, values))
            if "INSERT INTO sf_auth_identities" in normalized:
                return RecordingResult({"user_uuid": values[1]})
            return RecordingResult()

    connection = RecordingConnection()
    object.__new__(DocumentRepository)._sync_auth(connection, account_auth._read_doc())
    google_insert = next(
        (statement, values)
        for statement, values in connection.calls
        if "INSERT INTO sf_auth_identities" in statement and values[3] == "google"
    )

    assert "revoked_at=EXCLUDED.revoked_at" in google_insert[0]
    assert google_insert[1][-2] is None


def _resend_env(monkeypatch) -> None:
    monkeypatch.setenv("NTA_EMAIL_AUTH_PROVIDER", "resend")
    monkeypatch.setenv("NTA_RESEND_API_KEY", "re_test_key_value")
    monkeypatch.setenv("NTA_EMAIL_AUTH_FROM", "StratForge <auth@stratforges.com>")


def test_configured_resend_provider_replaces_the_development_test_backend(monkeypatch) -> None:
    _resend_env(monkeypatch)
    status = account_auth.email_auth_status()
    assert status["available"] is True
    assert status["operational"] is True
    assert status["provider"] == "resend"
    assert status["test_backend"] is False
    assert status["production_ready"] is True
    assert status["code"] == "ok"


def test_missing_resend_pieces_stay_unconfigured(monkeypatch) -> None:
    monkeypatch.setenv("NTA_EMAIL_AUTH_PROVIDER", "resend")
    monkeypatch.setenv("NTA_RESEND_API_KEY", "re_test_key_value")
    monkeypatch.delenv("NTA_EMAIL_AUTH_FROM", raising=False)
    monkeypatch.setattr(account_auth.runtime_env, "is_development", lambda: False)
    status = account_auth.email_auth_status()
    assert status["available"] is False
    assert status["provider"] == "resend"
    assert status["code"] == "transactional_provider_not_configured"


def test_live_email_delivery_hides_the_code_and_still_verifies(auth_store, monkeypatch) -> None:
    _resend_env(monkeypatch)
    account_auth.ensure_owner(999)
    sent: list = []

    def deliver(recipient, code, *, purpose, send=None):
        sent.append((recipient, code, purpose))
        return {"provider": "resend", "message_id": "msg_1"}

    monkeypatch.setattr(account_auth, "_deliver_email_code", deliver)
    started = account_auth.start_email_auth("grace@example.com", ip="127.0.0.1")

    assert started["delivery"] == "resend"
    # The one-time code must never travel back to the browser once a real
    # provider delivers it out of band.
    assert "test_code" not in started
    assert "test_magic_token" not in started
    assert sent and sent[0][0] == "grace@example.com"

    _calls, api = _api_recorder()
    delivered_code = sent[0][1]
    authenticated = account_auth.verify_email_auth(
        started["challenge_id"], code=delivered_code,
        profile={"first_name": "Grace", "last_name": "Hopper", "accept_terms": True},
        ip="127.0.0.1", user_agent="pytest", api_call=api, owner_chat_id="999",
    )
    assert authenticated["status"] == "authenticated"


def test_email_delivery_failure_is_a_service_error_without_provider_internals(
    auth_store, monkeypatch,
) -> None:
    _resend_env(monkeypatch)

    def explode(payload):
        raise RuntimeError("resend rejected key re_test_key_value")

    with pytest.raises(account_auth.AccountAuthError) as excinfo:
        account_auth._deliver_email_code(
            "ada@example.com", "123456", purpose="login", send=explode,
        )
    assert excinfo.value.status == 503
    assert "re_test_key_value" not in str(excinfo.value)


def test_delivered_message_carries_the_code_and_no_credentials(monkeypatch) -> None:
    _resend_env(monkeypatch)
    captured: dict = {}

    def send(payload):
        captured.update(payload)
        return {"id": "msg_2"}

    receipt = account_auth._deliver_email_code(
        "ada@example.com", "424242", purpose="login", send=send,
    )
    assert receipt == {"provider": "resend", "message_id": "msg_2"}
    assert captured["to"] == ["ada@example.com"]
    assert captured["from"] == "StratForge <auth@stratforges.com>"
    assert "424242" in captured["text"]
    assert "424242" in captured["html"]
    serialized = json.dumps(captured)
    assert "re_test_key_value" not in serialized


# ---------------------------------------------------------------------------
# Canonical owner contract: the owner is a person, not an environment variable.
# A deployment that cannot name its chat id must still resolve the canonical
# owner to full owner access, and must never greet them with a trial.
# ---------------------------------------------------------------------------

CANONICAL_UUID = "eb9d8e32-8db0-d590-9b35-ef1bd07ec61f"


def _canonical_owner_row(doc, uid=1647145559, *, is_owner=False, status="active"):
    """A stored account for the canonical human, optionally already demoted."""
    row = {
        "user_id": uid, "legacy_user_id": uid, "user_uuid": CANONICAL_UUID,
        "telegram_user_id": uid, "username": "owner",
        "first_name": "Owner", "last_name": "Tester",
        "email": "owner@example.test", "phone": "", "phone_hash": "",
        "role": "owner" if is_owner else "full_control",
        "status": status, "is_owner": is_owner,
        "primary_login_provider": "telegram",
        "created_at_utc": account_auth._now_iso(),
        "approved_at_utc": account_auth._now_iso(), "revoked_at_utc": "",
    }
    doc["users"].append(row)
    account_auth._link_identity_in_doc(
        doc, row, provider="telegram", subject=str(uid),
        verified_at_utc=account_auth._now_iso(), metadata={}, source="test",
        touch=False,
    )
    return row


def test_canonical_owner_resolves_without_a_configured_chat_id(auth_store, monkeypatch) -> None:
    # Exactly the Canary/Production shape: the canonical UUID is configured but
    # the chat id is not exported, which used to yield is_owner=False.
    monkeypatch.delenv("NTA_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv(account_auth.CANONICAL_OWNER_UUID_ENV, CANONICAL_UUID)
    doc = account_auth._read_doc()
    _canonical_owner_row(doc, is_owner=False)
    account_auth._write_doc(doc)

    doc = account_auth._read_doc()
    assert account_auth.owner_claim(
        doc, provider="telegram", subject=1647145559, user_id=1647145559,
        user=account_auth._user(doc, 1647145559),
    ) is True


def test_unknown_telegram_identity_is_never_promoted_to_owner(auth_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv(account_auth.CANONICAL_OWNER_UUID_ENV, CANONICAL_UUID)
    doc = account_auth._read_doc()
    _canonical_owner_row(doc, is_owner=True)
    account_auth._write_doc(doc)

    doc = account_auth._read_doc()
    assert account_auth.owner_claim(
        doc, provider="telegram", subject=515151, user_id=515151,
        user=account_auth._user(doc, 515151),
    ) is False


def test_missing_chat_id_never_demotes_a_stored_owner(auth_store, monkeypatch) -> None:
    # The store is authoritative: an unset variable is missing configuration,
    # not a decision to remove someone's ownership.
    monkeypatch.delenv("NTA_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv(account_auth.CANONICAL_OWNER_UUID_ENV, raising=False)
    doc = account_auth._read_doc()
    _canonical_owner_row(doc, is_owner=True)
    account_auth._write_doc(doc)

    doc = account_auth._read_doc()
    assert account_auth.owner_claim(
        doc, provider="telegram", subject=1647145559, user_id=1647145559,
        user=account_auth._user(doc, 1647145559),
    ) is True


def test_recognised_owner_keeps_the_canonical_uuid_instead_of_a_new_one(auth_store, monkeypatch) -> None:
    monkeypatch.setenv(account_auth.CANONICAL_OWNER_UUID_ENV, CANONICAL_UUID)
    assert account_auth.owner_user_uuid_for_new_row(True) == CANONICAL_UUID
    assert account_auth.owner_user_uuid_for_new_row(False) != CANONICAL_UUID


def test_owner_telegram_login_grants_owner_access_and_no_trial_message(auth_store, monkeypatch) -> None:
    """End to end over the real /login flow that produced the Free Preview bug."""
    monkeypatch.delenv("NTA_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv(account_auth.CANONICAL_OWNER_UUID_ENV, CANONICAL_UUID)
    uid = 1647145559
    doc = account_auth._read_doc()
    # The account as Canary had already stored it: an ordinary verified human.
    _canonical_owner_row(doc, uid, is_owner=False)
    account_auth._write_doc(doc)

    login = account_auth.start_login(bot_username="StratForge_bot", ip="127.0.0.1")
    calls, api = _api_recorder()
    assert account_auth.process_update({"message": {
        "text": f"/login {login['code']}",
        "from": {"id": uid, "first_name": "Owner", "username": "owner"},
        "chat": {"id": uid, "type": "private"},
    }}, api_call=api, owner_chat_id="")
    assert account_auth.process_update({"message": {
        "contact": {"user_id": uid, "phone_number": "+15551234567"},
        "from": {"id": uid}, "chat": {"id": uid, "type": "private"},
    }}, api_call=api, owner_chat_id="")

    assert account_auth.login_state(login["challenge_id"])["status"] == "login_approved"
    row = account_auth._user(account_auth._read_doc(), uid)
    assert row["is_owner"] is True and row["role"] == "owner"
    # The trial outbox must not be left pending for an owner.
    assert not row.get("initial_trial_pending")

    texts = [payload.get("text", "") for method, payload in calls if method == "sendMessage"]
    approval = [t for t in texts if "Личность подтверждена" in t]
    assert approval, texts
    assert "полный доступ владельца" in approval[-1]
    assert not any("пробный доступ" in t for t in approval)
    assert not any("Free Preview" in t for t in texts)


def test_non_owner_still_receives_the_trial_message(auth_store, monkeypatch) -> None:
    monkeypatch.setenv(account_auth.CANONICAL_OWNER_UUID_ENV, CANONICAL_UUID)
    account_auth.ensure_owner(999)
    login = account_auth.start_login(bot_username="StratForge_bot", ip="127.0.0.1")
    calls, api = _api_recorder()
    assert account_auth.process_update({"message": {
        "text": f"/login {login['code']}",
        "from": {"id": 4242, "first_name": "Ada", "last_name": "L",
                 "username": "ada"},
        "chat": {"id": 4242, "type": "private"},
    }}, api_call=api, owner_chat_id="999")
    account_auth.process_update({"message": {
        "contact": {"user_id": 4242, "phone_number": "+15559876543"},
        "from": {"id": 4242}, "chat": {"id": 4242, "type": "private"},
    }}, api_call=api, owner_chat_id="999")

    row = account_auth._user(account_auth._read_doc(), 4242)
    assert not row.get("is_owner")


def test_local_owner_row_prefers_canonical_uuid_over_lowest_id(auth_store, monkeypatch) -> None:
    """LOCAL must open as the same person Canary/Production resolve."""
    monkeypatch.delenv("NTA_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv(account_auth.CANONICAL_OWNER_UUID_ENV, CANONICAL_UUID)
    doc = account_auth._read_doc()
    # A lower-numbered legacy owner row must not win over the canonical one.
    doc["users"].append({
        "user_id": 999, "legacy_user_id": 999,
        "user_uuid": "11111111-2222-3333-4444-555555555555",
        "first_name": "Legacy", "role": "owner", "status": "active",
        "is_owner": True, "created_at_utc": account_auth._now_iso(),
    })
    _canonical_owner_row(doc, is_owner=True)
    account_auth._write_doc(doc)

    assert account_auth.primary_owner_id() == 1647145559


def test_developer_test_auth_cannot_exist_outside_development(monkeypatch) -> None:
    """Other developers get owner/test access on LOCAL only -- never remotely."""
    from app import runtime_env as rt

    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    for environment in (rt.CANARY, rt.PRODUCTION):
        monkeypatch.setattr(rt, "deployment_environment", lambda env=environment: env)
        assert rt.test_auth_enabled() is False
        with pytest.raises(rt.RuntimeEnvError):
            rt.assert_production_safe()
        with pytest.raises(rt.RuntimeEnvError):
            rt.require_test_auth()


# ---------------------------------------------------------------------------
# QR / one-tap Telegram login. The browser shows a short-lived QR carrying a
# deep link; the phone opens the bot and confirms once. No popup window and no
# mandatory contact upload on every login.
# ---------------------------------------------------------------------------

def _start_and_scan(api, uid=4242, code_owner="999", first="Ada", last="L"):
    login = account_auth.start_login(bot_username="StratForge_bot", ip="127.0.0.1")
    account_auth.process_update({"message": {
        "text": f"/start {login['bot_url'].split('?start=', 1)[1]}",
        "from": {"id": uid, "first_name": first, "last_name": last, "username": "ada"},
        "chat": {"id": uid, "type": "private"},
    }}, api_call=api, owner_chat_id=code_owner)
    return login


def _tap(api, challenge_id, uid=4242, owner="999", ok=True):
    return account_auth.process_update(
        {"callback_query": {
            "id": "cb1", "from": {"id": uid},
            "data": f"login_{'ok' if ok else 'no'}:{challenge_id}",
        }}, api_call=api, owner_chat_id=owner)


def test_login_start_returns_a_short_lived_qr_deep_link(auth_store) -> None:
    login = account_auth.start_login(bot_username="StratForge_bot", ip="127.0.0.1")
    assert login["qr_payload"] == login["bot_url"]
    assert login["bot_url"].startswith("https://t.me/StratForge_bot?start=login_")
    assert login["qr_svg"].startswith("<svg") and login["qr_svg"].endswith("</svg>")
    # Short TTL: a QR on screen is a bearer token, not a 15-minute link.
    assert login["expires_in_sec"] == account_auth.LOGIN_CHALLENGE_TTL_SEC
    assert login["expires_in_sec"] <= 300
    # The manual code stays available as the Advanced fallback.
    assert login["manual_command"].startswith("/login ")


def test_one_tap_confirmation_logs_in_without_any_contact(auth_store) -> None:
    account_auth.ensure_owner(999)
    calls, api = _api_recorder()
    login = _start_and_scan(api)
    assert account_auth.login_state(login["challenge_id"])["status"] == "awaiting_confirm"

    _tap(api, login["challenge_id"])
    state = account_auth.login_state(login["challenge_id"])["status"]
    # A brand-new account still has to complete its profile, but it got there
    # without ever being asked for a phone number.
    assert state in {"login_approved", "awaiting_profile"}
    assert not any("контакт" in str(p.get("text") or "").lower() for _m, p in calls)
    row = account_auth._user(account_auth._read_doc(), 4242)
    assert not row.get("phone_hash")


def test_scanned_challenge_is_single_use(auth_store) -> None:
    account_auth.ensure_owner(999)
    calls, api = _api_recorder()
    login = _start_and_scan(api)
    _tap(api, login["challenge_id"])
    # A replayed tap on the same challenge must not re-authorise anything.
    _tap(api, login["challenge_id"])
    answers = [p.get("text", "") for m, p in calls if m == "answerCallbackQuery"]
    assert any("истёк или уже использован" in text for text in answers)


def test_a_second_scan_of_the_same_code_is_refused(auth_store) -> None:
    account_auth.ensure_owner(999)
    calls, api = _api_recorder()
    login = _start_and_scan(api)
    # Someone else scanning the same QR finds nothing left to claim.
    account_auth.process_update({"message": {
        "text": f"/start {login['bot_url'].split('?start=', 1)[1]}",
        "from": {"id": 5151, "first_name": "Mallory"},
        "chat": {"id": 5151, "type": "private"},
    }}, api_call=api, owner_chat_id="999")
    texts = [p.get("text", "") for m, p in calls if m == "sendMessage"]
    assert any("истекла или уже использована" in text for text in texts)


def test_only_the_scanner_can_confirm_the_login(auth_store) -> None:
    account_auth.ensure_owner(999)
    calls, api = _api_recorder()
    login = _start_and_scan(api)
    # A forwarded button tapped by a different Telegram account is refused.
    _tap(api, login["challenge_id"], uid=5151)
    answers = [p.get("text", "") for m, p in calls if m == "answerCallbackQuery"]
    assert any("только тот, кто открыл ссылку" in text.lower() for text in answers)
    assert account_auth.login_state(login["challenge_id"])["status"] == "awaiting_confirm"


def test_rejecting_the_login_denies_the_waiting_browser(auth_store) -> None:
    account_auth.ensure_owner(999)
    calls, api = _api_recorder()
    login = _start_and_scan(api)
    _tap(api, login["challenge_id"], ok=False)
    assert account_auth.login_state(login["challenge_id"])["status"] == "denied"


def test_challenge_is_bound_to_the_issuing_environment(auth_store, monkeypatch) -> None:
    """A code issued by one environment is not claimable on another.

    The binding lives in the stored challenge, so it is checked here directly:
    switching runtime_env across a write would also switch the storage backend,
    which would test the fixture rather than the rule.
    """
    monkeypatch.setattr(
        account_auth.runtime_env, "deployment_environment",
        lambda: account_auth.runtime_env.CANARY)
    account_auth.ensure_owner(999)
    login = account_auth.start_login(bot_username="StratForge_bot", ip="127.0.0.1")
    doc = account_auth._read_doc()
    stored = account_auth._challenge(doc, challenge_id=login["challenge_id"])
    assert stored["environment"] == account_auth.runtime_env.CANARY

    # Same store, different environment: the claim must be refused.
    monkeypatch.setattr(
        account_auth.runtime_env, "deployment_environment",
        lambda: account_auth.runtime_env.DEVELOPMENT)
    refused = account_auth._claim_login_challenge(
        doc, code=login["code"], uid=4242, sender={"first_name": "Ada"},
        status="awaiting_confirm")
    assert refused is None
    assert stored["status"] == "created"

    # Back on the issuing environment the very same code is accepted once.
    monkeypatch.setattr(
        account_auth.runtime_env, "deployment_environment",
        lambda: account_auth.runtime_env.CANARY)
    claimed = account_auth._claim_login_challenge(
        doc, code=login["code"], uid=4242, sender={"first_name": "Ada"},
        status="awaiting_confirm")
    assert claimed is not None and claimed["status"] == "awaiting_confirm"


def test_owner_one_tap_login_is_owner_and_never_trial(auth_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv(account_auth.CANONICAL_OWNER_UUID_ENV, CANONICAL_UUID)
    uid = 1647145559
    doc = account_auth._read_doc()
    _canonical_owner_row(doc, uid, is_owner=False)
    account_auth._write_doc(doc)

    calls, api = _api_recorder()
    login = _start_and_scan(api, uid=uid, code_owner="", first="Owner", last="Tester")
    _tap(api, login["challenge_id"], uid=uid, owner="")

    assert account_auth.login_state(login["challenge_id"])["status"] == "login_approved"
    row = account_auth._user(account_auth._read_doc(), uid)
    assert row["is_owner"] is True and row["role"] == "owner"
    assert not row.get("initial_trial_pending")
    texts = [p.get("text", "") for m, p in calls if m == "sendMessage"]
    assert any("полный доступ владельца" in text for text in texts)
    assert not any("пробный" in text or "Free Preview" in text for text in texts)


def test_login_start_is_rate_limited_per_ip(auth_store) -> None:
    for _ in range(10):
        account_auth.start_login(bot_username="StratForge_bot", ip="10.0.0.9")
    with pytest.raises(account_auth.AccountAuthError) as excinfo:
        account_auth.start_login(bot_username="StratForge_bot", ip="10.0.0.9")
    assert excinfo.value.status == 429


def test_login_start_offers_both_an_app_scheme_and_a_universal_link(auth_store) -> None:
    login = account_auth.start_login(bot_username="StratForge_bot", ip="127.0.0.1")
    # tg: reaches an installed client with no browser hop and no resolver.
    assert login["app_url"].startswith("tg://resolve?domain=StratForge_bot&start=login_")
    # The QR carries the https form: it is a Universal/App Link, so a phone
    # with Telegram still opens the app, and one without it is not stranded.
    assert login["qr_payload"].startswith("https://t.me/")
    assert login["qr_payload"] == login["bot_url"]
    assert login["app_url"].endswith(login["code"])
    assert login["bot_url"].endswith(login["code"])
