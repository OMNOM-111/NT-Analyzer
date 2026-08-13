"""Phase 7 — Developer Preview / View-As and Development bootstrap.

These tests verify the Development-only developer preview: the single-use
loopback bootstrap, the View-As personas that apply real server-side
permissions without changing real roles, and the fail-closed behaviour in
Canary and Production. No real Connector, account, PII or network is involved.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, dev_preview, google_auth, runtime_env, server


@pytest.fixture()
def dev_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(google_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(account_auth.secure_store, "_protect", lambda b: b)
    monkeypatch.setattr(account_auth.secure_store, "_unprotect", lambda b: b)
    monkeypatch.setattr(account_auth.secure_store, "available", lambda: True)
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
    return tmp_path


def _session_user_id(store_token: str) -> int:
    import hashlib
    digest = hashlib.sha256(store_token.encode()).hexdigest()
    doc = account_auth._read_doc()
    for session in doc.get("sessions") or []:
        if session.get("token_hash") == digest and not session.get("revoked"):
            return int(session.get("user_id") or 0)
    return 0


# --------------------------------------------------------------------------- #
# Fail-closed outside Development.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("env", ["canary", "production"])
def test_dev_preview_disabled_outside_development(dev_store, monkeypatch, env):
    monkeypatch.setenv("DEPLOYMENT_ENV", env)
    for call in (
        lambda: dev_preview.status(999),
        lambda: dev_preview.start_view_as(999, "ordinary"),
        lambda: dev_preview.mint_bootstrap_token(999),
        lambda: dev_preview.redeem_bootstrap_token("x" * 40, is_loopback=True),
        lambda: dev_preview.return_to_developer(),
    ):
        with pytest.raises(dev_preview.DevPreviewError) as excinfo:
            call()
        assert excinfo.value.code == "dev_preview_disabled"


def test_dev_preview_disabled_when_test_auth_explicitly_off(dev_store, monkeypatch):
    # Development QA is default-on; it is disabled only when explicitly turned off.
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "0")
    with pytest.raises(dev_preview.DevPreviewError) as excinfo:
        dev_preview.status(999)
    assert excinfo.value.code == "dev_preview_disabled"


# --------------------------------------------------------------------------- #
# Bootstrap: single-use, loopback-only, expiry, cross-env.
# --------------------------------------------------------------------------- #
def test_bootstrap_roundtrip_is_single_use(dev_store):
    minted = dev_preview.mint_bootstrap_token(999)
    token = minted["token"]
    redeemed = dev_preview.redeem_bootstrap_token(token, is_loopback=True)
    assert redeemed["owner_id"] == 999
    assert _session_user_id(redeemed["session_token"]) == 999
    # A second redemption of the same token is rejected.
    with pytest.raises(dev_preview.DevPreviewError) as excinfo:
        dev_preview.redeem_bootstrap_token(token, is_loopback=True)
    assert excinfo.value.code == "token_used"


def test_bootstrap_requires_loopback(dev_store):
    token = dev_preview.mint_bootstrap_token(999)["token"]
    with pytest.raises(dev_preview.DevPreviewError) as excinfo:
        dev_preview.redeem_bootstrap_token(token, is_loopback=False)
    assert excinfo.value.code == "loopback_required"


def test_bootstrap_expired_token_is_rejected(dev_store):
    dev_preview.mint_bootstrap_token(999)
    doc = account_auth._read_doc()
    doc["dev_bootstrap_tokens"][-1]["expires_at"] = time.time() - 1
    account_auth._write_doc(doc)
    # Recover the token by minting again would rotate it; instead reject the
    # stored expired row by hash-matching a fresh mint's expiry manipulation.
    token = dev_preview.mint_bootstrap_token(999)["token"]
    doc = account_auth._read_doc()
    doc["dev_bootstrap_tokens"][-1]["expires_at"] = time.time() - 1
    account_auth._write_doc(doc)
    with pytest.raises(dev_preview.DevPreviewError) as excinfo:
        dev_preview.redeem_bootstrap_token(token, is_loopback=True)
    assert excinfo.value.code == "token_expired"


def test_bootstrap_cross_environment_token_is_rejected(dev_store):
    token = dev_preview.mint_bootstrap_token(999)["token"]
    # Simulate a token stamped for another environment.
    doc = account_auth._read_doc()
    doc["dev_bootstrap_tokens"][-1]["environment"] = "canary"
    account_auth._write_doc(doc)
    with pytest.raises(dev_preview.DevPreviewError) as excinfo:
        dev_preview.redeem_bootstrap_token(token, is_loopback=True)
    assert excinfo.value.code == "token_wrong_environment"


def test_bootstrap_audit_has_no_raw_token(dev_store, monkeypatch):
    records = []
    original = account_auth._audit
    monkeypatch.setattr(
        account_auth, "_audit",
        lambda event, **kwargs: records.append((event, kwargs)),
    )
    minted = dev_preview.mint_bootstrap_token(999)
    token = minted["token"]
    monkeypatch.setattr(account_auth, "_audit", original)
    dev_preview.redeem_bootstrap_token(token, is_loopback=True)
    serialized = repr(records)
    assert token not in serialized
    assert any(event == "dev.bootstrap_minted" for event, _ in records)


# --------------------------------------------------------------------------- #
# View As: real permissions, no real-role change.
# --------------------------------------------------------------------------- #
def test_view_as_does_not_change_real_permissions(dev_store):
    dev_preview.ensure_personas()
    out = dev_preview.start_view_as(999, "ordinary")
    # The preview session belongs to the ordinary persona, not the owner.
    persona_uid = _session_user_id(out["session_token"])
    assert persona_uid == dev_preview._PERSONAS["ordinary"]["uid"]
    doc = account_auth._read_doc()
    owner = account_auth._user(doc, 999)
    persona = account_auth._user(doc, persona_uid)
    # Real owner is untouched; persona keeps its own limited role.
    assert owner["is_owner"] is True
    assert owner["role"] == "owner"
    assert persona.get("is_owner") in (None, False)
    assert persona["role"] == "read_only"


def test_ordinary_persona_has_no_admin_capabilities(dev_store):
    dev_preview.ensure_personas()
    doc = account_auth._read_doc()
    persona = account_auth._user(doc, dev_preview._PERSONAS["ordinary"]["uid"])
    assert not persona.get("admin_permission_grants")
    assert persona.get("is_owner") in (None, False)


def test_developer_persona_sees_only_its_capabilities(dev_store):
    dev_preview.ensure_personas()
    doc = account_auth._read_doc()
    persona = account_auth._user(doc, dev_preview._PERSONAS["developer"]["uid"])
    grants = persona.get("admin_permission_grants") or {}
    assert set(grants) == set(dev_preview._DEVELOPER_GRANTS)
    # Developer is explicitly not the owner.
    assert persona.get("is_owner") in (None, False)
    assert "admin.manage" not in grants


def test_owner_persona_matches_owner_contract(dev_store):
    out = dev_preview.start_view_as(999, "owner")
    # The owner persona reuses the owner's own identity (owner_self).
    assert _session_user_id(out["session_token"]) == 999


def test_unauthenticated_persona_clears_session(dev_store):
    out = dev_preview.start_view_as(999, "unauthenticated")
    assert out.get("clear_session") is True
    assert "session_token" not in out


def test_unauthenticated_persona_sets_loopback_preview_mode(dev_store):
    handler = object.__new__(server.Handler)
    handler._check_local_post = lambda: True
    handler._read_body = lambda: {"persona": "unauthenticated"}
    handler._remote_context = {"user_id": 999}
    handler.headers = {}
    handler._request_ips = lambda: ("127.0.0.1", "")
    actions = []
    handler._clear_session_cookie = lambda: actions.append("session_cleared")
    handler._set_dev_preview_mode_cookie = lambda mode: actions.append(
        f"preview:{mode}"
    )
    handler._set_session_cookie = lambda _token: actions.append("session_set")
    handler._json = lambda _status, payload: actions.append(payload["persona"])

    handler._dev_preview_post("/api/dev/preview/view-as")

    assert actions == ["session_cleared", "preview:unauthenticated", "unauthenticated"]


def test_loopback_preview_mode_disables_local_owner_fallback(dev_store):
    handler = object.__new__(server.Handler)
    handler._cookie_value = lambda name: (
        "unauthenticated" if name == server._DEV_PREVIEW_MODE_COOKIE else ""
    )
    assert handler._local_development_cookie_context() is None


def test_auth_status_exposes_dev_preview_preset(dev_store):
    preview = dev_preview.start_view_as(999, "developer")
    token = str(preview["session_token"])
    httpd = ThreadingHTTPServer((server.HOST, 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://{httpd.server_address[0]}:{httpd.server_address[1]}/api/auth/status",
            headers={
                "Cookie": f"{runtime_env.session_cookie_name()}={token}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["authenticated"] is True
        assert payload["impersonating"] is True
        assert payload["impersonation_preset"] == "dev_preview"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_exit_restores_owner_session(dev_store):
    dev_preview.ensure_personas()
    preview = dev_preview.start_view_as(999, "ordinary")
    restored = dev_preview.exit_view_as(999, preview["session_token"])
    assert restored["restored"] is True
    assert _session_user_id(restored["session_token"]) == 999
    # The preview session is revoked.
    assert _session_user_id(preview["session_token"]) == 0


def test_return_to_developer_recovers_from_any_persona(dev_store):
    dev_preview.ensure_personas()
    dev_preview.start_view_as(999, "ordinary")
    restored = dev_preview.return_to_developer()
    assert restored["restored"] is True
    assert _session_user_id(restored["session_token"]) == 999


def test_status_reports_personas_and_owner_availability(dev_store):
    status = dev_preview.status(999)
    assert status["available"] is True
    assert status["bootstrap_available"] is True
    persona_ids = {p["id"] for p in status["personas"]}
    assert {"unauthenticated", "ordinary", "developer", "owner"} <= persona_ids


def test_non_owner_cannot_start_view_as(dev_store):
    dev_preview.ensure_personas()
    ordinary_uid = dev_preview._PERSONAS["ordinary"]["uid"]
    with pytest.raises(dev_preview.DevPreviewError) as excinfo:
        dev_preview.start_view_as(ordinary_uid, "developer")
    assert excinfo.value.code == "owner_required"


def test_non_owner_cannot_mint_bootstrap(dev_store):
    dev_preview.ensure_personas()
    ordinary_uid = dev_preview._PERSONAS["ordinary"]["uid"]
    with pytest.raises(dev_preview.DevPreviewError) as excinfo:
        dev_preview.mint_bootstrap_token(ordinary_uid)
    assert excinfo.value.code == "owner_required"
