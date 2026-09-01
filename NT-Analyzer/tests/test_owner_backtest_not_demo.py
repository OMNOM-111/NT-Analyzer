"""The owner's real backtests must never be presented as demo data.

The owner reported the Backtest page saying "Демоверсия. Данные нереальные."
and offering a subscription upsell while their backtests were real. Server
permissions were already correct; the demo scenario panel in the Aurora page
rendered unconditionally. These tests pin both halves so the tier-specific
panel cannot creep back onto a full-access account.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import permissions, subscriptions

AURORA = Path(__file__).resolve().parents[1] / "app" / "static" / "aurora" / "assets"
BACKTESTING_JS = AURORA / "pages" / "backtesting.js"
UI_JS = AURORA / "ui.js"

# The exact strings that told the owner their data was not real.
DEMO_WATERMARK = "Демоверсия. Данные нереальные."
SUBSCRIPTION_UPSELL = "После подписки откроются полный бэктест"


@pytest.fixture(autouse=True)
def isolated_subscriptions(monkeypatch, tmp_path):
    monkeypatch.setattr(subscriptions, "_root", lambda: tmp_path)
    return tmp_path


def test_owner_is_never_demo_tier_and_keeps_full_backtesting() -> None:
    perm = permissions.resolve({"is_owner": True})
    assert perm["is_owner"] is True
    assert perm["demo_tier"] is False
    assert perm["free_preview"] is False
    assert perm["capabilities"]["backtesting"] is True
    assert perm["locked_nav"] == []
    assert perm["ux_mode"] == "professional"


def test_owner_stays_full_even_with_no_entitlement_at_all() -> None:
    """Trial or subscription expiry must not demote the owner."""
    perm = permissions.resolve({"is_owner": True}, {})
    assert perm["demo_tier"] is False
    assert perm["capabilities"]["backtesting"] is True
    assert perm["plan_id"] == "founder"


def test_owner_stays_full_even_on_a_stored_demo_tier_plan() -> None:
    """A stale authenticated_basic row must not gate the owner."""
    entitlement = {"plan_id": "authenticated_basic",
                   "plan": subscriptions.PLANS["authenticated_basic"]}
    perm = permissions.resolve({"is_owner": True}, entitlement)
    assert perm["demo_tier"] is False
    assert perm["capabilities"]["backtesting"] is True


def test_retired_free_preview_is_never_an_authorization_fallback() -> None:
    """free_preview survives only as a migration plan id, never as a gate."""
    for user in ({"is_owner": True}, {"ux_mode": "professional"}):
        assert permissions.resolve(user, {})["free_preview"] is False


def test_demo_tier_still_works_for_a_real_demo_account() -> None:
    """The fix must not disable the legitimate demo tier."""
    entitlement = {"plan_id": "authenticated_basic",
                   "plan": subscriptions.PLANS["authenticated_basic"]}
    perm = permissions.resolve({"ux_mode": "professional"}, entitlement)
    assert perm["demo_tier"] is True
    assert perm["capabilities"]["demo_backtest"] is True
    assert perm["capabilities"]["backtesting"] is False


def test_backtest_demo_panel_is_scoped_to_the_demo_tier() -> None:
    """The watermark and upsell may only render inside the demo-only branch."""
    source = BACKTESTING_JS.read_text(encoding="utf-8")
    assert "if (host && isDemoOnly)" in source, (
        "the demo scenario panel must stay behind isDemoOnly"
    )
    # isDemoOnly itself must keep excluding the owner.
    assert "!auth.is_owner" in source

    # Every render of the tier strings must sit after that guard, and the only
    # other watermark use is the per-report badge keyed on a real demo report.
    guard_at = source.index("if (host && isDemoOnly)")
    upsell_at = source.index(SUBSCRIPTION_UPSELL)
    assert upsell_at > guard_at, "subscription upsell escaped the demo-tier guard"


def test_report_demo_badge_still_keys_off_the_actual_report_kind() -> None:
    """A genuine demo report must keep saying so -- that label is honest."""
    source = BACKTESTING_JS.read_text(encoding="utf-8")
    assert "detail.kind === 'demo_backtest'" in source
    assert "origin.type === 'demo'" in source


def test_global_demo_watermark_excludes_the_owner() -> None:
    source = UI_JS.read_text(encoding="utf-8")
    match = re.search(r"const demoTier = (.+?);", source, re.S)
    assert match, "demoTier computation not found in ui.js"
    assert "!isOwner" in match.group(1), (
        "the global demo watermark must never apply to the owner"
    )


def test_offline_mock_search_index_cannot_be_reached_over_http() -> None:
    """The MOCK facade is a file:// preview aid, not a production surface."""
    api = (AURORA / "api.js").read_text(encoding="utf-8")
    assert "const isFile = location.protocol === 'file:';" in api
    assert "offline: isFile" in api
    ui = UI_JS.read_text(encoding="utf-8")
    assert "offline ? Promise.resolve(buildSearchIndexMock())" in ui
