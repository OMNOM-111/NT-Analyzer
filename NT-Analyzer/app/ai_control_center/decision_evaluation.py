"""Decision performance, measured from the outcome an approved decision produced.

A decision authorises a bounded action. What can honestly be observed about it
afterwards is narrow, and worth saying exactly: was the thing that ran the thing
that was approved, and did it produce an outcome the independent verifier
accepted. Nothing here asks whether it was the right call in some deeper sense,
and the limitation on every reading says so.

This is not the model's score wearing another label. The subject is a Decision,
the evidence is the Outcome bound to the Execution, and the task class is its
own — so a model evaluation can never be counted here, and a decision
evaluation can never be counted as a model's. They also diverge in fact: a model
can answer its rubric perfectly under an execution that drifted out of the
approved scope, and then the model passed and the decision did not.

A failed execution is not a bad decision. When the machinery never delivered an
outcome — cancelled, expired, an uncertain provider reply, a receipt that does
not match its own record — the decision was never tested, and nothing is
written at all. Silence is the honest answer; a recorded failure would be a lie
about a decision that never got its chance.
"""
from __future__ import annotations

from . import deviation_control as deviations
from .model_contracts import Evaluation
from .model_service import _id
from .states import ContractError, EntityKind


VERSION = "decision-outcome-v1"
# Its own class. `measure` filters on the class as well as the subject, so a
# model's rubric and this one can never pool even by accident.
RUBRIC = "decision_outcome"

# What the approved decision is answerable for: the executed action was not the
# approved one, or what it produced would not be taken.
DECISION_DEVIATIONS = frozenset({
    "approved_scope_changed", "approved_decision_changed", "connection_changed",
    "application_scope_changed", "application_result_rejected", "provider_result_rejected",
    "provider_output_limit_exceeded", "delegation_source_changed",
})
# The execution failed on its own account. The decision is left unmeasured.
EXECUTION_DEVIATIONS = frozenset({
    "execution_deadline_expired", "execution_gate_disabled", "execution_authority_denied",
    "execution_claim_lost", "execution_cancelled", "provider_reply_uncertain",
    "provider_receipt_mismatch", "application_receipt_mismatch", "execution_source_failed",
    "execution_checkpoint_interrupted",
})


def unclassified_reasons():
    """Deviation codes nobody has decided about yet.

    A new reason must be attributed deliberately. Falling into "not the
    decision's fault" by default is how a decision quietly stops being measured.
    """
    return deviations.REASONS - DECISION_DEVIATIONS - EXECUTION_DEVIATIONS


def _reasons(service, context, task):
    """Deviation codes recorded against this task's execution controller."""
    from . import execution_v2
    controller = execution_v2._find(service, context, task.header.entity_id)
    if controller is None or controller.receipt is None:
        return ()
    state = service._json(context, controller.receipt)
    found = []
    for wire in state.get("deviations") or ():
        try:
            from .delegation import snapshot
            proof = service._json(context, snapshot(context, wire))
        except ContractError:
            # An unreadable deviation is itself a reason not to claim the
            # decision was observed cleanly.
            found.append("execution_checkpoint_interrupted")
            continue
        code = proof.get("reason_code")
        if code:
            found.append(code)
    return tuple(found)


def _grant_decision(service, context, checkpoint):
    """The standing authorisation this work ran under, when there is one.

    A grant is the decision that actually accumulates a history: one approved
    plan admits many executions, so its sample grows while a single task's own
    decision only ever has the one observation.
    """
    packet = checkpoint.get("delegation") or {}
    reference = packet.get("grant_ref")
    if not reference:
        return None
    from .automation_authority import _load
    try:
        # Expired and superseded grants still own their history: what ran under
        # them happened, and revoking the grant does not unhappen it.
        decision, _proof, _ref = _load(service, context, reference, operational=False)
    except ContractError:
        return None
    return decision


def record(service, context, *, task, checkpoint, execution, outcome, provenance):
    """One observation per decision that authorised this execution.

    Returns the evaluations written, which is empty whenever the decision was
    not actually put to the test.
    """
    reasons = _reasons(service, context, task)
    if any(reason in EXECUTION_DEVIATIONS for reason in reasons):
        return ()
    if outcome.status not in {"verified", "disputed"} or outcome.execution is None or (
            outcome.execution.entity_id != execution.header.entity_id):
        # No outcome bound to this execution means no observation. The evidence
        # is what decides this, not the fact that a task finished.
        return ()
    decision = service._get(context, EntityKind.DECISION, execution.decision.entity_id)
    if decision.status != "approved" or decision.approval is None:
        return ()

    approval = service._json(context, execution.approval)
    scope_held = (approval.get("request_sha256") == checkpoint.get("request_sha256")
                  and approval.get("task_id") == str(task.header.entity_id))
    attributed = tuple(reason for reason in reasons if reason in DECISION_DEVIATIONS)
    passed = outcome.status == "verified" and scope_held and not attributed
    # Said in the record itself, so a decision that did not pass is never read
    # as a statement about the model that answered under it.
    reason = ("approved_scope_not_held" if not scope_held else
              attributed[0] if attributed else
              "outcome_not_verified" if outcome.status != "verified" else None)

    written = []
    for subject in _subjects(service, context, decision, checkpoint):
        proof = service._put(context, {
            "version": VERSION, "source": "approved_decision_execution_outcome",
            "passed": passed, "reason": reason,
            "decision_id": str(subject.entity_id), "decision_revision": subject.revision,
            "execution_id": str(execution.header.entity_id), "execution_status": execution.status,
            "outcome_id": str(outcome.header.entity_id), "outcome_status": outcome.status,
            "outcome_evidence_sha256": outcome.verification.sha256 if outcome.verification else None,
            "scope_held": scope_held, "deviations": list(attributed),
            "task_id": str(task.header.entity_id),
            # The decider does not score itself: this reads the outcome's own
            # independent verification and nothing the decision said about it.
            "decided_by": "approved_decision", "scored_from": "independent_outcome_verification",
            "evaluator": "independent_local_evidence_verifier", "self_scored": False,
            "synthetic": bool(provenance.get("synthetic")),
            "professional_quality_assessed": False,
        })
        written.append(service._ensure(
            context, Evaluation,
            _id(context, f"decision-evaluation:{subject.entity_id}:{task.header.entity_id}"),
            task.header.correlation_id, task.header.policy,
            task=task.ref(), outcome=outcome.ref(), evidence=proof,
            subject=subject, rubric_key=RUBRIC))
    return tuple(written)


def _subjects(service, context, decision, checkpoint):
    """The decisions this outcome is evidence about, each in its own right."""
    subjects = [decision.ref()]
    grant = _grant_decision(service, context, checkpoint)
    if grant is not None and grant.ref() != decision.ref():
        subjects.append(grant.ref())
    return subjects
