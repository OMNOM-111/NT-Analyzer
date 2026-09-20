"""End-to-end contracts for pending -> OTP -> permanent/session access.

These tests intentionally use real account/security stores and the HTTP handler,
but development-only OTP echo instead of an external Telegram/e-mail delivery.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, security_devices
from app import server as server_mod


USER_UUID = "00000000-0000-4000-8000-000000000042"
OWNER_UUID = "00000000-0000-4000-8000-000000000999"
UA = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/126 Safari/537.36"


@pytest.fixture()
def confirmation_store(tmp_path, monkeypatch):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(account_auth.secure_store, "_protect", lambda value: value)
    monkeypatch.setattr(account_auth.secure_store, "_unprotect", lambda value: value)
    monkeypatch.setattr(account_auth.secure_store, "available", lambda: True)
    (tmp_path / "data" / "integrations").mkdir(parents=True)
    (tmp_path / "data" / "audit").mkdir(parents=True)
    security_devices._CHALLENGE_RATE.clear()
    account_auth._write_doc({
        "version": 3,
        "users": [
            {
                "user_id": 999, "user_uuid": OWNER_UUID,
                "username": "owner", "first_name": "Owner",
                "role": "owner", "status": "active", "is_owner": True,
                "telegram_user_id": 999, "ux_mode": "professional",
            },
            {
                "user_id": 42, "user_uuid": USER_UUID,
                "username": "alice", "first_name": "Alice",
                "role": "full_control", "status": "active", "is_owner": False,
                "telegram_user_id": 42, "email": "alice@example.com",
                "email_verified_at_utc": "2026-01-01T00:00:00Z",
                "ux_mode": "professional",
            },
        ],
        "auth_identities": [
            {
                "identity_id": "id_email_alice", "user_uuid": USER_UUID,
                "legacy_user_id": 42, "provider": "email",
                "provider_subject": "alice@example.com",
                "verified_at_utc": "2026-01-01T00:00:00Z",
                "linked_at_utc": "2026-01-01T00:00:00Z",
                "metadata": {"email": "alice@example.com"},
            },
        ],
        "challenges": [], "sessions": [], "trusted_devices": [],
        "physical_devices": [], "security_challenges": [],
        "identity_schema": {"stage": "dual_write", "canonical_key": "user_uuid"},
    })
    account_auth.set_auth_required(True)
    return tmp_path


def _login(*, credential="browser-a", ip="203.0.113.8"):
    return account_auth.create_session_for_user(
        42, ip=ip, user_agent=UA, source="email_login",
        require_google=False, skip_dual_auth_gate=True,
        device_credential=credential, device_confirmation_required=True,
    )


def _confirm(login, mode):
    context = account_auth.authenticate_session(login["session_token"])
    access = context["device_access"]
    started = security_devices.create_challenge(
        user_id=42, purpose=security_devices.PURPOSE_DEVICE_CONFIRM,
        device_id=access["client_id"], provider="email", trust_mode=mode,
        session_id=context["session_id"],
    )
    return security_devices.approve_device(
        user_id=42, device_id=access["client_id"],
        challenge_id=started["challenge_id"], code=started["test_code"],
        trust_mode=mode, session_id=context["session_id"],
    )


def _serve():
    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{server.server_address[0]}:{server.server_address[1]}"


def _request(base, path, *, token="", csrf="", method="GET", body=None):
    headers = {"Origin": base}
    if token:
        headers["Cookie"] = f"{account_auth.SESSION_COOKIE}={token}"
    if csrf:
        headers["X-CSRF-Token"] = csrf
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(base + path, headers=headers, data=data, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), json.loads(response.read())
    except urllib.error.HTTPError as error:
        payload = json.loads(error.read().decode("utf-8"))
        return error.code, dict(error.headers), payload


def test_pending_access_has_five_minute_deadline_and_minimal_http_bootstrap(confirmation_store):
    login = _login()
    context = account_auth.authenticate_session(login["session_token"])
    assert context["device_confirmation_state"] == "pending"
    assert context["device_access"]["required"] is True
    assert 0 < context["device_access"]["pending_expires_at"] - time.time() <= 301
    assert login["session_cookie_persistent"] is False

    server, base = _serve()
    try:
        status, _, payload = _request(base, "/api/auth/status", token=login["session_token"])
        assert status == 200
        assert payload["device_access"]["required"] is True
        assert "workspaces" not in payload
        assert "capabilities" not in payload

        status, _, blocked = _request(base, "/api/account/security", token=login["session_token"])
        assert status == 403
        assert blocked["code"] == "DEVICE_CONFIRMATION_REQUIRED"

        status, _, challenge = _request(
            base, "/api/account/security/challenge",
            token=login["session_token"], csrf=context["csrf_token"], method="POST",
            body={
                "purpose": "device_confirm", "device_id": context["trusted_device_id"],
                "provider": "email", "trust_mode": "session",
            },
        )
        assert status == 200
        assert challenge["expires_in_sec"] <= security_devices.PENDING_SESSION_TTL_SEC

        status, headers, approved = _request(
            base, "/api/account/devices/approve",
            token=login["session_token"], csrf=context["csrf_token"], method="POST",
            body={
                "device_id": context["trusted_device_id"],
                "challenge_id": challenge["challenge_id"],
                "code": challenge["test_code"], "trust_mode": "session",
            },
        )
        assert status == 200
        assert approved["trust_mode"] == "session"
        assert "Max-Age" not in str(headers.get("Set-Cookie") or "")

        status, _, page = _request(base, "/api/account/security", token=login["session_token"])
        assert status == 200
        assert page["standalone_clients"][0]["access"]["trust_mode"] == "session"
        assert page["standalone_clients"][0]["physical_device_id"] == ""
    finally:
        server.shutdown()
        server.server_close()


def test_session_only_applies_to_exact_session_and_next_login_is_pending(confirmation_store):
    first = _login()
    result = _confirm(first, security_devices.TRUST_MODE_SESSION)
    assert result["session_cookie_persistent"] is False
    assert account_auth.authenticate_session(first["session_token"])["device_trust_mode"] == "session"

    doc = account_auth._read_doc()
    assert doc["trusted_devices"][0]["status"] == security_devices.STATUS_PENDING

    second = _login()
    second_context = account_auth.authenticate_session(second["session_token"])
    assert second_context["device_confirmation_state"] == "pending"
    assert second_context["device_access"]["required"] is True


def test_permanent_trust_survives_login_until_explicit_revoke(confirmation_store):
    first = _login()
    result = _confirm(first, security_devices.TRUST_MODE_PERMANENT)
    assert result["session_cookie_persistent"] is True
    assert result["device"]["status"] == security_devices.STATUS_TRUSTED

    second = _login(ip="198.51.100.44")
    second_context = account_auth.authenticate_session(second["session_token"])
    assert second_context["device_confirmation_state"] == "active"
    assert second_context["device_trust_mode"] == "permanent"
    assert second["session_cookie_persistent"] is True

    security_devices.revoke_device(
        user_id=42, device_id=second_context["trusted_device_id"],
    )
    assert account_auth.authenticate_session(first["session_token"]) is None
    assert account_auth.authenticate_session(second["session_token"]) is None


def test_new_unknown_client_is_pending_even_when_another_client_is_trusted(confirmation_store):
    known = _login(credential="browser-known")
    _confirm(known, security_devices.TRUST_MODE_PERMANENT)

    unknown = _login(credential="browser-new")
    unknown_context = account_auth.authenticate_session(unknown["session_token"])
    assert unknown_context["device_confirmation_state"] == "pending"
    assert unknown_context["device_access"]["required"] is True
    catalog = security_devices.account_security(42)
    assert len(catalog["standalone_clients"]) == 2
    assert {row["status"] for row in catalog["standalone_clients"]} == {"pending", "trusted"}


def test_challenge_is_bound_to_session_mode_target_and_environment(confirmation_store):
    first = _login(credential="browser-a")
    second = _login(credential="browser-b")
    first_context = account_auth.authenticate_session(first["session_token"])
    second_context = account_auth.authenticate_session(second["session_token"])
    started = security_devices.create_challenge(
        user_id=42, purpose="device_confirm",
        device_id=first_context["trusted_device_id"], provider="email",
        trust_mode="session", session_id=first_context["session_id"],
    )
    with pytest.raises(security_devices.SecurityDeviceError) as wrong_session:
        security_devices.approve_device(
            user_id=42, device_id=first_context["trusted_device_id"],
            challenge_id=started["challenge_id"], code=started["test_code"],
            trust_mode="session", session_id=second_context["session_id"],
        )
    assert wrong_session.value.code == "challenge_wrong_session"

    with pytest.raises(security_devices.SecurityDeviceError) as wrong_mode:
        security_devices.approve_device(
            user_id=42, device_id=first_context["trusted_device_id"],
            challenge_id=started["challenge_id"], code=started["test_code"],
            trust_mode="permanent", session_id=first_context["session_id"],
        )
    assert wrong_mode.value.code == "challenge_wrong_trust_mode"


def test_pending_session_can_confirm_or_reject_only_its_own_client(confirmation_store):
    first = _login(credential="browser-a")
    second = _login(credential="browser-b")
    first_context = account_auth.authenticate_session(first["session_token"])
    second_context = account_auth.authenticate_session(second["session_token"])

    with pytest.raises(security_devices.SecurityDeviceError) as wrong_target:
        security_devices.create_challenge(
            user_id=42, purpose="device_confirm",
            device_id=second_context["trusted_device_id"], provider="email",
            trust_mode="permanent", session_id=first_context["session_id"],
        )
    assert wrong_target.value.code == "session_device_mismatch"

    server, base = _serve()
    try:
        status, _, payload = _request(
            base, "/api/account/devices/reject",
            token=first["session_token"], csrf=first_context["csrf_token"],
            method="POST", body={"device_id": second_context["trusted_device_id"]},
        )
        assert status == 403
        assert payload["code"] == "device_confirmation_target_mismatch"

        status, _, payload = _request(
            base, "/api/account/security/challenge",
            token=first["session_token"], csrf=first_context["csrf_token"],
            method="POST", body={"purpose": "step_up"},
        )
        assert status == 403
        assert payload["code"] == "DEVICE_CONFIRMATION_REQUIRED"
    finally:
        server.shutdown()
        server.server_close()

    assert account_auth.authenticate_session(second["session_token"])["device_confirmation_state"] == "pending"


def test_approving_another_client_does_not_persist_the_approver_cookie(confirmation_store):
    approver = _login(credential="browser-a")
    _confirm(approver, security_devices.TRUST_MODE_SESSION)
    approver_context = account_auth.authenticate_session(approver["session_token"])
    assert approver_context["device_trust_mode"] == "session"

    candidate = _login(credential="browser-b")
    candidate_context = account_auth.authenticate_session(candidate["session_token"])
    started = security_devices.create_challenge(
        user_id=42, purpose="device_confirm",
        device_id=candidate_context["trusted_device_id"], provider="email",
        trust_mode="permanent", session_id=approver_context["session_id"],
    )
    approved = security_devices.approve_device(
        user_id=42, device_id=candidate_context["trusted_device_id"],
        challenge_id=started["challenge_id"], code=started["test_code"],
        trust_mode="permanent", session_id=approver_context["session_id"],
    )
    assert approved["session_cookie_persistent"] is False
    assert account_auth.authenticate_session(approver["session_token"])["device_trust_mode"] == "session"
    assert account_auth.authenticate_session(candidate["session_token"])["device_trust_mode"] == "permanent"


def test_resend_enforces_server_cooldown_and_limit(confirmation_store):
    login = _login()
    context = account_auth.authenticate_session(login["session_token"])
    started = security_devices.create_challenge(
        user_id=42, purpose="device_confirm",
        device_id=context["trusted_device_id"], provider="email",
        trust_mode="session", session_id=context["session_id"],
    )
    with pytest.raises(security_devices.SecurityDeviceError) as cooldown:
        security_devices.resend_challenge(
            user_id=42, challenge_id=started["challenge_id"],
            session_id=context["session_id"],
        )
    assert cooldown.value.code == "challenge_resend_cooldown"

    current = started
    for expected_count in range(1, security_devices.CHALLENGE_MAX_RESENDS + 1):
        doc = account_auth._read_doc()
        row = next(item for item in doc["security_challenges"] if item["challenge_id"] == current["challenge_id"])
        row["resend_available_at"] = 0
        account_auth._write_doc(doc)
        current = security_devices.resend_challenge(
            user_id=42, challenge_id=current["challenge_id"],
            session_id=context["session_id"],
        )
        doc = account_auth._read_doc()
        row = next(item for item in doc["security_challenges"] if item["challenge_id"] == current["challenge_id"])
        assert row["resend_count"] == expected_count

    doc = account_auth._read_doc()
    row = next(item for item in doc["security_challenges"] if item["challenge_id"] == current["challenge_id"])
    row["resend_available_at"] = 0
    account_auth._write_doc(doc)
    with pytest.raises(security_devices.SecurityDeviceError) as exhausted:
        security_devices.resend_challenge(
            user_id=42, challenge_id=current["challenge_id"],
            session_id=context["session_id"],
        )
    assert exhausted.value.code == "challenge_resend_exhausted"


def test_expired_pending_session_fails_closed_with_specific_reason(confirmation_store):
    login = _login()
    context = account_auth.authenticate_session(login["session_token"])
    doc = account_auth._read_doc()
    session = next(row for row in doc["sessions"] if row["session_id"] == context["session_id"])
    session["expires_at"] = time.time() - 2
    session["pending_expires_at"] = time.time() - 2
    account_auth._write_doc(doc)

    assert account_auth.authenticate_session(login["session_token"]) is None
    failure = account_auth.session_auth_failure(login["session_token"])
    assert failure["code"] == "device_confirmation_expired"


def test_unbound_browser_is_not_a_fake_machine_and_ip_change_does_not_split_it(
    confirmation_store, monkeypatch,
):
    monkeypatch.setenv("COMPUTERNAME", "DEPLOYMENT-SERVER")
    first = _login(ip="203.0.113.8")
    _confirm(first, security_devices.TRUST_MODE_PERMANENT)
    _login(ip="198.51.100.9")
    catalog = security_devices.account_security(42)
    assert catalog["machines"] == []
    assert len(catalog["standalone_clients"]) == 1
    standalone = catalog["standalone_clients"][0]
    assert standalone["physical_device_id"] == ""
    assert "DEPLOYMENT-SERVER" not in standalone["display_name"]
    assert "Chrome" in standalone["display_name"]
    assert catalog["grouping_policy"]["ip_or_user_agent_is_identity"] is False
    assert catalog["grouping_policy"]["unbound_clients_are_devices"] is False


def test_rename_is_user_scoped_and_client_revoke_does_not_touch_other_client(confirmation_store):
    first = _login(credential="browser-a")
    _confirm(first, security_devices.TRUST_MODE_PERMANENT)
    first_context = account_auth.authenticate_session(first["session_token"])
    second = _login(credential="browser-b")
    _confirm(second, security_devices.TRUST_MODE_PERMANENT)

    renamed = security_devices.rename_device(
        user_id=42, device_id=first_context["trusted_device_id"],
        display_name="Chrome — работа",
    )
    assert renamed["device"]["display_name"] == "Chrome — работа"
    revoked = security_devices.revoke_device(
        user_id=42, device_id=first_context["trusted_device_id"],
    )
    assert revoked["revoked_sessions"] == 1
    assert account_auth.authenticate_session(first["session_token"]) is None
    assert account_auth.authenticate_session(second["session_token"]) is not None


def test_frontend_contract_has_session_mode_six_digits_and_no_day_based_copy():
    ui = (server_mod.STATIC_DIR / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
    # Wording follows the approved screens; the contract is the pair of trust
    # modes and the absence of any day- or hour-based grant.
    assert "Подтвердить постоянно" in ui
    assert "Только текущая сессия" in ui
    assert "Разрешить только сейчас" in ui
    assert "data-device-code-digit" in ui
    assert "[1, 2, 3, 4, 5, 6]" in ui
    assert "one-time-code" in ui
    assert "Код истёк. Запросите новый код." in ui
    assert "Устройство подтверждено!" in ui
    assert "Перейти в кабинет" in ui
    assert "24 часа" not in ui
    assert "Временный доступ" not in ui


def test_security_frontend_contract_has_three_views_and_scoped_actions():
    ui = (server_mod.STATIC_DIR / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
    api = (server_mod.STATIC_DIR / "aurora" / "assets" / "api.js").read_text(encoding="utf-8")
    for label in ("Устройства", "Мои сессии", "История входов"):
        assert label in ui
    for action in (
        "data-sec-client-rename", "data-sec-machine-rename",
        "data-sec-session-end", "data-sec-client-revoke", "data-sec-machine-revoke",
    ):
        assert action in ui
    for endpoint in (
        "/api/account/devices/rename", "/api/account/machines/rename",
        "/api/account/devices/revoke", "/api/account/machines/revoke",
        "/api/account/sessions/revoke",
    ):
        assert endpoint in api


def test_pending_cookie_is_nonpersistent_and_permanent_cookie_has_max_age():
    handler = object.__new__(server_mod.Handler)
    handler.headers = {}
    handler._extra_headers = []
    handler._set_session_cookie("pending-token", persistent=False)
    pending_cookie = handler._extra_headers[-1][1]
    assert "HttpOnly" in pending_cookie
    assert "SameSite=Strict" in pending_cookie
    assert "Max-Age" not in pending_cookie

    handler._set_session_cookie("trusted-token", persistent=True)
    trusted_cookie = handler._extra_headers[-1][1]
    assert f"Max-Age={account_auth.SESSION_TTL_SEC}" in trusted_cookie


def _fresh_access(login):
    """The screen payload the client actually draws the confirmation from."""
    context = account_auth.authenticate_session(login["session_token"])
    access = security_devices.current_session_access(42, context["session_id"])
    access["client_id"] = access["client"]["id"]
    return context, access


def test_first_confirmation_after_a_proved_signin_needs_no_second_code(confirmation_store):
    """The sign-in a minute ago is the proof; the screen only asks how long."""
    login = _login()
    context, access = _fresh_access(login)
    assert access["fresh_signin_provider"] == "email"
    assert access["code_required"] is False

    out = security_devices.approve_device(
        user_id=42, device_id=access["client_id"], challenge_id="", code="",
        trust_mode="permanent", session_id=context["session_id"],
    )
    assert out["ok"] is True
    assert out["trust_mode"] == "permanent"
    after = account_auth.authenticate_session(login["session_token"])
    assert after["device_access"]["state"] == "active"


def test_the_signin_proof_is_spent_by_the_confirmation_it_pays_for(confirmation_store):
    login = _login()
    context, access = _fresh_access(login)
    security_devices.approve_device(
        user_id=42, device_id=access["client_id"], challenge_id="", code="",
        trust_mode="session", session_id=context["session_id"],
    )
    doc = account_auth._read_doc()
    session = next(
        row for row in doc["sessions"]
        if account_auth._session_id(row) == context["session_id"]
    )
    assert "identity_verified_at_utc" not in session


def test_another_client_never_rides_on_this_sessions_signin(confirmation_store):
    """The proof covers the client that signed in, and nothing else."""
    first = _login(credential="browser-a")
    second = _login(credential="browser-b")
    first_context, _ = _fresh_access(first)
    _, second_access = _fresh_access(second)
    with pytest.raises(security_devices.SecurityDeviceError) as wrong:
        security_devices.approve_device(
            user_id=42, device_id=second_access["client_id"], challenge_id="", code="",
            trust_mode="permanent", session_id=first_context["session_id"],
        )
    assert wrong.value.code == "challenge_required"


def test_a_stale_signin_falls_back_to_an_ordinary_code(confirmation_store, monkeypatch):
    login = _login()
    context, access = _fresh_access(login)
    monkeypatch.setattr(
        security_devices, "_now",
        lambda: time.time() + security_devices.FRESH_IDENTITY_WINDOW_SEC + 60,
    )
    with pytest.raises(security_devices.SecurityDeviceError) as stale:
        security_devices.approve_device(
            user_id=42, device_id=access["client_id"], challenge_id="", code="",
            trust_mode="permanent", session_id=context["session_id"],
        )
    assert stale.value.code == "challenge_required"


def test_a_session_with_no_proved_signin_still_needs_a_code(confirmation_store):
    """A desktop session was never a provider handshake, so nothing is skipped."""
    login = account_auth.create_session_for_user(
        42, ip="203.0.113.8", user_agent=UA, source="desktop_session",
        require_google=False, skip_dual_auth_gate=True,
        device_credential="browser-c", device_confirmation_required=True,
    )
    context, access = _fresh_access(login)
    assert access["code_required"] is True
    assert access["fresh_signin_provider"] == ""
    with pytest.raises(security_devices.SecurityDeviceError) as needs:
        security_devices.approve_device(
            user_id=42, device_id=access["client_id"], challenge_id="", code="",
            trust_mode="permanent", session_id=context["session_id"],
        )
    assert needs.value.code == "challenge_required"


def test_a_second_client_signs_in_freshly_and_still_answers_a_code(confirmation_store):
    """Only the first client rides on the sign-in; later ones are unknown devices."""
    first = _login(credential="browser-a")
    first_context, first_access = _fresh_access(first)
    security_devices.approve_device(
        user_id=42, device_id=first_access["client_id"], challenge_id="", code="",
        trust_mode="permanent", session_id=first_context["session_id"],
    )

    second = _login(credential="browser-b")
    second_context, second_access = _fresh_access(second)
    assert second_access["code_required"] is True
    assert second_access["fresh_signin_provider"] == ""
    with pytest.raises(security_devices.SecurityDeviceError) as needs:
        security_devices.approve_device(
            user_id=42, device_id=second_access["client_id"], challenge_id="", code="",
            trust_mode="permanent", session_id=second_context["session_id"],
        )
    assert needs.value.code == "challenge_required"
    # The ordinary code path still confirms it.
    assert _confirm(second, "permanent")["ok"] is True
