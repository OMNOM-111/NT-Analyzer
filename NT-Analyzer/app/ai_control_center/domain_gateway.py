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
from . import presentation
from .states import ContractError, EntityKind

DOMAINS = frozenset({"personas", "memory", "projects", "routines", "calendar", "decisions", "court",
                     "models", "model_tasks", "experiments", "system", "tasks", "publications", "automation", "router"})


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
            "refresh": lambda **kw: access(normalized, read_only=kw.get("read_only", read_only)),
            "source_scope": {"workspace_id": workspace["workspace_id"], "user_id": uid, "allow_legacy": False},
            "snapshot": live_gateway.flag_snapshot(context), "read_only": read_only}


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
    if not current["chat_scope"]["capabilities"].get("ai_pro_models"):
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
    from .. import worker_router
    from . import execution_v2
    service = models(authorized)
    managed = execution_v2.enabled(authorized) or execution_v2.is_managed(service, context, task_id)
    if managed:
        execution_v2.prepare(authorized, service, task_id)
    job_id = "wj_aw_model_" + UUID(str(task_id)).hex
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


def models(authorized, repo=None):
    from .model_execution import ModelExecutor
    from .model_service import ModelService
    def bind(context, model, profile):
        if context != authorized["context"]:
            raise ContractError("model_context_required")
        return owner_binding(authorized, profile.get("existing_registry_id"))["id"]
    service = ModelService(repo or repository(authorized),
        mechanism_authorized=authorized,
        chat_scope=authorized["chat_scope"],
        admit=lambda context, operation, estimate: _model_admit(authorized, context, operation, estimate),
        enqueue=lambda **kw: enqueue_model(authorized, **kw),
        executor=ModelExecutor(budget_limits=_private_limits, owner_binding=bind),
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
    if payload.get("phase") == "delivery":
        source = worker_router.get(payload.get("source_worker_job_id"), workspace_id=str(job.get("workspace_id") or "")) or {}
        source_payload, scope = _model_source(source)
        if scope != payload.get("scope"):
            raise ContractError("model_delivery_scope_invalid")
    else:
        source_payload, scope = payload, payload.get("scope") or {}
    coordination = source_payload.get("phase") in {"delegation_step", "scheduler_occurrence", "automation_watch"}
    controller_id = source_payload.get("controller_id") if coordination else source_payload.get("automation_controller_id")
    reference = source_payload.get("grant_ref") if coordination else source_payload.get("automation_grant_ref")
    if bool(controller_id) != bool(reference):
        raise ContractError("automation_worker_authority_missing")
    if not controller_id:
        if coordination:
            raise ContractError("automation_worker_authority_missing")
        return access(scope, read_only=read_only)
    authorized = automation_authority.access(scope, controller_id=controller_id, grant_ref=reference, read_only=read_only)
    if not coordination:
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
            authorized = worker_authority(row, read_only=True)
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
    flags = {flag.value: resolve(flag, scope=authorized["context"].scope, snapshot=authorized["snapshot"]).enabled for flag in REGISTRY}
    return {"enabled": True, "items": [
        _component("scope", "Рабочая область", authorized["context"].scope.workspace_id,
                   implemented=True, enabled=True, mode="development", available=True),
        _component("storage", "Хранилище",
                   "Изоляция владельца и workspace · неизменяемые revisions/evidence",
                   implemented=True, enabled=True, mode="Development SQLite WAL", available=True,
                   note="PostgreSQL/RLS адаптер Agent World не реализован; этот путь не обслуживает Canary/Production."),
        _component("worker", "Исполнение",
                   "Повторный dispatch модели после неопределённого ответа запрещён",
                   implemented=True, enabled=True,
                   mode="существующий Local worker и очередь NinjaTrader", available=True,
                   note="Работает исходный исполнитель. Это не готовность Execution V2."),
        _component("execution_v2", "Execution Engine V2 · Deviation Control",
                   "Новый движок исполнения с контролем отклонений",
                   implemented=False, enabled=False,
                   mode="не обслуживает запросы", available=False,
                   note="Не реализован. Зелёный статус соседнего исполнителя его не заменяет."),
        _component("router", "Маршрутизация ваших подключений (Router)",
                   "Выбор вашей модели по классу задачи и наблюдаемой точности",
                   implemented=False, enabled=False,
                   mode="модель для каждого задания выбираете явно", available=False,
                   note="Наблюдаемые оценки AI Центра не влияют ни на один выбор. Отдельная маршрутизация штатных ролей AI Lab — другой механизм и другие данные."),
        _component("schedule", "Автономное расписание",
                   "Запуск принятых рутин по наступлении срока",
                   implemented=False, enabled=False,
                   mode="только ручной разбор", available=False,
                   note="Принятая рутина не включает фоновое исполнение."),
        _component("budgets", "Бюджет",
                   "Owner connections: существующие лимиты. Новые private paid connections: требуется ранее согласованный бюджет; free endpoints без расходов.",
                   implemented=True, enabled=True,
                   mode="существующие лимиты владельца", available=True),
        _component("external", "Внешние действия",
                   "Торговые ордера, Telegram mirror, автоматическое исполнение Court/routines",
                   implemented=True, enabled=False, mode="выключены", available=False)],
        "flags": flags, "capabilities": authorized["chat_scope"]["capabilities"], "actions": [], "limitations": []}


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
    """Mechanism domains ship with their own module; fail closed without it.

    Absence is a deployment fact, not a caller error: answer with a stable
    contract code rather than an unhandled import failure, and never fall back
    to another domain's handler.
    """
    try:
        from . import mechanism_gateway
    except ImportError:
        raise ContractError("mechanism_domain_unavailable") from None
    return mechanism_gateway


def list_domain(authorized, domain, *, identity=None, limit=50, cursor=None):
    if domain not in DOMAINS:
        raise ContractError("unknown_domain")
    context = authorized["context"]
    admit = domain_admission(authorized, domain)
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
        return model_service.task_detail(context=context, task_id=identity) if identity else model_service.tasks(context=context)
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
    if domain in {"routines", "calendar"}:
        result["items"] = [_followup_projection(authorized, service, domain, row) for row in result["items"]]
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
                False if key.startswith("can_") and key not in {"can_view_models", "can_view_system"} else project(item)
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
    from . import task_presentation
    tasks = [row if row.get("display_status") else task_presentation.project(row) for row in tasks]
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
            evaluation = active_observations[0]
        role_spec = ROLES.get(person.get("application_role"), {})
        legacy = legacy_agents.get(role_spec.get("legacy_id")) if aliases.get(role_spec.get("legacy_id")) == person["id"] else None
        personal_tasks = [row for row in tasks if (row.get("lead") or {}).get("id") == person["id"]]
        personal_counts = task_presentation.counters(personal_tasks)
        agents.append({"id": person["id"], "display_name": person.get("title") or person.get("name"),
            "avatar_key": role_spec.get("legacy_id", ""),
            "persona_profile": {key: person.get(key) for key in ("description", "style", "voice_label") if person.get(key)},
            "application_role": person.get("application_role", ""),
            "avatar_key": presentation.avatar_key(person.get("avatar_key", "")),
            "role": role_spec.get("label", "Персона · роль не назначена"),
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
                       "status": row["status"], "source_kind": "real_model_response", "synthetic": False,
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
        attention.append({**row, "phase": phase, "phase_label": presentation.phase_label(phase),
                          "reason": reason, "action_hint": action,
                          "since": row.get("updated_at") or row.get("created_at"),
                          "task_class_label": row.get("task_class_label")
                                              or presentation.rubric_label(row.get("task_class"))})
    return {**base, "enabled": True, "status": "IN DEVELOPMENT", "tasks": tasks, "agents": agents,
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
    if domain in {"automation", "router"}:
        return _mechanism_gateway().mutate(authorized, service, domain, identity, action, payload,
            expected_revision=body.get("expected_revision"), idempotency_key=key)
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
    elif domain in {"model_tasks", "tasks"} and action == "handoff":
        if set(payload) != {"target_model_id"}:
            raise ContractError("invalid_domain_request")
        from . import result_handoff
        return result_handoff.start(authorized, service, identity, payload["target_model_id"], key)
    elif domain in {"model_tasks", "tasks"} and action == "review_result":
        from . import task_review
        return task_review.submit(service, context=context, task_id=identity, payload=payload,
                                  expected_revision=body.get("expected_revision"), idempotency_key=key)
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
    delivery = job.get("kind") == "agent_world_model" and payload.get("phase") == "delivery"
    followup_delivery = job.get("kind") == "agent_world_followup" and payload.get("phase") == "chat_delivery"
    coordination = job.get("kind") == "agent_world_followup" and payload.get("phase") in {"delegation_step", "scheduler_occurrence", "automation_watch"}
    if payload.get("phase") and not (delivery or followup_delivery or coordination):
        raise ContractError("model_worker_phase_invalid")
    authorized = worker_authority(job, read_only=delivery)
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
    if followup_delivery:
        from . import followup_chat
        return followup_chat.execute(authorized, job, cancelled, heartbeat)
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
    return {"ok": True, "task_id": payload["task_id"], "status": result["status"]}
