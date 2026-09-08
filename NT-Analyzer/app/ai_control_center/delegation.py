"""Finite source-bound delegation through existing Task/model/worker stores.

The initial useful operation is verified scalar fact transfer. It is not a
professional strategy review, execution approval, or unrestricted agent loop.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
from uuid import UUID

from .. import worker_router
from . import contracts as c, result_handoff
from .flags import DISABLED, Flag, current_snapshot, resolve
from .model_evaluation import digest, json_bytes, prepare
from .model_service import _id, _key, _uuid
from .states import ContractError, EntityKind


VERSION = "bounded-delegation-v1"
SOURCE = "agent_world_delegation"
PHASE = "delegation_step"
MAX_DEPTH, MAX_FANOUT, MAX_TOTAL = 3, 2, 7


@dataclass(frozen=True)
class SealedDelegation:
    controller: c.EntityRef
    dependencies: tuple[c.EntityRef, ...]
    correlation_id: UUID
    payload: bytes

    def wire(self):
        if (not isinstance(self.controller, c.EntityRef) or type(self.dependencies) is not tuple
                or not 1 <= len(self.dependencies) <= MAX_TOTAL
                or any(not isinstance(ref, c.EntityRef) for ref in self.dependencies)
                or type(self.payload) is not bytes or not 1 <= len(self.payload) <= 65536):
            raise ContractError("delegation_sealed_packet_invalid")
        c.require_uuid(self.correlation_id)
        for ref in self.dependencies: c.require_same_scope(self.controller.scope, ref.scope)
        try:
            value = json.loads(self.payload)
        except (ValueError, UnicodeError):
            raise ContractError("delegation_sealed_packet_invalid") from None
        if type(value) is not dict: raise ContractError("delegation_sealed_packet_invalid")
        return value


def snapshot(context, value):
    if isinstance(value, c.SnapshotRef):
        c.require_same_scope(context.scope, value.scope)
        return value
    if type(value) is not dict or set(value) != {"artifact_id", "sha256", "scope"} or value["scope"] != c.primitive(context.scope):
        raise ContractError("mechanism_approval_reference_required")
    return c.SnapshotRef(scope=context.scope, artifact_id=_uuid(value["artifact_id"]), sha256=value["sha256"])


def utc(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        c.require_utc(parsed)
    except (ValueError, TypeError):
        raise ContractError("mechanism_utc_required") from None
    return parsed


def authority(service, context, controller, grant_ref, operation, model_id=None, *, proposed_plan=None):
    """An artifact is not a grant: only the root's live authority may admit it."""
    reference = snapshot(context, grant_ref)
    if not callable(getattr(service, "mechanism_admit", None)):
        raise ContractError("mechanism_automation_authority_required")
    result = service.mechanism_admit(context=context, controller=controller, grant_ref=reference,
        operation=operation, model_id=model_id, estimated_cost_usd=0.0,
        proposed_plan=json.loads(json_bytes(proposed_plan)) if proposed_plan is not None else None)
    if (type(result) is not dict or result.get("approved_scope") != c.primitive(context.scope)
            or type(result.get("revision")) is not int or result["revision"] < 1
            or result.get("sha256") != reference.sha256
            or utc(result.get("expires_at")) <= datetime.now(timezone.utc)):
        raise ContractError("mechanism_automation_authority_invalid")
    return result


def write_admission(authorized):
    if (not isinstance(authorized, dict) or not isinstance(authorized.get("context"), c.RequestContext)
            or not callable(authorized.get("admit")) or authorized.get("read_only") or authorized.get("session_read_only")):
        raise ContractError("mechanism_write_authority_required")
    authorized["admit"]()
    return authorized["context"]


def gate(authorized, name):
    context = write_admission(authorized)
    flag = getattr(Flag, name, None)
    if (flag is None or context.scope.environment != c.Environment.DEVELOPMENT
            or not resolve(flag, scope=context.scope, snapshot=current_snapshot(authorized)).enabled):
        raise ContractError("mechanism_disabled")
    return context


def subject(authorized):
    """Non-secret lookup identity, never an inherited browser session grant."""
    return {"user_id": authorized["source_scope"]["user_id"], "user_uuid": str(authorized["context"].user_uuid),
            "workspace_id": authorized["context"].scope.workspace_id}


def connection_digest(service, context, model_id):
    # Reuse Execution V2's semantic binding, without test/display timestamps or
    # plaintext credentials. Pin it at proposal time, before future dispatch.
    from .execution_v2 import _connection
    return digest(_connection(service, context, {"model_id": str(model_id)}))


def controller(service, context, identity, source=SOURCE):
    task = service._get(context, EntityKind.TASK, identity)
    checkpoint = service._json(context, task.checkpoint)
    if checkpoint.get("source") != source or checkpoint.get("synthetic") is not False:
        raise ContractError("mechanism_controller_not_found")
    plan = service._json(context, checkpoint["plan"])
    if digest(plan) != checkpoint.get("plan_sha256"):
        raise ContractError("mechanism_plan_changed")
    return task, checkpoint, plan


def create_controller(service, context, identity, plan, *, source, correlation, dependencies=()):
    existing = service.repository.get(context=context, kind=EntityKind.TASK, entity_id=identity)
    if existing is not None:
        task, checkpoint, saved = controller(service, context, identity, source)
        if saved != plan:
            raise ContractError("mechanism_idempotency_conflict")
        return task
    policy = service._put(context, {"version": VERSION, "source": source, "tools": [], "automation": "explicit_separate_approval"})
    role = service._ensure(context, c.AgentRole, _id(context, "role:" + source), correlation, policy,
        role_key=source, responsibilities=service._put(context, {"tools": [], "duty": "bounded durable coordination"}),
        capability_ceiling=("ai_pro_models",), autonomy_ceiling=c.Autonomy.DRAFT)
    role = service._walk(context, role, "active")
    checkpoint = {"source": source, "synthetic": False, "plan": c.primitive(service._put(context, plan)),
                  "plan_sha256": digest(plan)}
    intent = service._ensure(context, c.Intent, _id(context, "intent:" + str(identity)), correlation, policy,
        goal=service._put(context, checkpoint), acceptance=service._put(context, {"source": source,
            "evidence": "independent verified child outcomes", "human_acceptance": "separate"}),
        risk=c.Risk.LOW, autonomy=c.Autonomy.DRAFT,
        budget=c.ExternalRef(authority=c.ExternalAuthority.BUDGET, key="ai_budgets.mechanism." + str(identity), scope=context.scope))
    if service._json(context, intent.goal) != checkpoint:
        raise ContractError("mechanism_partial_intent_conflict")
    if intent.status == "draft" and plan.get("expires_at"):
        intent = service._change(context, intent, deadline=utc(plan["expires_at"]))
    service._walk(context, intent, "ready")
    return service._ensure(context, c.Task, identity, correlation, policy, intent=intent.ref(), role=role.ref(),
        dependencies=dependencies, checkpoint=service._put(context, checkpoint))


def _graph(model_ids, parent_indices, max_depth, root_persona, service, context):
    if type(max_depth) is not int or not 1 <= max_depth <= MAX_DEPTH:
        raise ContractError("delegation_depth_invalid")
    if type(model_ids) is not list or not 1 <= len(model_ids) < MAX_TOTAL:
        raise ContractError("delegation_total_limit")
    parents = [((index - 2) // 2 if index >= 2 else -1) for index in range(len(model_ids))] if parent_indices is None else parent_indices
    if type(parents) is not list or len(parents) != len(model_ids):
        raise ContractError("delegation_graph_invalid")
    nodes, counts = [], {}
    for index, (model_id, parent) in enumerate(zip(model_ids, parents)):
        if type(parent) is not int or not -1 <= parent < index:
            raise ContractError("delegation_cycle_or_forward_reference")
        counts[parent] = counts.get(parent, 0) + 1
        depth = 1 if parent == -1 else nodes[parent]["depth"] + 1
        if counts[parent] > MAX_FANOUT or depth > max_depth:
            raise ContractError("delegation_depth_or_fanout_limit")
        model = service._get(context, EntityKind.MODEL, model_id)
        profile = service._json(context, model.profile)
        persona = service._get(context, EntityKind.PERSONA, profile["persona_id"])
        account = service._get(context, EntityKind.PROVIDER_ACCOUNT, profile["provider_account_id"])
        if model.status != persona.status or model.status != account.status or model.status != "active":
            raise ContractError("delegation_target_inactive")
        ancestors, cursor = {root_persona}, parent
        while cursor != -1:
            ancestors.add(nodes[cursor]["persona_id"])
            cursor = nodes[cursor]["parent_index"]
        if str(persona.header.entity_id) in ancestors:
            raise ContractError("delegation_repeated_ancestor_identity")
        if str(model.header.entity_id) in {node["model_id"] for node in nodes}:
            raise ContractError("delegation_duplicate_target")
        nodes.append({"index": index, "parent_index": parent, "depth": depth,
            "model_id": str(model.header.entity_id), "persona_id": str(persona.header.entity_id),
            "provider_account_id": str(account.header.entity_id), "connection_sha256": connection_digest(service, context, model.header.entity_id)})
    return nodes


def _child_id(context, controller_id, index):
    return _id(context, "model-task:" + _key(_child_key(controller_id, index)))


def _child_key(controller_id, index):
    return "delegate." + str(controller_id) + "." + str(index)


def _verified(service, context, identity):
    # A status/score alone is not enough for a child to unlock descendants.
    data = result_handoff.verified_model_data(service, context, identity, allow_dependent=True)
    task = service._get(context, EntityKind.TASK, identity)
    checkpoint = service._json(context, task.checkpoint)
    outcome = service._get(context, EntityKind.OUTCOME, _id(context, "outcome:" + str(identity)))
    proof = service._json(context, outcome.verification)
    if (task.status != "succeeded" or outcome.status != "verified" or proof.get("passed") is not True
            or proof.get("synthetic") not in {False, data["synthetic"]} or proof.get("self_scored") is not False
            or proof.get("evaluator") != "independent_local_evidence_verifier"
            or checkpoint.get("synthetic") is not False or checkpoint.get("source") != "real_model_task"
            or checkpoint.get("spec", {}).get("rubric_key") != "extract_facts"
            or proof.get("input_sha256") != digest(checkpoint["spec"])
            or proof.get("task_id") != str(task.header.entity_id) or proof.get("model_id") != checkpoint.get("model_id")
            or proof.get("receipt") != checkpoint.get("receipt")):
        raise ContractError("delegation_verified_parent_required")
    return task, checkpoint, outcome


def _seal_node(service, context, control, plan, index):
    if plan.get("coordinator_id"):
        from .coordinator import validate_plan_link
        validate_plan_link(service, context, plan)
    if type(index) is not int or not 0 <= index < len(plan["nodes"]):
        raise ContractError("delegation_node_invalid")
    node = plan["nodes"][index]
    root = service._get(context, EntityKind.TASK, plan["root_task"]["entity_id"])
    if c.primitive(root.ref()) != plan["root_task"]:
        raise ContractError("delegation_root_source_changed")
    if node["parent_index"] == -1:
        # Initial human ingress derived these allowlisted facts. A later
        # authenticated service validates the immutable evidence, never forges
        # a Human context to call the legacy one-click handoff entry point.
        checkpoint = service._json(context, root.checkpoint)
        sealed = plan["root_source"]
        if plan.get("root_kind") == result_handoff.DATA_KIND:
            fresh = result_handoff.verified_model_data(service, context, root.header.entity_id)
            if not result_handoff.same_data_source(sealed, fresh):
                raise ContractError("delegation_root_evidence_changed")
        else:
            # Application/NinjaTrader/PNG verification is deliberately not
            # routed through the non-trading data verifier or relaxed here.
            from .social_publication import SocialPublicationService
            outcome, _ = SocialPublicationService(service.repository)._outcome(context, sealed["source_outcome_id"])
            if (root.status != "succeeded" or checkpoint.get("source") != "real_model_task"
                    or checkpoint.get("synthetic") is not False or not checkpoint.get("application_request")
                    or checkpoint.get("conversation_id") != plan["conversation_id"]
                    or checkpoint.get("message_id") != plan["source_message_id"]
                    or outcome.verification.sha256 != sealed["source_proof_sha256"]
                    or sorted(ref.sha256 for ref in outcome.evidence) != sealed["artifact_hashes"]
                    or digest(sealed["facts"]) != sealed["facts_sha256"]):
                raise ContractError("delegation_root_evidence_changed")
        parent, facts, outcome_id = root, sealed["facts"], sealed["source_outcome_id"]
    else:
        parent, checkpoint, outcome = _verified(service, context, _child_id(context, control.header.entity_id, node["parent_index"]))
        packet = checkpoint.get("delegation") or {}
        if (packet.get("controller_id") != str(control.header.entity_id) or packet.get("node_index") != node["parent_index"]
                or packet.get("plan_sha256") != digest(plan)):
            raise ContractError("delegation_parent_lineage_invalid")
        facts, outcome_id = checkpoint["spec"]["input"], str(outcome.header.entity_id)
    model = service._get(context, EntityKind.MODEL, node["model_id"])
    profile = service._json(context, model.profile)
    persona = service._get(context, EntityKind.PERSONA, node["persona_id"])
    account = service._get(context, EntityKind.PROVIDER_ACCOUNT, node["provider_account_id"])
    if (model.status != "active" or persona.status != "active" or account.status != "active"
            or profile["persona_id"] != node["persona_id"] or profile["provider_account_id"] != node["provider_account_id"]
            or connection_digest(service, context, node["model_id"]) != node.get("connection_sha256")):
        raise ContractError("delegation_target_changed")
    packet = {"kind": "delegation_v1", "controller_id": str(control.header.entity_id), "node_index": index,
        "plan_sha256": digest(plan), "parent_task": c.primitive(parent.ref()), "source_outcome_id": outcome_id,
        "target_model_id": node["model_id"], "target_persona_id": node["persona_id"],
        "conversation_id": plan["conversation_id"], "source_message_id": plan["source_message_id"],
        "grant_ref": plan["grant_ref"], "facts": facts, "facts_sha256": digest(facts),
        "synthetic": False, "limitation": result_handoff.DATA_LIMITATION if plan.get("root_kind") == result_handoff.DATA_KIND else result_handoff.LIMITATION}
    return SealedDelegation(control.ref(), (parent.ref(),), control.header.correlation_id, json_bytes(packet))


def validate_constructor(service, context, value, *, model_id, spec, conversation_id):
    if not isinstance(value, SealedDelegation):
        raise ContractError("delegation_sealed_constructor_required")
    packet = value.wire()
    if packet.get("kind") == "schedule_v1":
        from .scheduler import validate_constructor as validate_schedule
        return validate_schedule(service, context, value, model_id=model_id, spec=spec, conversation_id=conversation_id)
    control, _, plan = controller(service, context, value.controller.entity_id)
    result_handoff.admit_data_source(context, plan["root_source"])
    authorized = getattr(service, "mechanism_authorized", None)
    if not isinstance(authorized, dict) or authorized.get("context") != context:
        raise ContractError("delegation_fresh_authority_required")
    gate(authorized, "AI_DELEGATION_V2")
    if control.status not in {"planned", "ready", "running", "waiting"}:
        raise ContractError("delegation_controller_stopped")
    fresh = _seal_node(service, context, control, plan, packet.get("node_index"))
    if (fresh.payload != value.payload or fresh.dependencies != value.dependencies or fresh.correlation_id != value.correlation_id
            or str(model_id) != packet["target_model_id"] or conversation_id != packet["conversation_id"]
            or spec != prepare("extract_facts", "\n".join(key + "=" + item for key, item in packet["facts"].items()))):
        raise ContractError("delegation_source_changed")
    _admit_sources(service, context, control, plan, packet["node_index"])
    authority(service, context, control.ref(), plan["grant_ref"], "delegation_step", str(model_id))
    result_handoff._source_message({"context": context, "chat_scope": service.chat_scope}, packet)
    return packet


def validate_execution(service, context, task, checkpoint):
    packet = checkpoint.get("delegation")
    if type(packet) is not dict:
        raise ContractError("delegation_packet_required")
    if packet.get("kind") == "schedule_v1":
        from .scheduler import validate_execution as validate_schedule
        return validate_schedule(service, context, task, checkpoint)
    control, _, plan = controller(service, context, packet.get("controller_id"))
    fresh = _seal_node(service, context, control, plan, packet.get("node_index"))
    if (packet != fresh.wire() or task.dependencies != fresh.dependencies
            or task.header.correlation_id != fresh.correlation_id
            or task.header.entity_id != _child_id(context, control.header.entity_id, packet["node_index"])):
        raise ContractError("delegation_lineage_invalid")
    return validate_constructor(service, context, fresh, model_id=checkpoint["model_id"],
        spec=checkpoint["spec"], conversation_id=checkpoint["conversation_id"])


def _admit_sources(service, context, control, plan, index):
    result_handoff.admit_data_source(context, plan["root_source"])
    parent = plan["nodes"][index]["parent_index"]
    if parent != -1:
        source = result_handoff.verified_model_data(service, context,
            _child_id(context, control.header.entity_id, parent), allow_dependent=True)
        result_handoff.admit_data_source(context, source)


def _queue(authorized, service, control, plan, index):
    _admit_sources(service, authorized["context"], control, plan, index)
    authority(service, authorized["context"], control.ref(), plan["grant_ref"], "delegation_queue", plan["nodes"][index]["model_id"])
    identity = "wj_aw_delegate_" + control.header.entity_id.hex + "_" + str(index)
    payload = {"phase": PHASE, "scope": subject(authorized), "controller_id": str(control.header.entity_id),
               "node_index": index, "plan_sha256": digest(plan), "grant_ref": plan["grant_ref"]}
    try:
        return worker_router.enqueue("agent_world_followup", payload, job_id=identity, max_attempts=3, timeout_sec=60,
            user_id=authorized["source_scope"]["user_id"], workspace_id=authorized["context"].scope.workspace_id, priority=75)
    except sqlite3.IntegrityError:
        old = worker_router.get(identity, workspace_id=authorized["context"].scope.workspace_id) or {}
        if old.get("kind") != "agent_world_followup" or old.get("payload") != payload:
            raise ContractError("delegation_job_conflict") from None
        return old


def propose(authorized, service, source_task_id, target_model_ids, max_depth, idempotency_key, *, parent_indices=None, commission_id=None):
    """Read-only exact proposal; it is neither approval nor a queued action."""
    context = gate(authorized, "AI_DELEGATION_V2")
    if context.actor.kind != c.ActorKind.HUMAN:
        raise ContractError("delegation_initial_human_approval_required")
    key = _key(idempotency_key)
    identity = _id(context, "delegation:" + key)
    if type(target_model_ids) is not list or not target_model_ids:
        raise ContractError("delegation_targets_required")
    root = service._get(context, EntityKind.TASK, source_task_id)
    checkpoint = service._json(context, root.checkpoint)
    data_root = not checkpoint.get("application_request")
    source = (result_handoff.verified_model_data(service, context, source_task_id) if data_root
              else result_handoff._seal(service, context, source_task_id, target_model_ids[0]).wire())
    result_handoff.admit_data_source(context, source)
    result_handoff._source_message(authorized, source)
    plan = {"version": VERSION, "root_task": source["parent_task"], "root_source": {key: source[key] for key in
        ("source_outcome_id", "source_evaluation_id", "source_proof_sha256", "artifact_hashes", "facts", "facts_sha256")},
        "nodes": _graph(target_model_ids, parent_indices, max_depth, source["source_persona_id"], service, context),
        "max_depth": max_depth, "conversation_id": source["conversation_id"], "source_message_id": source["source_message_id"],
        "synthetic": False}
    if data_root:
        plan.update(root_kind=result_handoff.DATA_KIND, root_source=source)
        for node in plan["nodes"]:
            node.update(operation="verify_fact_transfer", role="fact_transfer_checker",
                operation_label="Проверка точности передачи фактов", produces_new_analysis=False)
    if commission_id is not None:
        from . import coordinator
        control, checkpoint, _ = controller(service, context, commission_id, coordinator.SOURCE)
        if identity != _id(context, "delegation:" + _key(coordinator._graph_key(control.header.entity_id))):
            raise ContractError("coordinator_plan_changed")
        plan.update(coordinator_id=str(control.header.entity_id), coordinator_plan_sha256=checkpoint["plan_sha256"])
        coordinator.validate_plan_link(service, context, plan)
    return {"controller_id": str(identity), "plan": plan}


def start(authorized, service, source_task_id, target_model_ids, max_depth, idempotency_key, *, grant_ref, parent_indices=None, commission_id=None):
    proposed = propose(authorized, service, source_task_id, target_model_ids, max_depth, idempotency_key,
        parent_indices=parent_indices, commission_id=commission_id)
    context = authorized["context"]
    identity = _uuid(proposed["controller_id"])
    plan = {**proposed["plan"], "grant_ref": c.primitive(snapshot(context, grant_ref))}
    expected = c.EntityRef(kind=EntityKind.TASK, entity_id=identity, revision=1, scope=context.scope)
    approved = authority(service, context, expected, plan["grant_ref"], "delegation_create", proposed_plan=plan)
    plan["expires_at"] = approved["expires_at"]
    root = service._get(context, EntityKind.TASK, source_task_id)
    control = create_controller(service, context, identity, plan, source=SOURCE,
                                correlation=root.header.correlation_id, dependencies=(root.ref(),))
    if control.status == "planned": service._walk(context, control, "ready")
    return reconcile(authorized, service, identity)


def reconcile(authorized, service, identity):
    context = gate(authorized, "AI_DELEGATION_V2")
    control, _, plan = controller(service, context, identity)
    if control.status in {"cancelled", "failed", "blocked", "review", "succeeded"}:
        if plan.get("coordinator_id") and control.status == "review":
            from .coordinator import synchronize
            synchronize(authorized, service, identity)
        return projection(authorized, service, identity)
    authority(service, context, control.ref(), plan["grant_ref"], "delegation_reconcile")
    result_handoff.admit_data_source(context, plan["root_source"])
    verified, stopped = [], False
    ready_nodes = []
    for node in plan["nodes"]:
        child_id = _child_id(context, identity, node["index"])
        child = service.repository.get(context=context, kind=EntityKind.TASK, entity_id=child_id)
        job = worker_router.get("wj_aw_delegate_" + _uuid(identity).hex + "_" + str(node["index"]), workspace_id=context.scope.workspace_id)
        model_job = worker_router.get("wj_aw_model_" + child_id.hex, workspace_id=context.scope.workspace_id)
        if any(row and row.get("status") in {"failed", "cancelled"} for row in (job, model_job)):
            stopped = True
        if child is not None:
            if child.status == "succeeded":
                _, checkpoint, outcome = _verified(service, context, child_id)
                fresh = _seal_node(service, context, control, plan, node["index"])
                if checkpoint.get("delegation") != fresh.wire() or child.dependencies != fresh.dependencies:
                    raise ContractError("delegation_lineage_invalid")
                verified.append(outcome)
            elif child.status in {"blocked", "cancelled", "failed", "review"}:
                stopped = True
            continue
        parent = node["parent_index"]
        if parent == -1 or any(outcome.task.entity_id == _child_id(context, identity, parent) for outcome in verified):
            ready_nodes.append(node["index"])
    control = service._get(context, EntityKind.TASK, identity)
    if stopped:
        if control.status == "waiting": control = service._change(context, control, "ready")
        service._change(context, control, "blocked")
    elif len(verified) == len(plan["nodes"]):
        control = service._walk(context, control, "ready", "running")
        evidence = tuple(outcome.verification for outcome in verified)
        contributions = [_contribution(service, context, row.task.entity_id) for row in verified]
        provenance = _provenance(plan, contributions)
        proof = service._put(context, {"source": SOURCE, "plan_sha256": digest(plan), "child_outcomes": [c.primitive(row.ref()) for row in verified],
            "verified_fact_transfer": True, "human_accepted": False, "professional_quality_assessed": False,
            "synthetic": bool(provenance["local_test_receipts"]),
            "root_kind": plan.get("root_kind", "application_result"), "root_source": plan["root_source"],
            "contributions": contributions, "provenance": provenance,
            "facts": plan["root_source"]["facts"], "produces_new_analysis": False})
        outcome = service._ensure(context, c.Outcome, _id(context, "delegation-outcome:" + str(identity)), control.header.correlation_id,
            control.header.policy, task=control.ref(), evidence=evidence, execution=None)
        if outcome.status == "pending": service._change(context, outcome, "verified", verification=proof)
        service._change(context, control, "review")
    else:
        for index in ready_nodes:
            _queue(authorized, service, control, plan, index)
    if plan.get("coordinator_id"):
        from .coordinator import synchronize
        synchronize(authorized, service, identity)
    return projection(authorized, service, identity)


def execute(authorized, service, job, cancelled, heartbeat):
    from .followup_chat import _claim
    context = gate(authorized, "AI_DELEGATION_V2")
    payload = job.get("payload") or {}
    if set(payload) != {"phase", "scope", "controller_id", "node_index", "plan_sha256", "grant_ref"} or payload.get("phase") != PHASE:
        raise ContractError("delegation_job_invalid")
    if payload["scope"] != subject(authorized):
        raise ContractError("delegation_job_scope_invalid")
    heartbeat()
    _claim(authorized, job)
    control, _, plan = controller(service, context, payload["controller_id"])
    result_handoff.admit_data_source(context, plan["root_source"])
    if cancelled() or control.status in {"cancelled", "failed", "blocked", "succeeded"}:
        raise ContractError("delegation_cancelled_or_stopped")
    if payload["plan_sha256"] != digest(plan) or payload["grant_ref"] != plan["grant_ref"]:
        raise ContractError("delegation_job_source_changed")
    index = payload["node_index"]
    if job.get("worker_job_id", job.get("id")) != "wj_aw_delegate_" + control.header.entity_id.hex + "_" + str(index):
        raise ContractError("delegation_job_identity_invalid")
    if control.status == "review":
        child, checkpoint, _ = _verified(service, context, _child_id(context, control.header.entity_id, index))
        packet = checkpoint.get("delegation") or {}
        if (packet.get("controller_id") != str(control.header.entity_id) or packet.get("node_index") != index
                or packet.get("plan_sha256") != digest(plan)):
            raise ContractError("delegation_lineage_invalid")
        authority(service, context, control.ref(), plan["grant_ref"], "delegation_step", packet["target_model_id"])
        return {"ok": True, "status": "child_completed", "task_id": str(child.header.entity_id),
                "controller_id": str(control.header.entity_id), "replayed": True, "provider_dispatch": False}
    seal = _seal_node(service, context, control, plan, index)
    node, packet = plan["nodes"][index], seal.wire()
    control = service._walk(context, control, "ready", "running")
    authority(service, context, control.ref(), plan["grant_ref"], "delegation_step", node["model_id"])
    if cancelled(): raise ContractError("delegation_cancelled_or_stopped")
    heartbeat()
    _claim(authorized, job)
    service.chat_scope = authorized["chat_scope"]
    service.mechanism_authorized = authorized
    detail = service.start_task(context=context, model_id=node["model_id"],
        payload={"rubric_key": "extract_facts", "input_text": "\n".join(key + "=" + value for key, value in packet["facts"].items())},
        idempotency_key=_child_key(control.header.entity_id, index), conversation_id=plan["conversation_id"],
        message_id=plan["source_message_id"], _delegation=seal)
    current = service._get(context, EntityKind.TASK, control.header.entity_id)
    if current.status == "running": service._change(context, current, "waiting")
    return {"ok": True, "status": "child_queued", "controller_id": str(control.header.entity_id), "task_id": detail["id"],
            "node_index": index, "human_accepted": False, "synthetic": False}


def _contribution(service, context, identity):
    proof = result_handoff.verified_model_data(service, context, identity, allow_dependent=True)
    return {"task_id": str(identity), "operation": "verify_fact_transfer", "role": "fact_transfer_checker",
        "operation_label": "Проверка точности передачи фактов", "produces_new_analysis": False,
        "contribution_id": proof["source_contribution_id"], "evaluation_id": proof["source_evaluation_id"],
        "outcome_id": proof["source_outcome_id"], "proof_sha256": proof["source_proof_sha256"],
        "checks": proof["checks"], "provenance": proof["provenance"], "facts_sha256": proof["facts_sha256"],
        "task_class": proof["task_class"], "model_id": proof["source_model_id"], "persona_id": proof["source_persona_id"],
        "synthetic": proof["synthetic"], "human_accepted": False, "professional_quality_assessed": False}


def _same_contributions(saved, current):
    """Compatibility for the missing historical local marker only."""
    if not isinstance(saved, list) or len(saved) != len(current): return False
    for old, new in zip(saved, current):
        if old == new: continue
        if (not isinstance(old, dict) or "synthetic" in old or {**old, "synthetic": new["synthetic"]} != new):
            return False
    return True


def _result_synthetic(result):
    return bool((result or {}).get("synthetic") is True or ((result or {}).get("provenance") or {}).get("local_test_receipts"))


def _same_result(saved, expected):
    if not isinstance(saved, dict): return False
    normalized = dict(saved)
    if not _same_contributions(saved.get("contributions"), expected["contributions"]): return False
    normalized["contributions"] = expected["contributions"]
    if (saved.get("synthetic") is False and expected["synthetic"] is True
            and all("synthetic" not in row for row in saved["contributions"])):
        normalized["synthetic"] = True
    return normalized == expected


def _provenance(plan, contributions):
    rows = [row["provenance"] for row in contributions]
    if plan["root_source"].get("provenance"):
        rows = [plan["root_source"]["provenance"], *rows]
    modes = sorted({row["mode"] for row in rows})
    return {"mode": modes[0] if len(modes) == 1 else "mixed", "modes": modes,
        "local_test_receipts": sum(row["mode"] == "local_test_executor" for row in rows),
        "provider_receipts": sum(row["mode"] == "provider_receipt" for row in rows),
        "confirmed_external_receipts": sum(row.get("live_provider_confirmed") is True for row in rows),
        "professional_quality_assessed": False, "rating_effect": "none"}


def projection(authorized, service, identity):
    authorized["admit"]()
    context = authorized["context"]
    control, _, plan = controller(service, context, identity)
    nodes = []
    for node in plan["nodes"]:
        identity = _child_id(context, control.header.entity_id, node["index"])
        task = service.repository.get(context=context, kind=EntityKind.TASK, entity_id=identity)
        job = worker_router.get("wj_aw_delegate_" + control.header.entity_id.hex + "_" + str(node["index"]), workspace_id=context.scope.workspace_id)
        child_job = worker_router.get("wj_aw_model_" + identity.hex, workspace_id=context.scope.workspace_id)
        item = {**node, "task_id": str(identity), "status": task.status if task else "pending_dependency",
            "coordination_job_status": job.get("status") if job else None, "model_job_status": child_job.get("status") if child_job else None}
        if task:
            checkpoint = service._json(context, task.checkpoint)
            item.update(task_class=checkpoint.get("spec", {}).get("rubric_key"), error_code=checkpoint.get("error_code"))
            role = service.repository.get_revision(context=context, kind=EntityKind.AGENT_ROLE,
                entity_id=task.role.entity_id, revision=task.role.revision)
            if role is None: raise ContractError("delegation_role_missing")
            item.update(operation_role=node.get("role", "fact_transfer_checker"),
                agent_role_key=role.role_key, agent_role_ref=c.primitive(role.ref()))
        if task and task.status == "succeeded":
            try:
                item["contribution"] = _contribution(service, context, identity)
            except ContractError as error:
                # Preserve the failed evidence in history instead of making a
                # successful-looking aggregate from incomplete contributions.
                item["contribution_error"] = error.code
        nodes.append(item)
    outcome = service.repository.get(context=context, kind=EntityKind.OUTCOME,
        entity_id=_id(context, "delegation-outcome:" + str(control.header.entity_id)))
    result = service._json(context, outcome.verification) if outcome and outcome.status == "verified" else None
    from . import task_review
    review = (task_review.aggregate_projection(authorized, service, control) if outcome else
        {"status": "not_required", "task_revision": control.header.revision, "required_reviews": [], "quality_claim": False})
    review_state = ("awaiting_required_reviews" if review.get("blocked_reason") == "delegation_required_reviews_pending" else
        "awaiting_review" if review["status"] == "pending" else review["status"] if outcome else "not_ready")
    return {"id": str(control.header.entity_id), "revision": control.header.revision,
        "status": control.status, "source": SOURCE, "nodes": nodes,
        "root_task": plan["root_task"], "plan_sha256": digest(plan), "conversation_id": plan["conversation_id"],
        "max_depth": plan["max_depth"], "max_fanout": MAX_FANOUT, "total_node_limit": MAX_TOTAL,
        "human_accepted": review["status"] == "accepted", "human_review": review,
        "actions": ["review_result"] if review["status"] == "pending" else [],
        "professional_quality_assessed": False, "synthetic": _result_synthetic(result) or bool(plan["root_source"].get("synthetic") or
            (plan["root_source"].get("provenance") or {}).get("mode") == "local_test_executor"),
        "root_kind": plan.get("root_kind", "application_result"), "result": result,
        "outcome_id": str(outcome.header.entity_id) if outcome else None,
        "review_state": review_state}


def cancel(authorized, service, identity):
    # A kill switch or revoked paid entitlement must not prevent stopping work.
    context = write_admission(authorized)
    control, _, plan = controller(service, context, identity)
    if control.status not in {"cancelled", "failed", "succeeded"}:
        service._change(context, control, "cancelled")
    for node in plan["nodes"]:
        child_id = _child_id(context, identity, node["index"])
        child = service.repository.get(context=context, kind=EntityKind.TASK, entity_id=child_id)
        for job_id in ("wj_aw_delegate_" + _uuid(identity).hex + "_" + str(node["index"]), "wj_aw_model_" + child_id.hex):
            if worker_router.get(job_id, workspace_id=context.scope.workspace_id):
                worker_router.cancel(job_id, workspace_id=context.scope.workspace_id, user_id=authorized["source_scope"]["user_id"])
        if child and child.status not in {"succeeded", "failed", "cancelled"}:
            service.cancel(context=context, task_id=child_id)
    return projection(authorized, service, identity)
