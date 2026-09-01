"""SF Chat human-conversation isolation and unread semantics."""
from __future__ import annotations

import copy

import pytest

from app import community, sf_chat, storage_router


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

    def read_document(name, default):
        return copy.deepcopy(documents.get(name, default))

    def write_document(name, document):
        documents[name] = copy.deepcopy(dict(document))
        writes.append(name)
        return len(writes)

    monkeypatch.setattr(storage_router, "read_document", read_document)
    monkeypatch.setattr(storage_router, "write_document", write_document)

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
