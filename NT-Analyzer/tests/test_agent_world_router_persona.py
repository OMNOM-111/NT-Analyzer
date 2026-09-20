"""Router speaker/executor contracts on disposable records only.

Transport is an in-memory provider-contract double, not a real model-quality
claim. The final scenario also exercises ordinary auth/device and the existing
durable worker/Execution V2. No user data, sockets or paid calls are permitted.
"""
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ai_control_center import contracts as c, execution_v2, mechanism_domains, router_v2 as router
from app.ai_control_center.model_evaluation import digest
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_models import setup, response
from tests.test_agent_world_router_v2 import authorization, observed, priced
from tests.test_agent_world_automation_revocation import world
from tests.test_agent_world_router_acceptance import routed, preview, apply, completed


@pytest.fixture
def speaking(setup, monkeypatch):
    service, context, payload, *_ = setup
    original_executor = service.executor
    source_persona = service._get(context, EntityKind.PERSONA, payload["persona_id"])
    source_profile = {"avatar": "persona-avatar-existing.png", "voice": {"rate": .9},
                      "description": "source speaker, not the selected executor"}
    source_persona = service._change(context, source_persona, display_name="Source Speaker",
                                    profile=service._put(context, source_profile))
    current = observed(setup, "speaking-source")
    target = service._ensure(context, c.Persona, uuid4(), uuid4(), source_persona.header.policy,
        display_name="Executor Connection Persona", profile=service._put(context, {"description": "separate identity"}))
    target = service._walk(context, target, "active")
    alternate_setup = (service, context, {**payload, "persona_id": str(target.header.entity_id)}, *setup[3:])
    service.executor = original_executor
    selected = observed(alternate_setup, "speaking-executor")
    source = service.start_task(context=context, model_id=current["id"],
        payload={"rubric_key": "json_arithmetic", "input_text": "[7, 2, 3]"},
        conversation_id=uuid4(), message_id=uuid4(), idempotency_key="speaking-original-request")
    auth = authorization(context)
    service.mechanism_authorized = auth
    monkeypatch.setattr(mechanism_domains, "_quote", priced(selected, current))
    env = SimpleNamespace(service=service, context=context, auth=auth, source=source,
        source_persona=source_persona, executor_persona=target, current=current, selected=selected,
        payload={"candidate_model_ids": [current["id"], selected["id"]], "max_cost_usd": .01}, calls=[])
    def transport(**kwargs):
        kwargs["admit"](kwargs["context"], "provider_transmit", .0002)
        env.calls.append(str(kwargs["model"].header.entity_id))
        values = json.loads(kwargs["prompt"].split("Array: ")[1])
        return response(json.dumps({"count": len(values), "sum": sum(values), "min": min(values),
            "max": max(values), "mean": sum(values) / len(values)}),
            actual_model="persona-contract-double", executor="persona-contract-double", external_call=False)
    service.executor = transport
    env.preview = lambda: mechanism_domains._preview(auth, service, source["id"], env.payload)
    env.apply = lambda shown, key="speaker-apply": mechanism_domains._apply(auth, service, source["id"],
        {"preview_ref": shown["preview_ref"]}, key, shown["source_revision"])
    return env


def test_router_keeps_source_speaker_role_avatar_and_settings_but_uses_selected_executor(speaking):
    env = speaking
    service, ctx = env.service, env.context
    before = {record.header.entity_id: record for record in service._all(ctx, EntityKind.PERSONA)}
    shown = env.preview()
    assert shown["preview_version"] == router.PREVIEW_VERSION
    assert shown["speaking_identity"]["persona_ref"] == c.primitive(env.source_persona.ref())
    assert shown["selected_model_id"] == env.selected["id"] and not env.calls
    applied = env.apply(shown)
    task = service._get(ctx, EntityKind.TASK, applied["started_task_id"])
    source = service._get(ctx, EntityKind.TASK, env.source["id"])
    checkpoint = service._json(ctx, task.checkpoint)
    assert checkpoint["routing"]["version"] == router.APPLIED_VERSION
    assert task.role == source.role and checkpoint["speaking_identity"] == shown["speaking_identity"]
    assert checkpoint["persona_id"] == str(env.source_persona.header.entity_id)
    assert checkpoint["executor_persona_id"] == str(env.executor_persona.header.entity_id)
    assert checkpoint["provider_account_id"] == env.selected["provider_account_id"]
    result = service.execute(context=ctx, task_id=task.header.entity_id)
    assert result["status"] == "succeeded" and env.calls == [env.selected["id"]]
    assert result["lead"]["id"] == str(env.source_persona.header.entity_id)
    assert result["lead"]["display_name"] == "Source Speaker"
    assert result["model_id"] == env.selected["id"] and result["human_review"]["status"] == "pending"
    assert env.apply(shown)["replayed"] and env.calls == [env.selected["id"]]
    assert before == {record.header.entity_id: record for record in service._all(ctx, EntityKind.PERSONA)}
    actual = router.actual_choice(service, ctx, service._get(ctx, EntityKind.TASK, task.header.entity_id),
                                  service._json(ctx, service._get(ctx, EntityKind.TASK, task.header.entity_id).checkpoint))
    assert actual["persona_preserved"] and actual["speaking_persona_id"] != actual["executor_persona_id"]
    assert actual["executor"] == "persona-contract-double" and actual["external_call"] is False


@pytest.mark.parametrize("mutation", ["rename", "profile", "suspend"])
def test_source_persona_change_requires_fresh_preview_without_dispatch(speaking, mutation):
    env = speaking
    shown = env.preview()
    persona = env.source_persona
    if mutation == "rename":
        env.service._change(env.context, persona, display_name="Renamed Source")
    elif mutation == "profile":
        env.service._change(env.context, persona, profile=env.service._put(env.context, {"description": "new source settings"}))
    else:
        env.service._change(env.context, persona, "suspended")
    with pytest.raises(ContractError, match="routing_speaking_identity_changed"):
        env.apply(shown)
    assert not env.calls
    if mutation != "suspend":
        fresh = env.preview()
        applied = env.apply(fresh)
        detail = env.service.task_detail(context=env.context, task_id=applied["started_task_id"])
        # Retain the original request's name; never adopt the executor's name.
        assert detail["lead"]["display_name"] == "Source Speaker"
        assert detail["speaking_identity"]["persona_ref"]["revision"] == persona.header.revision + 1


def test_source_suspended_after_apply_blocks_new_call_but_keeps_readable_identity(speaking):
    env = speaking
    applied = env.apply(env.preview())
    env.service._change(env.context, env.source_persona, "suspended")
    result = env.service.execute(context=env.context, task_id=applied["started_task_id"])
    assert result["status"] == "blocked" and result["error_code"] == "routing_speaking_identity_changed"
    assert result["lead"]["display_name"] == "Source Speaker" and not env.calls


def test_receipt_history_does_not_rewrite_speaker_after_rename_or_flag_change(speaking):
    env = speaking
    shown = env.preview()
    applied = env.apply(shown)
    result = env.service.execute(context=env.context, task_id=applied["started_task_id"])
    env.service._change(env.context, env.source_persona, display_name="Future Name")
    env.service.mechanism_authorized = authorization(env.context, active=False, shadow=False)
    saved = env.service.task_detail(context=env.context, task_id=result["id"])
    assert saved["lead"] == result["lead"] and saved["result_text"] == result["result_text"]
    assert env.calls == [env.selected["id"]]


@pytest.mark.parametrize("field", ["persona_id", "persona_name", "speaking_identity", "executor_persona_id", "role"])
def test_mutated_routed_assignment_is_not_projected_or_transmitted(speaking, field):
    env = speaking
    applied = env.apply(env.preview())
    task = env.service._get(env.context, EntityKind.TASK, applied["started_task_id"])
    checkpoint = env.service._json(env.context, task.checkpoint)
    if field == "role":
        original_role = env.service._get(env.context, EntityKind.AGENT_ROLE, task.role.entity_id)
        other_role = env.service._ensure(env.context, c.AgentRole, uuid4(), uuid4(), task.header.policy,
            role_key="different_response", responsibilities=original_role.responsibilities,
            capability_ceiling=original_role.capability_ceiling, autonomy_ceiling=original_role.autonomy_ceiling)
        other_role = env.service._walk(env.context, other_role, "active")
        task = env.service._change(env.context, task, role=other_role.ref())
    else:
        checkpoint[field] = {} if field == "speaking_identity" else str(uuid4())
        task = env.service._change(env.context, task, checkpoint=env.service._put(env.context, checkpoint))
    with pytest.raises(ContractError, match="routing_speaking_assignment_changed"):
        env.service.task_detail(context=env.context, task_id=task.header.entity_id)
    with pytest.raises(ContractError, match="routing_speaking_assignment_changed"):
        router.validate_execution(env.service, env.context, task, checkpoint)
    assert not env.calls


def test_public_persona_override_and_foreign_source_are_rejected(speaking):
    env = speaking
    for payload in ({**env.payload, "persona_id": str(env.executor_persona.header.entity_id)},
                    {**env.payload, "speaking_identity": {}}):
        with pytest.raises(ContractError, match="routing_request_invalid"):
            mechanism_domains._preview(env.auth, env.service, env.source["id"], payload)
    other_id = uuid4()
    other = replace(env.context, user_uuid=other_id, actor=c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=other_id))
    with pytest.raises(ContractError):
        router._preview_record(env.service, other, env.preview()["preview_ref"])
    assert not env.calls


def test_legacy_preview_can_be_read_but_cannot_admit_a_new_identity_unpinned_task(speaking):
    env = speaking
    shown = env.preview()
    legacy = env.service._json(env.context, shown["preview_ref"])
    legacy.pop("speaking_identity")
    legacy["version"] = "agent-world-routing-preview-v1"
    reference = env.service._put(env.context, legacy)
    assert router._preview_record(env.service, env.context, reference)[1] == legacy
    with pytest.raises(ContractError, match="routing_fresh_identity_preview_required"):
        env.apply({**shown, "preview_ref": c.primitive(reference)})
    assert not env.calls


def test_legacy_routed_checkpoint_is_read_only_history_not_a_claim_of_persona_preservation(speaking):
    env = speaking
    shown = env.preview()
    saved = env.service._json(env.context, shown["preview_ref"])
    saved.pop("speaking_identity")
    saved["version"] = "agent-world-routing-preview-v1"
    preview_ref = env.service._put(env.context, saved)
    # Reconstruct an old *pending* checkpoint through typed disposable stores;
    # no completed outcome, evaluation, receipt or graph is fabricated.
    detail = env.service.start_task(context=env.context, model_id=env.selected["id"],
        payload={"rubric_key": "json_arithmetic", "input_text": "[7,2,3]"},
        idempotency_key="legacy-pending-fixture", conversation_id=env.source["conversation_id"],
        message_id=env.source["message_id"])
    task = env.service._get(env.context, EntityKind.TASK, detail["id"])
    proof = env.service._put(env.context, {"version": "agent-world-routing-applied-v1",
        "preview_ref": c.primitive(preview_ref), "task_id": detail["id"],
        "selection_sha256": saved["selection_sha256"], "selected_model_id": env.selected["id"],
        "permission_granted": False})
    packet = router.RoutedTaskPacket(preview_ref=preview_ref, decision_ref=proof,
                                    task_id=task.header.entity_id, version="agent-world-routing-applied-v1")
    checkpoint = env.service._json(env.context, task.checkpoint)
    checkpoint["routing"] = packet.wire()
    checkpoint["request_sha256"] = digest(execution_v2._request(checkpoint))
    task = env.service._change(env.context, task, checkpoint=env.service._put(env.context, checkpoint))
    actual = router.actual_choice(env.service, env.context, task, checkpoint)
    assert actual["persona_preserved"] is None and actual["speaking_identity"] is None
    assert actual["speaking_persona_id"] == str(env.executor_persona.header.entity_id)
    assert env.service.task_detail(context=env.context, task_id=detail["id"])["lead"] == detail["lead"]
    with pytest.raises(ContractError, match="routing_fresh_identity_preview_required"):
        router.validate_execution(env.service, env.context, task, checkpoint)
    assert not env.calls


def test_unrouted_task_retains_its_assigned_persona_not_a_previous_source_speaker(speaking):
    env = speaking
    env.apply(env.preview())
    independent = env.service.start_task(context=env.context, model_id=env.selected["id"],
        payload={"rubric_key": "json_arithmetic", "input_text": "[8,9,10]"}, idempotency_key="independent-specialist")
    assert independent["persona_id"] == str(env.executor_persona.header.entity_id)
    assert independent["lead"]["display_name"] == env.executor_persona.display_name
    assert "speaking_identity" not in independent


def test_ordinary_worker_and_execution_v2_pin_both_identities(routed):
    """Actual ordinary admission/queue/controller with an offline transport."""
    env = routed
    shown = preview(env)
    applied = apply(env, shown)
    source = env.service.task_detail(context=env.context, task_id=env.source_id)
    task_id = applied["started_task_id"]
    _, approved, _ = execution_v2._load(env.service, env.context, task_id)
    assert approved["speaking_identity"] == shown["speaking_identity"]
    assert approved["executor_persona_id"] == env.models[1]["persona_id"]
    task = env.service._get(env.context, EntityKind.TASK, task_id)
    checkpoint = env.service._json(env.context, task.checkpoint)
    altered = env.service._change(env.context, task,
        checkpoint=env.service._put(env.context, {**checkpoint, "persona_name": "Wrong Speaker"}))
    with pytest.raises(ContractError, match="routing_speaking_assignment_changed"):
        execution_v2._scope(env.service, env.context, task_id, approved)
    # Restore only this deliberate disposable pre-transmit mutation, not any
    # history/result. The original issued packet must still run unchanged.
    env.service._change(env.context, altered, checkpoint=task.checkpoint)
    result = completed(env, task_id)
    assert result["status"] == "succeeded" and result["human_review"]["status"] == "pending"
    assert result["lead"] == source["lead"] and result["model_id"] == env.models[1]["id"]
    assert execution_v2.projection(env.service, env.context, task_id)["status"] == "succeeded"
    task = env.service._get(env.context, EntityKind.TASK, task_id)
    checkpoint = env.service._json(env.context, task.checkpoint)
    checkpoint["persona_name"] = "Wrong Speaker"
    with pytest.raises(ContractError, match="finalized_record_immutable"):
        env.service._change(env.context, task, checkpoint=env.service._put(env.context, checkpoint))
