"""Router preview/apply on disposable real auth, queue and Execution V2.

The injected transport is an explicitly isolated provider-contract double.
No socket or real model is called; these are pipeline tests, not model-quality
observations for a running Local. All evidence is produced through normal tasks.
"""
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import account_auth, durable, local_worker, worker_router, workspaces
from app.ai_lab import chief_agent
from app.ai_control_center import contracts as c, domain_gateway as gateway
from app.ai_control_center import execution_v2, mechanism_domains, result_handoff, test_executor
from app.ai_control_center.model_service import ModelService
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_automation_revocation import world, human, OWNER_ID
from tests.test_agent_world_models import response


@pytest.fixture
def routed(world, tmp_path, monkeypatch):
    # Only initial registration/device state is fixture data. Every model
    # observation, preview, routed task and receipt below uses real services.
    uid, identity, session_id, device_id = 990101, str(uuid4()), "router-user-session", str(uuid4())
    doc = account_auth._read_doc()
    doc["users"].append({"user_id": uid, "user_uuid": identity, "is_owner": False, "status": "active",
        "role": "full_control", "ux_mode": "professional", "first_name": "Router", "last_name": "Fixture",
        "email": "router-user@example.invalid"})
    doc["sessions"].append({"session_id": session_id, "user_id": uid, "expires_at": time.time() + 3600,
        "revoked": False, "device_confirmation_state": "active", "trusted_device_id": device_id,
        "device_trust_mode": "permanent"})
    doc["trusted_devices"].append({"device_id": device_id, "user_uuid": identity,
        "status": "trusted", "trust_mode": "permanent"})
    account_auth._write_doc(doc)
    for capability in ("ai_lab", "ai_pro_models"):
        account_auth.set_user_permission(OWNER_ID, uid, capability, True)
    workspace = workspaces.ensure_personal_workspace(uid, require_entitlement=False)["workspace_id"]
    original_world = world
    world = SimpleNamespace(workspace=workspace,
        scope={"user_id": uid, "user_uuid": identity, "workspace_id": workspace, "auth_session_id": session_id},
        mechanisms=lambda *names: original_world.mechanisms(*names).replace(original_world.workspace, workspace))
    monkeypatch.setenv(gateway.live_gateway.WORKSPACES_ENV, workspace)
    monkeypatch.setenv(test_executor.ENV, "")
    monkeypatch.setenv(gateway.live_gateway.MECHANISMS_ENV,
        world.mechanisms("AI_EXECUTION_V2", "AI_ROUTER_SHADOW_V2", "AI_ROUTER_V2"))
    registry = tmp_path / "router-chat"
    registry.mkdir()
    monkeypatch.setattr(chief_agent.paths, "REGISTRY_DIR", registry)
    monkeypatch.setattr(chief_agent.paths, "PROJECT_ROOT", tmp_path)
    calls, prices = [], {}
    def transport(**kw):
        kw["admit"](kw["context"], "provider_transmit", 0.0)
        identity = str(kw["model"].header.entity_id)
        calls.append(identity)
        if kw["purpose"] == "connection_test":
            text = "CONNECTION_OK"
        else:
            values = json.loads(kw["prompt"].split("Array: ")[1])
            text = json.dumps({"count": len(values), "sum": sum(values), "min": min(values),
                              "max": max(values), "mean": sum(values) / len(values)})
        return response(text, actual_model="router-acceptance-transport-double", executor="router-acceptance-double",
                        external_call=False, cost_usd=0.0, elapsed_sec=.100 if kw["profile"]["label"] == "Slow" else .020)
    monkeypatch.setattr(gateway, "_executor", lambda auth, bind, **kwargs: transport)
    monkeypatch.setattr(mechanism_domains, "_quote", lambda **kw:
        {"allowed": True, "cost_usd": prices.get(str(kw["model"].header.entity_id), 0.0)})
    authorized, service = human(world)
    assert authorized["chat_scope"]["is_owner"] is False and authorized["chat_scope"]["uses_owner_runtime"] is False
    context, models, tasks = authorized["context"], [], []
    env = SimpleNamespace(world=world, authorized=authorized, context=context, service=service,
                          models=models, tasks=tasks, calls=calls, prices=prices, transport=transport)
    for index, name in enumerate(("Slow", "Fast")):
        policy = service._put(context, {"fixture": "router isolated personas", "synthetic": True})
        persona = service._ensure(context, c.Persona, uuid4(), uuid4(), policy, display_name=name,
            profile=service._put(context, {"description": "Disposable Router test Persona"}))
        service._walk(context, persona, "active")
        model = service.connect(context=context, payload={"label": name, "provider": "deepseek",
            "model": "deepseek-v4-flash", "api_key": "router-fixture-not-owner-secret",
            "persona_id": str(persona.header.entity_id)}, idempotency_key="router-connect-" + name)
        models.append(model)
        check = gateway.mutate(authorized, "models", model["id"], "test",
            {"payload": {}, "idempotency_key": "router-connect-check-" + name})
        completed(env, check["id"])
        for sample in range(3):
            task = gateway.mutate(authorized, "models", model["id"], "task", {
                "payload": {"rubric_key": "json_arithmetic", "input_text": json.dumps([sample, 2, 3])},
                "idempotency_key": "router-observation-" + name + str(sample)})
            completed(env, task["id"])
            if index == 0: tasks.append(task["id"])
    env.source_id = tasks[-1]
    return env


def tick(env):
    worker = "router-acceptance-worker"
    job = durable.claim_worker_job(local_worker._root(), worker_id=worker)
    if job is None: return None
    def heartbeat():
        assert durable.heartbeat_worker_job(local_worker._root(), job["worker_job_id"], worker_id=worker)
    result = gateway.execute_worker(job,
        lambda: durable.worker_cancel_requested(local_worker._root(), job["worker_job_id"], worker_id=worker), heartbeat)
    durable.finish_worker_job(local_worker._root(), job["worker_job_id"], result, worker_id=worker)
    return job, result


def completed(env, task_id):
    for _ in range(20):
        tick(env)
        task = env.service.task_detail(context=env.context, task_id=task_id)
        if task["status"] in {"succeeded", "review", "blocked", "failed", "cancelled"}:
            return task
    pytest.fail("disposable Router task did not finish")


def preview(env, *, identity=None, **payload):
    return gateway.mutate(env.authorized, "router", identity or env.source_id, "preview", {
        "payload": payload, "idempotency_key": "router-preview-boundary"})


def apply(env, shown, *, key="router-explicit-apply", identity=None, **changes):
    body = {"payload": {"preview_ref": shown["preview_ref"]},
            "expected_revision": shown["source_revision"], "idempotency_key": key, **changes}
    return gateway.mutate(env.authorized, "router", identity or env.source_id, "apply", body)


def test_read_and_shadow_preview_preserve_source_tasks_and_perform_no_dispatch(routed):
    env = routed
    before = {row.ref() for row in env.service._all(env.context, EntityKind.TASK)}
    calls = list(env.calls)
    view = gateway.list_domain(env.authorized, "router", identity=env.source_id)
    assert view["actual_choice"]["decided_by"] == "request" and view["actions"] == ["preview"]
    shown = preview(env)
    assert shown["mode"] == "shadow" and shown["applied"] is False
    assert shown["selected_model_id"] == env.models[1]["id"]
    assert shown["effective_model_id"] == env.models[0]["id"] and shown["would_change"] is True
    assert shown["actions"] == ["apply"] and shown["creates_new_task"] is True
    assert shown["dispatch_performed"] is False and shown["permission_granted"] is False
    assert shown["quality_ranking"] is False and all(row["quality_score"] is None for row in shown["candidates"])
    assert before == {row.ref() for row in env.service._all(env.context, EntityKind.TASK)} and calls == env.calls
    saved = env.service._json(env.context, shown["preview_ref"])
    assert saved["source_task"]["revision"] == shown["source_revision"]
    assert saved["selection_sha256"] == shown["selection_sha256"]


def test_explicit_same_preview_runs_selected_executor_and_records_link_before_queue(routed):
    env = routed
    shown = preview(env)
    baseline = list(env.calls)
    applied = apply(env, shown)
    assert applied["applied"] and applied["started_model_id"] == env.models[1]["id"]
    assert applied["actual_choice"]["routing_applied"] and applied["actual_choice"]["execution_observed"] is False
    task = env.service._get(env.context, EntityKind.TASK, applied["started_task_id"])
    checkpoint = env.service._json(env.context, task.checkpoint)
    assert checkpoint["routing"]["preview_ref"] == shown["preview_ref"]
    queued = worker_router.get("wj_aw_model_" + task.header.entity_id.hex, workspace_id=env.world.workspace)
    assert queued["status"] == "queued" and baseline == env.calls
    result = completed(env, applied["started_task_id"])
    assert result["status"] == "succeeded" and result["human_review"]["status"] == "pending"
    assert env.calls[len(baseline):] == [env.models[1]["id"]]
    actual = gateway.list_domain(env.authorized, "router", identity=result["id"])["actual_choice"]
    assert actual["decided_by"] == "router_v2" and actual["routing_applied"] and actual["execution_observed"]
    assert actual["source_task_id"] == env.source_id and actual["preview_ref"] == shown["preview_ref"]
    assert actual["actual_model"] == "router-acceptance-transport-double" and actual["external_call"] is False
    execution = execution_v2.projection(env.service, env.context, result["id"])
    assert execution["status"] == "succeeded" and execution["deviation_count"] == 0
    # The new routing identity is also accepted by the existing strict
    # non-trading evidence reader; it does not become an application proof.
    source = result_handoff.verified_model_data(env.service, env.context, result["id"])
    assert source["kind"] == "verified_model_data" and source["parent_task"]["entity_id"] == result["id"]
    assert source["provenance"]["live_provider_confirmed"] is False
    assert source["provenance"]["professional_quality_assessed"] is False
    # Retry is an idempotent read of the completed result, never another call.
    again = apply(env, shown)
    assert again["started_task_id"] == result["id"] and again["replayed"]
    assert env.calls[len(baseline):] == [env.models[1]["id"]]


@pytest.mark.parametrize("bad", [{}, {"candidate_model_ids": []}, {"selected_model_id": "forged"}])
def test_apply_without_an_issued_preview_is_denied_before_new_work(routed, bad):
    env = routed
    before = {row.ref() for row in env.service._all(env.context, EntityKind.TASK)}
    with pytest.raises(ContractError, match="routing_explicit_preview_required"):
        gateway.mutate(env.authorized, "router", env.source_id, "apply", {
            "payload": bad, "idempotency_key": "router-no-preview", "expected_revision": 1})
    assert before == {row.ref() for row in env.service._all(env.context, EntityKind.TASK)}


@pytest.mark.parametrize("change", ["source_revision", "source_id", "artifact_hash", "foreign_scope", "changed_choice",
    "new_observation", "active_flag", "persona_suspended", "model_revision", "capability_revoked", "executor_origin"])
def test_changed_preview_or_fresh_authority_fails_closed(routed, monkeypatch, change):
    env = routed
    shown = preview(env)
    options = {}
    if change == "source_revision": options["expected_revision"] = shown["source_revision"] + 1
    if change == "source_id": options["identity"] = env.tasks[0]
    if change == "artifact_hash": shown["preview_ref"]["sha256"] = "0" * 64
    if change == "foreign_scope": shown["preview_ref"]["scope"]["workspace_id"] = "ws_foreign_router"
    if change == "changed_choice": env.prices[env.models[1]["id"]] = .01
    if change == "new_observation":
        extra = gateway.mutate(env.authorized, "models", env.models[1]["id"], "task", {
            "payload": {"rubric_key": "json_arithmetic", "input_text": "[42,8,1]"}, "idempotency_key": "router-new-observation"})
        completed(env, extra["id"])
    if change == "active_flag": monkeypatch.setenv(gateway.live_gateway.MECHANISMS_ENV, env.world.mechanisms("AI_EXECUTION_V2", "AI_ROUTER_SHADOW_V2"))
    if change == "persona_suspended":
        persona = env.service._get(env.context, EntityKind.PERSONA, env.models[1]["persona_id"])
        env.service._change(env.context, persona, "suspended")
    if change == "model_revision":
        model = env.service._get(env.context, EntityKind.MODEL, env.models[1]["id"])
        env.service._change(env.context, model, profile=env.service._put(env.context,
            {**env.service._json(env.context, model.profile), "label": "New current identity"}))
    if change == "capability_revoked":
        account_auth.set_user_permission(OWNER_ID, env.world.scope["user_id"], "ai_pro_models", False)
    if change == "executor_origin": monkeypatch.setenv(test_executor.ENV, env.world.workspace)
    before = {row.ref() for row in env.service._all(env.context, EntityKind.TASK)}
    calls = list(env.calls)
    with pytest.raises(ContractError): apply(env, shown, **options)
    assert before == {row.ref() for row in env.service._all(env.context, EntityKind.TASK)} and calls == env.calls


def test_changed_source_after_preview_is_not_silently_reexecuted(routed):
    env = routed
    source = gateway.mutate(env.authorized, "models", env.models[0]["id"], "task", {
        "payload": {"rubric_key": "json_arithmetic", "input_text": "[123,2,3]"}, "idempotency_key": "router-pending-source"})
    shown = preview(env, identity=source["id"])
    env.service.cancel(context=env.context, task_id=source["id"])
    with pytest.raises(ContractError, match="routing_source_changed"):
        apply(env, shown, identity=source["id"])


def test_queue_rechecks_router_flag_before_provider_and_preserves_history(routed, monkeypatch):
    env = routed
    applied = apply(env, preview(env))
    calls = list(env.calls)
    monkeypatch.setenv(gateway.live_gateway.MECHANISMS_ENV, env.world.mechanisms("AI_EXECUTION_V2", "AI_ROUTER_SHADOW_V2"))
    result = completed(env, applied["started_task_id"])
    assert result["status"] == "blocked" and result["error_code"] == "routing_disabled"
    assert calls == env.calls
    view = gateway.list_domain(env.authorized, "router", identity=result["id"])
    assert view["actual_choice"]["routing_applied"] is True and view["actual_choice"]["execution_observed"] is False


def test_queue_rechecks_executor_origin_before_provider(routed, monkeypatch):
    env = routed
    shown = preview(env)
    assert shown["synthetic"] is False and all(row["execution_origin"] == "configured_provider" for row in shown["candidates"])
    applied = apply(env, shown)
    calls = list(env.calls)
    monkeypatch.setenv(test_executor.ENV, env.world.workspace)
    result = completed(env, applied["started_task_id"])
    assert result["status"] == "blocked" and result["error_code"] == "routing_preview_changed"
    assert calls == env.calls


def test_retry_with_another_preview_cannot_reuse_the_same_task_key(routed):
    env = routed
    first = preview(env)
    created = apply(env, first, key="x" * 120)
    next_preview = preview(env)
    with pytest.raises(ContractError, match="routing_apply_idempotency_conflict"):
        apply(env, next_preview, key="x" * 120)
    assert apply(env, first, key="x" * 120)["started_task_id"] == created["started_task_id"]


@pytest.mark.parametrize("legacy", [False, True])
def test_named_test_observations_never_qualify_real_routing(routed, monkeypatch, legacy):
    env = routed
    monkeypatch.setenv(test_executor.ENV, env.world.workspace)
    monkeypatch.setattr(gateway, "_executor", lambda auth, bind, **kwargs: test_executor.execute)
    original_clean, original_put = ModelService._clean_receipt, ModelService._put
    if legacy:
        def old_clean(result, checkpoint):
            receipt = original_clean(result, checkpoint)
            if receipt.get("executor") == test_executor.EXECUTOR:
                receipt = {**receipt, "source": "provider_response", "synthetic": False}
                receipt.pop("source_kind", None)
            return receipt
        def old_put(self, context, value):
            if value.get("evaluator") == "independent_local_evidence_verifier" and value.get("executor") == test_executor.EXECUTOR:
                value = {**value, "synthetic": False}
                value.pop("source_kind", None)
            return original_put(self, context, value)
        monkeypatch.setattr(ModelService, "_clean_receipt", staticmethod(old_clean))
        monkeypatch.setattr(ModelService, "_put", old_put)
    before = preview(env)["candidates"]
    extra = gateway.mutate(env.authorized, "models", env.models[1]["id"], "task", {
        "payload": {"rubric_key": "json_arithmetic", "input_text": "[999,8,4]"}, "idempotency_key": "router-synthetic-observation"})
    result = completed(env, extra["id"])
    assert result["synthetic"] is True
    after = preview(env)["candidates"]
    assert [row["sample_size"] for row in before] == [row["sample_size"] for row in after] == [3, 3]
    assert all(len(row["evidence"]) == 3 for row in after)
