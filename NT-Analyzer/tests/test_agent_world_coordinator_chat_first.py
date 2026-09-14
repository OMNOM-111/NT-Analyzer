"""Ordinary SF Chat ingress uses the same scoped Coordinator and semantic plan."""
from dataclasses import replace
from pathlib import Path

import pytest

from app.ai_control_center import coordinator, domain_gateway, delegation, persona_identity
from app.ai_control_center.states import ContractError, EntityKind
from app.ai_lab import chief_agent
from tests.test_agent_world_coordinator import scenario, world, human


def ingress(env):
    return coordinator.try_chat("Координатор: Проверь мои числа", scope=env.authorized["chat_scope"],
        conversation_id="chat-first-coordinator", request_id="chat-first-request", source="app")


def test_ordinary_message_clarification_native_task_and_provenance(scenario, monkeypatch):
    env = scenario
    def intercepted(*args, **kwargs):
        pytest.fail("Explicit Coordinator request was intercepted by active Persona")
    monkeypatch.setattr(persona_identity, "try_chat", intercepted)
    response = chief_agent._handle_message_impl("Координатор: Проверь мои числа", source="app",
        conversation_id="chat-first-coordinator", request_id="chat-first-request",
        scope=env.authorized["chat_scope"], persona_id=env.models[0]["persona_id"])
    assert response["status"] == "clarification_required"
    assert not list(env.service._all(env.context, EntityKind.TASK))
    action = response["actions"][0]
    assert action["name"] == "coordinator_clarification"
    assert "plan_sha256" not in response["reply"]
    source = {key: action[key] for key in ("conversation_id", "source_message_id")}
    def call(action, payload, key="chat-first-action"):
        return domain_gateway.mutate(env.authorized, "automation", "new", action,
            {"payload": payload, "idempotency_key": key})
    seed = call("chat_seed", source)
    assert seed["goal"] == "Проверь мои числа"
    payload = {**env.payload, "goal": seed["goal"], "chat_source": source}
    plan = call("commission", payload)
    assert plan["status"] == "clarification_required"
    assert not list(env.service._all(env.context, EntityKind.TASK))
    payload["selection"] = {"id": "1", "plan_sha256": plan["plan_sha256"]}
    view = call("commission", payload)
    task = env.service.task_detail(context=env.context, task_id=view["root_task_id"])
    assert task["conversation_id"] == source["conversation_id"]
    control, _, saved = delegation.controller(env.service, env.context, view["id"], coordinator.SOURCE)
    assert saved["chat_source"] == source
    rows = chief_agent.read_jsonl(chief_agent._conversation_file(task["conversation_id"], scope=env.authorized["chat_scope"]))
    assert any(row["message_id"] == source["source_message_id"] and row["content"] == seed["original_message"] for row in rows)
    assert call("commission", payload, "different-transport-key")["id"] == view["id"]
    assert ingress(env)["idempotent_replay"] is True
    with pytest.raises(ContractError, match="request_changed"):
        coordinator.try_chat("Координатор: Другая цель", scope=env.authorized["chat_scope"],
            conversation_id="chat-first-coordinator", request_id="chat-first-request", source="app")


def test_source_cannot_be_forged_or_cross_workspace(scenario):
    env = scenario
    action = ingress(env)["actions"][0]
    source = {key: action[key] for key in ("conversation_id", "source_message_id")}
    with pytest.raises(ContractError):
        coordinator.chat_seed(env.authorized, {**source, "source_message_id": "missing"})
    foreign = {**env.authorized, "context": replace(env.context, scope=replace(env.context.scope, workspace_id="ws_foreign_workspace"))}
    with pytest.raises(ContractError):
        coordinator.chat_seed(foreign, source)
    with pytest.raises(ContractError, match="goal_changed"):
        coordinator.chat_commission(env.authorized, env.service, {**env.payload, "chat_source": source}, "bad")


def test_chat_button_and_form_use_labels_not_public_json():
    root = Path(__file__).resolve().parents[1]
    chat = (root / "app/static/aurora/assets/ui.js").read_text(encoding="utf-8")
    ui = (root / "app/static/aurora/assets/pages/ai-command-center.js").read_text(encoding="utf-8")
    chief = (root / "app/ai_lab/chief_agent.py").read_text(encoding="utf-8")
    assert "name === 'coordinator_clarification'" in chat
    assert "Уточнить данные и ожидаемый результат" in chat
    assert "chat_seed" in ui and "chatSource: chatSeed?.chat_source" in ui
    assert "name=\"intent_choice\"" in ui
    assert "Исходные числа (JSON-массив)" not in ui
    assert chief.index("coordinated_turn = coordinator.try_chat") < chief.index("persona_turn = persona_identity.try_chat")
