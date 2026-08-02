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
