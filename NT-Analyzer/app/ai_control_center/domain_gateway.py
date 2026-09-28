"""Development composition for own-workspace domains; existing authorities only.

No provider keys, caller-selected scope or new worker are introduced here.
Real NinjaTrader/Desktop access still requires the stricter Local-owner adapter.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import re
import sqlite3
import time
from uuid import UUID

from .. import account_auth, ai_budgets, permissions, preview_sandbox, runtime_env, workspaces
from . import live_gateway, server_gateway
from .contracts import ActorKind, ActorRef, Environment, RequestContext, TenantScope
from .flags import Flag, REGISTRY, resolve
from . import presentation
from .states import ContractError, EntityKind

DOMAINS = frozenset({"personas", "memory", "projects", "routines", "calendar", "decisions", "court",
                     "external_agents",
                     "models", "model_tasks", "experiments", "system", "tasks", "publications", "automation", "router"})


def access(scope, *, read_only=False):
    if preview_sandbox.enabled():
        from ..preview_shared_models import authorize
        return authorize(scope, read_only=read_only)
    if not isinstance(scope, dict) or not (live_gateway.configured(str(scope.get("workspace_id") or ""))
                                             or server_gateway.configured(str(scope.get("workspace_id") or ""))):
        raise ContractError("agent_world_local_disabled")
    try:
        uid, identity = int(scope.get("user_id") or 0), UUID(str(scope.get("user_uuid") or ""))
    except (ValueError, TypeError):
        raise ContractError("agent_world_identity_required") from None
    user = account_auth.find_active_user(uid)
    if (not user or user.get("is_preview_user") or user.get("is_service_account")
            or str(user.get("user_uuid") or user.get("id")) != str(identity)):
        raise ContractError("agent_world_identity_required")
    session_id = str(scope.get("auth_session_id") or "")
    if session_id:
        session_active = (account_auth.server_session_is_active(session_id, uid, str(identity))
                          if runtime_env.is_server_environment() else
                          account_auth.local_session_is_active(session_id, uid))
        if not session_active:
            raise ContractError("agent_world_session_expired")
    elif runtime_env.is_server_environment() or user.get("is_owner") is not True:
        raise ContractError("agent_world_confirmed_session_required")
    workspace_reader = workspaces.require_workspace_access if read_only else workspaces.require_workspace_writer
    workspace = workspace_reader(uid, workspace_id=scope["workspace_id"])
    if (workspace.get("status") != "active" or (not read_only and
            (int(workspace.get("owner_user_id") or 0) != uid or (workspace.get("membership") or {}).get("role") != "owner"))):
        raise ContractError("agent_world_own_workspace_required")
    perm = permissions.resolve_for_user_id(uid, user)
    permissions.enforce(live_gateway.PREFIX + "domains/personas", {**perm, "user": user, "user_id": uid,
                                                                  "_request_method": "GET" if read_only else "POST"})
    if not read_only and not (perm.get("capabilities") or {}).get("ai_lab"):
        raise ContractError("agent_world_capability_required")
    normalized = {"user_id": uid, "user_uuid": str(identity), "workspace_id": workspace["workspace_id"],
                  "workspace_kind": workspace["kind"], "uses_owner_runtime": bool(workspace.get("uses_owner_runtime")),
                  "is_owner": user.get("is_owner") is True, "membership_role": (workspace.get("membership") or {}).get("role"),
                  "display_name": str(scope.get("display_name") or ""), "capabilities": perm["capabilities"]}
    if session_id:
        normalized["auth_session_id"] = session_id
    server_environment = server_gateway.environment()
    context = RequestContext(scope=TenantScope(environment=server_environment or Environment.DEVELOPMENT,
                                                workspace_id=workspace["workspace_id"]),
                             user_uuid=identity, actor=ActorRef(kind=ActorKind.HUMAN, actor_id=identity))

    def admit():
        current = access(normalized, read_only=read_only)
        if current["context"] != context:
            raise ContractError("agent_world_context_changed")
        if not resolve(Flag.AI_TASK_GRAPH_V2, scope=context.scope, snapshot=current["snapshot"]).enabled:
            raise ContractError("agent_world_disabled")

    # The callback revalidates on mutations/transmission. Do not call it here
    # recursively; the constructor above itself already checks live authority.
    return {"context": context, "chat_scope": normalized, "admit": admit,
            "refresh": lambda **kw: access(normalized, read_only=kw.get("read_only", read_only)),
            "source_scope": {"workspace_id": workspace["workspace_id"], "user_id": uid, "allow_legacy": False},
            "snapshot": (server_gateway.flag_snapshot(context) if server_environment else
                         live_gateway.flag_snapshot(context)), "read_only": read_only}


def refresh_authority(authorized, *, read_only=None):
    mode = authorized.get("read_only", False) if read_only is None else read_only
    if callable(authorized.get("refresh")):
        return authorized["refresh"](read_only=mode)
    if authorized.get("automation") or authorized["context"].actor.kind != ActorKind.HUMAN:
        raise ContractError("automation_refresh_required")
    return access(authorized["chat_scope"], read_only=mode)


def from_handler(handler, *, read_only=False):
    raw = handler._remote_context or {}
    if ((raw.get("role") == "read_only" and not read_only) or (raw.get("source") != "local"
            and raw.get("device_confirmation_state") != "active")
            or (raw.get("source") == "local" and raw.get("is_owner") is not True)):
        raise ContractError("agent_world_confirmed_session_required")
    scope = dict(handler._ai_conversation_scope())
    if raw.get("source") != "local":
        scope["auth_session_id"] = str(raw.get("session_id") or scope.get("auth_session_id") or "")
        if not scope["auth_session_id"]:
            raise ContractError("agent_world_confirmed_session_required")
    result = access(scope, read_only=read_only)
    result["session_read_only"] = raw.get("role") == "read_only"
    return result


def domain_admission(authorized, domain, action="read"):
    required = {"memory": Flag.AI_MEMORY_V2, "decisions": Flag.AI_CONSENSUS_V2,
                "court": Flag.AI_COURT_V1, "experiments": Flag.AI_EVALUATION_SHADOW,
                "publications": Flag.AI_SOCIAL_PUBLISH_V1}.get(domain, Flag.AI_TASK_GRAPH_V2)
    if domain == "decisions" and action == "review":
        required = Flag.AI_COURT_V1
    def admit():
        authorized["admit"]()
        current = refresh_authority(authorized)
        if not resolve(required, scope=current["context"].scope, snapshot=current["snapshot"]).enabled:
            raise ContractError("agent_world_domain_disabled")
    admit()
    return admit


def repository(authorized):
    authorized["admit"]()
    if authorized.get("preview_bridge"):
        from .sqlite_repository import SQLiteAgentWorldRepository
        return SQLiteAgentWorldRepository(preview_sandbox.isolated_root() / "agent-world.sqlite3",
                                          read_only=authorized.get("read_only", False))
    if authorized["context"].scope.environment in {Environment.CANARY, Environment.PRODUCTION}:
        from ..production_storage.core import PostgresClient
        from .postgres_repository import PostgresAgentWorldRepository
        return PostgresAgentWorldRepository(PostgresClient(
            os.environ.get("STRATFORGE_DATABASE_URL", ""), production=True),
            environment=authorized["context"].scope.environment, read_only=authorized.get("read_only", False))
    backend = os.environ.get("STRATFORGE_AGENT_WORLD_STORAGE", "sqlite").strip().lower()
    if backend == "postgres":
        from ..production_storage.core import PostgresClient
        from .postgres_repository import PostgresAgentWorldRepository
        dsn = os.environ.get("STRATFORGE_AGENT_WORLD_DATABASE_URL", "")
        if not dsn:
            raise ContractError("agent_world_postgres_not_configured")
        # Explicit composition only. No inherited Production DSN, migration,
        # schema creation, copying of owner data, or SQLite fallback on error.
        return PostgresAgentWorldRepository(PostgresClient(dsn, production=False),
            environment=authorized["context"].scope.environment, read_only=authorized.get("read_only", False))
    if backend != "sqlite":
        raise ContractError("agent_world_storage_backend_invalid")
    from .sqlite_repository import SQLiteAgentWorldRepository
    return SQLiteAgentWorldRepository(runtime_env.data_path("ai_lab", "agent-world.sqlite3"),
                                      read_only=authorized.get("read_only", False))


def _model_admit(authorized, context, operation, estimate):
    authorized["admit"]()
    if context != authorized["context"] or not math.isfinite(float(estimate)) or estimate < 0:
        raise ContractError("model_context_required")
    if operation == "read":
        return
    if authorized.get("read_only"):
        raise ContractError("model_history_read_only")
    current = refresh_authority(authorized, read_only=False)
    # Calling a connection somebody else shares needs AI access, not the right
    # to connect models of one's own; the share and the budget still apply.
    required = "ai_lab" if str(operation).startswith("shared_") else "ai_pro_models"
    if not current["chat_scope"]["capabilities"].get(required):
        raise ContractError("model_capability_required")
    if not ai_budgets.check_budget(context.scope.workspace_id, estimate).get("ok"):
        raise ContractError("model_budget_exhausted")


def owner_binding(authorized, registry_id):
    authorized["admit"]()
    current = refresh_authority(authorized)
    if not current["chat_scope"].get("is_owner") or not current["chat_scope"].get("uses_owner_runtime"):
        raise ContractError("model_owner_binding_denied")
    if not isinstance(registry_id, str) or not re.fullmatch(r"AGT-[A-Z0-9]{12}", registry_id):
        raise ContractError("model_owner_binding_denied")
    from ..ai_lab import agent_registry
    try:
        row = agent_registry.get_agent(registry_id)
    except agent_registry.AgentRegistryError:
        raise ContractError("model_owner_binding_denied") from None
    if (not row.get("enabled") or not row.get("key_configured") or row.get("endpoint_type") != "chat"
            or row.get("pricing_status") not in {"free", "configured", "estimated"}):
        raise ContractError("model_owner_binding_unavailable")
    # An enabled owner connection with existing caps is reused, never modified.
    return {key: row.get(key) for key in ("id", "name", "provider", "model", "base_url", "pricing_status",
                                         "remaining_daily_budget_usd", "remaining_monthly_budget_usd")}


def _private_limits(context, model, profile):
    from ..ai_lab import agent_registry
    pricing = agent_registry.managed_pricing(model.provider_key, model.model_key,
                  agent_registry.infer_billing_mode(model.provider_key, model.model_key, 0))
    # No approved paid allowance exists for new private Development connections.
    # Zero-cost managed endpoints can be checked without increasing any budget.
    if pricing.get("pricing_status") != "free":
        raise ContractError("model_private_budget_not_configured")
    return {"daily_budget_usd": agent_registry.MAX_SINGLE_CALL_USD,
            "monthly_budget_usd": agent_registry.MAX_SINGLE_CALL_USD}


def enqueue_model(authorized, *, context, task_id):
    authorized["admit"]()
    if context != authorized["context"]:
        raise ContractError("model_context_required")
    if authorized.get("preview_bridge"):
        return {"status": "bounded_preview_pending"}
    from .. import worker_router
    from . import execution_v2
    service = models(authorized)
    managed = execution_v2.enabled(authorized) or execution_v2.is_managed(service, context, task_id)
    job_id = "wj_aw_model_" + UUID(str(task_id)).hex
    if managed:
        try:
            execution_v2.prepare(authorized, service, task_id)
        except ContractError as error:
            # Only prepare is inside this handler: enqueue can have committed
            # its job before losing the response, which is not a safe refusal.
            # An existing/concurrent submission also owns its own outcome.
            if not worker_router.get(job_id, workspace_id=context.scope.workspace_id):
                task = service._get(context, EntityKind.TASK, task_id)
                checkpoint = service._json(context, task.checkpoint)
                service._fail(context, task, checkpoint, error.code, pre_enqueue=True)
            raise
    payload = {"task_id": str(task_id), "scope": authorized["chat_scope"]}
    if authorized.get("automation"):
        payload.update(automation_controller_id=authorized["automation_controller_id"],
                       automation_grant_ref=authorized["automation_grant_ref"])
    try:
        return worker_router.enqueue("agent_world_model", payload, user_id=authorized["source_scope"]["user_id"],
            workspace_id=context.scope.workspace_id, job_id=job_id, max_attempts=3 if managed else 1, timeout_sec=180, priority=55)
    except sqlite3.IntegrityError:
        old = worker_router.get(job_id, workspace_id=context.scope.workspace_id)
        if not old or old.get("kind") != "agent_world_model" or old.get("payload") != payload:
            raise ContractError("model_queue_identity_conflict") from None
        return old


def _executor(authorized, bind, *, secrets=None):
    """The provider transport, or a named workspace's local test executor.

    A private connection cannot point at a loopback stub -- the transport
    refuses any non-global address, deliberately -- so an end-to-end run in an
    isolated instance needs this seam instead. It is off unless an operator
    named that exact workspace, it exists only in Development, and it changes
    nothing else: the same admissions, budget, grant and verifier apply.
    """
    from .model_execution import ModelExecutor
    if authorized.get("preview_bridge"):
        from ..preview_shared_models import execute
        return execute
    from . import test_executor
    if test_executor.enabled(authorized["context"].scope.workspace_id):
        return test_executor.execute
    # Server private connections are free-only. Their authoritative usage is
    # recorded by universal_llm through sf_ai_usage_events after transmission;
    # never append the Development JSONL registry inside a release directory.
    server = (server_gateway.environment() is not None and
              getattr(authorized["context"].scope, "environment", None)
              in {Environment.CANARY, Environment.PRODUCTION})
    return ModelExecutor(budget_limits=_private_limits, owner_binding=bind, secrets=secrets,
        usage_reader=(lambda **kw: []) if server else None,
        usage_writer=(lambda row: None) if server else None)


def models(authorized, repo=None):
    from .model_service import ModelService
    store = repo or repository(authorized)
    secrets = None
    if (server_gateway.environment() is not None and
            authorized["context"].scope.environment in {Environment.CANARY, Environment.PRODUCTION}):
        from .server_secrets import ServerSecrets
        secrets = ServerSecrets(store, authorized["context"])
    def bind(context, model, profile):
        if context != authorized["context"]:
            raise ContractError("model_context_required")
        return owner_binding(authorized, profile.get("existing_registry_id"))["id"]
    service = ModelService(store,
        mechanism_authorized=authorized,
        chat_scope=authorized["chat_scope"],
        admit=lambda context, operation, estimate: _model_admit(authorized, context, operation, estimate),
        enqueue=lambda **kw: enqueue_model(authorized, **kw),
        executor=(_executor(authorized, bind, secrets=secrets) if secrets is not None
                  else _executor(authorized, bind)), secrets=secrets,
        allowed_origins=tuple(item.strip() for item in os.environ.get("STRATFORGE_AGENT_WORLD_MODEL_ORIGINS", "").split(",") if item.strip()))
    from . import automation_authority
    service.mechanism_admit = lambda **kw: automation_authority.admit(authorized, service, **kw)
    def admission(context, operation, estimate=0.0):
        _model_admit(authorized, context, operation, estimate)
        if authorized.get("automation") and operation != "read":
            from .contracts import EntityRef
            service.mechanism_admit(context=context,
                controller=EntityRef(kind=EntityKind.TASK, entity_id=UUID(authorized["automation_controller_id"]), revision=1, scope=context.scope),
                grant_ref=authorized["automation_grant_ref"], operation=operation, estimated_cost_usd=estimate)
    service.admit = admission
    return service


def history_models(authorized):
    """Read-only completion projection with no executor/queue capability."""
    if authorized.get("read_only") is not True:
        raise ContractError("model_history_context_required")
    from .model_service import ModelService
    return ModelService(repository(authorized),
        chat_scope=authorized["chat_scope"],
        admit=lambda context, operation, estimate: _model_admit(authorized, context, operation, estimate))


def external_agents(authorized, repo=None):
    from .external_agent_native import ExternalAgentService
    from .. import worker_router
    def _enqueue(job_id, payload, **kw):
        # Same idiom as delegation._queue: a repeated enqueue of the identical
        # job is the queue already holding it, not a failure. Only a different
        # payload under the same id is a real conflict.
        try:
            return worker_router.enqueue("agent_world_external", payload, job_id=job_id,
                workspace_id=authorized["context"].scope.workspace_id,
                user_id=authorized["chat_scope"]["user_id"], **kw)
        except sqlite3.IntegrityError:
            old = worker_router.get(job_id, workspace_id=authorized["context"].scope.workspace_id) or {}
            if old.get("kind") != "agent_world_external" or old.get("payload") != payload:
                raise ContractError("external_agent_job_conflict") from None
            return old
    def queue(task_id):
        authorized["admit"]()
        return _enqueue("wj_aw_external_" + UUID(str(task_id)).hex,
            {"scope": authorized["chat_scope"], "task_id": str(task_id)}, max_attempts=5, timeout_sec=120)
    def cleanup(**kw):
        context, identity = kw["context"], kw["connection_id"]
        if context != authorized["context"]: raise ContractError("external_agent_scope_invalid")
        return _enqueue("wj_aw_external_cleanup_" + UUID(str(identity)).hex,
            {"scope": authorized["chat_scope"], "connection_id": str(identity), "phase": "external_cleanup"},
            max_attempts=5, timeout_sec=60)
    return ExternalAgentService(authorized, models(authorized, repo), enqueue=queue, enqueue_cleanup=cleanup)


def _model_source(job):
    payload = job.get("payload") or {}
    scope = payload.get("scope") or {}
    if (job.get("kind") != "agent_world_model" or payload.get("phase")
            or str(scope.get("workspace_id") or "") != str(job.get("workspace_id") or "")
            or str(scope.get("user_id") or "") != str(job.get("user_id") or "")):
        raise ContractError("model_delivery_source_invalid")
    try:
        identity = "wj_aw_model_" + UUID(str(payload.get("task_id"))).hex
    except (ValueError, TypeError):
        raise ContractError("model_delivery_source_invalid") from None
    if job.get("worker_job_id", job.get("id")) != identity:
        raise ContractError("model_delivery_source_invalid")
    return payload, scope


def worker_authority(job, *, read_only=False):
    """Scope comes from the durable job; automation also needs a sealed child."""
    from .. import worker_router
    from . import automation_authority
    payload = job.get("payload") or {}
    if payload.get("phase") in {"delivery", "coordinator_delivery", "coordinator_continue"}:
        source = worker_router.get(payload.get("source_worker_job_id"), workspace_id=str(job.get("workspace_id") or "")) or {}
        source_payload, scope = _model_source(source)
        if scope != payload.get("scope"):
            raise ContractError("model_delivery_scope_invalid")
    else:
        source_payload, scope = payload, payload.get("scope") or {}
    coordination = source_payload.get("phase") in {"delegation_step", "scheduler_occurrence", "automation_watch"}
    controller_id = source_payload.get("controller_id") if coordination else source_payload.get("automation_controller_id")
    reference = source_payload.get("grant_ref") if coordination else source_payload.get("automation_grant_ref")
    aggregate_delivery = payload.get("phase") == "coordinator_delivery" and (
        payload.get("automation_controller_id") or payload.get("automation_grant_ref"))
    if aggregate_delivery:
        if not read_only or payload.get("automation_controller_id") != payload.get("task_id"):
            raise ContractError("automation_delivery_scope_invalid")
        controller_id, reference = payload.get("automation_controller_id"), payload.get("automation_grant_ref")
    if bool(controller_id) != bool(reference):
        raise ContractError("automation_worker_authority_missing")
    if not controller_id:
        if coordination:
            raise ContractError("automation_worker_authority_missing")
        return access(scope, read_only=read_only)
    authorized = automation_authority.access(scope, controller_id=controller_id, grant_ref=reference, read_only=read_only)
    if aggregate_delivery:
        from . import delegation
        service = history_models(authorized)
        _, _, plan = delegation.controller(service, authorized["context"], controller_id)
        if plan.get("grant_ref") != reference or plan.get("root_task", {}).get("entity_id") != source_payload.get("task_id"):
            raise ContractError("automation_delivery_scope_invalid")
    elif not coordination:
        service = history_models(authorized) if read_only else models(authorized)
        task = service._get(authorized["context"], EntityKind.TASK, source_payload.get("task_id"))
        packet = service._json(authorized["context"], task.checkpoint).get("delegation") or {}
        if packet.get("controller_id") != str(controller_id) or packet.get("grant_ref") != reference:
            raise ContractError("automation_child_scope_mismatch")
    return authorized


def _delivery_job_id(task_id, event_id):
    try:
        return "wj_aw_delivery_" + UUID(str(task_id)).hex + "_" + UUID(str(event_id)).hex
    except (ValueError, TypeError):
        raise ContractError("model_delivery_identity_invalid") from None


def _require_delivery_claim(job):
    """Fence this publisher to the current existing worker claim, not a DTO."""
    from .. import worker_router
    current = worker_router.get(job.get("worker_job_id", job.get("id")),
                                workspace_id=str(job.get("workspace_id") or "")) or {}
    now = time.time()
    try:
        live = all(math.isfinite(float(current.get(key) or 0)) and float(current.get(key) or 0) > now
                   for key in ("locked_until", "deadline_at"))
    except (TypeError, ValueError):
        live = False
    if (job.get("status") != "running" or not job.get("worker_id")
            or job.get("kind") != "agent_world_model" or type(job.get("attempts")) is not int or job["attempts"] < 1
            or current.get("status") != "running" or current.get("kind") != "agent_world_model"
            or current.get("worker_id") != job.get("worker_id")
            or current.get("attempts") != job.get("attempts")
            or current.get("payload") != job.get("payload")
            or str(current.get("user_id")) != str(job.get("user_id"))
            or str(current.get("workspace_id")) != str(job.get("workspace_id"))
            or current.get("cancel_requested") or job.get("cancel_requested") or not live):
        raise ContractError("model_delivery_claim_required")


def history_delivery_authority(job):
    """Chief-only ingress from an exact claimed delivery, never a browser flag.

    A service actor keeps its existing grant-backed history access instead of
    impersonating a browser session. The caller still has to validate the exact
    saved completion and original user message before appending anything.
    """
    from . import coordinator_delivery, followup_chat
    if type(job) is not dict or type(job.get("payload")) is not dict:
        raise ContractError("model_delivery_job_required")
    payload = job["payload"]
    expected = {"phase", "scope", "source_worker_job_id", "task_id", "event_id", "checkpoint_sha256"}
    phase = payload.get("phase")
    if phase == "coordinator_delivery" and (payload.get("automation_controller_id") or payload.get("automation_grant_ref")):
        expected |= {"automation_controller_id", "automation_grant_ref"}
    if phase not in {"delivery", "coordinator_delivery"} or set(payload) != expected:
        raise ContractError("model_delivery_job_required")
    kind = "agent_world_model" if phase == "delivery" else "agent_world_followup"
    identity = (_delivery_job_id(payload["task_id"], payload["event_id"]) if phase == "delivery"
        else coordinator_delivery._identity(phase, payload["task_id"], payload["event_id"]))
    if job.get("kind") != kind or job.get("worker_job_id", job.get("id")) != identity:
        raise ContractError("model_delivery_identity_invalid")
    authorized = worker_authority(job, read_only=True)
    if (str(job.get("workspace_id")) != authorized["context"].scope.workspace_id
            or str(job.get("user_id")) != str(authorized["source_scope"]["user_id"])
            or str((payload.get("scope") or {}).get("user_uuid")) != str(authorized["context"].user_uuid)):
        raise ContractError("model_delivery_scope_invalid")
    def admitted():
        current = worker_authority(job, read_only=True)
        if current["context"] != authorized["context"] or current["chat_scope"] != authorized["chat_scope"]:
            raise ContractError("model_delivery_scope_invalid")
        current["admit"]()
        if phase == "delivery":
            from .. import worker_router
            source, scope = _model_source(worker_router.get(payload["source_worker_job_id"],
                workspace_id=current["context"].scope.workspace_id) or {})
            if source.get("task_id") != payload["task_id"] or scope != payload["scope"]:
                raise ContractError("model_delivery_scope_invalid")
            _require_delivery_claim(job)
        else:
            followup_chat._claim(current, job)
    admitted()
    return {**authorized, "admit": admitted}


def enqueue_model_delivery(authorized, service, task_id):
    """Existing worker, terminal-only phase; bounded delivery retries, no calls."""
    from .. import worker_router
    from . import model_chat
    saved = model_chat.completion(authorized, service, task_id)
    if saved is None:
        return None
    context = authorized["context"]
    if service.repository.events.is_acknowledged(context=context, consumer=model_chat.DELIVERY_CONSUMER,
                                                event_id=UUID(saved["event_id"])):
        return None
    source_id = "wj_aw_model_" + UUID(str(task_id)).hex
    source, scope = _model_source(worker_router.get(source_id, workspace_id=context.scope.workspace_id) or {})
    if (str(scope.get("user_uuid")) != str(context.user_uuid)
            or str(scope.get("user_id")) != str(authorized["source_scope"]["user_id"])
            or scope.get("auth_session_id") != authorized["chat_scope"].get("auth_session_id")):
        raise ContractError("model_delivery_scope_invalid")
    payload = {"phase": "delivery", "scope": scope, "source_worker_job_id": source_id,
               **{field: saved[field] for field in ("task_id", "event_id", "checkpoint_sha256")}}
    identity = _delivery_job_id(saved["task_id"], saved["event_id"])
    try:
        return worker_router.enqueue("agent_world_model", payload, user_id=authorized["source_scope"]["user_id"],
            workspace_id=context.scope.workspace_id, job_id=identity, max_attempts=3, timeout_sec=30, priority=70)
    except sqlite3.IntegrityError:
        old = worker_router.get(identity, workspace_id=context.scope.workspace_id)
        if (not old or old.get("kind") != "agent_world_model" or old.get("payload") != payload
                or str(old.get("user_id")) != str(authorized["source_scope"]["user_id"])):
            raise ContractError("model_delivery_identity_conflict") from None
        return old


def reconcile_model_deliveries(rows):
    """Existing worker's bounded read batch; never called from GET or a timer."""
    recovered, denied = 0, 0
    for row in rows[:100]:
        if row.get("status") not in {"succeeded", "failed", "stale", "cancelled"} or (row.get("payload") or {}).get("phase"):
            continue
        try:
            payload, scope = _model_source(row)
            authorized = worker_authority(row, read_only=True)
            authorized["admit"]()
            queued = enqueue_model_delivery(authorized, history_models(authorized), payload["task_id"])
            recovered += int(bool(queued and queued.get("status") == "queued"))
            from . import coordinator_delivery
            continued = coordinator_delivery.enqueue_continuation(authorized, payload["task_id"])
            recovered += int(bool(continued and continued.get("status") == "queued"))
            related = coordinator_delivery.related(authorized, payload["task_id"])
            recovered += len(related["queued"])
            denied += len(related["blocked"])
        except Exception:
            # A revoked/foreign scope or unavailable receipt is not permission
            # to repair domain state. Only bounded counts leave this selector.
            denied += 1
    return {"recovered": recovered, "denied": denied}


def reconcile_schedules(rows):
    """Existing worker's bounded batch; the scheduler owns every decision.

    A schedule nobody is watching still has to run. This never invents a scope
    -- it reuses the one recorded on a job the workspace already produced --
    and never dispatches anything itself. `scan_due` selects the controllers it
    considers due, and each occurrence is admitted against its own stored
    grant, flag and budget exactly as it would be from the panel.
    """
    from . import scheduler
    scanned, denied, seen = 0, 0, set()
    for row in rows[:100]:
        scope = (row.get("payload") or {}).get("scope")
        key = (str(row.get("workspace_id") or ""), str(row.get("user_id") or ""))
        if not isinstance(scope, dict) or not all(key) or key in seen:
            continue
        seen.add(key)
        try:
            authorized = access(scope)
            if not resolve(Flag.AI_SCHEDULER_V1, scope=authorized["context"].scope,
                           snapshot=authorized["snapshot"]).enabled:
                continue
            scanned += len(scheduler.scan_due(authorized, models(authorized)))
        except Exception:
            # A revoked grant, a disabled flag or a foreign scope is not a
            # reason to stop scanning the rest, and never a reason to run
            # anything. Only bounded counts leave this selector.
            denied += 1
    return {"scanned": scanned, "denied": denied}


def _followup(authorized, *, context, kind, payload, idempotency_key):
    authorized["admit"]()
    if context != authorized["context"] or kind not in {"routine", "calendar_item"} or payload.get("automation_enabled") is not False:
        raise ContractError("domain_followup_denied")
    from .. import worker_router
    key = "wj_aw_followup_" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]
    try:
        row = worker_router.enqueue("agent_world_followup", {"scope": authorized["chat_scope"], "kind": kind, "request": payload},
            user_id=authorized["source_scope"]["user_id"], workspace_id=context.scope.workspace_id,
            job_id=key, max_attempts=1, timeout_sec=30)
    except sqlite3.IntegrityError:
        row = worker_router.get(key, workspace_id=context.scope.workspace_id)
        if not row or row.get("kind") != "agent_world_followup" or row.get("payload", {}).get("request") != payload:
            raise ContractError("domain_followup_identity_conflict") from None
    return {"job_id": key, "status": row.get("status")}


def domains(authorized, repo=None):
    from .domain_service import DomainService
    repo = repo or repository(authorized)
    model_service = models(authorized, repo)
    def memory_authority(context):
        if context != authorized["context"]:
            raise ContractError("memory_context_mismatch")
        current = access(authorized["chat_scope"], read_only=True)
        domain_admission(current, "memory")
        user = account_auth.find_active_user(current["source_scope"]["user_id"]) or {}
        return {"session_id": current["chat_scope"].get("auth_session_id"),
                "governance_allowed": user.get("is_owner") is True or user.get("role") in {"owner", "admin"}}
    return DomainService(repo, judge_runner=model_service.judge, memory_authority=memory_authority,
                         enqueue=lambda **kw: _followup(authorized, **kw))


def scoped_memory_artifact(authorized, found):
    from .memory_policy import artifact_allowed
    return artifact_allowed(domains(authorized), authorized["context"], found)


def social(authorized, repo=None):
    from .social_publication import SocialPublicationService
    def backtest(*, context, source_id, admit):
        from .live_backtests import LiveBacktestService
        admit()
        if context != authorized["context"]:
            raise ContractError("social_source_scope_mismatch")
        owner = live_gateway.access(authorized["chat_scope"])
        return LiveBacktestService().get(**live_gateway.service_args(owner), job_id=source_id)
    return SocialPublicationService(repo or repository(authorized), backtest_loader=backtest)


def social_admission(authorized):
    admit = domain_admission(authorized, "publications")
    def check():
        admit()
        current = access(authorized["chat_scope"], read_only=authorized.get("read_only", False))
        scope = current["chat_scope"]
        user = account_auth.find_active_user(scope["user_id"])
        permissions.enforce("/api/community/social/posts", {**permissions.resolve_for_user_id(scope["user_id"], user),
            "user": user, "user_id": scope["user_id"], "_request_method": "GET" if authorized.get("read_only") else "POST"})
    check()
    return check


def _component(identity, title, summary, *, implemented, enabled, mode, available, note=""):
    """Four separate facts about one component.

    Whether the code exists, whether it is switched on, which implementation is
    actually serving requests and whether it currently answers are different
    questions. One green badge answered all four and hid the ones that were
    false, so each is reported on its own.
    """
    return {"id": identity, "title": title, "summary": summary,
            "implemented": implemented, "enabled": enabled, "mode": mode, "available": available,
            "status": "active" if implemented and enabled and available else
                      "planned" if not implemented else
                      "disabled" if not enabled else "external_blocked",
            "note": note}


def system(authorized):
    authorized["admit"]()
    from .flags import current_snapshot
    from .repositories import PageRequest
    from .. import worker_router
    context = authorized["context"]
    snapshot = current_snapshot(authorized)
    flags = {flag.value: resolve(flag, scope=context.scope, snapshot=snapshot).enabled for flag in REGISTRY}
    configured_storage = os.environ.get("STRATFORGE_AGENT_WORLD_STORAGE", "sqlite").strip().lower()
    storage_mode = {"postgres": "PostgreSQL выбран; соединение не подтверждено", "sqlite": "SQLite выбран; чтение не подтверждено"}.get(configured_storage, "недопустимый режим хранилища")
    storage_available = False
    storage_error = None
    try:
        store = repository({**authorized, "read_only": True})
        store.list(context=context, kind=EntityKind.PERSONA, page=PageRequest(limit=1))
        storage_mode = "PostgreSQL · scoped RLS" if store.__class__.__name__ == "PostgresAgentWorldRepository" else "Development SQLite WAL"
        storage_available = True
    except Exception as exc:
        storage_error = exc.code if isinstance(exc, ContractError) else "agent_world_storage_unavailable"
    try:
        worker = worker_router.status()
        worker_available = worker.get("process_alive") is True
    except Exception:
        worker_available = False
    execute = flags[Flag.AI_EXECUTION_V2.value]
    delegate = flags[Flag.AI_DELEGATION_V2.value]
    schedule = flags[Flag.AI_SCHEDULER_V1.value]
    router = flags[Flag.AI_ROUTER_V2.value]
    shadow = flags[Flag.AI_ROUTER_SHADOW_V2.value]
    return {"enabled": True, "items": [
        _component("scope", "Рабочая область", context.scope.workspace_id,
                   implemented=True, enabled=True, mode=context.scope.environment.value, available=True),
        _component("storage", "Хранилище",
                   "Данные владельца и рабочего пространства разделены; история и доказательства не изменяются",
                   implemented=True, enabled=True, mode=storage_mode, available=storage_available,
                   note="Режим подтверждён чтением через текущее хранилище. Изоляция и восстановление PostgreSQL проверяются отдельными тестами; SQLite их не доказывает. Автоматического переключения нет."),
        _component("worker", "Фоновое исполнение",
                   "Если ответ модели неясен, запрос не отправляется повторно",
                   implemented=True, enabled=True,
                   mode="фоновый исполнитель работает отдельным процессом" if worker_available else "фоновый исполнитель не подтверждён этим сервером", available=worker_available,
                   note="Это состояние фонового исполнителя этого сервера, а не готовность всех механизмов или NinjaTrader."),
        _component("execution_v2", "Исполнение решений",
                   "Исполнение одобренных решений с контролем отклонений",
                   implemented=True, enabled=execute,
                   mode="новый исполнитель для новых разрешённых задач" if execute else "выключен; новые задачи идут прежним путём", available=execute and storage_available and worker_available,
                   note="История задач нового исполнителя сохраняется. Включение не выдаёт прав и не подтверждает результат конкретного исполнения."),
        _component("router", "Выбор модели (Router)",
                   "Подбор вашей модели по классу задачи и измеренной точности",
                   implemented=True, enabled=router or shadow,
                   mode="выбор применяется после вашего подтверждения" if router else "только предпросмотр, без запуска" if shadow else "выключен; модель выбираете вы", available=(router or shadow) and storage_available,
                   note="Учитываются класс задачи и происхождение наблюдений. Тестовые проверки не считаются качеством реальной модели."),
        _component("delegation", "Делегирование",
                   "Координатор распределяет работу; каждый вклад и общий результат проверяются отдельно",
                   implemented=True, enabled=delegate,
                   mode="до трёх уровней, по отдельному разрешению" if delegate else "выключено", available=delegate and storage_available and worker_available,
                   note="Только заранее предусмотренные операции; это не универсальный автономный планировщик."),
        _component("schedule", "Расписания",
                   "Запуск принятых рутин в назначенное время",
                   implemented=True, enabled=schedule,
                   mode="запускаются разрешённые расписания" if schedule else "выключено; только ручной разбор", available=schedule and storage_available and worker_available,
                   note="Перед каждым запуском проверяются разрешение на автоматизацию, согласие на расписание, устройство, срок и бюджет. Принятая рутина сама не запускается."),
        _component("budgets", "Бюджет",
                   "Подключения владельца работают в существующих лимитах. Новым платным подключениям нужен заранее согласованный бюджет; бесплатные подключения расходов не создают.",
                   implemented=True, enabled=True,
                   mode="лимиты владельца", available=True),
        _component("external", "Внешние действия",
                   "Торговые ордера, пересылка в Telegram и автоматическое исполнение решений Court",
                   implemented=True, enabled=False, mode="выключены", available=False)],
        "flags": flags, "capabilities": authorized["chat_scope"]["capabilities"], "actions": [],
        "storage_error_code": storage_error, "limitations": []}


def _followup_projection(authorized, service, domain, row):
    """Expose a separate manual action; reading never queues or runs work."""
    if domain not in {"routines", "calendar"} or not row or row.get("status") != "accepted":
        return row
    from . import followup_chat
    row = dict(row)
    try:
        row["followup_chat"] = followup_chat.projection(authorized, service, domain, row["id"])
    except ContractError:
        row["limitations"] = [*row.get("limitations", []),
            "Источник ручного разбора недоступен или изменён. Автоматизация выключена."]
        return row
    row["actions"] = [*row.get("actions", []), "open_chat"]
    return row


def _mechanism_gateway():
    """Resolve the module that owns the mechanism domains.

    `mechanism_gateway` is the module the mechanisms checkpoint dispatches to
    and has never contained. While it is absent, `mechanism_domains` stands in:
    a thin adapter over `automation_authority`, `scheduler` and `router_v2` that
    creates no second mechanism of its own. When the real module lands it wins
    here, so the two never have to be merged.

    If neither exists the routes fail closed with a stable contract code rather
    than an unhandled import error, and never fall back to another domain.
    """
    for name in ("mechanism_gateway", "mechanism_domains"):
        try:
            return importlib.import_module("." + name, __package__)
        except ImportError:
            continue
    raise ContractError("mechanism_domain_unavailable")


def projected_task(row):
    """Project one task row and derive its progress from that single state.

    An adapter row arrives carrying its source status and a progress number
    computed from it alone. Being terminal at the source is not the same as
    being done: a finished report whose evidence failed verification is still
    awaiting a check, and it must not draw a completed bar. Nothing here
    re-derives the state -- it only makes progress agree with it.
    """
    from . import presentation, task_presentation
    projected = row if row.get("display_status") else task_presentation.project(row)
    result = {**projected,
              "progress_pct": presentation.progress_pct(projected.get("display_status"))}
    if (result.get("display_status") == "awaiting_review" and not result.get("actions")
            and result.get("source_kind") in {"ninjatrader_report", "desktop_chart"}):
        # An adapter row has no review record to accept or reject: its own
        # executor could not confirm its output. Say what happened and point at
        # the source instead of leaving a card with nothing to do.
        result["limitations"] = [*result.get("limitations", []),
            "Автоматическая проверка исходных файлов не пройдена, поэтому принять"
            " этот результат нельзя. Откройте исходный отчёт и при необходимости"
            " запустите новый расчёт."]
        source = str(result.get("report_url") or "")
        if source.startswith("/ui/"):
            result["source_url"] = source
    return result


def _aggregate_detail(authorized, service, record):
    from . import delegation, task_presentation
    context = authorized["context"]
    checkpoint = service._json(context, record.checkpoint)
    if checkpoint.get("source") != delegation.SOURCE:
        return None
    graph = delegation.projection(authorized, service, str(record.header.entity_id))
    root = service._get(context, EntityKind.TASK, graph["root_task"]["entity_id"])
    root_checkpoint = service._json(context, root.checkpoint)
    persona = service._get(context, EntityKind.PERSONA, root_checkpoint["persona_id"])
    result = graph.get("result") or {}
    facts = result.get("facts") or {}
    evaluation = {"passed": True, "operation": "verified_fact_transfer", "professional_quality_assessed": False} if result else None
    task = task_presentation.project({"id": str(record.header.entity_id), "revision": record.header.revision,
        "title": "Общий результат Координатора", "status": record.status,
        "source_kind": "bounded_delegation_result", "task_class": "verified_fact_transfer",
        "synthetic": graph["synthetic"], "conversation_id": graph["conversation_id"],
        "persona_id": str(persona.header.entity_id), "lead": {"id": str(persona.header.entity_id), "display_name": persona.display_name},
        "updated_at": record.header.updated_at.isoformat(), "created_at": record.header.created_at.isoformat(),
        "aggregate_result_received": bool(result), "actions": graph["actions"], "human_review": graph["human_review"],
        "review_state": graph["review_state"], "outcome_id": graph.get("outcome_id"),
        "limitations": ["Это проверка передачи фактов между узлами, не оценка профессионального качества модели."]},
        evaluation=evaluation, human_review=graph["human_review"])
    return {**task, "task": projected_task(task), "graph": graph, "evaluation": evaluation,
        "result_text": "; ".join(str(key) + " = " + str(value) for key, value in facts.items()),
        "artifacts": [], "contributions": result.get("contributions", []), "provenance": result.get("provenance", {})}


def task_detail(authorized, identity, service=None):
    # Reuse the ordinary facade's injected repository/composition. Read-only
    # admission still rejects every execution/mutation operation on this service.
    service = service or models(authorized)
    record = service._get(authorized["context"], EntityKind.TASK, identity)
    if record.checkpoint and service._json(authorized["context"], record.checkpoint).get("source") == "external_agent_task_v1":
        return external_agents(authorized).task_detail(identity)
    return _aggregate_detail(authorized, service, record) or service.task_detail(context=authorized["context"], task_id=identity)


def _aggregate_tasks(authorized, service):
    rows = []
    for record in service._all(authorized["context"], EntityKind.TASK):
        if record.header.owner_user_uuid != authorized["context"].user_uuid:
            continue
        item = _aggregate_detail(authorized, service, record)
        if item:
            rows.append(item)
    return rows


def list_domain(authorized, domain, *, identity=None, limit=50, cursor=None):
    if domain not in DOMAINS:
        raise ContractError("unknown_domain")
    context = authorized["context"]
    admit = domain_admission(authorized, domain)
    if domain == "external_agents":
        service = external_agents(authorized)
        return service.detail(identity) if identity else service.list()
    if domain == "system":
        return system(authorized)
    model_service = models(authorized)
    if domain in {"automation", "router"}:
        return _mechanism_gateway().read(authorized, model_service, domain, identity=identity, limit=limit, cursor=cursor)
    if domain == "publications":
        from .repositories import PageRequest
        service, allowed = social(authorized, model_service.repository), social_admission(authorized)
        candidates = []
        for kind in (EntityKind.OUTCOME, EntityKind.DECISION):
            page = model_service.repository.list(context=context, kind=kind, page=PageRequest(limit=100))
            for record in page.items:
                if record.header.owner_user_uuid != context.user_uuid:
                    continue
                try:
                    preview = service.prepare(context=context, admit=allowed, source_kind=kind.value,
                                              source_id=str(record.header.entity_id))
                except ContractError:
                    continue
                candidates.append({"source_kind": kind.value, "source_id": str(record.header.entity_id),
                    "title": preview["snapshot"]["title"], "source_revision": preview["source_revision"]})
        return {"enabled": True, "items": [], "source_candidates": candidates[:50], "actions": ["prepare"],
                "limitations": ["Публикация постоянная: только после просмотра точного снимка и явного подтверждения. Закрытые запросы и память не публикуются."]}
    if domain == "models":
        if identity:
            return model_service.model_detail(context=context, model_id=identity)
        result = model_service.models(context=context)
        if authorized["chat_scope"].get("is_owner") and authorized["chat_scope"].get("uses_owner_runtime"):
            from ..ai_lab import agent_registry
            candidates = []
            for row in agent_registry.list_agents():
                try:
                    candidates.append(owner_binding(authorized, row.get("id")))
                except ContractError:
                    continue
            result.update(owner_bindings=candidates, actions=result["actions"] + ["bind_existing"])
        return result
    if domain in {"model_tasks", "tasks"}:
        if identity:
            return task_detail(authorized, identity, model_service)
        result = model_service.tasks(context=context)
        aggregates = _aggregate_tasks(authorized, model_service)
        result["total"] = result["total"] + len(aggregates)
        result["items"] = sorted([*result["items"], *aggregates],
            key=lambda row: str(row.get("updated_at") or ""), reverse=True)[:100]
        result["truncated"] = result["total"] > len(result["items"])
        return result
    if domain == "experiments":
        result = model_service.experiments(context=context)
        if identity:
            return next((row for row in result["items"] if row["id"] == identity), None)
        return result
    service = domains(authorized, model_service.repository)
    if identity:
        return _followup_projection(authorized, service, domain,
            service.get(context=context, admit=admit, domain=domain, entity_id=identity))
    result = service.list(context=context, admit=admit, domain=domain, limit=limit, cursor=cursor)
    if domain == "personas":
        from . import persona_voice
        result["presentation_catalog"] = persona_voice.catalog()
    if domain == "memory":
        projects = service.list(context=context, admit=admit, domain="projects", limit=100)
        result["strategy_project_candidates"] = [{"id": row["id"], "title": row["title"]}
            for row in projects["items"] if row["status"] in {"draft", "active"}]
        result["task_candidates"] = [{"id": row["id"], "title": row.get("goal") or row.get("title") or "Задача"}
            for row in model_service.tasks(context=context)["items"]]
    if domain in {"routines", "calendar"}:
        result["items"] = [_followup_projection(authorized, service, domain, row) for row in result["items"]]
        from .process_intelligence import ProcessIntelligence
        result["process_intelligence"] = ProcessIntelligence(service, model_service).analyze(context=context, admit=admit)
        result["process_intelligence"]["candidates"] = [row for row in result["process_intelligence"]["candidates"] if row["domain"] == domain]
    result["actions"] = ["create"] if result["capabilities"].get("can_create") else []
    if domain in {"decisions", "routines"}:
        result["evidence_candidates"] = service.evidence_candidates(context=context, admit=admit)
        result["actions"] += ["propose_consensus" if domain == "decisions" else "suggest_routine"]
        kinds = {"outcome_candidates": ("outcome", "verified")}
        for field, (kind, status) in kinds.items():
            result[field] = list({row["source_id"]: {"id": row["source_id"], "title": row["title"]}
                for row in result["evidence_candidates"]["items"] if row["source_kind"] == kind and row["source_status"] == status}.values())
        if domain == "decisions":
            result["contribution_candidates"] = service.consensus_candidates(context=context, admit=admit)
    return result


def history_projection(authorized, result, *, domain=""):
    """Hide unavailable mutations, not existing evidence, after entitlement expiry."""
    caps = authorized["chat_scope"].get("capabilities") or {}
    blocked = (authorized.get("session_read_only") or not caps.get("ai_lab")
               or authorized["chat_scope"].get("membership_role") != "owner")
    model_domain = domain in {"models", "model_tasks", "tasks", "experiments"}
    model_blocked = (not caps.get("ai_pro_models") or
                     ((model_domain or not domain) and not ai_budgets.check_budget(
                         authorized["context"].scope.workspace_id, 0.0).get("ok")))
    def project(value):
        if isinstance(value, list):
            return [project(item) for item in value]
        if not isinstance(value, dict):
            return value
        return {key: [] if key in {"actions", "allowed_actions", "owner_bindings"} else
                False if key == "execution_available" or key.startswith("can_") and key not in {"can_view_models", "can_view_system"} else project(item)
                for key, item in value.items()}
    if blocked or (model_domain and model_blocked):
        return project(result)
    if not domain and model_blocked and isinstance(result, dict):
        return {key: project(value) if key in {"tasks", "agents", "outcomes"} else value
                for key, value in result.items()}
    return result


def _application_workflows(legacy_tasks, model_rows):
    """Fold only an exact stored model -> original source link, never titles.

    A malformed or ambiguous link remains visible as separate work rather than
    hiding evidence. The original task is retained under source_execution.
    """
    claims = {}
    for row in model_rows:
        task = row["task"]
        dispatch = task.get("application_dispatch") or {}
        identity = dispatch.get("source_task_id")
        if identity:
            claims.setdefault(identity, []).append(task)
    folded, sources = set(), {}
    for source in legacy_tasks:
        candidates = claims.get(source.get("id"), [])
        if len(candidates) != 1:
            continue
        parent = candidates[0]
        dispatch = parent["application_dispatch"]
        field = {"backtest": "source_job_id", "chart": "command_id"}.get(dispatch.get("kind"))
        if (not field or not dispatch.get("source_id") or not parent.get("conversation_id")
                or source.get(field) != dispatch["source_id"]
                or source.get("conversation_id") != parent["conversation_id"]):
            continue
        folded.add(source["id"])
        sources[parent["id"]] = dict(source)
    tasks = [dict(row) for row in legacy_tasks if row.get("id") not in folded]
    tasks += [{**row["task"], **({"source_execution": sources[row["id"]]} if row["id"] in sources else {})}
              for row in model_rows]
    return tasks, folded


def enrich_overview(authorized, base=None):
    """One-page read model; no job dispatch, scores or chat writes on GET."""
    base = dict(base or {})
    context, model_service = authorized["context"], models(authorized)
    can_models = bool(authorized["chat_scope"]["capabilities"].get("ai_pro_models"))
    model_rows = model_service.tasks(context=context)["items"]
    configured_models = model_service.models(context=context)["items"]
    people = domains(authorized, model_service.repository).list(context=context, admit=authorized["admit"], domain="personas")["items"]
    tasks, folded = _application_workflows(list(base.get("tasks") or []), model_rows)
    tasks += [row["task"] for row in _aggregate_tasks(authorized, model_service)]
    from .flags import Flag, current_snapshot, resolve
    if resolve(Flag.AI_EXTERNAL_AGENT_V1, scope=context.scope, snapshot=current_snapshot(authorized)).enabled:
        tasks += external_agents(authorized).tasks()
    from . import task_presentation
    tasks = [projected_task(row) for row in tasks]
    tasks.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    from .application_roles import ROLES
    from .team_roles import TEAM_ROLES
    assignments = {}
    for person in people:
        spec = ROLES.get(person.get("application_role"))
        if spec and person["status"] in {"active", "suspended"}:
            assignments.setdefault(spec["legacy_id"], []).append(person)
    aliases = {legacy: group[0]["id"] for legacy, group in assignments.items() if len(group) == 1}
    legacy_agents = {row["id"]: row for row in base.get("agents") or []}
    agents = [row for row in legacy_agents.values() if row["id"] not in aliases]
    for task in tasks:
        lead = task.get("lead") or {}
        if isinstance(lead, dict) and lead.get("id") in aliases:
            person = next(person for person in people if person["id"] == aliases[lead["id"]])
            task["legacy_lead"] = lead
            task["lead"] = {**lead, "id": person["id"], "display_name": person.get("title") or person.get("name")}
    for person in people:
        bound = [row for row in configured_models if row.get("persona_id") == person["id"]]
        mine = [row for row in model_rows if row.get("persona_id") == person["id"]]
        evaluation = {"sample_size": 0, "score_pct": None, "confidence": "insufficient", "label": "NEW",
                      "scope": "model_performance", "subject_kind": "model", "subject_id": None}
        observations, application_observations = [], []
        for model in bound:
            stats = model_service.evaluations(context=context, model_id=model["id"])
            observations.append({"model_id": model["id"], "model": model["model"],
                                 "connection_status": model["status"], "task_class": stats["rubric_key"], **stats})
            application_stats = model_service.evaluations(context=context, model_id=model["id"],
                                                          rubric_key="application_execution")
            application_observations.append({**application_stats, "model_id": model["id"],
                "model": model["model"], "connection_status": model["status"]})
        active_observations = [row for row in observations if row["connection_status"] == "active"]
        if len(active_observations) == 1:
            # Retired bindings remain history, but cannot erase the current
            # model's observed rating or be averaged into it.
            evaluation = {**active_observations[0], "scope": "model_performance",
                          "subject_kind": "model", "subject_id": active_observations[0]["model_id"]}
        role_spec = ROLES.get(person.get("application_role"), {})
        legacy = legacy_agents.get(role_spec.get("legacy_id")) if aliases.get(role_spec.get("legacy_id")) == person["id"] else None
        personal_tasks = [row for row in tasks if (row.get("lead") or {}).get("id") == person["id"]]
        personal_counts = task_presentation.counters(personal_tasks)
        agents.append({"id": person["id"], "display_name": person.get("title") or person.get("name"),
            "persona_profile": {key: person.get(key) for key in ("description", "style", "voice_label") if person.get(key)},
            "presentation": person.get("presentation", {}),
            "application_role": person.get("application_role", ""),
            "team_role": person.get("team_role", ""),
            "avatar_key": presentation.avatar_key(person.get("avatar_key", "")),
            "role": TEAM_ROLES.get(person.get("team_role", ""), {}).get("title") or role_spec.get("label", "Персона · роль не назначена"),
            "persona_status": person["status"],
            "status": "working" if personal_counts["active_tasks"] else "awaiting_review" if personal_counts["awaiting_review"] else "warning" if personal_counts["failed_tasks"] else "free" if person["status"] == "active" else person["status"],
            "task_counts": personal_counts,
            # Availability and occupancy are two facts, both derived from the
            # same personal_counts the line above uses — never recounted.
            "availability": person["status"],
            "occupancy": "working" if personal_counts["active_tasks"] else "free",
            "open_review": personal_counts["awaiting_review"],
            "open_decision": personal_counts["blocked"],
            "synthetic": False, "models": bound, "model_observations": observations,
            "application_observations": application_observations,
            "tasks_completed": personal_counts["completed_tasks"],
            "task_ids": [row["id"] for row in tasks if (row.get("lead") or {}).get("id") == person["id"]], "evaluation": evaluation,
            "compatibility_history": {"label": "История исходного Local-исполнителя; не оценка модели", "source": legacy} if legacy else None})
    model_outcomes = [{"task_id": row["id"], "title": row.get("display_title", row["title"]),
                       "summary": row.get("result_label"),
                       "display_status": row.get("display_status"), "display_status_label": row.get("display_status_label"),
                       "status": row["status"], "source_kind": row.get("source_kind", "real_model_response"),
                       "synthetic": row.get("synthetic") is True,
                       "application_result": row.get("application_result"), "source_job_id": row.get("source_job_id"),
                       "artifact": next((item for item in row.get("artifacts", [])
                                         if item.get("mime_type") == "image/png"), None),
                       "created_at": row["updated_at"]} for row in model_rows if row["status"] in {"succeeded", "failed", "review", "blocked", "cancelled"}]
    costs = [row["cost_usd"] for row in model_rows if isinstance(row.get("cost_usd"), (int, float))]
    # task_presentation.counters is the single tally. The attention rows are
    # then enriched with why the item is waiting and what unblocks it, which the
    # projection deliberately does not carry.
    counts = task_presentation.counters(tasks)
    attention = []
    for row in tasks:
        if not row.get("needs_attention"):
            continue
        phase = presentation.task_phase(row.get("display_status"))
        reason, action = presentation.attention_reason(phase)
        if row.get("human_review", {}).get("status") == "pending" and row.get("verification_status") == "passed":
            reason = "Результат получен, автоматическая проверка пройдена. Ожидается ваша отдельная проверка."
            action = "Откройте сохранённый результат и примите или отклоните его. Профессиональное качество автоматически не оценивается."
        elif row.get("source_kind") == "external_agent_task_v1" and row.get("display_status") == "awaiting_review":
            reason = "Результат внешнего агента ожидает проверки."
            action = "Откройте результат и сохранённые доказательства проверки."
        if row.get("enqueue_rejected"):
            # Nothing here is waiting on a decision: the server already refused
            # it. Saying "confirm the next step" would invent one.
            reason, action = presentation.refusal_reason(row.get("error_code")) or (reason, action)
        attention.append({**row, "phase": phase, "phase_label": presentation.phase_label(phase),
                          "reason": reason, "action_hint": action,
                          "since": row.get("updated_at") or row.get("created_at"),
                          "task_class_label": row.get("task_class_label")
                                              or presentation.rubric_label(row.get("task_class"))})
    server_scope = context.scope.environment in {Environment.CANARY, Environment.PRODUCTION}
    return {**base, "enabled": True, "status": "BETA" if server_scope else "IN DEVELOPMENT", "tasks": tasks, "agents": agents,
        "outcomes": model_outcomes + [row for row in base.get("outcomes") or [] if row.get("task_id") not in folded],
        "stats": {**base.get("stats", {}), **counts, "agents": len(agents),
                  "results_total": sum(len(row.get("outcomes") or []) for row in model_rows),
                  "evaluations": sum(len(row.get("evaluations") or []) for row in model_rows),
                  "artifacts": sum(row.get("evidence_count", 0) for row in tasks),
                  "paid_calls": sum(cost > 0 for cost in costs), "cost_usd": round(sum(costs), 8) if costs else None},
        "activity": [{"title": row.get("display_title", row["title"]),
                      "summary": row.get("display_title", row["title"]) + " · " + row.get("display_status_label", row["status"]),
                      "status": row["status"], "display_status": row.get("display_status"),
                      "task_id": row["id"], "time": row["updated_at"]} for row in tasks[:8]],
        "attention": attention, "scope": {"environment": context.scope.environment.value, "workspace_id": context.scope.workspace_id, "synthetic": False},
        "capabilities": {"can_run_demo": False, "can_view_models": True, "can_call_models": can_models, "can_view_system": True},
        "flags": system(authorized)["flags"],
        "limitations": (["Серверный Agent World ограничен подтверждённой сессией и собственной рабочей областью."] if server_scope
                        else ["Локальная разработка; не Canary/Production release."]) + [
                        "Оценки — независимые проверки конкретных результатов, не прибыльность и не общая квалификация модели. NEW до трёх разных входов.",
                        "Court не исполняет решения. Фактические режимы Router, Execution V2 и расписаний показаны в System; наличие worker не означает их включение."]}


def speak_persona(authorized, identity, body):
    """An explicit speech gesture; persisted Persona settings, never caller credentials."""
    if (authorized.get("read_only") or type(body) is not dict
            or set(body) != {"payload", "expected_revision", "idempotency_key"}
            or type(body["payload"]) is not dict
            or not (set(body["payload"]) == {"text"} and type(body["payload"]["text"]) is str
                    or set(body["payload"]) == {"conversation_id", "message_id"}
                    and all(type(value) is str for value in body["payload"].values()))
            or type(body["expected_revision"]) is not int
            or type(body["idempotency_key"]) is not str or not 8 <= len(body["idempotency_key"]) <= 120):
        raise ContractError("invalid_domain_request")
    from . import persona_voice
    admit = domain_admission(authorized, "personas", "speak")
    def owner_tts(context, scope):
        fresh = refresh_authority(authorized, read_only=False)
        fresh["admit"]()
        return (fresh["context"] == context and fresh["chat_scope"] == scope
                and scope.get("is_owner") is True and scope.get("uses_owner_runtime") is True)
    operation = persona_voice.speak if "text" in body["payload"] else persona_voice.speak_reply
    return operation(domains(authorized, models(authorized).repository), context=authorized["context"], admit=admit,
        persona_id=identity, **body["payload"], scope=authorized["chat_scope"],
        expected_revision=body["expected_revision"], authorize_server_tts=owner_tts)


def mutate(authorized, domain, identity, action, body):
    if authorized.get("read_only"):
        raise ContractError("agent_world_history_read_only")
    if (domain not in DOMAINS or not isinstance(body, dict) or set(body) - {"payload", "expected_revision", "idempotency_key"}
            or not isinstance(body.get("payload", {}), dict)):
        raise ContractError("invalid_domain_request")
    payload, key = body.get("payload", {}), body.get("idempotency_key", "")
    if not isinstance(key, str) or not 8 <= len(key) <= 120:
        raise ContractError("invalid_idempotency_key")
    context, service = authorized["context"], models(authorized)
    admit = domain_admission(authorized, domain, action)
    if domain == "external_agents":
        return external_agents(authorized).mutate(identity, action, payload, body.get("expected_revision"), key)
    if domain in {"automation", "router"}:
        return _mechanism_gateway().mutate(authorized, service, domain, identity, action, payload,
            expected_revision=body.get("expected_revision"), idempotency_key=key)
    if domain == "models":
        if identity == "new" and action == "bind_catalog" and set(payload) == {"registry_id"}:
            return service.bind_catalog_model(context=context, registry_id=payload["registry_id"],
                resolve_binding=lambda ctx, rid: owner_binding(authorized, rid) if ctx == context else None)
        if identity == "new" and action == "connect":
            return service.connect(context=context, payload=payload, idempotency_key=key)
        if identity == "new" and action == "bind_existing":
            return service.bind_existing_model(context=context, payload=payload, idempotency_key=key,
                    resolve_binding=lambda ctx, rid: owner_binding(authorized, rid) if ctx == context else None)
        if action in {"test", "task"}:
            from . import model_chat
            return model_chat.start(authorized, service, identity, payload, key, test=action == "test")
        if action == "disconnect" and not payload:
            return service.disconnect(context=context, model_id=identity)
        if action in {"share", "unshare"} and not payload:
            return service.set_sharing(context=context, model_id=identity, shared=action == "share")
    elif domain in {"model_tasks", "tasks"} and action == "handoff":
        if set(payload) != {"target_model_id"}:
            raise ContractError("invalid_domain_request")
        from . import result_handoff
        return result_handoff.start(authorized, service, identity, payload["target_model_id"], key)
    elif domain in {"model_tasks", "tasks"} and action == "review_result":
        from . import task_review
        result = task_review.submit(service, context=context, task_id=identity, payload=payload,
                                    expected_revision=body.get("expected_revision"), idempotency_key=key)
        # The decision is already persisted. A delivery problem must not turn
        # it into a failed review or silently replay any provider execution.
        from . import coordinator_delivery
        problems = []
        try:
            history = refresh_authority(authorized, read_only=True)
            if service._json(context, service._get(context, EntityKind.TASK, identity).checkpoint).get("source") == "real_model_task":
                enqueue_model_delivery(history, history_models(history), identity)
            elif service._json(context, service._get(context, EntityKind.TASK, identity).checkpoint).get("source") == "external_agent_task_v1":
                from . import external_agent_chat
                external_agent_chat.deliver(history, external_agents(history), identity)
            delivery_result = coordinator_delivery.related(history, identity)
            problems.extend(delivery_result["blocked"])
        except ContractError as exc:
            problems.append({"task_id": identity, "error_code": exc.code})
        except Exception:
            # The review itself committed before notification handling. Keep
            # transport/storage diagnostics non-secret and let normal recovery
            # replay only delivery, never the provider or the human decision.
            problems.append({"task_id": identity, "error_code": "review_delivery_pending"})
        return {**result, "chat_delivery": {"status": "pending" if problems else "queued_or_delivered", "problems": problems}}
    elif domain in {"model_tasks", "tasks"} and action == "cancel":
        if set(payload) - {"reason"}:
            raise ContractError("invalid_domain_request")
        from . import application_chat
        result = application_chat.cancel_dispatch(authorized, service, task_id=identity)
        if result is None:
            result = service.cancel(context=context, task_id=identity)
        from .. import worker_router
        if result.get("status") == "cancelled":
            worker_router.cancel("wj_aw_model_" + UUID(identity).hex, workspace_id=context.scope.workspace_id,
                                 user_id=authorized["source_scope"]["user_id"])
        return result
    elif domain == "experiments" and identity == "new" and action == "create":
        from . import model_chat
        return model_chat.compare(authorized, service, payload, key)
    elif domain == "publications" and identity == "new":
        allowed, publisher = social_admission(authorized), social(authorized, service.repository)
        if action == "prepare" and set(payload) == {"source_kind", "source_id"}:
            return publisher.prepare(context=context, admit=allowed, **payload)
        if action == "publish" and not set(payload) - {"source_kind", "source_id", "approved_snapshot_sha256", "text", "visibility", "confirm_permanent"}:
            return publisher.publish(context=context, admit=allowed, user_id=authorized["source_scope"]["user_id"],
                expected_revision=body.get("expected_revision"), idempotency_key=key, **payload)
    elif domain not in {"models", "model_tasks", "tasks", "experiments", "system", "publications"}:
        domain_service = domains(authorized, service.repository)
        if domain in {"routines", "calendar"} and action in {"propose", "accept"}:
            from .process_intelligence import ProcessIntelligence
            process = ProcessIntelligence(domain_service, service)
            if action == "propose":
                if set(payload) != {"source_sha256"}:
                    raise ContractError("invalid_domain_request")
                return process.propose(context=context, admit=admit, domain=domain,
                    candidate_id=identity, source_sha256=payload["source_sha256"])
            process.validate_suggestion(context=context, admit=admit, domain=domain,
                entity_id=identity, expected_revision=body.get("expected_revision"))
        if domain in {"routines", "calendar"} and action == "open_chat" and identity != "new":
            if payload:
                raise ContractError("invalid_domain_request")
            from . import followup_chat
            return followup_chat.start(authorized, domain_service, domain, identity,
                body.get("expected_revision"), key)
        if domain == "decisions" and identity == "new" and action == "propose_consensus":
            if set(payload) - {"title", "proposal", "contribution_ids", "risk", "trigger"}:
                raise ContractError("invalid_domain_request")
            return domain_service.propose_consensus(context=context, admit=admit,
                title=payload.get("title"), proposal=payload.get("proposal"), contribution_ids=payload.get("contribution_ids"),
                risk=payload.get("risk"), trigger=payload.get("trigger", "requested_review"), idempotency_key=key)
        if domain == "routines" and identity == "new" and action == "suggest_routine":
            if set(payload) - {"title", "outcome_ids", "interval_minutes"}:
                raise ContractError("invalid_domain_request")
            return domain_service.suggest_routine(context=context, admit=admit,
                title=payload.get("title"), outcome_ids=payload.get("outcome_ids"),
                interval_minutes=payload.get("interval_minutes"), idempotency_key=key)
        if identity == "new" and action == "create":
            return domain_service.create(context=context, admit=admit, domain=domain,
                                         payload=payload, idempotency_key=key)
        return domain_service.act(context=context, admit=admit, domain=domain, entity_id=identity,
            action=action, payload=payload, expected_revision=body.get("expected_revision"), idempotency_key=key)
    raise ContractError("domain_action_not_supported")


def execute_worker(job, cancelled, heartbeat):
    payload = job.get("payload") or {}
    scope = payload.get("scope") or {}
    if (str(scope.get("workspace_id") or "") != str(job.get("workspace_id") or "")
            or str(scope.get("user_id") or "") != str(job.get("user_id") or "")):
        raise ContractError("model_worker_scope_required")
    if job.get("kind") == "agent_world_external":
        authorized = worker_authority(job)
        authorized["admit"]()
        service = external_agents(authorized)
        if payload.get("phase") == "external_cleanup":
            identity = payload.get("connection_id")
            with service.repository.guard(authorized["context"], identity):
                row = service.connection(identity)
                service.onboarding(row.endpoint).cleanup_revoked(context=authorized["context"], connection_id=identity)
            return {"ok": True, "status": "cleaned"}
        if payload.get("phase"): raise ContractError("external_agent_worker_phase_invalid")
        return service.execute(payload.get("task_id"), cancelled, heartbeat)
    delivery = job.get("kind") == "agent_world_model" and payload.get("phase") == "delivery"
    followup_delivery = job.get("kind") == "agent_world_followup" and payload.get("phase") == "chat_delivery"
    coordinator_phase = job.get("kind") == "agent_world_followup" and payload.get("phase") in {"coordinator_delivery", "coordinator_continue"}
    coordination = job.get("kind") == "agent_world_followup" and payload.get("phase") in {"delegation_step", "scheduler_occurrence", "automation_watch"}
    if payload.get("phase") and not (delivery or followup_delivery or coordination or coordinator_phase):
        raise ContractError("model_worker_phase_invalid")
    authorized = worker_authority(job, read_only=delivery or payload.get("phase") == "coordinator_delivery")
    authorized["admit"]()
    if cancelled():
        raise ContractError("model_cancelled")
    heartbeat()
    if delivery:
        from .. import worker_router
        from . import model_chat
        source, source_scope = _model_source(worker_router.get(payload.get("source_worker_job_id"),
            workspace_id=authorized["context"].scope.workspace_id) or {})
        if (source_scope != scope or source.get("task_id") != payload.get("task_id")
                or job.get("worker_job_id", job.get("id")) != _delivery_job_id(payload.get("task_id"), payload.get("event_id"))):
            raise ContractError("model_delivery_scope_invalid")
        original_admit = authorized["admit"]
        def delivery_admit():
            original_admit()
            _require_delivery_claim(job)
            heartbeat()
        authorized = {**authorized, "admit": delivery_admit}
        authorized["admit"]()
        # Only this inbox consumer is writable. The history service itself has
        # no provider/queue and retains fresh read-only auth/flags admission.
        events = repository({**authorized, "read_only": False}).events
        return model_chat.deliver(authorized, history_models(authorized), task_id=payload["task_id"],
            event_id=payload["event_id"], checkpoint_sha256=payload.get("checkpoint_sha256"), events=events,
            delivery_job=job)
    if followup_delivery:
        from . import followup_chat
        return followup_chat.execute(authorized, job, cancelled, heartbeat)
    if coordinator_phase:
        from . import coordinator_delivery
        return coordinator_delivery.execute(authorized, job, cancelled, heartbeat)
    if coordination:
        from . import delegation, scheduler
        service = models(authorized)
        if payload["phase"] == "automation_watch":
            return _mechanism_gateway().execute_watch(authorized, service, job, cancelled, heartbeat)
        return (delegation if payload["phase"] == "delegation_step" else scheduler).execute(authorized, service, job, cancelled, heartbeat)
    if job["kind"] == "agent_world_followup":
        request = payload.get("request") or {}
        if request.get("automation_enabled") is not False or request.get("manual_review_required") is not True:
            raise ContractError("domain_followup_denied")
        # This queue receipt is a manual reminder, never an executable command.
        return {"ok": True, "status": "awaiting_manual_action", "item_id": request.get("id"),
                "title": request.get("title"), "automation_enabled": False, "execution_performed": False}
    service = models(authorized)
    from . import execution_v2
    managed = execution_v2.is_managed(service, authorized["context"], payload["task_id"])
    result = execution_v2.execute(authorized, service, job, cancelled, heartbeat) if managed else service.execute(context=authorized["context"], task_id=payload["task_id"], cancelled=cancelled)
    heartbeat()
    from . import model_chat, application_chat
    if not managed:
        application_chat.finish_dispatch(authorized, service, result)
    execution_v2.observe(authorized, service, payload["task_id"])
    # Only the claimed delivery phase appends a final model/application report.
    # The source executor and Chief monitor enqueue it, never race its append.
    # If interrupted even before enqueue, the existing worker's scan recovers it.
    history = refresh_authority(authorized, read_only=True)
    history_service = history_models(history)
    enqueue_model_delivery(history, history_service, payload["task_id"])
    from . import coordinator_delivery
    try:
        queued = coordinator_delivery.enqueue_continuation(history, payload["task_id"])
        continuation = {"status": "queued" if queued else "not_required"}
    except Exception as exc:
        # Saved in the existing source-job result; recovery can enqueue the
        # separate idempotent phase. Never retry the provider for this failure.
        continuation = {"status": "pending", "error_code": getattr(exc, "code", "coordinator_enqueue_unavailable")}
    return {"ok": True, "task_id": payload["task_id"], "status": result["status"], "continuation": continuation}
