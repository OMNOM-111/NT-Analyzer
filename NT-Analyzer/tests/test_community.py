"""Community contour isolation tests."""
from __future__ import annotations

import json
import uuid

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
    assert copied["copy"]["status"] == "pending_import"
    assert copied["copy"]["personal_strategy_created"] is False
    assert copied["import"]["action_required"] == "portfolio_import"
    duplicate = community.copy_strategy(99, sid)
    assert duplicate["deduplicated"] is True
    assert duplicate["copy"]["copy_id"] == copied["copy"]["copy_id"]
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


def test_workspace_scopes_accounts_messages_strategies_and_copies(community_store):
    ws_a = "ws_alpha_12345678"
    ws_b = "ws_beta_123456789"
    community.post_message(42, text="only alpha", display_name="Alice", workspace_id=ws_a)
    community.post_message(42, text="only beta", display_name="Alice B", workspace_id=ws_b)
    published = community.publish_strategy(
        42,
        title="Alpha strategy",
        metrics={"net_profit": 100, "max_drawdown": -10},
        workspace_id=ws_a,
    )
    sid = published["strategy"]["strategy_id"]

    alpha = community.feed(workspace_id=ws_a)
    beta = community.feed(workspace_id=ws_b)
    assert [row["text"] for row in alpha["messages"]] == ["only alpha"]
    assert [row["text"] for row in beta["messages"]] == ["only beta"]
    assert [row["strategy_id"] for row in alpha["strategies"]] == [sid]
    assert beta["strategies"] == []
    assert alpha["accounts"][0]["workspace_id"] == ws_a
    assert beta["accounts"][0]["workspace_id"] == ws_b

    with pytest.raises(community.CommunityError) as cross_copy:
        community.copy_strategy(99, sid, workspace_id=ws_b)
    assert cross_copy.value.status == 404

    copied = community.copy_strategy(99, sid, workspace_id=ws_a)
    assert copied["copy"]["workspace_id"] == ws_a
    stored = community._load()
    assert all(row.get("workspace_id") == ws_a for row in stored["copies"])


def test_workspace_block_does_not_cross_tenants(community_store):
    ws_a = "ws_alpha_12345678"
    ws_b = "ws_beta_123456789"
    community.moderate_block(1, 42, reason="alpha only", workspace_id=ws_a)
    with pytest.raises(community.CommunityError) as blocked:
        community.post_message(42, text="blocked", workspace_id=ws_a)
    assert blocked.value.status == 403
    assert community.post_message(42, text="allowed", workspace_id=ws_b)["ok"] is True


@pytest.mark.parametrize("bad_value", ["not-a-number", True, [1], float("nan"), float("inf")])
def test_bad_metrics_are_client_errors_not_500(community_store, bad_value):
    with pytest.raises(community.CommunityError) as exc:
        community.publish_strategy(
            42,
            title="Bad metrics",
            metrics={"net_profit": bad_value},
            workspace_id="ws_alpha_12345678",
        )
    assert exc.value.status == 400


def test_ratings_tolerate_legacy_corrupt_metrics(community_store):
    path = community._store_path()
    path.write_text(json.dumps({
        "version": 1,
        "strategies": [
            {
                "strategy_id": "cstr_bad",
                "workspace_id": "ws_alpha_12345678",
                "user_id": 42,
                "display_name": "Alice",
                "metrics": {"net_profit": "broken", "max_drawdown": None},
                "copies": "also-broken",
                "created_at_utc": "2026-01-01T00:00:00Z",
            }
        ],
    }), encoding="utf-8")

    ratings = community.ratings(workspace_id="ws_alpha_12345678")
    assert ratings["composite"][0]["strategy_id"] == "cstr_bad"
    assert ratings["authors"][0]["copies"] == 0


def test_message_idempotency_is_workspace_bound(community_store):
    first = community.post_message(
        42, text="retry-safe", workspace_id="ws_alpha_12345678", idempotency_key="req-1",
    )
    duplicate = community.post_message(
        42, text="retry-safe", workspace_id="ws_alpha_12345678", idempotency_key="req-1",
    )
    other_workspace = community.post_message(
        42, text="retry-safe", workspace_id="ws_beta_123456789", idempotency_key="req-1",
    )
    assert duplicate["deduplicated"] is True
    assert duplicate["message"]["message_id"] == first["message"]["message_id"]
    assert other_workspace["message"]["message_id"] != first["message"]["message_id"]


def test_message_identity_uuid_dual_write_and_legacy_backfill(community_store, monkeypatch):
    owner_uuid = str(uuid.uuid4())
    alice_uuid = str(uuid.uuid4())
    bob_uuid = str(uuid.uuid4())
    workspace = "ws_alpha_12345678"
    identities = {1: owner_uuid, 42: alice_uuid, 99: bob_uuid}
    monkeypatch.setattr(
        community,
        "_resolved_user_uuid",
        lambda user_id, preferred="": str(preferred or identities.get(int(user_id or 0), "")),
    )
    community._store_path().write_text(json.dumps({
        "version": 1,
        "accounts": [{"workspace_id": workspace, "user_id": 42}],
        "messages": [{"message_id": "cmsg_legacy", "workspace_id": workspace, "user_id": 42}],
        "posts": [{"workspace_id": workspace, "user_id": 42}],
        "strategies": [{"strategy_id": "cstr_legacy", "workspace_id": workspace, "user_id": 99}],
        "copies": [{"workspace_id": workspace, "from_user_id": 99, "to_user_id": 42}],
        "reports": [{"workspace_id": workspace, "from_user_id": 42}],
        "shared_reports": [{"workspace_id": workspace, "user_id": 42}],
        "requests": [{"workspace_id": workspace, "from_user_id": 42, "recipient_user_id": 99}],
        "blocks": [{"workspace_id": workspace, "user_id": 99, "by_owner_id": 1}],
    }), encoding="utf-8")

    community.feed(workspace_id=workspace)
    migrated = community._load()
    assert migrated["accounts"][0]["user_uuid"] == alice_uuid
    assert migrated["messages"][0]["user_uuid"] == alice_uuid
    assert migrated["posts"][0]["user_uuid"] == alice_uuid
    assert migrated["strategies"][0]["user_uuid"] == bob_uuid
    assert migrated["copies"][0]["from_user_uuid"] == bob_uuid
    assert migrated["copies"][0]["to_user_uuid"] == alice_uuid
    assert migrated["reports"][0]["from_user_uuid"] == alice_uuid
    assert migrated["shared_reports"][0]["user_uuid"] == alice_uuid
    assert migrated["requests"][0]["from_user_uuid"] == alice_uuid
    assert migrated["requests"][0]["recipient_user_uuid"] == bob_uuid
    assert migrated["blocks"][0]["user_uuid"] == bob_uuid
    assert migrated["blocks"][0]["by_owner_uuid"] == owner_uuid

    message = community.post_message(
        42, text="uuid", workspace_id=workspace, user_uuid=alice_uuid,
    )["message"]
    assert message["user_id"] == 42
    assert message["user_uuid"] == alice_uuid
    account = community._load()["accounts"][0]
    assert account["user_id"] == 42
    assert account["user_uuid"] == alice_uuid
    report = community.share_report(42, title="UUID report", workspace_id=workspace, user_uuid=alice_uuid)
    request = community.create_request(
        42, title="UUID request", recipient_user_id=99, workspace_id=workspace, user_uuid=alice_uuid,
    )
    strategy = community.publish_strategy(42, title="UUID strategy", workspace_id=workspace, user_uuid=alice_uuid)
    copied = community.copy_strategy(42, "cstr_legacy", workspace_id=workspace, user_uuid=alice_uuid)
    abuse = community.report_abuse(42, target_id="cmsg_legacy", workspace_id=workspace, user_uuid=alice_uuid)
    community.moderate_block(1, 42, workspace_id="ws_beta_123456789", owner_user_uuid=owner_uuid)

    assert report["report"]["user_uuid"] == alice_uuid
    assert request["request"]["from_user_uuid"] == alice_uuid
    assert request["request"]["recipient_user_uuid"] == bob_uuid
    assert strategy["strategy"]["user_uuid"] == alice_uuid
    assert copied["copy"]["from_user_uuid"] == bob_uuid
    assert copied["copy"]["to_user_uuid"] == alice_uuid
    assert abuse["report"]["from_user_uuid"] == alice_uuid
    latest_block = community._load()["blocks"][-1]
    assert latest_block["user_uuid"] == alice_uuid
    assert latest_block["by_owner_uuid"] == owner_uuid


def test_channels_and_threads_stay_inside_one_workspace_and_channel(community_store):
    workspace = "ws_alpha_12345678"
    root = community.post_message(
        42, text="Разберём вход по MNQ", workspace_id=workspace, channel_id="study",
    )["message"]
    reply = community.post_message(
        99,
        text="Добавлю скриншот после закрытия бара",
        workspace_id=workspace,
        channel_id="study",
        thread_root_id=root["message_id"],
    )["message"]

    study = community.feed(workspace_id=workspace, channel_id="study")
    general = community.feed(workspace_id=workspace, channel_id="general")
    assert [row["message_id"] for row in study["messages"]] == [root["message_id"], reply["message_id"]]
    assert general["messages"] == []
    assert reply["thread_root_id"] == root["message_id"]
    assert {row["id"] for row in study["channels"]} >= {"general", "study", "strategy-review", "reports"}

    with pytest.raises(community.CommunityError) as exc:
        community.post_message(
            99,
            text="wrong channel",
            workspace_id=workspace,
            channel_id="general",
            thread_root_id=root["message_id"],
        )
    assert exc.value.status == 400


def test_reports_requests_and_image_attachment_are_private_to_workspace(community_store):
    workspace = "ws_alpha_12345678"
    png = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL6aQAAAABJRU5ErkJggg=="
    )
    message = community.post_message(
        42,
        text="Скрин сделки",
        workspace_id=workspace,
        channel_id="reports",
        attachments=[{"name": "mnq-entry.png", "data_url": png}],
    )["message"]
    public_attachment = message["attachments"][0]
    assert public_attachment["url"].startswith("/api/community/attachment/catt_")
    assert "stored_name" not in public_attachment
    resolved = community.attachment(public_attachment["attachment_id"], workspace_id=workspace)
    assert resolved["mime_type"] == "image/png"
    assert resolved["path"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(community.CommunityError) as cross_workspace:
        community.attachment(public_attachment["attachment_id"], workspace_id="ws_beta_123456789")
    assert cross_workspace.value.status == 404

    report = community.share_report(
        42,
        title="Итоги недели",
        summary="Только виртуальная статистика",
        metrics={"pnl": 125.5, "max_drawdown": -40},
        workspace_id=workspace,
        attachments=[{"name": "weekly.png", "data_url": png}],
    )["report"]
    request = community.create_request(
        99,
        title="Нужен скрин точки входа",
        request_type="screenshot",
        recipient_user_id=42,
        workspace_id=workspace,
    )["request"]
    feed = community.feed(workspace_id=workspace, channel_id="reports")
    assert feed["shared_reports"][0]["report_id"] == report["report_id"]
    assert feed["requests"][0]["request_id"] == request["request_id"]
    assert feed["requests"][0]["request_type"] == "screenshot"

    with pytest.raises(community.CommunityError) as invalid:
        community.post_message(
            42,
            text="bad file",
            workspace_id=workspace,
            attachments=[{"name": "bad.txt", "data_url": "data:text/plain;base64,Zm9v"}],
        )
    assert invalid.value.status == 400

    with pytest.raises(community.CommunityError, match="MIME"):
        community.post_message(
            42,
            text="spoofed image",
            workspace_id=workspace,
            attachments=[{"name": "fake.png", "data_url": "data:image/png;base64,Zm9v"}],
        )


def test_social_feed_profile_privacy_and_interactions(community_store):
    alice = community.ensure_social_profile(
        42, display_name="Alice Trader", username="alice_trader",
    )["profile"]
    bob = community.ensure_social_profile(
        99, display_name="Bob Quant", username="bob_quant",
    )["profile"]
    community.update_social_profile(
        99, bio="Private research notes", profile_visibility="followers",
        allow_messages="following",
    )

    restricted = community.social_profile(42, bob["profile_id"])["profile"]
    assert restricted["bio"] == ""
    assert restricted["details_visible"] is False
    assert restricted["can_message"] is False
    assert not ({"user_id", "user_uuid", "workspace_id", "email"} & restricted.keys())

    community.follow_profile(99, alice["profile_id"])
    visible = community.social_profile(42, bob["profile_id"])["profile"]
    assert visible["can_message"] is True
    community.follow_profile(42, bob["profile_id"])
    visible = community.social_profile(42, bob["profile_id"])["profile"]
    assert visible["bio"] == "Private research notes"

    post = community.create_social_post(
        99, text="Разбор #MNQ без инвестиционных обещаний", visibility="followers",
        idempotency_key="post-1",
    )["post"]
    duplicate = community.create_social_post(
        99, text="Разбор #MNQ без инвестиционных обещаний", visibility="followers",
        idempotency_key="post-1",
    )
    assert duplicate["deduplicated"] is True
    assert duplicate["post"]["post_id"] == post["post_id"]

    feed = community.social_feed(42, scope="following", hashtag="mnq")
    assert [row["post_id"] for row in feed["posts"]] == [post["post_id"]]
    reacted = community.react_to_post(42, post["post_id"], reaction="insightful")["post"]
    assert reacted["viewer_reaction"] == "insightful"
    assert reacted["reactions"]["insightful"] == 1
    commented = community.comment_on_post(42, post["post_id"], text="Полезный разбор")["post"]
    assert commented["comment_count"] == 1
    saved = community.bookmark_post(42, post["post_id"])["post"]
    assert saved["bookmarked"] is True
    assert community.social_feed(42, saved_only=True)["posts"][0]["post_id"] == post["post_id"]


def test_social_block_removes_relationships_and_hides_content(community_store):
    alice = community.ensure_social_profile(42, display_name="Alice", username="alice_42")["profile"]
    bob = community.ensure_social_profile(99, display_name="Bob", username="bob_99")["profile"]
    community.follow_profile(42, bob["profile_id"])
    community.create_social_post(99, text="Bob post")
    community.block_social_profile(42, bob["profile_id"])

    assert community.social_feed(42)["posts"] == []
    profiles = community.list_social_profiles(42)["profiles"]
    assert all(row["profile_id"] != bob["profile_id"] for row in profiles)
    with pytest.raises(community.CommunityError) as exc:
        community.social_profile(42, bob["profile_id"])
    assert exc.value.status == 404
    stored = community._load()
    assert not any({row.get("follower_profile_id"), row.get("target_profile_id")}
                   == {alice["profile_id"], bob["profile_id"]}
                   for row in stored["follows"])


def test_social_objects_must_be_server_attested(community_store):
    community.ensure_social_profile(42, display_name="Alice", username="alice_42")
    with pytest.raises(community.CommunityError) as exc:
        community.create_social_post(
            42, text="raw result", object_snapshot={"kind": "backtest", "pnl": 999999},
        )
    assert exc.value.status == 403


def test_server_attested_result_snapshot_is_allowlisted_and_immutable(community_store):
    summary = {
        "status": "done",
        "class_name": "MNQOpenDrive",
        "instrument": "MNQ 09-26",
        "timeframe": "1 Minute",
        "finished_at_utc": "2026-09-01T12:00:00Z",
        "metrics": {
            "net_profit": 125.5,
            "profit_factor": 1.42,
            "max_drawdown": -40,
            "trade_count": 12,
            "raw_private_metric": 999,
        },
        "path": "C:/private/result",
        "trades": [{"price": 1}],
        "source_code": "secret",
    }
    snapshot = community.attested_result_snapshot(
        "job_demo_001", summary, origin={"type": "demo", "user_id": "42"},
    )
    assert snapshot["source_type"] == "demo_result"
    assert snapshot["source_id"] == "job_demo_001"
    assert snapshot["metrics"] == {
        "Net P&L": 125.5,
        "Profit factor": 1.42,
        "Max drawdown": -40,
        "Trades": 12,
    }
    assert len(snapshot["attestation"]["digest"]) == 64
    assert not ({"path", "trades", "source_code", "origin"} & snapshot.keys())
    assert "raw_private_metric" not in snapshot["metrics"]

    community.ensure_social_profile(42, display_name="Alice", username="alice_42")
    post = community.create_social_post(
        42, text="Verified demo", object_snapshot=snapshot, trusted_snapshot=True,
    )["post"]
    assert post["object"]["attestation"] == snapshot["attestation"]

    with pytest.raises(community.CommunityError) as unfinished:
        community.attested_result_snapshot("job_running_1", {"status": "running"})
    assert unfinished.value.status == 409


def test_social_soft_delete_and_owner_moderation_queue(community_store):
    alice = community.ensure_social_profile(42, display_name="Alice", username="alice_42")["profile"]
    community.ensure_social_profile(99, display_name="Bob", username="bob_99")
    post = community.create_social_post(42, text="Reported post")["post"]

    with pytest.raises(community.CommunityError) as foreign_delete:
        community.delete_social_post(99, post["post_id"])
    assert foreign_delete.value.status == 403

    report = community.report_social_target(
        99, post["post_id"], target_type="post", reason="policy review",
    )
    queue = community.social_moderation_queue()
    assert queue["reports"][0]["report_id"] == report["report_id"]
    assert not ({"from_profile_id", "user_id", "user_uuid"} & queue["reports"][0].keys())
    resolved = community.moderate_social_report(
        1, report["report_id"], action="remove", note="confirmed",
    )
    assert resolved["content_removed"] is True
    assert community.social_feed(42)["posts"] == []
    stored = next(row for row in community._load()["posts"] if row["post_id"] == post["post_id"])
    assert stored["deleted_at_utc"] and stored["moderated"] is True
    assert community.social_moderation_queue(status="resolved")["reports"][0]["resolution"] == "remove"

    own = community.create_social_post(42, text="Own post")["post"]
    deleted = community.delete_social_post(42, own["post_id"])
    assert deleted == {"ok": True, "post_id": own["post_id"], "deleted": True, "soft_delete": True}
    assert alice["profile_id"]
