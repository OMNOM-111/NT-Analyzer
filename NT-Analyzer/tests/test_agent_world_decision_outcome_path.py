"""The production path from an approved decision to an observation about it.

An approved Decision, the Execution that names it, the Outcome bound to that
Execution, and the Evaluation the outcome justifies. Everything here goes
through the real producer and is read back through the same service entry the
panel uses.

The cases exist to catch four specific lies: a decision score that is really the
model's, a role score that has quietly eaten decision rows, an evaluation that
does not come from the outcome it claims, and a failed execution filed as a bad
decision.

Disposable SQLite only. No provider call, no queue, no owner data.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.ai_control_center import contracts as c, decision_evaluation as producer
from app.ai_control_center import deviation_control, reputation
from app.ai_control_center.model_service import _id
from app.ai_control_center.states import EntityKind
from tests.test_agent_world_models import Secrets, connected, setup, task as start  # noqa: F401


RUBRIC = producer.RUBRIC


def _policy(service, context):
    return service._put(context, {"fixture": "decision outcome path", "synthetic": True})


def _intent(service, context, policy):
    from datetime import timedelta
    from app.ai_control_center.model_service import _now
    return service._ensure(context, c.Intent, uuid4(), uuid4(), policy,
        goal=service._put(context, {"fixture": "goal"}),
        acceptance=service._put(context, {"fixture": "acceptance"}),
        risk=c.Risk.LOW, autonomy=c.Autonomy.ADVICE,
        budget=c.ExternalRef(authority=c.ExternalAuthority.BUDGET,
                             key="ai_budgets.fixture." + uuid4().hex, scope=context.scope),
        deadline=_now() + timedelta(hours=1))


def _approved_decision(service, context, policy):
    """An approved decision, carrying its own evidence packet.

    Separate from the per-execution approval on purpose: a standing
    authorisation covers many executions, and each of those still has its own
    approved request. Binding the two together in the fixture would hide which
    of them `scope_held` is actually about.
    """
    intent = _intent(service, context, policy)
    packet = service._put(context, {"source": "explicit_bounded_user_request",
                                    "user_uuid": str(context.user_uuid),
                                    "tools": [], "court": False})
    decision = service._ensure(context, c.Decision, uuid4(), uuid4(), policy,
        intent=intent.ref(), contributions=(), evidence_packet=packet)
    decision = service._walk(context, decision, "review")
    return service._change(context, decision, "approved", approval=packet), packet, intent


def _role(service, context, policy):
    role = service._ensure(context, c.AgentRole, uuid4(), uuid4(), policy,
        role_key="fixture_role_" + uuid4().hex[:8],
        responsibilities=service._put(context, {"duty": "bounded fixture role", "tools": []}),
        capability_ceiling=("ai_pro_models",), autonomy_ceiling=c.Autonomy.ADVICE)
    return service._walk(context, role, "active")


def _executed(service, context, policy, decision, _packet=None, *, request_sha256,
              approved_sha256=None, verified=True, synthetic=True, bind_outcome=True):
    """One execution of that decision, with the outcome it actually produced.

    The task comes first and the execution's approval names it, which is the
    order the real `_prepare_execution` builds them in.
    """
    correlation = uuid4()
    intent = service._get(context, EntityKind.INTENT, decision.intent.entity_id)
    task = service._ensure(context, c.Task, uuid4(), correlation, policy,
        intent=intent.ref(), role=_role(service, context, policy).ref(), dependencies=(),
        checkpoint=service._put(context, {"source": "real_model_task",
                                          "request_sha256": request_sha256,
                                          "spec": {"rubric_key": "json_arithmetic"}}))
    approval = service._put(context, {"source": "explicit_bounded_user_request",
                                      "user_uuid": str(context.user_uuid),
                                      "request_sha256": approved_sha256 or request_sha256,
                                      "task_id": str(task.header.entity_id),
                                      "tools": [], "court": False})
    execution = service._ensure(context, c.Execution, uuid4(), correlation, policy,
        decision=decision.ref(), approval=approval,
        command=c.ExternalRef(authority=c.ExternalAuthority.COMMAND,
                              key="aw_model." + str(task.header.entity_id), scope=context.scope))
    receipt = service._put(context, {"fixture": "receipt", "response": uuid4().hex})
    execution = service._walk(context, execution, "queued", "running")
    execution = service._change(context, execution, "succeeded", receipt=receipt)
    proof = service._put(context, {"passed": verified, "rubric_key": "json_arithmetic",
                                   "self_scored": False, "synthetic": synthetic,
                                   "evaluator": "independent_local_evidence_verifier"})
    outcome = service._ensure(context, c.Outcome, uuid4(), correlation, policy,
        task=task.ref(), evidence=(receipt, proof),
        execution=execution.ref() if bind_outcome else None)
    outcome = service._change(context, outcome, "verified" if verified else "disputed",
                              verification=proof)
    checkpoint = service._json(context, task.checkpoint)
    return task, execution, outcome, checkpoint


def _measure(service, context, decision, task_class=RUBRIC):
    return service.reputation(context=context, subject_kind=EntityKind.DECISION,
                              subject_id=decision.ref().entity_id, task_class=task_class)


@pytest.fixture
def store(setup):  # noqa: F811
    service, context = setup[0], setup[1]
    return service, context, _policy(service, context)


# --- the production path ----------------------------------------------------

def test_a_real_completed_task_records_an_observation_about_its_decision(setup):  # noqa: F811
    """The whole chain, driven by the application's own completion path.

    Nothing here constructs an Evaluation: the task is executed through the
    service, and the decision observation has to appear on its own.
    """
    from app.ai_control_center import model_chat  # noqa: F401
    service, context = setup[0], setup[1]
    model = connected(setup, key="decision-path-model")
    pending = start(setup, model, key="decision-path-task")
    service.execute(context=context, task_id=pending["id"])

    decision = service._get(context, EntityKind.DECISION,
                            _id(context, f"decision:{pending['id']}"))
    assert decision.status == "approved"

    view = service.reputation(context=context, subject_kind=EntityKind.DECISION,
                              subject_id=decision.header.entity_id, task_class=RUBRIC)
    assert view["scope"] == "decision_performance"
    assert view["sample_size"] == 1 and len(view["evidence_refs"]) == 1
    assert view["provenance"]["self_scored"] is False

    # And it is on the detail the panel reads, beside the other two.
    detail = service.task_detail(context=context, task_id=pending["id"])
    assert set(detail["reputation"]) == {
        "model_performance", "agent_role_performance", "decision_performance"}
    assert detail["reputation"]["decision_performance"]["sample_size"] == 1


def test_the_observation_names_the_outcome_and_the_execution_it_came_from(store):
    service, context, policy = store
    decision, _packet, _intent_record = _approved_decision(service, context, policy)
    task, execution, outcome, checkpoint = _executed(
        service, context, policy, decision, request_sha256="a" * 64)

    written = producer.record(service, context, task=task, checkpoint=checkpoint,
                              execution=execution, outcome=outcome,
                              provenance={"synthetic": True})
    assert len(written) == 1
    proof = service._json(context, written[0].evidence)
    assert proof["outcome_id"] == str(outcome.header.entity_id)
    assert proof["execution_id"] == str(execution.header.entity_id)
    assert proof["outcome_evidence_sha256"] == outcome.verification.sha256
    assert proof["passed"] is True and proof["reason"] is None
    assert proof["self_scored"] is False
    assert proof["scored_from"] == "independent_outcome_verification"


# --- no scope inherits another's rows ---------------------------------------

def test_a_decision_score_is_not_the_model_score_under_another_name(setup):  # noqa: F811
    """Same completed task, two subjects, and neither can reach the other's rows."""
    from app.ai_control_center import model_chat  # noqa: F401
    service, context = setup[0], setup[1]
    model = connected(setup, key="decision-vs-model")
    pending = start(setup, model, key="decision-vs-model-task")
    service.execute(context=context, task_id=pending["id"])
    detail = service.task_detail(context=context, task_id=pending["id"])

    decision_id = _id(context, f"decision:{pending['id']}")
    model_id = detail["reputation"]["model_performance"]["subject"]["id"]
    model_class = detail["reputation"]["model_performance"]["task_class"]

    # Asking the decision for the model's class finds nothing: the classes are
    # disjoint, so the rows cannot meet even if a filter is later loosened.
    assert service.reputation(context=context, subject_kind=EntityKind.DECISION,
                              subject_id=decision_id,
                              task_class=model_class)["sample_size"] == 0
    # And asking the model for the decision's class finds nothing either.
    assert service.reputation(context=context, subject_kind=EntityKind.MODEL,
                              subject_id=model_id,
                              task_class=RUBRIC)["sample_size"] == 0


def test_a_decision_can_fail_while_the_model_that_answered_passed(store):
    """The two numbers are not the same number.

    The model answered correctly and its outcome is verified; what was executed
    was not what the decision approved, so the decision did not pass. If this
    ever fails, one score has become a copy of the other.
    """
    service, context, policy = store
    decision, _packet, _intent_record = _approved_decision(service, context, policy)
    task, execution, outcome, checkpoint = _executed(
        service, context, policy, decision, request_sha256="b" * 64, approved_sha256="a" * 64)
    assert outcome.status == "verified"

    written = producer.record(service, context, task=task, checkpoint=checkpoint,
                              execution=execution, outcome=outcome,
                              provenance={"synthetic": True})
    proof = service._json(context, written[0].evidence)
    assert proof["passed"] is False and proof["scope_held"] is False
    assert proof["reason"] == "approved_scope_not_held"
    assert _measure(service, context, decision)["quality"]["passed"] == 0


def test_an_agent_role_scope_never_reads_a_decision_row(store):
    service, context, policy = store
    decision, _packet, _intent_record = _approved_decision(service, context, policy)
    task, execution, outcome, checkpoint = _executed(
        service, context, policy, decision, request_sha256="a" * 64)
    producer.record(service, context, task=task, checkpoint=checkpoint, execution=execution,
                    outcome=outcome, provenance={"synthetic": True})

    role_id = task.role.entity_id
    for task_class in (RUBRIC, "json_arithmetic"):
        view = service.reputation(context=context, subject_kind=EntityKind.AGENT_ROLE,
                                  subject_id=role_id, task_class=task_class)
        assert view["scope"] == "agent_role_performance"
        assert view["sample_size"] == 0, "a role scope is counting a decision's rows"


# --- the outcome is what decides -------------------------------------------

def test_no_outcome_bound_to_the_execution_means_no_observation(store):
    service, context, policy = store
    decision, _packet, _intent_record = _approved_decision(service, context, policy)
    task, execution, outcome, checkpoint = _executed(
        service, context, policy, decision, request_sha256="a" * 64, bind_outcome=False)

    assert producer.record(service, context, task=task, checkpoint=checkpoint,
                           execution=execution, outcome=outcome,
                           provenance={"synthetic": True}) == ()
    assert _measure(service, context, decision)["sample_size"] == 0


def test_a_disputed_outcome_is_a_failed_decision_and_says_which(store):
    service, context, policy = store
    decision, _packet, _intent_record = _approved_decision(service, context, policy)
    task, execution, outcome, checkpoint = _executed(
        service, context, policy, decision, request_sha256="a" * 64, verified=False)

    written = producer.record(service, context, task=task, checkpoint=checkpoint,
                              execution=execution, outcome=outcome,
                              provenance={"synthetic": True})
    proof = service._json(context, written[0].evidence)
    assert proof["passed"] is False and proof["reason"] == "outcome_not_verified"
    assert proof["outcome_status"] == "disputed"
    view = _measure(service, context, decision)
    assert view["sample_size"] == 1 and view["quality"]["passed"] == 0


def test_an_unapproved_decision_is_never_scored(store):
    """Nothing was authorised, so there is nothing to have been right about."""
    service, context, policy = store
    intent = _intent(service, context, policy)
    approval = service._put(context, {"source": "explicit_bounded_user_request",
                                      "request_sha256": "a" * 64})
    proposed = service._ensure(context, c.Decision, uuid4(), uuid4(), policy,
        intent=intent.ref(), contributions=(), evidence_packet=approval)
    assert proposed.status == "proposed"
    task, execution, outcome, checkpoint = _executed(
        service, context, policy, proposed, request_sha256="a" * 64)

    assert producer.record(service, context, task=task, checkpoint=checkpoint,
                           execution=execution, outcome=outcome,
                           provenance={"synthetic": True}) == ()


# --- a failed execution is not a bad decision -------------------------------

def test_every_deviation_reason_is_attributed_on_purpose():
    """A new reason must be classified, not default into "not our fault"."""
    assert producer.unclassified_reasons() == set()
    assert not (producer.DECISION_DEVIATIONS & producer.EXECUTION_DEVIATIONS)
    assert producer.DECISION_DEVIATIONS | producer.EXECUTION_DEVIATIONS == deviation_control.REASONS


def test_an_execution_that_failed_on_its_own_account_leaves_the_decision_unmeasured(store, monkeypatch):
    """Not a zero. Nothing. The decision never got its chance.

    A recorded failure here would be the exact confusion this split exists to
    prevent: a queue that lost its claim is not a decision that was wrong.
    """
    service, context, policy = store
    decision, _packet, _intent_record = _approved_decision(service, context, policy)
    task, execution, outcome, checkpoint = _executed(
        service, context, policy, decision, request_sha256="a" * 64)

    for reason in sorted(producer.EXECUTION_DEVIATIONS):
        monkeypatch.setattr(producer, "_reasons", lambda *_args, **_kw: (reason,))
        assert producer.record(service, context, task=task, checkpoint=checkpoint,
                               execution=execution, outcome=outcome,
                               provenance={"synthetic": True}) == (), reason
        assert _measure(service, context, decision)["sample_size"] == 0, reason


def test_a_deviation_the_decision_owns_is_recorded_as_a_failed_decision(store, monkeypatch):
    service, context, policy = store
    decision, _packet, _intent_record = _approved_decision(service, context, policy)
    task, execution, outcome, checkpoint = _executed(
        service, context, policy, decision, request_sha256="a" * 64)
    monkeypatch.setattr(producer, "_reasons", lambda *_args, **_kw: ("application_result_rejected",))

    written = producer.record(service, context, task=task, checkpoint=checkpoint,
                              execution=execution, outcome=outcome,
                              provenance={"synthetic": True})
    proof = service._json(context, written[0].evidence)
    assert proof["passed"] is False and proof["reason"] == "application_result_rejected"
    assert proof["deviations"] == ["application_result_rejected"]


# --- a diagnostic is never field performance --------------------------------

def test_a_decision_measured_only_on_synthetic_runs_is_diagnostic(store):
    """Three observations of one decision: enough to measure, and still a test.

    This is also the case that shows a decision accumulating a sample at all —
    one authorisation, several executions under it.
    """
    service, context, policy = store
    decision, _packet, _intent_record = _approved_decision(service, context, policy)
    for _ in range(3):
        task, execution, outcome, checkpoint = _executed(
            service, context, policy, decision, request_sha256="a" * 64)
        producer.record(service, context, task=task, checkpoint=checkpoint, execution=execution,
                        outcome=outcome, provenance={"synthetic": True})

    view = _measure(service, context, decision)
    assert view["sample_size"] == 3 and view["status"] == "measured"
    assert view["basis"] == "diagnostic"
    assert view["provenance"]["synthetic_observations"] == 3
    assert view["provenance"]["measured_observations"] == 0
    assert "диагности" in view["limitation"]


def test_a_decision_measured_on_real_runs_is_field_performance(store):
    service, context, policy = store
    decision, _packet, _intent_record = _approved_decision(service, context, policy)
    for _ in range(3):
        task, execution, outcome, checkpoint = _executed(
            service, context, policy, decision, request_sha256="a" * 64, synthetic=False)
        producer.record(service, context, task=task, checkpoint=checkpoint, execution=execution,
                        outcome=outcome, provenance={"synthetic": False})

    view = _measure(service, context, decision)
    assert view["sample_size"] == 3 and view["basis"] == "field"
    assert view["quality"]["observed_pct"] == 100.0
    assert view["scope"] == "decision_performance"
    assert reputation.SCOPES[view["scope"]] is EntityKind.DECISION
