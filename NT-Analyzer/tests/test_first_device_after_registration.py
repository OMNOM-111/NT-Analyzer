"""The first device confirmation right after registration asks only for a mode.

The person has just proved who they are with a one-time code; sending a second
code seconds later proves nothing and only stands between them and the product.
This exercises the real registration path, not a hand-built session.
"""
from __future__ import annotations

import pytest

from app import account_auth, security_devices


UA = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/126 Safari/537.36"


@pytest.fixture()
def store(tmp_path, monkeypatch):
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
        "users": [{
            "user_id": 999, "user_uuid": "00000000-0000-4000-8000-000000000999",
            "username": "owner", "first_name": "Owner",
            "role": "owner", "status": "active", "is_owner": True,
            "telegram_user_id": 999, "ux_mode": "professional",
        }],
        "auth_identities": [], "challenges": [], "sessions": [],
        "trusted_devices": [], "physical_devices": [], "security_challenges": [],
        "identity_schema": {"stage": "dual_write", "canonical_key": "user_uuid"},
    })
    return tmp_path


def _register(email="new@example.com", handle="newcomer"):
    started = account_auth.start_email_auth(email, ip="203.0.113.9", user_agent=UA)
    return account_auth.complete_registration(
        method="email",
        challenge_id=started["challenge_id"],
        code=started.get("test_code") or "",
        email=email,
        handle=handle,
        first_name="New",
        accept_terms=True,
        ip="203.0.113.9",
        user_agent=UA,
    )


def test_registration_lands_on_a_confirmation_that_needs_no_second_code(store):
    session = _register()
    context = account_auth.authenticate_session(session["session_token"])
    access = security_devices.current_session_access(
        context["user_id"], context["session_id"],
    )
    assert access["state"] == "pending"
    assert access["fresh_signin_provider"] == "email"
    assert access["code_required"] is False

    out = security_devices.approve_device(
        user_id=context["user_id"], device_id=access["client"]["id"],
        challenge_id="", code="", trust_mode="permanent",
        session_id=context["session_id"],
    )
    assert out["ok"] is True
    after = account_auth.authenticate_session(session["session_token"])
    assert after["device_access"]["state"] == "active"
