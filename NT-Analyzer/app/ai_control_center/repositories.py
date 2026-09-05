"""Storage contracts only. Stage 2 supplies SQLite/PostgreSQL implementations.

No queue, budget, permission engine, global read or in-memory authority here.
Admission must validate membership, capabilities and artifact access before
calling these interfaces. RLS and atomicity still require real storage tests.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Generic, Protocol, TypeVar
from uuid import UUID

from .contracts import (EntityKind, Record, RequestContext, require_revision,
                        require_same_scope, require_token, require_tuple, validate_record_scope)
from .events import EVENT_STATES, EventEnvelope, MutationIdentity, request_digest
from .states import ContractError, EDITABLE_STATES, INITIAL_STATES, validate_transition


T = TypeVar("T")


@dataclass(frozen=True, kw_only=True)
class PageRequest:
    limit: int = 50
    cursor: str | None = None

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ContractError("invalid_page_limit")
        if self.cursor is not None:
            require_token(self.cursor, limit=512)


@dataclass(frozen=True, kw_only=True)
class Page(Generic[T]):
    items: tuple[T, ...]
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        require_tuple(self.items, object)
        if self.next_cursor is not None:
            require_token(self.next_cursor, limit=512)


class RecordRepository(Protocol):
    def get(self, *, context: RequestContext, kind: EntityKind,
            entity_id: UUID) -> Record | None:
        """Scoped lookup; forbidden and absent records do not leak existence."""
        ...

    def list(self, *, context: RequestContext, kind: EntityKind,
             page: PageRequest) -> Page[Record]:
        """Stable opaque cursor bound to tenant, user and filter; never list all."""
        ...


@dataclass(frozen=True, kw_only=True)
class CommitResult:
    record: Record
    event: EventEnvelope
    replayed: bool


class UnitOfWork(Protocol):
    def commit(self, *, context: RequestContext, record: Record,
               expected_revision: int, event: EventEnvelope,
               mutation: MutationIdentity) -> CommitResult:
        """Atomically CAS record + append event + outbox + idempotency result.

        expected_revision=0 creates; a mutation of revision N creates N+1.
        A matching completed mutation replays its original result first.
        Same-key/different-hash and stale revisions conflict. No dual writes.
        """
        ...


class EventRepository(Protocol):
    def list(self, *, context: RequestContext, page: PageRequest) -> Page[EventEnvelope]:
        """Authorized tenant/user event view, stable cursor and explicit gaps."""
        ...

    def acknowledge(self, *, context: RequestContext, consumer: str,
                    event_id: UUID) -> bool:
        """Deduplicate delivery after idempotent effects; never before commit.

        Inbox key: tenant + consumer + event UUID. A database implementation
        may share the UnitOfWork transaction; external effects require replay.
        """
        ...

    def is_acknowledged(self, *, context: RequestContext, consumer: str,
                        event_id: UUID) -> bool:
        """Read a consumer receipt through the same fresh scoped event view.

        Unknown/foreign events return false. This never creates an inbox row,
        reserves work, grants visibility or acknowledges an unfinished effect.
        """
        ...


def validate_commit(*, context: RequestContext, record: Record, expected_revision: int,
                    event: EventEnvelope, mutation: MutationIdentity,
                    previous: Record | None) -> None:
    """Shared shape/precondition guard, not a replacement for DB transaction/ACL.

    Invoke after idempotency replay lookup and within the future transaction,
    using the previous record loaded and locked by the repository.
    """
    validate_record_scope(context, record)
    require_revision(expected_revision, zero=True)
    if not isinstance(event, EventEnvelope) or not isinstance(mutation, MutationIdentity):
        raise ContractError("event_and_mutation_required")
    require_same_scope(context.scope, event.scope)
    require_same_scope(context.scope, mutation.scope)
    header = record.header
    if header.revision != expected_revision + 1:
        raise ContractError("revision_conflict")
    if event.subject != record.ref() or event.actor != context.actor:
        raise ContractError("event_subject_or_actor_mismatch")
    if (event.correlation_id != header.correlation_id or event.policy != header.policy
            or event.causation_id != header.causation_id or event.time != header.updated_at):
        raise ContractError("event_provenance_mismatch")
    if not event.event_type.startswith(f"stratforge.ai.{record.KIND.value}."):
        raise ContractError("event_kind_mismatch")
    if event.event_type in EVENT_STATES and record.status not in EVENT_STATES[event.event_type]:
        raise ContractError("event_state_mismatch")
    if previous is None:
        if expected_revision != 0 or header.created_by != context.actor:
            raise ContractError("creation_conflict")
        if header.owner_user_uuid != context.user_uuid:
            raise ContractError("creation_owner_mismatch")
        if record.status != INITIAL_STATES[record.KIND]:
            raise ContractError("initial_state_required")
    else:
        validate_record_scope(context, previous)
        if (previous.KIND != record.KIND or previous.header.entity_id != header.entity_id
                or previous.header.revision != expected_revision):
            raise ContractError("revision_conflict")
        old = previous.header
        if (header.created_at != old.created_at or header.created_by != old.created_by
                or header.owner_user_uuid != old.owner_user_uuid
                or header.correlation_id != old.correlation_id
                or header.updated_at < old.updated_at):
            raise ContractError("immutable_identity_changed")
        if previous.status == record.status:
            if record.status not in EDITABLE_STATES[record.KIND]:
                raise ContractError("finalized_record_immutable")
        else:
            validate_transition(record.KIND, previous.status, record.status)
        if previous.status not in EDITABLE_STATES[record.KIND]:
            payload_changed = any(
                getattr(previous, field.name) != getattr(record, field.name)
                for field in fields(record) if field.name not in {"header", "status"})
            if header.policy != old.policy or payload_changed:
                raise ContractError("finalized_payload_immutable")
    if mutation.request_hash != request_digest(context=context, record=record,
                                              expected_revision=expected_revision, event=event):
        raise ContractError("mutation_payload_mismatch")
