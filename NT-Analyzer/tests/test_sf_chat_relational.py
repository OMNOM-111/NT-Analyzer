"""Production SF Chat reads must be relational, paged and free of global loads.

The document store stays the writer and the Development/import source. What
these tests pin down is the read side: in Production every ordinary chat action
— opening the panel, polling it, switching conversation, paging history,
marking read — must be answered from the indexed `sf_chat_*` / `sf_community_*`
mirrors, must cost a bounded number of statements, and must never deserialise
the document holding every user's conversations and messages.
"""
from __future__ import annotations

import copy

import pytest

from app import community, sf_chat, storage_router

from . import _relational_fake


@pytest.fixture()
def production(monkeypatch):
    """Production routing with document writes and relational reads."""
    documents: dict = {}

    def read_document(name, default):
        return copy.deepcopy(documents.get(name, default))

    def write_document(name, document):
        documents[name] = copy.deepcopy(dict(document))
        return len(documents)

    # These tests are about the chat read path, not account identity. Resolving
    # a legacy id through account_auth would mint UUIDs in the workstation's
    # durable database, which the suite's live-data guard rightly refuses.
    monkeypatch.setattr(
        community, "_resolved_user_uuid",
        lambda user_id, preferred="": str(preferred or "")
        or "00000000-0000-4000-8000-%012d" % int(user_id or 0),
    )
    monkeypatch.setattr(storage_router, "production_enabled", lambda: True)
    monkeypatch.setattr(storage_router, "read_document", read_document)
    monkeypatch.setattr(storage_router, "write_document", write_document)
    fake = _relational_fake.install(monkeypatch, documents)
    return documents, fake


def _seed(conversations: int, messages_each: int, *, viewer_user_id: int = 42):
    """Build a viewer with N conversations, each holding M messages."""
    viewer = community.ensure_social_profile(
        viewer_user_id, display_name="Viewer", username="viewer_acct",
    )["profile"]
    made = []
    for index in range(conversations):
        partner_user_id = 1000 + index
        partner = community.ensure_social_profile(
            partner_user_id, display_name=f"Partner {index}",
            username=f"partner_{index:04d}",
        )["profile"]
        cid = sf_chat.start_conversation(
            viewer_user_id, partner["profile_id"],
        )["conversation"]["conversation_id"]
        for step in range(messages_each):
            sender = viewer_user_id if step % 2 == 0 else partner_user_id
            sf_chat.send_message(sender, cid, text=f"m{index}-{step}")
        made.append((cid, partner_user_id))
    return viewer, made


def _forbid_document_loads(monkeypatch):
    """Any global document deserialisation in the hot path becomes a failure."""
    def boom(*_args, **_kwargs):
        raise AssertionError("hot path loaded a global document")

    monkeypatch.setattr(sf_chat, "_load", boom)
    monkeypatch.setattr(community, "_load", boom)


# ---------------------------------------------------------------------------
# 1. The two projections must agree.
# ---------------------------------------------------------------------------
def test_relational_and_document_projections_are_identical(production, monkeypatch):
    _seed(3, 4)

    relational_list = sf_chat.list_conversations(42, limit=50)
    relational_history = sf_chat.conversation_messages(
        42, relational_list["conversations"][0]["conversation_id"], limit=200,
    )

    # Same data, same code, document projection.
    monkeypatch.setattr(sf_chat, "_relational_reads", lambda: False)
    monkeypatch.setattr(storage_router, "production_enabled", lambda: True)
    document_list = sf_chat.list_conversations(42, limit=50)
    document_history = sf_chat.conversation_messages(
        42, document_list["conversations"][0]["conversation_id"], limit=200,
    )

    assert relational_list["conversations"] == document_list["conversations"]
    assert relational_list["unread_count"] == document_list["unread_count"]
    assert relational_history["messages"] == document_history["messages"]
    assert relational_history["conversation"] == document_history["conversation"]


# ---------------------------------------------------------------------------
# 2. No global document read on any ordinary action.
# ---------------------------------------------------------------------------
def test_open_poll_switch_and_page_never_load_a_global_document(production, monkeypatch):
    _seed(4, 6)
    listed = sf_chat.list_conversations(42, limit=2)
    first = listed["conversations"][0]["conversation_id"]
    second = listed["conversations"][1]["conversation_id"]
    # Read pointers are already at the head, so marking read is a no-op advance.
    sf_chat.mark_read(42, first)
    sf_chat.mark_read(42, second)

    _forbid_document_loads(monkeypatch)

    # Opening the panel.
    page = sf_chat.list_conversations(42, limit=2)
    assert len(page["conversations"]) == 2
    # Paging the rail.
    assert page["has_more"] is True
    later = sf_chat.list_conversations(42, limit=2, cursor=page["next_cursor"])
    assert later["conversations"]
    # Polling it.
    assert sf_chat.poll_state(42)["signature"]["conversation_count"] == 4
    # Switching conversation and paging its history.
    history = sf_chat.conversation_messages(42, second, limit=2)
    assert history["messages"]
    if history["has_more"]:
        older = sf_chat.conversation_messages(
            42, second, limit=2, before_seq=history["next_before_seq"],
        )
        assert older["messages"]
    # A read pointer already at the head must not rewrite the document.
    assert sf_chat.mark_read(42, second)["advanced"] == 0


def test_marking_genuinely_new_messages_still_writes_through_the_document(production):
    documents, _fake = production
    _viewer, made = _seed(1, 2)
    cid, partner_user_id = made[0]
    sf_chat.send_message(partner_user_id, cid, text="unread for the viewer")

    # The seed already leaves one unread partner message, so this is the second.
    before = sf_chat.list_conversations(42, limit=5)["conversations"][0]
    assert before["unread_count"] == 2

    advanced = sf_chat.mark_read(42, cid)
    assert advanced["advanced"] > 0
    assert sf_chat.list_conversations(42, limit=5)["conversations"][0]["unread_count"] == 0


# ---------------------------------------------------------------------------
# 3. Bounded statement count: no N+1, no growth with the store.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("conversations", [1, 5, 25])
def test_statement_count_per_action_does_not_grow_with_the_store(
    production, conversations,
):
    _documents, fake = production
    _seed(conversations, 3)

    fake.queries.clear()
    sf_chat.list_conversations(42, limit=30)
    listing = list(fake.queries)

    fake.queries.clear()
    sf_chat.poll_state(42)
    polling = list(fake.queries)

    # One page statement, one unread rollup, one profile batch, one identity.
    assert sorted(listing) == [
        "conversation_page", "profile_by_identity", "public_profiles", "unread_total",
    ], listing
    assert polling == ["profile_by_identity", "poll_state"], polling


def test_history_page_costs_the_same_statements_at_any_depth(production):
    _documents, fake = production
    _viewer, made = _seed(1, 40)
    cid = made[0][0]

    fake.queries.clear()
    first = sf_chat.conversation_messages(42, cid, limit=10)
    first_page_queries = list(fake.queries)
    assert first["has_more"] is True

    fake.queries.clear()
    older = sf_chat.conversation_messages(
        42, cid, limit=10, before_seq=first["next_before_seq"],
    )
    older_page_queries = list(fake.queries)

    assert first_page_queries == older_page_queries
    assert len(first["messages"]) == 10
    assert len(older["messages"]) == 10
    # Pages do not overlap and walk strictly backwards.
    assert max(int(m["seq"]) for m in older["messages"]) \
        < min(int(m["seq"]) for m in first["messages"])


# ---------------------------------------------------------------------------
# 4. Paging is a keyset walk that covers the list exactly once.
# ---------------------------------------------------------------------------
def test_conversation_paging_covers_every_row_exactly_once(production):
    _seed(11, 1)
    seen, cursor, pages = [], "", 0
    while True:
        page = sf_chat.list_conversations(42, limit=3, cursor=cursor)
        seen.extend(row["conversation_id"] for row in page["conversations"])
        pages += 1
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
        assert cursor, "has_more without a cursor would strand the remaining rows"
        assert pages < 20, "paging did not terminate"
    assert len(seen) == 11
    assert len(set(seen)) == 11


# ---------------------------------------------------------------------------
# 5. A polling cycle must carry markers, not content.
# ---------------------------------------------------------------------------
def test_polling_cycle_transfers_markers_not_conversation_content(production):
    _seed(6, 8)
    state = sf_chat.poll_state(42)
    listing = sf_chat.list_conversations(42, limit=30)

    assert set(state["conversations"][0]) == {
        "conversation_id", "last_seq", "updated_at_utc", "last_read_seq", "unread_count",
    }
    # No titles, previews, participant profiles or message bodies.
    serialised_state = repr(state)
    assert "last_message_preview" not in serialised_state
    assert "participant" not in serialised_state
    assert len(serialised_state) < len(repr(listing))
    # A change signature covers the threads that carry no row of their own.
    assert set(state["signature"]) == {
        "conversation_count", "newest_updated_at_utc", "seq_total",
    }
    assert state["signature"]["conversation_count"] == 6


@pytest.mark.parametrize("conversations", [10, 80])
def test_idle_polling_payload_stays_flat_as_the_rail_grows(production, conversations):
    """An idle poll must not scale with the number of conversations.

    Returning a marker row per conversation made one tick carry ~290KB at 2000
    conversations — heavier than the page it was meant to replace. Only threads
    with unread earn a row now; the rest are covered by the fixed signature.
    """
    _seed(conversations, 2)
    for row in sf_chat.list_conversations(42, limit=200)["conversations"]:
        sf_chat.mark_read(42, row["conversation_id"])

    quiet = sf_chat.poll_state(42)
    assert quiet["conversations"] == []
    assert quiet["signature"]["conversation_count"] == conversations
    # Signature plus envelope only: the payload is a constant handful of fields
    # whatever the rail holds.
    assert len(repr(quiet)) < 400


# ---------------------------------------------------------------------------
# 6. ACL stays fail-closed, and concurrent viewers stay isolated.
# ---------------------------------------------------------------------------
def test_a_non_participant_is_refused_and_cannot_probe_existence(production):
    _viewer, made = _seed(1, 2)
    cid = made[0][0]
    community.ensure_social_profile(777, display_name="Outsider", username="outsider_1")

    with pytest.raises(sf_chat.SFChatError) as refused:
        sf_chat.conversation_messages(777, cid, limit=10)
    assert refused.value.status == 404

    with pytest.raises(sf_chat.SFChatError) as missing:
        sf_chat.conversation_messages(777, "sfh_does_not_exist_at_all", limit=10)
    # Same answer for "not yours" and "not there": no existence oracle.
    assert missing.value.status == refused.value.status

    assert sf_chat.list_conversations(777, limit=30)["conversations"] == []


def test_concurrent_viewers_see_only_their_own_conversations_and_unread(production):
    _viewer, made = _seed(2, 2)
    first_cid, first_partner = made[0]
    second_cid, second_partner = made[1]
    sf_chat.send_message(first_partner, first_cid, text="for the viewer only")

    viewer_rows = {row["conversation_id"]: row
                   for row in sf_chat.list_conversations(42, limit=30)["conversations"]}
    partner_rows = {row["conversation_id"]: row
                    for row in sf_chat.list_conversations(first_partner, limit=30)["conversations"]}
    other_rows = {row["conversation_id"]: row
                  for row in sf_chat.list_conversations(second_partner, limit=30)["conversations"]}

    assert set(viewer_rows) == {first_cid, second_cid}
    assert set(partner_rows) == {first_cid}
    assert set(other_rows) == {second_cid}
    # Unread is per viewer: the sender has nothing to catch up on.
    # One partner message from the seed plus the one sent above.
    assert viewer_rows[first_cid]["unread_count"] == 2
    assert partner_rows[first_cid]["unread_count"] == 0


# ---------------------------------------------------------------------------
# 7. Identity resolution stops rewriting the Community document per request.
# ---------------------------------------------------------------------------
def test_identity_is_resolved_by_index_without_touching_the_document(
    production, monkeypatch,
):
    _seed(1, 1)
    _forbid_document_loads(monkeypatch)
    identity = community.chat_identity(
        42, display_name="Viewer", username="viewer_acct", role_label="Участник",
    )
    assert identity["profile_id"]


def test_a_changed_role_label_still_reaches_the_document(production):
    documents, _fake = production
    _seed(1, 1)
    community.chat_identity(42, display_name="Viewer", username="viewer_acct",
                            role_label="Владелец")
    stored = [row for row in documents["community"]["profiles"]
              if int(row.get("user_id") or 0) == 42]
    assert stored and stored[0]["role_label"] == "Владелец"


# ---------------------------------------------------------------------------
# 8. Storage failure is surfaced, never silently answered from a document.
# ---------------------------------------------------------------------------
def test_repository_failure_fails_closed_instead_of_falling_back(production, monkeypatch):
    from app.production_storage import StorageUnavailableError

    _seed(1, 1)

    def unavailable(*_args, **_kwargs):
        raise StorageUnavailableError("Authoritative PostgreSQL is unavailable.")

    monkeypatch.setattr(storage_router, "sf_chat_conversation_page", unavailable)
    with pytest.raises(sf_chat.SFChatError) as exc:
        sf_chat.list_conversations(42, limit=30)
    assert exc.value.status == 503
