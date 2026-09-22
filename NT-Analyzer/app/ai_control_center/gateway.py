"""Owner-review composition, not a second auth, permission or job system.

Only the existing isolated Preview child can activate this slice. Every request
also needs its owner-issued control cookie and a real, confirmed synthetic user
session. An ordinary Local owner, ordinary Preview session, Canary or Production
cannot activate it. No process-wide Local runtime setting is changed.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from uuid import UUID

from .. import account_auth, ai_budgets, audit_events, permissions, preview_sandbox, runtime_env, subscriptions, workspaces
from .contracts import ActorKind, ActorRef, Environment, ExternalAuthority, ExternalRef, RequestContext, TenantScope
from .flags import Flag, FlagRule, FlagSnapshot, REGISTRY, resolve
from .states import ContractError


PREFIX = "/api/ai-control-center/"
_LOCK = threading.RLock()
_SNAPSHOTS: dict[tuple, FlagSnapshot] = {}
_PREVIEW_FLAGS = (
    Flag.AI_CONTROL_CENTER_READ_MODEL, Flag.AI_COMMAND_CENTER_UI,
    Flag.AI_TASK_GRAPH_V2, Flag.AI_EVALUATION_SHADOW,
)
LIMITATIONS = [
    "Локальный проверочный контур: фиксированные synthetic-наборы, без вызова внешних моделей и без торговых команд.",
    "Оценки относятся только к локальным проверкам. Это не рейтинг качества LLM и не доказательство торговой доходности.",
    "В Preview доступны ручные синтетические персоны, память, проекты и предложения; Router, Court, исполнение и автопубликация выключены.",
    "Этот Preview использует отдельный SQLite, без workers. Его проверки не являются доказательством PostgreSQL/RLS или готовности Canary/Production.",
]


def request_context(raw: dict, *, control_authorized: bool) -> RequestContext:
    """Accept authenticated server context only; never a browser body/query."""
    if (not runtime_env.is_development() or not control_authorized
            or not preview_sandbox.synthetic_identity_allowed(raw)):
        raise ContractError("agent_world_preview_required")
    preview_sandbox.require_enabled()  # validates the isolated root too
    if raw.get("device_confirmation_state") != "active":
        raise ContractError("agent_world_confirmed_device_required")
    if str(raw.get("role") or "read_only") == "read_only":
        raise ContractError("agent_world_write_role_required")
    membership = raw.get("active_membership") or {}
    workspace_id = str(raw.get("workspace_id") or "")
    if (not workspace_id or membership.get("workspace_id") != workspace_id
            or str(membership.get("role") or "") not in workspaces.WRITE_ROLES):
        raise ContractError("agent_world_membership_required")
    if not (raw.get("capabilities") or {}).get("ai_lab") or raw.get("ux_mode") != "professional":
        raise ContractError("agent_world_capability_required")
    try:
        user_uuid = UUID(str(raw.get("user_uuid") or (raw.get("user") or {}).get("user_uuid") or ""))
    except (TypeError, ValueError):
        raise ContractError("agent_world_identity_required") from None
    return RequestContext(
        scope=TenantScope(environment=Environment.DEVELOPMENT, workspace_id=workspace_id),
        user_uuid=user_uuid, actor=ActorRef(kind=ActorKind.HUMAN, actor_id=user_uuid),
    )


def flag_snapshot(context: RequestContext) -> FlagSnapshot:
    """Trusted composition: fixed development flags AND exact workspace opt-in.

    The existing audit authority records activation. Its Development log is
    process-local, so restart re-audits rather than implying durable PG evidence.
    Capability/control/session checks remain mandatory independently of flags.
    """
    key = (str(preview_sandbox.isolated_root()), context.scope, context.user_uuid)
    with _LOCK:
        if key not in _SNAPSHOTS:
            audit_id = audit_events.record(
                str(context.user_uuid), "agent_world.preview_flags_activated", "agent_world",
                workspace_id=context.scope.workspace_id, resource_id="owner-review-v1",
                details={"flags": [flag.value for flag in _PREVIEW_FLAGS], "synthetic": True},
            )
            snapshot = FlagSnapshot(
                revision="owner-review-v1", audit_ref=UUID(audit_id.removeprefix("aud_")),
                rules=tuple(FlagRule(environment=Environment.DEVELOPMENT, flag=flag, enabled=True,
                                     workspace_id=workspace)
                            for flag in _PREVIEW_FLAGS for workspace in (None, context.scope.workspace_id)),
            )
            if len(_SNAPSHOTS) >= 256:
                _SNAPSHOTS.clear()
            _SNAPSHOTS[key] = snapshot
        return _SNAPSHOTS[key]


def navigation(raw: dict, *, control_authorized: bool) -> dict:
    try:
        context = request_context(raw, control_authorized=control_authorized)
        enabled = resolve(Flag.AI_COMMAND_CENTER_UI, scope=context.scope,
                          snapshot=flag_snapshot(context)).enabled
    except (ContractError, preview_sandbox.PreviewSandboxError):
        enabled = False
    return {"enabled": enabled, "status": "IN DEVELOPMENT", "synthetic": enabled,
            "url": "/ui/ai-command-center.html"}


def service_for(raw: dict, *, control_authorized: bool):
    context = request_context(raw, control_authorized=control_authorized)
    snapshot = flag_snapshot(context)
    if not resolve(Flag.AI_CONTROL_CENTER_READ_MODEL, scope=context.scope, snapshot=snapshot).enabled:
        raise ContractError("agent_world_disabled")
    # Lazy imports: ordinary Local/Canary/Production do not open this database.
    from .sqlite_repository import SQLiteAgentWorldRepository
    from .demo_workflows import DemoWorkflowService
    repository = SQLiteAgentWorldRepository(preview_sandbox.isolated_root() / "agent-world.sqlite3")
    return context, snapshot, DemoWorkflowService(repository, artifact_url_prefix=PREFIX + "artifacts/")


def domain_service_for(handler):
    """Compose the existing DomainService with fresh, isolated Preview admission.

    Even reads refresh the session before opening storage. No live gateway,
    credential resolver, judge, scheduler or enqueue adapter is imported here.
    """
    context = request_context(handler._remote_context or {},
                              control_authorized=handler._preview_control_authorized())
    root = preview_sandbox.isolated_root()

    def fresh(*, write=False, operator=False):
        preview_sandbox.require_enabled()
        if preview_sandbox.isolated_root() != root:
            raise ContractError("agent_world_context_changed")
        raw = account_auth.authenticate_session(handler._cookie_value(runtime_env.session_cookie_name()))
        if not raw:
            raise ContractError("agent_world_session_expired")
        raw = handler._decorate_workspace_context(raw)
        raw["_request_method"] = "POST" if write else "GET"
        permissions.enforce(PREFIX + "domains/personas", raw)
        current = request_context(raw, control_authorized=handler._preview_control_authorized())
        if current != context:
            raise ContractError("agent_world_context_changed")
        if subscriptions.trial_usage_for_user(raw.get("user_id")).get("expired"):
            raise ContractError("agent_world_access_expired")
        snapshot = flag_snapshot(context)
        required = (Flag.AI_CONTROL_CENTER_READ_MODEL, Flag.AI_TASK_GRAPH_V2) if write else (Flag.AI_CONTROL_CENTER_READ_MODEL,)
        if any(not resolve(flag, scope=context.scope, snapshot=snapshot).enabled for flag in required):
            raise ContractError("agent_world_disabled")
        if write and not ai_budgets.check_budget(context.scope.workspace_id, 0.0).get("ok"):
            raise ContractError("agent_world_budget_denied")
        if operator and not preview_sandbox.synthetic_operator_access_allowed(raw):
            raise ContractError("agent_world_preview_operator_required")
        return raw

    fresh()
    from .domain_service import DomainService
    from .preview_domains import PreviewDomains
    from .sqlite_repository import SQLiteAgentWorldRepository
    repository = SQLiteAgentWorldRepository(root / "agent-world.sqlite3")
    domains = PreviewDomains(context=context, service=DomainService(repository), fresh=fresh,
                          flags=lambda: {flag.value: resolve(flag, scope=context.scope,
                              snapshot=flag_snapshot(context)).enabled for flag in REGISTRY})
    from .. import preview_shared_models
    return preview_shared_models.SharedDomains(domains, handler) if preview_shared_models.enabled() else domains


def enrich(payload: dict, context: RequestContext, snapshot: FlagSnapshot) -> dict:
    stats = payload.get("stats") or {}
    agents = payload.get("agents") or []
    agents = agents.get("items", []) if isinstance(agents, dict) else agents
    tasks = (payload.get("work") or {}).get("items", [])
    latest = sorted(tasks, key=lambda task: task.get("updated_at", ""), reverse=True)[:8]
    return {**payload, "enabled": True, "status": "IN DEVELOPMENT",
            "agents": agents, "tasks": tasks,
            "activity": [{"title": task["title"], "status": task["status"],
                          "time": task["updated_at"], "task_id": task["id"],
                          "summary": task["title"] + " · " + task["status"], "synthetic": True} for task in latest],
            "attention": [{"title": task["title"], "status": task["status"], "task_id": task["id"],
                           "summary": "Откройте evidence и проверьте причину остановки."}
                          for task in tasks if task["status"] in {"failed", "blocked"}],
            "stats": {**stats, "active_tasks": stats.get("running", 0),
                      "completed_tasks": stats.get("completed", 0), "agents": len(agents), "attention": stats.get("failed", 0)},
            "scope": {"environment": context.scope.environment.value,
                      "workspace_id": context.scope.workspace_id, "synthetic": True},
            "capabilities": {"can_run_demo": True, "can_view_models": False, "can_view_system": True},
            "flags": {flag.value: resolve(flag, scope=context.scope, snapshot=snapshot).enabled for flag in REGISTRY},
            "limitations": list(LIMITATIONS)}


def admission(handler, context: RequestContext, snapshot: FlagSnapshot):
    from .demo_workflows import DemoAdmission

    def revalidate() -> None:
        # Refresh the real session/membership/capabilities during each bounded
        # checkpoint; no job is admitted on a stale UI capability snapshot.
        fresh = account_auth.authenticate_session(handler._cookie_value(runtime_env.session_cookie_name()))
        if not fresh:
            raise ContractError("agent_world_session_expired")
        fresh = handler._decorate_workspace_context(fresh)
        fresh["_request_method"] = "POST"
        permissions.enforce(PREFIX + "demo-runs", fresh)
        current = request_context(fresh, control_authorized=handler._preview_control_authorized())
        if current != context:
            raise ContractError("agent_world_context_changed")
        usage = subscriptions.trial_usage_for_user(fresh.get("user_id"))
        if usage.get("expired"):
            raise ContractError("agent_world_access_expired")
        for flag in (Flag.AI_TASK_GRAPH_V2, Flag.AI_EVALUATION_SHADOW):
            if not resolve(flag, scope=context.scope, snapshot=flag_snapshot(context)).enabled:
                raise ContractError("agent_world_disabled")
        if not ai_budgets.check_budget(context.scope.workspace_id, 0.0).get("ok"):
            raise ContractError("agent_world_budget_denied")

    revalidate()
    return DemoAdmission(
        scope=context.scope, user_uuid=context.user_uuid, synthetic=True, enabled=True,
        budget=ExternalRef(authority=ExternalAuthority.BUDGET, scope=context.scope,
                           key="ai_budgets.zero_cost." + context.scope.workspace_id),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=2), revalidate=revalidate,
    )
