"""Micro Live + AI star ratings tests."""
from __future__ import annotations

import pytest

from app import micro_live, permissions
from app.ai_lab import ai_ratings, agent_router


@pytest.fixture()
def micro_store(tmp_path, monkeypatch):
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.delenv("NTA_STAGING_ALLOW_REAL_PAYMENTS", raising=False)
    monkeypatch.delenv("NTA_STAGING_ALLOW_LIVE_ORDERS", raising=False)
    monkeypatch.setattr(micro_live, "_root", lambda: tmp_path)
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def ratings_store(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_ratings, "_root", lambda: tmp_path)
    (tmp_path / "ai_lab" / "registry").mkdir(parents=True)
    return tmp_path


def test_micro_live_free_trades_and_scale(micro_store):
    acct = micro_live.ensure_account(42, scale=100)
    assert acct["mode"] == "micro_live"
    assert acct["account"]["free_trades_left"] == 5
    with pytest.raises(micro_live.MicroLiveError):
        micro_live.place_scaled_trade(42, pnl_full=85)
    micro_live.accept_warnings(42)
    t1 = micro_live.place_scaled_trade(42, pnl_full=85, notional_full=100)
    assert t1["trade"]["free_trade"] is True
    assert t1["account"]["free_trades_left"] == 4
    assert "1:100" in t1["trade"]["comparison"]
    for _ in range(4):
        micro_live.place_scaled_trade(42, pnl_full=10)
    paid = micro_live.place_scaled_trade(42, pnl_full=100)
    assert paid["trade"]["free_trade"] is False
    assert abs(paid["trade"]["pnl_micro"] - 1.0) < 1e-6


def test_micro_live_not_on_free_preview():
    perm = permissions.resolve({"ux_mode": "professional"}, None)
    assert perm["capabilities"].get("micro_live") is False
    assert perm["nav"].get("micro_live") is False
    assert perm["capabilities"].get("practice_trading") is True
    assert perm["capabilities"].get("demo_backtest") is True


def test_star_ratings_influence_order(ratings_store, monkeypatch):
    ai_ratings.record_rating(role_id="coder", model_id="good-model", rating=3)
    ai_ratings.record_rating(role_id="coder", model_id="good-model", rating=3)
    ai_ratings.record_rating(role_id="coder", model_id="weak-model", rating=1)
    tables = ai_ratings.tables()
    assert tables["role_model"]
    assert tables["roles"]
    assert tables["models"]
    agents = [
        {"model": "weak-model", "provider": "x", "key_configured": True, "enabled": True, "endpoint_type": "chat", "priority": 1, "requests_today": 0},
        {"model": "good-model", "provider": "y", "key_configured": True, "enabled": True, "endpoint_type": "chat", "priority": 1, "requests_today": 0},
    ]
    monkeypatch.setattr(ai_ratings, "EXPLORATION_RATE", 0.0)
    ranked = ai_ratings.rank_agents("coder", agents, explore=False)
    assert ranked[0]["model"] == "good-model"


def test_rank_agents_does_not_resurrect_ungated(ratings_store, monkeypatch):
    """Ratings only reorder; callers must already filter keys/budget."""
    ai_ratings.record_rating(role_id="general", model_id="no-key", rating=3)
    gated = [{"model": "safe", "provider": "a"}]
    ranked = ai_ratings.rank_agents("general", gated, explore=False)
    assert [a["model"] for a in ranked] == ["safe"]


def test_candidates_still_require_key(monkeypatch, ratings_store):
    """agent_router.candidates keeps key_configured gate before rating sort."""
    monkeypatch.setattr(
        agent_router.agent_registry,
        "list_agents",
        lambda: [
            {
                "model": "starred", "provider": "x", "key_configured": False, "enabled": True,
                "endpoint_type": "chat", "priority": 1, "requests_today": 0,
                "billing_mode": "free_tier", "role": "general",
            },
            {
                "model": "ready", "provider": "y", "key_configured": True, "enabled": True,
                "endpoint_type": "chat", "priority": 1, "requests_today": 0,
                "billing_mode": "free_tier", "role": "general",
            },
        ],
    )
    ai_ratings.record_rating(role_id="general", model_id="starred", rating=3)
    rows = agent_router.candidates("general", endpoint_type="chat", allow_paid=True)
    assert all(r.get("key_configured") for r in rows)
    assert all(r.get("model") != "starred" for r in rows)
