"""Loss-accounted legacy JSONL -> canonical Memory migration planning.

Planning is pure and leaves both JSONL files untouched. Applying requires a
MemoryService whose canonical-write gate is already enabled by trusted server
composition.  The report is the cutover contract: every source row is either
migrated as history, deduplicated to a named survivor, or intentionally skipped
with an explicit reason; otherwise status is FAIL and cutover is forbidden.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping

from .memory_service import MemoryService
from .states import ContractError


REPORT_VERSION = "agent-world-memory-migration-v1"
_SPACE = re.compile(r"\s+")


class MemoryWriteMode(str, Enum):
    LEGACY = "legacy"
    DUAL = "dual"
    CANONICAL = "canonical"


def resolve_write_mode(*, canonical_enabled: bool, legacy_archive_only: bool,
                       reconciliation_report: Mapping[str, object] | None) -> MemoryWriteMode:
    if legacy_archive_only and not canonical_enabled:
        raise ContractError("memory_write_flag_dependency_invalid")
    if not canonical_enabled:
        return MemoryWriteMode.LEGACY
    verify_cutover_report(reconciliation_report or {})
    return MemoryWriteMode.CANONICAL if legacy_archive_only else MemoryWriteMode.DUAL


class MemoryWriteRouter:
    """Flag-selected write path; disabling flags is the rollback."""

    def __init__(self, *, mode: MemoryWriteMode, legacy_write, canonical_write):
        if not isinstance(mode, MemoryWriteMode) or not callable(legacy_write) or not callable(canonical_write):
            raise ContractError("memory_write_router_invalid")
        self.mode, self.legacy_write, self.canonical_write = mode, legacy_write, canonical_write

    def write(self):
        legacy = self.legacy_write() if self.mode in {MemoryWriteMode.LEGACY, MemoryWriteMode.DUAL} else None
        canonical = self.canonical_write() if self.mode in {MemoryWriteMode.DUAL, MemoryWriteMode.CANONICAL} else None
        return {"mode": self.mode.value, "legacy": legacy, "canonical": canonical}


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        allow_nan=False, default=str).encode("utf-8")


def _content(row: Mapping[str, object]) -> str:
    dialogue = row.get("dialogue")
    if isinstance(dialogue, list):
        return "\n".join(str(item.get("role") or "") + ": " + str(item.get("content") or "")
            for item in dialogue if isinstance(item, dict)).strip()
    return str(row.get("text") or row.get("content") or "").strip()


def _fingerprint(content: str) -> str:
    normalized = _SPACE.sub(" ", content).strip().casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _identity(row, source, index):
    return str(row.get("memory_id") or row.get("message_id") or row.get("conversation_id")
        or f"{source}:{index}")


def _entity_names(row: Mapping[str, object]) -> tuple[str, ...]:
    values = []
    raw = row.get("entities")
    if isinstance(raw, list):
        values.extend(str(value).strip() for value in raw if str(value).strip())
    for key in ("agent_name", "model", "strategy", "project"):
        if str(row.get(key) or "").strip():
            values.append(str(row[key]).strip())
    result = []
    for value in values:
        if value.casefold() not in {item.casefold() for item in result}:
            result.append(value[:160])
    return tuple(result[:32])


@dataclass(frozen=True, kw_only=True)
class MigrationItem:
    source: str
    source_index: int
    legacy_id: str
    action: str
    reason: str
    content: str
    content_sha256: str
    duplicate_of: str | None
    entity_names: tuple[str, ...]
    row_sha256: str

    def public(self) -> dict:
        return {"source": self.source, "source_index": self.source_index,
            "legacy_id": self.legacy_id, "action": self.action, "reason": self.reason,
            "content_sha256": self.content_sha256, "duplicate_of": self.duplicate_of,
            "entity_names": list(self.entity_names), "row_sha256": self.row_sha256}


class LegacyMemoryMigration:
    def __init__(self, *, explicit: Iterable[Mapping[str, object]],
                 archives: Iterable[Mapping[str, object]]):
        self.rows = (("explicit", tuple(explicit)), ("archive", tuple(archives)))

    @classmethod
    def from_jsonl(cls, explicit_path: Path, archive_path: Path):
        return cls(explicit=_read_jsonl(explicit_path), archives=_read_jsonl(archive_path))

    def items(self) -> tuple[MigrationItem, ...]:
        seen, result = {}, []
        for source, rows in self.rows:
            for index, row in enumerate(rows):
                if not isinstance(row, Mapping):
                    result.append(MigrationItem(source=source, source_index=index,
                        legacy_id=f"{source}:{index}", action="skip", reason="non_object_row",
                        content="", content_sha256=hashlib.sha256(b"").hexdigest(), duplicate_of=None,
                        entity_names=(), row_sha256=hashlib.sha256(repr(row).encode()).hexdigest()))
                    continue
                content = _content(row)
                identity = _identity(row, source, index)
                fingerprint = _fingerprint(content) if content else hashlib.sha256(b"").hexdigest()
                row_hash = hashlib.sha256(_canonical(dict(row))).hexdigest()
                if not content:
                    action, reason, duplicate = "skip", "empty_non_fact_row", None
                elif fingerprint in seen:
                    action, reason, duplicate = "deduplicate", "normalized_content_duplicate", seen[fingerprint]
                else:
                    action, reason, duplicate = "migrate", "historical_fact", None
                    seen[fingerprint] = identity
                result.append(MigrationItem(source=source, source_index=index, legacy_id=identity,
                    action=action, reason=reason, content=content, content_sha256=fingerprint,
                    duplicate_of=duplicate, entity_names=_entity_names(row), row_sha256=row_hash))
        return tuple(result)

    def report(self, applied: Mapping[str, str] | None = None) -> dict:
        items, applied = self.items(), dict(applied or {})
        counts = {name: sum(item.action == name for item in items)
                  for name in ("migrate", "deduplicate", "skip")}
        expected = counts["migrate"]
        migrated = sum(item.legacy_id in applied for item in items if item.action == "migrate")
        losses = [item.legacy_id for item in items if item.action == "migrate" and applied and item.legacy_id not in applied]
        accounted = sum(counts.values())
        status = "PASS" if accounted == len(items) and (not applied or migrated == expected) and not losses else "FAIL"
        source_digest = hashlib.sha256(_canonical([item.public() for item in items])).hexdigest()
        return {"schema_version": REPORT_VERSION, "status": status,
            "source_total": len(items), "migrate_as_history": expected,
            "deduplicated": counts["deduplicate"], "intentionally_not_migrated": counts["skip"],
            "accounted_total": accounted, "applied_as_history": migrated if applied else None,
            "losses": losses, "source_digest": source_digest,
            "legacy_archive_read_only": True, "legacy_deleted": False,
            "records": [item.public() | ({"canonical_memory_id": applied[item.legacy_id]}
                if item.legacy_id in applied else {}) for item in items]}

    def apply(self, service: MemoryService) -> dict:
        before = self.report()
        if before["status"] != "PASS":
            raise ContractError("memory_migration_plan_failed")
        applied = {}
        entities = {}
        for item in self.items():
            if item.action != "migrate":
                continue
            fact = service.write_fact(title="Legacy memory · " + item.legacy_id[:120],
                content=item.content, purpose="legacy_history", idempotency_key="legacy." + item.row_sha256,
                retention_days=3650, evidence={"source": "legacy_jsonl_read_only",
                    "legacy_id": item.legacy_id, "row_sha256": item.row_sha256,
                    "content_sha256": item.content_sha256})
            applied[item.legacy_id] = str(fact.header.entity_id)
            for name in item.entity_names:
                key = name.casefold()
                entity = entities.get(key)
                if entity is None:
                    entity = service.write_entity(entity_type="legacy_named_entity", canonical_name=name,
                        aliases=(), evidence={"source": "legacy_entity_resolution", "legacy_id": item.legacy_id},
                        idempotency_key="legacy-entity." + hashlib.sha256(key.encode()).hexdigest())
                    entities[key] = entity
                service.link(source=fact.ref(), relationship_type="ABOUT", target=entity.ref(),
                    evidence={"source": "legacy_entity_resolution", "legacy_id": item.legacy_id},
                    idempotency_key="legacy-about." + item.row_sha256 + "." + entity.header.entity_id.hex)
        report = self.report(applied)
        if report["status"] != "PASS" or report["applied_as_history"] != report["migrate_as_history"]:
            raise ContractError("memory_migration_reconciliation_failed")
        return report


def verify_cutover_report(report: Mapping[str, object]) -> None:
    required = {"schema_version", "status", "source_total", "migrate_as_history", "deduplicated",
        "intentionally_not_migrated", "accounted_total", "applied_as_history", "losses",
        "source_digest", "legacy_archive_read_only", "legacy_deleted"}
    if (not isinstance(report, Mapping) or not required <= set(report)
            or report.get("schema_version") != REPORT_VERSION or report.get("status") != "PASS"
            or report.get("legacy_archive_read_only") is not True or report.get("legacy_deleted") is not False
            or report.get("losses") != []
            or report.get("accounted_total") != report.get("source_total")
            or report.get("applied_as_history") != report.get("migrate_as_history")
            or not isinstance(report.get("source_digest"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", report["source_digest"])):
        raise ContractError("memory_cutover_reconciliation_required")


def _read_jsonl(path: Path) -> tuple[object, ...]:
    if not path.is_file():
        return ()
    rows = []
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ContractError("memory_legacy_archive_invalid") from exc
    return tuple(rows)
