"""Pure, allowlisted legacy projections. Never discover or write legacy data.

The caller supplies an already-authorized row and a trusted source binding.
Global/unscoped legacy records cannot be relabeled from a browser request.
Projections preserve origin/status and do not become a new authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping
from uuid import UUID, uuid5

from .contracts import (SnapshotRef, TenantScope, require_same_scope, require_text,
                        require_token, require_uuid)
from .states import ContractError


class Phase(str, Enum):
    PLANNED = "planned"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    REVIEW = "review"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"
    UNKNOWN = "unknown"


def _mapping(**phases: tuple[str, ...]):
    return MappingProxyType({legacy: Phase(phase) for phase, rows in phases.items()
                             for legacy in rows})


STATUS_MAP = MappingProxyType({
    "local_worker": _mapping(ready=("queued",), running=("running",), succeeded=("succeeded",),
                             failed=("failed",), cancelled=("cancelled",), review=("stale",)),
    "postgres_job": _mapping(ready=("queued",), running=("running",), succeeded=("completed",),
                             failed=("failed",), cancelled=("cancelled",), review=("dead_letter", "review")),
    "command": _mapping(ready=("queued",), running=("leased",), succeeded=("completed",),
                        failed=("failed", "rejected", "expired"), cancelled=("cancelled",), review=("review",)),
    "mission": _mapping(planned=("idle",), running=("active", "finishing"), blocked=("paused", "deadline_reached"),
                        succeeded=("completed",), cancelled=("stopped",), archived=("archived",)),
    "conversation_work": _mapping(planned=("open",), running=("in_progress",),
                                  blocked=("blocked",), review=("awaiting_owner",),
                                  succeeded=("completed",)),
    "experiment": _mapping(
        planned=("draft",), ready=("draft_ready",), running=("designing", "generating", "backtesting"),
        waiting=("awaiting_compile",),
        review=("generated", "catalog_visible", "backtest_done", "analysis_ready", "mutation_candidate",
                "sandbox_candidate", "champion_candidate", "human_review_candidate", "portfolio_contributor"),
        failed=("validation_failed", "compile_failed", "compile_failed_after_fix_loop", "backtest_failed",
                "pipeline_failed", "rejected"),
        blocked=("awaiting_compile_timeout", "blocked_by_real_environment_issue", "blocked_lm_studio"),
        cancelled=("cancelled",), archived=("archived",)),
})


@dataclass(frozen=True, kw_only=True)
class StatusProjection:
    source: str
    legacy_status: str
    phase: Phase
    review_required: bool


def project_status(source: str, legacy_status: str) -> StatusProjection:
    require_token(source, limit=80)
    require_token(legacy_status, limit=100)
    phase = STATUS_MAP.get(source, {}).get(legacy_status, Phase.UNKNOWN)
    return StatusProjection(source=source, legacy_status=legacy_status, phase=phase,
                            review_required=phase in {Phase.UNKNOWN, Phase.REVIEW})


# Fixed namespace, not an identity or a grant. Never change once records exist.
_NAMESPACE = UUID("de8ea13f-6a31-4918-a277-2e4239c89e51")


def legacy_uuid(scope: TenantScope, namespace: str, source_id: str) -> UUID:
    require_same_scope(scope, scope)
    require_token(namespace, limit=80)
    require_token(source_id)
    # Length-delimited fields avoid collisions from source IDs containing ':' .
    parts = (scope.environment.value, scope.workspace_id, namespace, source_id)
    return uuid5(_NAMESPACE, "".join(f"{len(part)}:{part}" for part in parts))


@dataclass(frozen=True, kw_only=True)
class LegacyBinding:
    """Verified binding input, supplied by a future server-side source adapter.

    Binding evidence records source ownership and environment. Its authenticity
    must be checked at service admission; a DTO cannot prove source authority.
    """

    scope: TenantScope
    owner_user_uuid: UUID
    source: str
    source_id: str
    evidence: SnapshotRef

    def __post_init__(self) -> None:
        require_same_scope(self.scope, self.scope)
        require_uuid(self.owner_user_uuid)
        require_token(self.source, limit=80)
        require_token(self.source_id)
        if not isinstance(self.evidence, SnapshotRef):
            raise ContractError("binding_evidence_required")
        require_same_scope(self.scope, self.evidence.scope)


def _bound(row: Mapping, binding: LegacyBinding, source: str, *, id_field: str = "id") -> None:
    if not isinstance(row, Mapping) or not isinstance(binding, LegacyBinding):
        raise ContractError("legacy_binding_required")
    if binding.source != source or row.get(id_field) != binding.source_id:
        raise ContractError("legacy_source_mismatch")
    # Explicit contradictory scope is never overridden by a binding. Missing
    # fields are allowed only because the caller supplied binding evidence.
    expected = {"workspace_id": binding.scope.workspace_id,
                "environment": binding.scope.environment.value,
                "user_uuid": str(binding.owner_user_uuid),
                "owner_user_uuid": str(binding.owner_user_uuid)}
    for key, value in expected.items():
        if key in row and row[key] != value:
            raise ContractError("legacy_scope_mismatch")


@dataclass(frozen=True, kw_only=True)
class ProviderModelProjection:
    scope: TenantScope
    source_id: str
    provider_account_id: UUID
    model_id: UUID
    provider_key: str
    model_key: str
    enabled: bool
    endpoint_type: str


def project_provider_model(row: Mapping, *, binding: LegacyBinding) -> ProviderModelProjection:
    _bound(row, binding, "agent_registry")
    provider, model = row.get("provider"), row.get("model")
    require_token(provider, limit=80)
    require_text(model)
    enabled = row.get("enabled")
    endpoint_type = row.get("endpoint_type")
    if type(enabled) is not bool or endpoint_type not in {"chat", "embeddings"}:
        raise ContractError("invalid_legacy_provider")
    # No keys, masks, endpoints, budgets, usage, prompts or free-form metadata.
    return ProviderModelProjection(
        scope=binding.scope, source_id=binding.source_id,
        provider_account_id=legacy_uuid(binding.scope, "provider_account", binding.source_id),
        model_id=uuid5(_NAMESPACE, str(legacy_uuid(binding.scope, "provider", provider)) + ":" + model),
        provider_key=provider, model_key=model, enabled=enabled, endpoint_type=endpoint_type)


@dataclass(frozen=True, kw_only=True)
class PersonaRoleProjection:
    scope: TenantScope
    source_id: str
    persona_id: UUID
    role_id: UUID
    display_name: str
    role_key: str
    legacy_management_level: int | None


def project_persona_role(row: Mapping, *, binding: LegacyBinding) -> PersonaRoleProjection:
    _bound(row, binding, "domain_agents")
    name, role = row.get("name"), row.get("role")
    require_text(name)
    require_token(role)
    level = row.get("level")
    if level is not None and (type(level) is not int or not 1 <= level <= 4):
        raise ContractError("invalid_legacy_management_level")
    return PersonaRoleProjection(
        scope=binding.scope, source_id=binding.source_id,
        persona_id=legacy_uuid(binding.scope, "persona", binding.source_id),
        role_id=legacy_uuid(binding.scope, "agent_role", role), display_name=name, role_key=role,
        legacy_management_level=level)


@dataclass(frozen=True, kw_only=True)
class WorkProjection:
    scope: TenantScope
    owner_user_uuid: UUID
    entity_id: UUID
    source_id: str
    status: StatusProjection
    binding_evidence: SnapshotRef


_WORK_IDS = MappingProxyType({
    "experiment": "experiment_id", "mission": "mission_id",
    "local_worker": "worker_job_id", "postgres_job": "job_id",
    "command": "command_id", "conversation_work": "conversation_id",
})


def project_work(row: Mapping, *, binding: LegacyBinding) -> WorkProjection:
    if not isinstance(binding, LegacyBinding) or binding.source not in _WORK_IDS:
        raise ContractError("unsupported_work_source")
    _bound(row, binding, binding.source, id_field=_WORK_IDS[binding.source])
    status_key = "work_state" if binding.source == "conversation_work" else "status"
    status = project_status(binding.source, row.get(status_key))
    return WorkProjection(scope=binding.scope, owner_user_uuid=binding.owner_user_uuid,
                          entity_id=legacy_uuid(binding.scope, binding.source, binding.source_id),
                          source_id=binding.source_id, status=status, binding_evidence=binding.evidence)
