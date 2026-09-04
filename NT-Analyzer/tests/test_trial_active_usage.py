"""The starting grant is spent in active use, not in calendar time."""
from __future__ import annotations

import pytest

from app import subscriptions


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(subscriptions, "_root", lambda: tmp_path)
    monkeypatch.delenv("STRATFORGE_TRIAL_ACTIVE_SECONDS", raising=False)
    subscriptions._clear_doc_cache()
    (tmp_path / "data").mkdir(exist_ok=True)
    yield tmp_path
    subscriptions._clear_doc_cache()


def _grant(user_id: int = 42) -> None:
    subscriptions.ensure_initial_trial(user_id, source="pytest")


def test_limit_is_five_hours_and_configurable(store, monkeypatch):
    assert subscriptions.trial_active_seconds_limit() == 5 * 3600
    monkeypatch.setenv("STRATFORGE_TRIAL_ACTIVE_SECONDS", "7200")
    assert subscriptions.trial_active_seconds_limit() == 7200
    # A nonsense value falls back to the shipped default instead of locking
    # everyone out or granting a decade.
    monkeypatch.setenv("STRATFORGE_TRIAL_ACTIVE_SECONDS", "5")
    assert subscriptions.trial_active_seconds_limit() == 5 * 3600


def test_idle_time_is_not_charged(store):
    _grant()
    base = 1_000_000.0
    subscriptions.record_active_usage(42, now=base)
    # Two hours away from the keyboard cost one idle cutoff, not two hours.
    usage = subscriptions.record_active_usage(42, now=base + 7200)
    assert usage["used_sec"] <= subscriptions.TRIAL_IDLE_CUTOFF_SEC
    assert usage["remaining_sec"] >= 5 * 3600 - subscriptions.TRIAL_IDLE_CUTOFF_SEC


def test_continuous_use_is_charged_and_finally_expires(store):
    _grant()
    now = 2_000_000.0
    subscriptions.record_active_usage(42, now=now)
    # Steady activity, one request per minute.
    for _ in range(5 * 60):
        now += 60
        usage = subscriptions.record_active_usage(42, now=now)
    assert usage["expired"] is True
    assert usage["remaining_sec"] == 0
    assert usage["percent_remaining"] == 0


def test_percent_and_human_facing_fields_stay_consistent(store):
    _grant()
    now = 3_000_000.0
    subscriptions.record_active_usage(42, now=now)
    for _ in range(60):
        now += 60
        usage = subscriptions.record_active_usage(42, now=now)
    assert usage["kind"] == "active_usage"
    assert usage["limit_sec"] == 5 * 3600
    assert 0 < usage["used_sec"] < usage["limit_sec"]
    assert usage["used_sec"] + usage["remaining_sec"] == usage["limit_sec"]
    assert usage["percent_remaining"] == round(usage["remaining_sec"] * 100 / usage["limit_sec"])
    assert usage["expired"] is False


def test_a_paid_or_promo_entitlement_replaces_the_grant(store):
    _grant()
    now = 4_000_000.0
    subscriptions.record_active_usage(42, now=now)
    for _ in range(5 * 60):
        now += 60
        subscriptions.record_active_usage(42, now=now)
    assert subscriptions.trial_usage_for_user(42)["expired"] is True

    subscriptions.activate_paid(42, "pro", provider="promo", provider_subscription_id="promo-1")
    after = subscriptions.trial_usage_for_user(42)
    assert after["granted_elsewhere"] is True
    assert after["expired"] is False, "a granted account is not held by the trial gate"


def test_usage_is_never_negative_or_over_the_limit(store):
    _grant()
    usage = subscriptions.record_active_usage(42, now=5_000_000.0)
    assert usage["used_sec"] == 0
    huge = subscriptions.record_active_usage(42, now=5_000_000.0 + 10 ** 6)
    assert 0 <= huge["used_sec"] <= huge["limit_sec"]


def test_an_account_without_a_grant_reports_nothing_to_spend(store):
    usage = subscriptions.trial_usage_for_user(999)
    assert usage["expired"] is False
    assert usage["started"] is False


def test_the_gate_holds_the_product_but_never_the_account(store):
    """An account with a spent grant keeps profile, security and promo entry."""
    from app import server as server_mod

    for path in (
        "/api/auth/me", "/api/auth/logout", "/api/account/security",
        "/api/account/devices/revoke", "/api/billing/promo/redeem",
        "/api/legal/terms", "/api/health", "/api/notifications",
    ):
        assert server_mod._trial_gate_allows(path), path

    for path in (
        "/api/performance", "/api/ops/runtime/accounts", "/api/community/v2/feed",
        "/api/sf-chat/conversations", "/api/ai-lab/researches", "/api/jobs",
    ):
        assert not server_mod._trial_gate_allows(path), path
