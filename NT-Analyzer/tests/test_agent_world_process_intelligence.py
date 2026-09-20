"""Process suggestions on disposable records/PNG transport fixtures, not real work."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import inspect
import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.ai_control_center import model_service as model_module
from app.ai_control_center import process_intelligence as process
from app.ai_control_center.domain_service import DomainService
from app.ai_control_center.repositories import PageRequest
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_domain_service import env, NOW, act, context, create, get, model_service_fixture, stored_count
from tests.test_agent_world_live_charts import _png


def add_chart(fixture, index, *, source_id=None):
    """A generated 1x1 PNG / mocked model receipt in a temp DB only."""
    models, ctx = fixture.models, fixture.env.ctx
    spec = {"instrument": "MNQ 09-26", "timeframe": "5m"}
    planned = models.plan_application(context=ctx, model_id=fixture.ids[0], spec=spec, kind="chart",
        idempotency_key=f"pi-chart-plan-{index:04}", conversation_id="pi-isolated-chat", message_id=f"pi-fixture-{index}")
    models.executor = lambda **_: {"ok": True, "response": json.dumps(spec), "actual_model": "isolated-fixture",
        "executor": "pi_transport_fixture", "external_call": False,
        "elapsed_sec": .01, "cost_known": True, "cost_usd": 0, "application_cache_hit": False}
    planned = models.execute(context=ctx, task_id=planned["id"])
    task = models._get(ctx, EntityKind.TASK, planned["id"])
    checkpoint = models._json(ctx, task.checkpoint)
    source_id = source_id or f"pi_chart_fixture_{index:04}"
    checkpoint["application_dispatch"] = {"source_id": source_id, "source_task_id": f"pi-source-fixture-{index}"}
    models._change(ctx, task, checkpoint=models._put(ctx, checkpoint))
    artifact = fixture.env.repo.put_artifact(context=ctx, content=_png(), media_type="image/png")
    verification = {"verified": True, "synthetic": False, "source_kind": "desktop_chart", "source_id": source_id,
        "sha256": artifact.sha256, "source_sha256": artifact.sha256,
        "request_sha256": planned["application_request"]["request_sha256"]}
    result = models.record_application_result(context=ctx, task_id=planned["id"], source_id=source_id,
                                              verification=verification, artifact_refs=(artifact,))
    fixture.tasks.append(planned["id"])
    fixture.outcomes.append(result["outcome_id"])


@pytest.fixture
def history(env, monkeypatch):
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    env.state.now = NOW - timedelta(days=3)
    monkeypatch.setattr(model_module, "_now", lambda: env.state.now)
    models, ids, calls = model_service_fixture(env)
    fixture = SimpleNamespace(env=env, models=models, ids=ids, calls=calls, tasks=[], outcomes=[])
    for index in range(3):
        env.state.now = NOW - timedelta(days=3-index)
        add_chart(fixture, index)
    env.state.now = NOW
    fixture.pi = process.ProcessIntelligence(env.service, models)
    return fixture


def analyze(fixture, **changes):
    return fixture.pi.analyze(**{"context": fixture.env.ctx, "admit": fixture.env.admit, **changes})


def candidate(fixture, domain="routines"):
    return next(row for row in analyze(fixture)["candidates"] if row["domain"] == domain)


def propose(fixture, row):
    return fixture.pi.propose(context=fixture.env.ctx, admit=fixture.env.admit,
        domain=row["domain"], candidate_id=row["id"], source_sha256=row["source_sha256"])


def test_existing_manual_routine_path_is_preserved_and_acceptance_is_separate(history):
    env = history.env
    row = env.service.suggest_routine(context=env.ctx, admit=env.admit, outcome_ids=history.outcomes[:2],
        title="Manual retained path", interval_minutes=1440, idempotency_key="manual-existing-routine")["item"]
    assert row["status"] == "proposed" and env.state.calls == []
    assert history.pi.validate_suggestion(context=env.ctx, admit=env.admit, domain="routines",
        entity_id=row["id"], expected_revision=row["revision"])["managed"] is False
    accepted = act(env, row, "routines", "accept")["item"]
    assert accepted["status"] == "accepted" and accepted["automation_enabled"] is False
    assert len(env.state.calls) == 1 and env.state.calls[0]["payload"]["manual_review_required"] is True


def test_analyze_is_read_only_structured_cadence_not_private_messages_or_model_quality(history):
    before = [stored_count(history.env, name) for name in ("aw_records", "aw_events", "aw_artifacts", "aw_mutations")]
    result = analyze(history)
    assert result["incomplete"] is False and result["automation_enabled"] is False
    assert {row["domain"] for row in result["candidates"]} == {"routines", "calendar"}
    for row in result["candidates"]:
        assert row["sample_size"] == 3 and row["interval_minutes"] == 1440
        assert row["source_kind"] == "desktop_chart" and row["quality_claim"] is False
        assert row["pending_source_reviews"] == 3
    assert before == [stored_count(history.env, name) for name in ("aw_records", "aw_events", "aw_artifacts", "aw_mutations")]
    assert history.env.state.calls == []
    public = json.dumps(result)
    for forbidden in ("fixture-placeholder-only", '"prompt"', '"response"', '"messages"', "pi-isolated-chat"):
        assert forbidden not in public
    assert "chief_agent" not in inspect.getsource(process) and "chat_store" not in inspect.getsource(process)


@pytest.mark.parametrize("domain", ["routines", "calendar"])
def test_proposal_reuses_existing_domain_and_requires_separate_manual_acceptance(history, domain):
    row = candidate(history, domain)
    result = propose(history, row)
    item = result["item"]
    assert item["status"] == "proposed" and result["domain"] == domain
    assert item["automation_enabled"] is False and history.env.state.calls == []
    proof = history.pi.validate_suggestion(context=history.env.ctx, admit=history.env.admit,
        domain=domain, entity_id=item["id"], expected_revision=item["revision"])
    assert proof["managed"] is True and proof["source_valid"] is True
    assert proof["quality_claim"] is False
    assert propose(history, row)["item"]["id"] == item["id"]
    assert propose(history, row)["replayed"] is True
    accepted = act(history.env, item, domain, "accept")["item"]
    assert accepted["status"] == "accepted" and accepted["automation_enabled"] is False
    assert len(history.env.state.calls) == 1


def test_dismiss_cooldown_and_new_sources_are_durable_across_service_restart(history):
    first = propose(history, candidate(history))["item"]
    dismissed = act(history.env, first, "routines", "dismiss")["item"]
    history.env.state.now += timedelta(hours=1)
    add_chart(history, 9)
    history.pi = process.ProcessIntelligence(DomainService(history.env.repo, now=lambda: history.env.state.now), history.models)
    result = analyze(history)
    assert not any(row["domain"] == "routines" for row in result["candidates"])
    assert any(row["reason"] == "cooldown" and row["domain"] == "routines" for row in result["suppressed"])
    history.env.state.now += timedelta(hours=24)
    next_row = candidate(history)
    following = propose(history, next_row)["item"]
    assert following["id"] != first["id"]
    assert get(history.env, "routines", first["id"])["status"] == dismissed["status"] == "dismissed"


def test_old_same_observations_do_not_reappear_after_cooldown(history):
    first = propose(history, candidate(history))["item"]
    act(history.env, first, "routines", "dismiss")
    history.env.state.now += timedelta(days=2)
    result = analyze(history)
    assert not any(row["domain"] == "routines" for row in result["candidates"])
    assert any(row["reason"] == "duplicate_observations" for row in result["suppressed"])


def test_shrinking_time_window_is_not_mistaken_for_new_work(history):
    history.pi = process.ProcessIntelligence(history.env.service, history.models,
                                             policy=process.Policy(lookback_days=3))
    add_chart(history, 9)
    row = candidate(history)
    assert row["sample_size"] == 4
    first = propose(history, row)["item"]
    act(history.env, first, "routines", "dismiss")
    history.env.state.now += timedelta(days=1)
    result = analyze(history)
    assert not any(row["domain"] == "routines" for row in result["candidates"])
    assert any(row["reason"] == "duplicate_observations" for row in result["suppressed"])


def test_pending_proposal_blocks_new_proposals_without_auto_dismissal(history):
    first = propose(history, candidate(history))["item"]
    history.env.state.now += timedelta(days=2)
    add_chart(history, 9)
    assert not any(row["domain"] == "routines" for row in analyze(history)["candidates"])
    assert get(history.env, "routines", first["id"])["status"] == "proposed"


def test_concurrent_same_pattern_creates_one_record_without_new_jobs(history):
    row = candidate(history)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: propose(history, row), range(2)))
    assert len({item["item"]["id"] for item in results}) == 1
    assert history.env.service.list(context=history.env.ctx, admit=history.env.admit, domain="routines")["items"][0]["status"] == "proposed"
    assert history.env.state.calls == []


def test_commit_between_history_and_analysis_returns_only_exact_winner(history, monkeypatch):
    row = candidate(history)
    original = history.pi.analyze
    other = process.ProcessIntelligence(history.env.service, history.models)
    def racing_analysis(**kwargs):
        other.propose(context=history.env.ctx, admit=history.env.admit, domain=row["domain"],
                      candidate_id=row["id"], source_sha256=row["source_sha256"])
        return original(**kwargs)
    monkeypatch.setattr(history.pi, "analyze", racing_analysis)
    result = propose(history, row)
    assert result["replayed"] is True
    assert len(history.env.service.list(context=history.env.ctx, admit=history.env.admit, domain="routines")["items"]) == 1


def test_stale_snapshot_is_refused_without_creating_proposal(history):
    row = candidate(history)
    history.env.state.now += timedelta(hours=1)
    add_chart(history, 9)
    with pytest.raises(ContractError, match="process_sources_changed"):
        propose(history, row)
    assert history.env.service.list(context=history.env.ctx, admit=history.env.admit, domain="routines")["items"] == []


def test_withdrawn_outcome_blocks_acceptance_and_keeps_proposal_and_error_history(history):
    item = propose(history, candidate(history))["item"]
    outcome = history.env.repo.get(context=history.env.ctx, kind=EntityKind.OUTCOME, entity_id=UUID(history.outcomes[-1]))
    disputed = history.env.service._change(outcome, status="disputed")
    history.env.service._save(history.env.ctx, history.env.admit, disputed, "fixture.outcome.disputed", "pi-disputed-001", "0"*64)
    with pytest.raises(ContractError, match="process_sources_changed"):
        history.pi.validate_suggestion(context=history.env.ctx, admit=history.env.admit, domain="routines",
                                      entity_id=item["id"], expected_revision=item["revision"])
    assert get(history.env, "routines", item["id"])["status"] == "proposed"
    assert history.env.repo.get(context=history.env.ctx, kind=EntityKind.OUTCOME, entity_id=outcome.header.entity_id).status == "disputed"
    assert history.env.state.calls == []


@pytest.mark.parametrize("decision", ["accept", "reject"])
def test_later_real_manual_review_is_preserved_and_does_not_close_suggestion(history, decision):
    from app.ai_control_center import task_review
    item = propose(history, candidate(history))["item"]
    detail = history.models.task_detail(context=history.env.ctx, task_id=history.tasks[-1])
    reviewed = task_review.submit(history.models, context=history.env.ctx, task_id=history.tasks[-1],
        payload={"decision": decision, "comment":"Explicit isolated user review",
                 "source_sha256":detail["human_review"]["source_sha256"]},
        expected_revision=detail["revision"], idempotency_key="pi-human-review-001")
    assert reviewed["human_review"]["status"] == {"accept":"accepted", "reject":"rejected"}[decision]
    args = {"context":history.env.ctx, "admit":history.env.admit, "domain":"routines",
            "entity_id":item["id"], "expected_revision":item["revision"]}
    if decision == "reject":
        with pytest.raises(ContractError, match="process_sources_changed"):
            history.pi.validate_suggestion(**args)
    else:
        assert history.pi.validate_suggestion(**args)["source_valid"] is True
    assert get(history.env, "routines", item["id"])["status"] == "proposed"
    assert history.env.state.calls == []


@pytest.mark.parametrize("foreign", [context(user=2), context(workspace="ws_pi_foreign")])
def test_foreign_scope_never_observes_or_proposes_pattern(history, foreign):
    row = candidate(history)
    assert analyze(history, context=foreign)["candidates"] == []
    with pytest.raises(ContractError, match="process_sources_changed"):
        history.pi.propose(context=foreign, admit=history.env.admit, domain=row["domain"],
                           candidate_id=row["id"], source_sha256=row["source_sha256"])


def test_revoked_admission_prevents_read_and_propose(history):
    row = candidate(history)
    history.env.state.allowed = False
    with pytest.raises(ContractError, match="test_access_revoked"):
        analyze(history)
    with pytest.raises(ContractError, match="test_access_revoked"):
        propose(history, row)


def test_explicit_false_admission_is_not_treated_as_success(history):
    with pytest.raises(ContractError, match="process_admission_denied"):
        analyze(history, admit=lambda: False)


def test_duplicate_application_receipt_is_not_an_additional_process_observation(history):
    before = candidate(history)
    history.env.state.now += timedelta(hours=1)
    add_chart(history, 9, source_id="pi_chart_fixture_0002")
    after = candidate(history)
    assert after["sample_size"] == 3 and after["observations_sha256"] == before["observations_sha256"]
    assert analyze(history)["excluded"]["duplicate_source"] == 1


def test_existing_manual_binary_provenance_does_not_break_process_analysis(history):
    env = history.env
    image = env.repo.put_artifact(context=env.ctx, content=_png(), media_type="image/png")
    create(env, "routines", {"title":"Manual image follow-up", "description":"", "interval_minutes":1440,
        "source_ids":[str(image.artifact_id)]}, "manual-image-reference-001")
    assert len(analyze(history)["candidates"]) == 2


def test_time_window_does_not_turn_old_history_into_current_statistics(history):
    history.env.state.now += timedelta(days=31)
    result = analyze(history)
    assert result["candidates"] == [] and result["incomplete"] is False


def test_structured_diagnostics_are_not_promoted_to_professional_work_pattern(history):
    models = history.models
    models.executor = lambda **_: {"ok": True, "response": '{"count":4,"sum":34,"min":-4,"max":17,"mean":8.5}',
        "elapsed_sec": .01, "cost_known": True, "cost_usd": 0, "actual_model": "diagnostic-fixture"}
    for index in range(3):
        task = models.start_task(context=history.env.ctx, model_id=history.ids[0], payload={"rubric_key":"json_arithmetic"},
                                 idempotency_key=f"pi-diagnostic-{index:04}")
        models.execute(context=history.env.ctx, task_id=task["id"])
    result = analyze(history)
    assert result["excluded"].get("bounded_capability", 0) >= 3
    assert all(row["sample_size"] == 3 for row in result["candidates"])


@pytest.mark.parametrize("change", [{"human_review":{"status":"rejected"}},
    {"execution_v2":{"status":"deviated","deviation_count":1}}, {"execution_v2":{"status":"review","deviation_count":0}}])
def test_rejected_or_deviated_task_cannot_generate_suggestion(history, monkeypatch, change):
    original = history.models.task_detail
    def detail(**kwargs):
        result = original(**kwargs)
        return {**result, **deepcopy(change)} if str(kwargs["task_id"]) == history.tasks[-1] else result
    monkeypatch.setattr(history.models, "task_detail", detail)
    assert analyze(history)["candidates"] == []


def test_incomplete_event_scan_fails_closed_instead_of_using_a_partial_denominator(history):
    history.pi = process.ProcessIntelligence(history.env.service, history.models,
                                             policy=process.Policy(max_events=1))
    result = analyze(history)
    assert result["incomplete"] is True and result["candidates"] == []
    assert result["reason"] == "event_scan_limit"


def test_policy_rejects_unsafe_bounds():
    for changes in ({"cooldown_minutes":0}, {"minimum_observations":1}, {"lookback_days":366}, {"max_events":False}):
        with pytest.raises(ContractError):
            process.Policy(**changes)
    repository = object()
    fake = SimpleNamespace(repository=repository)
    for invalid in (False, 0, {}, {"cooldown_minutes":1}):
        with pytest.raises(ContractError, match="process_policy_invalid"):
            process.ProcessIntelligence(fake, fake, policy=invalid)


def test_synthetic_source_is_excluded_even_when_current_outcome_status_is_verified(history, monkeypatch):
    original = history.env.service._json
    outcome = history.env.repo.get(context=history.env.ctx, kind=EntityKind.OUTCOME, entity_id=UUID(history.outcomes[-1]))
    def read(ctx, reference):
        result = original(ctx, reference)
        return {**result, "synthetic": True} if reference == outcome.verification else result
    monkeypatch.setattr(history.env.service, "_json", read)
    result = analyze(history)
    assert result["candidates"] == [] and result["excluded"]["synthetic_source"] == 1
