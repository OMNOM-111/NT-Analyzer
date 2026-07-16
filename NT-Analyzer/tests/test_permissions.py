from __future__ import annotations

import pytest

from app import permissions, subscriptions


@pytest.fixture(autouse=True)
def isolated_subscriptions(monkeypatch, tmp_path):
    # Keep the Free Preview plan-matrix lookup off the real DPAPI store.
    monkeypatch.setattr(subscriptions, "_root", lambda: tmp_path)
    return tmp_path


def _entitlement(plan_id: str) -> dict:
    return {"plan_id": plan_id, "plan": subscriptions.PLANS[plan_id]}


def test_owner_has_all_capabilities() -> None:
    perm = permissions.resolve({"is_owner": True})
    assert all(perm["capabilities"].values())
    assert all(perm["nav"].values())
    assert perm["free_preview"] is False
    assert perm["locked_nav"] == []
    assert perm["plan_id"] == "founder"


def test_free_preview_when_no_entitlement() -> None:
    perm = permissions.resolve({"is_owner": False}, {})
    assert perm["free_preview"] is True
    assert perm["plan_id"] == permissions.FREE_PREVIEW_PLAN_ID
    # Free Preview: news, docs, demo backtest, practice trading.
    assert perm["nav"]["news"] is True
    assert perm["nav"]["docs"] is True
    assert perm["nav"]["backtest"] is True
    assert perm["capabilities"]["demo_backtest"] is True
    assert perm["capabilities"]["backtesting"] is False
    assert perm["demo_tier"] is True
    assert perm["nav"]["desktop"] is False
    assert "backtest" not in perm["locked_nav"]
    assert "desktop" in perm["locked_nav"]


def test_plan_capabilities_map_to_nav() -> None:
    perm = permissions.resolve({"is_owner": False}, _entitlement("standard"))
    assert perm["free_preview"] is False
    assert perm["capabilities"]["charts_realtime"] is True
    assert perm["nav"]["desktop"] is True   # charts_realtime -> desktop
    assert perm["nav"]["ai"] is True         # ai_lab -> ai
    assert perm["nav"]["backtest"] is True   # backtesting -> backtest
    assert perm["capabilities"]["live_commands"] is False


def test_user_permission_override_grants_capability() -> None:
    user = {"is_owner": False, "permission_overrides": {"ai_lab": True}}
    perm = permissions.resolve(user, _entitlement("basic"))
    # basic has no ai_lab, but the per-user override grants it (and its nav).
    assert perm["capabilities"]["ai_lab"] is True
    assert perm["nav"]["ai"] is True


def test_user_permission_override_revokes_capability() -> None:
    user = {"is_owner": False, "permission_overrides": {"backtesting": False, "demo_backtest": False}}
    perm = permissions.resolve(user, _entitlement("pro"))
    assert perm["capabilities"]["backtesting"] is False
    assert perm["capabilities"]["demo_backtest"] is False
    assert perm["nav"]["backtest"] is False


def test_user_nav_override_wins() -> None:
    user = {"is_owner": False, "feature_overrides": {"topstep": True}}
    perm = permissions.resolve(user, {})
    assert perm["nav"]["topstep"] is True


def test_required_capability_prefix_match() -> None:
    assert permissions.required_capability("/api/ai-lab/backtest") == "ai_lab"
    assert permissions.required_capability("/api/ops/live/unlock-request") == "live_commands"
    assert permissions.required_capability("/api/auth/me") is None
    assert permissions.required_capability("/api/ops/runtime/bars/batch") is None


def test_enforce_owner_bypasses() -> None:
    permissions.enforce("/api/ai-lab/x", {"is_owner": True})  # must not raise


def test_enforce_blocks_without_capability() -> None:
    ctx = {"is_owner": False, "capabilities": {"ai_lab": False}}
    with pytest.raises(permissions.PermissionError) as exc:
        permissions.enforce("/api/ai-lab/x", ctx)
    assert exc.value.status == 403


def test_enforce_allows_with_capability() -> None:
    ctx = {"is_owner": False, "capabilities": {"ai_lab": True}}
    permissions.enforce("/api/ai-lab/x", ctx)  # must not raise


def test_enforce_ignores_unrestricted_paths() -> None:
    ctx = {"is_owner": False, "capabilities": {}}
    permissions.enforce("/api/auth/me", ctx)  # must not raise
