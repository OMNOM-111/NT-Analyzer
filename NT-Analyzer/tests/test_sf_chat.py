"""SF Chat human-conversation isolation and unread semantics."""
from __future__ import annotations

import copy

import pytest

from app import account_lifecycle, community, sf_chat, storage_router

from . import _relational_fake
from app.production_storage import StorageUnavailableError


@pytest.fixture()
def profiles():
    alice = community.ensure_social_profile(
        42, display_name="Alice Trader", username="alice_trader",
    )["profile"]
    bob = community.ensure_social_profile(
        99, display_name="Bob Quant", username="bob_quant",
    )["profile"]
    eve = community.ensure_social_profile(
        77, display_name="Eve Observer", username="eve_observer",
    )["profile"]
    return alice, bob, eve


def test_private_conversation_unread_read_and_idempotency(profiles):
    alice, bob, _ = profiles
    started = sf_chat.start_conversation(42, bob["profile_id"])
    conversation_id = started["conversation"]["conversation_id"]
    assert conversation_id.startswith("sfh_")
    assert started["conversation"]["conversation_type"] == "human"

    first = sf_chat.send_message(
        42, conversation_id, text="Привет, Bob", idempotency_key="same-request",
    )
    duplicate = sf_chat.send_message(
        42, conversation_id, text="Привет, Bob", idempotency_key="same-request",
    )
    assert duplicate["deduplicated"] is True
    assert duplicate["message"]["message_id"] == first["message"]["message_id"]

    bob_list = sf_chat.list_conversations(99)
    assert bob_list["unread_count"] == 1
    assert bob_list["conversations"][0]["last_message_preview"] == "Привет, Bob"
    detail = sf_chat.conversation_messages(99, conversation_id)
    assert detail["viewer_profile_id"] == bob["profile_id"]
    assert detail["messages"][0]["sender_profile_id"] == alice["profile_id"]
    assert "user_id" not in detail["messages"][0]

    read = sf_chat.mark_read(99, conversation_id)
    assert read["advanced"] == 1
    assert sf_chat.list_conversations(99)["unread_count"] == 0


def test_non_participant_cannot_enumerate_messages_or_attachments(profiles):
    _, bob, _ = profiles
    conversation_id = sf_chat.start_conversation(42, bob["profile_id"])["conversation"]["conversation_id"]
    png = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL6aQAAAABJRU5ErkJggg=="
    )
    sent = sf_chat.send_message(
        42, conversation_id, attachments=[{"name": "entry.png", "data_url": png}],
    )
    attachment_id = sent["message"]["attachments"][0]["attachment_id"]

    with pytest.raises(sf_chat.SFChatError) as messages_exc:
        sf_chat.conversation_messages(77, conversation_id)
    assert messages_exc.value.status == 404
    with pytest.raises(sf_chat.SFChatError) as attachment_exc:
        sf_chat.attachment(77, attachment_id)
    assert attachment_exc.value.status == 404
    assert sf_chat.attachment(99, attachment_id)["mime_type"] == "image/png"

    with pytest.raises(sf_chat.SFChatError, match="MIME"):
        sf_chat.send_message(
            42, conversation_id,
            attachments=[{"name": "fake.png", "data_url": "data:image/png;base64,Zm9v"}],
        )


def test_block_and_message_policy_are_enforced(profiles):
    alice, bob, _ = profiles
    community.update_social_profile(99, allow_messages="following")
    with pytest.raises(sf_chat.SFChatError) as policy_exc:
        sf_chat.start_conversation(42, bob["profile_id"])
    assert policy_exc.value.status == 403

    community.follow_profile(99, alice["profile_id"])
    conversation_id = sf_chat.start_conversation(42, bob["profile_id"])["conversation"]["conversation_id"]
    community.block_social_profile(99, alice["profile_id"])
    with pytest.raises(sf_chat.SFChatError) as blocked_exc:
        sf_chat.send_message(42, conversation_id, text="should not pass")
    assert blocked_exc.value.status == 403


def test_explicit_server_environment_uses_authoritative_documents(monkeypatch):
    documents = {}
    writes = []

    monkeypatch.setattr(storage_router, "production_enabled", lambda: True)
    monkeypatch.setattr(account_lifecycle, "deleted_ids", lambda: set())
    monkeypatch.setattr(account_lifecycle, "deleted_legacy_ids", lambda: set())

    def read_document(name, default):
        return copy.deepcopy(documents.get(name, default))

    def write_document(name, document):
        documents[name] = copy.deepcopy(dict(document))
        writes.append(name)
        return len(writes)

    monkeypatch.setattr(storage_router, "read_document", read_document)
    monkeypatch.setattr(storage_router, "write_document", write_document)
    # Writes stay document-authoritative; reads are relational in this mode, so
    # the read side is served from the same documents through the mirror API.
    _relational_fake.install(monkeypatch, documents)

    alice = community.ensure_social_profile(
        42, display_name="Alice", username="alice_42",
    )["profile"]
    bob = community.ensure_social_profile(
        99, display_name="Bob", username="bob_99",
    )["profile"]
    conversation_id = sf_chat.start_conversation(42, bob["profile_id"])["conversation"]["conversation_id"]
    sf_chat.send_message(42, conversation_id, text="PostgreSQL document")

    assert alice["profile_id"] != bob["profile_id"]
    assert set(documents) == {"community", "sf_chat"}
    assert "community" in writes and "sf_chat" in writes
    assert documents["sf_chat"]["messages"][0]["text"] == "PostgreSQL document"


def test_authoritative_repository_outage_never_falls_back_to_local_json(monkeypatch):
    monkeypatch.setattr(storage_router, "production_enabled", lambda: True)

    def unavailable(*_args, **_kwargs):
        raise StorageUnavailableError("offline")

    monkeypatch.setattr(storage_router, "read_document", unavailable)
    with pytest.raises(community.CommunityError) as community_exc:
        community._load()
    assert community_exc.value.status == 503
    assert "storage_unavailable" in str(community_exc.value)

    with pytest.raises(sf_chat.SFChatError) as chat_exc:
        sf_chat._load()
    assert chat_exc.value.status == 503
    assert "storage_unavailable" in str(chat_exc.value)


def test_listing_conversations_does_not_rescan_messages_per_conversation(
    profiles, monkeypatch,
):
    """Listing must stay linear in the size of the store.

    `_public_conversation` used to call `_conversation_messages` for every row,
    so a viewer with C conversations rescanned all M messages C times. At the
    document cap that is 100M row tests, and one listing measured ~44s against
    ~0.66s once the grouping is done a single time. Counting the per-row scans
    keeps the guarantee deterministic instead of timing-dependent.
    """
    alice, bob, eve = profiles
    for partner_user_id, partner in ((99, bob), (77, eve)):
        conversation_id = sf_chat.start_conversation(
            42, partner["profile_id"],
        )["conversation"]["conversation_id"]
        for index in range(3):
            sf_chat.send_message(42, conversation_id, text=f"Сообщение {index}")
            sf_chat.send_message(partner_user_id, conversation_id, text=f"Ответ {index}")

    scans = []
    original = sf_chat._conversation_messages
    monkeypatch.setattr(
        sf_chat, "_conversation_messages",
        lambda doc, cid: (scans.append(cid), original(doc, cid))[1],
    )

    listed = sf_chat.list_conversations(42)

    assert len(listed["conversations"]) == 2
    assert scans == [], "listing rescanned the message list per conversation"
    # The grouped index must still produce the same public payload.
    previews = {row["last_message_preview"] for row in listed["conversations"]}
    assert previews == {"Ответ 2"}
    assert all(row["message_count"] == 6 for row in listed["conversations"])
