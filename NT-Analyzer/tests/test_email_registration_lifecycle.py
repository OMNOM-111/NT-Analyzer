"""Real temporary auth-store lifecycle behind the staged e-mail UI.

No browser/runtime data or provider transport is used. These tests distinguish
the final registration TTL/replay contract from manual visual acceptance.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app import account_auth
from tests.test_auth_onboarding import auth_store  # noqa: F401 - existing isolated fixture
from tests.test_preview_sandbox import preview_env  # noqa: F401 - real Preview data-root isolation


EMAIL = "email-lifecycle@example.invalid"
UA = "Email lifecycle disposable test"


@pytest.fixture(params=("auth_store", "preview_env"), ids=("development", "preview"))
def storage(request):
    return request.getfixturevalue(request.param)


@pytest.fixture
def clock(monkeypatch, storage):
    current = SimpleNamespace(value=time.time())
    # Patch only account_auth's clock; do not change pytest or other modules'
    # time module and do not sleep through the ten-minute proof lifetime.
    monkeypatch.setattr(account_auth, "time", SimpleNamespace(time=lambda: current.value))
    return current


def start():
    return account_auth.start_email_auth(EMAIL, ip="127.0.0.1", user_agent=UA)


def complete(opened, **changes):
    values = dict(method="email", challenge_id=opened["challenge_id"],
                  code=opened["test_code"], email=EMAIL, handle="email.lifecycle",
                  first_name="Lifecycle", last_name="", accept_terms=True,
                  ip="127.0.0.1", user_agent=UA, device_credential="disposable-email-client")
    values.update(changes)
    return account_auth.complete_registration(**values)


def state():
    with account_auth._LOCK:
        return account_auth._read_doc()


def users():
    return [row for row in state()["users"] if row.get("email") == EMAIL]


def challenge(opened):
    return next(row for row in state()["challenges"] if row["challenge_id"] == opened["challenge_id"])


def test_fresh_registration_creates_one_user_only_on_final_submit(clock):
    opened = start()
    assert opened["expires_in_sec"] == 600
    assert users() == []
    assert challenge(opened)["status"] == "email_code_sent"
    finished = complete(opened)
    assert finished["status"] == "authenticated"
    assert len(users()) == 1
    assert users()[0]["handle"] == "email.lifecycle"
    assert users()[0]["terms_accepted_at_utc"]
    assert challenge(opened)["status"] == "consumed"


def test_refusing_consent_does_not_spend_or_refresh_the_code(clock):
    opened = start()
    original = dict(challenge(opened))
    with pytest.raises(account_auth.AccountAuthError) as refused:
        complete(opened, accept_terms=False)
    assert refused.value.code == "terms_required"
    assert users() == []
    assert challenge(opened) == original
    assert complete(opened)["status"] == "authenticated"


def test_the_code_still_works_immediately_before_its_original_deadline(clock):
    opened = start()
    clock.value = challenge(opened)["expires_at"] - .01
    assert complete(opened)["status"] == "authenticated"


@pytest.mark.parametrize("past_deadline", (0, .01, 601))
def test_waiting_at_final_consent_expiry_has_a_recoverable_registration_code(clock, past_deadline):
    opened = start()
    original = dict(challenge(opened))
    clock.value = original["expires_at"] + past_deadline
    with pytest.raises(account_auth.AccountAuthError) as expired:
        complete(opened)
    assert expired.value.status == 410
    assert expired.value.code == "registration_expired"
    assert users() == []
    assert challenge(opened)["expires_at"] == original["expires_at"]
    assert challenge(opened)["attempts"] == 0


def test_expired_login_verification_stays_410_and_does_not_make_an_account(clock):
    opened = start()
    clock.value = challenge(opened)["expires_at"] + 1
    with pytest.raises(account_auth.AccountAuthError) as expired:
        account_auth.verify_email_auth(opened["challenge_id"], code=opened["test_code"],
            profile={"accept_terms": False}, ip="127.0.0.1", user_agent=UA)
    assert expired.value.status == 410
    assert users() == []


def test_known_single_use_login_proof_cannot_create_another_account(clock):
    opened = start()
    first = account_auth.verify_email_auth(opened["challenge_id"], code=opened["test_code"],
        profile={"accept_terms": True, "first_name": "Lifecycle", "last_name": "Test"},
        ip="127.0.0.1", user_agent=UA)
    assert first["status"] == "authenticated"
    assert len(users()) == 1
    with pytest.raises(account_auth.AccountAuthError) as consumed:
        complete(opened, handle="email.another")
    assert consumed.value.status == 410
    assert consumed.value.code == "registration_expired"
    assert len(users()) == 1


def test_wrong_otp_is_not_reported_as_expiry_and_correct_otp_can_retry(clock):
    opened = start()
    bad = "000000" if opened["test_code"] != "000000" else "111111"
    with pytest.raises(account_auth.AccountAuthError) as invalid:
        complete(opened, code=bad)
    assert invalid.value.status == 401
    assert invalid.value.code == "email_code_invalid"
    assert challenge(opened)["attempts"] == 1
    assert users() == []
    assert complete(opened)["status"] == "authenticated"


def test_unknown_address_login_without_consent_does_not_double_consume(clock):
    opened = start()
    original_expiry = challenge(opened)["expires_at"]
    with pytest.raises(account_auth.AccountAuthError) as refused:
        account_auth.verify_email_auth(opened["challenge_id"], code=opened["test_code"],
            profile={"accept_terms": False}, ip="127.0.0.1", user_agent=UA)
    assert refused.value.status == 400
    assert users() == []
    assert challenge(opened)["status"] == "email_code_sent"
    assert challenge(opened)["expires_at"] == original_expiry
    assert complete(opened)["status"] == "authenticated"


def test_explicit_new_code_after_expiry_recovers_without_reusing_old_proof(clock):
    old = start()
    clock.value = challenge(old)["expires_at"] + 1
    with pytest.raises(account_auth.AccountAuthError):
        complete(old)
    new = start()
    assert new["challenge_id"] != old["challenge_id"]
    assert new["expires_in_sec"] == 600
    assert complete(new)["status"] == "authenticated"
    assert len(users()) == 1
