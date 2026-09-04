"""Contracts for the rebuilt login / registration onboarding.

Registration is staged: identity is verified first, the StratForge handle and
the terms are applied last, and only then does an account exist.
"""
from __future__ import annotations

import pytest

from app import account_auth, google_auth


OWNER_UUID = "00000000-0000-4000-8000-000000000999"
EXISTING_UUID = "00000000-0000-4000-8000-000000000042"


@pytest.fixture()
def auth_store(tmp_path, monkeypatch):
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
    account_auth._write_doc({
        "version": 3,
        "users": [
            {
                "user_id": 999, "user_uuid": OWNER_UUID,
                "username": "owner", "first_name": "Owner", "last_name": "One",
                "role": "owner", "status": "active", "is_owner": True,
                "telegram_user_id": 999, "ux_mode": "professional",
                "email": "owner@example.com",
            },
            {
                "user_id": 42, "user_uuid": EXISTING_UUID,
                "username": "tg_alice", "handle": "alice",
                "first_name": "Alice", "last_name": "Ivanova",
                "role": "full_control", "status": "active", "is_owner": False,
                "telegram_user_id": 42, "email": "alice@example.com",
                "email_verified_at_utc": "2026-01-01T00:00:00Z",
                "ux_mode": "professional",
            },
        ],
        "auth_identities": [],
        "sessions": [],
        "challenges": [],
    })
    with account_auth._RATE_LOCK:
        account_auth._LOGIN_RATE.clear()
    yield tmp_path
    account_auth._clear_doc_cache()


# --------------------------------------------------------------------------- #
# StratForge handle
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value,expected", [
    ("Dmytro", "dmytro"),
    ("@dmytro", "dmytro"),
    ("  dmytro.trader  ", "dmytro.trader"),
    ("a_b_c", "a_b_c"),
])
def test_handle_is_normalised_to_one_canonical_form(auth_store, value, expected):
    assert account_auth.normalize_handle(value) == expected


@pytest.mark.parametrize("value,code", [
    ("", "handle_required"),
    ("ab", "handle_length"),
    ("x" * 33, "handle_length"),
    ("_dmytro", "handle_format"),
    ("dmytro-", "handle_format"),
    ("дмитрий", "handle_format"),
    ("a..b", "handle_format"),
    ("admin", "handle_reserved"),
])
def test_handle_rejects_unusable_names(auth_store, value, code):
    with pytest.raises(account_auth.AccountAuthError) as exc:
        account_auth.normalize_handle(value)
    assert getattr(exc.value, "code", "") == code


def test_handle_availability_reports_taken_names_without_revealing_owner(auth_store):
    taken = account_auth.handle_available("Alice")
    assert taken["available"] is False
    assert taken["code"] == "handle_taken"
    assert EXISTING_UUID not in str(taken)
    assert account_auth.handle_available("alice", user_uuid=EXISTING_UUID)["available"] is True
    assert account_auth.handle_available("brand.new")["available"] is True
    invalid = account_auth.handle_available("bad!name")
    assert invalid["available"] is False and invalid["code"] == "handle_format"


def test_telegram_login_never_overwrites_the_stratforge_handle(auth_store):
    """`username` mirrors Telegram; the handle belongs to the account."""
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, 42)
        user["username"] = "renamed_on_telegram"
        account_auth._write_doc(doc)
    with account_auth._LOCK:
        stored = account_auth._user(account_auth._read_doc(), 42)
    assert stored["handle"] == "alice"
    public = account_auth._public_user(stored)
    assert public["handle"] == "alice"
    assert public["username"] == "renamed_on_telegram"


def test_suggested_handle_is_only_a_free_starting_point(auth_store):
    assert account_auth.suggest_handle(email="Bob.New@example.com") == "bob.new"
    # An existing handle is never suggested for a second account.
    assert account_auth.suggest_handle(email="alice@example.com") != "alice"


# --------------------------------------------------------------------------- #
# Registration completion
# --------------------------------------------------------------------------- #
def _start_email(email: str) -> dict:
    return account_auth.start_email_auth(
        email, ip="127.0.0.1", user_agent="pytest",
    )


def test_email_registration_creates_the_account_only_at_the_consent_step(auth_store):
    started = _start_email("new.person@example.com")
    with account_auth._LOCK:
        before = [u for u in account_auth._read_doc()["users"]]
    assert all(str(u.get("email") or "") != "new.person@example.com" for u in before)

    with pytest.raises(account_auth.AccountAuthError) as refused:
        account_auth.complete_registration(
            method="email", challenge_id=started["challenge_id"],
            code=started["test_code"], handle="dmytro", first_name="Дмитрий",
            accept_terms=False, ip="127.0.0.1", user_agent="pytest",
        )
    assert getattr(refused.value, "code", "") == "terms_required"

    out = account_auth.complete_registration(
        method="email", challenge_id=started["challenge_id"],
        code=started["test_code"], handle="Dmytro", first_name="Дмитрий",
        last_name="", accept_terms=True, ip="127.0.0.1", user_agent="pytest",
    )
    assert out["status"] == "authenticated"
    assert out["user"]["handle"] == "dmytro"
    assert out["user"]["first_name"] == "Дмитрий"
    # An omitted family name is stored explicitly, never guessed.
    assert out["user"]["last_name"] == "—"


def test_registration_refuses_a_handle_that_is_already_taken(auth_store):
    started = _start_email("second.person@example.com")
    with pytest.raises(account_auth.AccountAuthError) as taken:
        account_auth.complete_registration(
            method="email", challenge_id=started["challenge_id"],
            code=started["test_code"], handle="alice", first_name="Пётр",
            accept_terms=True, ip="127.0.0.1", user_agent="pytest",
        )
    assert getattr(taken.value, "code", "") == "handle_taken"
    # The e-mail challenge is untouched, so the person can retry with a free
    # name instead of restarting the whole registration.
    out = account_auth.complete_registration(
        method="email", challenge_id=started["challenge_id"],
        code=started["test_code"], handle="petr", first_name="Пётр",
        accept_terms=True, ip="127.0.0.1", user_agent="pytest",
    )
    assert out["user"]["handle"] == "petr"


def test_unknown_registration_method_is_rejected(auth_store):
    with pytest.raises(account_auth.AccountAuthError) as exc:
        account_auth.complete_registration(
            method="passkey", challenge_id="x", handle="dmytro",
            first_name="Дмитрий", accept_terms=True,
        )
    assert getattr(exc.value, "code", "") == "method_invalid"


# --------------------------------------------------------------------------- #
# Staged Google registration
# --------------------------------------------------------------------------- #
def test_google_registration_is_staged_then_consumed_once(auth_store):
    identity = google_auth.fake_identity(google_sub="sub-new", email="new.g@example.com")
    staged = account_auth.stage_google_registration(
        google_sub=identity["google_sub"], google_email=identity["google_email"],
        google_name="New Person", email_verified=True, ip="127.0.0.1",
    )
    state = account_auth.registration_state(staged["registration_id"])
    assert state["provider"] == "google"
    assert state["email"] == "new.g@example.com"
    assert state["suggested_handle"]

    out = account_auth.complete_registration(
        method="google", challenge_id=staged["registration_id"],
        handle="newperson", first_name="New", last_name="Person",
        accept_terms=True, ip="127.0.0.1", user_agent="pytest",
    )
    assert out["user"]["handle"] == "newperson"

    with pytest.raises(account_auth.AccountAuthError) as replay:
        account_auth.complete_registration(
            method="google", challenge_id=staged["registration_id"],
            handle="secondname", first_name="New", accept_terms=True,
        )
    assert getattr(replay.value, "code", "") == "registration_expired"


def test_google_registration_refuses_an_already_registered_identity(auth_store):
    identity = google_auth.fake_identity(google_sub="sub-twice", email="twice@example.com")
    staged = account_auth.stage_google_registration(
        google_sub=identity["google_sub"], google_email=identity["google_email"],
        email_verified=True, ip="127.0.0.1",
    )
    account_auth.complete_registration(
        method="google", challenge_id=staged["registration_id"],
        handle="twiceuser", first_name="Twice", accept_terms=True,
    )
    with pytest.raises(account_auth.AccountAuthError) as again:
        account_auth.stage_google_registration(
            google_sub=identity["google_sub"], google_email=identity["google_email"],
            email_verified=True, ip="127.0.0.1",
        )
    assert getattr(again.value, "code", "") == "google_already_registered"


def test_google_registration_requires_a_verified_email(auth_store):
    with pytest.raises(account_auth.AccountAuthError):
        account_auth.stage_google_registration(
            google_sub="sub-unverified", google_email="x@example.com",
            email_verified=False, ip="127.0.0.1",
        )


def test_expired_registration_state_is_reported_as_expired(auth_store):
    staged = account_auth.stage_google_registration(
        google_sub="sub-expiring", google_email="expiring@example.com",
        email_verified=True, ip="127.0.0.1",
    )
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        for row in doc["challenges"]:
            row["expires_at"] = 0
        account_auth._write_doc(doc)
    with pytest.raises(account_auth.AccountAuthError) as exc:
        account_auth.registration_state(staged["registration_id"])
    assert getattr(exc.value, "code", "") == "registration_expired"


# --------------------------------------------------------------------------- #
# Cross-module identity: registration -> profile -> SF Social / SF Chat
# --------------------------------------------------------------------------- #
def test_social_identity_uses_the_stratforge_handle_not_the_telegram_mirror(auth_store):
    """The name chosen at registration is the name other members see."""
    from app import server as server_mod

    handler = object.__new__(server_mod.Handler)
    handler._remote_context = {
        "user_id": 42,
        "is_owner": False,
        "ux_mode": "professional",
        "user": {
            "user_uuid": EXISTING_UUID,
            "handle": "alice",
            # Telegram rewrites this on every login; an e-mail/Google account
            # has no value here at all.
            "username": "",
            "first_name": "Alice",
            "last_name": "—",
            "created_at_utc": "2026-01-01T00:00:00Z",
        },
    }
    actor = handler._community_actor()
    assert actor["username"] == "alice"
    # The optional-family-name placeholder is account bookkeeping, not a name.
    assert actor["display_name"] == "Alice"

    handler._remote_context["user"].update({"handle": "", "username": "tg_only"})
    legacy = handler._community_actor()
    assert legacy["username"] == "tg_only", "legacy Telegram accounts keep working"


def test_social_accepts_every_handle_the_account_contract_allows(auth_store):
    """One person, one name: Social must not rewrite a legitimate handle."""
    from app import community

    for handle in ("dmytro", "sf.trader", "a_b_c", "x" * 32):
        normalized = account_auth.normalize_handle(handle)
        assert community._normalise_username(normalized, "sfp_abcdefghij") == normalized, handle

    # A value the account contract would never mint still falls back safely.
    assert community._normalise_username("", "sfp_abcdefghij").startswith("sf_")
    assert community._normalise_username(".bad", "sfp_abcdefghij").startswith("sf_")


def test_pending_window_is_short_but_still_allows_one_resend(auth_store):
    """The unconfirmed window closes fast without stranding a late code."""
    from app import security_devices

    assert security_devices.PENDING_SESSION_TTL_SEC == 120
    # A resend costs the cooldown plus delivery and typing; if that no longer
    # fits, the resend button becomes decoration.
    assert (
        security_devices.CHALLENGE_RESEND_COOLDOWN_SEC + 45
        <= security_devices.PENDING_SESSION_TTL_SEC
    )
    # The OTP itself may live longer, but the session gate is what expires.
    assert security_devices.PENDING_SESSION_TTL_SEC < security_devices.CHALLENGE_TTL_SEC
