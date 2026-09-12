"""Bounded Coordinator phases on the existing worker and event inbox.

Provider execution, graph progression and Chat delivery are distinct jobs.
A failed continuation never retries an already persisted provider response.
"""
from __future__ import annotations

import sqlite3
from uuid import UUID

from .. import worker_router
from . import coordinator, delegation
from .states import ContractError

DELIVERY = "coordinator_delivery"
CONTINUE = "coordinator_continue"


def _identity(phase, task_id, event_id=None):
    try:
        suffix = UUID(str(task_id)).hex
        if phase == DELIVERY:
            suffix += "_" + UUID(str(event_id)).hex
        return "wj_aw_" + phase + "_" + suffix
    except (ValueError, TypeError):
        raise ContractError("coordinator_job_identity_invalid") from None


def _source(authorized, source_id):
    from . import domain_gateway as gateway
    context = authorized["context"]
    job = worker_router.get(source_id, workspace_id=context.scope.workspace_id) or {}
    payload, scope = gateway._model_source(job)
    service_history = authorized.get("automation") is True and context.actor.kind.value == "service"
    if (str(scope.get("user_uuid")) != str(context.user_uuid)
            or str(scope.get("user_id")) != str(authorized["source_scope"]["user_id"])
            or scope.get("workspace_id") != context.scope.workspace_id
            or (not service_history and scope.get("auth_session_id") != authorized["chat_scope"].get("auth_session_id"))):
        raise ContractError("coordinator_job_scope_invalid")
    return payload, scope


def _enqueue(authorized, payload):
    authorized["admit"]()
    key = _identity(payload["phase"], payload["task_id"], payload.get("event_id"))
    try:
        return worker_router.enqueue("agent_world_followup", payload,
            user_id=authorized["source_scope"]["user_id"], workspace_id=authorized["context"].scope.workspace_id,
            job_id=key, max_attempts=3, timeout_sec=45, priority=70)
    except sqlite3.IntegrityError:
        old = worker_router.get(key, workspace_id=authorized["context"].scope.workspace_id) or {}
        if (old.get("kind") != "agent_world_followup" or old.get("payload") != payload
                or str(old.get("user_id")) != str(authorized["source_scope"]["user_id"])):
            raise ContractError("coordinator_job_identity_conflict") from None
        return old


def enqueue_continuation(authorized, task_id):
    source_id = "wj_aw_model_" + UUID(str(task_id)).hex
    payload, scope = _source(authorized, source_id)
    if not payload.get("automation_controller_id"):
        return None
    return _enqueue(authorized, {"phase": CONTINUE, "scope": scope,
        "source_worker_job_id": source_id, "task_id": str(task_id)})


def enqueue_completion(authorized, service, controller_id):
    saved = coordinator.completion(authorized, service, controller_id)
    if not saved:
        return None
    context = authorized["context"]
    if service.repository.events.is_acknowledged(context=context, consumer=coordinator.delivery_consumer(controller_id),
                                                 event_id=UUID(saved["event_id"])):
        return None
    _, _, plan = delegation.controller(service, context, controller_id)
    if authorized.get("automation") and authorized.get("automation_controller_id") != str(controller_id):
        raise ContractError("coordinator_job_scope_invalid")
    source_id = "wj_aw_model_" + UUID(plan["root_task"]["entity_id"]).hex
    _, scope = _source(authorized, source_id)
    return _enqueue(authorized, {"phase": DELIVERY, "scope": scope, "source_worker_job_id": source_id,
        "automation_controller_id": str(controller_id), "automation_grant_ref": plan["grant_ref"],
        **{key: saved[key] for key in ("task_id", "event_id", "checkpoint_sha256")}})


def related(authorized, task_id):
    """Read the current saved reviews; do not create approvals or run models."""
    from . import domain_gateway as gateway
    history = gateway.refresh_authority(authorized, read_only=True)
    service = gateway.history_models(history)
    matches = coordinator.related_completions(history, service, str(task_id))
    queued, blocked = [], list(matches["blocked"])
    for saved in matches["deliveries"]:
        try:
            row = enqueue_completion(history, service, saved["task_id"])
            if row:
                queued.append(row.get("worker_job_id", row.get("id")))
        except ContractError as exc:
            blocked.append({"controller_id": saved["task_id"], "error_code": exc.code})
    return {"queued": queued, "blocked": blocked}


def execute(authorized, job, cancelled, heartbeat):
    from . import domain_gateway as gateway
    from .followup_chat import _claim
    payload = job.get("payload") or {}
    phase = payload.get("phase")
    expected = {"phase", "scope", "source_worker_job_id", "task_id"}
    if phase == DELIVERY:
        expected |= {"event_id", "checkpoint_sha256"}
        if payload.get("automation_controller_id") or payload.get("automation_grant_ref"):
            expected |= {"automation_controller_id", "automation_grant_ref"}
    if phase not in {CONTINUE, DELIVERY} or set(payload) != expected or job.get("kind") != "agent_world_followup":
        raise ContractError("coordinator_job_invalid")
    if job.get("worker_job_id", job.get("id")) != _identity(phase, payload["task_id"], payload.get("event_id")):
        raise ContractError("coordinator_job_identity_invalid")
    source, scope = _source(authorized, payload["source_worker_job_id"])
    if scope != payload["scope"]:
        raise ContractError("coordinator_job_scope_invalid")
    original_admit = authorized["admit"]
    def admitted():
        original_admit()
        if cancelled():
            raise ContractError("coordinator_job_cancelled")
        _claim(authorized, job)
        heartbeat()
    authorized = {**authorized, "admit": admitted}
    admitted()
    if phase == CONTINUE:
        if source.get("task_id") != payload["task_id"] or not source.get("automation_controller_id"):
            raise ContractError("coordinator_job_source_invalid")
        service = gateway.models(authorized)
        result = coordinator.after_model(authorized, service, payload["task_id"])
        delivery = related(authorized, payload["task_id"])
        return {"ok": True, "status": "continued", "task_id": payload["task_id"],
                "progression": result, "delivery": delivery, "provider_execution_performed": False}
    service = gateway.history_models(authorized)
    _, _, plan = delegation.controller(service, authorized["context"], payload["task_id"])
    if source.get("task_id") != plan["root_task"]["entity_id"]:
        raise ContractError("coordinator_job_source_invalid")
    events = gateway.repository({**authorized, "read_only": False}).events
    return coordinator.deliver(authorized, service, task_id=payload["task_id"], event_id=payload["event_id"],
        checkpoint_sha256=payload["checkpoint_sha256"], events=events, delivery_job=job)
