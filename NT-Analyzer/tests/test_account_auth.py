from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, secure_store
from app import server as server_mod


@pytest.fixture
def auth_store(monkeypatch, tmp_path):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
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


def test_new_account_requires_contact_profile_and_owner_approval(auth_store) -> None:
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

    state = account_auth.complete_profile(login["challenge_id"], {
        "first_name": "Ada", "last_name": "Lovelace", "email": "ADA@example.com",
    }, api_call=api, owner_chat_id="999")
    assert state["status"] == "pending_owner"
    approval = next(payload for method, payload in calls if method == "sendMessage" and (payload.get("reply_markup") or {}).get("inline_keyboard"))
    callback_data = approval["reply_markup"]["inline_keyboard"][0][0]["callback_data"]

    account_auth.process_update({"callback_query": {
        "id": "wrong", "data": callback_data, "from": {"id": 123},
    }}, api_call=api, owner_chat_id="999")
    assert account_auth.login_state(login["challenge_id"])["status"] == "pending_owner"

    account_auth.process_update({"callback_query": {
        "id": "owner", "data": callback_data, "from": {"id": 999},
    }}, api_call=api, owner_chat_id="999")
    result = account_auth.create_session_for_challenge(
        login["challenge_id"], ip="127.0.0.1", user_agent="pytest",
    )
    assert result["status"] == "authenticated"
    context = account_auth.authenticate_session(result["session_token"])
    assert context and context["user_id"] == 42
    assert account_auth.verify_csrf(context, result["csrf_token"])

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
