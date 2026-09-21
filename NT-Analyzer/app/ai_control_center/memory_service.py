"""Canonical Agent World memory facade and token-budgeted Context Builder.

The service is intentionally storage-agnostic: both Agent World repositories
already implement the same immutable record/artifact ledger.  During migration
an authorized canonical repository and an already scope-bound legacy reader are
queried together.  The legacy reader is never a writer here.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Mapping, Sequence
from uuid import UUID, uuid5

from . import contracts as c
from .events import EventData, EventEnvelope, MutationIdentity
from .repositories import PageRequest
from .source_identity import content_sha256, fragment_id, new_source_id, source_version_id
from .states import ContractError, EntityKind


_NS = UUID("255805c9-8d33-5869-95d6-00c486619988")
_WORD = re.compile(r"[\w.-]+", re.UNICODE)
_TERMINAL_MEMORY = frozenset({"revoked", "expired", "superseded"})
# Words that carry no topic. Without this a note matched a question merely by
# sharing "на" or "the", which is noise scored as relevance.
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "was", "are", "has", "have", "not", "you", "your",
    "и", "в", "во", "на", "не", "что", "как", "это", "для", "по", "из", "за", "от", "до", "или", "но", "же",
    "бы", "ли", "мне", "мы", "вы", "он", "она", "они", "там", "тут", "уже", "ещё", "еще", "при", "над", "под",
})
# Standing instructions of the person: how to address them, what to always do.
# They are not a topic, so relevance must never drop them from the packet.
_PINNED_PURPOSES = frozenset({"address_preference", "preference", "preferences",
                              "instruction", "standing_instruction", "rule"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _tokens(text: str) -> frozenset[str]:
    """Words of a text, with compound keys split into their parts.

    `address_preference` is one token to a word regex, so a question about the
    preferred address matched nothing. Each part is kept beside the whole.
    """
    found = set()
    for value in _WORD.findall(text or ""):
        for part in (value, *re.split(r"[_.-]+", value)):
            folded = part.casefold()
            if len(folded) > 1 and folded not in _STOPWORDS:
                found.add(folded)
    return frozenset(found)


def _token_cost(text: str) -> int:
    # Conservative for Cyrillic and JSON punctuation; model-specific policies
    # may lower the final budget but must never bypass this hard bound.
    return max(1, math.ceil(len(text.encode("utf-8")) / 3.2))


def _stamp(value, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.utcoffset() == timedelta(0) else fallback
    if isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return result if result.utcoffset() == timedelta(0) else fallback
        except ValueError:
            pass
    return fallback


def _node(reference: c.EntityRef | tuple[EntityKind, UUID]) -> tuple[EntityKind, UUID]:
    return (reference.kind, reference.entity_id) if isinstance(reference, c.EntityRef) else reference


@dataclass(frozen=True, kw_only=True)
class MemoryQuery:
    text: str
    max_tokens: int = 2_000
    candidate_limit: int = 200
    entity_ids: tuple[UUID, ...] = ()
    entity_names: tuple[str, ...] = ()
    task_id: UUID | None = None
    strategy_project_id: UUID | None = None
    session_binding: str | None = None
    include_legacy: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or len(self.text) > 32_000:
            raise ContractError("memory_query_invalid")
        if type(self.max_tokens) is not int or not 128 <= self.max_tokens <= 64_000:
            raise ContractError("memory_token_budget_invalid")
        if type(self.candidate_limit) is not int or not 1 <= self.candidate_limit <= 1_000:
            raise ContractError("memory_candidate_limit_invalid")
        c.require_tuple(self.entity_ids, UUID)
        c.require_tuple(self.entity_names, str)
        for value in self.entity_ids:
            c.require_uuid(value)
        for value in self.entity_names:
            c.require_text(value)
        for value in (self.task_id, self.strategy_project_id):
            if value is not None:
                c.require_uuid(value)
        if self.session_binding is not None and not re.fullmatch(r"[0-9a-f]{64}", self.session_binding):
            raise ContractError("memory_session_binding_invalid")
        if type(self.include_legacy) is not bool:
            raise ContractError("memory_query_invalid")


@dataclass(frozen=True, kw_only=True)
class MemoryCandidate:
    identity: str
    source: str
    content: str
    title: str
    purpose: str
    created_at: datetime
    updated_at: datetime
    verified: bool
    explicit: bool
    scope: str
    task_id: UUID | None
    entity_ids: tuple[UUID, ...]
    provenance: tuple[object, ...]
    raw: Mapping[str, object]
    score: float = 0.0
    reasons: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    @property
    def token_cost(self) -> int:
        return _token_cost(self.content)

    @property
    def pinned(self) -> bool:
        """A standing instruction the person gave, not a topic of a question."""
        return self.explicit and any(
            value.casefold() in _PINNED_PURPOSES
            for value in (self.purpose, str(self.raw.get("kind") or "")) if value)


class ContextBuilder:
    """Dedupe and fit ranked authorized candidates into a token budget."""

    def build(self, query: MemoryQuery, candidates: Sequence[MemoryCandidate]) -> dict:
        selected, seen, used = [], set(), 0
        for candidate in sorted(candidates, key=lambda row: (not row.pinned, -row.score,
                                                            -row.updated_at.timestamp(), row.identity)):
            normalized = re.sub(r"\s+", " ", candidate.content).strip().casefold()
            digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            if not normalized or digest in seen:
                continue
            cost = candidate.token_cost
            if selected and used + cost > query.max_tokens:
                continue
            if not selected and cost > query.max_tokens:
                # A single large fact is summarized by bounded truncation, not
                # allowed to crowd out the entire task prompt.
                suffix = "\n[truncated to memory token budget]"
                low, high = 0, len(candidate.content)
                while low < high:
                    middle = (low + high + 1) // 2
                    if _token_cost(candidate.content[:middle] + suffix) <= query.max_tokens:
                        low = middle
                    else:
                        high = middle - 1
                candidate = replace(candidate, content=candidate.content[:low].rstrip() + suffix)
                cost = candidate.token_cost
            seen.add(digest)
            used += cost
            selected.append(candidate)
        return {
            "schema_version": "context-package-v2",
            "scope": "current_user_workspace",
            "query": query.text,
            "token_budget": query.max_tokens,
            "estimated_tokens": used,
            "entries": [self._entry(row) for row in selected],
            "candidate_count": len(candidates),
            "selected_count": len(selected),
            "conflict_count": sum(bool(row.conflicts) for row in selected),
            "legacy_selected": sum(row.source.startswith("legacy_") for row in selected),
            "canonical_selected": sum(row.source == "canonical" for row in selected),
        }

    @staticmethod
    def _entry(row: MemoryCandidate) -> dict:
        result = dict(row.raw) if row.source.startswith("legacy_") else {}
        result.update({"memory_id": row.identity, "source": row.source,
            "title": row.title, "content": row.content, "text": row.content,
            "purpose": row.purpose, "memory_scope": row.scope, "verified": row.verified,
            "score": round(row.score, 6), "score_reasons": list(row.reasons),
            "conflicts": list(row.conflicts), "entity_ids": [str(value) for value in row.entity_ids],
            "task_id": str(row.task_id) if row.task_id else None,
            "created_at_utc": c.primitive(row.created_at), "updated_at_utc": c.primitive(row.updated_at),
            "provenance": list(row.provenance)})
        result.setdefault("kind", "memory")
        return result


class MemoryService:
    """One read/write API over canonical records plus a read-only legacy view."""

    def __init__(self, repository, context: c.RequestContext | None, *, admit: Callable[[], None],
                 legacy_reader: Callable[[], Iterable[Mapping[str, object]]] | None = None,
                 now: Callable[[], datetime] | None = None, context_builder: ContextBuilder | None = None,
                 write_gate: Callable[[], bool] | None = None):
        if (repository is not None and not isinstance(context, c.RequestContext)) or not callable(admit):
            raise ContractError("memory_service_authority_required")
        if repository is None and not callable(legacy_reader):
            raise ContractError("memory_service_source_required")
        self.repository, self.context, self.admit = repository, context, admit
        self.legacy_reader = legacy_reader
        self.now = now or _utc_now
        self.context_builder = context_builder or ContextBuilder()
        self.write_gate = write_gate

    def _write_admit(self) -> None:
        self.admit()
        if not callable(self.write_gate) or self.write_gate() is not True:
            raise ContractError("memory_canonical_write_disabled")

    def query(self, query: MemoryQuery) -> tuple[MemoryCandidate, ...]:
        if not isinstance(query, MemoryQuery):
            raise ContractError("memory_query_invalid")
        self.admit()
        entities = self._entities(query.candidate_limit) if self.repository is not None else {}
        relationships = self._relationships(query.candidate_limit) if self.repository is not None else []
        canonical = self._canonical(query) if self.repository is not None else []
        legacy = self._legacy(query) if query.include_legacy else []
        return tuple(self._rank(query, [*canonical, *legacy], entities, relationships))

    def get_context(self, query: MemoryQuery) -> dict:
        result = self.context_builder.build(query, self.query(query))
        result["loaded_at_once"] = True
        return result

    def _all(self, kind: EntityKind, limit: int):
        cursor, total, seen = None, 0, set()
        while total < limit:
            page = self.repository.list(context=self.context, kind=kind,
                page=PageRequest(limit=min(100, limit - total), cursor=cursor))
            for record in page.items:
                total += 1
                yield record
            if not page.next_cursor:
                return
            if page.next_cursor in seen:
                raise ContractError("memory_cursor_invalid")
            seen.add(page.next_cursor)
            cursor = page.next_cursor

    def _json(self, record: c.Memory) -> dict | None:
        if record.header.owner_user_uuid == self.context.user_uuid:
            found = self.repository.get_artifact(context=self.context, reference=record.content)
            raw = (record.content, *found) if found is not None else None
        else:
            raw = self.repository.read_memory_artifact(context=self.context,
                memory_id=record.header.entity_id, artifact_id=record.content.artifact_id, now=self.now())
        if raw is None:
            return None
        content, media_type = raw[1], raw[2]
        if media_type != "application/json":
            return None
        try:
            value = json.loads(content)
        except (ValueError, UnicodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _policy_allowed(data: Mapping[str, object], query: MemoryQuery) -> bool:
        policy = data.get("_memory_policy") or {}
        if not isinstance(policy, dict):
            return False
        scope = str(policy.get("scope") or data.get("memory_scope") or "user")
        if scope == "session":
            return bool(query.session_binding and policy.get("session_binding") == query.session_binding)
        if scope == "strategy":
            return bool(query.strategy_project_id and policy.get("strategy_project_id") == str(query.strategy_project_id))
        if scope == "operational":
            return bool(query.task_id and policy.get("task_id") == str(query.task_id))
        return scope in {"user", "workspace", "governance"}

    def _canonical(self, query: MemoryQuery) -> list[MemoryCandidate]:
        rows = []
        for record in self._all(EntityKind.MEMORY, query.candidate_limit):
            if not isinstance(record, c.Memory) or record.status != "active" or record.retention_until <= self.now():
                continue
            data = self._json(record)
            if data is None or not self._policy_allowed(data, query):
                continue
            stamp = self.now()
            valid_from = _stamp(data.get("valid_from"), record.header.created_at)
            valid_to_raw = data.get("valid_to")
            valid_to = (_stamp(valid_to_raw, record.header.created_at)
                        if valid_to_raw is not None else None)
            if valid_from > stamp or (valid_to is not None and valid_to <= stamp):
                continue
            content = str(data.get("content") or "").strip()
            if not content:
                continue
            task_id = record.task.entity_id if record.task else None
            if record.memory_class == c.MemoryClass.TASK and task_id != query.task_id:
                continue
            policy = data.get("_memory_policy") or {}
            rows.append(MemoryCandidate(identity=str(record.header.entity_id), source="canonical", content=content,
                title=str(data.get("title") or "Memory")[:160], purpose=str(data.get("purpose") or "")[:160],
                created_at=record.header.created_at, updated_at=record.header.updated_at,
                verified=bool(record.verification or record.memory_class == c.MemoryClass.VERIFIED_LESSON),
                explicit=True, scope=str(policy.get("scope") or data.get("memory_scope") or "user"),
                task_id=task_id, entity_ids=(), provenance=tuple(c.primitive(ref) for ref in record.provenance), raw=data))
        return rows

    def _legacy(self, query: MemoryQuery) -> list[MemoryCandidate]:
        if not callable(self.legacy_reader):
            return []
        rows, fallback = [], self.now()
        for index, source in enumerate(self.legacy_reader()):
            if not isinstance(source, Mapping):
                continue
            dialogue = source.get("dialogue")
            if isinstance(dialogue, list):
                content = "\n".join(str(row.get("role") or "") + ": " + str(row.get("content") or "")
                    for row in dialogue if isinstance(row, dict))
                origin = "legacy_archive"
            else:
                content = str(source.get("text") or source.get("content") or source.get("conversation_id")
                    or source.get("title") or source.get("kind") or "")
                origin = "legacy_explicit"
            content = content.strip()
            if not content:
                continue
            created = _stamp(source.get("created_at_utc") or source.get("created_at"), fallback)
            identity = str(source.get("memory_id") or source.get("message_id") or
                uuid5(_NS, "legacy:" + hashlib.sha256(json.dumps(dict(source), sort_keys=True,
                    ensure_ascii=False, default=str).encode()).hexdigest()))
            rows.append(MemoryCandidate(identity=identity, source=origin, content=content,
                title=str(source.get("title") or source.get("kind") or "Legacy memory")[:160],
                purpose=str(source.get("purpose") or source.get("kind") or "legacy_history")[:160],
                created_at=created, updated_at=_stamp(source.get("updated_at_utc"), created),
                verified=source.get("verified") is True, explicit=origin == "legacy_explicit",
                scope="user", task_id=None, entity_ids=(), provenance=({"legacy_read_only": True},), raw=dict(source)))
            if index + 1 >= query.candidate_limit:
                break
        return rows

    def _entities(self, limit: int) -> dict[UUID, c.KnowledgeEntity]:
        return {record.header.entity_id: record for record in self._all(EntityKind.KNOWLEDGE_ENTITY, limit)
                if isinstance(record, c.KnowledgeEntity) and record.status == "active"
                and record.header.owner_user_uuid == self.context.user_uuid}

    def _relationships(self, limit: int) -> list[c.Relationship]:
        stamp = self.now()
        return [record for record in self._all(EntityKind.RELATIONSHIP, limit)
                if isinstance(record, c.Relationship) and record.status == "active"
                and record.header.owner_user_uuid == self.context.user_uuid
                and record.valid_from <= stamp and (record.valid_to is None or record.valid_to > stamp)]

    def _rank(self, query, candidates, entities, relationships):
        query_terms = _tokens(query.text) | frozenset(_tokens(" ".join(query.entity_names)))
        query_entities = set(query.entity_ids)
        for identity, entity in entities.items():
            names = _tokens(" ".join((entity.canonical_name, *entity.aliases)))
            if names & query_terms:
                query_entities.add(identity)
        adjacency: dict[tuple[EntityKind, UUID], set[tuple[EntityKind, UUID]]] = {}
        superseded, conflicts, attached = set(), {}, {}
        for edge in relationships:
            source, target = _node(edge.source), _node(edge.target)
            adjacency.setdefault(source, set()).add(target)
            adjacency.setdefault(target, set()).add(source)
            if edge.relationship_type == "SUPERSEDES" and edge.target.kind == EntityKind.MEMORY:
                superseded.add(str(edge.target.entity_id))
            if edge.relationship_type == "CONTRADICTS":
                conflicts.setdefault(str(edge.source.entity_id), set()).add(str(edge.target.entity_id))
                conflicts.setdefault(str(edge.target.entity_id), set()).add(str(edge.source.entity_id))
            if edge.source.kind == EntityKind.MEMORY and edge.target.kind == EntityKind.KNOWLEDGE_ENTITY:
                attached.setdefault(str(edge.source.entity_id), set()).add(edge.target.entity_id)
            if edge.target.kind == EntityKind.MEMORY and edge.source.kind == EntityKind.KNOWLEDGE_ENTITY:
                attached.setdefault(str(edge.target.entity_id), set()).add(edge.source.entity_id)
        distances = self._distances(query_entities, adjacency)
        now = self.now()
        ranked = []
        for candidate in candidates:
            if candidate.identity in superseded:
                continue
            terms = _tokens(" ".join((candidate.title, candidate.purpose, candidate.content)))
            lexical = len(query_terms & terms) / max(1, len(query_terms)) if query_terms else 0.5
            entity_ids = set(candidate.entity_ids) | attached.get(candidate.identity, set())
            entity_match = len(entity_ids & query_entities) / max(1, len(query_entities)) if query_entities else 0.0
            distance_values = [distances.get((EntityKind.MEMORY, UUID(candidate.identity))) for _ in (0,)
                if candidate.source == "canonical"]
            distance = next((value for value in distance_values if value is not None), None)
            graph = 1 / (1 + distance) if distance is not None else 0.0
            task = 1.0 if query.task_id and candidate.task_id == query.task_id else 0.0
            age_days = max(0.0, (now - candidate.updated_at).total_seconds() / 86400)
            recency = math.exp(-age_days / 90)
            conflict_ids = tuple(sorted(conflicts.get(candidate.identity, set())))
            score = (.35 * lexical + .25 * entity_match + .15 * graph + .15 * task
                     + .10 * float(candidate.verified) + .10 * recency + .05 * float(candidate.explicit)
                     - .10 * float(bool(conflict_ids)))
            reasons = tuple(name for name, value in (("lexical", lexical), ("entity", entity_match),
                ("graph", graph), ("task", task), ("verified", float(candidate.verified)),
                ("recency", recency), ("explicit", float(candidate.explicit))) if value > 0)
            # An unrelated recent record no longer wins merely because it was
            # written last. Empty queries intentionally form a general bundle.
            if query_terms and not (lexical or entity_match or graph or task) and not candidate.pinned:
                continue
            ranked.append(replace(candidate, entity_ids=tuple(sorted(entity_ids, key=str)),
                score=score, reasons=reasons, conflicts=conflict_ids))
        return ranked

    @staticmethod
    def _distances(entity_ids, adjacency):
        distances, queue = {}, deque()
        for identity in entity_ids:
            node = (EntityKind.KNOWLEDGE_ENTITY, identity)
            distances[node] = 0
            queue.append(node)
        while queue:
            node = queue.popleft()
            if distances[node] >= 3:
                continue
            for target in adjacency.get(node, ()):
                if target not in distances:
                    distances[target] = distances[node] + 1
                    queue.append(target)
        return distances

    # Write APIs are used only after a reconciliation PASS. They deliberately
    # do not mutate or delete the legacy reader.
    def write_fact(self, *, title: str, content: str, purpose: str, idempotency_key: str,
                   retention_days: int, evidence: Mapping[str, object], verified: bool = False,
                   valid_from: datetime | None = None, valid_to: datetime | None = None) -> c.Memory:
        if self.repository is None or getattr(self.repository, "read_only", False):
            raise ContractError("agent_world_repository_read_only")
        c.require_text(title)
        if not isinstance(content, str) or not content.strip() or len(content) > 32_000:
            raise ContractError("memory_content_invalid")
        c.require_text(purpose)
        if type(retention_days) is not int or not 1 <= retention_days <= 3650:
            raise ContractError("invalid_memory_retention")
        start = valid_from or self.now()
        c.require_utc(start)
        if valid_to is not None:
            c.require_utc(valid_to)
            if valid_to <= start:
                raise ContractError("memory_validity_invalid")
        self._write_admit()
        identity = uuid5(_NS, f"{self.context.scope.environment.value}:{self.context.scope.workspace_id}:"
            f"{self.context.user_uuid}:fact:{idempotency_key}")
        found = self.repository.get(context=self.context, kind=EntityKind.MEMORY, entity_id=identity)
        if found is not None:
            if not isinstance(found, c.Memory) or found.header.owner_user_uuid != self.context.user_uuid:
                raise ContractError("memory_record_conflict")
            if found.status == "active":
                return found
            if found.status != "draft":
                raise ContractError("memory_record_conflict")
            active = replace(found, status="active", header=replace(found.header,
                revision=found.header.revision + 1, updated_at=self.now()))
            return self._commit(active, found.header.revision, "fact.activate", idempotency_key + ".activate")
        policy = self._artifact({"version": "memory-service-v1", "legacy_deleted": False})
        proof = self._artifact({"source": "memory_service", "evidence": dict(evidence),
            "idempotency_sha256": hashlib.sha256(idempotency_key.encode()).hexdigest()})
        payload = {"title": title.strip(), "content": content.strip(), "purpose": purpose.strip(),
            "memory_scope": "user", "valid_from": c.primitive(start),
            "valid_to": c.primitive(valid_to) if valid_to else None,
            "_memory_policy": {"version": 1, "scope": "user", "record_id": str(identity)}}
        definition = self._artifact(payload)
        stamp = self.now()
        header = c.RecordHeader(entity_id=identity, scope=self.context.scope, owner_user_uuid=self.context.user_uuid,
            revision=1, created_at=stamp, updated_at=stamp, created_by=self.context.actor,
            correlation_id=identity, policy=policy)
        memory_class = c.MemoryClass.VERIFIED_LESSON if verified else c.MemoryClass.PRIVATE
        draft = c.Memory(header=header, status="draft", memory_class=memory_class,
            visibility=c.Visibility.PRIVATE, sensitivity=c.Sensitivity.CONFIDENTIAL,
            content=definition, provenance=(proof,), retention_until=stamp + timedelta(days=retention_days),
            verification=proof if verified else None)
        draft = self._commit(draft, 0, "fact.create", idempotency_key)
        active = replace(draft, status="active", header=replace(draft.header, revision=2, updated_at=self.now()))
        return self._commit(active, 1, "fact.activate", idempotency_key + ".activate")

    def write_fragment(self, *, source: c.KnowledgeSource, anchor: str, title: str,
                       content: str, purpose: str, retention_days: int,
                       evidence: Mapping[str, object], verified: bool = False) -> tuple[UUID, c.Memory]:
        """Persist one logical section with an id stable across locator changes."""
        if not isinstance(source, c.KnowledgeSource):
            raise ContractError("knowledge_source_required")
        if source.header.scope != self.context.scope or source.header.owner_user_uuid != self.context.user_uuid:
            raise ContractError("knowledge_source_scope_denied")
        identity = fragment_id(source.header.entity_id, anchor)
        fact = self.write_fact(title=title, content=content, purpose=purpose,
            idempotency_key="fragment." + identity.hex + "." + source.source_version_id.hex,
            retention_days=retention_days,
            evidence={**dict(evidence), "source_id": str(source.header.entity_id),
                "source_version_id": str(source.source_version_id), "fragment_id": str(identity),
                "fragment_anchor": anchor}, verified=verified)
        self.link(source=fact.ref(), relationship_type="DERIVED_FROM", target=source.ref(),
            evidence={"source": "stable_fragment", "fragment_id": str(identity),
                "source_version_id": str(source.source_version_id)},
            idempotency_key="fragment-derived." + identity.hex + "." + source.source_version_id.hex)
        return identity, fact

    def write_entity(self, *, entity_type: str, canonical_name: str, aliases: tuple[str, ...],
                     evidence: Mapping[str, object], idempotency_key: str) -> c.KnowledgeEntity:
        self._write_admit()
        proof = self._artifact(dict(evidence))
        identity = uuid5(_NS, f"{self.context.scope}:{self.context.user_uuid}:entity:{idempotency_key}")
        found = self.repository.get(context=self.context, kind=EntityKind.KNOWLEDGE_ENTITY, entity_id=identity)
        if found is not None:
            if not isinstance(found, c.KnowledgeEntity) or found.header.owner_user_uuid != self.context.user_uuid:
                raise ContractError("knowledge_entity_conflict")
            return found
        policy = self._artifact({"version": "knowledge-graph-v1"})
        stamp = self.now()
        record = c.KnowledgeEntity(header=c.RecordHeader(entity_id=identity, scope=self.context.scope,
            owner_user_uuid=self.context.user_uuid, revision=1, created_at=stamp, updated_at=stamp,
            created_by=self.context.actor, correlation_id=identity, policy=policy), status="active",
            entity_type=entity_type, canonical_name=canonical_name, aliases=aliases, provenance=(proof,))
        return self._commit(record, 0, "entity.create", idempotency_key)

    def link(self, *, source: c.EntityRef, relationship_type: str, target: c.EntityRef,
             evidence: Mapping[str, object], idempotency_key: str,
             valid_from: datetime | None = None, valid_to: datetime | None = None) -> c.Relationship:
        self._write_admit()
        proof = self._artifact(dict(evidence))
        identity = uuid5(_NS, f"{self.context.scope}:{self.context.user_uuid}:edge:{idempotency_key}")
        found = self.repository.get(context=self.context, kind=EntityKind.RELATIONSHIP, entity_id=identity)
        if found is not None:
            if not isinstance(found, c.Relationship) or found.header.owner_user_uuid != self.context.user_uuid:
                raise ContractError("relationship_record_conflict")
            return found
        policy = self._artifact({"version": "knowledge-graph-v1"})
        stamp = self.now()
        record = c.Relationship(header=c.RecordHeader(entity_id=identity, scope=self.context.scope,
            owner_user_uuid=self.context.user_uuid, revision=1, created_at=stamp, updated_at=stamp,
            created_by=self.context.actor, correlation_id=identity, policy=policy), status="active",
            source=source, relationship_type=relationship_type, target=target, provenance=(proof,),
            valid_from=valid_from or stamp, valid_to=valid_to)
        return self._commit(record, 0, "relationship.create", idempotency_key)

    def register_source(self, *, locator: str, source_type: str, content: bytes,
                        idempotency_key: str, source_id: UUID | None = None) -> c.KnowledgeSource:
        self._write_admit()
        c.require_text(locator, limit=1000)
        c.require_token(source_type, limit=80)
        digest, version = content_sha256(content), source_version_id(content)
        if source_id is not None:
            c.require_uuid(source_id)
            current = self.repository.get(context=self.context, kind=EntityKind.KNOWLEDGE_SOURCE,
                entity_id=source_id)
            if current is not None and not isinstance(current, c.KnowledgeSource):
                raise ContractError("knowledge_source_conflict")
        else:
            current = next((row for row in self._all(EntityKind.KNOWLEDGE_SOURCE, 1_000)
                if isinstance(row, c.KnowledgeSource)
                and row.header.owner_user_uuid == self.context.user_uuid
                and (row.locator == locator or row.content_sha256 == digest)), None)
        evidence = self._artifact({"locator": locator, "content_sha256": digest,
            "source_version_id": str(version), "captured_at": c.primitive(self.now())})
        if current is None:
            identity = source_id or new_source_id(
                f"{self.context.scope}:{self.context.user_uuid}:{idempotency_key}")
            policy = self._artifact({"version": "stable-source-v1"})
            stamp = self.now()
            record = c.KnowledgeSource(header=c.RecordHeader(entity_id=identity, scope=self.context.scope,
                owner_user_uuid=self.context.user_uuid, revision=1, created_at=stamp, updated_at=stamp,
                created_by=self.context.actor, correlation_id=identity, policy=policy), status="active",
                source_type=source_type, locator=locator, source_version_id=version,
                content_sha256=digest, observed_at=stamp, evidence=evidence)
            return self._commit(record, 0, "source.create", idempotency_key)
        if (current.locator, current.source_version_id, current.content_sha256) == (locator, version, digest):
            return current
        updated = replace(current, header=replace(current.header, revision=current.header.revision + 1,
            updated_at=self.now()), locator=locator, source_version_id=version, content_sha256=digest,
            observed_at=self.now(), evidence=evidence)
        return self._commit(updated, current.header.revision, "source.observe",
            idempotency_key + ".observe." + digest[:16])

    def _artifact(self, value: Mapping[str, object]) -> c.SnapshotRef:
        self.admit()
        try:
            raw = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise ContractError("invalid_memory_payload") from exc
        return self.repository.put_artifact(context=self.context, content=raw, media_type="application/json")

    def _commit(self, record, previous, operation, key):
        self.admit()
        event = EventEnvelope(event_id=uuid5(record.header.entity_id, f"revision:{record.header.revision}"),
            event_type=f"stratforge.ai.{record.KIND.value}.changed", time=record.header.updated_at,
            subject=record.ref(), actor=self.context.actor, correlation_id=record.header.correlation_id,
            policy=record.header.policy, causation_id=record.header.causation_id,
            data=EventData(reason_code="memory_service"))
        safe_key = "memory." + hashlib.sha256(key.encode("utf-8")).hexdigest()
        mutation = MutationIdentity.for_record(context=self.context,
            operation="agent_world.memory." + operation, idempotency_key=safe_key,
            record=record, expected_revision=previous, event=event)
        return self.repository.commit(context=self.context, record=record, expected_revision=previous,
            event=event, mutation=mutation).record
