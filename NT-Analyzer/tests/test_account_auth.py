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


def test_new_account_waits_for_owner_after_contact_profile_and_terms(auth_store) -> None:
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
    assert account_auth.login_state(
        login["challenge_id"], browser_nonce=login["browser_nonce"],
    )["status"] == "awaiting_profile"

    # Terms acceptance is mandatory.
    with pytest.raises(account_auth.AccountAuthError):
        account_auth.complete_profile(login["challenge_id"], {
            "first_name": "Ada", "last_name": "Lovelace", "email": "ADA@example.com",
        }, api_call=api, owner_chat_id="999", browser_nonce=login["browser_nonce"])

    state = account_auth.complete_profile(login["challenge_id"], {
        "first_name": "Ada", "last_name": "Lovelace", "email": "ADA@example.com",
        "accept_terms": True,
    }, api_call=api, owner_chat_id="999", browser_nonce=login["browser_nonce"])
    # New accounts wait for the owner's personal confirmation.
    assert state["status"] == "pending_owner"
    assert account_auth._user(account_auth._read_doc(), 42)["status"] == "pending"
    notice = next(payload for method, payload in calls if method == "sendMessage" and (payload.get("reply_markup") or {}).get("inline_keyboard"))
    allow = notice["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    assert allow.startswith("account_allow:")

    assert account_auth.process_update({"callback_query": {
        "id": "cb1", "data": allow, "from": {"id": 999},
    }}, api_call=api, owner_chat_id="999")
    assert account_auth.login_state(
        login["challenge_id"], browser_nonce=login["browser_nonce"],
    )["status"] == "login_approved"
    assert account_auth._user(account_auth._read_doc(), 42)["status"] == "active"

    result = account_auth.create_session_for_challenge(
        login["challenge_id"], ip="127.0.0.1", user_agent="pytest",
        browser_nonce=login["browser_nonce"],
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
    assert account_auth.login_state(
        login["challenge_id"], browser_nonce=login["browser_nonce"],
    )["status"] == "identity_mismatch"


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

    assert account_auth.login_state(
        login["challenge_id"], browser_nonce=login["browser_nonce"],
    )["status"] == "awaiting_contact"
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


def test_browser_nonce_binds_login_and_challenge_is_consumed_once(auth_store) -> None:
    account_auth.ensure_owner(999)
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        owner = account_auth._user(doc, 999)
        owner.update({
            "first_name": "Owner", "last_name": "One", "email": "owner@example.com",
        })
        account_auth._write_doc(doc)
    login = account_auth.start_login(
        bot_username="StratForge_bot", ip="127.0.0.1", user_agent="Browser A",
    )
    assert login["telegram_app_url"].startswith("tg://resolve?")
    assert login["telegram_web_url"].startswith("https://t.me/")
    assert len(login["code"]) >= 20
    assert login["browser_nonce"] not in login["telegram_app_url"]
    assert login["browser_nonce"] not in login["telegram_web_url"]

    with pytest.raises(account_auth.AccountAuthError) as stolen:
        account_auth.login_state(login["challenge_id"], browser_nonce="x" * 43)
    assert stolen.value.status == 403
    assert stolen.value.code == "login_state_mismatch"

    _calls, api = _api_recorder()
    assert account_auth.process_update({"message": {
        "text": f"/start login_{login['code']}",
        "from": {"id": 999, "first_name": "Renamed", "username": "new_name"},
        "chat": {"id": 999, "type": "private"},
    }}, api_call=api, owner_chat_id="999")
    assert account_auth.process_update({"message": {
        "contact": {"user_id": 999, "phone_number": "+15551234567"},
        "from": {"id": 999}, "chat": {"id": 999, "type": "private"},
    }}, api_call=api, owner_chat_id="999")

    first = account_auth.create_session_for_challenge(
        login["challenge_id"], ip="127.0.0.1", user_agent="Browser A",
        browser_nonce=login["browser_nonce"],
    )
    replay = account_auth.create_session_for_challenge(
        login["challenge_id"], ip="127.0.0.1", user_agent="Browser A",
        browser_nonce=login["browser_nonce"],
    )
    assert first["status"] == "authenticated"
    assert replay["status"] == "consumed"
    stored = account_auth._read_doc()
    assert len(stored["sessions"]) == 1
    assert account_auth._user(stored, 999)["is_owner"] is True
    assert account_auth._user(stored, 999)["username"] == "new_name"


def test_login_cancel_is_nonce_bound_and_terminal(auth_store) -> None:
    account_auth.ensure_owner(999)
    login = account_auth.start_login(bot_username="StratForge_bot", ip="127.0.0.1")
    with pytest.raises(account_auth.AccountAuthError) as wrong:
        account_auth.cancel_login(login["challenge_id"], browser_nonce="z" * 43)
    assert wrong.value.code == "login_state_mismatch"

    cancelled = account_auth.cancel_login(
        login["challenge_id"], browser_nonce=login["browser_nonce"],
    )
    assert cancelled["status"] == "cancelled"
    assert account_auth.login_state(
        login["challenge_id"], browser_nonce=login["browser_nonce"],
    )["status"] == "cancelled"
    _calls, api = _api_recorder()
    assert account_auth.process_update({"message": {
        "text": f"/login {login['code']}", "from": {"id": 999},
        "chat": {"id": 999, "type": "private"},
    }}, api_call=api, owner_chat_id="999")
    assert not account_auth._user(account_auth._read_doc(), 999).get("phone")


def test_owner_conflict_fails_closed_instead_of_using_first_registrant(auth_store) -> None:
    account_auth._write_doc({
        "version": 2,
        "users": [{
            "user_id": 42, "role": "owner", "is_owner": True, "status": "active",
        }],
        "challenges": [], "sessions": [],
    })
    with pytest.raises(account_auth.AccountAuthError) as conflict:
        account_auth.ensure_owner(999)
    assert conflict.value.status == 503
    assert conflict.value.code == "owner_identity_conflict"
    assert account_auth._user(account_auth._read_doc(), 999) is None


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


def test_public_login_origin_nonce_cancel_and_ui_fallback_contract(auth_store, monkeypatch) -> None:
    monkeypatch.setattr(
        server_mod.telegram_service, "load_settings",
        lambda: {"bot_username": "StratForge_bot"},
    )
    srv = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True); thread.start()
    base = f"http://{srv.server_address[0]}:{srv.server_address[1]}"

    def post(path, body, *, origin):
        request = urllib.request.Request(
            base + path,
            data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Origin": origin},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    try:
        with pytest.raises(urllib.error.HTTPError) as cross_site:
            post("/api/auth/login/start", {}, origin="https://evil.example")
        assert cross_site.value.code == 403

        status, login = post("/api/auth/login/start", {}, origin=base)
        assert status == 200
        assert login["telegram_app_url"].startswith("tg://resolve?")
        assert login["telegram_web_url"].startswith("https://t.me/")
        with pytest.raises(urllib.error.HTTPError) as missing_nonce:
            post(
                "/api/auth/login/status",
                {"challenge_id": login["challenge_id"]}, origin=base,
            )
        assert missing_nonce.value.code == 403
        _status, state = post(
            "/api/auth/login/status",
            {"challenge_id": login["challenge_id"], "browser_nonce": login["browser_nonce"]},
            origin=base,
        )
        assert state["status"] == "created"
        _status, cancelled = post(
            "/api/auth/login/cancel",
            {"challenge_id": login["challenge_id"], "browser_nonce": login["browser_nonce"]},
            origin=base,
        )
        assert cancelled["status"] == "cancelled"
    finally:
        srv.shutdown(); srv.server_close()

    root = auth_store.parent if (auth_store.parent / "app").is_dir() else None
    if root is None:
        root = account_auth._PROJECT_ROOT
    ui = (root / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
    api = (root / "app" / "static" / "aurora" / "assets" / "api.js").read_text(encoding="utf-8")
    assert "telegram_app_url" in ui and "telegram_web_url" in ui
    assert "QR-код для телефона" in ui and "telegramQrSvg" in ui
    assert "launcher.click()" in ui
    assert "browser_nonce" in api and "/api/auth/login/cancel" in api


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


def test_production_owner_never_falls_back_to_synthetic_local_workspace(monkeypatch) -> None:
    monkeypatch.setenv("STRATFORGE_ENV", "production")
    monkeypatch.setattr(
        server_mod.workspaces, "context_for_user",
        lambda *args, **kwargs: {
            "error": "canonical workspace unavailable",
            "workspaces": [], "active_workspace": {}, "active_membership": {},
        },
    )
    monkeypatch.setattr(
        server_mod.permissions, "resolve_for_user_id",
        lambda *args, **kwargs: {"capabilities": {}, "ux_mode": ""},
    )
    handler = server_mod.Handler.__new__(server_mod.Handler)
    context = handler._decorate_workspace_context({
        "user_id": 999, "is_owner": True, "role": "owner", "user": {},
    })
    assert context["active_workspace"] == {}
    assert context["active_membership"] == {}
    assert context["workspace_context"]["error"] == "canonical workspace unavailable"


def test_register_via_telegram_waits_for_owner(auth_store) -> None:
    account_auth.ensure_owner(999)
    calls, api = _api_recorder()
    out = account_auth.register_via_telegram(
        {"id": 42, "first_name": "Ada", "username": "ada"},
        email="ada@example.com", accept_terms=True, api_call=api, owner_chat_id="999")
    assert out["status"] == "pending_owner" and out["authenticated"] is False
    assert out["user"]["user_id"] == 42 and out["user"]["status"] == "pending"
    assert out["challenge_id"]
    assert account_auth.find_active_user(42) is None
    # Owner gets allow/deny buttons.
    assert any((p.get("reply_markup") or {}).get("inline_keyboard") for _m, p in calls)
    allow = next(
        btn["callback_data"]
        for _m, p in calls
        for row in (p.get("reply_markup") or {}).get("inline_keyboard") or []
        for btn in row
        if str(btn.get("callback_data") or "").startswith("account_allow:")
    )
    assert account_auth.process_update({"callback_query": {
        "id": "cb1", "data": allow, "from": {"id": 999},
    }}, api_call=api, owner_chat_id="999")
    assert account_auth.find_active_user(42) is not None

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

    assert doc == {"version": 2, "users": [], "challenges": [], "sessions": []}
    assert not path.exists()
    assert list(path.parent.glob("accounts.dpapi.unreadable-*.bak"))
    assert (path.parent / "accounts.dpapi.recovery.json").is_file()
