"""Immutable plan-versus-observation evidence, not an execution authority.

Deviations use the existing artifact store and Execution/event history. This
module never dispatches, grants permission, evaluates a model's reputation, or
replaces the authoritative application's receipt verifier.
"""
from __future__ import annotations

from .model_evaluation import digest
from .model_service import _wire
from .states import ContractError


REASONS = frozenset({
    "approved_scope_changed", "approved_decision_changed", "connection_changed",
    "execution_deadline_expired", "execution_gate_disabled", "execution_authority_denied",
    "execution_claim_lost", "execution_cancelled", "provider_reply_uncertain",
    "provider_receipt_mismatch", "provider_output_limit_exceeded", "provider_result_rejected",
    "application_scope_changed", "application_result_rejected", "application_receipt_mismatch",
    "delegation_source_changed", "execution_source_failed", "execution_checkpoint_interrupted",
})


def record(service, context, controller, *, reason, phase, expected=None, observed=None):
    """Persist only hashes/reason codes; never exception bodies, prompts or keys."""
    if reason not in REASONS or phase not in {
        "prepare", "admission", "provider", "application", "observe", "cancel", "resume"
    }:
        raise ContractError("execution_deviation_invalid")
    value = {
        "schema_version": 1, "source": "execution_v2_deviation",
        "controller_id": str(controller.header.entity_id),
        "correlation_id": str(controller.header.correlation_id),
        "approved_scope": _wire(controller.approval), "reason_code": reason,
        "phase": phase, "severity": "stop_and_review",
        "expected_sha256": digest(expected) if expected is not None else None,
        "observed_sha256": digest(observed) if observed is not None else None,
        "automatic_compensation": False, "court_execution": False,
    }
    return service._put(context, value)


def inspect_provider(approved, receipt):
    """Compare a verified stored response to the exact approved model request."""
    if (receipt.get("source") != "provider_response"
            or receipt.get("task_id") != approved["task_id"]
            or receipt.get("request_id") != approved["task_id"]
            or receipt.get("request_sha256") != approved["request_sha256"]
            or receipt.get("synthetic") is not False):
        return "provider_receipt_mismatch"
    output = receipt.get("output_tokens")
    if output is not None and (type(output) is not int or output < 0
                              or output > approved["max_output_tokens"]):
        return "provider_output_limit_exceeded"
    return None


def inspect_application(approved, checkpoint, result):
    """No numeric P&L recomputation: the existing source verifier owns truth."""
    expected = approved.get("application_request")
    if not expected or checkpoint.get("application_request") != expected:
        return "application_scope_changed"
    dispatch = checkpoint.get("application_dispatch") or {}
    proof = (result or {}).get("evaluation") or {}
    verification = proof.get("verification") or {}
    expected_kind = "ninjatrader_report" if expected["kind"] == "backtest" else "desktop_chart"
    if (not result or result.get("verified") is not True
            or result.get("source_id") != dispatch.get("source_id")
            or result.get("source_kind") != expected_kind
            or proof.get("task_id") != approved["task_id"]
            or proof.get("source") != "existing_application_receipt"
            or proof.get("synthetic") is not False
            or verification.get("verified") is not True
            or verification.get("synthetic") is not False
            or verification.get("request_sha256") != expected["request_sha256"]
            or verification.get("source_id") != dispatch.get("source_id")):
        return "application_receipt_mismatch"
    return None
