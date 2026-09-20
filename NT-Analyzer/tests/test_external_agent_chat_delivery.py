"""Saved native external receipts, not provider reruns, drive SF Chat recovery."""
from dataclasses import replace

import pytest

from app.ai_lab import chief_agent
from app.ai_control_center import domain_gateway as gateway, external_agent_chat
from app.ai_control_center.external_agent_adapter import ExternalAgentAdapter
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_automation_revocation import world, human
from tests.test_external_agent_native_e2e import external, connected, act


def test_delivery_failure_retries_saved_receipt_without_dispatch(external, monkeypatch):
    env = external
    conn = connected(env)
    started = act(env, conn["id"], "task", {"input_text": "[1,2,3]"}, key="external-chat-retry")
    identity = started["started_task_id"]
    service = gateway.external_agents(env.authorized)
    detail = service.task_detail(identity)
    assert detail["conversation_id"] and detail["message_id"]
    sends = []
    original_send = ExternalAgentAdapter.send
    def send(*args, **kwargs):
        sends.append(1)
        return original_send(*args, **kwargs)
    monkeypatch.setattr(ExternalAgentAdapter, "send", send)
    report = chief_agent.report_agent_world_live_update
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", lambda *a, **kw: (_ for _ in ()).throw(OSError("delivery unavailable")))
    with pytest.raises(OSError):
        service.execute(identity, lambda: False, lambda: None)
    assert service.records._get(service.context, EntityKind.TASK, identity).status == "review"
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", report)
    assert service.execute(identity, lambda: False, lambda: None)["status"] == "review"
    assert service.execute(identity, lambda: False, lambda: None)["status"] == "review"
    assert len(sends) == 1
    rows = chief_agent.read_jsonl(chief_agent._conversation_file(detail["conversation_id"], scope=env.authorized["chat_scope"]))
    results = [row for row in rows if row.get("source") == "agent_world_local"]
    assert len(results) == 1
    assert results[0]["actions"][0]["source_kind"] == external_agent_chat.SOURCE
    assert results[0]["actions"][0]["status"] == "awaiting_review"
    assert results[0]["actions"][0]["synthetic"] is True
    assert "externally managed" in results[0]["content"]


def test_external_delivery_rejects_forged_or_foreign_evidence(external):
    env = external
    conn = connected(env)
    identity = act(env, conn["id"], "task", {"input_text": "[1,2,3]"}, key="external-chat-scope")["started_task_id"]
    service = gateway.external_agents(env.authorized)
    service.execute(identity, lambda: False, lambda: None)
    saved = external_agent_chat.envelope(env.authorized, service, identity)
    readonly = gateway.access(env.authorized["chat_scope"], read_only=True)
    with pytest.raises(ContractError):
        external_agent_chat.validate(readonly, {**saved, "text": "fake success"})
    with pytest.raises(ContractError):
        external_agent_chat.validate(readonly, {**saved, "conversation_id": "foreign"})
    foreign = {**env.authorized, "context": replace(env.context, scope=replace(env.context.scope,
        workspace_id="ws_external_foreign_test"))}
    with pytest.raises(ContractError):
        external_agent_chat.envelope(foreign, gateway.external_agents(foreign), identity)
    assert not list(service.records._all(service.context, EntityKind.MODEL))


@pytest.mark.parametrize("decision,expected", [("accept", "completed"), ("reject", "rejected")])
def test_saved_human_review_delivery_failure_recovers_only_chat(external, monkeypatch, decision, expected):
    env = external
    conn = connected(env)
    identity = act(env, conn["id"], "task", {"input_text": "[1,2,3]"}, key="external-human-review")["started_task_id"]
    service = gateway.external_agents(env.authorized)
    service.execute(identity, lambda: False, lambda: None)
    detail = service.task_detail(identity)
    evaluations_before = list(service.records._all(service.context, EntityKind.EVALUATION))
    def forbidden(*args, **kwargs):
        pytest.fail("Human review delivery must not dispatch an external agent")
    monkeypatch.setattr(ExternalAgentAdapter, "send", forbidden)
    payload = {"expected_revision": detail["revision"], "idempotency_key": "external-human-review-decision",
        "payload": {"decision": decision, "comment": "Checked separately", "source_sha256": detail["human_review"]["source_sha256"]}}
    report = chief_agent.report_agent_world_live_update
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", lambda *a, **kw: (_ for _ in ()).throw(OSError("transport interrupted")))
    first = gateway.mutate(env.authorized, "tasks", identity, "review_result", payload)
    assert first["human_review"]["status"] == ("accepted" if decision == "accept" else "rejected")
    assert first["chat_delivery"]["status"] == "pending"
    assert first["chat_delivery"]["problems"][0]["error_code"] == "review_delivery_pending"
    evaluations_after_review = list(service.records._all(service.context, EntityKind.EVALUATION))
    assert len(evaluations_after_review) == len(evaluations_before) + 1  # One canonical human decision.
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", report)
    recovered = gateway.mutate(env.authorized, "tasks", identity, "review_result", payload)
    assert recovered["deduplicated"] is True
    assert recovered["chat_delivery"]["status"] == "queued_or_delivered"
    gateway.mutate(env.authorized, "tasks", identity, "review_result", payload)
    assert list(service.records._all(service.context, EntityKind.EVALUATION)) == evaluations_after_review
    rows = chief_agent.read_jsonl(chief_agent._conversation_file(detail["conversation_id"], scope=env.authorized["chat_scope"]))
    updates = [row for row in rows if row.get("source") == "agent_world_local"]
    assert len(updates) == 2  # Original awaiting-review receipt is retained.
    assert [row["actions"][0]["status"] for row in updates] == ["awaiting_review", expected]
