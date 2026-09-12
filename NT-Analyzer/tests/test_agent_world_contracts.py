from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.ai_control_center import contracts as c
from app.ai_control_center.domain_contracts import CalendarItem, CourtCase, CourtVote, Routine, StrategyProject
from app.ai_control_center.model_contracts import Evaluation
from app.ai_control_center.external_agent_contracts import ExternalAgentConnection
from app.ai_control_center.external_agent_protocol import PROTOCOL, CAPABILITIES
from app.ai_control_center.events import (EventData, EventEnvelope, MutationIdentity,
                                         is_replay)
from app.ai_control_center.repositories import PageRequest, validate_commit
from app.ai_control_center.states import (ContractError, EntityKind, INITIAL_STATES,
                                         TRANSITIONS, validate_transition)


NOW = datetime(2026, 9, 4, 22, 0, tzinfo=timezone.utc)
USER = UUID(int=1)
SCOPE = c.TenantScope(environment=c.Environment.DEVELOPMENT, workspace_id="ws_example01")
ACTOR = c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=USER)
CONTEXT = c.RequestContext(scope=SCOPE, user_uuid=USER, actor=ACTOR)


def snapshot(scope=SCOPE, number=90):
    return c.SnapshotRef(artifact_id=UUID(int=number), sha256="a" * 64, scope=scope)


def ref(kind, scope=SCOPE, number=30):
    return c.EntityRef(kind=kind, entity_id=UUID(int=number), revision=1, scope=scope)


def external(authority):
    return c.ExternalRef(authority=authority, key="opaque-test-reference", scope=SCOPE)


def header(**changes):
    values = dict(entity_id=UUID(int=2), scope=SCOPE, owner_user_uuid=USER, revision=1,
                  created_at=NOW, updated_at=NOW, created_by=ACTOR,
                  correlation_id=UUID(int=3), policy=snapshot())
    return c.RecordHeader(**{**values, **changes})


def record(kind=EntityKind.TASK, **changes):
    definitions = {
        EntityKind.EXTERNAL_AGENT_CONNECTION: (ExternalAgentConnection, dict(
            display_name="External fixture", protocol=PROTOCOL, endpoint="https://agent.example/a2a",
            credential=external(c.ExternalAuthority.CREDENTIAL), requested_capabilities=tuple(sorted(CAPABILITIES)))),
        EntityKind.PERSONA: (c.Persona, dict(display_name="Марина", profile=snapshot())),
        EntityKind.AGENT_ROLE: (c.AgentRole, dict(role_key="accountant", responsibilities=snapshot(),
                                               capability_ceiling=("ai_lab",), autonomy_ceiling=c.Autonomy.ADVICE)),
        EntityKind.PROVIDER_ACCOUNT: (c.ProviderAccount, dict(provider_key="test_provider",
                                                            credential=external(c.ExternalAuthority.CREDENTIAL))),
        EntityKind.MODEL: (c.Model, dict(provider_key="test_provider", model_key="sample/model-v1",
                                        profile=snapshot(), modalities=("text",))),
        EntityKind.INTENT: (c.Intent, dict(goal=snapshot(), acceptance=snapshot(), risk=c.Risk.LOW,
                                          autonomy=c.Autonomy.DRAFT, budget=external(c.ExternalAuthority.BUDGET),
                                          deadline=NOW + timedelta(hours=1))),
        EntityKind.TASK: (c.Task, dict(intent=ref(EntityKind.INTENT), role=ref(EntityKind.AGENT_ROLE))),
        EntityKind.CONTRIBUTION: (c.Contribution, dict(task=ref(EntityKind.TASK), role=ref(EntityKind.AGENT_ROLE),
                                                      result=snapshot(), evidence=(snapshot(),))),
        EntityKind.DECISION: (c.Decision, dict(intent=ref(EntityKind.INTENT), contributions=(),
                                              evidence_packet=snapshot())),
        EntityKind.EXECUTION: (c.Execution, dict(decision=ref(EntityKind.DECISION), approval=snapshot(),
                                                command=external(c.ExternalAuthority.COMMAND))),
        EntityKind.OUTCOME: (c.Outcome, dict(task=ref(EntityKind.TASK), evidence=(snapshot(),))),
        EntityKind.MEMORY: (c.Memory, dict(memory_class=c.MemoryClass.PRIVATE, visibility=c.Visibility.PRIVATE,
                                         sensitivity=c.Sensitivity.CONFIDENTIAL, content=snapshot(),
                                         provenance=(snapshot(),), retention_until=NOW + timedelta(days=1))),
        EntityKind.STRATEGY_PROJECT: (StrategyProject, dict(title="Scoped project", definition=snapshot())),
        EntityKind.ROUTINE: (Routine, dict(title="Review outcomes", definition=snapshot(), provenance=(snapshot(),))),
        EntityKind.CALENDAR_ITEM: (CalendarItem, dict(title="Review", definition=snapshot(), provenance=(snapshot(),),
                                                     starts_at=NOW, ends_at=NOW + timedelta(hours=1))),
        EntityKind.COURT_CASE: (CourtCase, dict(decision=ref(EntityKind.DECISION), packet=snapshot(),
                                               models=tuple(ref(EntityKind.MODEL, number=40 + index) for index in range(3)),
                                               session_ids=tuple(UUID(int=50 + index) for index in range(3)), risk=c.Risk.LOW)),
        EntityKind.COURT_VOTE: (CourtVote, dict(case=ref(EntityKind.COURT_CASE), model=ref(EntityKind.MODEL),
                                               session_id=UUID(int=50), packet=snapshot(), verdict="abstain", confidence=0,
                                               rationale=snapshot(), provider_key="test_provider", model_key="sample/model-v1",
                                               model_version="fixture-v1", failure_domain="fixture-domain")),
        EntityKind.EVALUATION: (Evaluation, dict(task=ref(EntityKind.TASK), outcome=ref(EntityKind.OUTCOME),
                                                evidence=snapshot(), subject=ref(EntityKind.MODEL), rubric_key="fixture-rubric-v1")),
    }
    cls, values = definitions[kind]
    return cls(**{**values, "header": header(), "status": INITIAL_STATES[kind], **changes})


def event_for(item, **changes):
    suffix = "recorded" if item.KIND in {EntityKind.COURT_VOTE, EntityKind.EVALUATION} else "changed"
    values = dict(event_id=UUID(int=80), event_type=f"stratforge.ai.{item.KIND.value}.{suffix}",
                  time=item.header.updated_at, subject=item.ref(), actor=ACTOR,
                  correlation_id=item.header.correlation_id, policy=item.header.policy,
                  data=EventData(references=(snapshot(),)))
    return EventEnvelope(**{**values, **changes})


def commit_args(item, previous=None, **event_changes):
    expected = 0 if previous is None else previous.header.revision
    event = event_for(item, **event_changes)
    mutation = MutationIdentity.for_record(context=CONTEXT, operation=f"{item.KIND.value}.write",
                                           idempotency_key="example-idempotency-key",
                                           record=item, expected_revision=expected, event=event)
    return dict(context=CONTEXT, record=item, expected_revision=expected,
                event=event, mutation=mutation, previous=previous)


@pytest.mark.parametrize("kind", list(EntityKind))
def test_all_entity_contracts_have_typed_identity_and_immutable_payload(kind):
    item = record(kind)
    assert item.ref().kind is kind
    assert item.ref().scope == SCOPE
    assert json.loads(json.dumps(c.primitive(item)))["kind"] == kind.value
    with pytest.raises(FrozenInstanceError):
        item.status = "active"


def test_persona_role_provider_and_model_fields_do_not_conflate_authorities():
    assert not {"model", "provider", "credential", "capability_ceiling"} & {f.name for f in fields(c.Persona)}
    assert not {"model", "credential", "provider_account"} & {f.name for f in fields(c.AgentRole)}
    assert "credential" in {f.name for f in fields(c.ProviderAccount)}
    assert "credential" not in {f.name for f in fields(c.Model)}
    with pytest.raises(ContractError, match="reference_kind_mismatch"):
        record(role=ref(EntityKind.MODEL))
    with pytest.raises(ContractError, match="external_authority_mismatch"):
        record(EntityKind.PROVIDER_ACCOUNT, credential=external(c.ExternalAuthority.COMMAND))


@pytest.mark.parametrize("workspace", ["", "global", "ws_short", "ws_example01/../other", "*"])
def test_missing_or_unsafe_workspace_never_defaults_to_owner(workspace):
    with pytest.raises(ContractError, match="invalid_workspace"):
        c.TenantScope(environment=c.Environment.DEVELOPMENT, workspace_id=workspace)


def test_environment_user_and_utc_are_explicit():
    with pytest.raises(ContractError, match="invalid_enum"):
        c.TenantScope(environment="development", workspace_id=SCOPE.workspace_id)
    with pytest.raises(ContractError, match="invalid_uuid"):
        replace(CONTEXT, user_uuid="1")
    with pytest.raises(ContractError, match="utc_required"):
        header(created_at=NOW.replace(tzinfo=None))
    with pytest.raises(ContractError, match="unsupported_schema"):
        header(schema_version=True)
    with pytest.raises(ContractError, match="timestamp_order"):
        header(updated_at=NOW - timedelta(seconds=1))


@pytest.mark.parametrize("foreign", [
    replace(SCOPE, workspace_id="ws_example02"),
    replace(SCOPE, environment=c.Environment.CANARY),
    replace(SCOPE, environment=c.Environment.PRODUCTION),
])
def test_cross_tenant_nested_edges_and_policy_are_denied(foreign):
    with pytest.raises(ContractError, match="scope_mismatch"):
        record(role=ref(EntityKind.AGENT_ROLE, scope=foreign))
    with pytest.raises(ContractError, match="scope_mismatch"):
        record(dependencies=(ref(EntityKind.TASK, scope=foreign),))
    with pytest.raises(ContractError, match="scope_mismatch"):
        header(policy=snapshot(foreign))
    with pytest.raises(ContractError, match="scope_mismatch"):
        c.validate_record_scope(replace(CONTEXT, scope=foreign), record())
    with pytest.raises(ContractError, match="scope_mismatch"):
        event_for(record(), data=EventData(references=(snapshot(foreign),)))


def test_private_memory_is_not_shared_with_another_user_in_same_workspace():
    other = UUID(int=99)
    context = c.RequestContext(scope=SCOPE, user_uuid=other,
                               actor=c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=other))
    c.validate_record_scope(CONTEXT, record(EntityKind.MEMORY))
    with pytest.raises(ContractError, match="private_memory_denied"):
        c.validate_record_scope(context, record(EntityKind.MEMORY))
    with pytest.raises(ContractError, match="private_memory_visibility"):
        record(EntityKind.MEMORY, visibility=c.Visibility.WORKSPACE)


def test_delegated_actor_preserves_human_and_cannot_borrow_identity():
    agent = c.ActorRef(kind=c.ActorKind.AGENT, actor_id=UUID(int=50), on_behalf_of=USER)
    assert replace(CONTEXT, actor=agent).actor.actor_id != USER
    for actor in (replace(agent, on_behalf_of=None), replace(agent, on_behalf_of=UUID(int=99)),
                  c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=UUID(int=99))):
        with pytest.raises(ContractError, match="actor_user_mismatch"):
            replace(CONTEXT, actor=actor)


def test_mutable_payload_and_self_dependencies_are_rejected():
    with pytest.raises(ContractError, match="mutable_payload"):
        record(dependencies=[ref(EntityKind.TASK)])
    with pytest.raises(ContractError, match="invalid_dependency"):
        record(dependencies=(ref(EntityKind.TASK, number=2),))
    with pytest.raises(ContractError, match="invalid_dependency"):
        record(dependencies=(ref(EntityKind.TASK), ref(EntityKind.TASK)))
    with pytest.raises(ContractError, match="invalid_modalities"):
        record(EntityKind.MODEL, modalities=("unrestricted-tools",))


@pytest.mark.parametrize("kind,status,error", [
    (EntityKind.DECISION, "approved", "approval_required"),
    (EntityKind.EXECUTION, "succeeded", "receipt_required"),
    (EntityKind.OUTCOME, "verified", "verification_required"),
])
def test_success_claim_requires_a_structural_proof_reference(kind, status, error):
    with pytest.raises(ContractError, match=error):
        record(kind, status=status)


def test_memory_has_retention_and_verified_lesson_provenance():
    with pytest.raises(ContractError, match="verification_required"):
        record(EntityKind.MEMORY, memory_class=c.MemoryClass.VERIFIED_LESSON)
    with pytest.raises(ContractError, match="memory_provenance_or_retention_required"):
        record(EntityKind.MEMORY, retention_until=NOW)
    with pytest.raises(ContractError, match="memory_task_required"):
        record(EntityKind.MEMORY, memory_class=c.MemoryClass.TASK)


@pytest.mark.parametrize("kind,states", [
    (EntityKind.INTENT, ("draft", "ready", "running", "completed")),
    (EntityKind.TASK, ("planned", "ready", "running", "waiting", "ready", "running", "succeeded")),
    (EntityKind.DECISION, ("proposed", "review", "approved", "superseded")),
    (EntityKind.EXECUTION, ("requested", "queued", "running", "deviated")),
    (EntityKind.MEMORY, ("draft", "active", "revoked")),
])
def test_explicit_lifecycles_and_terminal_resume_denial(kind, states):
    for before, after in zip(states, states[1:]):
        validate_transition(kind, before, after)
    with pytest.raises(ContractError, match="invalid_transition"):
        validate_transition(kind, states[-1], states[0])


def test_unknown_state_and_direct_approval_are_not_transitions():
    with pytest.raises(ContractError, match="invalid_state"):
        validate_transition(EntityKind.TASK, "provider-says-done", "succeeded")
    with pytest.raises(ContractError, match="invalid_transition"):
        validate_transition(EntityKind.DECISION, "proposed", "approved")
    with pytest.raises(TypeError):
        TRANSITIONS[EntityKind.TASK]["running"] = frozenset({"approved"})


def test_envelope_is_fresh_reference_only_and_preserves_correlation():
    item = record()
    event = event_for(item, causation_id=UUID(int=81))
    wire = event.as_dict()
    assert wire["specversion"] == "1.0"
    assert wire["correlationid"] == str(item.header.correlation_id)
    assert wire["causationid"] == str(UUID(int=81))
    assert wire["workspaceid"] == SCOPE.workspace_id
    assert all(key.isalnum() and key.lower() == key for key in wire)
    assert not {"api_key", "prompt", "messages", "reasoning", "idempotency_key"} & set(wire["data"])
    wire["data"]["references"].clear()
    assert len(event.as_dict()["data"]["references"]) == 1
    with pytest.raises(TypeError):
        EventData(prompt="example untrusted prompt")
    with pytest.raises(ContractError, match="unknown_event_type"):
        event_for(item, event_type="stratforge.ai.permissions.granted")
    with pytest.raises(ContractError, match="event_self_causation"):
        replace(event, causation_id=event.event_id)


def test_idempotent_retry_and_conflicting_payload_are_distinct():
    args = commit_args(record())
    first = args["mutation"]
    assert is_replay(first, replace(first))
    assert "example-idempotency-key" not in repr(first)
    assert first.storage_key[:2] == ("development", SCOPE.workspace_id)
    assert not is_replay(first, replace(first, scope=replace(SCOPE, environment=c.Environment.CANARY)))
    assert not is_replay(first, replace(first, operation="task.cancel"))
    with pytest.raises(ContractError, match="idempotency_conflict"):
        is_replay(first, replace(first, request_hash="b" * 64))


def test_mutation_hash_changes_with_actor_and_expected_revision():
    args = commit_args(record())
    values = dict(context=CONTEXT, operation="task.write", idempotency_key="example-idempotency-key",
                  record=args["record"], event=args["event"], expected_revision=1)
    assert MutationIdentity.for_record(**values).request_hash != args["mutation"].request_hash
    agent = c.ActorRef(kind=c.ActorKind.AGENT, actor_id=UUID(int=50), on_behalf_of=USER)
    values.update(context=replace(CONTEXT, actor=agent), expected_revision=0)
    assert MutationIdentity.for_record(**values).request_hash != args["mutation"].request_hash


def test_commit_preconditions_validate_create_transition_and_checkpoint():
    item = record()
    validate_commit(**commit_args(item))
    ready = replace(item, header=header(revision=2, updated_at=NOW + timedelta(seconds=1)), status="ready")
    validate_commit(**commit_args(ready, item))
    running = replace(ready, header=header(revision=3, updated_at=NOW + timedelta(seconds=2)), status="running")
    validate_commit(**commit_args(running, ready))
    checkpoint = replace(running, header=header(revision=4, updated_at=NOW + timedelta(seconds=3)), checkpoint=snapshot())
    validate_commit(**commit_args(checkpoint, running))


@pytest.mark.parametrize("change,error", [
    ({"event_type": "stratforge.ai.outcome.changed"}, "event_kind_mismatch"),
    ({"actor": c.ActorRef(kind=c.ActorKind.SERVICE, actor_id=UUID(int=99), on_behalf_of=USER)}, "event_subject_or_actor_mismatch"),
    ({"policy": snapshot(number=99)}, "event_provenance_mismatch"),
    ({"correlation_id": UUID(int=99)}, "event_provenance_mismatch"),
    ({"time": NOW + timedelta(seconds=1)}, "event_provenance_mismatch"),
    ({"event_type": "stratforge.ai.task.completed"}, "event_state_mismatch"),
])
def test_forged_event_cannot_accompany_record(change, error):
    with pytest.raises(ContractError, match=error):
        validate_commit(**commit_args(record(), **change))


def test_commit_rejects_unsafe_insert_stale_revision_and_identity_rewrite():
    item = record()
    with pytest.raises(ContractError, match="initial_state_required"):
        validate_commit(**commit_args(replace(item, status="succeeded")))
    next_item = replace(item, header=header(revision=3), status="ready")
    with pytest.raises(ContractError, match="revision_conflict"):
        validate_commit(**commit_args(next_item, item))
    next_item = replace(item, header=header(revision=2, owner_user_uuid=UUID(int=99)), status="ready")
    with pytest.raises(ContractError, match="immutable_identity_changed"):
        validate_commit(**commit_args(next_item, item))
    terminal = replace(item, status="succeeded")
    changed_terminal = replace(terminal, header=header(revision=2), checkpoint=snapshot())
    with pytest.raises(ContractError, match="finalized_record_immutable"):
        validate_commit(**commit_args(changed_terminal, terminal))


def test_mutation_cannot_be_reused_for_another_record_payload():
    args = commit_args(record())
    args["mutation"] = replace(args["mutation"], request_hash="b" * 64)
    with pytest.raises(ContractError, match="mutation_payload_mismatch"):
        validate_commit(**args)


@pytest.mark.parametrize("kind", list(EntityKind))
def test_each_entity_can_be_created_only_through_its_initial_state(kind):
    validate_commit(**commit_args(record(kind)))


@pytest.mark.parametrize("kind,before,after", [
    (kind, before, after) for kind, states in TRANSITIONS.items()
    for before, successors in states.items() for after in sorted(successors)
])
def test_each_declared_edge_can_commit_with_preserved_evidence_and_a_revision_event(kind, before, after):
    proof = {
        EntityKind.EXTERNAL_AGENT_CONNECTION: {"advertised_capabilities": tuple(sorted(CAPABILITIES)),
            "allowed_capabilities": tuple(sorted(CAPABILITIES)), "last_verification": NOW, "card_sha256": "a" * 64},
        EntityKind.DECISION: {"approval": snapshot()},
        EntityKind.EXECUTION: {"receipt": snapshot()},
        EntityKind.OUTCOME: {"verification": snapshot()},
        EntityKind.COURT_CASE: {"votes": tuple(ref(EntityKind.COURT_VOTE, number=60 + index) for index in range(3)),
                               "verdict": "approve"},
    }.get(kind, {})
    previous = record(kind, status=before, **proof)
    following = replace(previous, status=after, header=header(revision=2))
    validate_commit(**commit_args(following, previous))


def test_superseding_an_approved_decision_preserves_its_original_evidence():
    approved = record(EntityKind.DECISION, status="approved", approval=snapshot(number=91))
    successor = replace(approved, status="superseded", header=header(revision=2))
    validate_commit(**commit_args(successor, approved))
    with pytest.raises(ContractError, match="finalized_payload_immutable"):
        validate_commit(**commit_args(replace(successor, evidence_packet=snapshot(number=99)), approved))
    with pytest.raises(ContractError, match="finalized_payload_immutable"):
        validate_commit(**commit_args(replace(successor, header=header(revision=2, policy=snapshot(number=99))), approved))


@pytest.mark.parametrize("limit", [0, 101, True, -1])
def test_repository_pagination_is_bounded(limit):
    with pytest.raises(ContractError, match="invalid_page_limit"):
        PageRequest(limit=limit)


@pytest.mark.parametrize("kind", [EntityKind.MODEL, EntityKind.AGENT_ROLE, EntityKind.DECISION])
def test_an_evaluation_accepts_every_declared_subject_kind(kind):
    """One contract, several kinds of thing to be good at."""
    from app.ai_control_center.model_contracts import SUBJECT_KINDS

    assert kind in SUBJECT_KINDS
    item = record(EntityKind.EVALUATION, subject=ref(kind))
    assert item.subject.kind is kind
    validate_commit(**commit_args(item))


@pytest.mark.parametrize("kind", [EntityKind.TASK, EntityKind.OUTCOME, EntityKind.PERSONA,
                                  EntityKind.INTENT, EntityKind.MEMORY])
def test_an_evaluation_refuses_a_subject_kind_nobody_measures(kind):
    with pytest.raises(ContractError) as refused:
        record(EntityKind.EVALUATION, subject=ref(kind))
    assert refused.value.code == "evaluation_subject_kind_unsupported"


def test_a_subject_must_be_a_typed_reference_at_all():
    with pytest.raises(ContractError) as refused:
        record(EntityKind.EVALUATION, subject=snapshot())
    assert refused.value.code == "reference_kind_mismatch"


def test_one_subject_score_is_never_readable_as_another():
    """The compatibility accessor refuses rather than quietly answering.

    A caller asking a role's evaluation for its "model" has made a mistake, and
    returning the role would put an agent-role score where a model score is
    displayed — the exact conflation these scopes exist to prevent.
    """
    model_eval = record(EntityKind.EVALUATION, subject=ref(EntityKind.MODEL))
    assert model_eval.model == model_eval.subject

    for kind in (EntityKind.AGENT_ROLE, EntityKind.DECISION):
        other = record(EntityKind.EVALUATION, subject=ref(kind))
        with pytest.raises(ContractError) as refused:
            _ = other.model
        assert refused.value.code == "evaluation_subject_not_a_model"


def test_an_evaluation_written_before_subjects_existed_still_decodes():
    """Stored bytes are not rewritten; the old field name is mapped on read."""
    import json
    from app.ai_control_center import contracts as c
    from app.ai_control_center.storage_codec import decode_record, encode_record

    item = record(EntityKind.EVALUATION, subject=ref(EntityKind.MODEL))
    legacy = json.loads(encode_record(item))
    legacy["model"] = legacy.pop("subject")          # exactly what old rows hold
    assert "subject" not in legacy

    restored = decode_record(json.dumps(legacy))
    assert restored == item
    assert restored.subject.kind is EntityKind.MODEL
    assert restored.model == item.subject
    # And a row carrying both names is refused rather than guessed at.
    both = json.loads(encode_record(item))
    both["model"] = both["subject"]
    with pytest.raises(ContractError):
        decode_record(json.dumps(both))
