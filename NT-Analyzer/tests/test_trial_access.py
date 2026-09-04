from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import account_auth, secure_store, subscriptions


@pytest.fixture
def trial_store(monkeypatch, tmp_path):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(subscriptions, "_root", lambda: tmp_path)
    monkeypatch.setattr(secure_store, "available", lambda: True)
    monkeypatch.setattr(secure_store, "backend_name", lambda: "test DPAPI")
    monkeypatch.setattr(secure_store, "_protect", lambda value: value[::-1])
    monkeypatch.setattr(secure_store, "_unprotect", lambda value: value[::-1])
    account_auth._clear_doc_cache()
    subscriptions._clear_doc_cache()
    return tmp_path


def _seed_accounts() -> tuple[str, str]:
    owner_uuid = "5d9a7d97-22f6-44ad-8ddd-77f0f390d0a3"
    user_uuid = "c3fafab6-551e-4f39-b641-1e8675504ce7"
    account_auth._write_doc({
        "version": 3,
        "users": [
            {
                "user_id": 999, "legacy_user_id": 999, "user_uuid": owner_uuid,
                "first_name": "Owner", "last_name": "One", "email": "owner@example.com",
                "role": "owner", "status": "active", "is_owner": True,
            },
            {
                "user_id": 42, "legacy_user_id": 42, "user_uuid": user_uuid,
                "first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com",
                "role": "full_control", "status": "active", "is_owner": False,
                "ux_mode": "professional",
            },
        ],
        "auth_identities": [], "challenges": [], "sessions": [],
    })
    return owner_uuid, user_uuid


def test_initial_trial_is_full_seven_days_and_never_restarts(trial_store) -> None:
    _owner_uuid, user_uuid = _seed_accounts()

    first = subscriptions.ensure_initial_trial(
        42, user_uuid=user_uuid, source="telegram_mini_app",
    )
    assert first["created"] is True
    assert first["entitlement"]["plan_id"] == subscriptions.TRIAL_PLAN_ID
    assert first["entitlement"]["access_kind"] == "initial_trial"
    assert all(first["entitlement"]["plan"]["features"].values())
    starts = datetime.fromisoformat(first["access"]["starts_at_utc"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(first["access"]["expires_at_utc"].replace("Z", "+00:00"))
    # The grant is spent in active use; the calendar expiry is only an outer
    # bound so an untouched account keeps the hours it never used.
    assert expires - starts == timedelta(days=subscriptions.TRIAL_CALENDAR_BOUND_DAYS)
    usage = subscriptions.trial_usage_for_user(42)
    assert usage["limit_sec"] == subscriptions.trial_active_seconds_limit()
    assert usage["expired"] is False

    second = subscriptions.ensure_initial_trial(
        42, user_uuid=user_uuid, source="google_verified_registration",
    )
    assert second["created"] is False
    assert second["entitlement"]["entitlement_id"] == first["entitlement"]["entitlement_id"]
    assert second["access"]["expires_at_utc"] == first["access"]["expires_at_utc"]
    assert [row["event"] for row in second["access"]["history"]] == ["initial_trial_granted"]


def test_owner_extends_from_current_boundary_or_exact_utc_with_history(trial_store) -> None:
    owner_uuid, user_uuid = _seed_accounts()
    initial = subscriptions.ensure_initial_trial(42, user_uuid=user_uuid)
    initial_expiry = datetime.fromisoformat(initial["access"]["expires_at_utc"].replace("Z", "+00:00"))

    by_days = subscriptions.extend_trial_access(
        999, 42, days=3, reason="QA acceptance extension",
        idempotency_key="extend-days-1",
    )
    days_expiry = datetime.fromisoformat(by_days["access"]["expires_at_utc"].replace("Z", "+00:00"))
    assert days_expiry - initial_expiry == timedelta(days=3)
    newest = by_days["access"]["history"][0]
    assert newest["event"] == "trial_extended"
    assert newest["actor_user_id"] == 999
    assert newest["actor_user_uuid"] == owner_uuid
    assert newest["reason"] == "QA acceptance extension"
    assert newest["before"]["expires_at_utc"] == initial["access"]["expires_at_utc"]

    exact = (days_expiry + timedelta(days=2)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    by_date = subscriptions.extend_trial_access(
        999, 42, expires_at_utc=exact, reason="Owner chose exact date",
        idempotency_key="extend-date-1",
    )
    assert by_date["access"]["expires_at_utc"] == exact.replace(".000000", "")
    replay = subscriptions.extend_trial_access(
        999, 42, expires_at_utc=(days_expiry + timedelta(days=5)).isoformat(),
        idempotency_key="extend-date-1",
    )
    assert replay["replayed"] is True
    assert replay["access"]["expires_at_utc"] == by_date["access"]["expires_at_utc"]
    assert len(replay["access"]["history"]) == 3


def test_extension_validation_and_existing_plan_conflict(trial_store) -> None:
    _seed_accounts()
    with pytest.raises(subscriptions.SubscriptionError):
        subscriptions.extend_trial_access(999, 42)
    with pytest.raises(subscriptions.SubscriptionError):
        subscriptions.extend_trial_access(999, 42, days=2, expires_at_utc="2030-01-01T00:00:00Z")
    with pytest.raises(subscriptions.SubscriptionError):
        subscriptions.extend_trial_access(999, 42, expires_at_utc="2030-01-01")

    subscriptions.grant_plan(999, 42, "pro", duration_days=30)
    recorded = subscriptions.ensure_initial_trial(42)
    assert recorded["entitlement"]["status"] == "superseded"
    with pytest.raises(subscriptions.SubscriptionError) as exc:
        subscriptions.extend_trial_access(999, 42, days=1)
    assert exc.value.status == 409


def test_verified_telegram_registration_is_professional_and_trial_is_idempotent(trial_store) -> None:
    account_auth.ensure_owner(999)
    out = account_auth.register_via_telegram(
        {"id": 42, "first_name": "Ada", "last_name": "Lovelace", "username": "ada"},
        email="ada@example.com", accept_terms=True, owner_chat_id="999",
    )
    assert out["status"] == "active" and out["authenticated"] is True
    user = account_auth._user(account_auth._read_doc(), 42)
    assert user["role"] == "full_control"
    assert user["ux_mode"] == "professional"
    assert user["initial_trial_pending"] is False
    first = subscriptions.trial_access_for_user(42)
    assert first["state"] == "active"

    account_auth.register_via_telegram(
        {"id": 42, "first_name": "Ada", "last_name": "Lovelace", "username": "ada"},
        email="ada@example.com", accept_terms=True, owner_chat_id="999",
    )
    second = subscriptions.trial_access_for_user(42)
    assert second["expires_at_utc"] == first["expires_at_utc"]
    assert len(second["history"]) == 1


def test_verified_email_and_google_registrations_activate_with_one_trial_each(trial_store, monkeypatch) -> None:
    monkeypatch.setattr(account_auth, "email_auth_status", lambda: {"available": True})
    account_auth.ensure_owner(999)

    email_start = account_auth.start_email_auth("ada@example.com", ip="127.0.0.1")
    email_login = account_auth.verify_email_auth(
        email_start["challenge_id"], code=email_start["test_code"],
        profile={"first_name": "Ada", "last_name": "Lovelace", "accept_terms": True},
        ip="127.0.0.1", user_agent="pytest", owner_chat_id="999",
    )
    assert email_login["status"] == "authenticated"

    google_login = account_auth.login_via_google_identity(
        google_sub="google-grace", google_email="grace@example.com", google_name="Grace Hopper",
        email_verified=True, accept_terms=True, ip="127.0.0.1", user_agent="pytest",
        owner_chat_id="999",
    )
    assert google_login["status"] == "authenticated"

    doc = account_auth._read_doc()
    humans = [row for row in doc["users"] if not row.get("is_owner")]
    assert len(humans) == 2
    for human in humans:
        assert human["status"] == "active"
        assert human["role"] == "full_control"
        assert human["ux_mode"] == "professional"
        access = subscriptions.trial_access_for_user(human["user_id"])
        assert access["state"] == "active"
        assert len(access["history"]) == 1
