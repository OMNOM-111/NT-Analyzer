"""Real disposable source/auth/connection plan must match the reviewed snapshot."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.ai_lab import chief_agent
from app.ai_control_center import domain_gateway, live_gateway, model_chat, test_executor
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_automation_revocation import world, human
from tests.test_agent_world_coordinator import scenario


@pytest.fixture
def approved_source(scenario, monkeypatch):
    env = scenario
    flags = json.loads(__import__('os').environ[live_gateway.MECHANISMS_ENV])
    flags["flags"]["AI_SCHEDULER_V1"] = [env.world.workspace]
    monkeypatch.setenv(live_gateway.MECHANISMS_ENV, json.dumps(flags))
    live_gateway._SNAPSHOTS.clear()
    env.authorized, env.service = human(env.world)
    service = domain_gateway.domains(env.authorized)
    item = service.create(context=env.context, admit=env.authorized["admit"], domain="routines",
        payload={"title": "Explicit reviewed routine", "description": "Diagnostic only", "interval_minutes": 5},
        idempotency_key="approval-source")['item']
    item = service.act(context=env.context, admit=env.authorized["admit"], domain="routines", entity_id=item["id"],
        expected_revision=item["revision"], action="accept", payload={}, idempotency_key="approval-consent")['item']
    cid = model_chat._conversation(env.authorized, "approval-message", "Schedule approval")
    message = chief_agent._append_conversation("user", "Repeat arithmetic diagnostic", source="app", request_id="approval-message",
        path=chief_agent._conversation_file(cid, scope=env.authorized["chat_scope"]), scope=env.authorized["chat_scope"])
    payload = {"model_id": env.models[0]["id"], "source_domain": "routines", "conversation_id": cid,
        "message_id": message["message_id"], "rubric_key": "json_arithmetic", "input_text": "[1,2,3]",
        "max_call_cost_usd": 0, "grant_hours": 1,
        "schedule": {"local_start": (datetime.now(timezone.utc)+timedelta(minutes=2)).replace(tzinfo=None).isoformat(),
            "timezone": "UTC", "interval_seconds": 0, "occurrences": 1, "grace_seconds": 60}}
    def call(action, body):
        return domain_gateway.mutate(env.authorized, "automation", item["id"], action,
            {"payload": body, "expected_revision": item["revision"], "idempotency_key": "reviewed-schedule"})
    preview = call("propose", payload)
    payload["approved_plan_sha256"] = preview["approved_plan_sha256"]
    env.routine, env.domain_service, env.schedule_payload, env.schedule_call = item, service, payload, call
    return env


def test_exact_reviewed_schedule_plan_can_be_enabled(approved_source):
    env = approved_source
    result = env.schedule_call("enable", env.schedule_payload)
    assert result["approved"] is True


@pytest.mark.parametrize("change", ["missing_hash", "wrong_hash", "mode", "profile", "source"])
def test_stale_schedule_snapshot_never_creates_grant(approved_source, monkeypatch, change):
    env = approved_source
    if change == "missing_hash":
        env.schedule_payload.pop("approved_plan_sha256")
    elif change == "wrong_hash":
        env.schedule_payload["approved_plan_sha256"] = "0" * 64
    elif change == "mode":
        monkeypatch.delenv(test_executor.ENV, raising=False)
    elif change == "profile":
        model = env.service._get(env.context, EntityKind.MODEL, env.models[0]["id"])
        profile = env.service._json(env.context, model.profile)
        profile["base_url"] = "https://changed-after-review.example/v1"
        env.service._change(env.context, model, profile=env.service._put(env.context, profile))
    else:
        env.domain_service.act(context=env.context, admit=env.authorized["admit"], domain="routines", entity_id=env.routine["id"],
            expected_revision=env.routine["revision"], action="dismiss", payload={}, idempotency_key="withdraw-before-approval")
    with pytest.raises(ContractError):
        env.schedule_call("enable", env.schedule_payload)
    grants = domain_gateway.list_domain(env.authorized, "automation")["items"]
    assert grants == []
