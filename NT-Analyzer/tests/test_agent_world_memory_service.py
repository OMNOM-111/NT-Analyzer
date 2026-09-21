from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from app.ai_control_center.memory_service import MemoryQuery, MemoryService
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_storage import context


NOW = datetime(2026, 9, 21, 16, 0, tzinfo=timezone.utc)


def service(tmp_path, *, legacy=(), ctx=None):
    ctx = ctx or context()
    repo = SQLiteAgentWorldRepository(tmp_path / "memory-service.sqlite3")
    return MemoryService(repo, ctx, admit=lambda: None, legacy_reader=lambda: legacy,
        now=lambda: NOW, write_gate=lambda: True)


def test_query_ranks_relevance_before_recency_and_merges_read_only_legacy(tmp_path):
    old = {"memory_id": "LEGACY-RELEVANT", "kind": "owner_note",
        "text": "Risk threshold for Agent World is fail closed.", "created_at_utc": "2025-01-01T00:00:00Z"}
    latest = {"memory_id": "LEGACY-LATEST", "kind": "owner_note",
        "text": "Unrelated lunch note", "created_at_utc": "2026-09-21T15:59:00Z"}
    memory = service(tmp_path, legacy=(old, latest))
    memory.write_fact(title="Risk", content="Agent World risk threshold requires verified evidence.",
        purpose="governance", idempotency_key="risk-threshold-v1", retention_days=365,
        evidence={"source": "test"}, verified=True)

    packet = memory.get_context(MemoryQuery(text="Agent World risk threshold", max_tokens=512))

    assert [row["memory_id"] for row in packet["entries"]] == [
        str(memory.query(MemoryQuery(text="Agent World risk threshold"))[0].identity),
        "LEGACY-RELEVANT",
    ]
    assert packet["canonical_selected"] == 1
    assert packet["legacy_selected"] == 1
    assert packet["estimated_tokens"] <= packet["token_budget"]


def test_entity_graph_conflicts_and_supersession_are_visible_not_silent(tmp_path):
    memory = service(tmp_path)
    old = memory.write_fact(title="Model", content="The selected model is version old.", purpose="configuration",
        idempotency_key="model-old-version", retention_days=365, evidence={"source": "old"})
    new = memory.write_fact(title="Model", content="The selected model is version current.", purpose="configuration",
        idempotency_key="model-current-version", retention_days=365, evidence={"source": "new"}, verified=True)
    other = memory.write_fact(title="Model dispute", content="The selected model is disputed.", purpose="configuration",
        idempotency_key="model-disputed-version", retention_days=365, evidence={"source": "other"})
    entity = memory.write_entity(entity_type="product", canonical_name="Agent World", aliases=("AW",),
        evidence={"source": "owner"}, idempotency_key="entity-agent-world")
    memory.link(source=new.ref(), relationship_type="ABOUT", target=entity.ref(), evidence={"source": "owner"},
        idempotency_key="new-about-aw")
    memory.link(source=new.ref(), relationship_type="SUPERSEDES", target=old.ref(), evidence={"source": "owner"},
        idempotency_key="new-supersedes-old")
    memory.link(source=new.ref(), relationship_type="CONTRADICTS", target=other.ref(), evidence={"source": "owner"},
        idempotency_key="new-contradicts-other")

    packet = memory.get_context(MemoryQuery(text="AW selected model", entity_names=("Agent World",), max_tokens=1_000))
    ids = {row["memory_id"] for row in packet["entries"]}
    assert str(old.header.entity_id) not in ids
    assert {str(new.header.entity_id), str(other.header.entity_id)} <= ids
    assert packet["conflict_count"] == 2
    assert all(row["conflicts"] for row in packet["entries"])
    assert "graph" in next(row for row in packet["entries"] if row["memory_id"] == str(new.header.entity_id))["score_reasons"]


def test_stable_source_survives_rename_and_versions_follow_content(tmp_path):
    memory = service(tmp_path)
    first = memory.register_source(locator="docs/Old.md", source_type="markdown", content=b"same",
        idempotency_key="first-source-read")
    renamed = memory.register_source(locator="docs/New.md", source_type="markdown", content=b"same",
        idempotency_key="renamed-source-read")
    changed = memory.register_source(locator="docs/New.md", source_type="markdown", content=b"changed",
        idempotency_key="changed-source-read")

    assert first.header.entity_id == renamed.header.entity_id == changed.header.entity_id
    assert first.source_version_id == renamed.source_version_id
    assert changed.source_version_id != renamed.source_version_id
    assert changed.header.revision == 3
    stored = memory.repository.get(context=memory.context, kind=EntityKind.KNOWLEDGE_SOURCE,
        entity_id=first.header.entity_id)
    assert stored.locator == "docs/New.md" and stored.content_sha256 == changed.content_sha256


def test_explicit_source_id_survives_simultaneous_rename_and_content_change(tmp_path):
    memory = service(tmp_path)
    identity = uuid4()
    first = memory.register_source(locator="docs/Old.md", source_type="markdown", content=b"old",
        idempotency_key="source-first-read", source_id=identity)
    changed = memory.register_source(locator="docs/Renamed.md", source_type="markdown", content=b"new",
        idempotency_key="source-second-read", source_id=identity)
    fragment_before, fact_before = memory.write_fragment(source=first, anchor="Architecture / Memory",
        title="Memory", content="old section", purpose="architecture", retention_days=365,
        evidence={"source": "test"})
    fragment_after, fact_after = memory.write_fragment(source=changed, anchor="Architecture / Memory",
        title="Memory", content="new section", purpose="architecture", retention_days=365,
        evidence={"source": "test"})

    assert first.header.entity_id == changed.header.entity_id == identity
    assert first.source_version_id != changed.source_version_id
    assert fragment_before == fragment_after
    assert fact_before.header.entity_id != fact_after.header.entity_id


def test_explicit_source_id_never_adopts_a_different_matching_locator(tmp_path):
    memory = service(tmp_path)
    first = memory.register_source(locator="docs/Shared.md", source_type="markdown", content=b"first",
        idempotency_key="first-locator-owner")
    second_id = uuid4()
    second = memory.register_source(locator="docs/Shared.md", source_type="markdown", content=b"second",
        idempotency_key="second-locator-owner", source_id=second_id)

    assert second.header.entity_id == second_id
    assert second.header.entity_id != first.header.entity_id


def test_canonical_writes_require_explicit_server_gate(tmp_path):
    ctx = context()
    memory = MemoryService(SQLiteAgentWorldRepository(tmp_path / "gated.sqlite3"), ctx, admit=lambda: None)
    with pytest.raises(ContractError, match="canonical_write_disabled"):
        memory.write_fact(title="Denied", content="must not write", purpose="gate",
            idempotency_key="disabled-write", retention_days=1, evidence={"source": "test"})


def test_task_scope_ttl_temporal_edge_and_owner_isolation(tmp_path):
    owner = context()
    memory = service(tmp_path, ctx=owner)
    fact = memory.write_fact(title="Private", content="owner-only memory", purpose="privacy",
        idempotency_key="private-owner-memory", retention_days=1, evidence={"source": "owner"})
    other = context(user=2)
    reader = MemoryService(memory.repository, other, admit=lambda: None, now=lambda: NOW)

    assert not reader.query(MemoryQuery(text="owner-only"))
    assert memory.query(MemoryQuery(text="owner-only"))[0].identity == str(fact.header.entity_id)


def test_fact_retention_and_validity_windows_are_enforced(tmp_path):
    current = [NOW]
    ctx = context()
    memory = MemoryService(SQLiteAgentWorldRepository(tmp_path / "temporal.sqlite3"), ctx,
        admit=lambda: None, now=lambda: current[0], write_gate=lambda: True)
    memory.write_fact(title="Future", content="future memory fact", purpose="temporal",
        idempotency_key="future-fact", retention_days=10, evidence={"source": "test"},
        valid_from=NOW + timedelta(days=1))
    memory.write_fact(title="Short", content="short retention fact", purpose="temporal",
        idempotency_key="short-fact", retention_days=1, evidence={"source": "test"})

    assert not memory.query(MemoryQuery(text="future memory"))
    assert memory.query(MemoryQuery(text="short retention"))
    current[0] = NOW + timedelta(days=2)
    assert memory.query(MemoryQuery(text="future memory"))
    assert not memory.query(MemoryQuery(text="short retention"))


def test_token_budget_truncates_one_oversized_fact_and_deduplicates(tmp_path):
    duplicate = {"memory_id": "legacy-duplicate", "text": "alpha " * 500,
        "created_at_utc": "2026-09-21T00:00:00Z"}
    memory = service(tmp_path, legacy=(duplicate,))
    memory.write_fact(title="Alpha", content="alpha " * 500, purpose="test",
        idempotency_key="large-alpha-fact", retention_days=10, evidence={"source": "test"})

    packet = memory.get_context(MemoryQuery(text="alpha", max_tokens=128))
    assert packet["selected_count"] == 1
    assert packet["estimated_tokens"] <= 128
    assert packet["entries"][0]["content"].endswith("[truncated to memory token budget]")


def test_a_standing_instruction_is_never_ranked_out_of_the_packet(tmp_path):
    """How the owner asked to be addressed is not a topic of the question.

    Ranking it against the current message dropped it whenever the words
    differed, and the assistant lost the owner's own name mid-conversation.
    """
    address = {"memory_id": "LEGACY-ADDRESS", "kind": "address_preference",
        "text": "Обращайся ко мне Дмитрий", "created_at_utc": "2026-08-01T10:00:00Z"}
    note = {"memory_id": "LEGACY-NOTE", "kind": "owner_note",
        "text": "Стратегия MNQ Liquidity Sweep на проверке", "created_at_utc": "2026-09-15T10:00:00Z"}
    memory = service(tmp_path, legacy=(address, note))
    for question in ("что там с MNQ Liquidity Sweep?", "поставь задачу команде на неделю", ""):
        entries = memory.get_context(MemoryQuery(text=question, max_tokens=2000))["entries"]
        assert "Обращайся ко мне Дмитрий" in [row["content"] for row in entries], question
        # It leads the packet, so a tight budget never spends itself elsewhere first.
        assert entries[0]["content"] == "Обращайся ко мне Дмитрий", question
    # The topic still decides everything that is a topic.
    about_strategy = memory.get_context(MemoryQuery(text="что там с MNQ Liquidity Sweep?", max_tokens=2000))
    assert any("MNQ" in row["content"] for row in about_strategy["entries"])
    unrelated = memory.get_context(MemoryQuery(text="поставь задачу команде на неделю", max_tokens=2000))
    assert not any("MNQ" in row["content"] for row in unrelated["entries"])


def test_a_compound_key_matches_its_parts_and_stopwords_match_nothing(tmp_path):
    """`address_preference` is one word to a regex; the question says "address"."""
    from app.ai_control_center.memory_service import _tokens

    assert {"address", "preference", "address_preference"} <= _tokens("address_preference")
    assert _tokens("и в на не что как это the and for") == frozenset()
    # A note must not become relevant because it shares "на" with the question.
    note = {"memory_id": "LEGACY-NOTE", "kind": "owner_note",
        "text": "Стратегия MNQ на проверке", "created_at_utc": "2026-09-15T10:00:00Z"}
    memory = service(tmp_path, legacy=(note,))
    packet = memory.get_context(MemoryQuery(text="поставь задачу команде на неделю", max_tokens=2000))
    assert packet["entries"] == []
