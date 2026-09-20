"""Reference-only event envelope and mutation identity; no event delivery."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

from .contracts import (
    ActorRef, EntityRef, Record, RequestContext, SnapshotRef, TenantScope,
    primitive, require_same_scope, require_token, require_tuple, require_utc,
    require_uuid, require_revision,
)
from .states import ContractError


EVENT_TYPES = frozenset("stratforge.ai." + value for value in (
    "intent.created", "intent.changed", "task.assigned", "task.started",
    "task.completed", "task.failed", "task.changed", "contribution.recorded", "contribution.changed",
    "decision.proposed", "decision.approved", "decision.rejected", "decision.changed",
    "court.opened", "court.voted", "court.closed", "execution.requested",
    "execution.started", "execution.completed", "execution.failed", "execution.deviated", "execution.changed",
    "outcome.verified", "outcome.changed", "evaluation.recorded", "memory.promoted",
    "memory.revoked", "memory.changed", "persona.changed", "agent_role.changed",
    "provider_account.changed", "model.changed", "external_agent_connection.changed",
    "strategy_project.changed", "routine.changed", "calendar_item.changed",
    "court_case.changed", "court_vote.recorded",
))

# Generic *.changed events carry revisions. Semantic claims also constrain state.
EVENT_STATES = MappingProxyType({"stratforge.ai." + name: frozenset(states) for name, states in (
    ("intent.created", ("draft",)), ("task.assigned", ("planned", "ready")),
    ("task.started", ("running",)), ("task.completed", ("succeeded",)),
    ("task.failed", ("failed",)), ("decision.proposed", ("proposed",)),
    ("decision.approved", ("approved",)), ("decision.rejected", ("rejected",)),
    ("execution.requested", ("requested",)), ("execution.started", ("running",)),
    ("execution.completed", ("succeeded",)), ("execution.failed", ("failed",)),
    ("execution.deviated", ("deviated",)), ("outcome.verified", ("verified",)),
    ("memory.promoted", ("active",)), ("memory.revoked", ("revoked",)),
)})


@dataclass(frozen=True, kw_only=True)
class EventData:
    references: tuple[EntityRef | SnapshotRef, ...] = ()
    reason_code: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        require_tuple(self.references, (EntityRef, SnapshotRef))
        if len(self.references) > 64:
            raise ContractError("too_many_event_references")
        if self.reason_code is not None:
            require_token(self.reason_code, limit=80)
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ContractError("unsupported_schema")


@dataclass(frozen=True, kw_only=True)
class EventEnvelope:
    event_id: UUID
    event_type: str
    time: datetime
    subject: EntityRef
    actor: ActorRef
    correlation_id: UUID
    policy: SnapshotRef
    data: EventData
    causation_id: UUID | None = None

    def __post_init__(self) -> None:
        require_uuid(self.event_id)
        require_uuid(self.correlation_id)
        require_utc(self.time)
        if self.causation_id is not None:
            require_uuid(self.causation_id)
            if self.causation_id == self.event_id:
                raise ContractError("event_self_causation")
        if not isinstance(self.event_type, str) or self.event_type not in EVENT_TYPES:
            raise ContractError("unknown_event_type")
        if (not isinstance(self.subject, EntityRef) or not isinstance(self.actor, ActorRef)
                or not isinstance(self.policy, SnapshotRef) or not isinstance(self.data, EventData)):
            raise ContractError("event_contract_required")
        require_same_scope(self.subject.scope, self.policy.scope)
        for reference in self.data.references:
            require_same_scope(self.subject.scope, reference.scope)

    @property
    def scope(self) -> TenantScope:
        return self.subject.scope

    def as_dict(self) -> dict:
        """Fresh internal wire object with primitive CloudEvents extensions."""
        event = {
            "specversion": "1.0", "id": str(self.event_id),
            "source": "urn:stratforge:ai-control-center", "type": self.event_type,
            "time": primitive(self.time),
            "subject": f"{self.subject.kind.value}/{self.subject.entity_id}",
            "environment": self.scope.environment.value,
            "workspaceid": self.scope.workspace_id,
            "correlationid": str(self.correlation_id),
            "datacontenttype": "application/json",
            "data": {"subject": primitive(self.subject), "actor": primitive(self.actor),
                     "policy": primitive(self.policy), **primitive(self.data)},
        }
        if self.causation_id is not None:
            event["causationid"] = str(self.causation_id)
        return event


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def request_digest(*, context: RequestContext, record: Record,
                   expected_revision: int, event: EventEnvelope) -> str:
    if (not isinstance(context, RequestContext) or not isinstance(record, Record)
            or not isinstance(event, EventEnvelope)):
        raise ContractError("mutation_contract_required")
    require_revision(expected_revision, zero=True)
    return _digest({"context": primitive(context), "record": primitive(record),
                    "expected_revision": expected_revision, "event": event.as_dict()})


@dataclass(frozen=True, kw_only=True)
class MutationIdentity:
    scope: TenantScope
    operation: str
    key_hash: str = field(repr=False)
    request_hash: str

    def __post_init__(self) -> None:
        require_same_scope(self.scope, self.scope)
        require_token(self.operation, limit=100)
        for digest in (self.key_hash, self.request_hash):
            if (not isinstance(digest, str) or len(digest) != 64
                    or any(c not in "0123456789abcdef" for c in digest)):
                raise ContractError("invalid_sha256")

    @classmethod
    def for_record(cls, *, context: RequestContext, operation: str,
                   idempotency_key: str, record: Record, expected_revision: int,
                   event: EventEnvelope) -> MutationIdentity:
        # The raw caller key exists only during construction, never in repr or events.
        if (not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 160
                or any(ord(c) < 33 or ord(c) > 126 for c in idempotency_key)):
            raise ContractError("invalid_idempotency_key")
        if not isinstance(context, RequestContext):
            raise ContractError("context_required")
        return cls(scope=context.scope, operation=operation,
                   key_hash=hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest(),
                   request_hash=request_digest(context=context, record=record,
                                               expected_revision=expected_revision, event=event))

    @property
    def storage_key(self) -> tuple[str, str, str, str]:
        return (self.scope.environment.value, self.scope.workspace_id,
                self.operation, self.key_hash)


def is_replay(existing: MutationIdentity, candidate: MutationIdentity) -> bool:
    """Pure comparison; atomic reservation/replay belongs to the existing store."""
    if existing.storage_key != candidate.storage_key:
        return False
    if existing.request_hash != candidate.request_hash:
        raise ContractError("idempotency_conflict")
    return True
