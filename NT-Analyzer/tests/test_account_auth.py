from __future__ import annotations

import hashlib
import base64
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, secure_store, workspaces
from app import server as server_mod


@pytest.fixture
def auth_store(monkeypatch, tmp_path):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
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


def test_new_account_auto_activates_after_contact_profile_and_terms(auth_store) -> None:
    account_auth.ensure_owner(999)
    login = account_auth.start_login(bot_username="StratForge_bot", ip="127.0.0.1")
    calls, api = _api_recorder()

    assert account_auth.process_update({"message": {
        "text": login["bot_url"].split("?start=", 1)[1].join(["/start ", ""]),
        "from": {"id": 42, "first_name": "Ada", "username": "ada"},
        "chat": {"id": 42, "type": "private"},
    }}, api_call=api, owner_chat_id="999")
    assert any((payload.get("reply_markup") or {}).get("keyboard") for _method, payload in calls)

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
    # Telegram-verified users enter Free Preview immediately — no owner-approval gate.
    assert state["status"] == "login_approved"
    notice = next(payload for method, payload in calls if method == "sendMessage" and (payload.get("reply_markup") or {}).get("inline_keyboard"))
    assert "account_revoke:42" in notice["reply_markup"]["inline_keyboard"][0][0]["callback_data"]

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

    assert account_auth.login_state(login["challenge_id"])["status"] == "awaiting_contact"
    assert any((payload.get("reply_markup") or {}).get("keyboard") for _method, payload in calls)


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


def test_register_via_telegram_activates_free_preview(auth_store) -> None:
    account_auth.ensure_owner(999)
    calls, api = _api_recorder()
    user = account_auth.register_via_telegram(
        {"id": 42, "first_name": "Ada", "username": "ada"},
        email="ada@example.com", accept_terms=True, api_call=api, owner_chat_id="999")
    assert user["user_id"] == 42 and user["status"] == "active" and user["is_owner"] is False
    assert account_auth.find_active_user(42) is not None
    # Owner notified of the new Free Preview user.
    assert any((p.get("reply_markup") or {}).get("inline_keyboard") for _m, p in calls)

    # Terms acceptance is mandatory.
    with pytest.raises(account_auth.AccountAuthError):
        account_auth.register_via_telegram({"id": 43}, email="b@e.com", accept_terms=False, owner_chat_id="999")

    # The owner is recognised from initData.
    owner = account_auth.register_via_telegram(
        {"id": 999, "first_name": "Own"}, email="o@e.com", accept_terms=True, owner_chat_id="999")
    assert owner["is_owner"] is True

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
    monkeypatch.setenv("NTA_DEVICE_LABEL", "PC2")
    account_auth.register_via_telegram(
        {"id": 42, "first_name": "Ada", "username": "ada"},
        email="pc2@example.com", accept_terms=True, owner_chat_id="999")

    user = account_auth._user(account_auth._read_doc(), 42)
    assert user["email"] == "pc1@example.com"
    device_emails = {row.get("label"): row.get("email") for row in user.get("devices", [])}
    assert device_emails["PC1"] == "pc1@example.com"
    assert device_emails["PC2"] == "pc2@example.com"


def test_foreign_dpapi_account_store_is_quarantined(auth_store, monkeypatch) -> None:
    path = account_auth._store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(account_auth._MAGIC + base64.b64encode(b"foreign-dpapi"))

    def fail_unprotect(_value):
        raise secure_store.SecureStoreError("foreign DPAPI")

    monkeypatch.setattr(secure_store, "_unprotect", fail_unprotect)

    doc = account_auth._read_doc()

    assert doc == {"version": 1, "users": [], "challenges": [], "sessions": []}
    assert not path.exists()
    assert list(path.parent.glob("accounts.dpapi.unreadable-*.bak"))
    assert (path.parent / "accounts.dpapi.recovery.json").is_file()
