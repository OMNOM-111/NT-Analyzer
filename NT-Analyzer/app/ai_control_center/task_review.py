"""Explicit immutable human review of one exact model/application result.

It is a human signal, never model calibration, execution authorization or a
rewrite of the source task/outcome. Reads never create or close reviews.
"""
from __future__ import annotations

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
        detail = service.task_detail(context=context, task_id=task_id)
        state = detail["human_review"]
        if state["status"] in {"not_required", "blocked"} or state.get("blocked_reason") or state.get("source_sha256") != payload.get("source_sha256"):
            raise ContractError("task_review_result_required")
        if state["status"] != "pending":
            if (state["status"] != {"accept": "accepted", "reject": "rejected"}[payload["decision"]]
                    or state.get("comment", "") != payload.get("comment", "").strip()):
                raise ContractError("task_review_already_recorded")
            return {**detail, "deduplicated": True}
        checkpoint = service._json(context, task.checkpoint)
        proof = service._put(context, {"version": "human-review-v1", "decision": payload["decision"],
            "comment": payload.get("comment", "").strip(), "source_sha256": state["source_sha256"],
            "task_revision": task.header.revision, "reviewer_user_uuid": str(context.user_uuid),
            "origin": "explicit_human_review", "quality_claim": False,
            "request_key_sha256": digest(idempotency_key)})
        outcome_id = (detail.get("application_result") or {}).get("outcome_id") or detail["outcome_id"]
        outcome = service._get(context, EntityKind.OUTCOME, outcome_id)
        model = service._get(context, EntityKind.MODEL, checkpoint["model_id"])
        # Authorization may have been revoked while the exact source was read.
        service._access(context, "review")
        committed = service._ensure(context, Evaluation, _identity(service, context, task),
            task.header.correlation_id, task.header.policy, task=task.ref(), outcome=outcome.ref(),
            model=model.ref(), evidence=proof, rubric_key=RUBRIC)
        # _ensure is deliberately reusable/idempotent and can return a record
        # created by another process after our read. Never report its opposite
        # decision as success for this request (the ledger remains untouched).
        if (committed.evidence != proof or committed.header.created_by != context.actor
                or committed.task != task.ref() or committed.outcome != outcome.ref()
                or committed.model != model.ref() or committed.rubric_key != RUBRIC):
            raise ContractError("task_review_already_recorded")
    return service.task_detail(context=context, task_id=task_id)
