"""Link independently verified existing job/chart evidence to a model plan.

No tool dispatch, result recomputation, scheduler or report authority. The root
calls this only after revalidating the existing real application's own receipt.
"""
from __future__ import annotations

import re

from . import contracts as c
from .model_contracts import Evaluation
from .model_evaluation import digest
from .states import ContractError, EntityKind


def application_spec(kind, value):
    if kind == "backtest":
        from .live_backtests import _spec
        return _spec(value)
    if kind != "chart" or type(value) is not dict or set(value) != {"instrument", "timeframe"}:
        raise ContractError("model_application_spec_invalid")
    if (type(value["instrument"]) is not str or not re.fullmatch(r"[A-Z0-9]{1,10} \d{2}-\d{2}", value["instrument"])
            or type(value["timeframe"]) is not str or not re.fullmatch(r"[1-9]\d{0,3}m", value["timeframe"])):
        raise ContractError("model_application_spec_invalid")
    from .. import market_data
    try:
        timeframe = market_data.normalize_timeframe(value["timeframe"])
    except market_data.MarketDataError:
        raise ContractError("model_application_spec_invalid") from None
    return {"instrument": value["instrument"], "timeframe": timeframe}


def record_application_result(service, *, context, task_id, source_id, verification, artifact_refs):
    from .model_service import _id, _LOCK
    service._access(context, "application_result")
    task = service._get(context, EntityKind.TASK, task_id)
    checkpoint = service._json(context, task.checkpoint)
    request = checkpoint.get("application_request")
    if not request or task.status not in {"waiting", "succeeded"}:
        raise ContractError("model_application_plan_unverified")
    c.require_token(source_id, limit=120)
    if not isinstance(verification, dict):
        raise ContractError("model_application_evidence_invalid")
    expected_kind = "ninjatrader_report" if request["kind"] == "backtest" else "desktop_chart"
    if (verification.get("verified") is not True or verification.get("synthetic") is not False
            or verification.get("source_id") != source_id or verification.get("source_kind") != expected_kind
            or verification.get("request_sha256") != request["request_sha256"]
            or not re.fullmatch(r"[0-9a-f]{64}", str(verification.get("sha256") or ""))):
        raise ContractError("model_application_evidence_invalid")
    if (type(artifact_refs) is not tuple or not 1 <= len(artifact_refs) <= 10
            or any(not isinstance(ref, c.SnapshotRef) for ref in artifact_refs)):
        raise ContractError("model_application_artifacts_required")
    for ref in artifact_refs:
        c.require_same_scope(context.scope, ref.scope)
        if service.repository.get_artifact(context=context, reference=ref) is None:
            raise ContractError("model_application_evidence_unavailable")
    if verification["sha256"] not in {ref.sha256 for ref in artifact_refs}:
        raise ContractError("model_application_source_hash_mismatch")
    identity = _id(context, f"application-outcome:{task.header.entity_id}")
    with _LOCK:
        existing = service.repository.get(context=context, kind=EntityKind.OUTCOME, entity_id=identity)
        if existing is not None and existing.status == "verified":
            old = service._json(context, existing.verification)
            if old.get("verification") != verification or old.get("artifact_ids") != [str(ref.artifact_id) for ref in artifact_refs]:
                raise ContractError("model_application_result_conflict")
            # An interruption may have happened after the immutable Outcome
            # commit but before its evaluation or terminal task transition.
            model = service._get(context, EntityKind.MODEL, checkpoint["model_id"])
            service._ensure(context, Evaluation, _id(context, f"application-evaluation:{task.header.entity_id}"),
                task.header.correlation_id, task.header.policy, task=task.ref(), outcome=existing.ref(),
                evidence=existing.verification, model=model.ref(), rubric_key="application_execution")
            _complete_task(service, context, task)
            return application_result(service, context, task)
        # Caller already verified actual bytes. Preserve that authority and
        # hashes; this evaluation does not re-compute profits or inspect pixels.
        proof_data = {"schema_version": 1, "source": "existing_application_receipt",
            "verification": verification, "source_id": source_id, "source_kind": expected_kind,
            "task_id": str(task.header.entity_id), "model_id": checkpoint["model_id"],
            "artifact_ids": [str(ref.artifact_id) for ref in artifact_refs],
            "rubric_key": "application_execution", "passed": True, "observed_score_pct": 100,
            "evaluator": "existing_application_evidence_verifier", "self_scored": False,
            "synthetic": False, "input_sha256": digest(request), "routing_effect": "none",
            "limitation": "Execution/evidence conformance only; not profitability, freshness or general model quality."}
        proof = service._put(context, proof_data)
        policy, correlation = task.header.policy, task.header.correlation_id
        # External execution is separately authorized by the existing adapter,
        # not retrospectively attributed to the model's text-only approval.
        approval = service._put(context, {"source": "existing_application_authorization", "user_uuid": str(context.user_uuid),
            "request_sha256": request["request_sha256"], "source_id": source_id,
            "scope": context.scope.workspace_id, "verification": verification["sha256"]})
        intent = service._get(context, EntityKind.INTENT, task.intent.entity_id)
        decision = service._ensure(context, c.Decision, _id(context, f"application-decision:{task.header.entity_id}"),
            correlation, policy, intent=intent.ref(), contributions=(), evidence_packet=approval)
        if decision.status == "proposed":
            decision = service._change(context, decision, "review")
        if decision.status == "review":
            decision = service._change(context, decision, "approved", approval=approval)
        execution = service._ensure(context, c.Execution, _id(context, f"application-execution:{task.header.entity_id}"),
            correlation, policy, decision=decision.ref(), approval=approval,
            command=c.ExternalRef(authority=c.ExternalAuthority.COMMAND, key=expected_kind + "." + source_id, scope=context.scope))
        if execution.status == "requested":
            execution = service._change(context, execution, "queued")
        if execution.status == "queued":
            execution = service._change(context, execution, "running")
        if execution.status == "running":
            execution = service._change(context, execution, "succeeded", receipt=proof)
        outcome = service._ensure(context, c.Outcome, identity, correlation, policy, task=task.ref(),
            evidence=artifact_refs + (proof,), execution=execution.ref())
        outcome = service._change(context, outcome, "verified", verification=proof)
        model = service._get(context, EntityKind.MODEL, checkpoint["model_id"])
        service._ensure(context, Evaluation, _id(context, f"application-evaluation:{task.header.entity_id}"),
            correlation, policy, task=task.ref(), outcome=outcome.ref(), evidence=proof,
            model=model.ref(), rubric_key="application_execution")
        _complete_task(service, context, task)
    return application_result(service, context, task)


def _complete_task(service, context, task):
    task = service._get(context, EntityKind.TASK, task.header.entity_id)
    if task.status == "waiting":
        task = service._change(context, task, "ready")
    if task.status == "ready":
        task = service._change(context, task, "running")
    if task.status == "running":
        service._change(context, task, "succeeded")
    intent = service._get(context, EntityKind.INTENT, task.intent.entity_id)
    if intent.status == "waiting":
        intent = service._change(context, intent, "ready")
    if intent.status == "ready":
        intent = service._change(context, intent, "running")
    if intent.status == "running":
        service._change(context, intent, "completed")


def application_result(service, context, task):
    from .model_service import _id
    outcome = service.repository.get(context=context, kind=EntityKind.OUTCOME,
        entity_id=_id(context, f"application-outcome:{task.header.entity_id}"))
    if outcome is None or outcome.status != "verified":
        return None
    evaluation = service.repository.get(context=context, kind=EntityKind.EVALUATION,
        entity_id=_id(context, f"application-evaluation:{task.header.entity_id}"))
    if evaluation is None:
        return None  # incomplete closeout is repaired, never shown as final
    if (evaluation.outcome.entity_id != outcome.header.entity_id or evaluation.evidence != outcome.verification
            or evaluation.task.entity_id != task.header.entity_id):
        raise ContractError("model_application_evaluation_mismatch")
    proof = service._json(context, outcome.verification)
    for ref in outcome.evidence:
        if service.repository.get_artifact(context=context, reference=ref) is None:
            raise ContractError("model_application_evidence_unavailable")
    return {"outcome_id": str(outcome.header.entity_id), "execution_id": str(outcome.execution.entity_id),
            "source_id": proof["source_id"], "source_kind": proof["source_kind"], "verified": True,
            "evaluation": proof, "artifact_ids": proof["artifact_ids"],
            "result_text": proof["verification"].get("summary"), "report_url": proof["verification"].get("report_url")}
