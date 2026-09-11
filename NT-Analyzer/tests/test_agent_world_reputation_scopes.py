"""Three reputation scopes that must never read each other's evidence.

A real Model, a real Agent Role and a real Decision are created in a disposable
store, evaluated against their own subject, and read back through the service
entry the panel uses. A model score surfacing as a role score — or a scope
borrowing another's sample to escape `NEW` — is what these cases exist to catch.

Disposable SQLite only. No provider call, no queue, no owner data.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.ai_control_center import contracts as c, reputation
from app.ai_control_center.model_contracts import Evaluation
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_models import Secrets, connected, setup  # noqa: F401


TASK_CLASS = "json_arithmetic"


def _policy(service, context):
    return service._put(context, {"fixture": "reputation scopes", "synthetic": True})


def _role(service, context, policy, suffix):
    role = service._ensure(context, c.AgentRole, uuid4(), uuid4(), policy,
        role_key="fixture_role_" + suffix,
        responsibilities=service._put(context, {"duty": "bounded fixture role", "tools": []}),
        capability_ceiling=("ai_pro_models",), autonomy_ceiling=c.Autonomy.ADVICE)
    return service._walk(context, role, "active")


def _intent(service, context, policy):
    from datetime import timedelta
    from app.ai_control_center.model_service import _now
    intent = service._ensure(context, c.Intent, uuid4(), uuid4(), policy,
        goal=service._put(context, {"fixture": "goal"}),
        acceptance=service._put(context, {"fixture": "acceptance"}),
        risk=c.Risk.LOW, autonomy=c.Autonomy.ADVICE,
        budget=c.ExternalRef(authority=c.ExternalAuthority.BUDGET,
                             key="ai_budgets.fixture." + uuid4().hex, scope=context.scope),
        deadline=_now() + timedelta(hours=1))
    return intent


def _decision(service, context, policy, intent):
    return service._ensure(context, c.Decision, uuid4(), uuid4(), policy,
        intent=intent.ref(), contributions=(),
        evidence_packet=service._put(context, {"fixture": "packet"}))


def _observe(service, context, policy, *, subject, passed=True, task_class=TASK_CLASS,
             synthetic=False, self_scored=False):
    """One evaluation recorded against an explicit subject, through the store."""
    correlation = uuid4()
    intent = _intent(service, context, policy)
    role = _role(service, context, policy, uuid4().hex[:8])
    task = service._ensure(context, c.Task, uuid4(), correlation, policy,
        intent=intent.ref(), role=role.ref(), dependencies=(),
        checkpoint=service._put(context, {"fixture": uuid4().hex}))
    outcome = service._ensure(context, c.Outcome, uuid4(), correlation, policy,
        task=task.ref(), evidence=(service._put(context, {"fixture": uuid4().hex}),))
    proof = service._put(context, {"passed": passed, "self_scored": self_scored,
                                   "synthetic": synthetic,
                                   "evaluator": "independent_local_evidence_verifier"})
    return service._ensure(context, Evaluation, uuid4(), correlation, policy,
        task=task.ref(), outcome=outcome.ref(), evidence=proof,
        subject=subject, rubric_key=task_class)


@pytest.fixture
def scopes(setup):  # noqa: F811
    service, context = setup[0], setup[1]
    policy = _policy(service, context)
    model = connected(setup, key="reputation-model")
    model_ref = service._get(context, EntityKind.MODEL, model["id"]).ref()
    role_ref = _role(service, context, policy, "measured").ref()
    decision_ref = _decision(service, context, policy, _intent(service, context, policy)).ref()
    return service, context, policy, model_ref, role_ref, decision_ref


def _measure(service, context, ref, task_class=TASK_CLASS):
    return service.reputation(context=context, subject_kind=ref.kind,
                              subject_id=ref.entity_id, task_class=task_class)


def test_three_subject_kinds_are_measured_separately_and_never_share_a_sample(scopes):
    service, context, policy, model_ref, role_ref, decision_ref = scopes
    for _ in range(3):
        _observe(service, context, policy, subject=model_ref)
    _observe(service, context, policy, subject=role_ref)
    _observe(service, context, policy, subject=decision_ref, passed=False)

    model = _measure(service, context, model_ref)
    role = _measure(service, context, role_ref)
    decision = _measure(service, context, decision_ref)

    assert model["scope"] == "model_performance" and model["subject"]["kind"] == "model"
    assert role["scope"] == "agent_role_performance" and role["subject"]["kind"] == "agent_role"
    assert decision["scope"] == "decision_performance" and decision["subject"]["kind"] == "decision"
    assert model["subject"]["id"] == str(model_ref.entity_id)

    # The model reached a measurement; neither of the others borrowed its sample.
    assert model["sample_size"] == 3 and model["status"] == "measured"
    assert role["sample_size"] == 1 and role["status"] == "new"
    assert decision["sample_size"] == 1 and decision["status"] == "new"
    assert role["confidence"] == decision["confidence"] == "insufficient"
    assert model["quality"]["observed_pct"] == 100.0
    assert role["quality"]["observed_pct"] is None and decision["quality"]["observed_pct"] is None

    for view in (model, role, decision):
        assert view["task_class"] == TASK_CLASS
        assert len(view["evidence_refs"]) == view["sample_size"]
        assert view["provenance"]["evaluator"] == "independent_local_evidence_verifier"
        assert view["provenance"]["professional_quality_assessed"] is False
        assert view["window"]["days"] and view["window"]["newest_observation"]
    ids = [ref["evaluation_id"] for view in (model, role, decision) for ref in view["evidence_refs"]]
    assert len(ids) == len(set(ids)), "a scope is reading another scope's evidence"


def test_a_subject_never_sees_another_subject_of_the_same_kind(scopes):
    service, context, policy, model_ref, _role_ref, _decision_ref = scopes
    for _ in range(3):
        _observe(service, context, policy, subject=model_ref)
    # A second stored model is unnecessary: an id with no evaluations is the
    # sharper case, because it must report nothing rather than someone else's.
    unknown = c.EntityRef(kind=EntityKind.MODEL, entity_id=uuid4(), revision=1, scope=context.scope)

    assert _measure(service, context, model_ref)["sample_size"] == 3
    empty = _measure(service, context, unknown)
    assert empty["sample_size"] == 0 and empty["status"] == "new" and empty["evidence_refs"] == []


def test_task_class_is_part_of_the_measurement(scopes):
    service, context, policy, model_ref, _role_ref, _decision_ref = scopes
    for _ in range(3):
        _observe(service, context, policy, subject=model_ref)
    _observe(service, context, policy, subject=model_ref, task_class="extract_facts")

    arithmetic = _measure(service, context, model_ref)
    extraction = _measure(service, context, model_ref, task_class="extract_facts")
    assert arithmetic["sample_size"] == 3 and arithmetic["status"] == "measured"
    assert extraction["sample_size"] == 1 and extraction["status"] == "new"


def test_a_self_scored_observation_is_not_counted_in_any_scope(scopes):
    service, context, policy, model_ref, _role_ref, _decision_ref = scopes
    for _ in range(3):
        _observe(service, context, policy, subject=model_ref, self_scored=True)
    view = _measure(service, context, model_ref)
    assert view["sample_size"] == 0 and view["status"] == "new"


def test_synthetic_observations_are_counted_but_named(scopes):
    """They record a real run, and are never silently a provider's."""
    service, context, policy, model_ref, _role_ref, _decision_ref = scopes
    for _ in range(3):
        _observe(service, context, policy, subject=model_ref, synthetic=True)
    view = _measure(service, context, model_ref)
    assert view["sample_size"] == 3
    assert view["provenance"]["synthetic_observations"] == 3
    assert view["provenance"]["measured_observations"] == 0


def test_a_kind_nobody_measures_is_refused_rather_than_scored(scopes):
    service, context, *_ = scopes
    for kind in (EntityKind.TASK, EntityKind.OUTCOME, EntityKind.PERSONA):
        with pytest.raises(ContractError) as refused:
            service.reputation(context=context, subject_kind=kind, subject_id=uuid4(),
                               task_class=TASK_CLASS)
        assert refused.value.code == "reputation_scope_unsupported"


def test_every_declared_scope_maps_to_exactly_one_subject_kind():
    kinds = list(reputation.SCOPES.values())
    assert len(kinds) == len(set(kinds)) == 3
    for name, kind in reputation.SCOPES.items():
        assert reputation.scope_for(kind) == name


def test_the_task_detail_carries_both_scopes_named_and_unmerged(setup):  # noqa: F811
    """The API path a panel reads: two scopes, each saying whose it is."""
    from app.ai_control_center import model_chat  # noqa: F401
    service, context = setup[0], setup[1]
    model = connected(setup, key="reputation-detail-model")
    from tests.test_agent_world_models import task as start
    pending = start(setup, model, key="reputation-detail-task")
    service.execute(context=context, task_id=pending["id"])
    detail = service.task_detail(context=context, task_id=pending["id"])

    views = detail["reputation"]
    assert set(views) == {"model_performance", "agent_role_performance"}
    for name, view in views.items():
        assert view["scope"] == name
        assert view["subject"]["kind"] == ("model" if name == "model_performance" else "agent_role")
        assert view["task_class"] and view["window"]["days"]
        assert view["provenance"]["professional_quality_assessed"] is False
        assert "confidence" in view and "sample_size" in view
    # The two subjects are different records, so the scores cannot be the same
    # measurement wearing two labels.
    assert views["model_performance"]["subject"]["id"] != views["agent_role_performance"]["subject"]["id"]
    # One observation is never enough in either scope.
    assert all(view["status"] == "new" for view in views.values())
    assert all(view["quality"]["observed_pct"] is None for view in views.values())


def test_measuring_the_same_rows_twice_gives_the_same_answer(scopes):
    """A measurement is a function of its evidence, not of when it was read.

    Two reads seconds apart described the same three observations differently,
    because the window was stamped with the wall clock. Anything comparing two
    reads of one task — and a person looking at the panel twice — saw a score
    that had apparently moved while nothing happened.
    """
    service, context, policy, model_ref, _role_ref, _decision_ref = scopes
    for _ in range(3):
        _observe(service, context, policy, subject=model_ref)

    first = _measure(service, context, model_ref)
    second = _measure(service, context, model_ref)
    assert first == second

    # And it does move when the evidence does.
    _observe(service, context, policy, subject=model_ref, passed=False)
    third = _measure(service, context, model_ref)
    assert third["sample_size"] == 4 and third != first


def test_a_sample_of_only_diagnostics_is_not_reported_as_observed_performance(scopes):
    """Four local test-executor runs are not a model scoring 100%.

    The live walk produced exactly this: a green headline percentage off a
    sample that was entirely synthetic. The rate is still computed — it is true
    about the diagnostic — but the basis says what it is, and the limitation
    says it in words.
    """
    service, context, policy, model_ref, _role_ref, _decision_ref = scopes
    for _ in range(4):
        _observe(service, context, policy, subject=model_ref, synthetic=True)

    view = _measure(service, context, model_ref)
    assert view["status"] == "measured" and view["sample_size"] == 4
    assert view["basis"] == "diagnostic"
    assert view["provenance"]["measured_observations"] == 0
    assert "диагности" in view["limitation"]
    assert "не наблюдаемое качество" in view["limitation"]


def test_basis_separates_field_evidence_from_diagnostics_and_from_a_mixture(scopes):
    service, context, policy, model_ref, role_ref, decision_ref = scopes
    for _ in range(3):
        _observe(service, context, policy, subject=model_ref)
    assert _measure(service, context, model_ref)["basis"] == "field"

    for _ in range(3):
        _observe(service, context, policy, subject=role_ref, synthetic=True)
    _observe(service, context, policy, subject=role_ref)
    mixed = _measure(service, context, role_ref)
    assert mixed["basis"] == "mixed" and mixed["provenance"]["synthetic_observations"] == 3

    assert _measure(service, context, decision_ref)["basis"] == "none"
