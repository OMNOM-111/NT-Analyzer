"""Explicit immutable human review of one exact model/application result.

It is a human signal, never model calibration, execution authorization or a
rewrite of the source task/outcome. Reads never create or close reviews.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import contracts as c
from .model_contracts import Evaluation
from .model_evaluation import digest
from .states import ContractError, EntityKind

RUBRIC = "human_review"


def _identity(service, context, task):
    from .model_service import _id
    return _id(context, f"human-review:{task.header.entity_id}:{task.header.revision}")


def fingerprint(task, checkpoint, dto):
    return digest({"task": c.primitive(task.ref()),
                   "receipt": checkpoint.get("receipt"),
                   "application": dto.get("application_result"),
                   "evaluation_id": dto.get("evaluation_id"),
                   "application_evaluation_id": dto.get("application_evaluation_id")})


def projection(service, context, task, checkpoint, dto):
    if (dto.get("status") != "succeeded" or not dto.get("evaluation_id")
            or dto.get("task_class") in {"connection_exact", "court_vote"}):
        return {"status": "not_required", "quality_claim": False}
    if checkpoint.get("application_request") and not dto.get("application_evaluation_id"):
        return {"status": "not_required", "quality_claim": False}
    execution = dto.get("execution_v2") or {}
    blocked_reason = "execution_v2_not_verified" if execution and execution.get("status") != "succeeded" else None
    source_hash = fingerprint(task, checkpoint, dto)
    found = service.repository.get(context=context, kind=EntityKind.EVALUATION,
                                    entity_id=_identity(service, context, task))
    if found is None:
        return {"status": "blocked" if blocked_reason else "pending", "source_sha256": source_hash,
                "blocked_reason": blocked_reason, "task_revision": task.header.revision, "quality_claim": False}
    proof = service._json(context, found.evidence)
    expected_outcome = (dto.get("application_result") or {}).get("outcome_id") or dto.get("outcome_id")
    if (found.rubric_key != RUBRIC or found.task != task.ref()
            or found.header.created_by.kind != c.ActorKind.HUMAN
            or found.header.owner_user_uuid != context.user_uuid
            or str(found.model.entity_id) != checkpoint["model_id"]
            or str(found.outcome.entity_id) != expected_outcome
            or proof.get("version") != "human-review-v1"
            or proof.get("task_revision") != task.header.revision
            or proof.get("origin") != "explicit_human_review" or proof.get("quality_claim") is not False
            or proof.get("source_sha256") != source_hash
            or proof.get("decision") not in {"accept", "reject"}
            or not isinstance(proof.get("comment"), str) or len(proof["comment"]) > 2000
            or proof.get("reviewer_user_uuid") != str(found.header.created_by.actor_id)):
        raise ContractError("task_review_evidence_mismatch")
    return {"status": "accepted" if proof["decision"] == "accept" else "rejected",
            "source_sha256": source_hash, "task_revision": task.header.revision,
            "evaluation_id": str(found.header.entity_id), "reviewer_user_uuid": proof["reviewer_user_uuid"],
            "reviewed_at": found.header.created_at.isoformat(), "comment": proof["comment"],
            "origin": "explicit_human_review", "quality_claim": False, "blocked_reason": blocked_reason}


def _aggregate_authority(authorized, service, control, plan):
    """Read current eligibility, without minting/replaying an operational grant."""
    from .. import ai_budgets
    from . import automation_authority as authority, delegation, live_gateway
    from .flags import Flag, resolve
    context = authorized["context"]
    state = {"grant_ref": plan["grant_ref"]}
    try:
        decision, proof, ref = authority._load(service, context, plan["grant_ref"], operational=False)
        state.update(decision=c.primitive(decision.ref()), decision_status=decision.status,
                     expires_at=proof["expires_at"], expired=delegation.utc(proof["expires_at"]) <= datetime.now(timezone.utc))
        _, current = authority._bound_subject(authorized, read_only=True)
        if (proof["controller_id"] != str(control.header.entity_id) or proof["user_id"] != current["user_id"]
                or proof["plan_sha256"] != digest(authority.normalized_plan(plan))):
            raise ContractError("automation_plan_changed")
        state["entitled"] = all(current["capabilities"].get(key) is True for key in ("ai_lab", "ai_pro_models", "ai_automation"))
        state["flag_enabled"] = resolve(Flag.AI_DELEGATION_V2, scope=context.scope,
            snapshot=live_gateway.flag_snapshot(context)).enabled
        state["budget_admitted"] = ai_budgets.check_budget(context.scope.workspace_id, 0.0).get("ok") is True
        if decision.status != "approved": raise ContractError("automation_approval_revoked")
        if state["expired"]: raise ContractError("automation_approval_expired")
        if not state["entitled"]: raise ContractError("automation_entitlement_required")
        if not state["flag_enabled"]: raise ContractError("automation_disabled")
        if not state["budget_admitted"]: raise ContractError("automation_budget_denied")
        # This existing registry reader checks actual trust/session state. It
        # never grants permissions, updates a device or creates a new session.
        authority.device_binding(current, saved=proof["device"])
        state["device_confirmed"] = True
        if current["membership_role"] != "owner": raise ContractError("automation_workspace_access_denied")
    except ContractError as error:
        state["blocked_reason"] = error.code
    return state


def _aggregate_snapshot(authorized, service, task):
    """Full current graph truth; neither saved green DTOs nor raw scores suffice."""
    from . import delegation, result_handoff
    from .model_service import _id
    context = authorized["context"]
    control, checkpoint, plan = delegation.controller(service, context, task.header.entity_id)
    outcome = service.repository.get(context=context, kind=EntityKind.OUTCOME,
        entity_id=_id(context, "delegation-outcome:" + str(control.header.entity_id)))
    result = service._json(context, outcome.verification) if outcome and outcome.status == "verified" else None
    snapshot = {"version": "bounded-delegation-human-review-v1", "controller": c.primitive(control.ref()),
        "checkpoint_sha256": control.checkpoint.sha256, "plan_sha256": digest(plan), "plan": plan,
        "outcome": c.primitive(outcome.ref()) if outcome else None,
        "outcome_verification_sha256": outcome.verification.sha256 if result else None,
        "result": result, "sources": [], "required_reviews": [], "errors": []}
    errors, required = snapshot["errors"], snapshot["required_reviews"]
    if control.status != "review": errors.append("delegation_result_not_ready")
    root = service._get(context, EntityKind.TASK, plan["root_task"]["entity_id"])
    root_checkpoint = service._json(context, root.checkpoint)
    model = service._get(context, EntityKind.MODEL, root_checkpoint["model_id"])
    snapshot["model"] = c.primitive(model.ref())
    identities = [(root.header.entity_id, "numeric_summary" if plan.get("root_kind") == result_handoff.DATA_KIND else "application_result")]
    identities.extend((delegation._child_id(context, control.header.entity_id, node["index"]), "verify_fact_transfer") for node in plan["nodes"])
    contributions, child_outcomes = [], []
    for index, (identity, operation) in enumerate(identities):
        source = service.repository.get(context=context, kind=EntityKind.TASK, entity_id=identity)
        item = {"task_id": str(identity), "operation": operation, "status": "not_ready"}
        required.append(item)
        if source is None:
            errors.append("delegation_source_missing")
            continue
        source_checkpoint = service._json(context, source.checkpoint)
        entry = {"task": c.primitive(source.ref()), "checkpoint_sha256": source.checkpoint.sha256}
        snapshot["sources"].append(entry)
        try:
            detail = service.task_detail(context=context, task_id=identity)
            review = detail["human_review"]
            item.update(review)
            entry["human_review"] = review
            entry["model"] = c.primitive(service._get(context, EntityKind.MODEL, source_checkpoint["model_id"]).ref())
            if index:
                _, _, child_outcome = delegation._verified(service, context, identity,
                    operation=delegation.operation_of(plan))
                fresh = delegation._seal_node(service, context, control, plan, index - 1)
                if source_checkpoint.get("delegation") != fresh.wire() or source.dependencies != fresh.dependencies:
                    raise ContractError("delegation_lineage_invalid")
                entry["source"] = result_handoff.verified_model_data(service, context, identity, allow_dependent=True)
                contributions.append(delegation._contribution(service, context, identity,
                    operation=delegation.operation_of(plan)))
                child_outcomes.append(child_outcome)
            elif c.primitive(source.ref()) != plan["root_task"]:
                raise ContractError("delegation_root_source_changed")
            elif plan.get("root_kind") == result_handoff.DATA_KIND:
                entry["source"] = result_handoff.verified_model_data(service, context, identity)
                if not result_handoff.same_data_source(plan["root_source"], entry["source"]):
                    raise ContractError("delegation_root_evidence_changed")
        except ContractError as error:
            entry["blocked_reason"] = error.code
            errors.append(error.code)
    try:
        result_handoff._source_message(authorized, {"conversation_id": plan["conversation_id"], "source_message_id": plan["source_message_id"]})
        if plan.get("coordinator_id"):
            from . import coordinator
            commission = coordinator.validate_plan_link(service, context, plan)
            commission_plan = service._json(context, service._json(context, commission.checkpoint)["plan"])
            snapshot["commission"] = {"task": c.primitive(commission.ref()), "checkpoint_sha256": commission.checkpoint.sha256}
            if delegation.connection_digest(service, context, model.header.entity_id) != commission_plan["root_connection_sha256"]:
                raise ContractError("coordinator_connection_changed")
        if len(child_outcomes) != len(plan["nodes"]) or result is None:
            raise ContractError("delegation_result_unverified")
        provenance = delegation._provenance(plan, contributions)
        expected = {"source": delegation.SOURCE, "plan_sha256": digest(plan),
            "child_outcomes": [c.primitive(row.ref()) for row in child_outcomes], "verified_fact_transfer": True,
            "human_accepted": False, "professional_quality_assessed": False, "synthetic": bool(provenance["local_test_receipts"]),
            "root_kind": plan.get("root_kind", "application_result"), "root_source": plan["root_source"],
            "contributions": contributions, "provenance": provenance,
            "facts": plan["root_source"]["facts"], "operation": delegation.operation_of(plan),
            "produces_new_analysis": delegation.OPERATIONS[delegation.operation_of(plan)]["produces_new_analysis"]}
        if (not delegation._same_result(result, expected) or outcome.task.entity_id != control.header.entity_id
                or outcome.evidence != tuple(row.verification for row in child_outcomes) or outcome.execution is not None):
            raise ContractError("delegation_result_changed")
        historical = service.repository.get_revision(context=context, kind=EntityKind.TASK,
            entity_id=outcome.task.entity_id, revision=outcome.task.revision)
        if historical is None or historical.ref() != outcome.task:
            raise ContractError("delegation_result_lineage_invalid")
    except ContractError as error:
        errors.append(error.code)
    snapshot["authority"] = _aggregate_authority(authorized, service, control, plan)
    if snapshot["authority"].get("blocked_reason"): errors.append(snapshot["authority"]["blocked_reason"])
    if not all(item["status"] == "accepted" and not item.get("blocked_reason") for item in required):
        errors.append("delegation_required_reviews_pending" if all(item["status"] in {"accepted", "pending"} for item in required)
                      else "delegation_required_reviews_not_accepted")
    return snapshot


def aggregate_projection(authorized, service, task):
    """The same human-review ledger, bound to an exact, separately checked DAG."""
    from .model_service import _id
    context = authorized["context"]
    source = _aggregate_snapshot(authorized, service, task)
    current_hash = digest(source)
    base = {"status": "blocked" if source["errors"] else "pending", "source_sha256": current_hash,
        "task_revision": task.header.revision, "required_reviews": source["required_reviews"],
        "blocked_reason": source["errors"][0] if source["errors"] else None, "quality_claim": False}
    # Cancellation/current-truth drift must not erase a prior immutable review.
    candidates = [row for row in service._all(context, EntityKind.EVALUATION)
        if row.rubric_key == RUBRIC and row.task.entity_id == task.header.entity_id]
    if not candidates: return base
    found = max(candidates, key=lambda row: (row.task.revision, row.header.created_at))
    proof = service._json(context, found.evidence)
    saved = service._json(context, proof.get("source_snapshot"))
    if (found.header.created_by.kind != c.ActorKind.HUMAN or found.header.created_by.actor_id != context.user_uuid
            or found.header.owner_user_uuid != context.user_uuid or proof.get("version") != "human-review-v1"
            or found.header.entity_id != _id(context, f"human-review:{found.task.entity_id}:{found.task.revision}")
            or proof.get("origin") != "explicit_human_review" or proof.get("quality_claim") is not False
            or proof.get("reviewer_user_uuid") != str(found.header.created_by.actor_id)
            or proof.get("task_revision") != found.task.revision or proof.get("decision") not in {"accept", "reject"}
            or not isinstance(proof.get("comment"), str) or len(proof["comment"]) > 2000
            or saved.get("version") != "bounded-delegation-human-review-v1" or saved.get("errors") != []
            or not saved.get("required_reviews") or any(item.get("status") != "accepted" for item in saved["required_reviews"])
            or c.primitive(found.task) != saved.get("controller") or c.primitive(found.model) != saved.get("model")
            or c.primitive(found.outcome) != saved.get("outcome") or digest(saved) != proof.get("source_sha256")):
        raise ContractError("task_review_evidence_mismatch")
    decision = "accepted" if proof["decision"] == "accept" else "rejected"
    return {**base, "status": decision if proof["source_sha256"] == current_hash else "stale",
        "recorded_status": decision, "recorded_source_sha256": proof["source_sha256"],
        "evaluation_id": str(found.header.entity_id), "reviewer_user_uuid": proof["reviewer_user_uuid"],
        "reviewed_at": found.header.created_at.isoformat(), "comment": proof["comment"], "origin": "explicit_human_review"}


def _aggregate_detail(authorized, service, task):
    from . import delegation
    return delegation.projection(authorized, service, task.header.entity_id)


def submit(service, *, context, task_id, payload, expected_revision, idempotency_key):
    from .model_service import _LOCK, _key
    service._access(context, "review")
    _key(idempotency_key)
    if (context.actor.kind != c.ActorKind.HUMAN or not isinstance(payload, dict)
            or set(payload) - {"decision", "comment", "source_sha256"}
            or payload.get("decision") not in {"accept", "reject"}
            or not isinstance(payload.get("comment", ""), str)
            or len(payload.get("comment", "")) > 2000):
        raise ContractError("task_review_invalid")
    with _LOCK:
        task = service._get(context, EntityKind.TASK, task_id)
        if type(expected_revision) is not int or task.header.revision != expected_revision:
            raise ContractError("task_review_stale")
        checkpoint = service._json(context, task.checkpoint)
        aggregate = checkpoint.get("source") == "agent_world_delegation"
        authorized = service.mechanism_authorized
        if aggregate and (not isinstance(authorized, dict) or authorized.get("context") != context):
            raise ContractError("task_review_authority_required")
        detail = (_aggregate_detail(authorized, service, task) if aggregate else
                  service.task_detail(context=context, task_id=task_id))
        state = detail["human_review"]
        if state["status"] in {"not_required", "blocked"} or state.get("blocked_reason") or state.get("source_sha256") != payload.get("source_sha256"):
            raise ContractError("task_review_result_required")
        if state["status"] != "pending":
            if (state["status"] != {"accept": "accepted", "reject": "rejected"}[payload["decision"]]
                    or state.get("comment", "") != payload.get("comment", "").strip()):
                raise ContractError("task_review_already_recorded")
            return {**detail, "deduplicated": True}
        proof_data = {"version": "human-review-v1", "decision": payload["decision"],
            "comment": payload.get("comment", "").strip(), "source_sha256": state["source_sha256"],
            "task_revision": task.header.revision, "reviewer_user_uuid": str(context.user_uuid),
            "origin": "explicit_human_review", "quality_claim": False,
            "request_key_sha256": digest(idempotency_key)}
        if aggregate:
            from . import delegation
            # Human review grants no execution. Reuse the existing exact grant
            # solely to recheck authority before recording the human decision.
            plan = service._json(context, checkpoint["plan"])
            delegation.authority(service, context, task.ref(), plan["grant_ref"], "delegation_reconcile")
            source = _aggregate_snapshot(authorized, service, task)
            if source["errors"] or digest(source) != state["source_sha256"]:
                raise ContractError("task_review_stale")
            proof_data["source_snapshot"] = c.primitive(service._put(context, source))
            model_id = source["model"]["entity_id"]
        else:
            model_id = checkpoint["model_id"]
        proof = service._put(context, proof_data)
        outcome_id = (detail.get("application_result") or {}).get("outcome_id") or detail["outcome_id"]
        outcome = service._get(context, EntityKind.OUTCOME, outcome_id)
        model = service._get(context, EntityKind.MODEL, model_id)
        # Authorization may have been revoked while the exact source was read.
        service._access(context, "review")
        if aggregate:
            delegation.authority(service, context, task.ref(), plan["grant_ref"], "delegation_reconcile")
            if service._get(context, EntityKind.TASK, task_id).ref() != task.ref():
                raise ContractError("task_review_stale")
        committed = service._ensure(context, Evaluation, _identity(service, context, task),
            task.header.correlation_id, task.header.policy, task=task.ref(), outcome=outcome.ref(),
            subject=model.ref(), evidence=proof, rubric_key=RUBRIC)
        # _ensure is deliberately reusable/idempotent and can return a record
        # created by another process after our read. Never report its opposite
        # decision as success for this request (the ledger remains untouched).
        if (committed.evidence != proof or committed.header.created_by != context.actor
                or committed.task != task.ref() or committed.outcome != outcome.ref()
                or committed.model != model.ref() or committed.rubric_key != RUBRIC):
            raise ContractError("task_review_already_recorded")
    if aggregate:
        result = _aggregate_detail(authorized, service, task)
        # Cross-store auth/graph changes cannot be made atomic by this ledger.
        # Never report success if a concurrent change already invalidated the
        # recorded snapshot; the exact human decision remains in history.
        if result["human_review"]["status"] != {"accept": "accepted", "reject": "rejected"}[payload["decision"]]:
            raise ContractError("task_review_stale")
        return result
    return service.task_detail(context=context, task_id=task_id)
