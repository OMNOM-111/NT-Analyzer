from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest

from app.ai_control_center import contracts as c
from app.ai_control_center.relationship_registry import RELATIONSHIP_TYPES
from app.ai_control_center.source_identity import fragment_id, source_version_id
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_contracts import NOW, SCOPE, header, ref, snapshot


def test_memory_contract_remains_the_fact_contract():
    assert [field.name for field in __import__("dataclasses").fields(c.Memory)] == [
        "header", "status", "memory_class", "visibility", "sensitivity", "content",
        "provenance", "retention_until", "verification", "task",
    ]


def test_entity_relationship_and_source_are_additive_typed_records():
    entity = c.KnowledgeEntity(header=header(), status="active", entity_type="project",
        canonical_name="Agent World", aliases=("AW",), provenance=(snapshot(),))
    edge = c.Relationship(header=replace(header(), entity_id=UUID(int=4)), status="active",
        source=entity.ref(), relationship_type="ABOUT", target=ref(EntityKind.MEMORY),
        provenance=(snapshot(),), valid_from=NOW)
    source = c.KnowledgeSource(header=replace(header(), entity_id=UUID(int=5)), status="active",
        source_type="markdown", locator="docs/agent-world.md", source_version_id=UUID(int=6),
        content_sha256="b" * 64, observed_at=NOW, evidence=snapshot())
    assert edge.relationship_type in RELATIONSHIP_TYPES
    assert source.ref().kind is EntityKind.KNOWLEDGE_SOURCE


def test_relationship_registry_temporal_and_scope_guards():
    values = dict(header=header(), status="active", source=ref(EntityKind.MEMORY),
        target=ref(EntityKind.KNOWLEDGE_ENTITY, number=31), provenance=(snapshot(),), valid_from=NOW)
    with pytest.raises(ContractError, match="unregistered"):
        c.Relationship(**values, relationship_type="MADE_UP")
    with pytest.raises(ContractError, match="validity"):
        c.Relationship(**values, relationship_type="ABOUT", valid_to=NOW - timedelta(seconds=1))
    foreign = replace(SCOPE, workspace_id="ws_example02")
    with pytest.raises(ContractError, match="scope_mismatch"):
        c.Relationship(**{**values, "source": ref(EntityKind.MEMORY, scope=foreign)}, relationship_type="ABOUT")


def test_source_versions_follow_content_and_fragments_follow_source_anchor_not_path():
    source = UUID(int=120)
    assert source_version_id(b"same bytes") == source_version_id(b"same bytes")
    assert source_version_id(b"same bytes") != source_version_id(b"changed")
    assert fragment_id(source, "Plan / Phase 1") == fragment_id(source, "  plan / PHASE 1 ")
    assert fragment_id(source, "Plan / Phase 1") != fragment_id(source, "Plan / Phase 2")
