"""Phase 5: personal NinjaTrader security — factors + step-up for critical actions.

Covers the two-factor requirement (confirmed Telegram + verified email, with a
Google verified email acting as the email factor), the single-use step-up grant
lifecycle, cross-user/UUID/action/environment isolation, replay protection,
owner/test exemptions, and the self-service HTTP contract. PostgreSQL acceptance
is gated separately by real DSNs; here the store is the DPAPI account document.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, personal_nt_security, security_devices
from app import server as server_mod

OWNER_UUID = "00000000-0000-4000-8000-000000000999"
ALICE_UUID = "00000000-0000-4000-8000-000000000042"  # telegram + verified email
BOB_UUID = "00000000-0000-4000-8000-000000000007"    # telegram only (no email)
CAROL_UUID = "00000000-0000-4000-8000-000000000008"  # email only (no telegram)
DAVE_UUID = "00000000-0000-4000-8000-000000000009"   # telegram + google email


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv("NTA_APP_ENV", "staging")  # -> deployment_environment == development
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    monkeypatch.setenv("NTA_NT_GOOGLE_REQUIRED", "1")
    monkeypatch.setenv("NTA_NT_TELEGRAM_CONFIRM_REQUIRED", "1")
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(account_auth.secure_store, "_protect", lambda b: b)
    monkeypatch.setattr(account_auth.secure_store, "_unprotect", lambda b: b)
    monkeypatch.setattr(account_auth.secure_store, "available", lambda: True)
    (tmp_path / "data" / "integrations").mkdir(parents=True)
    (tmp_path / "data" / "audit").mkdir(parents=True)
    security_devices._CHALLENGE_RATE.clear()

    def _email_identity(user_uuid, legacy, email):
        return {
            "identity_id": "id_email_%s" % legacy, "user_uuid": user_uuid,
            "legacy_user_id": legacy, "provider": "email", "provider_subject": email,
            "verified_at_utc": "2026-01-01T00:00:00Z", "linked_at_utc": "2026-01-01T00:00:00Z",
        }

    def _telegram_identity(user_uuid, legacy):
        return {
            "identity_id": "id_tg_%s" % legacy, "user_uuid": user_uuid,
            "legacy_user_id": legacy, "provider": "telegram", "provider_subject": str(legacy),
            "verified_at_utc": "2026-01-01T00:00:00Z", "linked_at_utc": "2026-01-01T00:00:00Z",
        }

    def _google_identity(user_uuid, legacy, subject, email):
        return {
            "identity_id": "id_google_%s" % legacy, "user_uuid": user_uuid,
            "legacy_user_id": legacy, "provider": "google", "provider_subject": subject,
            "verified_at_utc": "2026-01-01T00:00:00Z", "linked_at_utc": "2026-01-01T00:00:00Z",
            "metadata": {"email": email},
        }

    account_auth._write_doc({
        "version": 3,
        "users": [
            {"user_id": 999, "user_uuid": OWNER_UUID, "username": "owner", "first_name": "Owner",
             "role": "owner", "status": "active", "is_owner": True, "telegram_user_id": 999},
            {"user_id": 42, "user_uuid": ALICE_UUID, "username": "alice", "first_name": "Alice",
             "role": "full_control", "status": "active", "is_owner": False, "telegram_user_id": 42,
             "email": "alice@example.com", "ux_mode": "professional"},
            {"user_id": 7, "user_uuid": BOB_UUID, "username": "bob", "first_name": "Bob",
             "role": "full_control", "status": "active", "is_owner": False, "telegram_user_id": 7,
             "ux_mode": "professional"},
            {"user_id": 8, "user_uuid": CAROL_UUID, "username": "carol", "first_name": "Carol",
             "role": "full_control", "status": "active", "is_owner": False,
             "email": "carol@example.com", "ux_mode": "professional"},
            {"user_id": 9, "user_uuid": DAVE_UUID, "username": "dave", "first_name": "Dave",
             "role": "full_control", "status": "active", "is_owner": False, "telegram_user_id": 9,
             "google_sub": "dave-google", "google_email": "dave@gmail.com", "ux_mode": "professional"},
        ],
        "auth_identities": [
            _telegram_identity(ALICE_UUID, 42), _email_identity(ALICE_UUID, 42, "alice@example.com"),
            _telegram_identity(BOB_UUID, 7),
            _email_identity(CAROL_UUID, 8, "carol@example.com"),
            _telegram_identity(DAVE_UUID, 9),
            _google_identity(DAVE_UUID, 9, "dave-google", "dave@gmail.com"),
        ],
        "challenges": [],
        "sessions": [],
        "trusted_devices": [],
        "security_challenges": [],
        "identity_schema": {"stage": "dual_write", "canonical_key": "user_uuid"},
    })
    account_auth.set_auth_required(True)
    return tmp_path


def _grant(uid: int, action: str) -> str:
    started = personal_nt_security.begin_step_up(uid, action=action)
    security_devices.confirm_challenge(
        user_id=uid, challenge_id=started["challenge_id"], code=started["test_code"],
    )
    return started["challenge_id"]


# --------------------------------------------------------------------------- #
# Factors and posture.
# --------------------------------------------------------------------------- #
def test_posture_ready_with_telegram_and_email(store):
    posture = personal_nt_security.security_posture(42)
    assert posture["factors"] == {"telegram": True, "email": True}
    assert posture["email_factor_via"] == "email"
    assert posture["ready"] is True


def test_posture_missing_email(store):
    posture = personal_nt_security.security_posture(7)
    assert posture["factors"]["telegram"] is True
    assert posture["factors"]["email"] is False
    assert posture["ready"] is False
    assert "email" in posture["missing"]


def test_posture_missing_telegram(store):
    posture = personal_nt_security.security_posture(8)
    assert posture["factors"]["telegram"] is False
    assert posture["factors"]["email"] is True
    assert "telegram" in posture["missing"]


def test_google_verified_email_satisfies_email_factor(store):
    posture = personal_nt_security.security_posture(9)
    assert posture["factors"] == {"telegram": True, "email": True}
    assert posture["email_factor_via"] == "google"
    assert posture["ready"] is True


def test_google_profile_fields_without_verified_identity_do_not_satisfy_factor(store):
    doc = account_auth._read_doc()
    doc["auth_identities"] = [
        row for row in doc["auth_identities"]
        if not (row.get("provider") == "google" and row.get("legacy_user_id") == 9)
    ]
    account_auth._write_doc(doc)

    posture = personal_nt_security.security_posture(9)

    assert posture["factors"] == {"telegram": True, "email": False}
    assert posture["ready"] is False
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.create_challenge(
            user_id=9, purpose="step_up", action="connector_revoke", provider="google",
        )
    assert exc.value.code == "provider_unavailable"


def test_owner_is_exempt(store):
    posture = personal_nt_security.security_posture(999)
    assert posture["is_owner"] is True
    assert posture["ready"] is True
    # Owner never needs a grant.
    assert personal_nt_security.require_step_up(999, action="pairing")["owner_exempt"] is True


# --------------------------------------------------------------------------- #
# require_ready.
# --------------------------------------------------------------------------- #
def test_require_ready_blocks_missing_factor(store):
    with pytest.raises(personal_nt_security.PersonalNtSecurityError) as exc:
        personal_nt_security.require_ready(7)
    assert exc.value.code == "personal_nt_onboarding_required"
    assert exc.value.onboarding is not None
    assert any(step["factor"] == "email" for step in exc.value.onboarding["onboarding"])


def test_require_ready_passes_when_ready(store):
    assert personal_nt_security.require_ready(42)["ready"] is True


# --------------------------------------------------------------------------- #
# Step-up grant lifecycle.
# --------------------------------------------------------------------------- #
def test_pairing_requires_step_up(store):
    with pytest.raises(personal_nt_security.PersonalNtSecurityError) as exc:
        personal_nt_security.require_step_up(42, action="pairing")
    assert exc.value.code == "step_up_required"
    assert exc.value.action == "pairing"


def test_step_up_grant_authorizes_action(store):
    _grant(42, "pairing")
    out = personal_nt_security.require_step_up(42, action="pairing")
    assert out["ok"] is True
    assert out["action"] == "pairing"


def test_step_up_grant_is_single_use(store):
    _grant(42, "pairing")
    personal_nt_security.require_step_up(42, action="pairing")
    with pytest.raises(personal_nt_security.PersonalNtSecurityError) as exc:
        personal_nt_security.require_step_up(42, action="pairing")
    assert exc.value.code == "step_up_required"


def test_step_up_grant_action_bound(store):
    _grant(42, "pairing")
    # A pairing grant cannot authorize a revoke.
    with pytest.raises(personal_nt_security.PersonalNtSecurityError) as exc:
        personal_nt_security.require_step_up(42, action="connector_revoke")
    assert exc.value.code == "step_up_required"


def test_step_up_grant_cross_user_isolated(store):
    _grant(42, "pairing")
    # Bob cannot consume Alice's grant.
    with pytest.raises(personal_nt_security.PersonalNtSecurityError) as exc:
        personal_nt_security.require_step_up(7, action="pairing")
    assert exc.value.code == "step_up_required"
    # Alice's grant is still intact.
    assert personal_nt_security.require_step_up(42, action="pairing")["ok"] is True


def test_step_up_grant_environment_bound(store, monkeypatch):
    _grant(42, "pairing")
    monkeypatch.setattr(personal_nt_security, "_current_environment", lambda: "canary")
    with pytest.raises(personal_nt_security.PersonalNtSecurityError) as exc:
        personal_nt_security.require_step_up(42, action="pairing")
    assert exc.value.code == "step_up_required"


def test_step_up_challenge_id_binding(store):
    cid = _grant(42, "pairing")
    # A wrong challenge_id does not match the grant.
    with pytest.raises(personal_nt_security.PersonalNtSecurityError):
        personal_nt_security.require_step_up(42, action="pairing", challenge_id="not-a-real-id")
    # The correct one works.
    assert personal_nt_security.require_step_up(42, action="pairing", challenge_id=cid)["ok"] is True


def test_begin_step_up_requires_factors_for_pairing(store):
    with pytest.raises(personal_nt_security.PersonalNtSecurityError) as exc:
        personal_nt_security.begin_step_up(7, action="pairing")
    assert exc.value.code == "personal_nt_onboarding_required"


def test_staging_grant_helper(store):
    out = personal_nt_security.grant_step_up_staging(7, action="connector_revoke")
    assert out["staging"] is True
    # The staging grant authorizes the action without a real code.
    assert personal_nt_security.require_step_up(7, action="connector_revoke")["ok"] is True


def test_invalid_action_rejected(store):
    with pytest.raises(personal_nt_security.PersonalNtSecurityError) as exc:
        personal_nt_security.require_step_up(42, action="not_a_real_action")
    assert exc.value.code == "action_invalid"


# --------------------------------------------------------------------------- #
# General NT gate: verified email now satisfies the identity factor.
# --------------------------------------------------------------------------- #
def test_nt_gate_accepts_verified_email_factor(store):
    doc = account_auth._read_doc()
    alice = account_auth._user(doc, 42)
    alice = dict(alice)
    alice["email_factor_ok"] = personal_nt_security.email_factor_ok(doc, account_auth._user(doc, 42))
    gate = account_auth.nt_action_gate(alice, session={})
    # Email factor present (no Google) -> identity factor OK, only Telegram left.
    assert gate["google_ok"] is True
    assert gate["email_factor_ok"] is True
    assert gate["code"] == "nt_telegram_confirm_required"


def test_require_nt_dual_auth_email_factor_then_telegram(store):
    import time
    # Alice has a verified email but no Google; with a Telegram-elevated session
    # the NT gate must pass.
    context = {
        "user_id": 42,
        "nt_elevated_until": time.time() + 600,
    }
    account_auth.require_nt_dual_auth(context)  # should not raise


# --------------------------------------------------------------------------- #
# Self-service identity unlink.
# --------------------------------------------------------------------------- #
def test_unlink_identity_self_keeps_last_method(store):
    # Carol has only one login identity (email) -> cannot unlink it.
    ids = account_auth.list_account_identities(8)["identities"]
    assert len(ids) == 1
    with pytest.raises(account_auth.AccountAuthError) as exc:
        account_auth.unlink_identity_self(8, identity_id=ids[0]["identity_id"])
    assert exc.value.code == "last_login_method"


def test_unlink_identity_self_removes_non_last(store):
    ids = account_auth.list_account_identities(42)["identities"]
    assert len(ids) == 2
    email_id = next(i["identity_id"] for i in ids if i["provider"] == "email")
    out = account_auth.unlink_identity_self(42, identity_id=email_id)
    assert out["provider"] == "email"
    remaining = account_auth.list_account_identities(42)["identities"]
    assert [i["provider"] for i in remaining] == ["telegram"]


def test_unlink_identity_cross_user_not_found(store):
    alice_ids = account_auth.list_account_identities(42)["identities"]
    email_id = next(i["identity_id"] for i in alice_ids if i["provider"] == "email")
    # Bob cannot unlink Alice's identity.
    with pytest.raises(account_auth.AccountAuthError) as exc:
        account_auth.unlink_identity_self(7, identity_id=email_id)
    assert exc.value.code == "identity_not_found"


# --------------------------------------------------------------------------- #
# Workspace mutations exist for default/capabilities.
# --------------------------------------------------------------------------- #
def test_workspace_capability_helpers_present():
    from app import workspaces
    assert hasattr(workspaces, "set_default_connection")
    assert hasattr(workspaces, "set_connection_capabilities")


# --------------------------------------------------------------------------- #
# Migration static contract.
# --------------------------------------------------------------------------- #
def test_migration_0007_is_additive():
    from app.production_storage.core import MigrationRunner

    migrations = {row["version"]: row for row in MigrationRunner.migrations()}
    assert 7 in migrations
    sql = str(migrations[7]["sql"]).lower()
    assert "drop table" not in sql
    assert "alter table sf_security_challenges" in sql
    assert "add column if not exists action" in sql
    assert "add column if not exists step_up_used_at" in sql


# --------------------------------------------------------------------------- #
# HTTP contract.
# --------------------------------------------------------------------------- #
def _login(uid: int) -> str:
    out = account_auth.create_session_for_user(
        uid, ip="203.0.113.5", user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/120",
        require_google=False, skip_dual_auth_gate=True,
    )
    return out["session_token"]


def _request(base, path, *, token="", csrf="", method="GET", body=None, origin=""):
    data = None
    headers = {"Origin": origin or base}
    if token:
        headers["Cookie"] = f"{account_auth.SESSION_COOKIE}={token}"
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _serve():
    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{server.server_address[0]}:{server.server_address[1]}"


def test_http_nt_security_posture_scoped(store):
    token = _login(7)
    server, base = _serve()
    try:
        _, page = _request(base, "/api/account/nt-security", token=token)
        assert page["factors"]["telegram"] is True
        assert page["factors"]["email"] is False
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/account/nt-security", origin="https://app.stratforge.example")
        assert exc.value.code == 401
    finally:
        server.shutdown()
        server.server_close()


def test_http_pairing_blocked_without_step_up(store):
    token = _login(42)
    ctx = account_auth.authenticate_session(token)
    csrf = ctx["csrf_token"]
    # Clear the workspace observation gate + dual-auth so the Phase 5 step-up is
    # the remaining blocker.
    account_auth.grant_nt_elevation_staging(42, session_id=ctx["session_id"])
    server, base = _serve()
    try:
        # Ready account, elevated, but no per-action grant -> blocked (403).
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/bridge/pair/start", token=token, csrf=csrf,
                     method="POST", body={"machine_label": "PC"})
        assert exc.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_http_step_up_start_onboarding_when_factor_missing(store):
    token = _login(7)  # Bob missing email
    ctx = account_auth.authenticate_session(token)
    csrf = ctx["csrf_token"]
    server, base = _serve()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/account/nt-security/step-up/start", token=token, csrf=csrf,
                     method="POST", body={"action": "pairing"})
        assert exc.value.code == 403
        payload = json.loads(exc.value.read().decode("utf-8"))
        assert payload["code"] == "personal_nt_onboarding_required"
        assert "onboarding" in payload
    finally:
        server.shutdown()
        server.server_close()


def test_http_step_up_start_confirm_creates_grant(store):
    token = _login(42)
    ctx = account_auth.authenticate_session(token)
    csrf = ctx["csrf_token"]
    server, base = _serve()
    try:
        _, started = _request(base, "/api/account/nt-security/step-up/start", token=token,
                              csrf=csrf, method="POST", body={"action": "pairing"})
        assert started["action"] == "pairing"
        code = started["test_code"]
        _request(base, "/api/account/nt-security/step-up/confirm", token=token, csrf=csrf,
                 method="POST", body={"challenge_id": started["challenge_id"], "code": code})
        # The confirmed grant authorizes exactly one pairing step-up server-side.
        assert personal_nt_security.require_step_up(42, action="pairing")["ok"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_http_staging_step_up_helper(store):
    token = _login(7)
    ctx = account_auth.authenticate_session(token)
    csrf = ctx["csrf_token"]
    server, base = _serve()
    try:
        status, out = _request(base, "/api/account/nt-security/step-up/staging", token=token,
                               csrf=csrf, method="POST", body={"action": "connector_revoke"})
        assert status == 200
        assert out["staging"] is True
        assert personal_nt_security.require_step_up(7, action="connector_revoke")["ok"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_http_identity_unlink_requires_step_up(store):
    token = _login(42)
    ctx = account_auth.authenticate_session(token)
    csrf = ctx["csrf_token"]
    ids = account_auth.list_account_identities(42)["identities"]
    email_id = next(i["identity_id"] for i in ids if i["provider"] == "email")
    server, base = _serve()
    try:
        # Without a step-up grant the unlink is refused.
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/account/identities/unlink", token=token, csrf=csrf,
                     method="POST", body={"identity_id": email_id})
        assert exc.value.code == 403
        payload = json.loads(exc.value.read().decode("utf-8"))
        assert payload["code"] == "step_up_required"
        # With a staging grant the unlink proceeds.
        _request(base, "/api/account/nt-security/step-up/staging", token=token, csrf=csrf,
                 method="POST", body={"action": "unlink_method"})
        status, out = _request(base, "/api/account/identities/unlink", token=token, csrf=csrf,
                               method="POST", body={"identity_id": email_id})
        assert status == 200
        assert out["provider"] == "email"
    finally:
        server.shutdown()
        server.server_close()
