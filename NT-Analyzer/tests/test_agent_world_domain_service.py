"""Isolated real-SQLite domain, scope, replay, TTL and independent Court tests."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5

import pytest

from app.ai_control_center import contracts as c
from app.ai_control_center.domain_contracts import JudgeResult
from app.ai_control_center.domain_service import DomainService
from app.ai_control_center.repositories import PageRequest
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_storage import arguments, artifact, context, persona, update


NOW = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("domain tests must never open a network connection"))
    repo = SQLiteAgentWorldRepository(tmp_path / "private-test" / "domain.sqlite3")
    state = SimpleNamespace(allowed=True, checks=0, now=NOW, calls=[], jobs={})

    def admit():
        state.checks += 1
        if not state.allowed:
            raise ContractError("test_access_revoked")

    def enqueue(**kwargs):
        assert kwargs["payload"]["automation_enabled"] is False
        assert kwargs["payload"]["manual_review_required"] is True
        state.calls.append(kwargs)
        key = kwargs["idempotency_key"]
        state.jobs.setdefault(key, {"job_id": "job_" + str(len(state.jobs) + 1), "status": "queued"})
        return state.jobs[key]

    service = DomainService(repo, now=lambda: state.now, enqueue=enqueue)
    return SimpleNamespace(repo=repo, service=service, ctx=context(), state=state, admit=admit, enqueue=enqueue)


def create(env, domain="personas", payload=None, key="create-persona-001", ctx=None):
    return env.service.create(context=ctx or env.ctx, admit=env.admit, domain=domain,
                              payload=payload or {"name": "Марина", "description": "Аналитик", "style": "Кратко"},
                              idempotency_key=key)


def act(env, item, domain="personas", action="activate", payload=None, key=None, ctx=None):
    return env.service.act(context=ctx or env.ctx, admit=env.admit, domain=domain, entity_id=item["id"],
                           action=action, payload=payload or {}, expected_revision=item["revision"],
                           idempotency_key=key or f"action-{item['id']}-{action}-{item['revision']}")


def get(env, domain, identity, ctx=None):
    return env.service.get(context=ctx or env.ctx, admit=env.admit, domain=domain, entity_id=identity)


def stored_count(env, table):
    with sqlite3.connect(env.repo.path) as db:
        return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def source(env, value=None, ctx=None):
    return env.repo.put_artifact(context=ctx or env.ctx, content=json.dumps(value or {"assertions": {"passed": True}, "observations": 3}).encode(),
                                media_type="application/json")


def memory_payload(**changes):
    return {"title": "Risk process", "content": "Always record the source result.", "purpose": "report_review",
            "retention_days": 2, **changes}


def project_payload(**changes):
    return {"title": "MNQ research", "description": "Historical research only", "strategy_key": "SampleMACrossOver", **changes}


def decision(env, *, risk="low", key="new-decision-001"):
    evidence = source(env)
    return create(env, "decisions", {"title": "Review report", "proposal": "Accept the historical analysis as a research result.",
                                     "evidence_ids": [str(evidence.artifact_id)], "risk": risk, "trigger": "requested_review"}, key)["item"]


def models(env):
    records = []
    for index in range(3):
        base = persona(env.repo, ctx=env.ctx)
        record = c.Model(header=base.header, status="draft", provider_key=f"provider{index}", model_key=f"test-model-{index}",
                         profile=base.profile, modalities=("text",))
        env.repo.commit(**arguments(record, ctx=env.ctx))
        record = update(record)
        env.repo.commit(**arguments(record, ctx=env.ctx))
        records.append(record)
    return records


def judges(env, records, *, verdicts=("approve", "approve", "reject"), domains=None, fail_at=None):
    calls = []
    domains = domains or ("provider0/test-model-0", "provider1/test-model-1", "provider2/test-model-2")

    def judge(request):
        index = next(index for index, record in enumerate(records) if record.header.entity_id == request.model_id)
        calls.append(request)
        if index == fail_at:
            raise RuntimeError("fixture provider unavailable")
        confidence, rationale = (1, 2, 100)[index], f"Independent evidence review {index}"
        contribution = judge_contribution(env, request, verdicts[index], confidence, rationale)
        return JudgeResult(verdict=verdicts[index], confidence=confidence, rationale=rationale,
                           provider_key=records[index].provider_key, model_key=records[index].model_key,
                           model_version="fixture-runtime-v1", failure_domain=domains[index], contribution_id=contribution.header.entity_id)

    env.service.judge_runner = judge
    return calls


def judge_contribution(env, request, verdict, confidence, rationale):
    """Isolated transport fixture with the same accepted receipt linkage."""
    service, ctx = env.service, env.ctx
    policy = source(env, {"policy": "isolated-judge-fixture", "network_calls": False})

    def header(name):
        return service._header(ctx, uuid5(request.session_id, name), policy, correlation_id=request.case_id)

    def save(record):
        return service._save(ctx, env.admit, record, "fixture.judge." + record.KIND.value,
                              str(record.header.entity_id) + "." + str(record.header.revision), "0" * 64).record

    role = save(c.AgentRole(header=header("role"), status="draft", role_key="isolated_fixture_judge",
                            responsibilities=policy, capability_ceiling=(), autonomy_ceiling=c.Autonomy.ADVICE))
    intent = save(c.Intent(header=header("intent"), status="draft", goal=policy, acceptance=policy,
                           risk=c.Risk.LOW, autonomy=c.Autonomy.ADVICE,
                           budget=c.ExternalRef(authority=c.ExternalAuthority.BUDGET, key="existing-test-budget", scope=ctx.scope),
                           deadline=NOW + timedelta(days=1)))
    task_header = header("task")
    checkpoint = source(env, {"source": "real_model_task", "synthetic": False, "model_id": str(request.model_id),
                              "request_sha256": "1" * 64,
                              "spec": {"rubric_key": "court_vote", "session_id": str(request.session_id), "case_id": str(request.case_id),
                                       "packet_sha256": request.packet_sha256, "policy_version": request.policy_version,
                                       "prompt_version": request.prompt_version}})
    task = save(c.Task(header=task_header, status="planned", role=role.ref(), intent=intent.ref(), checkpoint=checkpoint))
    for state in ("ready", "running", "succeeded"):
        task = save(service._change(task, status=state))
    receipt = source(env, {"source": "provider_response", "synthetic": False, "task_id": str(task.header.entity_id),
                           "request_sha256": "1" * 64,
                           "response": json.dumps({"verdict": verdict, "confidence": confidence, "rationale": rationale})})
    contribution = save(c.Contribution(header=header("contribution"), status="draft", task=task.ref(), role=role.ref(),
                                       result=receipt, evidence=(receipt,)))
    for state in ("submitted", "accepted"):
        contribution = save(service._change(contribution, status=state))
    return contribution


def review(env, item, records, *, key="review-decision-001"):
    return act(env, item, "decisions", "review", {"model_ids": [str(record.header.entity_id) for record in records]}, key)


def test_persona_create_activate_update_and_retire_preserve_identity_and_revisions(env):
    first = create(env)["item"]
    assert first["status"] == "draft" and first["profile"]["style"] == "Кратко"
    active = act(env, first)["item"]
    changed = act(env, active, action="update", payload={"name": "Марина Research", "description": "Read-only", "style": "Concise"})["item"]
    assert changed["revision"] == 3 and changed["id"] == first["id"]
    assert not {"credential", "model_id", "capability_ceiling"} & changed.keys()
    retired = act(env, changed, action="archive")["item"]
    assert retired["status"] == "retired" and retired["actions"] == []
    with pytest.raises(ContractError, match="finalized_record_immutable"):
        act(env, retired, action="update", payload={"name": "Overwrite", "description": "", "style": ""})
    original = env.repo.get_revision(context=env.ctx, kind=EntityKind.PERSONA, entity_id=UUID(first["id"]), revision=1)
    assert original.display_name == "Марина"


def test_create_and_action_replay_return_original_revision_even_after_later_updates_and_restart(env):
    first = create(env)["item"]
    active = act(env, first, key="activation-replay-001")["item"]
    act(env, active, action="update", payload={"name": "Changed", "description": "", "style": ""})
    before = stored_count(env, "aw_events")
    env.service = DomainService(SQLiteAgentWorldRepository(env.repo.path), now=lambda: NOW)
    replay = create(env)
    replay_action = act(env, first, key="activation-replay-001")
    assert replay["replayed"] is True and replay["item"]["revision"] == 1
    assert replay_action["replayed"] is True and replay_action["item"]["revision"] == 2
    assert stored_count(env, "aw_events") == before


def test_reused_key_changed_payload_and_stale_revision_conflict(env):
    first = create(env)["item"]
    with pytest.raises(ContractError, match="idempotency_conflict"):
        create(env, payload={"name": "Other"})
    act(env, first)
    with pytest.raises(ContractError, match="revision_conflict"):
        act(env, first, action="archive", key="new-stale-operation")


@pytest.mark.parametrize("foreign", [context(user=2), context(workspace="ws_foreign01"), context(environment=c.Environment.CANARY)])
def test_all_domain_reads_and_mutations_reject_foreign_context(env, foreign):
    item = create(env)["item"]
    with pytest.raises(ContractError, match="domain_record_not_found|scope_mismatch"):
        get(env, "personas", item["id"], foreign)
    with pytest.raises(ContractError, match="domain_record_not_found|scope_mismatch"):
        act(env, item, action="archive", ctx=foreign)
    if foreign.scope.environment == c.Environment.DEVELOPMENT:
        assert env.service.list(context=foreign, admit=env.admit, domain="personas")["items"] == []


def test_same_workspace_users_can_reuse_client_keys_without_clobbering_each_other(env):
    first = create(env)["item"]
    other = create(env, ctx=context(user=2))["item"]
    assert first["id"] != other["id"]
    assert [item["id"] for item in env.service.list(context=env.ctx, admit=env.admit, domain="personas")["items"]] == [first["id"]]


def test_mutation_lookup_and_revision_read_enforce_user_and_workspace_scope(env):
    first = create(env)["item"]
    key = env.service._key(env.ctx, "create-persona-001")
    assert env.repo.lookup_mutation(context=env.ctx, operation="domain.personas.create", idempotency_key=key).record.header.revision == 1
    assert env.repo.lookup_mutation(context=context(user=2), operation="domain.personas.create", idempotency_key=key) is None
    assert env.repo.lookup_mutation(context=context(workspace="ws_foreign01"), operation="domain.personas.create", idempotency_key=key) is None
    assert env.repo.get_revision(context=context(user=2), kind=EntityKind.PERSONA, entity_id=UUID(first["id"]), revision=1) is None
    private = create(env, "memory", memory_payload(), "new-private-memory")["item"]
    assert env.repo.get_revision(context=context(user=2), kind=EntityKind.MEMORY, entity_id=UUID(private["id"]), revision=1) is None


def test_cursor_is_bound_to_owner_domain_and_snapshot(env):
    for index in range(3):
        create(env, key=f"pagination-{index:04}")
    first = env.service.list(context=env.ctx, admit=env.admit, domain="personas", limit=1)
    assert first["next_cursor"]
    create(env, key="pagination-later")
    following = env.service.list(context=env.ctx, admit=env.admit, domain="personas", cursor=first["next_cursor"])
    assert len(following["items"]) == 2
    for ctx, domain in [(context(user=2), "personas"), (env.ctx, "memory")]:
        with pytest.raises(ContractError, match="invalid_cursor"):
            env.service.list(context=ctx, admit=env.admit, domain=domain, cursor=first["next_cursor"])


def test_fresh_admission_applies_to_read_write_and_replay_without_domain_writes(env):
    item = create(env)["item"]
    env.state.allowed = False
    before = stored_count(env, "aw_events")
    for call in [lambda: create(env), lambda: get(env, "personas", item["id"]),
                 lambda: act(env, item), lambda: env.service.list(context=env.ctx, admit=env.admit, domain="personas")]:
        with pytest.raises(ContractError, match="test_access_revoked"):
            call()
    assert stored_count(env, "aw_events") == before


def test_judge_actor_cannot_control_persona_memory_or_acceptance(env):
    actor = c.ActorRef(kind=c.ActorKind.AGENT, actor_id=uuid4(), on_behalf_of=env.ctx.user_uuid)
    with pytest.raises(ContractError, match="domain_human_decision_required"):
        create(env, ctx=replace(env.ctx, actor=actor))


@pytest.mark.parametrize("payload", [
    {"name": "Profile", "api_key": "not-permitted"},
    {"name": "Profile", "description": "api_key=example-secret-value"},
    {"name": "Profile", "description": "sk-abcdefghijklmnopqrstuvw"},
    {"name": "Profile", "capabilities": ["trade"]},
    {"name": "Profile", "workspace_id": "ws_foreign01"},
])
def test_profile_does_not_accept_credentials_scope_or_capability_injection(env, payload):
    with pytest.raises(ContractError):
        create(env, payload=payload)
    assert stored_count(env, "aw_records") == 0


def test_memory_requires_manual_promotion_then_filters_purpose_and_ttl_without_get_writes(env):
    item = create(env, "memory", memory_payload(), "new-private-memory")["item"]
    assert env.service.retrieve_memory(context=env.ctx, admit=env.admit, purpose="report_review")["items"] == []
    promoted = act(env, item, "memory", "promote", {"reason": "I checked this procedure"})["item"]
    assert promoted["verification"]["method"] == "explicit_user_review" and promoted["visibility"] == "private"
    assert len(env.service.retrieve_memory(context=env.ctx, admit=env.admit, purpose="report_review")["items"]) == 1
    assert env.service.retrieve_memory(context=env.ctx, admit=env.admit, purpose="unrelated_task")["items"] == []
    before = stored_count(env, "aw_events")
    env.state.now += timedelta(days=3)
    expired = get(env, "memory", item["id"])
    assert expired["status"] == "expired" and expired["stored_status"] == "active" and "content" not in expired
    assert env.service.retrieve_memory(context=env.ctx, admit=env.admit, purpose="report_review")["items"] == []
    assert stored_count(env, "aw_events") == before


def test_revoked_memory_is_not_retrieved_or_reactivated_and_history_remains(env):
    item = create(env, "memory", memory_payload(), "new-private-memory")["item"]
    active = act(env, item, "memory", "promote", {"reason": "Reviewed"})["item"]
    revoked = act(env, active, "memory", "revoke", {"reason": "No longer correct"})["item"]
    assert revoked["status"] == "revoked" and "content" not in revoked
    assert env.service.retrieve_memory(context=env.ctx, admit=env.admit, purpose="report_review")["items"] == []
    with pytest.raises(ContractError, match="memory_not_promotable"):
        act(env, revoked, "memory", "promote", {"reason": "Try revival"})
    assert env.repo.get_revision(context=env.ctx, kind=EntityKind.MEMORY, entity_id=UUID(item["id"]), revision=1).status == "draft"


def test_memory_cannot_claim_foreign_evidence_or_extend_expired_draft(env):
    foreign = source(env, ctx=context(user=2))
    with pytest.raises(ContractError, match="domain_evidence_unavailable"):
        create(env, "memory", memory_payload(source_ids=[str(foreign.artifact_id)]), "invalid-evidence-001")
    item = create(env, "memory", memory_payload(), "new-private-memory")["item"]
    env.state.now += timedelta(days=3)
    with pytest.raises(ContractError, match="memory_expired"):
        act(env, item, "memory", "update", memory_payload(retention_days=10))


def test_project_versions_are_append_only_and_preserve_negative_parameters(env):
    item = create(env, "projects", project_payload(), "new-project-001")["item"]
    first = act(env, item, "projects", "version", {"notes": "Initial", "parameters": {"offset": -4.5, "enabled": False}})["item"]
    second = act(env, first, "projects", "version", {"notes": "Second", "parameters": {"offset": -2}})["item"]
    assert second["version_count"] == 2 and second["versions"][0]["parameters"]["offset"] == -4.5
    assert first["versions"][0]["created_at"] == c.primitive(env.state.now)
    assert second["versions"][0] == first["versions"][0]
    changed = act(env, second, "projects", "update", project_payload(description="New description"))["item"]
    assert changed["versions"] == second["versions"]
    archived = act(env, changed, "projects", "archive")["item"]
    with pytest.raises(ContractError, match="finalized_record_immutable"):
        act(env, archived, "projects", "version", {"notes": "Unauthorized rewrite", "parameters": {}})


@pytest.mark.parametrize("domain,payload", [
    ("routines", {"title": "Daily review", "description": "Check verified outcomes", "interval_minutes": 1440}),
    ("calendar", {"title": "Owner review", "description": "Manual", "starts_at": "2026-09-06T12:00:00Z", "ends_at": "2026-09-06T13:00:00Z"}),
])
def test_suggestions_default_off_accept_only_enqueues_existing_manual_followup_and_replay_dedupes(env, domain, payload):
    item = create(env, domain, payload, "new-suggestion-001")["item"]
    assert item["automation_enabled"] is False and env.state.calls == []
    accepted = act(env, item, domain, "accept", key="accept-suggestion-001")
    repeated = act(env, item, domain, "accept", key="accept-suggestion-001")
    assert accepted["item"]["status"] == "accepted" and accepted["item"]["handoff"]["job_id"] == "job_1"
    assert repeated["replayed"] and len(env.state.calls) == len(env.state.jobs) == 1
    env.service.get(context=env.ctx, admit=env.admit, domain=domain, entity_id=item["id"])
    assert len(env.state.calls) == 1


def test_suggestion_without_existing_queue_adapter_is_explicitly_blocked(env):
    env.service.enqueue = None
    item = create(env, "routines", {"title": "Daily review", "description": "", "interval_minutes": 1440}, "new-routine-001")["item"]
    assert "accept" not in item["actions"]
    with pytest.raises(ContractError, match="domain_followup_adapter_required"):
        act(env, item, "routines", "accept")
    assert get(env, "routines", item["id"])["status"] == "proposed"


def test_suggestion_queue_commit_crash_retries_the_same_existing_job_key(env, monkeypatch):
    item = create(env, "routines", {"title": "Review", "description": "", "interval_minutes": 30}, "routine-crash-001")["item"]
    original = env.service._save

    def crash(*args, **kwargs):
        if args[3].endswith(".accept"):
            raise RuntimeError("fixture crash after existing queue receipt")
        return original(*args, **kwargs)

    monkeypatch.setattr(env.service, "_save", crash)
    with pytest.raises(RuntimeError):
        act(env, item, "routines", "accept", key="stable-accept-001")
    monkeypatch.setattr(env.service, "_save", original)
    accepted = act(env, item, "routines", "accept", key="stable-accept-001")
    assert accepted["item"]["status"] == "accepted" and len(env.state.jobs) == 1
    assert env.state.calls[0]["idempotency_key"] == env.state.calls[1]["idempotency_key"]


def test_court_runs_three_isolated_contexts_same_immutable_packet_and_unweighted_two_of_three(env):
    item, records = decision(env), models(env)
    calls = judges(env, records)
    result = review(env, item, records)["item"]
    case = result["court_cases"][0]
    assert result["status"] == "approved" and case["verdict"] == "approve"
    assert len(calls) == len(set(call.session_id for call in calls)) == 3
    assert len(set(call.packet_json for call in calls)) == 1
    assert all(hashlib.sha256(call.packet_json.encode()).hexdigest() == call.packet_sha256 for call in calls)
    assert all(not any(word in json.loads(call.packet_json) for word in ("votes", "messages", "memory", "transcript")) for call in calls)
    assert "observations" in calls[0].packet_json
    assert case["votes"][2]["verdict"] == "reject" and case["votes"][2]["confidence"] == 100
    assert result["approval"]["execution_allowed"] is False and case["execution_allowed"] is False
    assert env.state.calls == []
    with pytest.raises(FrozenInstanceError):
        calls[0].packet_json = "changed"
    assert env.repo.list(context=env.ctx, kind=EntityKind.EXECUTION, page=PageRequest()).items == ()


def test_court_partial_failure_resumes_committed_votes_without_reasking_prior_judge(env):
    item, records = decision(env), models(env)
    calls = judges(env, records, fail_at=1)
    with pytest.raises(ContractError, match="court_judge_unavailable"):
        review(env, item, records)
    assert len(calls) == 2
    partial = get(env, "decisions", item["id"])
    assert partial["status"] == "review" and len(partial["court_cases"][0]["votes"]) == 1
    env.service = DomainService(SQLiteAgentWorldRepository(env.repo.path), now=lambda: NOW)
    resumed = judges(env, records)
    finished = review(env, item, records)
    assert finished["item"]["status"] == "approved"
    assert [call.model_id for call in resumed] == [record.header.entity_id for record in records[1:]]
    count = stored_count(env, "aw_events")
    assert review(env, item, records)["replayed"] is True
    assert stored_count(env, "aw_events") == count and len(resumed) == 2


@pytest.mark.parametrize("verdicts,expected", [(("reject", "reject", "approve"), "rejected"), (("approve", "reject", "abstain"), "review")])
def test_court_rejection_and_no_quorum_never_execute(env, verdicts, expected):
    item, records = decision(env), models(env)
    judges(env, records, verdicts=verdicts)
    result = review(env, item, records)["item"]
    assert result["status"] == expected
    assert result["court_cases"][0]["status"] == ("decided" if expected == "rejected" else "blocked")
    assert env.state.calls == []


def test_critical_court_fails_closed_without_failure_domain_diversity(env):
    item, records = decision(env, risk="critical"), models(env)
    judges(env, records, domains=("same-provider/model",) * 3)
    result = review(env, item, records)["item"]
    assert result["status"] == "review" and result["approval"] is None
    assert result["court_cases"][0]["reason_code"] == "court_diversity_required"


def test_court_rejects_browser_votes_missing_providers_and_foreign_models(env):
    item = decision(env)
    assert "review" not in item["actions"]
    with pytest.raises(ContractError, match="court_judge_provider_required"):
        act(env, item, "decisions", "review", {"model_ids": [str(uuid4()) for _ in range(3)]})
    env.service.judge_runner = lambda _: pytest.fail("unowned model must not run")
    with pytest.raises(ContractError, match="invalid_domain_fields"):
        act(env, item, "decisions", "review", {"votes": ["approve"] * 3})
    with pytest.raises(ContractError, match="domain_record_not_found"):
        act(env, item, "decisions", "review", {"model_ids": [str(uuid4()) for _ in range(3)]})


def test_judge_results_require_trusted_matching_model_provenance(env):
    item, records = decision(env), models(env)
    env.service.judge_runner = lambda request: JudgeResult(verdict="approve", confidence=100, rationale="Claim",
                                                          provider_key="invented", model_key="invented", model_version="unknown", failure_domain="invented")
    with pytest.raises(ContractError, match="judge_model_provenance_mismatch"):
        review(env, item, records)
    assert env.repo.list(context=env.ctx, kind=EntityKind.COURT_VOTE, page=PageRequest()).items == ()


def test_court_rechecks_revocation_after_model_call_before_recording_vote(env):
    item, records = decision(env), models(env)
    judges(env, records)
    original = env.service.judge_runner

    def revoke(request):
        result = original(request)
        env.state.allowed = False
        return result

    env.service.judge_runner = revoke
    with pytest.raises(ContractError, match="test_access_revoked"):
        review(env, item, records)
    assert env.repo.list(context=env.ctx, kind=EntityKind.COURT_VOTE, page=PageRequest()).items == ()


def test_court_vote_terminal_and_packet_payload_immutable_after_approval(env):
    item, records = decision(env), models(env)
    judges(env, records)
    approved = review(env, item, records)["item"]
    before = stored_count(env, "aw_events")
    with pytest.raises(ContractError, match="domain_action_not_supported"):
        act(env, approved, "decisions", "execute", {})
    votes = env.repo.list(context=env.ctx, kind=EntityKind.COURT_VOTE, page=PageRequest()).items
    with pytest.raises(ContractError, match="finalized_record_immutable"):
        changed = env.service._change(votes[0], verdict="reject")
        env.service._save(env.ctx, env.admit, changed, "court_vote.changed", "immutable-vote-key", "0" * 64)
    assert stored_count(env, "aw_events") == before


def test_get_collections_never_dispatch_publish_rate_or_change_domain_records(env):
    item = create(env)["item"]
    snapshot = {table: stored_count(env, table) for table in ("aw_records", "aw_revisions", "aw_events", "aw_mutations")}
    for domain in ("personas", "memory", "projects", "routines", "calendar", "decisions", "court"):
        env.service.list(context=env.ctx, admit=env.admit, domain=domain)
    get(env, "personas", item["id"])
    assert snapshot == {table: stored_count(env, table) for table in snapshot}
    assert env.state.calls == []


def test_domain_event_envelopes_are_reference_only_and_not_raw_profile_memory_or_reason(env):
    item = create(env, "memory", memory_payload(), "sensitive-private-memory")["item"]
    act(env, item, "memory", "promote", {"reason": "An owner-private review explanation"})
    events = env.repo.events.list(context=env.ctx, page=PageRequest()).items
    serialized = json.dumps([event.as_dict() for event in events])
    assert "Always record the source result" not in serialized
    assert "owner-private review explanation" not in serialized
    assert "sensitive-private-memory" not in serialized
    assert all(event.data.reason_code.startswith("rq.") for event in events)


def model_service_fixture(env):
    from app.ai_control_center.model_service import ModelService
    values, calls = {}, []
    secrets = SimpleNamespace(available=lambda: True, set_secret=lambda key, value: values.__setitem__(key, value),
                              get_secret=lambda key: values[key], delete_secret=lambda key: values.pop(key, None))

    def admission(ctx, operation, estimate):
        assert ctx == env.ctx
        env.admit()

    def executor(**kwargs):
        calls.append(kwargs)
        if "isolated evidence reviewer" in kwargs["system_prompt"]:
            response = {"verdict": "reject" if len(calls) % 3 == 0 else "approve", "confidence": 70,
                        "rationale": "Isolated mocked transport checked this packet."}
        else:
            response = {"count": 4, "sum": 34, "min": -4, "max": 17, "mean": 8.5}
        return {"ok": True, "response": json.dumps(response), "actual_model": kwargs["model"].model_key,
                "elapsed_sec": 0.01, "cost_known": True, "cost_usd": 0.0, "application_cache_hit": False}

    service = ModelService(env.repo, admit=admission, executor=executor, secrets=secrets)
    p = act(env, create(env)["item"])["item"]
    ids = []
    for index in range(3):
        model = service.connect(context=env.ctx, idempotency_key=f"isolated-model-{index:04}",
                                payload={"label": f"Fixture {index}", "provider": "openai", "model": f"fixture-model-{index}",
                                         "api_key": "fixture-placeholder-only", "persona_id": p["id"]})
        ids.append(model["id"])
    return service, ids, calls


def test_real_model_service_adapter_contract_integrates_court_receipts_without_network(env):
    model_service, ids, calls = model_service_fixture(env)
    env.service.judge_runner = model_service.judge
    item = decision(env)
    result = act(env, item, "decisions", "review", {"model_ids": ids}, key="actual-adapter-review-001")["item"]
    assert result["status"] == "approved" and len(calls) == 3
    assert len({call["request_id"] for call in calls}) == 3
    votes = result["court_cases"][0]["votes"]
    assert all(vote["contribution_id"] for vote in votes)
    for vote in votes:
        contribution = env.repo.get(context=env.ctx, kind=EntityKind.CONTRIBUTION, entity_id=UUID(vote["contribution_id"]))
        assert contribution.status == "accepted"
    items = env.service.list(context=env.ctx, admit=env.admit, domain="decisions")["items"]
    assert {item["decision_type"] for item in items} == {"advisory_proposal", "explicit_task_authorization"}
    assert all(item["actions"] == [] for item in items if item["decision_type"] == "explicit_task_authorization")
    assert env.service.consensus_candidates(context=env.ctx, admit=env.admit) == []  # Court cannot vote into its own proposal
    assert act(env, item, "decisions", "review", {"model_ids": ids}, key="actual-adapter-review-001")["replayed"]
    assert len(calls) == 3


def test_court_evidence_picker_serializes_only_verified_stored_json_media_type(env, monkeypatch):
    model_service, ids, _ = model_service_fixture(env)
    task = model_service.start_task(context=env.ctx, model_id=ids[0],
        payload={"rubric_key": "json_arithmetic", "input_text": "[17,-4,12,9]"},
        idempotency_key="court-evidence-picker-json")
    result = model_service.execute(context=env.ctx, task_id=task["id"])
    assert result["status"] == "succeeded"
    candidates = env.service.evidence_candidates(context=env.ctx, admit=env.admit)["items"]
    assert candidates and all(row["media_type"] == "application/json" for row in candidates)
    assert env.service.evidence_candidates(context=context(user=2), admit=env.admit)["items"] == []

    original = env.repo.get_artifact
    def non_json(*args, **kwargs):
        found = original(*args, **kwargs)
        return (found[0], "text/plain") if found else None
    monkeypatch.setattr(env.repo, "get_artifact", non_json)
    assert env.service.evidence_candidates(context=env.ctx, admit=env.admit)["items"] == []
    monkeypatch.setattr(env.repo, "get_artifact", lambda *args, **kwargs: None)
    assert env.service.evidence_candidates(context=env.ctx, admit=env.admit)["items"] == []


def test_consensus_uses_independent_same_input_contributions_then_separate_court(env):
    model_service, ids, calls = model_service_fixture(env)
    contribution_ids = []
    for index, model_id in enumerate(ids[:2]):
        task = model_service.start_task(context=env.ctx, model_id=model_id,
                                       payload={"rubric_key": "json_arithmetic", "input_text": "[17,-4,12,9]"},
                                       idempotency_key=f"independent-consensus-{index:04}")
        result = model_service.execute(context=env.ctx, task_id=task["id"])
        assert result["status"] == "succeeded"
        contribution_ids.append(result["contribution_id"])
    proposal = env.service.propose_consensus(context=env.ctx, admit=env.admit, title="Consensus proposal",
                                             proposal="Two independent paths agree on this bounded result.",
                                             contribution_ids=contribution_ids, risk="low", idempotency_key="consensus-proposal-001")["item"]
    record = env.repo.get(context=env.ctx, kind=EntityKind.DECISION, entity_id=UUID(proposal["id"]))
    assert len(record.contributions) == 2 and proposal["status"] == "proposed"
    assert proposal["court_cases"] == [] and len(calls) == 2
    with pytest.raises(ContractError, match="consensus_independent_same_task_required"):
        env.service.propose_consensus(context=env.ctx, admit=env.admit, title="Duplicated path", proposal="Not independent",
                                      contribution_ids=[contribution_ids[0]] * 2, risk="low", idempotency_key="bad-consensus-proposal")
    candidates = env.service.evidence_candidates(context=env.ctx, admit=env.admit)["items"]
    assert candidates and all(item["source_kind"] in {"outcome", "contribution"} for item in candidates)
    assert all(item["media_type"] == "application/json" for item in candidates)
    assert env.service.evidence_candidates(context=context(user=2), admit=env.admit)["items"] == []
    choices = env.service.consensus_candidates(context=env.ctx, admit=env.admit)
    assert {row["id"] for row in choices} == set(contribution_ids)
    assert len({row["input_group"] for row in choices}) == 1
    assert env.service.consensus_candidates(context=context(user=2), admit=env.admit) == []
    env.state.allowed = False
    with pytest.raises(ContractError, match="test_access_revoked"):
        env.service.consensus_candidates(context=env.ctx, admit=env.admit)


@pytest.mark.parametrize("change", ["review", "failed", "synthetic", "different_input"])
def test_consensus_picker_excludes_unverified_and_unmatched_paths(env, monkeypatch, change):
    model_service, ids, calls = model_service_fixture(env)
    for index, model_id in enumerate(ids[:2]):
        task = model_service.start_task(context=env.ctx, model_id=model_id,
            payload={"rubric_key": "json_arithmetic"}, idempotency_key=f"picker-filter-{index}")
        result = model_service.execute(context=env.ctx, task_id=task["id"])
        assert result["status"] == "succeeded"
    record = env.repo.get(context=env.ctx, kind=EntityKind.TASK, entity_id=UUID(task["id"]))
    if change in {"review", "failed"}:
        changed = env.service._change(record, status=change)
    else:
        checkpoint = env.service._json(env.ctx, record.checkpoint)
        if change == "synthetic":
            checkpoint["synthetic"] = True
        else:
            checkpoint["spec"]["input"] = [1, 2, 3]
        changed = env.service._change(record, checkpoint=env.service._put(env.ctx, env.admit, checkpoint))
    # Fault-inject the read boundary; never force an invalid terminal transition.
    original_get = env.repo.get
    monkeypatch.setattr(env.repo, "get", lambda **kwargs:
        changed if kwargs["kind"] == EntityKind.TASK and kwargs["entity_id"] == record.header.entity_id else original_get(**kwargs))
    assert env.service.consensus_candidates(context=env.ctx, admit=env.admit) == []
    assert len(calls) == 2


def test_verified_lesson_retrieval_stops_when_source_outcome_is_disputed(env):
    model_service, ids, _ = model_service_fixture(env)
    task = model_service.start_task(context=env.ctx, model_id=ids[0], payload={"rubric_key": "json_arithmetic"},
                                   idempotency_key="lesson-source-task-001")
    model_service.execute(context=env.ctx, task_id=task["id"])
    outcome = env.repo.list(context=env.ctx, kind=EntityKind.OUTCOME, page=PageRequest()).items[0]
    item = create(env, "memory", memory_payload(memory_class="verified_lesson", verified_outcome_id=str(outcome.header.entity_id)),
                  "verified-lesson-001")["item"]
    active = act(env, item, "memory", "promote", {"reason": "I accept this verified lesson"})["item"]
    assert active["memory_class"] == "verified_lesson"
    assert len(env.service.retrieve_memory(context=env.ctx, admit=env.admit, purpose="report_review")["items"]) == 1
    disputed = env.service._change(outcome, status="disputed")
    env.service._save(env.ctx, env.admit, disputed, "fixture.outcome.disputed", "source-dispute-001", "0" * 64)
    assert env.service.retrieve_memory(context=env.ctx, admit=env.admit, purpose="report_review")["items"] == []
    detail = get(env, "memory", item["id"])
    assert detail["status"] == "review" and "content" not in detail


def test_task_memory_requires_exact_task_context_and_working_memory_has_short_ttl(env):
    model_service, ids, _ = model_service_fixture(env)
    task = model_service.start_task(context=env.ctx, model_id=ids[0], payload={"rubric_key": "json_arithmetic"},
                                   idempotency_key="task-memory-source-001")
    item = create(env, "memory", memory_payload(memory_class="task", task_id=task["id"]), "task-memory-001")["item"]
    act(env, item, "memory", "promote", {"reason": "Task-specific note"})
    assert env.service.retrieve_memory(context=env.ctx, admit=env.admit, purpose="report_review")["items"] == []
    assert len(env.service.retrieve_memory(context=env.ctx, admit=env.admit, purpose="report_review", task_id=task["id"])["items"]) == 1
    with pytest.raises(ContractError, match="working_memory_ttl_limit"):
        create(env, "memory", memory_payload(memory_class="working", retention_days=2), "working-context-too-long")
    working = create(env, "memory", memory_payload(memory_class="working", retention_days=1), "working-context-001")["item"]
    assert _utc_test(working["retention_until"]) - _utc_test(working["created_at"]) == timedelta(days=1)


def _utc_test(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def publish(env):
    private = create(env, "memory", memory_payload(), "private-for-publication")["item"]
    active = act(env, private, "memory", "promote", {"reason": "Verified my note"})["item"]
    shared = act(env, active, "memory", "publish_to_workspace", {"reason": "Share this selected note with my workspace"},
                  key="explicit-publication-001")["item"]
    return active, shared


def test_explicit_shared_memory_grant_reads_only_published_content_without_owner_impersonation(env):
    original, published = publish(env)
    other = context(user=2)
    visible = get(env, "memory", published["id"], other)
    assert visible["visibility"] == "workspace" and visible["content"] == memory_payload()["content"]
    assert visible["actions"] == [] and visible["provenance"][0]["type"] == "workspace_memory_publication"
    own_private = env.repo.get(context=env.ctx, kind=EntityKind.MEMORY, entity_id=UUID(original["id"]))
    assert original["content_artifact_url"] == "/api/ai-control-center/artifacts/" + str(own_private.content.artifact_id)
    assert visible["content_artifact_url"] == "/api/ai-control-center/memory-artifacts/" + published["id"] + "/" + str(own_private.content.artifact_id)
    assert visible["verification_artifact_url"].startswith("/api/ai-control-center/memory-artifacts/" + published["id"] + "/")
    assert env.repo.get_artifact(context=other, reference=own_private.content) is None
    assert env.repo.get_artifact_by_id(context=other, artifact_id=own_private.content.artifact_id) is None
    assert env.repo.get_revision(context=other, kind=EntityKind.MEMORY, entity_id=UUID(published["id"]), revision=1) is None
    with pytest.raises(ContractError, match="domain_record_not_found"):
        get(env, "memory", original["id"], other)
    rows = env.service.list(context=other, admit=env.admit, domain="memory")["items"]
    assert [row["id"] for row in rows] == [published["id"]]
    assert len(env.service.retrieve_memory(context=other, admit=env.admit, purpose="report_review")["items"]) == 1
    private_proof = own_private.provenance[0]
    assert env.repo.read_memory_artifact(context=other, memory_id=UUID(published["id"]), artifact_id=private_proof.artifact_id, now=NOW) is None


def test_shared_memory_never_crosses_workspace_and_reader_cannot_modify_or_revoke(env):
    _, shared = publish(env)
    with pytest.raises(ContractError, match="domain_record_not_found"):
        get(env, "memory", shared["id"], context(user=2, workspace="ws_foreign01"))
    for action, payload in [("revoke", {"reason": "I do not own it"}), ("publish_to_workspace", {"reason": "Reshare"})]:
        with pytest.raises(ContractError, match="domain_record_not_found"):
            act(env, shared, "memory", action, payload, ctx=context(user=2))


@pytest.mark.parametrize("revocation", ["shared", "source", "ttl"])
def test_shared_memory_grant_disappears_after_publisher_revocation_source_revocation_or_ttl(env, revocation):
    original, shared = publish(env)
    if revocation == "ttl":
        env.state.now += timedelta(days=3)
    else:
        act(env, shared if revocation == "shared" else original, "memory", "revoke", {"reason": "Withdraw sharing"})
    before = stored_count(env, "aw_events")
    with pytest.raises(ContractError, match="domain_record_not_found"):
        get(env, "memory", shared["id"], context(user=2))
    assert env.service.list(context=context(user=2), admit=env.admit, domain="memory")["items"] == []
    assert env.service.retrieve_memory(context=context(user=2), admit=env.admit, purpose="report_review")["items"] == []
    assert stored_count(env, "aw_events") == before


def test_shared_memory_publication_replay_no_duplicate_and_new_key_cannot_republish_same_version(env):
    original, shared = publish(env)
    count = stored_count(env, "aw_events")
    replay = act(env, original, "memory", "publish_to_workspace", {"reason": "Share this selected note with my workspace"},
                  key="explicit-publication-001")
    assert replay["replayed"] and replay["item"]["id"] == shared["id"]
    assert stored_count(env, "aw_events") == count
    with pytest.raises(ContractError, match="memory_publication_already_exists"):
        act(env, original, "memory", "publish_to_workspace", {"reason": "Duplicate"}, key="different-key-same-note")


def test_shared_memory_integrity_failure_is_not_masked_as_success(env):
    _, shared = publish(env)
    record = env.repo.get(context=env.ctx, kind=EntityKind.MEMORY, entity_id=UUID(shared["id"]))
    with sqlite3.connect(env.repo.path) as db:
        db.execute("UPDATE aw_artifacts SET content=? WHERE artifact_id=?", (b'{"tampered":true}', str(record.content.artifact_id)))
    with pytest.raises(ContractError, match="artifact_integrity_mismatch"):
        get(env, "memory", shared["id"], context(user=2))


def test_hiring_into_a_team_place_needs_only_a_name_and_brings_the_duties(env):
    from app.ai_control_center.team_roles import TEAM_ROLES
    hired = create(env, payload={"name": "Сева", "team_role": "researcher"}, key="hire-researcher-001")["item"]
    assert hired["team_role"] == "researcher" and hired["description"] == TEAM_ROLES["researcher"]["duty"]
    own_words = create(env, payload={"name": "Дина", "team_role": "code_reviewer", "description": "Своё описание"}, key="hire-reviewer-001")["item"]
    assert own_words["description"] == "Своё описание"
    renamed = act(env, act(env, hired)["item"], action="update", payload={"name": "Сева Research"})["item"]
    assert renamed["team_role"] == "researcher"
    with pytest.raises(ContractError, match="invalid_team_role"):
        create(env, payload={"name": "Кто-то", "team_role": "trader"}, key="hire-invalid-001")
    plain = create(env, payload={"name": "Без места"}, key="hire-plain-001")["item"]
    assert "team_role" not in plain


def test_the_deputy_is_the_one_the_owner_speaks_to_and_there_is_only_one(env):
    """The owner manages the project; their right hand is the Заместитель."""
    from app.ai_control_center.team_roles import LEAD, TEAM_ROLES
    assert LEAD == "deputy"
    right_hand = create(env, payload={"name": "Витёк", "team_role": "deputy"}, key="hire-deputy-001")["item"]
    assert right_hand["team_role"] == "deputy" and right_hand["main_assistant"] is True
    # The duties are the owner's chain, written once in the place itself.
    assert "напрямую" in TEAM_ROLES["deputy"]["duty"] and "судьям" in TEAM_ROLES["deputy"]["duty"]
    # A place below the lead never becomes the assistant the owner addresses.
    other = create(env, payload={"name": "Лера", "team_role": "secretary"}, key="hire-secretary-001")["item"]
    assert other.get("main_assistant", False) is False
    # A second right hand is refused, so no message is ever ambiguous.
    act(env, right_hand)
    with pytest.raises(ContractError, match="persona_main_exists"):
        create(env, payload={"name": "Второй", "team_role": "deputy"}, key="hire-deputy-002")
