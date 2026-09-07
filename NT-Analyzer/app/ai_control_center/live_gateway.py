"""Explicit Local-owner composition over existing auth, jobs, budgets and chat.

This is not Preview and never changes its identity/data root. The one trusted
server allowlist opts exact Development workspaces in; flags alone grant no
authority. The normal router remains unchanged while this opt-in is absent.
"""
from __future__ import annotations

import os
import hashlib
import json
import re
import threading
from uuid import UUID

from .. import account_auth, ai_budgets, audit_events, permissions, preview_sandbox, runtime_env, workspaces
from .contracts import ActorKind, ActorRef, Environment, RequestContext, TenantScope
from .flags import Flag, FlagRule, FlagSnapshot, REGISTRY, resolve
from . import presentation
from .states import ContractError

PREFIX = "/api/ai-control-center/"
WORKSPACES_ENV = "STRATFORGE_AGENT_WORLD_LOCAL_WORKSPACES"
MECHANISMS_ENV = "STRATFORGE_AGENT_WORLD_LOCAL_MECHANISMS"
_MECHANISM_FLAGS = frozenset({Flag.AI_ROUTER_SHADOW_V2, Flag.AI_ROUTER_V2,
    Flag.AI_EXECUTION_V2, Flag.AI_DELEGATION_V2, Flag.AI_SCHEDULER_V1})
_FLAGS = (Flag.AI_CONTROL_CENTER_READ_MODEL, Flag.AI_COMMAND_CENTER_UI, Flag.AI_TASK_GRAPH_V2,
          Flag.AI_EVALUATION_SHADOW, Flag.AI_MEMORY_V2, Flag.AI_CONSENSUS_V2, Flag.AI_COURT_V1, Flag.AI_SOCIAL_PUBLISH_V1)
_LOCK = threading.RLock()
_SNAPSHOTS: dict[tuple, FlagSnapshot] = {}
BACKTEST_EXAMPLE = "Толик, запусти бэктест SampleMACrossOver на MNQ 09-26, 5m, с 2026-08-24 по 2026-08-29, Fast=10, Slow=25"
CHART_EXAMPLE = "Иван, сделай снимок рабочего стола MNQ 09-26, 5m"


def configured(workspace_id: str = "") -> bool:
    if not runtime_env.is_development() or preview_sandbox.enabled():
        return False
    entries = [item.strip() for item in os.environ.get(WORKSPACES_ENV, "").split(",") if item.strip()]
    # An invalid or wildcard configuration fails closed rather than becoming a
    # process-wide grant. The registry still requires an exact workspace rule.
    if not entries or any(not re.fullmatch(r"ws_[A-Za-z0-9_-]{3,93}", item) for item in entries):
        return False
    return workspace_id in entries if workspace_id else True


def _fresh(scope: dict) -> tuple[RequestContext, dict]:
    if not isinstance(scope, dict) or not configured(str(scope.get("workspace_id") or "")):
        raise ContractError("agent_world_local_disabled")
    if scope.get("is_owner") is not True or scope.get("uses_owner_runtime") is not True:
        raise ContractError("agent_world_local_owner_required")
    try:
        uid = int(scope.get("user_id") or 0)
        identity = UUID(str(scope.get("user_uuid") or ""))
    except (ValueError, TypeError):
        raise ContractError("agent_world_identity_required") from None
    user = account_auth.find_active_user(uid)
    if (not user or user.get("is_owner") is not True or user.get("is_preview_user")
            or user.get("is_service_account") or str(user.get("user_uuid") or user.get("id") or "") != str(identity)):
        raise ContractError("agent_world_local_owner_required")
    workspace = workspaces.require_workspace_writer(uid, workspace_id=scope["workspace_id"])
    membership = workspace.get("membership") or {}
    if (workspace.get("uses_owner_runtime") is not True or workspace.get("status") != "active"
            or int(workspace.get("owner_user_id") or 0) != uid or membership.get("role") != "owner"):
        raise ContractError("agent_world_owner_workspace_required")
    perm = permissions.resolve_for_user_id(uid, user)
    raw = {**perm, "user": user, "user_id": uid, "_request_method": "POST"}
    for path in (PREFIX + "backtests", "/api/jobs"):
        permissions.enforce(path, raw)
    if not (perm.get("capabilities") or {}).get("ai_lab") or not (perm.get("capabilities") or {}).get("backtesting"):
        raise ContractError("agent_world_capability_required")
    normalized = {"user_id": uid, "user_uuid": str(identity), "workspace_id": workspace["workspace_id"],
                  "workspace_kind": workspace["kind"], "uses_owner_runtime": True, "is_owner": True,
                  "membership_role": "owner", "display_name": str(scope.get("display_name") or ""),
                  "capabilities": perm["capabilities"]}
    context = RequestContext(scope=TenantScope(environment=Environment.DEVELOPMENT, workspace_id=workspace["workspace_id"]),
                             user_uuid=identity, actor=ActorRef(kind=ActorKind.HUMAN, actor_id=identity))
    return context, normalized


def flag_snapshot(context: RequestContext) -> FlagSnapshot:
    if not configured(context.scope.workspace_id):
        raise ContractError("agent_world_local_disabled")
    configured_mechanisms = mechanism_configuration(context.scope.workspace_id)
    extra = tuple(flag for flag in Flag if flag.value in configured_mechanisms["flags"])
    enabled_flags = (*_FLAGS, *extra)
    revision = "owner-domains-v1" if not extra else "local-mechanisms-" + hashlib.sha256(
        json.dumps([flag.value for flag in enabled_flags]).encode()).hexdigest()[:16]
    # Configuration changes, including removal, must invalidate an old opt-in.
    key = (str(runtime_env.data_root()), context.scope, context.user_uuid, revision)
    with _LOCK:
        if key not in _SNAPSHOTS:
            reference = audit_events.record(str(context.user_uuid), "agent_world.local_flags_activated", "agent_world",
                                            workspace_id=context.scope.workspace_id, resource_id=revision,
                                            details={"flags": [flag.value for flag in enabled_flags], "synthetic": False})
            if len(_SNAPSHOTS) >= 256:
                _SNAPSHOTS.clear()
            _SNAPSHOTS[key] = FlagSnapshot(revision=revision, audit_ref=UUID(reference.removeprefix("aud_")),
                                          rules=tuple(FlagRule(environment=Environment.DEVELOPMENT, flag=flag, enabled=True,
                                                               workspace_id=workspace)
                                                      for flag in enabled_flags for workspace in (None, context.scope.workspace_id)))
        return _SNAPSHOTS[key]


def mechanism_configuration(workspace_id):
    """Trusted server opt-ins only; one exact Development/workspace registry.

    Format: {"environment":"development","flags":{"AI_EXECUTION_V2":["ws_example"]}}.
    No wildcard, inherited environment, implicit dependency activation or UI
    mutation exists. An invalid document disables every *new* mechanism, while
    leaving the already approved Local functionality untouched.
    """
    empty = {"status": "disabled", "flags": [], "reason_code": "not_configured"}
    raw = os.environ.get(MECHANISMS_ENV, "").strip()
    if not raw or not configured(workspace_id):
        return empty
    def _reject_duplicate_keys(pairs):
        # json.loads keeps the last value for a repeated key. A configuration
        # that says both {"AI_EXECUTION_V2": ["*"]} and a narrow list must not
        # quietly resolve to whichever came last; an ambiguous document is
        # invalid and disables every new mechanism.
        seen = {}
        for key, item in pairs:
            if key in seen:
                raise ValueError("duplicate key in mechanism configuration")
            seen[key] = item
        return seen

    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
        if (type(value) is not dict or set(value) != {"environment", "flags"}
                or value["environment"] != Environment.DEVELOPMENT.value
                or type(value["flags"]) is not dict):
            raise ValueError()
        configured_names = {flag.value for flag in _MECHANISM_FLAGS}
        for name, ids in value["flags"].items():
            if (name not in configured_names or type(ids) is not list or not ids
                    or len(ids) != len(set(ids)) or any(type(item) is not str
                        or not re.fullmatch(r"ws_[A-Za-z0-9_-]{3,93}", item) for item in ids)):
                raise ValueError()
        names = sorted(name for name, ids in value["flags"].items() if workspace_id in ids)
        return {"status": "configured" if names else "disabled", "flags": names,
                "reason_code": "explicit_server_opt_in" if names else "workspace_not_opted_in"}
    except (ValueError, TypeError):
        return {"status": "invalid", "flags": [], "reason_code": "invalid_server_configuration"}


def access(scope: dict) -> dict:
    context, normalized = _fresh(scope)
    snapshot = flag_snapshot(context)

    def admit():
        current, _ = _fresh(normalized)
        if current != context or not resolve(Flag.AI_TASK_GRAPH_V2, scope=context.scope, snapshot=flag_snapshot(context)).enabled:
            raise ContractError("agent_world_context_changed")
        if not ai_budgets.check_budget(context.scope.workspace_id, 0.0).get("ok"):
            raise ContractError("agent_world_budget_denied")

    admit()
    return {"context": context, "source_scope": {"workspace_id": context.scope.workspace_id,
                                                 "user_id": normalized["user_id"], "allow_legacy": False},
            "chat_scope": normalized, "admit": admit, "snapshot": snapshot}


def from_handler(handler) -> dict:
    raw = handler._remote_context or {}
    # The established Local owner entry is retained. Browser sessions still
    # traverse the normal auth/device gates, not a new synthetic/master code.
    if (raw.get("is_owner") is not True or raw.get("role") == "read_only"
            or (raw.get("source") != "local" and raw.get("device_confirmation_state") != "active")):
        raise ContractError("agent_world_confirmed_owner_required")
    return access(handler._ai_conversation_scope())


def navigation(handler) -> dict:
    enabled = False
    if configured():
        try:
            from . import domain_gateway
            authorized = domain_gateway.from_handler(handler, read_only=True)
            enabled = resolve(Flag.AI_COMMAND_CENTER_UI, scope=authorized["context"].scope, snapshot=authorized["snapshot"]).enabled
        except (ContractError, account_auth.AccountAuthError, workspaces.WorkspaceError, permissions.PermissionError):
            pass
    return {"enabled": enabled, "synthetic": False, "status": "IN DEVELOPMENT", "url": "/ui/ai-command-center.html"}


def service_args(authorized: dict) -> dict:
    return {key: authorized[key] for key in ("context", "source_scope", "chat_scope", "admit")}


def overview(authorized: dict) -> dict:
    from .live_backtests import LiveBacktestService
    from . import live_charts
    service = LiveBacktestService()
    payload = service.overview(**service_args(authorized))
    tasks, agents, stats = payload["work"]["items"], payload["agents"]["items"], payload["stats"]
    chart_details = live_charts.details(authorized)
    chart_tasks = [item["task"] for item in chart_details]
    outcomes = []
    for task in tasks[:8]:
        if task["source_status"] in {"done", "failed", "cancelled"}:
            detail = service.get(**service_args(authorized), job_id=task["source_job_id"])
            outcomes.append({"task_id": task["id"], "title": task["title"], "summary": detail["result_text"],
                             "status": task["status"], "source_kind": "ninjatrader_report", "synthetic": False,
                             "source_job_id": task["source_job_id"], "created_at": task["updated_at"]})
    for item in chart_details:
        task = item["task"]
        if item["artifacts"]:
            outcomes.append({"task_id": task["id"], "title": task["title"], "summary": item["result_text"],
                             "status": task["status"], "source_kind": "desktop_chart", "synthetic": False,
                             "artifact": item["artifacts"][0], "created_at": task["updated_at"]})
    tasks = sorted(tasks + chart_tasks, key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    stats = {**stats, "tasks_total": len(tasks), "completed": sum(task["status"] == "succeeded" for task in tasks),
             "running": sum(task["status"] in {"ready", "queued", "running"} for task in tasks),
             "failed": sum(task["status"] in {"failed", "blocked", "review"} for task in tasks),
             "artifacts": sum(task.get("evidence_count", 0) for task in tasks)}
    chart_busy = any(task["status"] == "queued" for task in chart_tasks)
    # This compatibility row is rendered by the same card as a domain agent, so
    # it has to answer the same two questions: switched on, and busy right now.
    agents.append({**live_charts.PERSONA, "status": "working" if chart_busy else "idle",
                   "availability": "active", "occupancy": "working" if chart_busy else "free",
                   "open_review": sum(presentation.task_phase(task["status"]) == presentation.PHASE_AWAITING_REVIEW
                                      for task in chart_tasks),
                   "open_decision": sum(presentation.task_phase(task["status"]) == presentation.PHASE_AWAITING_DECISION
                                        for task in chart_tasks),
                   "tasks_completed": sum(task["status"] == "succeeded" for task in chart_tasks), "task_ids": [task["id"] for task in chart_tasks],
                   "evaluation": {"sample_size": 0, "score_pct": None, "confidence": "insufficient", "mode": "desktop_canvas_receipt",
                                  "model_quality_assessed": False, "routing_effect": "none"}})
    outcomes.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return {**payload, "enabled": True, "status": "IN DEVELOPMENT", "tasks": tasks, "agents": agents, "outcomes": outcomes,
            "stats": {**stats, "active_tasks": stats["running"], "completed_tasks": stats["completed"], "agents": len(agents), "attention": stats["failed"]},
            "scope": {"environment": "development", "workspace_id": authorized["context"].scope.workspace_id, "synthetic": False},
            "activity": [{"title": task["title"],
                          "summary": task["title"] + " · " + presentation.phase_label(presentation.task_phase(task["status"])),
                          "time": task["updated_at"], "task_id": task["id"]} for task in tasks[:8]],
            "attention": [{"task_id": task["id"], "title": task["title"], "status": task["status"], "summary": task.get("summary", "")}
                          for task in tasks if task["status"] in {"failed", "blocked", "review"}],
            "capabilities": {"can_run_demo": False, "can_view_models": False, "can_view_system": True},
            "flags": {flag.value: resolve(flag, scope=authorized["context"].scope, snapshot=authorized["snapshot"]).enabled for flag in REGISTRY},
            "limitations": ["Реальные исторические бэктесты выполняет существующий NinjaTrader. Торговые ордера не отправляются.",
                            "Успешное выполнение не означает прибыль. В отчёте сохраняются убыточные результаты и ограничения риск-профиля.",
                            "Показываются только поручения этого владельца из SF Chat/AI Центра; ручные и synthetic запуски не смешиваются.",
                            "Этот совместимый срез показывает реальные поручения NinjaTrader/Рабочего стола. Модели и их оценки доступны в доменах AI Центра. Router/Execution V2, Canary/Production выключены."]}


def parse_backtest(text: str) -> dict:
    strategy = re.search(r"(?:бэктест(?:ирование)?|backtest)\s+([A-Za-z_][A-Za-z0-9_]{2,126})\b", text, re.I)
    instrument = re.search(r"\b([A-Z][A-Z0-9]{0,9})\s+(\d{2}-\d{2})\b", text)
    timeframe = re.search(r"\b(\d{1,4})\s*(?:m|мин(?:ут(?:ы)?)?)\b", text, re.I)
    dates = re.search(r"\b(?:с|from)\s+(\d{4}-\d\d-\d\d)\s+(?:по|to)\s+(\d{4}-\d\d-\d\d)\b", text, re.I)
    if not all((strategy, instrument, timeframe, dates)):
        raise ContractError("live_backtest_explicit_spec_required")
    parameters = {}
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-+]?\d+(?:\.\d+)?|true|false)\b", text, re.I):
        key, value = match.groups()
        if key in parameters:
            raise ContractError("live_backtest_duplicate_parameter")
        parameters[key] = value.lower() == "true" if value.lower() in {"true", "false"} else float(value) if "." in value else int(value)
    if len(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\s*=", text)) != len(parameters):
        raise ContractError("live_backtest_invalid_parameters")
    return {"class_name": strategy[1], "instrument": instrument[1] + " " + instrument[2],
            "bars_period_type": "Minute", "bars_period_value": int(timeframe[1]),
            "from_utc": dates[1] + "T00:00:00Z", "to_utc": dates[2] + "T00:00:00Z", "parameters": parameters,
            "session_template": "CME US Index Futures RTH", "commission_template": "NinjaTrader Brokerage Free", "slippage_ticks": 1}


def try_chat(message: str, *, scope: dict | None, conversation_id: str, request_id: str, source: str) -> dict | None:
    if source != "app" or not configured(str((scope or {}).get("workspace_id") or "")):
        return None
    from . import model_chat, application_chat
    model_reply = model_chat.try_chat(message, scope=scope, conversation_id=conversation_id, request_id=request_id, source=source)
    if model_reply is not None:
        return model_reply
    application_reply = application_chat.try_chat(message, scope=scope, conversation_id=conversation_id,
                                                   request_id=request_id, source=source)
    if application_reply is not None:
        return application_reply
    backtest = bool(re.search(r"(?:запусти|запустить|выполни|проведи|run)\b.*(?:бэктест|backtest)", message, re.I))
    chart = bool(re.search(r"(?:сделай|создай|покажи)\b.*(?:снимок|скриншот).*рабоч", message, re.I))
    if not backtest and not chart:
        return None
    authorized = access(scope)
    from ..ai_lab import chief_agent
    conversation_id = chief_agent._safe_conversation_id(conversation_id)

    def execute():
        envelope = {"request_id": request_id, "conversation_id": conversation_id, "scope": authorized["chat_scope"],
                    "agent_id": "tolik" if backtest else "ivan", "agent_name": "Толик" if backtest else "Иван",
                    "synthetic": False, "source_kind": "ninjatrader_report" if backtest else "desktop_chart"}
        try:
            if backtest:
                from .live_backtests import LiveBacktestService
                result = LiveBacktestService().start(**service_args(authorized), spec=parse_backtest(message),
                                                    idempotency_key=request_id, conversation_id=conversation_id)
                envelope.update(task_id=result["task_id"], source_job_id=result["job_id"], status="queued",
                                text=("Исторический бэктест принят существующей очередью NinjaTrader: " + result["job_id"]
                                      + ". Это ещё не результат. После завершения проверю отчёт и вернусь сюда.\n"
                                      + "Период UTC, правая граница исключается; CME US Index Futures RTH; High fill, 1 tick slippage; "
                                      + "запрошен NinjaTrader Brokerage Free (фактическая комиссия будет в отчёте). Торговые ордера не отправляются."))
            else:
                from . import live_charts
                envelope.update(live_charts.start(message=message, authorized=authorized, conversation_id=conversation_id, request_id=request_id))
        except ContractError as exc:
            envelope.update(status="blocked", text="Поручение не запущено: " + str(exc) + ".\nУкажите стратегию из каталога и доступный период явно. Пример:\n" + (BACKTEST_EXAMPLE if backtest else CHART_EXAMPLE))
        return envelope

    return chief_agent.run_agent_world_live_request(message=message, request_id=request_id, conversation_id=conversation_id,
                                                    scope=authorized["chat_scope"], execute=execute)


def poll_once() -> dict:
    if not configured():
        return {"enabled": False}
    from .live_backtests import LiveBacktestService
    from . import live_charts
    from ..ai_lab import chief_agent
    deliveries, errors = 0, []
    for scope in workspaces.runtime_monitor_scopes():
        if not configured(str(scope.get("workspace_id") or "")):
            continue
        try:
            user = account_auth.find_active_user(scope.get("user_id")) or {}
            authorized = access({**scope, "user_uuid": user.get("user_uuid") or user.get("id")})
            result = LiveBacktestService().reconcile(**service_args(authorized), publish=chief_agent.report_agent_world_live_update)
            deliveries += result["delivered"]
            errors.extend(result["errors"])
            deliveries += live_charts.reconcile(authorized)["delivered"]
            from . import application_chat, domain_gateway
            domain = domain_gateway.access(authorized["chat_scope"])
            service = domain_gateway.models(domain)
            application = application_chat.reconcile(domain, service)
            deliveries += len(application["completed"])
            errors.extend(application["errors"])
        except (ContractError, workspaces.WorkspaceError, account_auth.AccountAuthError, permissions.PermissionError):
            errors.append({"code": "agent_world_local_admission_denied"})
    return {"enabled": True, "delivered": deliveries, "errors": errors}
