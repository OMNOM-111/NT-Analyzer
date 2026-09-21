from pathlib import Path

import pytest

from app.ai_control_center.memory_migration import (LegacyMemoryMigration, MemoryWriteMode,
    MemoryWriteRouter, resolve_write_mode, verify_cutover_report)
from app.ai_control_center.memory_service import MemoryService
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_memory_service import NOW
from tests.test_agent_world_storage import context


def migration():
    return LegacyMemoryMigration(explicit=(
        {"memory_id": "M1", "kind": "owner_note", "text": "Use verified outcomes", "entities": ["Agent World"]},
        {"memory_id": "M2", "kind": "owner_note", "text": "  use  VERIFIED outcomes  "},
        {"memory_id": "M3", "kind": "metadata"},
    ), archives=(
        {"memory_id": "A1", "kind": "conversation_archive", "dialogue": [
            {"role": "user", "content": "Keep the owner chat alive"},
            {"role": "assistant", "content": "Accepted"}], "agent_name": "Vitek"},
    ))


def test_plan_accounts_every_row_without_rewriting_source():
    source = migration()
    before = source.rows
    report = source.report()
    assert report["status"] == "PASS"
    assert report["source_total"] == report["accounted_total"] == 4
    assert report["migrate_as_history"] == 2
    assert report["deduplicated"] == 1
    assert report["intentionally_not_migrated"] == 1
    assert report["legacy_archive_read_only"] and not report["legacy_deleted"]
    assert source.rows == before


def test_apply_normalizes_deduplicates_resolves_entities_and_reconciles(tmp_path):
    ctx = context()
    repository = SQLiteAgentWorldRepository(tmp_path / "migration.sqlite3")
    service = MemoryService(repository, ctx, admit=lambda: None, now=lambda: NOW, write_gate=lambda: True)
    report = migration().apply(service)

    verify_cutover_report(report)
    assert report["applied_as_history"] == 2
    memories = list(service._all(EntityKind.MEMORY, 100))
    entities = list(service._all(EntityKind.KNOWLEDGE_ENTITY, 100))
    relationships = list(service._all(EntityKind.RELATIONSHIP, 100))
    assert len(memories) == 2 and all(item.status == "active" for item in memories)
    assert {item.canonical_name for item in entities} == {"Agent World", "Vitek"}
    assert len(relationships) == 2


def test_cutover_rejects_dry_run_partial_or_deleted_archive():
    dry = migration().report()
    with pytest.raises(ContractError, match="reconciliation_required"):
        verify_cutover_report(dry)
    partial = {**dry, "applied_as_history": 1}
    with pytest.raises(ContractError, match="reconciliation_required"):
        verify_cutover_report(partial)
    forged = {**dry, "applied_as_history": dry["migrate_as_history"], "legacy_deleted": True}
    with pytest.raises(ContractError, match="reconciliation_required"):
        verify_cutover_report(forged)


def test_write_cutover_is_reconciled_flagged_and_reversible():
    applied = {item.legacy_id: "canonical-" + item.legacy_id for item in migration().items()
               if item.action == "migrate"}
    report = migration().report(applied)
    assert resolve_write_mode(canonical_enabled=False, legacy_archive_only=False,
        reconciliation_report=None) is MemoryWriteMode.LEGACY
    assert resolve_write_mode(canonical_enabled=True, legacy_archive_only=False,
        reconciliation_report=report) is MemoryWriteMode.DUAL
    assert resolve_write_mode(canonical_enabled=True, legacy_archive_only=True,
        reconciliation_report=report) is MemoryWriteMode.CANONICAL
    with pytest.raises(ContractError, match="reconciliation_required"):
        resolve_write_mode(canonical_enabled=True, legacy_archive_only=False,
            reconciliation_report=migration().report())
    calls = []
    result = MemoryWriteRouter(mode=MemoryWriteMode.DUAL,
        legacy_write=lambda: calls.append("legacy") or "L",
        canonical_write=lambda: calls.append("canonical") or "C").write()
    assert calls == ["legacy", "canonical"] and result == {"mode": "dual", "legacy": "L", "canonical": "C"}
