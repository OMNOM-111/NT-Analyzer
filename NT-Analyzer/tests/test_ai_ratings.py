"""AI star ratings remain independent from removed product contours."""
from __future__ import annotations

import pytest

from app.ai_lab import ai_ratings, agent_router


@pytest.fixture()
def ratings_store(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_ratings, "_root", lambda: tmp_path)
    (tmp_path / "ai_lab" / "registry").mkdir(parents=True)
    return tmp_path


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


def test_star_rating_event_is_idempotent_upsert_with_scope(ratings_store):
    ai_ratings.record_rating(
        event_id="message_rating:ws-a:MSG-1", message_id="MSG-1",
        role_id="coder", model_id="model-a", provider="test",
        rating=1, workspace_id="ws-a", user_id="42", source="owner",
    )
    ai_ratings.record_rating(
        event_id="message_rating:ws-a:MSG-1", message_id="MSG-1",
        role_id="coder", model_id="model-a", provider="test",
        rating=3, workspace_id="ws-a", user_id="42", source="owner",
    )
    pair = ai_ratings.tables(workspace_id="ws-a")["role_model"][0]
    assert pair["count"] == 1
    assert pair["avg"] == 3.0
    assert ai_ratings.tables(workspace_id="ws-b")["role_model"] == []
    event = ai_ratings._load()["events"][0]
    assert event["message_id"] == "MSG-1"
    assert event["workspace_id"] == "ws-a"
    assert event["user_id"] == "42"
    assert event["source"] == "owner"


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
