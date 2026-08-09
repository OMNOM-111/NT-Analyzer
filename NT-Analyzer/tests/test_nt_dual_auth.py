"""NinjaTrader dual-auth: Google + Telegram confirm only for NT actions."""
from __future__ import annotations

import hashlib
import time

import pytest

from app import account_auth


@pytest.fixture()
def nt_auth_store(tmp_path, monkeypatch):
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    monkeypatch.setenv("NTA_NT_GOOGLE_REQUIRED", "1")
    monkeypatch.setenv("NTA_NT_TELEGRAM_CONFIRM_REQUIRED", "1")
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
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
                "google_sub": "owner-google",
            },
            {
                "user_id": 42, "username": "alice", "first_name": "Alice",
                "role": "full_control", "status": "active", "is_owner": False,
            },
        ],
        "challenges": [],
        "sessions": [],
    })
    return tmp_path


def test_login_does_not_require_google(nt_auth_store):
    user = account_auth._user(account_auth._read_doc(), 42)
    assert account_auth.user_needs_google(user) is True  # informational for NT
    public = account_auth._public_user(user)
    assert public["dual_auth_complete"] is True
    assert public["google_linked"] is False


def test_nt_gate_requires_google_then_telegram(nt_auth_store):
    user = account_auth._user(account_auth._read_doc(), 42)
    gate = account_auth.nt_action_gate(user, session={})
    assert gate["ok"] is False
    assert gate["code"] == "nt_google_required"

    account_auth.link_google_identity(
        42, google_sub="g-alice", google_email="a@example.com", email_verified=True,
    )
    user = account_auth._user(account_auth._read_doc(), 42)
    gate = account_auth.nt_action_gate(user, session={})
    assert gate["google_ok"] is True
    assert gate["telegram_ok"] is False
    assert gate["code"] == "nt_telegram_confirm_required"

    session = {
        "session_id": "sess_abc",
        "user_id": 42,
        "nt_elevated_until": time.time() + 600,
        "revoked": False,
        "expires_at": time.time() + 9999,
        "token_hash": "x",
    }
    gate2 = account_auth.nt_action_gate(user, session=session)
    assert gate2["ok"] is True


def test_nt_gate_reads_public_user_google_linked_flag(nt_auth_store):
    """Auth context uses _public_user without raw google_sub — gate must still pass."""
    account_auth.link_google_identity(
        42, google_sub="g-alice", google_email="a@example.com", email_verified=True,
    )
    raw = account_auth._user(account_auth._read_doc(), 42)
    public = account_auth._public_user(raw, include_contact=True)
    assert "google_sub" not in public or not public.get("google_sub")
    assert public["google_linked"] is True
    gate = account_auth.nt_action_gate(
        public,
        context={
            "user": public,
            "is_owner": False,
            "nt_elevated_until": time.time() + 600,
        },
    )
    assert gate["ok"] is True
    assert gate["google_ok"] is True


def test_owner_exempt_from_nt_dual_auth(nt_auth_store):
    owner = account_auth._user(account_auth._read_doc(), 999)
    assert account_auth.nt_action_gate(owner)["ok"] is True


def test_forged_google_linked_flag_rejected_by_store_lookup(nt_auth_store):
    """Public payload google_linked=True without store google_sub must fail."""
    with pytest.raises(account_auth.AccountAuthError) as exc:
        account_auth.require_nt_dual_auth({
            "user_id": 42,
            "is_owner": False,
            "nt_elevated_until": time.time() + 600,
            "user": {
                "user_id": 42,
                "is_owner": False,
                "google_linked": True,  # forged
            },
        })
    assert exc.value.status == 403
    assert exc.value.code == "nt_google_required"


def test_telegram_confirm_callback_elevates_session(nt_auth_store):
    account_auth.link_google_identity(
        42, google_sub="g-alice", google_email="a@example.com", email_verified=True,
    )
    token = "t" * 48
    csrf = "c" * 32
    doc = account_auth._read_doc()
    doc["sessions"].append({
        "session_id": "sess_user42",
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(),
        "csrf_token": csrf,
        "user_id": 42,
        "created_at_utc": "2026-07-15T00:00:00Z",
        "expires_at": time.time() + 99999,
        "revoked": False,
    })
    doc["sessions"].append({
        "session_id": "sess_other_device",
        "token_hash": hashlib.sha256(b"other-token").hexdigest(),
        "csrf_hash": hashlib.sha256(b"other-csrf").hexdigest(),
        "csrf_token": "other-csrf",
        "user_id": 42,
        "created_at_utc": "2026-07-15T00:00:01Z",
        "expires_at": time.time() + 99999,
        "revoked": False,
    })
    account_auth._write_doc(doc)

    started = account_auth.start_nt_telegram_confirm(42, session_id="sess_user42", api_call=None)
    cid = started["challenge_id"]
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        result, uid = account_auth._apply_nt_confirm_callback(
            doc, challenge_id=cid, allowed=True, actor_id=42,
        )
        account_auth._write_doc(doc)
    assert result == "confirmed" and uid == 42
    sess = next(s for s in account_auth._read_doc()["sessions"] if s["session_id"] == "sess_user42")
    assert float(sess.get("nt_elevated_until") or 0) > time.time()
    other = next(s for s in account_auth._read_doc()["sessions"] if s["session_id"] == "sess_other_device")
    assert not float(other.get("nt_elevated_until") or 0)


def test_telegram_confirm_requires_specific_active_session(nt_auth_store):
    account_auth.link_google_identity(
        42, google_sub="g-alice", google_email="a@example.com", email_verified=True,
    )
    with pytest.raises(account_auth.AccountAuthError) as exc:
        account_auth.start_nt_telegram_confirm(42, session_id="", api_call=None)
    assert exc.value.code == "nt_session_required"


def test_path_requires_nt_dual_auth():
    assert account_auth.path_requires_nt_dual_auth("/api/workspaces/personal", "POST")
    assert account_auth.path_requires_nt_dual_auth("/api/bridge/pair/start", "POST")
    assert account_auth.path_requires_nt_dual_auth("/api/bridge/connections/c1/revoke", "POST")
    assert account_auth.path_requires_nt_dual_auth("/api/ops/runtime/command", "POST")
    assert account_auth.path_requires_nt_dual_auth("/api/ops/strategies/x/paper/arm", "POST")
    assert not account_auth.path_requires_nt_dual_auth("/api/demo-backtests", "POST")
    assert not account_auth.path_requires_nt_dual_auth("/api/community/message", "POST")
    assert not account_auth.path_requires_nt_dual_auth("/api/workspaces/personal", "GET")
