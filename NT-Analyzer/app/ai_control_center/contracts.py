"""Immutable stage-1 DTOs. Authentication/authorization belongs to services.

Constructors reject malformed scope, mutable collections and cross-tenant
references. They do not read files, discover credentials or grant permissions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import ClassVar
from uuid import UUID

from .states import ContractError, EntityKind, validate_state


class Environment(str, Enum):
    DEVELOPMENT = "development"
    CANARY = "canary"
    PRODUCTION = "production"


class ActorKind(str, Enum):
    HUMAN = "human"
    AGENT = "agent"
    SERVICE = "service"


class Risk(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class Autonomy(str, Enum):
    ADVICE = "advice"
    DRAFT = "draft"
    REVERSIBLE_EXECUTION = "reversible_execution"
    APPROVAL_REQUIRED = "approval_required"
    FORBIDDEN = "forbidden"


class MemoryClass(str, Enum):
    PRIVATE = "private"
    WORKSPACE = "workspace"
    TASK = "task"
    VERIFIED_LESSON = "verified_lesson"
    WORKING = "working"


class Visibility(str, Enum):
    PRIVATE = "private"
    WORKSPACE = "workspace"


class Sensitivity(str, Enum):
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


def require_uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ContractError("invalid_uuid")


def require_utc(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ContractError("utc_required")


def require_token(value: str, *, limit: int = 160) -> None:
    if (not isinstance(value, str) or not 1 <= len(value) <= limit
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value)):
        raise ContractError("invalid_token")


def require_text(value: str, *, limit: int = 160) -> None:
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value)):
        raise ContractError("invalid_text")


def require_revision(value: int, *, zero: bool = False) -> None:
    if type(value) is not int or value < (0 if zero else 1):
        raise ContractError("invalid_revision")


def require_tuple(value: tuple, element_type: type | tuple[type, ...]) -> None:
    if type(value) is not tuple or not all(isinstance(v, element_type) for v in value):
        raise ContractError("immutable_tuple_required")


def require_enum(value: Enum, enum_type: type[Enum]) -> None:
    if not isinstance(value, enum_type):
        raise ContractError("invalid_enum")


@dataclass(frozen=True, kw_only=True)
class TenantScope:
    environment: Environment
    workspace_id: str

    def __post_init__(self) -> None:
        require_enum(self.environment, Environment)
        if (not isinstance(self.workspace_id, str)
                or not re.fullmatch(r"ws_[A-Za-z0-9_-]{8,80}", self.workspace_id)):
            raise ContractError("invalid_workspace")


def require_same_scope(expected: TenantScope, actual: TenantScope) -> None:
    if not isinstance(expected, TenantScope) or not isinstance(actual, TenantScope):
        raise ContractError("scope_required")
    if expected != actual:
        raise ContractError("scope_mismatch")


@dataclass(frozen=True, kw_only=True)
class ActorRef:
    kind: ActorKind
    actor_id: UUID
    on_behalf_of: UUID | None = None

    def __post_init__(self) -> None:
        require_enum(self.kind, ActorKind)
        require_uuid(self.actor_id)
        if self.on_behalf_of is not None:
            require_uuid(self.on_behalf_of)
        if self.kind == ActorKind.HUMAN and self.on_behalf_of is not None:
            raise ContractError("human_delegation_not_supported")


@dataclass(frozen=True, kw_only=True)
class RequestContext:
    """Shape of already-authenticated context; never construct from a body."""

    scope: TenantScope
    user_uuid: UUID
    actor: ActorRef

    def __post_init__(self) -> None:
        require_same_scope(self.scope, self.scope)
        require_uuid(self.user_uuid)
        if not isinstance(self.actor, ActorRef):
            raise ContractError("actor_required")
        principal = (self.actor.actor_id if self.actor.kind == ActorKind.HUMAN
                     else self.actor.on_behalf_of)
        if principal != self.user_uuid:
            raise ContractError("actor_user_mismatch")


@dataclass(frozen=True, kw_only=True)
class EntityRef:
    kind: EntityKind
    entity_id: UUID
    revision: int
    scope: TenantScope

    def __post_init__(self) -> None:
        require_enum(self.kind, EntityKind)
        require_uuid(self.entity_id)
        require_revision(self.revision)
        require_same_scope(self.scope, self.scope)


@dataclass(frozen=True, kw_only=True)
class SnapshotRef:
    """Immutable content reference; the repository verifies actual bytes/ACL."""

    artifact_id: UUID
    sha256: str
    scope: TenantScope

    def __post_init__(self) -> None:
        require_uuid(self.artifact_id)
        require_same_scope(self.scope, self.scope)
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ContractError("invalid_sha256")


class ExternalAuthority(str, Enum):
    BUDGET = "budget"
    COMMAND = "command"
    CREDENTIAL = "credential"


@dataclass(frozen=True, kw_only=True)
class ExternalRef:
    """Opaque lookup key, never a secret, URL, file path or a grant."""

    authority: ExternalAuthority
    key: str
    scope: TenantScope

    def __post_init__(self) -> None:
        require_enum(self.authority, ExternalAuthority)
        require_token(self.key)
        require_same_scope(self.scope, self.scope)


@dataclass(frozen=True, kw_only=True)
class RecordHeader:
    entity_id: UUID
    scope: TenantScope
    owner_user_uuid: UUID
    revision: int
    created_at: datetime
    updated_at: datetime
    created_by: ActorRef
    correlation_id: UUID
    policy: SnapshotRef
    causation_id: UUID | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        for value in (self.entity_id, self.owner_user_uuid, self.correlation_id):
            require_uuid(value)
        if self.causation_id is not None:
            require_uuid(self.causation_id)
        require_revision(self.revision)
        require_utc(self.created_at)
        require_utc(self.updated_at)
        if self.updated_at < self.created_at:
            raise ContractError("timestamp_order")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ContractError("unsupported_schema")
        if not isinstance(self.created_by, ActorRef) or not isinstance(self.policy, SnapshotRef):
            raise ContractError("provenance_required")
        require_same_scope(self.scope, self.policy.scope)


def _validate_reference_tree(scope: TenantScope, value: object) -> None:
    if isinstance(value, (EntityRef, SnapshotRef, ExternalRef)):
        require_same_scope(scope, value.scope)
    elif isinstance(value, tuple):
        for item in value:
            _validate_reference_tree(scope, item)
    elif isinstance(value, (dict, list, set)):
        raise ContractError("mutable_payload")


def require_entity(value: EntityRef, kind: EntityKind) -> None:
    if not isinstance(value, EntityRef) or value.kind != kind:
        raise ContractError("reference_kind_mismatch")


def require_external(value: ExternalRef, authority: ExternalAuthority) -> None:
    if not isinstance(value, ExternalRef) or value.authority != authority:
        raise ContractError("external_authority_mismatch")


def require_snapshot(value: SnapshotRef) -> None:
    if not isinstance(value, SnapshotRef):
        raise ContractError("snapshot_required")


@dataclass(frozen=True, kw_only=True)
class Record:
    header: RecordHeader
    status: str
    KIND: ClassVar[EntityKind]

    def __post_init__(self) -> None:
        if not isinstance(self.header, RecordHeader):
            raise ContractError("header_required")
        validate_state(self.KIND, self.status)
        for field in fields(self):
            _validate_reference_tree(self.header.scope, getattr(self, field.name))

    def ref(self) -> EntityRef:
        return EntityRef(kind=self.KIND, entity_id=self.header.entity_id,
                         revision=self.header.revision, scope=self.header.scope)


@dataclass(frozen=True, kw_only=True)
class Persona(Record):
    KIND: ClassVar = EntityKind.PERSONA
    display_name: str
    profile: SnapshotRef

    def __post_init__(self) -> None:
        super().__post_init__()
        require_text(self.display_name)
        require_snapshot(self.profile)


@dataclass(frozen=True, kw_only=True)
class AgentRole(Record):
    KIND: ClassVar = EntityKind.AGENT_ROLE
    role_key: str
    responsibilities: SnapshotRef
    capability_ceiling: tuple[str, ...]
    autonomy_ceiling: Autonomy

    def __post_init__(self) -> None:
        super().__post_init__()
        require_token(self.role_key)
        require_snapshot(self.responsibilities)
        require_tuple(self.capability_ceiling, str)
        for capability in self.capability_ceiling:
            require_token(capability)
        require_enum(self.autonomy_ceiling, Autonomy)


@dataclass(frozen=True, kw_only=True)
class ProviderAccount(Record):
    KIND: ClassVar = EntityKind.PROVIDER_ACCOUNT
    provider_key: str
    credential: ExternalRef

    def __post_init__(self) -> None:
        super().__post_init__()
        require_token(self.provider_key, limit=80)
        require_external(self.credential, ExternalAuthority.CREDENTIAL)


@dataclass(frozen=True, kw_only=True)
class Model(Record):
    KIND: ClassVar = EntityKind.MODEL
    provider_key: str
    model_key: str
    profile: SnapshotRef
    modalities: tuple[str, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        require_token(self.provider_key, limit=80)
        require_text(self.model_key)
        require_snapshot(self.profile)
        require_tuple(self.modalities, str)
        if not self.modalities or not set(self.modalities) <= {"text", "image", "audio", "embedding"}:
            raise ContractError("invalid_modalities")


@dataclass(frozen=True, kw_only=True)
class Intent(Record):
    KIND: ClassVar = EntityKind.INTENT
    goal: SnapshotRef
    acceptance: SnapshotRef
    risk: Risk
    autonomy: Autonomy
    budget: ExternalRef
    deadline: datetime

    def __post_init__(self) -> None:
        super().__post_init__()
        require_snapshot(self.goal)
        require_snapshot(self.acceptance)
        require_enum(self.risk, Risk)
        require_enum(self.autonomy, Autonomy)
        require_external(self.budget, ExternalAuthority.BUDGET)
        require_utc(self.deadline)
        if self.deadline <= self.header.created_at:
            raise ContractError("invalid_deadline")


@dataclass(frozen=True, kw_only=True)
class Task(Record):
    KIND: ClassVar = EntityKind.TASK
    intent: EntityRef
    role: EntityRef
    dependencies: tuple[EntityRef, ...] = ()
    checkpoint: SnapshotRef | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        require_entity(self.intent, EntityKind.INTENT)
        require_entity(self.role, EntityKind.AGENT_ROLE)
        require_tuple(self.dependencies, EntityRef)
        seen = set()
        for dependency in self.dependencies:
            require_entity(dependency, EntityKind.TASK)
            if dependency.entity_id == self.header.entity_id or dependency.entity_id in seen:
                raise ContractError("invalid_dependency")
            seen.add(dependency.entity_id)
        if self.checkpoint is not None:
            require_snapshot(self.checkpoint)


@dataclass(frozen=True, kw_only=True)
class Contribution(Record):
    KIND: ClassVar = EntityKind.CONTRIBUTION
    task: EntityRef
    role: EntityRef
    result: SnapshotRef
    evidence: tuple[SnapshotRef, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        require_entity(self.task, EntityKind.TASK)
        require_entity(self.role, EntityKind.AGENT_ROLE)
        require_snapshot(self.result)
        require_tuple(self.evidence, SnapshotRef)
        if self.status == "accepted" and not self.evidence:
            raise ContractError("evidence_required")


@dataclass(frozen=True, kw_only=True)
class Decision(Record):
    KIND: ClassVar = EntityKind.DECISION
    intent: EntityRef
    contributions: tuple[EntityRef, ...]
    evidence_packet: SnapshotRef
    approval: SnapshotRef | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        require_entity(self.intent, EntityKind.INTENT)
        require_tuple(self.contributions, EntityRef)
        for contribution in self.contributions:
            require_entity(contribution, EntityKind.CONTRIBUTION)
        require_snapshot(self.evidence_packet)
        if self.approval is not None:
            require_snapshot(self.approval)
        if self.status == "approved" and self.approval is None:
            raise ContractError("approval_required")


@dataclass(frozen=True, kw_only=True)
class Execution(Record):
    KIND: ClassVar = EntityKind.EXECUTION
    decision: EntityRef
    approval: SnapshotRef
    command: ExternalRef
    receipt: SnapshotRef | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        require_entity(self.decision, EntityKind.DECISION)
        require_snapshot(self.approval)
        require_external(self.command, ExternalAuthority.COMMAND)
        if self.receipt is not None:
            require_snapshot(self.receipt)
        if self.status == "succeeded" and self.receipt is None:
            raise ContractError("receipt_required")


@dataclass(frozen=True, kw_only=True)
class Outcome(Record):
    KIND: ClassVar = EntityKind.OUTCOME
    task: EntityRef
    evidence: tuple[SnapshotRef, ...]
    verification: SnapshotRef | None = None
    execution: EntityRef | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        require_entity(self.task, EntityKind.TASK)
        require_tuple(self.evidence, SnapshotRef)
        if self.execution is not None:
            require_entity(self.execution, EntityKind.EXECUTION)
        if self.verification is not None:
            require_snapshot(self.verification)
        if self.status == "verified" and (not self.evidence or self.verification is None):
            raise ContractError("verification_required")


@dataclass(frozen=True, kw_only=True)
class Memory(Record):
    KIND: ClassVar = EntityKind.MEMORY
    memory_class: MemoryClass
    visibility: Visibility
    sensitivity: Sensitivity
    content: SnapshotRef
    provenance: tuple[SnapshotRef, ...]
    retention_until: datetime
    verification: SnapshotRef | None = None
    task: EntityRef | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        require_enum(self.memory_class, MemoryClass)
        require_enum(self.visibility, Visibility)
        require_enum(self.sensitivity, Sensitivity)
        require_snapshot(self.content)
        require_tuple(self.provenance, SnapshotRef)
        require_utc(self.retention_until)
        if not self.provenance or self.retention_until <= self.header.created_at:
            raise ContractError("memory_provenance_or_retention_required")
        if self.memory_class == MemoryClass.PRIVATE and self.visibility != Visibility.PRIVATE:
            raise ContractError("private_memory_visibility")
        if self.verification is not None:
            require_snapshot(self.verification)
        if self.task is not None:
            require_entity(self.task, EntityKind.TASK)
        if self.memory_class == MemoryClass.TASK and self.task is None:
            raise ContractError("memory_task_required")
        if self.memory_class == MemoryClass.VERIFIED_LESSON and self.verification is None:
            raise ContractError("verification_required")


def validate_record_scope(context: RequestContext, record: Record) -> None:
    """Structural boundary only; membership/capabilities must still be checked."""
    if not isinstance(context, RequestContext) or not isinstance(record, Record):
        raise ContractError("context_and_record_required")
    require_same_scope(context.scope, record.header.scope)
    if (record.KIND == EntityKind.EXTERNAL_AGENT_CONNECTION
            and context.user_uuid != record.header.owner_user_uuid):
        raise ContractError("external_agent_owner_denied")
    if (isinstance(record, Memory) and record.visibility == Visibility.PRIVATE
            and context.user_uuid != record.header.owner_user_uuid):
        raise ContractError("private_memory_denied")


def primitive(value: object) -> object:
    """Internal deterministic representation; not a public API serializer."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        require_utc(value)
        return value.isoformat().replace("+00:00", "Z")
    if is_dataclass(value) and not isinstance(value, type):
        result = {field.name: primitive(getattr(value, field.name)) for field in fields(value)}
        if isinstance(value, Record):
            result["kind"] = value.KIND.value
        return result
    if isinstance(value, tuple):
        return [primitive(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    raise ContractError("unsupported_payload_type")
