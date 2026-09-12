"""A bounded new-goal commission, using the existing model, graph and chat stores.

The bounded scenarios transfer verified numeric facts or analyse separate
numeric segments. This is not a general planner. The root is a normal model task;
no descendant is dispatched until the human approves the exact resulting
graph through automation_authority. No second queue, permission or budget.
"""
from __future__ import annotations

import json
import re
from uuid import UUID, uuid5

from . import contracts as c, delegation, model_chat, result_handoff
from .model_evaluation import digest, prepare
from .model_service import _id, _key, _uuid
from .states import ContractError, EntityKind

SOURCE = "agent_world_coordinator"
VERSION = "bounded-data-coordinator-v1"
DELIVERY_CONSUMER = "agent_world.delegation.sf_chat.v1"
LIMITATION = ("Координатор поддерживает проверку передачи числовых фактов и отдельный разбор участков данных. "
              "Это ограниченные проверяемые задачи, не оценка профессионального качества; приёмка владельцем отдельная.")


def _load(authorized, service, identity):
    authorized["admit"]()
    return delegation.controller(service, authorized["context"], identity, SOURCE)


def _graph_key(identity):
    return "coordinator.graph." + str(identity)


def _intent_target(control):
    return {"planned": "ready", "ready": "ready", "running": "running", "waiting": "waiting",
            "review": "waiting", "blocked": "blocked", "cancelled": "cancelled",
            "failed": "failed", "succeeded": "completed"}[control.status]


def _sync_control_intent(service, context, control):
    """Write-path repair through existing transitions; immutable goal stays pinned.

    A review is waiting for a human, never an automatically completed Intent.
    Projections do not call this method or conceal historical inconsistency.
    """
    control = service._get(context, EntityKind.TASK, control.header.entity_id)
    intent = service._get(context, EntityKind.INTENT, control.intent.entity_id)
    target = _intent_target(control)
    if intent.status == target:
        return intent
    if intent.status in {"completed", "failed", "cancelled"}:
        raise ContractError("coordinator_intent_terminal_conflict")
    if target == "cancelled":
        return service._change(context, intent, target)
    if intent.status == "draft":
        intent = service._change(context, intent, "ready")
    if target == "failed" and intent.status in {"waiting", "blocked"}:
        return service._change(context, intent, target)
    if intent.status in {"waiting", "blocked"}:
        intent = service._change(context, intent, "ready")
    if target == "ready" and intent.status == "running":
        intent = service._change(context, intent, "waiting")
    if target in {"waiting", "completed", "failed"} and intent.status == "ready":
        intent = service._change(context, intent, "running")
    return service._change(context, intent, target)


def commission(authorized, service, payload, key, *, conversation_id=None, user_message=None,
               _intent_selection=None, _supersedes=None):
    """One explicit new goal -> pinned finite plan -> normal SF Chat model root."""
    context = delegation.gate(authorized, "AI_DELEGATION_V2")
    if context.actor.kind != c.ActorKind.HUMAN:
        raise ContractError("coordinator_human_required")
    allowed = {"goal", "input_text", "coordinator_model_id", "target_model_ids", "parent_indices",
               "max_depth", "operation"}
    if type(payload) is not dict or set(payload) - allowed:
        raise ContractError("coordinator_payload_invalid")
    goal = payload.get("goal")
    if type(goal) is not str or not 1 <= len(goal.strip()) <= 400 or not payload.get("input_text"):
        raise ContractError("coordinator_goal_and_data_required")
    operation = payload.get("operation", delegation.DEFAULT_OPERATION)
    if operation not in delegation.OPERATIONS:
        raise ContractError("coordinator_operation_unsupported")
    profile = delegation.OPERATIONS[operation]
    spec = prepare("json_arithmetic", payload["input_text"])
    identity = _id(context, "coordinator:" + _key(key))
    root_key = "coordinator.root." + str(identity)
    root_id = _id(context, "model-task:" + _key(root_key))
    model = service.model_detail(context=context, model_id=payload.get("coordinator_model_id"))
    depth = payload.get("max_depth", 3)
    nodes = delegation._graph(payload.get("target_model_ids"), payload.get("parent_indices"), depth,
                              model["persona_id"], service, context)
    for node in nodes:
        node.update(operation=operation, role=profile["role"],
            operation_label=profile["label"],
            produces_new_analysis=profile["produces_new_analysis"])
    # A plan that cannot carry the work is refused while it is still a proposal,
    # not once the first specialist is already queued.
    _validate_operation(operation, nodes, spec["input"])
    # The plan contains no supplied execution status, result or credential.
    cid = conversation_id or model_chat._conversation(authorized, root_key, "Координатор · " + goal.strip()[:100])
    from .intent_planning import execution_mode
    mode = execution_mode(service)
    plan = {"version": VERSION, "goal": goal.strip(), "operation": operation, "root_task_id": str(root_id),
        "root_model_id": model["id"], "root_persona_id": model["persona_id"], "root_operation": "numeric_summary",
        "root_connection_sha256": delegation.connection_digest(service, context, model["id"]),
        "spec": spec, "nodes": nodes, "max_depth": depth, "conversation_id": cid,
        "synthetic": mode == "diagnostic", "limitation": LIMITATION,
        "planned_execution": {"root": mode, "children": [{"index": node["index"], "mode": mode}
            for node in nodes], "actual_evidence": "per-task receipt required"}}
    if _intent_selection is not None:
        plan["intent_selection"] = _intent_selection
    if _supersedes is not None:
        plan["supersedes"] = _supersedes
    control = delegation.create_controller(service, context, identity, plan, source=SOURCE,
        correlation=root_id)
    if control.status in {"cancelled", "failed", "blocked", "review", "succeeded"}:
        _sync_control_intent(service, context, control)
        return projection(authorized, service, identity)
    text = user_message or ("Координатор: " + goal.strip() + "\nДанные: " + json.dumps(spec["input"])
        + "\nПлан: 1. Числовая сводка выбранной моделью; 2. После проверки — отдельное согласование "
        + str(len(nodes)) + " " + profile["plan_phrase"]
        + "; 3. Общий результат, ожидающий вашей приёмки. " + LIMITATION)
    # Chief ingress itself rejects body changes on an existing request. The
    # immutable controller additionally pins targets even after a partial crash.
    model_chat.start(authorized, service, model["id"],
        {"rubric_key": "json_arithmetic", "input_text": json.dumps(spec["input"])}, root_key,
        conversation_id=cid, user_message=text)
    if control.status == "planned":
        control = service._walk(context, control, "ready", "running", "waiting")
    _sync_control_intent(service, context, control)
    return projection(authorized, service, identity)


def plan_request(authorized, service, payload):
    """Read-only clarification, no task, permission grant or dispatch."""
    from .intent_planning import proposal
    context = delegation.gate(authorized, "AI_DELEGATION_V2")
    if context.actor.kind != c.ActorKind.HUMAN:
        raise ContractError("coordinator_human_required")
    return proposal(context, service, payload)


def commission_request(authorized, service, payload, key, **chat):
    """Public seam. Internal operation identifiers are never accepted here."""
    from .intent_planning import resolve
    context = delegation.gate(authorized, "AI_DELEGATION_V2")
    if context.actor.kind != c.ActorKind.HUMAN:
        raise ContractError("coordinator_human_required")
    body, selection = resolve(context, service, payload)
    return commission(authorized, service, body, key, _intent_selection=selection, **chat)


def clarify_request(authorized, service, identity, payload, key, *, expected_revision):
    """Cancel then replace, never edit a finalized Intent or its evidence.

    Validate the full replacement first. Cancellation is authoritative before
    any replacement queues. A retry reuses the same immutable replacement plan.
    """
    from .intent_planning import resolve
    context = delegation.write_admission(authorized)
    if context.actor.kind != c.ActorKind.HUMAN:
        raise ContractError("coordinator_human_required")
    if type(expected_revision) is not int or expected_revision < 1:
        raise ContractError("coordinator_revision_conflict")
    body, selection = resolve(context, service, payload)
    service._access(context, "task")  # existing entitlement/budget admission before cancellation
    control, checkpoint, previous = _load(authorized, service, identity)
    new_id = _id(context, "coordinator:" + _key(key))
    if new_id == control.header.entity_id:
        raise ContractError("coordinator_new_request_key_required")
    supersedes = {"coordinator_id": str(control.header.entity_id), "revision": expected_revision,
                  "plan_sha256": checkpoint["plan_sha256"], "root_task_id": previous["root_task_id"],
                  "intent_id": str(control.intent.entity_id)}
    existing = service.repository.get(context=context, kind=EntityKind.TASK, entity_id=new_id)
    if existing is not None:
        _, _, saved = _load(authorized, service, new_id)
        if saved.get("supersedes") != supersedes:
            raise ContractError("idempotency_conflict")
    elif (type(expected_revision) is not int or
          not (control.header.revision == expected_revision or
               (control.status == "cancelled" and control.header.revision == expected_revision + 1))):
        raise ContractError("coordinator_revision_conflict")
    elif control.status in {"failed", "succeeded", "review"}:
        raise ContractError("coordinator_new_request_required")
    cancel(authorized, service, identity, expected_revision=control.header.revision)
    return commission(authorized, service, body, key, conversation_id=previous["conversation_id"],
                      _intent_selection=selection, _supersedes=supersedes)


def commission_external(service, connection, payload, key):
    """A bounded external assignment in this Coordinator, not a Model alias.

    The connection advertises data skills, never authority. The native service
    pins a compatible low-risk role, then uses the existing durable worker.
    """
    service.admit()
    if service.context.actor.kind != c.ActorKind.HUMAN:
        raise ContractError("coordinator_human_required")
    return service.assign(connection, payload, key)


def _validate_operation(operation, nodes, values):
    """Refuse a plan whose specialists could not actually do the work.

    A breakdown gives every node its own slice of its parent's data, and the
    rubric only accepts 3..20 integers. Walking the tree here means an
    impossible graph is rejected while the person can still change it, rather
    than at the first child. `_graph` has already ordered parents before
    children, so one pass is enough.
    """
    if operation != "numeric_breakdown":
        return
    arrays = {-1: values}
    for node in nodes:
        index, parent = node["index"], node["parent_index"]
        order = [row["index"] for row in nodes if row["parent_index"] == parent]
        arrays[index] = delegation.segment(arrays[parent], order.index(index), len(order))


def validate_plan_link(service, context, plan):
    """Exact server-created commission binding, also checked by each worker."""
    control, checkpoint, commission_plan = delegation.controller(service, context, plan["coordinator_id"], SOURCE)
    if (control.status in {"cancelled", "failed", "blocked", "succeeded"}
            or checkpoint["plan_sha256"] != plan.get("coordinator_plan_sha256")
            or commission_plan["root_task_id"] != plan["root_task"]["entity_id"]
            or commission_plan["nodes"] != plan["nodes"]
            or commission_plan["max_depth"] != plan["max_depth"]
            or commission_plan["conversation_id"] != plan["conversation_id"]
            or plan.get("root_kind") != result_handoff.DATA_KIND):
        raise ContractError("coordinator_plan_changed")
    root = service._get(context, EntityKind.TASK, commission_plan["root_task_id"])
    source = service._json(context, root.checkpoint)
    if source.get("model_id") != commission_plan["root_model_id"] or source.get("spec") != commission_plan["spec"]:
        raise ContractError("coordinator_root_changed")
    return control


def preview(authorized, service, coordinator_id):
    control, checkpoint, plan = _load(authorized, service, coordinator_id)
    context = authorized["context"]
    if control.status in {"cancelled", "failed", "blocked", "succeeded"}:
        raise ContractError("coordinator_stopped")
    proposed = delegation.propose(authorized, service, plan["root_task_id"],
        [node["model_id"] for node in plan["nodes"]], plan["max_depth"], _graph_key(control.header.entity_id),
        parent_indices=[node["parent_index"] for node in plan["nodes"]], commission_id=control.header.entity_id,
        operation=delegation.operation_of(plan))
    if proposed["plan"]["nodes"] != plan["nodes"] or delegation.connection_digest(service, context, plan["root_model_id"]) != plan["root_connection_sha256"]:
        raise ContractError("coordinator_connection_changed")
    from .automation_authority import normalized_plan
    return {**proposed, "coordinator_id": str(control.header.entity_id),
        "approved_plan_sha256": digest(normalized_plan(proposed["plan"])),
        "approved": False, "dispatches": 0, "actions": ["approve_commission"],
        "goal": plan["goal"], "limitation": LIMITATION}


def approve(authorized, service, coordinator_id, payload):
    """Explicit UI approval uses the displayed hash and a fixed expiry on retry."""
    from . import automation_authority
    if type(payload) is not dict or set(payload) != {"approved_plan_sha256", "expires_at", "max_call_cost_usd"}:
        raise ContractError("coordinator_explicit_approval_required")
    proposed = preview(authorized, service, coordinator_id)
    if payload["approved_plan_sha256"] != proposed["approved_plan_sha256"]:
        raise ContractError("coordinator_plan_changed")
    control, _, plan = _load(authorized, service, coordinator_id)
    key = _graph_key(control.header.entity_id)
    grant = automation_authority.approve(authorized, service,
        proposal={"controller_id": proposed["controller_id"], "plan": proposed["plan"]}, kind="delegation",
        expires_at=payload["expires_at"], max_call_cost_usd=payload["max_call_cost_usd"],
        approved_plan_sha256=payload["approved_plan_sha256"], idempotency_key=key)
    graph = delegation.start(authorized, service, plan["root_task_id"], [node["model_id"] for node in plan["nodes"]],
        plan["max_depth"], key, grant_ref=grant, parent_indices=[node["parent_index"] for node in plan["nodes"]],
        commission_id=control.header.entity_id, operation=delegation.operation_of(plan))
    return {**projection(authorized, service, coordinator_id), "graph": graph, "grant_ref": grant,
        "approved": True, "human_accepted": graph["human_accepted"]}


def synchronize(authorized, service, graph_id):
    """Called within an admitted graph reconcile; update only its pinned parent."""
    context = authorized["context"]
    graph, _, plan = delegation.controller(service, context, graph_id)
    if not plan.get("coordinator_id") or graph.status not in {"review", "blocked", "cancelled", "failed"}:
        return
    delegation.authority(service, context, graph.ref(), plan["grant_ref"], "delegation_reconcile")
    control = validate_plan_link(service, context, plan)
    target = "review" if graph.status == "review" else "blocked"
    if control.status == target:
        _sync_control_intent(service, context, control)
        return
    control = service._walk(context, control, "ready", "running")
    control = service._change(context, control, target)
    _sync_control_intent(service, context, control)


def projection(authorized, service, identity):
    control, _, plan = _load(authorized, service, identity)
    context = authorized["context"]
    intent = service._get(context, EntityKind.INTENT, control.intent.entity_id)
    root = service.repository.get(context=context, kind=EntityKind.TASK, entity_id=_uuid(plan["root_task_id"]))
    from .model_service import receipt_provenance
    source = service._json(context, root.checkpoint) if root else {}
    root_origin = receipt_provenance(service._json(context, source["receipt"]) if source.get("receipt") else {})
    graph_id = _id(context, "delegation:" + _key(_graph_key(control.header.entity_id)))
    graph = service.repository.get(context=context, kind=EntityKind.TASK, entity_id=graph_id)
    view = delegation.projection(authorized, service, graph_id) if graph is not None else None
    state = (view["review_state"] if view and view["status"] == "review" else view["status"] if view else
             "awaiting_approval" if root and root.status == "succeeded" else root.status if root else "planned")
    if control.status in {"cancelled", "failed", "blocked", "succeeded"}: state = control.status
    actions = ["preview_commission"] if state == "awaiting_approval" else []
    if control.status not in {"cancelled", "failed", "succeeded"}:
        actions.append("cancel")
    if control.status not in {"cancelled", "failed", "succeeded", "review"} and root and root.status in {"planned", "ready"}:
        actions.append("clarify_commission")
    return {"id": str(control.header.entity_id), "revision": control.header.revision, "source": SOURCE, "version": VERSION,
        "status": control.status, "stage": state, "goal": plan["goal"], "root_task_id": plan["root_task_id"],
        "root_operation": "numeric_summary", "root_status": root.status if root else "not_created",
        "root_source_kind": root_origin["source_kind"], "root_synthetic": root_origin["synthetic"],
        "root_model_id": plan["root_model_id"], "root_persona_id": plan["root_persona_id"], "nodes": plan["nodes"],
        "conversation_id": plan["conversation_id"], "graph": view, "synthetic": root_origin["synthetic"] or bool(view and view["synthetic"]),
        "planned_execution": plan.get("planned_execution"), "planned_synthetic": bool(plan.get("synthetic")),
        "intent_selection": plan.get("intent_selection"), "supersedes": plan.get("supersedes"),
        "request_seed": {"goal": plan["goal"], "input_text": json.dumps(plan["spec"]["input"]),
            "coordinator_model_id": plan["root_model_id"], "target_model_ids": [node["model_id"] for node in plan["nodes"]],
            "parent_indices": [node["parent_index"] for node in plan["nodes"]], "max_depth": plan["max_depth"]},
        "intent_id": str(control.intent.entity_id), "root_intent_id": str(root.intent.entity_id) if root else None,
        "intent_status": intent.status, "intent_expected_status": _intent_target(control),
        "intent_status_consistent": intent.status == _intent_target(control),
        "actions": actions,
        "human_accepted": bool(view and view["human_accepted"]), "professional_quality_assessed": False, "limitation": LIMITATION}


def cancel(authorized, service, identity, *, expected_revision=None):
    context = delegation.write_admission(authorized)
    if context.actor.kind != c.ActorKind.HUMAN:
        raise ContractError("coordinator_human_required")
    control, _, plan = _load(authorized, service, identity)
    if expected_revision is not None and control.header.revision != expected_revision:
        raise ContractError("coordinator_revision_conflict")
    if control.status not in {"cancelled", "failed", "succeeded"}:
        service._change(context, control, "cancelled")
    _sync_control_intent(service, context, control)
    # Stop the parent first so a concurrently claimed child fails its fresh
    # plan-link check. Original receipts and failures remain in history.
    graph_id = _id(context, "delegation:" + _key(_graph_key(control.header.entity_id)))
    if service.repository.get(context=context, kind=EntityKind.TASK, entity_id=graph_id):
        delegation.cancel(authorized, service, graph_id)
    root = service.repository.get(context=context, kind=EntityKind.TASK, entity_id=_uuid(plan["root_task_id"]))
    if root and root.status not in {"succeeded", "failed", "cancelled"}:
        service.cancel(context=context, task_id=root.header.entity_id)
        from .. import worker_router
        worker_router.cancel("wj_aw_model_" + root.header.entity_id.hex, workspace_id=context.scope.workspace_id,
            user_id=authorized["source_scope"]["user_id"])
    return projection(authorized, service, identity)


def after_model(authorized, service, task_id):
    """No worker discovery or authority creation: the caller supplies fresh grant."""
    context = authorized["context"]
    task = service._get(context, EntityKind.TASK, task_id)
    checkpoint = service._json(context, task.checkpoint)
    packet = checkpoint.get("delegation") or {}
    if packet.get("kind") != "delegation_v1": return None
    controller_id = packet.get("controller_id")
    if (authorized.get("automation") is not True
            or authorized.get("automation_controller_id") != controller_id
            or delegation.snapshot(context, authorized.get("automation_grant_ref")) != delegation.snapshot(context, packet.get("grant_ref"))):
        raise ContractError("coordinator_worker_authority_required")
    # Source-bound task identity/lineage is checked again before progression;
    # a fabricated task from the same workspace is not an ingress proof.
    control, _, plan = delegation.controller(service, context, controller_id)
    index = packet.get("node_index")
    if type(index) is not int or not 0 <= index < len(plan["nodes"]) or task.header.entity_id != delegation._child_id(context, control.header.entity_id, index):
        raise ContractError("delegation_lineage_invalid")
    if task.status == "succeeded":
        fresh = delegation._seal_node(service, context, control, plan, index)
        if fresh.wire() != packet or fresh.dependencies != task.dependencies:
            raise ContractError("delegation_lineage_invalid")
    return delegation.reconcile(authorized, service, controller_id)


def completion(authorized, service, controller_id):
    """Immutable aggregate for the existing durable SF Chat delivery adapter."""
    authorized["admit"]()
    context = authorized["context"]
    control, _, plan = delegation.controller(service, context, controller_id)
    if control.status != "review": return None
    view = delegation.projection(authorized, service, controller_id)
    result = view.get("result")
    if not result or result.get("plan_sha256") != digest(plan):
        raise ContractError("coordinator_result_unverified")
    actual = [node["contribution"] for node in view["nodes"] if node.get("contribution")]
    if not delegation._same_contributions(result.get("contributions"), actual) or len(actual) != len(plan["nodes"]):
        raise ContractError("coordinator_result_changed")
    outcome = service._get(context, EntityKind.OUTCOME, view["outcome_id"])
    review = view["human_review"]
    event_record = _completion_event_record(service, context, control, plan, outcome, review)
    event = str(uuid5(event_record.header.entity_id, f"revision:{event_record.header.revision}"))
    provenance = result["provenance"]
    facts = "; ".join(key + " = " + str(value) for key, value in result["facts"].items())
    required = review.get("required_reviews") or []
    reviewed = sum(row["status"] == "accepted" for row in required)
    review_text = ("Результат явно принят владельцем." if view["human_accepted"] else
        "Владелец отклонил общий результат." if review["status"] == "rejected" else
        "Состояние источников изменилось после проверки; прежнее решение сохранено в истории." if review["status"] == "stale" else
        "Сначала проверьте исходную задачу и отдельные вклады (принято " + str(reviewed) + " из " + str(len(required)) + ")." if view["review_state"] == "awaiting_required_reviews" else
        "Приёмка заблокирована; откройте детали проверки." if review["status"] == "blocked" else "Ожидается ваша проверка общего результата.")
    count_label = ("Проверок передачи фактов: " if delegation.operation_of(plan) == "verify_fact_transfer"
                   else "Проверенных разборов участков данных: ")
    text = ("Общий результат Координатора: " + facts + ".\n" + count_label + str(len(actual))
        + ". Локальных тестовых ответов: " + str(provenance["local_test_receipts"])
        + "; ответов с подтверждённым внешним вызовом: " + str(provenance["confirmed_external_receipts"])
        + ".\n" + review_text + " " + LIMITATION)
    envelope = {"scope": authorized["chat_scope"], "conversation_id": plan["conversation_id"],
        "request_id": "delegation-result:" + str(control.header.entity_id) + ":" + event,
        "source_kind": "bounded_delegation_result", "synthetic": view["synthetic"],
        "task_id": str(control.header.entity_id), "outcome_id": view["outcome_id"],
        "correlation_id": str(control.header.correlation_id), "status": "completed" if view["human_accepted"] else "awaiting_review", "text": text,
        "agent_name": "Координатор", "actual_model": None, "provider": None, "provenance": provenance,
        "verification": {"passed": True, "operation": ("verified_fact_transfer" if delegation.operation_of(plan) == "verify_fact_transfer"
                                                        else delegation.operation_of(plan)), "human_accepted": view["human_accepted"],
            "synthetic": view["synthetic"],
            "review_state": view["review_state"], "human_review": review,
            "professional_quality_assessed": False, "proof_sha256": outcome.verification.sha256,
            "contributions": actual, "provenance": provenance},
        "attachments": [], "participation_chain": [{"agent_id": item["persona_id"], "model_id": item["model_id"],
            "role": item["role"], "operation": item["operation"], "task_id": item["task_id"],
            "synthetic": item["synthetic"],
            "operation_role": view["nodes"][index]["operation_role"],
            "agent_role_key": view["nodes"][index]["agent_role_key"], "agent_role_ref": view["nodes"][index]["agent_role_ref"],
            "actual_model": item["provenance"]["actual_model"], "executor": item["provenance"]["executor"]} for index, item in enumerate(actual)]}
    return {"task_id": str(control.header.entity_id), "event_id": event, "checkpoint_sha256": control.checkpoint.sha256,
        "message_id": plan["source_message_id"], "envelope": envelope}


def _completion_event_record(service, context, control, plan, outcome, review):
    """Anchor inbox acknowledgement to a real, visible UnitOfWork event."""
    records = [outcome]
    for item in [review, *review.get("required_reviews", [])]:
        if item.get("evaluation_id"):
            records.append(service._get(context, EntityKind.EVALUATION, item["evaluation_id"]))
    if review["status"] in {"stale", "blocked"} and review.get("blocked_reason") != "delegation_required_reviews_pending":
        # Current-truth changes that have a real AW record (e.g. revocation,
        # disconnect, source update) can emit a distinct durable delivery.
        records.append(control)
        if plan.get("coordinator_id"):
            records.append(service._get(context, EntityKind.TASK, plan["coordinator_id"]))
        for identity in [plan["root_task"]["entity_id"], *[delegation._child_id(context, control.header.entity_id, node["index"]) for node in plan["nodes"]]]:
            task = service._get(context, EntityKind.TASK, identity)
            records.append(task)
            checkpoint = service._json(context, task.checkpoint)
            records.append(service._get(context, EntityKind.MODEL, checkpoint["model_id"]))
        try:
            from .automation_authority import _load
            decision, _, _ = _load(service, context, plan["grant_ref"], operational=False)
            records.append(decision)
        except ContractError:
            pass  # the blocked projection retains the reason; never fake an event
    return max(records, key=lambda record: (record.header.updated_at, record.header.entity_id.hex))


def related_completions(authorized, service, reviewed_task_id):
    """Only read existing scope-owned graphs; never create/reconcile a graph.

    Called after a human review of root, child or aggregate. A broken graph
    cannot roll back that review or prevent another valid graph's delivery.
    """
    authorized["admit"]()
    context = authorized["context"]
    reviewed = service._get(context, EntityKind.TASK, reviewed_task_id)
    deliveries, blocked = [], []
    for task in service._all(context, EntityKind.TASK):
        checkpoint = service._json(context, task.checkpoint)
        if checkpoint.get("source") != delegation.SOURCE: continue
        try:
            control, _, plan = delegation.controller(service, context, task.header.entity_id)
            related = {control.header.entity_id, _uuid(plan["root_task"]["entity_id"])}
            related.update(delegation._child_id(context, control.header.entity_id, node["index"]) for node in plan["nodes"])
            if reviewed.header.entity_id not in related: continue
            saved = completion(authorized, service, control.header.entity_id)
            if saved is not None: deliveries.append(saved)
        except ContractError as error:
            blocked.append({"controller_id": str(task.header.entity_id), "error_code": error.code})
    return {"deliveries": deliveries, "blocked": blocked}


def validate_history_envelope(authorized, envelope):
    from . import domain_gateway
    service = domain_gateway.history_models(authorized)
    saved = completion(authorized, service, envelope.get("task_id"))
    if saved is None or saved["envelope"] != envelope:
        raise ContractError("coordinator_delivery_evidence_changed")
    result_handoff._source_message(authorized, {"conversation_id": envelope["conversation_id"],
        "source_message_id": saved["message_id"]})
    return saved


def delivery_consumer(task_id):
    # A root review event may be shared by multiple approved graphs. Keep each
    # result's idempotent effect separate in the same existing scoped inbox.
    return DELIVERY_CONSUMER + "." + _uuid(task_id).hex


def deliver(authorized, service, *, task_id, event_id, checkpoint_sha256, events, delivery_job=None):
    from ..ai_lab import chief_agent
    saved = completion(authorized, service, task_id)
    if saved is None or saved["event_id"] != event_id or saved["checkpoint_sha256"] != checkpoint_sha256:
        return {"ok": True, "status": "superseded", "task_id": str(task_id)}
    context, identity = authorized["context"], UUID(event_id)
    consumer = delivery_consumer(task_id)
    if service.repository.events.is_acknowledged(context=context, consumer=consumer, event_id=identity):
        return {"ok": True, "status": "delivered", "task_id": str(task_id), "replayed": True}
    authorized["admit"]()
    result = chief_agent.report_agent_world_live_update(saved["envelope"], history_delivery=True, _delivery_job=delivery_job)
    if result.get("ok") is not True: raise ContractError("coordinator_delivery_unconfirmed")
    authorized["admit"]()
    acknowledged = events.acknowledge(context=context, consumer=consumer, event_id=identity)
    if not acknowledged and not service.repository.events.is_acknowledged(context=context, consumer=consumer, event_id=identity):
        raise ContractError("coordinator_delivery_unconfirmed")
    return {"ok": True, "status": "delivered", "task_id": str(task_id), "replayed": result.get("idempotent_replay") is True}


def try_chat(message, *, scope, conversation_id, request_id, source):
    if source != "app": return None
    match = re.fullmatch(r"Координатор\s*:\s*([^\n]{1,400})\n([\s\S]+)", message, re.I)
    if not match: return None
    try:
        payload = json.loads(match[2])
    except (TypeError, ValueError):
        raise ContractError("coordinator_payload_invalid") from None
    if type(payload) is not dict or "goal" in payload:
        raise ContractError("coordinator_payload_invalid")
    from . import domain_gateway
    authorized = domain_gateway.access(scope)
    service = domain_gateway.models(authorized)
    public = {**payload, "goal": match[1]}
    if "selection" not in public:
        clarification = plan_request(authorized, service, public)
        return {"ok": True, "conversation_id": conversation_id, "reply": clarification["question"],
                "status": "clarification_required", "clarification": clarification, "actions": []}
    view = commission_request(authorized, service, public, request_id,
        conversation_id=conversation_id, user_message=message)
    return {"ok": True, "conversation_id": view["conversation_id"], "reply": "Новое поручение Координатору принято. " + LIMITATION,
        "task_id": view["root_task_id"], "coordinator_id": view["id"],
        "actions": [{"name": "real_model_response", "status": "queued", "task_id": view["root_task_id"]}]}
