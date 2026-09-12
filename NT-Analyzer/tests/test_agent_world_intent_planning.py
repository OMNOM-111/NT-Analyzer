"""Public, explicitly clarified goals reuse the real bounded graph machinery."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace

import pytest

from app.ai_control_center import coordinator, intent_planning
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_coordinator import scenario, world, human, tick, finish


def selected(env, choice="1", **changes):
    body = {**env.payload, **changes}
    plan = coordinator.plan_request(env.authorized, env.service, body)
    return {**body, "selection": {"id": choice, "plan_sha256": plan["plan_sha256"]}}


def test_ambiguous_goal_never_guesses_keywords_or_dispatches(scenario):
    env = scenario
    before = list(env.service._all(env.context, EntityKind.TASK))
    body = {**env.payload, "goal": "numeric_breakdown verify_fact_transfer разберись сам"}
    preview = coordinator.plan_request(env.authorized, env.service, body)
    assert preview["status"] == "clarification_required" and preview["dispatches"] == 0
    assert len(preview["choices"]) == 2
    assert "operation" not in str(preview)
    with pytest.raises(ContractError, match="clarification_required"):
        coordinator.commission_request(env.authorized, env.service, body, "ambiguous")
    assert list(env.service._all(env.context, EntityKind.TASK)) == before


@pytest.mark.parametrize("operation", ["numeric_breakdown", "verify_fact_transfer", "execute_trade"])
def test_public_operation_injection_rejected(scenario, operation):
    with pytest.raises(ContractError, match="public_payload_invalid"):
        coordinator.plan_request(scenario.authorized, scenario.service, {**scenario.payload, "operation": operation})


def test_selection_is_bound_to_goal_data_and_workspace(scenario):
    env = scenario
    body = selected(env)
    for change in ({"goal": "changed"}, {"input_text": "[4,5,6]"}):
        with pytest.raises(ContractError, match="clarification_required"):
            coordinator.commission_request(env.authorized, env.service, {**body, **change}, "changed")
    bad = {**body, "selection": {**body["selection"], "id": "execute_trade"}}
    with pytest.raises(ContractError, match="selection_unavailable"):
        coordinator.commission_request(env.authorized, env.service, bad, "bad-choice")
    foreign = replace(env.context, scope=replace(env.context.scope, workspace_id="ws_foreign_scope_123"))
    with pytest.raises(ContractError):
        intent_planning.resolve(foreign, env.service, body)


@pytest.mark.parametrize("change", [
    {"parent_indices": [1, -1, 0]}, {"parent_indices": [-1, -1, -1]},
    {"max_depth": 2}, {"max_depth": True},
])
def test_public_plan_bounds_before_dispatch(scenario, change):
    with pytest.raises(ContractError, match="delegation_"):
        coordinator.plan_request(scenario.authorized, scenario.service, {**scenario.payload, **change})
    assert not list(scenario.service._all(scenario.context, EntityKind.TASK))


def test_cancel_then_new_intent_preserves_old_request_and_replays(scenario):
    env = scenario
    first = coordinator.commission_request(env.authorized, env.service, selected(env), "intent-first")
    assert first["intent_status"] == "waiting" and first["intent_status_consistent"]
    old_task = env.service._get(env.context, EntityKind.TASK, first["root_task_id"])
    old_intent = env.service._get(env.context, EntityKind.INTENT, old_task.intent.entity_id)
    body = selected(env, goal="Уточнённая цель", input_text="[6,7,8]")
    bad = {**body, "selection": {**body["selection"], "plan_sha256": "0" * 64}}
    with pytest.raises(ContractError):
        coordinator.clarify_request(env.authorized, env.service, first["id"], bad, "intent-second", expected_revision=first["revision"])
    assert coordinator.projection(env.authorized, env.service, first["id"])["status"] != "cancelled"
    with pytest.raises(ContractError, match="revision_conflict"):
        coordinator.clarify_request(env.authorized, env.service, first["id"], body, "intent-second", expected_revision=0)
    result = coordinator.clarify_request(env.authorized, env.service, first["id"], body, "intent-second", expected_revision=first["revision"])
    assert result["intent_id"] != first["intent_id"]
    assert result["supersedes"]["coordinator_id"] == first["id"]
    retained = env.service._get(env.context, EntityKind.INTENT, old_intent.header.entity_id)
    assert retained.goal == old_intent.goal and retained.acceptance == old_intent.acceptance
    assert retained.status == "cancelled"
    cancelled = coordinator.projection(env.authorized, env.service, first["id"])
    assert cancelled["intent_status"] == "cancelled" and cancelled["intent_status_consistent"]
    assert coordinator.clarify_request(env.authorized, env.service, first["id"], body, "intent-second", expected_revision=first["revision"])["id"] == result["id"]
    with pytest.raises(ContractError, match="finalized_record_immutable"):
        env.service._change(env.context, retained, goal=env.service._put(env.context, {"goal": "tamper"}))


@pytest.mark.parametrize("terminal,expected", [("succeeded", "completed"), ("failed", "failed"), ("blocked", "blocked")])
def test_control_intent_follows_existing_states_without_changing_payload(scenario, terminal, expected):
    env = scenario
    view = coordinator.commission_request(env.authorized, env.service, selected(env), "state-alignment")
    intent = env.service._get(env.context, EntityKind.INTENT, view["intent_id"])
    original_goal, original_acceptance = intent.goal, intent.acceptance
    control = env.service._get(env.context, EntityKind.TASK, view["id"])
    control = env.service._walk(env.context, control, "ready", "running")
    running = coordinator._sync_control_intent(env.service, env.context, control)
    assert running.status == "running"
    control = env.service._change(env.context, control, "waiting")
    assert coordinator._sync_control_intent(env.service, env.context, control).status == "waiting"
    control = env.service._walk(env.context, control, "ready", "running")
    control = env.service._change(env.context, control, terminal)
    final = coordinator._sync_control_intent(env.service, env.context, control)
    assert final.status == expected and final.goal == original_goal and final.acceptance == original_acceptance
    assert coordinator._sync_control_intent(env.service, env.context, control) == final
    projection = coordinator.projection(env.authorized, env.service, view["id"])
    assert projection["intent_status"] == expected and projection["intent_status_consistent"]


def test_projection_reports_historical_mismatch_without_mutating_it(scenario):
    env = scenario
    view = coordinator.commission_request(env.authorized, env.service, selected(env), "history-state-view")
    intent = env.service._get(env.context, EntityKind.INTENT, view["intent_id"])
    historical = env.service._change(env.context, intent, "ready")
    projected = coordinator.projection(env.authorized, env.service, view["id"])
    assert projected["intent_status"] == "ready" and projected["intent_expected_status"] == "waiting"
    assert projected["intent_status_consistent"] is False
    assert env.service._get(env.context, EntityKind.INTENT, view["intent_id"]) == historical


@pytest.mark.parametrize("choice,operation", [("1", "verify_fact_transfer"), ("2", "numeric_breakdown")])
def test_two_typed_meanings_create_existing_distinct_operations(scenario, choice, operation):
    env = scenario
    body = selected(env, choice, input_text="[1,2,3,10,20,30]",
                    target_model_ids=[row["id"] for row in env.models[1:3]], parent_indices=[-1,-1])
    view = coordinator.commission_request(env.authorized, env.service, body, "typed-intent-" + choice)
    assert view["planned_synthetic"] is True
    assert view["planned_execution"]["root"] == "diagnostic"
    assert all(row["mode"] == "diagnostic" for row in view["planned_execution"]["children"])
    assert all(node["operation"] == operation for node in view["nodes"])
    assert view["intent_selection"]["origin"] == "explicit_human_clarification"
    assert coordinator.commission_request(env.authorized, env.service, body, "typed-intent-" + choice)["id"] == view["id"]
    # Reopen the repository and re-resolve authority before durable work resumes.
    env.authorized, env.service = human(env.world)
    for _ in range(4):
        tick(env)
        view = coordinator.projection(env.authorized, env.service, view["id"])
        if view["stage"] == "awaiting_approval":
            break
    preview = coordinator.preview(env.authorized, env.service, view["id"])
    assert preview["plan"]["synthetic"] is True
    approved = coordinator.approve(env.authorized, env.service, view["id"], {
        "approved_plan_sha256": preview["approved_plan_sha256"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), "max_call_cost_usd": 0.0})
    graph = finish(env, approved["graph"]["id"])
    completed = coordinator.projection(env.authorized, env.service, view["id"])
    assert completed["status"] == "review" and completed["intent_status"] == "waiting"
    assert completed["intent_status_consistent"]
    assert graph["result"]["operation"] == operation
    assert len(graph["result"]["contributions"]) == 2
    assert graph["synthetic"] and not graph["human_accepted"]
    facts = [row["facts_sha256"] for row in graph["result"]["contributions"]]
    assert (facts[0] != facts[1]) == (choice == "2")
