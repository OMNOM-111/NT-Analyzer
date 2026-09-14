"""Bounded due-time dispatch on the existing queue, with explicit automation.

An accepted manual source never becomes an autonomous schedule. A separate
controller pins its source, grant, model, input and finite UTC occurrence set.
The existing worker's recovery tick calls scan_due; no thread/scheduler is born.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .. import worker_router
from . import contracts as c, delegation as d, result_handoff
from .domain_service import DomainService
from .followup_chat import _accepted, _claim
from .model_evaluation import digest, json_bytes, prepare
from .model_service import _id, _key, _uuid
from .states import ContractError, EntityKind


SOURCE = "agent_world_schedule"
PHASE = "scheduler_occurrence"
VERSION = "finite-schedule-v1"
MAX_OCCURRENCES = 10


def occurrence_times(schedule):
    """Explicit IANA timezone, reject gaps and unspecified ambiguous folds.

    Recurrence is fixed elapsed seconds in UTC, not an inferred wall-clock cron.
    Both the original zone and every actual UTC occurrence are retained.
    """
    if (type(schedule) is not dict or set(schedule) - {"local_start", "timezone", "fold", "interval_seconds", "occurrences", "grace_seconds"}
            or not {"local_start", "timezone", "interval_seconds", "occurrences", "grace_seconds"} <= set(schedule)):
        raise ContractError("schedule_definition_invalid")
    interval, count, grace = (schedule[key] for key in ("interval_seconds", "occurrences", "grace_seconds"))
    if (type(interval) is not int or not 0 <= interval <= 30 * 86400 or (interval and interval < 60)
            or type(count) is not int or not 1 <= count <= MAX_OCCURRENCES or (count > 1 and interval == 0)
            or type(grace) is not int or not 1 <= grace <= 3600):
        raise ContractError("schedule_bounds_invalid")
    try:
        local = datetime.fromisoformat(schedule["local_start"])
        if local.tzinfo is not None: raise ValueError()
        zone = ZoneInfo(schedule["timezone"])
        candidates = []
        for fold in (0, 1):
            aware = local.replace(tzinfo=zone, fold=fold)
            utc = aware.astimezone(timezone.utc)
            restored = utc.astimezone(zone)
            if restored.replace(tzinfo=None) == local and restored.fold == fold:
                candidates.append((fold, utc))
        if not candidates:
            raise ContractError("schedule_local_time_nonexistent")
        requested = schedule.get("fold")
        if len(candidates) == 2 and requested is None:
            raise ContractError("schedule_local_time_ambiguous")
        if requested is not None and (type(requested) is not int or requested not in (0, 1)):
            raise ContractError("schedule_fold_invalid")
        start = next(value for fold, value in candidates if requested is None or requested == fold)
    except ContractError:
        raise
    except (ValueError, TypeError, KeyError, ZoneInfoNotFoundError, StopIteration):
        raise ContractError("schedule_timezone_or_start_invalid") from None
    try:
        return [(start + timedelta(seconds=interval * index)).isoformat() for index in range(count)]
    except OverflowError:
        raise ContractError("schedule_date_overflow") from None


def _control_ref(context, identity):
    return c.EntityRef(kind=EntityKind.TASK, entity_id=_uuid(identity), revision=1, scope=context.scope)


def _child_key(identity, index):
    return "schedule." + str(identity) + "." + str(index)


def _child_id(context, identity, index):
    return _id(context, "model-task:" + _key(_child_key(identity, index)))


def _job_id(identity, index):
    return "wj_aw_schedule_" + _uuid(identity).hex + "_" + str(index)


def _source(authorized, service, plan):
    source, _, _ = _accepted(authorized, DomainService(service.repository), plan["domain"], plan["source"]["entity_id"], plan["source"]["revision"])
    if c.primitive(source.ref()) != plan["source"] or c.primitive(source.definition) != plan["definition"]:
        raise ContractError("schedule_source_changed")
    return source


def _seal(service, context, control, plan, index, *, now=None):
    from . import test_executor
    if bool(plan.get("synthetic")) != test_executor.enabled(context.scope.workspace_id):
        raise ContractError("schedule_executor_mode_changed")
    if type(index) is not int or not 0 <= index < len(plan["due_at"]):
        raise ContractError("schedule_occurrence_invalid")
    now = now or datetime.now(timezone.utc)
    c.require_utc(now)
    due = d.utc(plan["due_at"][index])
    if now < due:
        raise ContractError("schedule_not_due")
    if now > due + timedelta(seconds=plan["schedule"]["grace_seconds"]):
        raise ContractError("schedule_occurrence_missed")
    if d.connection_digest(service, context, plan["model_id"]) != plan.get("connection_sha256"):
        raise ContractError("schedule_target_changed")
    packet = {"kind": "schedule_v1", "controller_id": str(control.header.entity_id), "occurrence_index": index,
        "plan_sha256": digest(plan), "due_at": plan["due_at"][index], "timezone": plan["schedule"]["timezone"],
        "source": plan["source"], "definition": plan["definition"], "model_id": plan["model_id"],
        "grant_ref": plan["grant_ref"], "spec": plan["spec"], "conversation_id": plan["conversation_id"],
        "source_message_id": plan["source_message_id"], "synthetic": bool(plan.get("synthetic"))}
    reference = _control_ref(context, control.header.entity_id)
    return d.SealedDelegation(reference, (reference,), control.header.correlation_id, json_bytes(packet))


def validate_constructor(service, context, value, *, model_id, spec, conversation_id):
    packet = value.wire()
    control, _, plan = d.controller(service, context, value.controller.entity_id, SOURCE)
    if control.status not in {"planned", "ready", "running", "waiting"}:
        raise ContractError("schedule_controller_stopped")
    authorized = getattr(service, "mechanism_authorized", None)
    if not isinstance(authorized, dict) or authorized.get("context") != context:
        raise ContractError("schedule_fresh_authority_required")
    d.gate(authorized, "AI_SCHEDULER_V1")
    _source(authorized, service, plan)
    fresh = _seal(service, context, control, plan, packet.get("occurrence_index"))
    if (packet != fresh.wire() or value.dependencies != fresh.dependencies or value.correlation_id != fresh.correlation_id
            or str(model_id) != plan["model_id"] or spec != plan["spec"] or conversation_id != plan["conversation_id"]):
        raise ContractError("schedule_source_or_request_changed")
    d.authority(service, context, control.ref(), plan["grant_ref"], "schedule_step", plan["model_id"])
    result_handoff._source_message({"context": context, "chat_scope": service.chat_scope}, packet)
    return packet


def validate_execution(service, context, task, checkpoint):
    packet = checkpoint.get("delegation") or {}
    control, _, plan = d.controller(service, context, packet.get("controller_id"), SOURCE)
    seal = _seal(service, context, control, plan, packet.get("occurrence_index"))
    if (task.dependencies != seal.dependencies or task.header.correlation_id != seal.correlation_id
            or packet != seal.wire()
            or task.header.entity_id != _child_id(context, control.header.entity_id, packet["occurrence_index"])):
        raise ContractError("schedule_task_identity_invalid")
    return validate_constructor(service, context, seal, model_id=checkpoint["model_id"],
        spec=checkpoint["spec"], conversation_id=checkpoint["conversation_id"])


def propose(authorized, service, domain_service, *, domain, identity, expected_revision, model_id,
            schedule, payload, idempotency_key, conversation_id, message_id):
    """Read-only definition for a separate explicit durable approval."""
    context = d.gate(authorized, "AI_SCHEDULER_V1")
    if context.actor.kind != c.ActorKind.HUMAN:
        raise ContractError("schedule_initial_human_approval_required")
    key = _key(idempotency_key)
    control_id = _id(context, "schedule:" + key)
    due = occurrence_times(schedule)
    if type(payload) is not dict or set(payload) != {"rubric_key", "input_text"} or payload["rubric_key"] not in {"extract_facts", "json_arithmetic"}:
        raise ContractError("schedule_bounded_operation_required")
    spec = prepare(payload["rubric_key"], payload["input_text"])
    source, _, _ = _accepted(authorized, domain_service, domain, identity, expected_revision)
    from . import test_executor
    from .process_intelligence import ProcessIntelligence
    synthetic = test_executor.enabled(context.scope.workspace_id)
    marker = ProcessIntelligence(domain_service, service)._marker(context, source)
    if marker and marker.get("synthetic") is True and not synthetic:
        raise ContractError("schedule_synthetic_source_disabled")
    model = service._get(context, EntityKind.MODEL, model_id)
    profile = service._json(context, model.profile)
    for kind, selected in ((EntityKind.PERSONA, profile["persona_id"]), (EntityKind.PROVIDER_ACCOUNT, profile["provider_account_id"])):
        if service._get(context, kind, selected).status != "active":
            raise ContractError("schedule_target_inactive")
    if model.status != "active": raise ContractError("schedule_target_inactive")
    plan = {"version": VERSION, "domain": domain, "source": c.primitive(source.ref()), "definition": c.primitive(source.definition),
        "model_id": str(model.header.entity_id), "persona_id": profile["persona_id"], "provider_account_id": profile["provider_account_id"],
        "connection_sha256": d.connection_digest(service, context, model.header.entity_id),
        "schedule": schedule, "due_at": due, "spec": spec,
        "conversation_id": conversation_id, "source_message_id": message_id, "synthetic": synthetic}
    result_handoff._source_message(authorized, plan)
    return {"controller_id": str(control_id), "plan": plan}


def create(authorized, service, domain_service, *, domain, identity, expected_revision, model_id,
           schedule, payload, idempotency_key, grant_ref, conversation_id, message_id):
    proposed = propose(authorized, service, domain_service, domain=domain, identity=identity, expected_revision=expected_revision,
        model_id=model_id, schedule=schedule, payload=payload, idempotency_key=idempotency_key,
        conversation_id=conversation_id, message_id=message_id)
    context = authorized["context"]
    control_id, reference = _uuid(proposed["controller_id"]), d.snapshot(context, grant_ref)
    plan = {**proposed["plan"], "grant_ref": c.primitive(reference)}
    approved = d.authority(service, context, _control_ref(context, control_id), reference, "schedule_create",
                           plan["model_id"], proposed_plan=plan)
    if d.utc(plan["due_at"][-1]) + timedelta(seconds=schedule["grace_seconds"]) > d.utc(approved["expires_at"]):
        raise ContractError("schedule_after_approval_expiry")
    plan["expires_at"] = approved["expires_at"]
    result_handoff._source_message(authorized, plan)
    control = d.create_controller(service, context, control_id, plan, source=SOURCE, correlation=control_id)
    if control.status == "planned": service._walk(context, control, "ready")
    return projection(authorized, service, control_id)


def _queue(authorized, service, control, plan, index):
    context = authorized["context"]
    d.authority(service, context, control.ref(), plan["grant_ref"], "schedule_queue", plan["model_id"])
    payload = {"phase": PHASE, "scope": d.subject(authorized), "controller_id": str(control.header.entity_id),
               "occurrence_index": index, "plan_sha256": digest(plan), "grant_ref": plan["grant_ref"]}
    try:
        return worker_router.enqueue("agent_world_followup", payload, job_id=_job_id(control.header.entity_id, index),
            max_attempts=3, timeout_sec=60, user_id=authorized["source_scope"]["user_id"], workspace_id=context.scope.workspace_id, priority=80)
    except sqlite3.IntegrityError:
        old = worker_router.get(_job_id(control.header.entity_id, index), workspace_id=context.scope.workspace_id) or {}
        if old.get("kind") != "agent_world_followup" or old.get("payload") != payload:
            raise ContractError("schedule_job_identity_conflict") from None
        return old


def tick(authorized, service, identity, *, now=None):
    context = d.gate(authorized, "AI_SCHEDULER_V1")
    now = now or datetime.now(timezone.utc)
    c.require_utc(now)
    control, checkpoint, plan = d.controller(service, context, identity, SOURCE)
    if control.status in {"cancelled", "failed", "blocked", "review", "succeeded"}:
        return projection(authorized, service, identity)
    d.authority(service, context, control.ref(), plan["grant_ref"], "schedule_tick", plan["model_id"])
    _source(authorized, service, plan)
    missed = dict(checkpoint.get("missed", {}))
    terminal, stopped, ready_occurrences = 0, False, []
    for index, due in enumerate(plan["due_at"]):
        task = service.repository.get(context=context, kind=EntityKind.TASK, entity_id=_child_id(context, identity, index))
        job = worker_router.get(_job_id(identity, index), workspace_id=context.scope.workspace_id)
        model_job = worker_router.get("wj_aw_model_" + _child_id(context, identity, index).hex, workspace_id=context.scope.workspace_id)
        if any(row and row.get("status") in {"failed", "cancelled"} for row in (job, model_job)) and str(index) not in missed:
            stopped = True
            break  # Unexpected queue failure never starts later occurrences.
        if task:
            terminal += task.status in {"succeeded", "failed", "review", "blocked", "cancelled"}
            continue
        if str(index) in missed:
            terminal += 1
            continue
        if now < d.utc(due): continue
        if now > d.utc(due) + timedelta(seconds=plan["schedule"]["grace_seconds"]):
            if job and job.get("status") == "running": continue
            if job and job.get("status") == "queued":
                worker_router.cancel(_job_id(identity, index), workspace_id=context.scope.workspace_id, user_id=authorized["source_scope"]["user_id"])
            missed[str(index)] = {"status": "missed", "due_at": due, "recorded_at": now.isoformat(), "provider_dispatch": False}
            terminal += 1
        else:
            ready_occurrences.append(index)
    current = service._get(context, EntityKind.TASK, identity)
    if missed != checkpoint.get("missed", {}):
        current = service._change(context, current, checkpoint=service._put(context, {**checkpoint, "missed": missed}))
    if stopped:
        if current.status == "waiting": current = service._change(context, current, "ready")
        service._change(context, current, "blocked")
    elif terminal == len(plan["due_at"]):
        current = service._walk(context, current, "ready", "running")
        service._change(context, current, "review")
    else:
        for index in ready_occurrences:
            _queue(authorized, service, current, plan, index)
    return projection(authorized, service, identity)


def scan_due(authorized, service, *, now=None, limit=25):
    if type(limit) is not int or not 1 <= limit <= 100: raise ContractError("schedule_scan_limit_invalid")
    context = d.gate(authorized, "AI_SCHEDULER_V1")
    now = now or datetime.now(timezone.utc)
    c.require_utc(now)
    result, candidates = [], []
    for task in service._all(context, EntityKind.TASK):
        if task.status not in {"planned", "ready", "running", "waiting"}: continue
        checkpoint = service._json(context, task.checkpoint) if task.checkpoint else {}
        if checkpoint.get("source") != SOURCE: continue
        _, checkpoint, plan = d.controller(service, context, task.header.entity_id, SOURCE)
        remaining, waiting = [], False
        for index, due in enumerate(plan["due_at"]):
            child = service.repository.get(context=context, kind=EntityKind.TASK,
                entity_id=_child_id(context, task.header.entity_id, index))
            if child is not None:
                waiting |= child.status not in {"succeeded", "failed", "review", "blocked", "cancelled"}
            elif str(index) not in checkpoint.get("missed", {}):
                remaining.append(d.utc(due))
        if not remaining and waiting:
            continue  # The existing model worker, not a scheduler tick, owns it.
        candidates.append((min(remaining) if remaining else now, str(task.header.entity_id)))
    # Future controllers cannot consume the bounded scan ahead of actually due
    # work merely because repository UUID ordering happened to put them first.
    for _, identity in sorted(candidates):
        try:
            result.append(tick(authorized, service, identity, now=now))
        except ContractError as exc:
            result.append({"id": identity, "status": "blocked", "reason_code": exc.code, "dispatch_performed": False})
        if len(result) >= limit: break
    return result


def execute(authorized, service, job, cancelled, heartbeat):
    context = d.gate(authorized, "AI_SCHEDULER_V1")
    payload = job.get("payload") or {}
    if set(payload) != {"phase", "scope", "controller_id", "occurrence_index", "plan_sha256", "grant_ref"} or payload.get("phase") != PHASE:
        raise ContractError("schedule_worker_request_invalid")
    if payload["scope"] != d.subject(authorized): raise ContractError("schedule_worker_scope_invalid")
    heartbeat()
    _claim(authorized, job)
    control, _, plan = d.controller(service, context, payload["controller_id"], SOURCE)
    if cancelled() or control.status in {"cancelled", "failed", "blocked", "succeeded"}:
        raise ContractError("schedule_cancelled_or_stopped")
    index = payload["occurrence_index"]
    if (payload["plan_sha256"] != digest(plan) or payload["grant_ref"] != plan["grant_ref"]
            or job.get("worker_job_id", job.get("id")) != _job_id(control.header.entity_id, index)):
        raise ContractError("schedule_worker_source_changed")
    if control.status == "review":
        child = service._get(context, EntityKind.TASK, _child_id(context, control.header.entity_id, index))
        packet = service._json(context, child.checkpoint).get("delegation") or {}
        if (child.status not in {"succeeded", "failed", "blocked", "review", "cancelled"}
                or packet.get("controller_id") != str(control.header.entity_id)
                or packet.get("occurrence_index") != index or packet.get("plan_sha256") != digest(plan)):
            raise ContractError("schedule_task_identity_invalid")
        d.authority(service, context, control.ref(), plan["grant_ref"], "schedule_step", plan["model_id"])
        return {"ok": True, "status": "child_terminal", "task_id": str(child.header.entity_id),
                "controller_id": str(control.header.entity_id), "replayed": True, "provider_dispatch": False}
    _source(authorized, service, plan)
    seal = _seal(service, context, control, plan, index)
    d.authority(service, context, control.ref(), plan["grant_ref"], "schedule_step", plan["model_id"])
    control = service._walk(context, control, "ready", "running")
    service.mechanism_authorized = authorized
    service.chat_scope = authorized["chat_scope"]
    if cancelled(): raise ContractError("schedule_cancelled_or_stopped")
    heartbeat()
    _claim(authorized, job)
    input_text = (json_bytes(plan["spec"]["input"]).decode("utf-8") if plan["spec"]["rubric_key"] == "json_arithmetic"
                  else "\n".join(key + "=" + value for key, value in plan["spec"]["input"].items()))
    detail = service.start_task(context=context, model_id=plan["model_id"], payload={"rubric_key": plan["spec"]["rubric_key"],
        "input_text": input_text}, idempotency_key=_child_key(control.header.entity_id, index),
        conversation_id=plan["conversation_id"], message_id=plan["source_message_id"], _delegation=seal)
    current = service._get(context, EntityKind.TASK, control.header.entity_id)
    if current.status == "running": service._change(context, current, "waiting")
    return {"ok": True, "status": "child_queued", "controller_id": str(control.header.entity_id), "occurrence_index": index,
        "due_at": plan["due_at"][index], "queued_at": job["queued_at_utc"], "task_id": detail["id"], "synthetic": bool(plan.get("synthetic"))}


def projection(authorized, service, identity):
    authorized["admit"]()
    context = authorized["context"]
    control, checkpoint, plan = d.controller(service, context, identity, SOURCE)
    occurrences = []
    for index, due in enumerate(plan["due_at"]):
        task = service.repository.get(context=context, kind=EntityKind.TASK, entity_id=_child_id(context, identity, index))
        job = worker_router.get(_job_id(identity, index), workspace_id=context.scope.workspace_id)
        model_job = worker_router.get("wj_aw_model_" + _child_id(context, identity, index).hex, workspace_id=context.scope.workspace_id)
        missed = checkpoint.get("missed", {}).get(str(index))
        occurrences.append({"index": index, "due_at": due, "task_id": str(task.header.entity_id) if task else None,
            "synthetic": bool(plan.get("synthetic")),
            "status": task.status if task else "missed" if missed else job["status"] if job else "scheduled",
            "recorded_at": missed.get("recorded_at") if missed else None,
            "coordination_job_status": job.get("status") if job else None, "model_job_status": model_job.get("status") if model_job else None})
    return {"id": str(control.header.entity_id), "source": SOURCE, "status": control.status, "schedule": plan["schedule"],
        "occurrences": occurrences, "source_record": plan["source"], "plan_sha256": digest(plan),
        "model_id": plan["model_id"], "conversation_id": plan["conversation_id"], "grant_ref": plan["grant_ref"],
        "explicit_automation": True, "manual_source_unchanged": True, "human_accepted": False, "synthetic": bool(plan.get("synthetic"))}


def cancel(authorized, service, identity):
    context = d.write_admission(authorized)
    control, _, plan = d.controller(service, context, identity, SOURCE)
    if control.status not in {"cancelled", "failed", "succeeded"}: service._change(context, control, "cancelled")
    for index in range(len(plan["due_at"])):
        child_id = _child_id(context, identity, index)
        child = service.repository.get(context=context, kind=EntityKind.TASK, entity_id=child_id)
        for job_id in (_job_id(identity, index), "wj_aw_model_" + child_id.hex):
            if worker_router.get(job_id, workspace_id=context.scope.workspace_id):
                worker_router.cancel(job_id, workspace_id=context.scope.workspace_id, user_id=authorized["source_scope"]["user_id"])
        if child and child.status not in {"succeeded", "failed", "cancelled"}: service.cancel(context=context, task_id=child_id)
    return projection(authorized, service, identity)
