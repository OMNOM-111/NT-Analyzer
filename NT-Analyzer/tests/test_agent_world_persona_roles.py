"""Explicit roles, rename stability and one workflow per original source."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.ai_control_center import application_chat, domain_gateway
from app.ai_control_center.model_service import ModelService
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_domain_service import env, create, act, get, context
from tests.test_agent_world_models import setup as model_setup, connected


def assigned(env, name="Any name", key="persona-create-one", role="backtest_researcher", ctx=None):
    item = create(env, payload={"name": name, "application_role": role}, key=key, ctx=ctx)["item"]
    return act(env, item, ctx=ctx)["item"]


def test_rename_older_client_preserves_role_and_explicit_empty_unassigns(env):
    item = assigned(env)
    changed = act(env, item, action="update", payload={"name": "Renamed analyst"})["item"]
    assert changed["application_role"] == "backtest_researcher"
    assert changed["title"] == "Renamed analyst"
    cleared = act(env, changed, action="update", payload={"name": "Renamed analyst", "application_role": ""})["item"]
    assert cleared["application_role"] == ""
    assert get(env, "personas", item["id"])["revision"] == cleared["revision"]


@pytest.mark.parametrize("value", [None, True, 1, [], "owner", "tolik", "trade_executor"])
def test_invalid_role_never_grants_authority(env, value):
    with pytest.raises(ContractError, match="invalid_application_role"):
        create(env, payload={"name": "Anything", "application_role": value})


def test_role_exclusivity_is_private_scoped_and_suspension_reserves_slot(env):
    one = assigned(env)
    one = act(env, one, action="suspend")["item"]
    other = create(env, payload={"name": "Other", "application_role": "backtest_researcher"}, key="other-role-draft")["item"]
    with pytest.raises(ContractError, match="application_role_already_assigned"):
        act(env, other)
    # Same role in a different user or workspace does not collide.
    assigned(env, ctx=context(user=2), key="other-user-assignment")
    assigned(env, ctx=context(workspace="ws_separate"), key="other-workspace-assignment")
    act(env, one, action="archive")
    assert act(env, other)["item"]["status"] == "active"


def test_concurrent_activation_has_exactly_one_winner(env):
    items = [create(env, payload={"name": str(i), "application_role": "chart_researcher"},
                    key=f"concurrent-draft-{i}")["item"] for i in range(2)]
    def activate(item):
        try:
            return act(env, item)["item"]["status"]
        except ContractError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(activate, items))
    assert sorted(results) == ["active", "application_role_already_assigned"]


def test_name_is_not_assignment_and_an_assigned_persona_requires_active_model(model_setup):
    service, ctx, payload, *_ = model_setup
    person = service._get(ctx, EntityKind.PERSONA, payload["persona_id"])
    person = service._change(ctx, person, display_name="Толик")
    assert application_chat._select_model(service, ctx, "backtest") is None
    profile = {**service._json(ctx, person.profile), "application_role": "backtest_researcher"}
    person = service._change(ctx, person, profile=service._put(ctx, profile))
    with pytest.raises(ContractError, match="application_role_model_required"):
        application_chat._select_model(service, ctx, "backtest")
    model = connected(model_setup)
    assert application_chat._select_model(service, ctx, "backtest") == model["id"]
    person = service._change(ctx, person, display_name="Entirely different name")
    assert application_chat._select_model(service, ctx, "backtest") == model["id"]
    assert application_chat._select_model(service, ctx, "chart") is None
    service._change(ctx, person, status="suspended")
    with pytest.raises(ContractError, match="application_persona_inactive"):
        application_chat._select_model(service, ctx, "backtest")


def workflow():
    source = {"id": "original-task", "source_job_id": "original-job", "conversation_id": "original-chat", "status": "succeeded"}
    parent = {"id": "model-task", "conversation_id": "original-chat", "status": "succeeded",
              "application_dispatch": {"kind": "backtest", "source_task_id": "original-task", "source_id": "original-job"}}
    return source, {"id": parent["id"], "task": parent}


def test_exact_workflow_is_counted_once_with_original_source_retained():
    source, model = workflow()
    originals = deepcopy((source, model))
    tasks, folded = domain_gateway._application_workflows([source], [model])
    assert len(tasks) == 1 and tasks[0]["id"] == "model-task"
    assert tasks[0]["source_execution"] == source and folded == {"original-task"}
    assert (source, model) == originals  # read projection never rewrites history


@pytest.mark.parametrize("changes", [{"id": "other-task"}, {"source_job_id": "other-job"},
                                     {"conversation_id": "other-chat"}, {"conversation_id": None}])
def test_similar_names_or_foreign_trace_never_hide_another_task(changes):
    source, model = workflow()
    source.update(changes, title="same displayed title")
    model["task"]["title"] = source["title"]
    tasks, folded = domain_gateway._application_workflows([source], [model])
    assert len(tasks) == 2 and not folded


def test_ambiguous_source_links_are_not_hidden():
    source, model = workflow()
    duplicate = deepcopy(model)
    duplicate["id"] = duplicate["task"]["id"] = "other-model-task"
    tasks, folded = domain_gateway._application_workflows([source], [model, duplicate])
    assert len(tasks) == 3 and not folded


def test_legacy_projection_merges_only_explicit_role_and_keeps_rating_separate(env, monkeypatch):
    person = assigned(env, name="Not Tolik")
    # Overview also reads aggregate Tasks now. Use its actual scoped iterator
    # over this disposable repository; only model-list/evaluation DTOs are fake.
    reader = ModelService(env.repo, admit=lambda *_: env.admit())
    fake_models = SimpleNamespace(repository=env.repo, tasks=lambda **_: {"items": []},
                                  models=lambda **_: {"items": []}, _all=reader._all)
    monkeypatch.setattr(domain_gateway, "models", lambda _: fake_models)
    monkeypatch.setattr(domain_gateway, "domains", lambda *_: env.service)
    monkeypatch.setattr(domain_gateway, "system", lambda _: {"flags": {}})
    auth = {"context": env.ctx, "admit": env.admit, "chat_scope": {"capabilities": {}}}
    base = {"agents": [{"id": "tolik", "display_name": "Толик", "evaluation": {"score_pct": 99}},
                       {"id": "ivan", "display_name": "Иван"}]}
    result = domain_gateway.enrich_overview(auth, base)
    assert len(result["agents"]) == 2
    current = next(row for row in result["agents"] if row["id"] == person["id"])
    assert current["display_name"] == "Not Tolik" and current["evaluation"]["score_pct"] is None
    assert current["compatibility_history"]["source"]["evaluation"]["score_pct"] == 99
    assert base["agents"][0]["id"] == "tolik"


@pytest.mark.parametrize("old_status,expected", [("retired", 100), ("suspended", 100), ("active", None)])
def test_inactive_binding_keeps_history_without_hiding_current_rating(env, monkeypatch, old_status, expected):
    person = assigned(env)
    bindings = [{"id": "old", "model": "old-model", "status": old_status, "persona_id": person["id"]},
                {"id": "current", "model": "current-model", "status": "active", "persona_id": person["id"]}]
    stats = {"rubric_key": "json_arithmetic", "score_pct": 100, "sample_size": 3, "label": "OBSERVED"}
    reader = ModelService(env.repo, admit=lambda *_: env.admit())
    service = SimpleNamespace(repository=env.repo, tasks=lambda **_: {"items": []},
        models=lambda **_: {"items": bindings}, evaluations=lambda **_: stats, _all=reader._all)
    monkeypatch.setattr(domain_gateway, "models", lambda _: service)
    monkeypatch.setattr(domain_gateway, "domains", lambda *_: env.service)
    monkeypatch.setattr(domain_gateway, "system", lambda _: {"flags": {}})
    result = domain_gateway.enrich_overview({"context": env.ctx, "admit": env.admit, "chat_scope": {"capabilities": {}}})
    card = result["agents"][0]
    assert card["evaluation"]["score_pct"] == expected
    assert len(card["model_observations"]) == 2
    assert card["model_observations"][0]["connection_status"] == old_status
    if expected is not None:
        assert card["evaluation"]["model_id"] == "current"
