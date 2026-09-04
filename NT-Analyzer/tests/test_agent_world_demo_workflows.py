from __future__ import annotations

import ast
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from app.ai_control_center import contracts as c
from app.ai_control_center.demo_benchmark import PERSONAS, execute, fixture, json_bytes
from app.ai_control_center.demo_evaluation import evaluate
from app.ai_control_center.demo_workflows import DemoAdmission, DemoWorkflowService
from app.ai_control_center.repositories import PageRequest
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError, EntityKind


USER = UUID("877f09a5-1967-50cc-9175-3b6e533991b3")
SCOPE = c.TenantScope(environment=c.Environment.DEVELOPMENT, workspace_id="ws_demo_test01")
CONTEXT = c.RequestContext(scope=SCOPE, user_uuid=USER,
                           actor=c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=USER))


def admission(context=CONTEXT, **changes):
    fields = {"scope": context.scope, "user_uuid": context.user_uuid,
              "budget": c.ExternalRef(authority=c.ExternalAuthority.BUDGET,
                                      key="ai_budgets.zero_cost.test", scope=context.scope),
              "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
              "synthetic": True, "enabled": True, "revalidate": lambda: None}
    return DemoAdmission(**{**fields, **changes})


@pytest.fixture
def service(tmp_path):
    return DemoWorkflowService(SQLiteAgentWorldRepository(tmp_path / "demo.sqlite3"))


def run(service, key="demo-test-run-01", round_index=0, context=CONTEXT, granted=None):
    return service.run(context=context, admission=granted or admission(context),
                       idempotency_key=key, round_index=round_index)


def rows(service, kind, context=CONTEXT):
    return service.repository.list(context=context, kind=kind, page=PageRequest(limit=100)).items


def events(service, context=CONTEXT):
    result, cursor = [], None
    while True:
        found = service.repository.events.list(context=context, page=PageRequest(limit=100, cursor=cursor))
        result.extend(found.items)
        cursor = found.next_cursor
        if not cursor:
            return result


@pytest.mark.parametrize("round_index", range(3))
@pytest.mark.parametrize("persona_key", [row["key"] for row in PERSONAS])
def test_actual_fixture_computation_passes_independent_checker(persona_key, round_index):
    source = fixture(round_index)
    upstream, _ = execute("tolik", source)
    result, svg = execute(persona_key, source, upstream=upstream)
    measured = evaluate(persona_key, source, result, svg=svg, upstream=upstream)
    assert measured["passed"] is True
    assert measured["score_pct"] == 100
    assert measured["input_sha256"] == hashlib.sha256(json_bytes(source)).hexdigest()
    assert measured["output_sha256"] == hashlib.sha256(json_bytes(result)).hexdigest()
    assert measured["model_quality_assessed"] is False
    assert measured["routing_effect"] == "none"
    assert len(measured["rubric"]) == 4


@pytest.mark.parametrize("persona_key,field", [("marina", "net_cents"), ("tolik", "delta_ticks"),
                                               ("nikita", "review_count"), ("ivan", "bar_count")])
def test_executor_cannot_self_certify_wrong_results(persona_key, field):
    source = fixture(0)
    upstream, _ = execute("tolik", source)
    result, svg = execute(persona_key, source, upstream=upstream)
    result[field] += 1
    measured = evaluate(persona_key, source, result, svg=svg, upstream=upstream)
    assert measured["passed"] is False
    assert measured["score_pct"] < 100
    assert not measured["rubric"][-1]["passed"]


def test_chart_geometry_and_external_markup_are_checked_not_just_a_supplied_hash():
    source = fixture(0)
    upstream, _ = execute("tolik", source)
    result, svg = execute("ivan", source, upstream=upstream)
    for poisoned in (svg.replace(b'points="100,', b'points="900,'),
                     svg.replace(b'width="24"', b'width="98"'),
                     svg.replace(b'viewBox="0 0 960 420"', b'viewBox="0 0 42 96"'),
                     svg.replace(b"</svg>", b'<script>alert(1)</script></svg>'),
                     svg.replace(b"</svg>", b'<text href="https://example.invalid">external</text></svg>')):
        copy_result = {**result, "chart_sha256": hashlib.sha256(poisoned).hexdigest()}
        assert not evaluate("ivan", source, copy_result, svg=poisoned, upstream=upstream)["passed"]


def test_chart_requires_matching_upstream_input_evidence():
    source = fixture(0)
    wrong, _ = execute("tolik", fixture(1))
    with pytest.raises(ContractError, match="verified_upstream_required"):
        execute("ivan", source, upstream=wrong)


def test_run_persists_graph_evidence_and_independent_actor_provenance(service):
    result = run(service)
    assert result["run"]["replayed"] is False
    assert len(result["run"]["task_ids"]) == 4
    assert result["overview"]["summary"]["completed"] == 4
    assert result["overview"]["summary"]["evaluations"] == 4
    assert result["overview"]["summary"]["paid_calls"] == 0
    assert {item.status for item in rows(service, EntityKind.TASK)} == {"succeeded"}
    assert {item.status for item in rows(service, EntityKind.CONTRIBUTION)} == {"accepted"}
    assert {item.status for item in rows(service, EntityKind.OUTCOME)} == {"verified"}
    assert len(rows(service, EntityKind.PERSONA)) == 4
    assert len(rows(service, EntityKind.AGENT_ROLE)) == 4
    assert not rows(service, EntityKind.MODEL)
    assert not rows(service, EntityKind.PROVIDER_ACCOUNT)
    assert not rows(service, EntityKind.EXECUTION)
    assert not rows(service, EntityKind.DECISION)
    contribution = rows(service, EntityKind.CONTRIBUTION)[0]
    outcome = rows(service, EntityKind.OUTCOME)[0]
    assert contribution.header.created_by.kind == c.ActorKind.SERVICE
    assert outcome.header.created_by.kind == c.ActorKind.SERVICE
    assert outcome.header.created_by.actor_id != contribution.header.created_by.actor_id
    assert contribution.header.created_by.on_behalf_of == USER
    accepted = [event for event in events(service) if event.subject.entity_id == contribution.header.entity_id][-1]
    assert accepted.actor.actor_id == outcome.header.created_by.actor_id
    chart_task = next(item for item in service.work(context=CONTEXT) if item["lead"]["key"] == "ivan")
    assert len(chart_task["dependencies"]) == 1
    detail = service.task_detail(context=CONTEXT, entity_id=UUID(chart_task["id"]))
    assert detail["result"]["bar_count"] == 8
    chart = next(item for item in detail["artifacts"] if item["mime_type"] == "image/svg+xml")
    ref, content, mime = service.artifact(context=CONTEXT, entity_id=UUID(chart["id"]))
    assert hashlib.sha256(content).hexdigest() == chart["sha256"] == ref.sha256
    assert mime == "image/svg+xml"
    assert b"SYNTHETIC BENCHMARK" in content
    assert detail["activity"]
    assert detail["evaluations"][0]["passed"]


def test_same_key_replays_original_graph_without_new_records_or_events(service):
    first = run(service)
    before = events(service)
    again = run(service)
    assert again["run"]["replayed"] is True
    assert again["run"]["id"] == first["run"]["id"]
    assert again["run"]["task_ids"] == first["run"]["task_ids"]
    assert events(service) == before
    assert len(service.work(context=CONTEXT)) == 4
    with pytest.raises(ContractError, match="idempotency_conflict"):
        run(service, round_index=1)


def test_three_distinct_benchmark_samples_are_required_and_replays_do_not_inflate_rating(service):
    assert all(agent["evaluation"]["score_pct"] is None for agent in service.agents(context=CONTEXT))
    for index in range(3):
        run(service, key=f"demo-test-run-0{index + 1}", round_index=index)
        agents = service.agents(context=CONTEXT)
        assert all(agent["evaluation"]["sample_size"] == index + 1 for agent in agents)
        assert all(agent["evaluation"]["observed_score_pct"] == 100 for agent in agents)
        if index < 2:
            assert all(agent["evaluation"]["score_pct"] is None for agent in agents)
            assert all(agent["evaluation"]["confidence"] == "insufficient" for agent in agents)
        else:
            assert all(agent["evaluation"]["score_pct"] == 100 for agent in agents)
            assert all(agent["evaluation"]["confidence"] == "low" for agent in agents)
    run(service, key="demo-repeat-same-fixture", round_index=0)
    assert all(agent["evaluation"]["sample_size"] == 3 for agent in service.agents(context=CONTEXT))
    assert len(service.work(context=CONTEXT)) == 16


def test_automatic_three_round_selection_is_stored_for_idempotent_replay(service):
    runs = [run(service, key=f"demo-auto-round-{index}", round_index=None) for index in range(3)]
    assert all(agent["evaluation"]["sample_size"] == 3 for agent in service.agents(context=CONTEXT))
    again = run(service, key="demo-auto-round-0", round_index=None)
    assert again["run"]["id"] == runs[0]["run"]["id"]
    assert again["run"]["replayed"]


@pytest.mark.parametrize("round_index", [0, None])
def test_concurrent_same_key_retries_commit_one_graph(service, round_index):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: run(service, round_index=round_index), range(2)))
    assert results[0]["run"]["id"] == results[1]["run"]["id"]
    assert len(rows(service, EntityKind.INTENT)) == 1
    assert len(rows(service, EntityKind.TASK)) == 4
    assert {item.status for item in rows(service, EntityKind.TASK)} == {"succeeded"}
    event_ids = [event.event_id for event in events(service)]
    assert len(set(event_ids)) == len(event_ids)


@pytest.mark.parametrize("changes,error", [
    ({"synthetic": False}, "demo_not_enabled"), ({"synthetic": "true"}, "demo_not_enabled"),
    ({"enabled": False}, "demo_not_enabled"), ({"enabled": 1}, "demo_not_enabled"),
    ({"user_uuid": UUID(int=999)}, "demo_owner_mismatch"),
    ({"expires_at": datetime(2020, 1, 1, tzinfo=timezone.utc)}, "demo_admission_expired"),
    ({"revalidate": None}, "demo_revalidation_required"),
])
def test_admission_fails_closed_before_any_write(service, changes, error):
    with pytest.raises(ContractError, match=error):
        run(service, granted=admission(**changes))
    assert not rows(service, EntityKind.INTENT)
    assert not events(service)


@pytest.mark.parametrize("environment", [c.Environment.CANARY, c.Environment.PRODUCTION])
def test_no_canary_or_production_execution_even_with_true_booleans(service, environment):
    scope = replace(SCOPE, environment=environment)
    context = replace(CONTEXT, scope=scope)
    with pytest.raises(ContractError, match="demo_development_only"):
        run(service, context=context)


def test_external_admission_recheck_can_stop_and_resume_from_durable_checkpoint(service):
    calls = []
    def recheck():
        calls.append(1)
        if any(item.status == "running" for item in rows(service, EntityKind.TASK)):
            raise PermissionError("access expired")
    with pytest.raises(PermissionError, match="access expired"):
        run(service, granted=admission(revalidate=recheck))
    assert calls
    assert any(item.status == "running" for item in rows(service, EntityKind.TASK))
    original_ids = {item.header.entity_id for item in rows(service, EntityKind.TASK)}
    result = run(service)
    assert result["overview"]["summary"]["completed"] == 4
    assert original_ids <= {item.header.entity_id for item in rows(service, EntityKind.TASK)}
    assert len(rows(service, EntityKind.INTENT)) == 1


def test_expired_intent_cannot_be_resumed_by_extending_only_admission(service, monkeypatch):
    from app.ai_control_center import demo_workflows
    def recheck():
        if rows(service, EntityKind.TASK):
            raise PermissionError("pause")
    with pytest.raises(PermissionError):
        run(service, granted=admission(revalidate=recheck))
    later = datetime.now(timezone.utc) + timedelta(minutes=6)
    monkeypatch.setattr(demo_workflows, "_now", lambda: later)
    with pytest.raises(ContractError, match="demo_deadline_expired"):
        run(service, granted=admission(expires_at=later + timedelta(minutes=5)))


def test_context_and_artifacts_are_private_across_user_and_workspace(service):
    result = run(service)
    task_id = UUID(result["run"]["task_ids"][-1])
    artifact_id = UUID(service.task_detail(context=CONTEXT, entity_id=task_id)["artifacts"][0]["id"])
    foreign_user = UUID(int=99)
    by_user = replace(CONTEXT, user_uuid=foreign_user,
                      actor=c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=foreign_user))
    by_workspace = replace(CONTEXT, scope=replace(SCOPE, workspace_id="ws_foreign01"))
    for foreign in (by_user, by_workspace):
        assert not service.work(context=foreign)
        assert service.task_detail(context=foreign, entity_id=task_id) is None
        assert service.artifact(context=foreign, entity_id=artifact_id) is None
        assert all(agent["evaluation"]["sample_size"] == 0 for agent in service.agents(context=foreign))


def test_actual_workflow_makes_no_network_subprocess_or_provider_calls(service, monkeypatch):
    import socket
    import subprocess
    import urllib.request
    def forbidden(*args, **kwargs):
        raise AssertionError("external effect attempted")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    result = run(service)
    assert result["overview"]["summary"]["completed"] == 4


def test_tampered_executor_does_not_produce_verified_outcome(service, monkeypatch):
    from app.ai_control_center import demo_workflows
    original = demo_workflows.execute
    def tamper(persona_key, source, **kwargs):
        result, svg = original(persona_key, source, **kwargs)
        if persona_key == "marina":
            result["net_cents"] += 1
        return result, svg
    monkeypatch.setattr(demo_workflows, "execute", tamper)
    result = run(service)
    assert result["overview"]["summary"]["failed"] == 1
    assert result["overview"]["summary"]["completed"] == 3
    assert {item.status for item in rows(service, EntityKind.INTENT)} == {"failed"}
    assert sorted(item.status for item in rows(service, EntityKind.OUTCOME)) == ["rejected", "verified", "verified", "verified"]


def test_failed_upstream_prevents_chart_execution(service, monkeypatch):
    from app.ai_control_center import demo_workflows
    original = demo_workflows.execute
    called = []
    def tamper(persona_key, source, **kwargs):
        called.append(persona_key)
        result, svg = original(persona_key, source, **kwargs)
        if persona_key == "tolik":
            result["delta_ticks"] += 1
        return result, svg
    monkeypatch.setattr(demo_workflows, "execute", tamper)
    result = run(service)
    assert "ivan" not in called
    ivan = next(task for task in service.work(context=CONTEXT) if task["lead"]["key"] == "ivan")
    assert ivan["status"] == "blocked"
    assert not service.task_detail(context=CONTEXT, entity_id=UUID(ivan["id"]))["evaluations"]


def test_executor_and_verifier_do_not_import_side_effect_authorities():
    folder = Path(__file__).resolve().parents[1] / "app" / "ai_control_center"
    banned = {"socket", "requests", "urllib", "subprocess", "ai_lab", "ai_budgets", "jobqueue",
              "local_worker", "market_data", "connector_protocol", "sf_chat", "community"}
    for name in ("demo_benchmark.py", "demo_evaluation.py", "demo_workflows.py"):
        tree = ast.parse((folder / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [item.name for item in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(set(module.split(".")) & banned for module in names)


def test_rehearsal_persona_labels_and_roles_reuse_existing_roster():
    from app.ai_lab.domain_agents import PERSONAS as legacy
    for persona in PERSONAS:
        assert persona["display_name"] == legacy[persona["key"]]["name"]
        assert persona["role_key"] == legacy[persona["key"]]["role"]
