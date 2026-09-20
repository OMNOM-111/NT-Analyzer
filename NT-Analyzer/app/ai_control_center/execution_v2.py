"""Additive, fail-closed orchestration over existing model/application workers.

An Execution record is the durable controller; its approval is an immutable
scope snapshot, and each receipt revision is a checkpoint or final evidence.
The original model Task/Execution, queue, budget, transport, and application
jobs remain authoritative. No Court decision, new queue, permission system,
trade command, or automatic human acceptance is introduced here.
"""
from __future__ import annotations

import copy
import math
import threading
import time
from dataclasses import replace
from uuid import uuid5

from . import contracts as c, deviation_control as deviations
from .events import EventData, EventEnvelope, MutationIdentity
from .flags import DISABLED, Flag, resolve
from .model_evaluation import digest
from .model_service import _id, _now, _uuid, _wire
from .states import ContractError, EntityKind


VERSION = "execution-v2-1"
_LOCKS = tuple(threading.RLock() for _ in range(64))
# ModelService calls prepare while holding its mutation lock. A runtime holds
# _LOCKS while calling ModelService; preparation must not take that same lock.
_PREPARE_LOCKS = tuple(threading.RLock() for _ in range(64))
_TERMINAL = frozenset({"succeeded", "failed", "deviated", "rejected", "cancelled", "expired"})
_PROFILE_FIELDS = ("provider_account_id", "persona_id", "base_url", "credential_source",
                   "existing_registry_id", "connection_kind", "provider", "model")


def _controller_id(context, task_id):
    return _id(context, "execution-v2:" + str(_uuid(task_id)))


def _lock(task_id):
    return _LOCKS[_uuid(task_id).int % len(_LOCKS)]


def enabled(authorized):
    return resolve(Flag.AI_EXECUTION_V2, scope=authorized["context"].scope,
                   snapshot=authorized.get("snapshot", DISABLED)).enabled


def _find(service, context, task_id):
    return service.repository.get(context=context, kind=EntityKind.EXECUTION,
                                  entity_id=_controller_id(context, task_id))


def is_managed(service, context, task_id):
    """Never consult the flag here: OFF must not fall back to legacy dispatch."""
    return _find(service, context, task_id) is not None


def _load(service, context, task_id):
    controller = _find(service, context, task_id)
    if controller is None:
        raise ContractError("execution_v2_controller_required")
    approved = service._json(context, controller.approval)
    state = service._json(context, controller.receipt) if controller.receipt else {}
    if (approved.get("source") != VERSION or approved.get("task_id") != str(_uuid(task_id))
            or approved.get("user_uuid") != str(context.user_uuid)
            or approved.get("workspace_id") != context.scope.workspace_id
            or controller.command.key != "aw_execution_v2." + str(_uuid(task_id))):
        raise ContractError("execution_v2_controller_mismatch")
    return controller, approved, state


def _commit(service, context, record, previous=0, reason="execution_v2_checkpoint"):
    event = EventEnvelope(event_id=uuid5(record.header.entity_id, f"revision:{record.header.revision}"),
        event_type="stratforge.ai.execution.deviated" if record.status == "deviated" else "stratforge.ai.execution.changed",
        time=record.header.updated_at, subject=record.ref(), actor=context.actor,
        correlation_id=record.header.correlation_id, policy=record.header.policy,
        causation_id=record.header.causation_id, data=EventData(reason_code=reason))
    mutation = MutationIdentity.for_record(context=context, operation="agent_world.execution_v2.write",
        idempotency_key=f"execution_v2.{record.header.entity_id}.{record.header.revision}",
        record=record, expected_revision=previous, event=event)
    return service.repository.commit(context=context, record=record, expected_revision=previous,
                                     event=event, mutation=mutation).record


def _save(service, context, controller, state, *, status=None, **changes):
    if controller.status in _TERMINAL:
        return controller
    value = {**state, **changes}
    receipt = service._put(context, value)
    target = status or controller.status
    if controller.receipt == receipt and target == controller.status:
        return controller
    header = replace(controller.header, revision=controller.header.revision + 1, updated_at=_now())
    return _commit(service, context, replace(controller, header=header, status=target, receipt=receipt),
                   controller.header.revision)


def _connection(service, context, checkpoint):
    model = service._get(context, EntityKind.MODEL, checkpoint["model_id"])
    profile = service._json(context, model.profile)
    account = service._get(context, EntityKind.PROVIDER_ACCOUNT, profile["provider_account_id"])
    persona = service._get(context, EntityKind.PERSONA, profile["persona_id"])
    if any(row.status != "active" for row in (model, account, persona)):
        raise ContractError("execution_v2_connection_changed")
    # last_test/connected timestamps do not change the approved connection.
    return {"model_id": str(model.header.entity_id), "provider": model.provider_key,
        "model": model.model_key, "profile": {key: profile.get(key) for key in _PROFILE_FIELDS},
        "credential_reference_sha256": digest(c.primitive(account.credential))}


def _request(checkpoint):
    value = {key: checkpoint.get(key) for key in (
        "model_id", "spec", "conversation_id", "message_id", "comparison_id", "comparison_title")}
    # ModelService hashes the optional selected Persona into the same request.
    # Keep legacy requests byte-equivalent when no selection was supplied;
    # omitting it here rejects a valid selection, while ignoring it would allow
    # a different identity to escape the approved request's integrity check.
    for key in ("handoff", "delegation", "comparison_spec", "routing", "persona_selection"):
        if key in checkpoint:
            value[key] = checkpoint[key]
    return value


def _intent_scope(intent):
    return {"goal": c.primitive(intent.goal), "acceptance": c.primitive(intent.acceptance),
        "budget": c.primitive(intent.budget), "risk": intent.risk.value, "autonomy": intent.autonomy.value,
        "policy": c.primitive(intent.header.policy)}


def _fresh(authorized, service, context, *, operation, estimate=0.0, require_flag=True):
    from . import domain_gateway
    if authorized["context"] != context or authorized.get("read_only"):
        raise ContractError("execution_v2_authority_denied")
    authorized["admit"]()
    refresh = authorized.get("refresh")
    if callable(refresh):
        current = refresh()
    else:
        # Never turn a scheduled SERVICE into a forged browser/Human session.
        if context.actor.kind != c.ActorKind.HUMAN or authorized.get("automation"):
            raise ContractError("execution_v2_automation_refresh_required")
        current = domain_gateway.access(authorized["chat_scope"])
    if current["context"] != context:
        raise ContractError("execution_v2_authority_denied")
    if require_flag and not enabled(current):
        raise ContractError("execution_v2_gate_disabled")
    # Includes existing fresh capabilities, account access and ai_budgets.
    service._access(context, operation, estimate)
    return current


def _scope(service, context, task_id, approved):
    task = service._get(context, EntityKind.TASK, task_id)
    checkpoint = service._json(context, task.checkpoint)
    intent = service._get(context, EntityKind.INTENT, task.intent.entity_id)
    role = service._get(context, EntityKind.AGENT_ROLE, task.role.entity_id)
    if (checkpoint.get("source") != "real_model_task"
            or checkpoint.get("request_sha256") != approved["request_sha256"]
            or digest(_request(checkpoint)) != approved["request_sha256"]
            or checkpoint.get("application_request") != approved.get("application_request")
            or checkpoint.get("delegation") != approved.get("delegation")
            or checkpoint.get("routing") != approved.get("routing")
            or checkpoint.get("speaking_identity") != approved.get("speaking_identity")
            or checkpoint.get("executor_persona_id") != approved.get("executor_persona_id")
            or c.primitive(task.dependencies) != approved["dependencies"]
            or c.primitive(task.role) != approved["role"]
            or task.header.policy.sha256 != approved["task_policy_sha256"]
            or str(task.intent.entity_id) != approved["intent_id"]
            or str(task.header.correlation_id) != approved["correlation_id"]
            or intent.deadline.isoformat() != approved["deadline"]
            or digest(_intent_scope(intent)) != approved["intent_scope_sha256"]
            or role.status != "active" or c.primitive(role.ref()) != approved["role"]):
        raise ContractError("execution_v2_approved_scope_changed")
    decision = service._get(context, EntityKind.DECISION, approved["decision_id"])
    if (decision.status != "approved" or decision.header.revision != approved["decision_revision"]
            or decision.approval.sha256 != approved["decision_approval_sha256"]
            or decision.contributions):
        raise ContractError("execution_v2_approved_decision_changed")
    if _now() >= intent.deadline:
        raise ContractError("execution_v2_deadline_expired")
    if digest(_connection(service, context, checkpoint)) != approved["connection_sha256"]:
        raise ContractError("execution_v2_connection_changed")
    if checkpoint.get("delegation"):
        from .delegation import validate_execution
        validate_execution(service, context, task, checkpoint)
    if checkpoint.get("routing"):
        from .router_v2 import validate_assignment
        validate_assignment(service, context, task, checkpoint)
    return task, checkpoint


def prepare(authorized, service, task_id):
    """Seal only a new approved request, before its existing model job enqueue."""
    context = authorized["context"]
    _fresh(authorized, service, context, operation="execute")
    with _PREPARE_LOCKS[_uuid(task_id).int % len(_PREPARE_LOCKS)]:
        existing = _find(service, context, task_id)
        if existing is not None:
            _, approved, _ = _load(service, context, task_id)
            _scope(service, context, task_id, approved)
            return projection(service, context, task_id)
        task = service._get(context, EntityKind.TASK, task_id)
        checkpoint = service._json(context, task.checkpoint)
        if (task.status != "ready" or checkpoint.get("source") != "real_model_task"
                or checkpoint.get("receipt") or checkpoint.get("application_dispatch")
                or checkpoint.get("spec", {}).get("rubric_key") == "court_vote"):
            raise ContractError("execution_v2_new_approved_task_required")
        from .. import worker_router
        job_id = "wj_aw_model_" + task.header.entity_id.hex
        if worker_router.get(job_id, workspace_id=context.scope.workspace_id):
            raise ContractError("execution_v2_legacy_adoption_denied")
        decision = service._get(context, EntityKind.DECISION, _id(context, f"decision:{task.header.entity_id}"))
        if decision.status != "approved" or not decision.approval or decision.contributions:
            raise ContractError("execution_v2_approved_decision_required")
        approval = service._json(context, decision.approval)
        origin = checkpoint.get("delegation")
        if (approval.get("court") is not False or approval.get("task_id") != str(task.header.entity_id)
                or approval.get("user_uuid") != str(context.user_uuid)
                or approval.get("request_sha256") != checkpoint.get("request_sha256")
                or (not origin and approval.get("source") != "explicit_bounded_user_request")):
            raise ContractError("execution_v2_approval_invalid")
        intent = service._get(context, EntityKind.INTENT, task.intent.entity_id)
        if intent.risk not in {c.Risk.LOW, c.Risk.MODERATE} or intent.autonomy not in {
            c.Autonomy.ADVICE, c.Autonomy.REVERSIBLE_EXECUTION
        }:
            # High-risk / trades require a separately accepted step-up contract.
            raise ContractError("execution_v2_high_risk_not_supported")
        connection = _connection(service, context, checkpoint)
        policy = service._put(context, {"version": VERSION, "permission_authority": "existing_auth_device_workspace",
            "budget_authority": "existing_ai_budgets_and_model_limits", "queue_authority": "existing_worker",
            "retry": "pre_transmit_or_persisted_receipt_only", "uncertain_reply": "stop_and_review",
            "rollback": "existing_source_cancel_only", "court_execution": False, "human_acceptance": False})
        approved = {"source": VERSION, "task_id": str(task.header.entity_id),
            "user_uuid": str(context.user_uuid), "workspace_id": context.scope.workspace_id,
            "source_user_id": authorized["source_scope"]["user_id"],
            "environment": context.scope.environment.value, "actor": c.primitive(context.actor),
            "session_binding_sha256": digest(authorized["chat_scope"].get("auth_session_id")),
            "request_sha256": checkpoint["request_sha256"], "approved_task": c.primitive(task.ref()),
            "task_policy_sha256": task.header.policy.sha256, "correlation_id": str(task.header.correlation_id),
            "intent_id": str(task.intent.entity_id), "role": c.primitive(task.role),
            "intent_scope_sha256": digest(_intent_scope(intent)),
            "dependencies": c.primitive(task.dependencies), "decision_id": str(decision.header.entity_id),
            "decision_revision": decision.header.revision, "decision_approval_sha256": decision.approval.sha256,
            "connection_sha256": digest(connection), "model_id": checkpoint["model_id"],
            "application_request": checkpoint.get("application_request"), "delegation": origin,
            **({"routing": checkpoint["routing"]} if "routing" in checkpoint else {}),
            **({"speaking_identity": checkpoint["speaking_identity"],
                "executor_persona_id": checkpoint.get("executor_persona_id")}
               if "speaking_identity" in checkpoint else {}),
            "delegation_sha256": digest(origin) if origin else None, "deadline": intent.deadline.isoformat(),
            "max_output_tokens": 512, "worker_job_id": job_id,
            "commands": ["bounded_model_text"] + ([checkpoint["application_request"]["kind"]] if checkpoint.get("application_request") else [])}
        _scope(service, context, task_id, approved)
        now = _now()
        header = c.RecordHeader(entity_id=_controller_id(context, task_id), scope=context.scope,
            owner_user_uuid=context.user_uuid, revision=1, created_at=now, updated_at=now,
            created_by=context.actor, correlation_id=task.header.correlation_id, policy=policy)
        controller = c.Execution(header=header, status="requested", decision=decision.ref(),
            approval=service._put(context, approved), command=c.ExternalRef(authority=c.ExternalAuthority.COMMAND,
                key="aw_execution_v2." + str(task.header.entity_id), scope=context.scope),
            receipt=service._put(context, {"source": VERSION, "phase": "approved", "deviations": [],
                "provider_started": False, "application_started": False, "human_accepted": False,
                "automatic_retry_allowed": True}))
        _commit(service, context, controller, reason="execution_v2_approved")
        return projection(service, context, task_id)


def _claim(job, context, approved, *, cancelled=None):
    from .. import worker_router
    current = worker_router.get(approved["worker_job_id"], workspace_id=context.scope.workspace_id) or {}
    payload = job.get("payload") or {}
    scope = payload.get("scope") or {}
    def future(value):
        return type(value) in {int, float} and math.isfinite(value) and value > time.time()
    if (job.get("worker_job_id", job.get("id")) != approved["worker_job_id"]
            or job.get("kind") != "agent_world_model" or payload.get("phase")
            or payload.get("task_id") != approved["task_id"]
            or job.get("workspace_id") != context.scope.workspace_id
            or scope.get("workspace_id") != context.scope.workspace_id
            or scope.get("user_uuid") != str(context.user_uuid)
            or str(scope.get("user_id")) != str(approved["source_user_id"])
            or digest(scope.get("auth_session_id")) != approved["session_binding_sha256"]
            or current.get("status") != "running" or job.get("status") != "running"
            or not job.get("worker_id") or current.get("worker_id") != job["worker_id"]
            or current.get("kind") != "agent_world_model" or current.get("payload") != payload
            or str(current.get("user_id")) != str(scope.get("user_id"))
            or str(job.get("user_id")) != str(scope.get("user_id"))
            or current.get("attempts") != job.get("attempts")
            or not future(current.get("locked_until")) or not future(current.get("deadline_at"))):
        raise ContractError("execution_v2_claim_lost")
    if current.get("cancel_requested") or (callable(cancelled) and cancelled()):
        raise ContractError("execution_v2_cancelled")


def _reason(error):
    if isinstance(error, OSError):
        return "execution_checkpoint_interrupted"
    code = error.code if isinstance(error, ContractError) else ""
    return {
        "execution_v2_gate_disabled": "execution_gate_disabled", "execution_v2_claim_lost": "execution_claim_lost",
        "execution_v2_cancelled": "execution_cancelled", "execution_v2_deadline_expired": "execution_deadline_expired",
        "execution_v2_approved_scope_changed": "approved_scope_changed",
        "execution_v2_approved_decision_changed": "approved_decision_changed",
        "execution_v2_connection_changed": "connection_changed",
    }.get(code, "delegation_source_changed" if code.startswith(("delegation_", "schedule_")) else "execution_authority_denied")


def _deviate(service, context, task_id, reason, phase, *, uncertain=False):
    controller, approved, state = _load(service, context, task_id)
    if controller.status in _TERMINAL:
        return
    reference = deviations.record(service, context, controller, reason=reason, phase=phase,
                                  expected=approved["request_sha256"])
    records = state.get("deviations", [])
    if _wire(reference) not in records:
        records = [*records, _wire(reference)]
    # Retain recoverability only before a transmit or from an actual receipt.
    target = "review" if controller.status == "running" else controller.status
    _save(service, context, controller, state, status=target, phase="uncertain" if uncertain else "blocked",
          deviations=records, reason_code=reason, automatic_retry_allowed=False)


def before_application(authorized, service, task_id):
    """Also guards reconciliation, which may resume after the model lease ends."""
    context = authorized["context"]
    if not is_managed(service, context, task_id):
        return
    with _lock(task_id):
        controller, approved, state = _load(service, context, task_id)
        try:
            if controller.status in _TERMINAL:
                task = service._get(context, EntityKind.TASK, task_id)
                if task.status != "waiting":
                    return None  # finished/cancelled source is an ordinary no-op
            if controller.status in _TERMINAL or state.get("phase") == "uncertain":
                raise ContractError("execution_v2_continuation_denied")
            _fresh(authorized, service, context, operation="application_dispatch")
            task, checkpoint = _scope(service, context, task_id, approved)
            if (not checkpoint.get("receipt") or not approved.get("application_request") or task.status != "waiting"
                    or service.task_detail(context=context, task_id=task_id).get("model_plan_verified") is not True):
                raise ContractError("execution_v2_application_not_ready")
            receipt = service._json(context, checkpoint["receipt"])
            reason = deviations.inspect_provider(approved, receipt)
            if reason:
                _deviate(service, context, task_id, reason, "application")
                raise ContractError("execution_v2_provider_scope_mismatch")
            # The source adapters retain their deterministic source key. A
            # crash here can recover that same job, never a second external job.
            _save(service, context, controller, state, phase="application_dispatch",
                  application_started=True, provider_receipt=checkpoint["receipt"])
        except Exception as error:
            _deviate(service, context, task_id, _reason(error), "application")
            raise
    def guard():
        # Called by the EXISTING source adapter immediately before enqueue.
        # No controller lock here: application code owns its own lock order.
        try:
            current, _, current_state = _load(service, context, task_id)
            if current.status in _TERMINAL or current_state.get("phase") == "uncertain":
                raise ContractError("execution_v2_continuation_denied")
            _fresh(authorized, service, context, operation="application_dispatch")
            task, _ = _scope(service, context, task_id, approved)
            if task.status != "waiting":
                raise ContractError("execution_v2_application_not_ready")
        except Exception as error:
            _deviate(service, context, task_id, _reason(error), "application")
            raise
    return guard


def execute(authorized, service, job, cancelled, heartbeat):
    context, task_id = authorized["context"], job["payload"]["task_id"]
    with _lock(task_id):
        controller, approved, state = _load(service, context, task_id)
        _claim(job, context, approved, cancelled=cancelled)
        if controller.status in _TERMINAL:
            return service.task_detail(context=context, task_id=task_id)
        try:
            _fresh(authorized, service, context, operation="execute")
            task, checkpoint = _scope(service, context, task_id, approved)
            if state.get("provider_started") and not checkpoint.get("receipt"):
                _deviate(service, context, task_id, "provider_reply_uncertain", "resume", uncertain=True)
                return service.task_detail(context=context, task_id=task_id)
            if not state.get("provider_started") and not checkpoint.get("receipt") and task.status == "running":
                # Our durable fence proves the executor was never entered.
                # Reuse legal Task transitions; do not reset the queue/attempt.
                task = service._change(context, task, "blocked")
                service._change(context, task, "ready")
            if controller.status == "requested":
                controller = _save(service, context, controller, state, status="queued")
            if controller.status == "queued":
                controller = _save(service, context, controller, state, status="running", phase="admission")
            state = service._json(context, controller.receipt)
            _save(service, context, controller, state,
                  claim={"worker_id": job["worker_id"], "attempt": job["attempts"]},
                  automatic_retry_allowed=not state.get("provider_started"))
            guarded = copy.copy(service)
            original_executor = service.executor
            def guard(current_context, operation, estimate=0.0):
                if current_context != context:
                    raise ContractError("execution_v2_authority_denied")
                if operation == "read":
                    return service.admit(current_context, operation, estimate)
                _claim(job, context, approved, cancelled=cancelled)
                heartbeat()
                _fresh(authorized, service, context, operation=operation, estimate=estimate)
                _scope(service, context, task_id, approved)
            def dispatch(**kwargs):
                guard(context, "provider_transmit")
                current, _, checkpoint_state = _load(service, context, task_id)
                if checkpoint_state.get("provider_started"):
                    raise ContractError("execution_v2_provider_replay_denied")
                _save(service, context, current, checkpoint_state, phase="provider_in_flight", provider_started=True)
                return original_executor(**{**kwargs, "admit": guard})
            guarded.admit, guarded.executor = guard, dispatch
            result = guarded.execute(context=context, task_id=task_id, cancelled=cancelled)
            observe(authorized, service, task_id)
            current, _, checkpoint_state = _load(service, context, task_id)
            if current.status not in _TERMINAL and checkpoint_state.get("phase") != "uncertain":
                heartbeat()
                from . import application_chat
                application_chat.finish_dispatch(authorized, service, result)
                observe(authorized, service, task_id)
            return result
        except Exception as error:
            _deviate(service, context, task_id, _reason(error), "admission")
            raise


def _receipt_service(authorized, service):
    """Read authority plus this same private audit store, never an executor."""
    from . import domain_gateway
    context = authorized["context"]
    def admit(current_context, operation, estimate):
        if current_context != context or operation != "read" or estimate != 0:
            raise ContractError("execution_v2_receipt_only")
        if context.actor.kind == c.ActorKind.HUMAN and not authorized.get("automation"):
            current = domain_gateway.access(authorized["chat_scope"], read_only=True)
        else:
            refresh = authorized.get("refresh")
            if not callable(refresh):
                raise ContractError("execution_v2_automation_refresh_required")
            current = refresh(read_only=True)
        if current["context"] != context:
            raise ContractError("execution_v2_authority_denied")
        current["admit"]()
    view = copy.copy(service)
    view.admit, view.executor, view.enqueue = admit, None, None
    view._access(context)
    return view


def observe(authorized, service, task_id):
    """Persist receipt-only closeout on a mutation/reconcile path, never GET."""
    context = authorized["context"]
    if not is_managed(service, context, task_id):
        return None
    service = _receipt_service(authorized, service)
    with _lock(task_id):
        controller, approved, state = _load(service, context, task_id)
        if controller.status in _TERMINAL:
            return projection(service, context, task_id)
        # Result inspection is not a paid/background step. An expired model
        # allowance must not prevent recording already-received evidence.
        service._access(context)
        task = service._get(context, EntityKind.TASK, task_id)
        checkpoint = service._json(context, task.checkpoint)
        if task.status == "cancelled":
            if controller.status == "running":
                controller = _save(service, context, controller, state, status="review")
            _save(service, context, controller, state, status="cancelled", phase="cancelled")
        elif not checkpoint.get("receipt"):
            if state.get("provider_started"):
                _deviate(service, context, task_id, "provider_reply_uncertain", "observe", uncertain=True)
            elif task.status in {"failed", "blocked"}:
                _deviate(service, context, task_id, "execution_source_failed", "observe")
        else:
            receipt = service._json(context, checkpoint["receipt"])
            scope_matches = (checkpoint.get("request_sha256") == approved["request_sha256"]
                and digest(_request(checkpoint)) == approved["request_sha256"]
                and checkpoint.get("application_request") == approved.get("application_request")
                and checkpoint.get("delegation") == approved.get("delegation")
                and checkpoint.get("routing") == approved.get("routing")
                and checkpoint.get("speaking_identity") == approved.get("speaking_identity")
                and checkpoint.get("executor_persona_id") == approved.get("executor_persona_id")
                and c.primitive(task.role) == approved["role"])
            if scope_matches and checkpoint.get("routing"):
                from .router_v2 import validate_assignment
                try:
                    validate_assignment(service, context, task, checkpoint)
                except ContractError:
                    scope_matches = False
            reason = deviations.inspect_provider(approved, receipt, check_test_executor_enabled=False) if scope_matches else "approved_scope_changed"
            result = None
            if not reason:
                detail = service.task_detail(context=context, task_id=task_id)
                if approved.get("application_request"):
                    from .application_evidence import application_result
                    result = application_result(service, context, task)
                    if result:
                        reason = deviations.inspect_application(approved, checkpoint, result)
                    elif checkpoint.get("application_error") or task.status in {"failed", "review"}:
                        reason = "application_result_rejected"
                elif task.status in {"succeeded", "review"}:
                    if (detail.get("evaluation") or {}).get("passed") is not True:
                        reason = "provider_result_rejected"
                    else:
                        result = {"outcome_id": detail.get("outcome_id"), "verification": detail["evaluation"]}
            if reason:
                _deviate(service, context, task_id, reason, "observe")
                current, _, current_state = _load(service, context, task_id)
                if current.status in {"running", "review"}:
                    _save(service, context, current, current_state, status="deviated", phase="deviated")
            elif result:
                _save(service, context, controller, state, status="succeeded", phase="verified_result",
                      provider_receipt=checkpoint["receipt"], result=result, human_accepted=False)
            else:
                _save(service, context, controller, state, phase="waiting_result" if approved.get("application_request") else "receipt_received",
                      provider_receipt=checkpoint["receipt"])
        return projection(service, context, task_id)


def projection(service, context, task_id):
    """Read-only DTO. A successful controller is NOT an accepted human review."""
    controller, approved, state = _load(service, context, task_id)
    evidence = [service._json(context, ref) for ref in state.get("deviations", [])]
    return {"id": str(controller.header.entity_id), "revision": controller.header.revision,
        "version": VERSION, "status": controller.status, "phase": state.get("phase"),
        "task_id": approved["task_id"], "worker_job_id": approved["worker_job_id"],
        "approved_scope_sha256": controller.approval.sha256,
        "decision_id": approved["decision_id"], "correlation_id": approved["correlation_id"],
        "reason_codes": [row["reason_code"] for row in evidence],
        "deviation_count": len(evidence), "provider_started": bool(state.get("provider_started")),
        "application_started": bool(state.get("application_started")),
        "provider_receipt_present": bool(state.get("provider_receipt")),
        "automatic_retry_allowed": state.get("automatic_retry_allowed") is True and not state.get("provider_started") and controller.status not in _TERMINAL,
        "resume_mode": "receipt_only" if state.get("provider_receipt") else "never_retransmit" if state.get("provider_started") else "fresh_authority_required",
        "human_accepted": False, "court_execution": False, "routing_effect": "none"}
