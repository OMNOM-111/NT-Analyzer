"""Real PostgreSQL acceptance for the SF Chat relational read path.

Runs only when acceptance DSNs are supplied, following the same convention as
the Stage 8 suite:

    STRATFORGE_TEST_POSTGRES_ADMIN_URL   schema owner, used to migrate/truncate
    STRATFORGE_TEST_POSTGRES_URL         the constrained application role

Without them the module is skipped rather than silently passing — a skipped
acceptance run is honest, a green one that never touched a database is not.

What these check that the in-memory equivalence tests cannot: that the SQL is
valid, that the planner actually uses the intended indexes instead of scanning
`sf_chat_messages`, that FORCE RLS still admits the service scope, and that
several viewers reading at once stay isolated.
"""
from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.production_storage import MigrationRunner, Scope
from app.production_storage.core import (
    CommunityRepository,
    DocumentRepository,
    PostgresClient,
    SFChatRepository,
)

ADMIN_URL = os.environ.get("STRATFORGE_TEST_POSTGRES_ADMIN_URL", "")
APP_URL = os.environ.get("STRATFORGE_TEST_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL or not APP_URL,
    reason="real PostgreSQL SF Chat acceptance DSNs were not provided",
)

VIEWER_USER = 9101
PARTNER_BASE = 9200


def _service_scope(conn) -> None:
    """Give a raw fixture connection the scope the service always sets.

    Every table carries FORCE ROW LEVEL SECURITY and a policy of
    `sf_scope_global() OR user_id = sf_scope_user()`. `PostgresClient`
    establishes that scope per transaction; a bare psycopg connection does not,
    so seeding would be refused by the very policy the suite exists to prove.
    Setting it here keeps RLS enforced rather than granting the fixture
    BYPASSRLS, which would switch the protection off instead of satisfying it.
    """
    conn.execute("SELECT set_config('stratforge.service_scope', 'global', false)")


def _truncate(admin_url: str) -> None:
    import psycopg

    with psycopg.connect(admin_url, autocommit=True) as conn:
        _service_scope(conn)
        conn.execute(
            """
            TRUNCATE sf_chat_reads, sf_chat_messages, sf_chat_participants,
              sf_chat_conversations, sf_community_bookmarks,
              sf_community_reactions, sf_community_comments,
              sf_community_moderation_reports, sf_community_blocks,
              sf_community_follows, sf_community_posts, sf_community_profiles,
              sf_repository_documents, sf_users
            RESTART IDENTITY CASCADE
            """
        )


def _profile_id(index: int) -> str:
    return f"sfp_acceptance_{index:012d}"


def _build_document(conversations: int, messages_each: int) -> tuple:
    """A community + sf_chat document pair, as the writer would persist them."""
    viewer = _profile_id(0)
    profiles = [{
        "profile_id": viewer, "user_id": VIEWER_USER,
        "display_name": "Acceptance Viewer", "username": "acc_viewer",
        "role_label": "Участник", "bio": "", "profile_visibility": "network",
        "allow_messages": "everyone", "joined_at_utc": "2026-01-01T00:00:00Z",
        "created_at_utc": "2026-01-01T00:00:00Z",
        "updated_at_utc": "2026-01-01T00:00:00Z", "has_avatar": False,
    }]
    convs, msgs, reads = [], [], []
    seq_total = 0
    for index in range(conversations):
        partner = _profile_id(index + 1)
        profiles.append({
            "profile_id": partner, "user_id": PARTNER_BASE + index,
            "display_name": f"Partner {index}", "username": f"acc_partner_{index:04d}",
            "role_label": "Участник", "bio": "", "profile_visibility": "network",
            "allow_messages": "everyone", "joined_at_utc": "2026-01-01T00:00:00Z",
            "created_at_utc": "2026-01-01T00:00:00Z",
            "updated_at_utc": "2026-01-01T00:00:00Z", "has_avatar": False,
        })
        cid = f"sfh_acceptance_{index:012d}"
        # Distinct timestamps so keyset order is total and reproducible.
        stamp = f"2026-09-01T{index // 3600:02d}:{index // 60 % 60:02d}:{index % 60:02d}Z"
        convs.append({
            "conversation_id": cid, "conversation_type": "human",
            "participant_profile_ids": [viewer, partner],
            "created_at_utc": "2026-01-01T00:00:00Z", "updated_at_utc": stamp,
            "last_seq": messages_each,
        })
        for step in range(messages_each):
            seq_total += 1
            msgs.append({
                "message_id": f"sfm_acceptance_{seq_total:012d}",
                "conversation_id": cid, "seq": step + 1,
                "sender_profile_id": viewer if step % 2 == 0 else partner,
                "text": f"acceptance {index}-{step}", "attachments": [],
                "created_at_utc": stamp, "timestamp_utc": stamp,
            })
        reads.append({"conversation_id": cid, "profile_id": viewer,
                      "last_read_seq": 0, "read_at_utc": stamp})
    community = {"version": 1, "profiles": profiles, "accounts": [], "posts": [],
                 "comments": [], "reactions": [], "bookmarks": [], "follows": [],
                 "social_blocks": [], "moderation_reports": []}
    chat = {"version": 1, "conversations": convs, "messages": msgs, "reads": reads}
    return viewer, community, chat


@pytest.fixture()
def seeded():
    """Migrated schema holding a viewer with conversations and history."""
    import psycopg

    MigrationRunner(ADMIN_URL).apply()
    _truncate(ADMIN_URL)

    conversations, messages_each = 40, 25
    viewer, community_doc, chat_doc = _build_document(conversations, messages_each)

    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        _service_scope(conn)
        conn.execute(
            "INSERT INTO sf_users(user_id,status,is_owner,document) VALUES(%s,'active',TRUE,'{}'::jsonb)",
            (VIEWER_USER,),
        )
        for index in range(conversations):
            conn.execute(
                "INSERT INTO sf_users(user_id,status,is_owner,document) VALUES(%s,'active',FALSE,'{}'::jsonb)",
                (PARTNER_BASE + index,),
            )

    # Loopback acceptance instance, not a Production endpoint: the production
    # client would (correctly) demand TLS that a throwaway local server has no
    # certificate for.
    client = PostgresClient(APP_URL, production=False)
    documents = DocumentRepository(client)
    # The repository refuses a blind write: a document must be read first so a
    # concurrent update cannot be clobbered. Seeding follows the same rule.
    documents.read("community", {})
    documents.write("community", community_doc)
    documents.read("sf_chat", {})
    documents.write("sf_chat", chat_doc)
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        _service_scope(conn)
        conn.execute("ANALYZE sf_chat_messages")
        conn.execute("ANALYZE sf_chat_conversations")
        conn.execute("ANALYZE sf_chat_participants")
    return {
        "client": client, "viewer": viewer,
        "conversations": conversations, "messages_each": messages_each,
        "scope": Scope.global_service_scope(),
    }


def test_conversation_paging_walks_the_keyset_without_repeats(seeded):
    repo = SFChatRepository(seeded["client"])
    seen, cursor, pages = [], None, 0
    while True:
        page = repo.conversation_page(
            seeded["viewer"], scope=seeded["scope"], limit=7, cursor=cursor,
        )
        seen.extend(str(row["conversation_id"]) for row in page["rows"])
        pages += 1
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
        assert cursor
        assert pages < 50
    assert len(seen) == seeded["conversations"]
    assert len(set(seen)) == seeded["conversations"]


def test_conversation_page_carries_unread_and_last_message_in_one_statement(seeded):
    repo = SFChatRepository(seeded["client"])
    page = repo.conversation_page(seeded["viewer"], scope=seeded["scope"], limit=5)
    assert len(page["rows"]) == 5
    for row in page["rows"]:
        assert row["message_count"] == seeded["messages_each"]
        # Read pointer is 0 and the partner sent every odd seq.
        assert row["unread_count"] == seeded["messages_each"] // 2
        assert row["last_message"]["seq"] == seeded["messages_each"]


def test_history_pages_backwards_without_overlap(seeded):
    repo = SFChatRepository(seeded["client"])
    first_id = repo.conversation_page(
        seeded["viewer"], scope=seeded["scope"], limit=1,
    )["rows"][0]["conversation_id"]

    newest = repo.message_page(first_id, scope=seeded["scope"], limit=10)
    assert len(newest["messages"]) == 10
    assert newest["has_more"] is True
    older = repo.message_page(
        first_id, scope=seeded["scope"], limit=10,
        before_seq=newest["next_before_seq"],
    )
    assert max(int(m["seq"]) for m in older["messages"]) \
        < min(int(m["seq"]) for m in newest["messages"])


def test_history_and_listing_use_indexes_rather_than_scanning_messages(seeded):
    """The planner must not read `sf_chat_messages` end to end for a page."""
    client = seeded["client"]
    first_id = SFChatRepository(client).conversation_page(
        seeded["viewer"], scope=seeded["scope"], limit=1,
    )["rows"][0]["conversation_id"]
    with client.transaction(seeded["scope"], read_only=True) as conn:
        plan = "\n".join(str(row["QUERY PLAN"]) for row in conn.execute(
            """
            EXPLAIN SELECT seq, document FROM sf_chat_messages
             WHERE conversation_id = %s AND deleted_at IS NULL
             ORDER BY seq DESC LIMIT 50
            """,
            (first_id,),
        ).fetchall())
    assert "Seq Scan on sf_chat_messages" not in plan, plan
    assert "Index" in plan, plan


def test_a_non_participant_reads_nothing_under_the_service_scope(seeded):
    repo = SFChatRepository(seeded["client"])
    outsider = _profile_id(10_000)
    first_id = repo.conversation_page(
        seeded["viewer"], scope=seeded["scope"], limit=1,
    )["rows"][0]["conversation_id"]
    assert repo.conversation(first_id, outsider, scope=seeded["scope"]) is None
    assert repo.conversation_page(outsider, scope=seeded["scope"], limit=10)["rows"] == []
    assert repo.unread_total(outsider, scope=seeded["scope"]) == 0


def test_poll_state_returns_markers_only(seeded):
    repo = SFChatRepository(seeded["client"])
    state = repo.poll_state(seeded["viewer"], scope=seeded["scope"])
    assert state["rows"]
    assert set(state["rows"][0]) == {
        "conversation_id", "last_seq", "updated_at", "last_read_seq", "unread_count",
    }


def test_profiles_resolve_in_one_statement_for_a_whole_page(seeded):
    repo = CommunityRepository(seeded["client"])
    wanted = [_profile_id(index) for index in range(0, 12)]
    rows = repo.public_profiles(seeded["viewer"], wanted, scope=seeded["scope"])
    assert {str(row["profile_id"]) for row in rows} == set(wanted)
    for row in rows:
        assert row["followers"] == 0 and row["following"] == 0
        assert row["blocked"] is False


def test_identity_lookup_uses_the_unique_user_index(seeded):
    client = seeded["client"]
    with client.transaction(seeded["scope"], read_only=True) as conn:
        plan = "\n".join(str(row["QUERY PLAN"]) for row in conn.execute(
            """
            EXPLAIN SELECT profile_id, user_id, user_uuid, document
              FROM sf_community_profiles
             WHERE ('' <> '' AND user_uuid::text = '')
                OR ('' = '' AND user_id = %s)
             LIMIT 1
            """,
            (VIEWER_USER,),
        ).fetchall())
    assert "Seq Scan on sf_community_profiles" not in plan, plan


def test_concurrent_viewers_read_their_own_rows_simultaneously(seeded):
    """Several open panels at once must stay isolated and keep working."""
    repo = SFChatRepository(seeded["client"])
    viewers = [_profile_id(index) for index in range(1, 9)]

    def read(profile_id: str):
        page = repo.conversation_page(profile_id, scope=seeded["scope"], limit=10)
        state = repo.poll_state(profile_id, scope=seeded["scope"])
        return profile_id, [str(row["conversation_id"]) for row in page["rows"]], \
            len(state["rows"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(read, viewers))

    for profile_id, conversation_ids, state_rows in results:
        # Every partner participates in exactly one conversation.
        assert len(conversation_ids) == 1, (profile_id, conversation_ids)
        assert state_rows == 1
    # No two partners saw the same conversation.
    everything = [cid for _pid, cids, _n in results for cid in cids]
    assert len(set(everything)) == len(everything)
