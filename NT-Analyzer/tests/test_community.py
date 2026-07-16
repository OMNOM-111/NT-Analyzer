"""Community contour isolation tests."""
from __future__ import annotations

import pytest

from app import community


@pytest.fixture()
def community_store(tmp_path, monkeypatch):
    monkeypatch.setattr(community, "_root", lambda: tmp_path)
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    return tmp_path


def test_community_chat_not_orchestrator_and_copy_rating(community_store):
    msg = community.post_message(42, text="привет community", display_name="Alice")
    assert msg["message"]["contour"] == "community"
    assert msg["telegram_mirror"] is False
    pub = community.publish_strategy(
        42, title="ORB Demo", metrics={"net_profit": 1000, "max_drawdown": -200}, display_name="Alice",
    )
    sid = pub["strategy"]["strategy_id"]
    copied = community.copy_strategy(99, sid)
    assert copied["copy"]["to_user_id"] == 99
    ranks = community.ratings()
    assert ranks["composite"]
    assert ranks["by_copies"][0]["copies"] >= 1
    feed = community.feed()
    assert feed["contour"] == "community"
    assert any(m["text"] == "привет community" for m in feed["messages"])


def test_block_stops_posting(community_store):
    community.moderate_block(1, 42, reason="spam")
    with pytest.raises(community.CommunityError) as exc:
        community.post_message(42, text="blocked")
    assert exc.value.status == 403
