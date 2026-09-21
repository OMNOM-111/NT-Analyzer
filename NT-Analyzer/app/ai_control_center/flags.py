"""One immutable, server-side flag registry; no browser mutation endpoint.

A deployment gate AND an exact workspace opt-in are required. Configuration
must come from trusted server composition, with an existing audit reference.
The Local composition records its exact opt-ins before publishing a snapshot.
Flags never authorize actions.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from uuid import UUID

from .contracts import Environment, TenantScope, require_enum, require_token, require_tuple, require_uuid
from .states import ContractError


class Flag(str, Enum):
    AI_EXTERNAL_AGENT_V1 = "AI_EXTERNAL_AGENT_V1"
    AI_EXTERNAL_AGENT_TEST_V1 = "AI_EXTERNAL_AGENT_TEST_V1"
    AI_COMMAND_CENTER_UI = "AI_COMMAND_CENTER_UI"
    AI_CONTROL_CENTER_READ_MODEL = "AI_CONTROL_CENTER_READ_MODEL"
    AI_TASK_GRAPH_V2 = "AI_TASK_GRAPH_V2"
    AI_ROUTER_SHADOW_V2 = "AI_ROUTER_SHADOW_V2"
    AI_ROUTER_V2 = "AI_ROUTER_V2"
    AI_DELEGATION_V2 = "AI_DELEGATION_V2"
    AI_SCHEDULER_V1 = "AI_SCHEDULER_V1"
    AI_EVALUATION_SHADOW = "AI_EVALUATION_SHADOW"
    AI_CONSENSUS_V2 = "AI_CONSENSUS_V2"
    AI_COURT_V1 = "AI_COURT_V1"
    AI_EXECUTION_V2 = "AI_EXECUTION_V2"
    AI_MEMORY_V2 = "AI_MEMORY_V2"
    AI_MEMORY_UNIFIED_READ = "AI_MEMORY_UNIFIED_READ"
    AI_MEMORY_EXTERNAL_CONTEXT = "AI_MEMORY_EXTERNAL_CONTEXT"
    AI_MEMORY_CANONICAL_WRITE = "AI_MEMORY_CANONICAL_WRITE"
    AI_MEMORY_LEGACY_ARCHIVE_ONLY = "AI_MEMORY_LEGACY_ARCHIVE_ONLY"
    AI_SOCIAL_PUBLISH_V1 = "AI_SOCIAL_PUBLISH_V1"


@dataclass(frozen=True)
class FlagDefinition:
    flag: Flag
    dependencies: tuple[Flag, ...] = ()
    default: bool = False


REGISTRY = MappingProxyType({
    flag: FlagDefinition(flag, dependencies) for flag, dependencies in (
        (Flag.AI_EXTERNAL_AGENT_V1, (Flag.AI_TASK_GRAPH_V2,)),
        (Flag.AI_EXTERNAL_AGENT_TEST_V1, (Flag.AI_EXTERNAL_AGENT_V1,)),
        (Flag.AI_CONTROL_CENTER_READ_MODEL, ()),
        (Flag.AI_COMMAND_CENTER_UI, (Flag.AI_CONTROL_CENTER_READ_MODEL,)),
        (Flag.AI_TASK_GRAPH_V2, (Flag.AI_CONTROL_CENTER_READ_MODEL,)),
        (Flag.AI_ROUTER_SHADOW_V2, (Flag.AI_TASK_GRAPH_V2,)),
        (Flag.AI_ROUTER_V2, (Flag.AI_TASK_GRAPH_V2,)),
        (Flag.AI_DELEGATION_V2, (Flag.AI_EXECUTION_V2,)),
        (Flag.AI_SCHEDULER_V1, (Flag.AI_EXECUTION_V2,)),
        (Flag.AI_EVALUATION_SHADOW, (Flag.AI_TASK_GRAPH_V2,)),
        (Flag.AI_CONSENSUS_V2, (Flag.AI_TASK_GRAPH_V2,)),
        (Flag.AI_COURT_V1, (Flag.AI_CONSENSUS_V2,)),
        (Flag.AI_EXECUTION_V2, (Flag.AI_TASK_GRAPH_V2,)),
        (Flag.AI_MEMORY_V2, (Flag.AI_TASK_GRAPH_V2,)),
        (Flag.AI_MEMORY_UNIFIED_READ, (Flag.AI_MEMORY_V2,)),
        (Flag.AI_MEMORY_EXTERNAL_CONTEXT, (Flag.AI_MEMORY_UNIFIED_READ,)),
        (Flag.AI_MEMORY_CANONICAL_WRITE, (Flag.AI_MEMORY_UNIFIED_READ,)),
        (Flag.AI_MEMORY_LEGACY_ARCHIVE_ONLY, (Flag.AI_MEMORY_CANONICAL_WRITE,)),
        (Flag.AI_SOCIAL_PUBLISH_V1, (Flag.AI_EVALUATION_SHADOW,)),
    )
})


@dataclass(frozen=True, kw_only=True)
class FlagRule:
    environment: Environment
    flag: Flag
    enabled: bool
    workspace_id: str | None = None

    def __post_init__(self) -> None:
        require_enum(self.environment, Environment)
        require_enum(self.flag, Flag)
        if type(self.enabled) is not bool:
            raise ContractError("flag_boolean_required")
        if self.workspace_id is not None:
            TenantScope(environment=self.environment, workspace_id=self.workspace_id)


@dataclass(frozen=True, kw_only=True)
class FlagSnapshot:
    revision: str = "disabled-v1"
    rules: tuple[FlagRule, ...] = ()
    audit_ref: UUID | None = None

    def __post_init__(self) -> None:
        require_token(self.revision)
        require_tuple(self.rules, FlagRule)
        if self.rules and self.audit_ref is None:
            raise ContractError("flag_audit_reference_required")
        if self.audit_ref is not None:
            require_uuid(self.audit_ref)
        keys = [(rule.environment, rule.workspace_id, rule.flag) for rule in self.rules]
        if len(keys) != len(set(keys)):
            raise ContractError("duplicate_flag_rule")


DISABLED = FlagSnapshot()


@dataclass(frozen=True, kw_only=True)
class FlagDecision:
    flag: Flag
    enabled: bool
    reason: str
    revision: str
    blocked_by: Flag | None = None


def resolve(flag: Flag, *, scope: TenantScope,
            snapshot: FlagSnapshot = DISABLED) -> FlagDecision:
    require_enum(flag, Flag)
    if not isinstance(scope, TenantScope) or not isinstance(snapshot, FlagSnapshot):
        raise ContractError("flag_scope_and_snapshot_required")
    rules = {(row.environment, row.workspace_id, row.flag): row.enabled
             for row in snapshot.rules}

    def decision(current: Flag, visiting: frozenset[Flag]) -> FlagDecision:
        reason, blocked_by = "enabled", None
        if current in visiting:
            raise ContractError("flag_dependency_cycle")
        if not rules.get((scope.environment, None, current), False):
            reason = "environment_disabled"
        elif not rules.get((scope.environment, scope.workspace_id, current), False):
            reason = "workspace_disabled"
        else:
            for dependency in REGISTRY[current].dependencies:
                result = decision(dependency, visiting | {current})
                if not result.enabled:
                    reason, blocked_by = "dependency_disabled", dependency
                    break
        return FlagDecision(flag=current, enabled=reason == "enabled", reason=reason,
                            revision=snapshot.revision, blocked_by=blocked_by)

    return decision(flag, frozenset())


def current_snapshot(authorized):
    """The snapshot to resolve against, re-read when authority can be refreshed.

    A snapshot captured when the request was admitted is not a standing grant:
    revoking a mechanism must take effect for work already in flight. execution_v2
    already re-reads authority this way; delegation, the scheduler and the router
    resolve through here so all four behave the same.
    """
    from .states import ContractError
    refresh = authorized.get("refresh") if isinstance(authorized, dict) else None
    if not callable(refresh):
        return authorized.get("snapshot", DISABLED) if isinstance(authorized, dict) else DISABLED
    current = refresh()
    if not isinstance(current, dict) or current.get("context") != authorized.get("context"):
        raise ContractError("mechanism_authority_denied")
    return current.get("snapshot", DISABLED)
