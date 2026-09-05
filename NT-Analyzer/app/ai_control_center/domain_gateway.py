"""Development composition for own-workspace domains; existing authorities only.

No provider keys, caller-selected scope or new worker are introduced here.
Real NinjaTrader/Desktop access still requires the stricter Local-owner adapter.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
from uuid import UUID

from .. import account_auth, ai_budgets, permissions, preview_sandbox, runtime_env, workspaces
from . import live_gateway
from .contracts import ActorKind, ActorRef, Environment, RequestContext, TenantScope
from .flags import Flag, REGISTRY, resolve
from .states import ContractError, EntityKind

DOMAINS = frozenset({"personas", "memory", "projects", "routines", "calendar", "decisions", "court",
                     "models", "model_tasks", "experiments", "system", "tasks", "publications"})


def access(scope, *, read_only=False):
    if not isinstance(scope, dict) or not live_gateway.configured(str(scope.get("workspace_id") or "")):
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
        if not account_auth.local_session_is_active(session_id, uid):
            raise ContractError("agent_world_session_expired")
    elif user.get("is_owner") is not True:
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
    context = RequestContext(scope=TenantScope(environment=Environment.DEVELOPMENT, workspace_id=workspace["workspace_id"]),
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
            "source_scope": {"workspace_id": workspace["workspace_id"], "user_id": uid, "allow_legacy": False},
            "snapshot": live_gateway.flag_snapshot(context), "read_only": read_only}


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
    return access(scope, read_only=read_only)


def domain_admission(authorized, domain, action="read"):
    required = {"memory": Flag.AI_MEMORY_V2, "decisions": Flag.AI_CONSENSUS_V2,
                "court": Flag.AI_COURT_V1, "experiments": Flag.AI_EVALUATION_SHADOW,
                "publications": Flag.AI_SOCIAL_PUBLISH_V1}.get(domain, Flag.AI_TASK_GRAPH_V2)
    if domain == "decisions" and action == "review":
        required = Flag.AI_COURT_V1
    def admit():
        authorized["admit"]()
        current = access(authorized["chat_scope"], read_only=authorized.get("read_only", False))
        if not resolve(required, scope=current["context"].scope, snapshot=current["snapshot"]).enabled:
            raise ContractError("agent_world_domain_disabled")
    admit()
    return admit


def repository(authorized):
    authorized["admit"]()
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
    current = access(authorized["chat_scope"])
    if not current["chat_scope"]["capabilities"].get("ai_pro_models"):
        raise ContractError("model_capability_required")
    if not ai_budgets.check_budget(context.scope.workspace_id, estimate).get("ok"):
        raise ContractError("model_budget_exhausted")


def owner_binding(authorized, registry_id):
    authorized["admit"]()
    current = access(authorized["chat_scope"], read_only=authorized.get("read_only", False))
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
    from .. import worker_router
    job_id = "wj_aw_model_" + UUID(str(task_id)).hex
    payload = {"task_id": str(task_id), "scope": authorized["chat_scope"]}
    try:
        return worker_router.enqueue("agent_world_model", payload, user_id=authorized["source_scope"]["user_id"],
            workspace_id=context.scope.workspace_id, job_id=job_id, max_attempts=1, timeout_sec=180, priority=55)
    except sqlite3.IntegrityError:
        old = worker_router.get(job_id, workspace_id=context.scope.workspace_id)
        if not old or old.get("kind") != "agent_world_model" or old.get("payload") != payload:
            raise ContractError("model_queue_identity_conflict") from None
        return old


def models(authorized, repo=None):
    from .model_execution import ModelExecutor
    from .model_service import ModelService
    def bind(context, model, profile):
        if context != authorized["context"]:
            raise ContractError("model_context_required")
        return owner_binding(authorized, profile.get("existing_registry_id"))["id"]
    return ModelService(repo or repository(authorized),
        admit=lambda context, operation, estimate: _model_admit(authorized, context, operation, estimate),
        enqueue=lambda **kw: enqueue_model(authorized, **kw),
        executor=ModelExecutor(budget_limits=_private_limits, owner_binding=bind),
        allowed_origins=tuple(item.strip() for item in os.environ.get("STRATFORGE_AGENT_WORLD_MODEL_ORIGINS", "").split(",") if item.strip()))


def history_models(authorized):
    """Read-only completion projection with no executor/queue capability."""
    if authorized.get("read_only") is not True:
        raise ContractError("model_history_context_required")
    from .model_service import ModelService
    return ModelService(repository(authorized),
        admit=lambda context, operation, estimate: _model_admit(authorized, context, operation, estimate))


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
    if (job.get("status") != "running" or not job.get("worker_id")
            or current.get("status") != "running" or current.get("kind") != "agent_world_model"
            or current.get("worker_id") != job.get("worker_id")
            or current.get("attempts") != job.get("attempts")
            or current.get("payload") != job.get("payload")
            or str(current.get("user_id")) != str(job.get("user_id"))
            or current.get("cancel_requested") or float(current.get("locked_until") or 0) <= now
            or float(current.get("deadline_at") or 0) <= now):
        raise ContractError("model_delivery_claim_required")


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
            authorized = access(scope, read_only=True)
            authorized["admit"]()
            queued = enqueue_model_delivery(authorized, history_models(authorized), payload["task_id"])
            recovered += int(bool(queued and queued.get("status") == "queued"))
        except Exception:
            # A revoked/foreign scope or unavailable receipt is not permission
            # to repair domain state. Only bounded counts leave this selector.
            denied += 1
    return {"recovered": recovered, "denied": denied}


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
    return DomainService(repo, judge_runner=model_service.judge,
                         enqueue=lambda **kw: _followup(authorized, **kw))


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


def system(authorized):
    authorized["admit"]()
    flags = {flag.value: resolve(flag, scope=authorized["context"].scope, snapshot=authorized["snapshot"]).enabled for flag in REGISTRY}
    return {"enabled": True, "items": [
        {"id": "scope", "title": "Рабочая область", "status": "active", "summary": authorized["context"].scope.workspace_id},
        {"id": "storage", "title": "Хранилище", "status": "active", "summary": "Development SQLite WAL · изоляция владельца и workspace · неизменяемые revisions/evidence"},
        {"id": "worker", "title": "Исполнение", "status": "active", "summary": "Существующий Local worker и очередь NinjaTrader; повторный dispatch модели после неопределённого ответа запрещён"},
        {"id": "budgets", "title": "Бюджет", "status": "guarded", "summary": "Owner connections: существующие лимиты. Новые private paid connections: требуется ранее согласованный бюджет; free endpoints без расходов."},
        {"id": "external", "title": "Внешние действия", "status": "disabled", "summary": "Торговые ордера, Telegram mirror, автоматическое исполнение Court/routines выключены"}],
        "flags": flags, "capabilities": authorized["chat_scope"]["capabilities"], "actions": [], "limitations": []}


def list_domain(authorized, domain, *, identity=None, limit=50, cursor=None):
    if domain not in DOMAINS:
        raise ContractError("unknown_domain")
    context = authorized["context"]
    admit = domain_admission(authorized, domain)
    if domain == "system":
        return system(authorized)
    model_service = models(authorized)
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
        return model_service.task_detail(context=context, task_id=identity) if identity else model_service.tasks(context=context)
    if domain == "experiments":
        result = model_service.experiments(context=context)
        if identity:
            return next((row for row in result["items"] if row["id"] == identity), None)
        return result
    service = domains(authorized, model_service.repository)
    if identity:
        return service.get(context=context, admit=admit, domain=domain, entity_id=identity)
    result = service.list(context=context, admit=admit, domain=domain, limit=limit, cursor=cursor)
    result["actions"] = ["create"] if result["capabilities"].get("can_create") else []
    if domain in {"decisions", "routines"}:
        result["evidence_candidates"] = service.evidence_candidates(context=context, admit=admit)
        result["actions"] += ["propose_consensus" if domain == "decisions" else "suggest_routine"]
        kinds = {"contribution_candidates": ("contribution", "accepted"), "outcome_candidates": ("outcome", "verified")}
        for field, (kind, status) in kinds.items():
            result[field] = list({row["source_id"]: {"id": row["source_id"], "title": row["title"]}
                for row in result["evidence_candidates"]["items"] if row["source_kind"] == kind and row["source_status"] == status}.values())
    return result


def history_projection(authorized, result, *, domain=""):
    """Hide unavailable mutations, not existing evidence, after entitlement expiry."""
    caps = authorized["chat_scope"].get("capabilities") or {}
    blocked = (not caps.get("ai_lab") or authorized["chat_scope"].get("membership_role") != "owner"
               or (domain in {"models", "model_tasks", "tasks", "experiments"} and
                   (not caps.get("ai_pro_models") or not ai_budgets.check_budget(authorized["context"].scope.workspace_id, 0.0).get("ok"))))
    if not blocked:
        return result
    def project(value):
        if isinstance(value, list):
            return [project(item) for item in value]
        if not isinstance(value, dict):
            return value
        return {key: [] if key in {"actions", "allowed_actions", "owner_bindings"} else
                False if key.startswith("can_") and key not in {"can_view_models", "can_view_system"} else project(item)
                for key, item in value.items()}
    return project(result)


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
    tasks.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    from .application_roles import ROLES
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
        evaluation = {"sample_size": 0, "score_pct": None, "confidence": "insufficient", "label": "NEW"}
        observations = []
        for model in bound:
            stats = model_service.evaluations(context=context, model_id=model["id"])
            observations.append({"model_id": model["id"], "model": model["model"],
                                 "connection_status": model["status"], "task_class": stats["rubric_key"], **stats})
        active_observations = [row for row in observations if row["connection_status"] == "active"]
        if len(active_observations) == 1:
            # Retired bindings remain history, but cannot erase the current
            # model's observed rating or be averaged into it.
            evaluation = active_observations[0]
        role_spec = ROLES.get(person.get("application_role"), {})
        legacy = legacy_agents.get(role_spec.get("legacy_id")) if aliases.get(role_spec.get("legacy_id")) == person["id"] else None
        agents.append({"id": person["id"], "display_name": person.get("title") or person.get("name"),
            "application_role": person.get("application_role", ""),
            "role": role_spec.get("label", "Персона · роль не назначена"), "status": "working" if any(row["status"] in {"ready", "running", "waiting"} for row in mine) else person["status"],
            "synthetic": False, "models": bound, "model_observations": observations,
            "tasks_completed": sum(row["status"] == "succeeded" for row in mine),
            "task_ids": [row["id"] for row in tasks if (row.get("lead") or {}).get("id") == person["id"]], "evaluation": evaluation,
            "compatibility_history": {"label": "История исходного Local-исполнителя; не оценка модели", "source": legacy} if legacy else None})
    model_outcomes = [{"task_id": row["id"], "title": row["title"], "summary": row.get("result_text") or row.get("summary"),
                       "status": row["status"], "source_kind": "real_model_response", "synthetic": False,
                       "created_at": row["updated_at"]} for row in model_rows if row["status"] in {"succeeded", "failed", "review", "blocked", "cancelled"}]
    costs = [row["cost_usd"] for row in model_rows if isinstance(row.get("cost_usd"), (int, float))]
    completed = sum(row["status"] == "succeeded" for row in tasks)
    active = sum(row["status"] in {"queued", "ready", "running", "waiting"} for row in tasks)
    attention = [row for row in tasks if row["status"] in {"review", "blocked", "failed"}]
    return {**base, "enabled": True, "status": "IN DEVELOPMENT", "tasks": tasks, "agents": agents,
        "outcomes": model_outcomes + [row for row in base.get("outcomes") or [] if row.get("task_id") not in folded],
        "stats": {**base.get("stats", {}), "tasks_total": len(tasks), "active_tasks": active, "running": active,
                  "completed": completed, "completed_tasks": completed, "agents": len(agents), "attention": len(attention),
                  "failed": len(attention), "evaluations": sum(bool(row.get("evaluation_id")) for row in model_rows),
                  "artifacts": sum(row.get("evidence_count", 0) for row in tasks),
                  "paid_calls": sum(cost > 0 for cost in costs), "cost_usd": round(sum(costs), 8) if costs else None},
        "activity": [{"title": row["title"], "summary": row["title"] + " · " + row["status"], "task_id": row["id"], "time": row["updated_at"]} for row in tasks[:8]],
        "attention": attention, "scope": {"environment": "development", "workspace_id": context.scope.workspace_id, "synthetic": False},
        "capabilities": {"can_run_demo": False, "can_view_models": True, "can_call_models": can_models, "can_view_system": True},
        "flags": system(authorized)["flags"],
        "limitations": ["Локальная разработка; не Canary/Production release.",
                        "Оценки — независимые проверки конкретных результатов, не прибыльность и не общая квалификация модели. NEW до трёх разных входов.",
                        "Court не исполняет решения. Router/Execution V2 и автоматический запуск routines выключены."]}


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
    if domain == "models":
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
    delivery = job.get("kind") == "agent_world_model" and payload.get("phase") == "delivery"
    if payload.get("phase") and not delivery:
        raise ContractError("model_worker_phase_invalid")
    authorized = access(scope, read_only=True) if delivery else access(scope)
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
            event_id=payload["event_id"], checkpoint_sha256=payload.get("checkpoint_sha256"), events=events)
    if job["kind"] == "agent_world_followup":
        request = payload.get("request") or {}
        if request.get("automation_enabled") is not False or request.get("manual_review_required") is not True:
            raise ContractError("domain_followup_denied")
        # This queue receipt is a manual reminder, never an executable command.
        return {"ok": True, "status": "awaiting_manual_action", "item_id": request.get("id"),
                "title": request.get("title"), "automation_enabled": False, "execution_performed": False}
    service = models(authorized)
    result = service.execute(context=authorized["context"], task_id=payload["task_id"], cancelled=cancelled)
    heartbeat()
    from . import model_chat, application_chat
    application_chat.finish_dispatch(authorized, service, result)
    # Only the claimed delivery phase appends a final model/application report.
    # The source executor and Chief monitor enqueue it, never race its append.
    # If interrupted even before enqueue, the existing worker's scan recovers it.
    history = access(scope, read_only=True)
    history_service = history_models(history)
    enqueue_model_delivery(history, history_service, payload["task_id"])
    return {"ok": True, "task_id": payload["task_id"], "status": result["status"]}
