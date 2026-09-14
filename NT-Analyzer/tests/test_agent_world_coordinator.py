"""New goals through real disposable auth/grants/worker, never real providers.

The explicit local test executor supplies every answer. Its receipts, graph,
contributions and checks are real persisted test records, not live model QA.
No finished graph, fabricated application report or pre-approved grant is seeded.
"""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app import durable, local_worker, worker_router
from app.ai_lab import chief_agent
from app.ai_control_center import contracts as c, coordinator, delegation, domain_gateway, result_handoff, test_executor
from app.ai_control_center import automation_authority, mechanism_domains, model_chat, task_review
from app.ai_control_center.model_service import _id
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_automation_revocation import world, human


@pytest.fixture
def scenario(world, tmp_path, monkeypatch):
    assert world.capability(True)
    monkeypatch.setenv(test_executor.ENV, world.workspace)
    registry = tmp_path / "coordinator-chat"
    registry.mkdir()
    monkeypatch.setattr(chief_agent.paths, "REGISTRY_DIR", registry)
    monkeypatch.setattr(chief_agent.paths, "PROJECT_ROOT", tmp_path)
    authorized, service = human(world)
    context = authorized["context"]
    models = []
    for index in range(4):
        policy = service._put(context, {"fixture": "disposable coordinator personas", "synthetic": True})
        persona = service._ensure(context, c.Persona, uuid4(), uuid4(), policy,
            display_name="Проверяющий " + str(index), profile=service._put(context, {"description": "Disposable test profile"}))
        service._walk(context, persona, "active")
        models.append(service.connect(context=context, payload={"label": "Local test connection " + str(index),
            "provider": "deepseek", "model": "deepseek-v4-flash", "api_key": "fixture-key-not-an-owner-secret",
            "persona_id": str(persona.header.entity_id)}, idempotency_key="coordinator-test-connect-" + str(index)))
    payload = {"goal": "Проверить сводку переданных чисел", "input_text": "[17,-4,12,9]",
        "coordinator_model_id": models[0]["id"], "target_model_ids": [row["id"] for row in models[1:]],
        "parent_indices": [-1, 0, 1], "max_depth": 3}
    return SimpleNamespace(world=world, authorized=authorized, service=service, context=context, payload=payload, models=models)


def request(env, action, identity="new", payload=None, key="coordinator-owner-new-goal"):
    # Same gateway that handles the application's real HTTP domain route.
    payload = dict(env.payload if payload is None else payload)
    if action == "commission":
        # This compatibility fixture makes the human's meaning explicit.
        # Production callers never send these internal operation identifiers.
        operation = payload.pop("operation", "verify_fact_transfer")
        if operation not in delegation.OPERATIONS:
            return coordinator.commission(env.authorized, env.service, {**payload, "operation": operation}, key)
        preview = coordinator.plan_request(env.authorized, env.service, payload)
        choice = preview["choices"][0 if operation == "verify_fact_transfer" else 1]
        if not choice["available"]:
            raise ContractError(choice["reason"])
        payload["selection"] = {"id": choice["id"], "plan_sha256": preview["plan_sha256"]}
    return domain_gateway.mutate(env.authorized, "automation", identity, action,
        {"payload": payload, "idempotency_key": key})


def tick(env):
    worker = "coordinator-disposable-worker"
    job = durable.claim_worker_job(local_worker._root(), worker_id=worker)
    if job is None: return None
    def heartbeat():
        assert durable.heartbeat_worker_job(local_worker._root(), job["worker_job_id"], worker_id=worker)
    def cancelled():
        return durable.worker_cancel_requested(local_worker._root(), job["worker_job_id"], worker_id=worker)
    result = domain_gateway.execute_worker(job, cancelled, heartbeat)
    if job["kind"] == "agent_world_model" and not job["payload"].get("phase"):
        auth = domain_gateway.worker_authority(job)
        model_service = domain_gateway.models(auth)
        # The shared worker hook may already do this; it is idempotent.
        coordinator.after_model(auth, model_service, job["payload"]["task_id"])
    durable.finish_worker_job(local_worker._root(), job["worker_job_id"], result, worker_id=worker)
    return job, result


def root_ready(env):
    view = request(env, "commission")
    assert view["root_status"] == "ready" and view["stage"] == "ready" and view["graph"] is None
    for _ in range(4):
        tick(env)
        current = coordinator.projection(env.authorized, env.service, view["id"])
        if current["stage"] == "awaiting_approval": return current
    pytest.fail("root model did not produce a checked result")


def approved(env):
    view = root_ready(env)
    plan = request(env, "preview_commission", view["id"], {})
    assert plan["approved"] is False and plan["dispatches"] == 0
    grant = {"approved_plan_sha256": plan["approved_plan_sha256"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), "max_call_cost_usd": 0.0}
    return view, plan, grant, request(env, "approve_commission", view["id"], grant)


def finish(env, graph_id):
    for _ in range(30):
        tick(env)
        state = delegation.projection(env.authorized, env.service, graph_id)
        if state["status"] == "review": return state
    pytest.fail("bounded graph did not complete")


def test_new_goal_api_real_grant_worker_three_levels_contributions_and_local_provenance(scenario):
    env = scenario
    view, plan, grant, started = approved(env)
    context = env.context
    graph = finish(env, started["graph"]["id"])
    assert [node["depth"] for node in graph["nodes"]] == [1, 2, 3]
    assert graph["root_kind"] == result_handoff.DATA_KIND and graph["review_state"] == "awaiting_required_reviews"
    assert graph["result"]["facts"] == {"count": "4", "sum": "34", "min": "-4", "max": "17", "mean": "8.5"}
    assert graph["result"]["provenance"]["local_test_receipts"] == 4
    assert graph["result"]["provenance"]["confirmed_external_receipts"] == 0
    assert graph["result"]["provenance"]["provider_receipts"] == 0
    assert graph["result"]["human_accepted"] is False
    assert graph["synthetic"] is True and graph["result"]["synthetic"] is True
    assert len({row["contribution_id"] for row in graph["result"]["contributions"]}) == 3
    parent = env.service._get(context, EntityKind.TASK, view["root_task_id"])
    for node in graph["nodes"]:
        contribution = node["contribution"]
        assert contribution["operation"] == "verify_fact_transfer"
        assert contribution["synthetic"] is True
        assert node["operation_role"] == "fact_transfer_checker" and node["agent_role_key"] == "model_response"
        assert contribution["produces_new_analysis"] is False and all(check["passed"] for check in contribution["checks"])
        child = env.service._get(context, EntityKind.TASK, node["task_id"])
        assert child.dependencies == (parent.ref(),) and child.header.correlation_id == parent.header.correlation_id
        checkpoint = env.service._json(context, child.checkpoint)
        receipt = env.service._json(context, checkpoint["receipt"])
        assert receipt["executor"] == test_executor.EXECUTOR and receipt["external_call"] is False
        parent = child
    commission = coordinator.projection(env.authorized, env.service, view["id"])
    assert commission["status"] == "review" and commission["stage"] == "awaiting_required_reviews"
    saved = coordinator.completion(env.authorized, env.service, graph["id"])
    assert saved["envelope"]["status"] == "awaiting_review"
    assert saved["envelope"]["source_kind"] == "bounded_delegation_result"
    assert saved["envelope"]["synthetic"] is True and saved["envelope"]["verification"]["synthetic"] is True
    assert "Локальных тестовых ответов: 4" in saved["envelope"]["text"]
    history = domain_gateway.access(env.world.scope, read_only=True)
    assert coordinator.validate_history_envelope(history, saved["envelope"]) == saved
    # Closing neither the root nor the graph constitutes an owner's review.
    assert not saved["envelope"]["verification"]["human_accepted"]
    assert request(env, "approve_commission", view["id"], grant)["graph"]["id"] == graph["id"]
    rows = list(env.service._all(context, EntityKind.TASK))
    assert len([row for row in rows if env.service._json(context, row.checkpoint).get("receipt")]) == 4


def test_preview_does_not_grant_or_queue_descendants_and_explicit_hash_required(scenario):
    env = scenario
    view = root_ready(env)
    before = len(list(env.service._all(env.context, EntityKind.TASK)))
    one = request(env, "preview_commission", view["id"], {})
    two = request(env, "preview_commission", view["id"], {})
    assert one == two and len(list(env.service._all(env.context, EntityKind.TASK))) == before
    with pytest.raises(ContractError, match="explicit_approval_required"):
        request(env, "approve_commission", view["id"], {})
    with pytest.raises(ContractError, match="plan_changed"):
        request(env, "approve_commission", view["id"], {"approved_plan_sha256": "0" * 64,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), "max_call_cost_usd": 0.0})
    assert coordinator.projection(env.authorized, env.service, view["id"])["graph"] is None


def test_repeated_new_goal_is_idempotent_and_cannot_replace_target_or_data(scenario):
    env = scenario
    first = request(env, "commission")
    assert request(env, "commission")["root_task_id"] == first["root_task_id"]
    for change in ({"goal": "Другая цель"}, {"input_text": "[1,2,3]"}, {"parent_indices": [-1, -1, 0]}):
        with pytest.raises(ContractError, match="idempotency_conflict"):
            request(env, "commission", payload={**env.payload, **change})
    row = worker_router.get("wj_aw_model_" + first["root_task_id"].replace("-", ""), workspace_id=env.world.workspace)
    assert row["status"] == "queued" and row["attempts"] == 0


@pytest.mark.parametrize("change", [{"parent_indices": [1, -1, 0]}, {"parent_indices": [-1, -1, -1]}, {"max_depth": 2}])
def test_goal_rejects_cycle_fanout_and_depth_before_model_dispatch(scenario, change):
    with pytest.raises(ContractError, match="delegation_"):
        request(scenario, "commission", payload={**scenario.payload, **change})
    assert not list(scenario.service._all(scenario.context, EntityKind.TASK))


def test_existing_verified_nontrading_root_can_propose_without_weakening_application_seal(scenario):
    env = scenario
    view = root_ready(env)
    proof = result_handoff.verified_model_data(env.service, env.context, view["root_task_id"])
    assert proof["checks"] and proof["provenance"]["mode"] == "local_test_executor"
    with pytest.raises(ContractError, match="handoff_verified_source_required"):
        result_handoff._seal(env.service, env.context, view["root_task_id"], env.models[1]["id"])
    request_payload = {"target_model_ids": [env.models[1]["id"]], "max_depth": 1}
    proposal = request(env, "preview_delegation", view["root_task_id"], request_payload, key="standalone-data-root")
    assert proposal["plan"]["root_kind"] == result_handoff.DATA_KIND
    with pytest.raises(ContractError, match="explicit_approval_required"):
        request(env, "delegate", view["root_task_id"], request_payload, key="standalone-data-root")


def test_withdrawn_capability_blocks_queued_child_and_restart(scenario):
    env = scenario
    view, _, _, started = approved(env)
    graph_id = started["graph"]["id"]
    source = worker_router.get("wj_aw_delegate_" + graph_id.replace("-", "") + "_0", workspace_id=env.world.workspace)
    auth = domain_gateway.worker_authority(source)
    assert auth["automation"]
    assert env.world.capability(None) is False
    with pytest.raises(ContractError, match="automation_entitlement_required"): auth["admit"]()
    with pytest.raises(ContractError, match="automation_entitlement_required"): domain_gateway.worker_authority(source)
    assert len([task for task in env.service._all(env.context, EntityKind.TASK)
        if env.service._json(env.context, task.checkpoint).get("receipt")]) == 1


@pytest.mark.parametrize("expired", [False, True])
def test_unclaimed_or_expired_worker_cannot_create_child(scenario, monkeypatch, expired):
    env = scenario
    _, _, _, started = approved(env)
    identity = "wj_aw_delegate_" + started["graph"]["id"].replace("-", "") + "_0"
    source = worker_router.get(identity, workspace_id=env.world.workspace)
    if expired:
        from app.ai_control_center import followup_chat
        for _ in range(4):
            source = durable.claim_worker_job(local_worker._root(), worker_id="expired-coordinator-worker")
            if source["worker_job_id"] == identity: break
            assert source["payload"].get("phase") == "delivery"
            result = domain_gateway.execute_worker(source, lambda: False, lambda: durable.heartbeat_worker_job(
                local_worker._root(), source["worker_job_id"], worker_id="expired-coordinator-worker"))
            durable.finish_worker_job(local_worker._root(), source["worker_job_id"], result, worker_id="expired-coordinator-worker")
        assert source["worker_job_id"] == identity
        # Advance only the claim guard's clock; no wall-clock sleep or DB seed.
        monkeypatch.setattr(followup_chat, "time", SimpleNamespace(time=lambda: float(source["locked_until"]) + 1))
    auth = domain_gateway.worker_authority(source)
    with pytest.raises(ContractError, match="claim"):
        delegation.execute(auth, domain_gateway.models(auth), source, lambda: False, lambda: None)
    assert not any(env.service._json(env.context, task.checkpoint).get("delegation")
        for task in env.service._all(env.context, EntityKind.TASK))


def test_real_grant_call_ceiling_and_foreign_model_are_rechecked(scenario):
    env = scenario
    _, _, _, started = approved(env)
    graph_id = started["graph"]["id"]
    source = worker_router.get("wj_aw_delegate_" + graph_id.replace("-", "") + "_0", workspace_id=env.world.workspace)
    auth = domain_gateway.worker_authority(source)
    service = domain_gateway.models(auth)
    controller = service._get(auth["context"], EntityKind.TASK, graph_id)
    args = {"context": auth["context"], "controller": controller.ref(), "grant_ref": started["grant_ref"],
        "operation": "provider_transmit", "model_id": env.models[1]["id"]}
    with pytest.raises(ContractError, match="automation_budget_denied"):
        service.mechanism_admit(**args, estimated_cost_usd=0.01)
    with pytest.raises(ContractError, match="automation_model_not_approved"):
        service.mechanism_admit(**{**args, "model_id": env.models[0]["id"]}, estimated_cost_usd=0.0)
    assert not any(env.service._json(env.context, task.checkpoint).get("delegation")
        for task in env.service._all(env.context, EntityKind.TASK))


def test_fresh_service_restart_continues_same_queue_and_single_receipt_per_node(scenario):
    env = scenario
    view, _, grant, started = approved(env)
    graph_id = started["graph"]["id"]
    # Drop all service/request handles after dispatching the first child.
    tick(env)
    env.authorized, env.service = human(env.world)
    env.context = env.authorized["context"]
    assert request(env, "approve_commission", view["id"], grant)["graph"]["id"] == graph_id
    finished = finish(env, graph_id)
    assert finished["status"] == "review"
    assert len([task for task in env.service._all(env.context, EntityKind.TASK)
        if env.service._json(env.context, task.checkpoint).get("receipt")]) == 4
    sources = [worker_router.get("wj_aw_model_" + item.replace("-", ""), workspace_id=env.world.workspace)
        for item in [view["root_task_id"], *[node["task_id"] for node in finished["nodes"]]]]
    assert all(row["attempts"] == 1 and row["status"] == "succeeded" for row in sources)


def test_cancel_commission_retains_root_receipt_and_stops_descendants(scenario):
    env = scenario
    view, _, _, started = approved(env)
    stopped = request(env, "cancel", view["id"], {})
    assert stopped["status"] == "cancelled" and stopped["graph"]["status"] == "cancelled"
    proof = result_handoff.verified_model_data(env.service, env.context, view["root_task_id"])
    assert proof["provenance"]["mode"] == "local_test_executor"
    with pytest.raises(ContractError, match="coordinator_stopped"):
        request(env, "preview_commission", view["id"], {})
    job = worker_router.get("wj_aw_delegate_" + started["graph"]["id"].replace("-", "") + "_0", workspace_id=env.world.workspace)
    assert job["status"] == "cancelled"


def test_failed_root_verification_never_grants_graph_and_history_is_kept(scenario, monkeypatch):
    env = scenario
    monkeypatch.setattr(test_executor, "_answer", lambda prompt: '{"count":999,"sum":0,"min":0,"max":0,"mean":0}')
    view = request(env, "commission")
    tick(env)
    root = env.service.task_detail(context=env.context, task_id=view["root_task_id"])
    assert root["status"] == "review" and root["evaluation"]["passed"] is False
    with pytest.raises(ContractError, match="handoff_verified_data_required"):
        request(env, "preview_commission", view["id"], {})
    assert coordinator.projection(env.authorized, env.service, view["id"])["graph"] is None
    assert request(env, "commission")["root_task_id"] == view["root_task_id"]
    retained = env.service.task_detail(context=env.context, task_id=view["root_task_id"])
    assert retained["result_text"] == root["result_text"] and retained["evaluation"] == root["evaluation"]


def test_evaluation_and_receipt_links_rechecked_not_a_green_dto(scenario, monkeypatch):
    env = scenario
    view = root_ready(env)
    identity = view["root_task_id"]
    outcome = env.service._get(env.context, EntityKind.OUTCOME, _id(env.context, "outcome:" + identity))
    proof = env.service._json(env.context, outcome.verification)
    changed = env.service._put(env.context, {**proof, "checks": [{"key": "fabricated", "passed": True}]})
    with pytest.raises(ContractError, match="finalized_record_immutable"):
        env.service._change(env.context, outcome, verification=changed)
    # Even an injected corrupt reader cannot turn a green aggregate DTO into
    # evidence. The real repository already rejected the attempted overwrite.
    read = env.service._json
    monkeypatch.setattr(env.service, "_json", lambda context, ref: {**proof, "checks": [{"key": "fabricated", "passed": True}]}
        if ref == outcome.verification else read(context, ref))
    with pytest.raises(ContractError, match="data_evidence_changed"):
        result_handoff.verified_model_data(env.service, env.context, identity)
    with pytest.raises(ContractError): coordinator.preview(env.authorized, env.service, view["id"])


def test_normal_chat_starts_new_goal_with_exact_source_message(scenario):
    env = scenario
    payload = {key: value for key, value in env.payload.items() if key != "goal"}
    preview = coordinator.plan_request(env.authorized, env.service, env.payload)
    payload["selection"] = {"id": "1", "plan_sha256": preview["plan_sha256"]}
    message = "Координатор: " + env.payload["goal"] + "\n" + json.dumps(payload)
    reply = coordinator.try_chat(message, scope=env.authorized["chat_scope"], conversation_id="coordinator-new-goal-chat",
        request_id="coordinator-explicit-chat-goal", source="app")
    assert reply["ok"] and reply["coordinator_id"]
    task = env.service.task_detail(context=env.context, task_id=reply["task_id"])
    rows = chief_agent.read_jsonl(chief_agent._conversation_file(task["conversation_id"], scope=env.authorized["chat_scope"]))
    assert any(row.get("message_id") == task["message_id"] and row.get("content") == message and row.get("role") == "user" for row in rows)
    assert coordinator.try_chat(message, scope={}, conversation_id="ignored", request_id="ignored", source="telegram") is None


def review_result(env, detail, decision="accept", **changes):
    return domain_gateway.mutate(env.authorized, "tasks", detail["id"], "review_result", {
        "expected_revision": changes.pop("expected_revision", detail["revision"]),
        "idempotency_key": "coordinator-explicit-review-" + detail["id"],
        "payload": {"decision": decision, "comment": "Проверено отдельно владельцем",
            "source_sha256": detail["human_review"].get("source_sha256"), **changes}})


def accept_individuals(env, graph):
    for identity in [graph["root_task"]["entity_id"], *[node["task_id"] for node in graph["nodes"]]]:
        detail = env.service.task_detail(context=env.context, task_id=identity)
        assert review_result(env, detail)["human_review"]["status"] == "accepted"
    return delegation.projection(env.authorized, env.service, graph["id"])


def test_existing_review_route_requires_individuals_then_records_exact_aggregate_once(scenario):
    env = scenario
    _, _, _, started = approved(env)
    graph = finish(env, started["graph"]["id"])
    initial = coordinator.completion(env.authorized, env.service, graph["id"])
    assert graph["human_review"]["status"] == "blocked" and graph["actions"] == []
    assert len(graph["human_review"]["required_reviews"]) == 4
    assert all(row["status"] == "pending" for row in graph["human_review"]["required_reviews"])
    with pytest.raises(ContractError, match="task_review_result_required"):
        review_result(env, graph)
    automatic = {row.header.entity_id for row in env.service._all(env.context, EntityKind.EVALUATION)}
    source_tasks = {str(row.header.entity_id): row.ref() for row in env.service._all(env.context, EntityKind.TASK)}
    original_outcome = env.service._get(env.context, EntityKind.OUTCOME, graph["outcome_id"])
    graph = accept_individuals(env, graph)
    assert graph["review_state"] == "awaiting_review" and graph["actions"] == ["review_result"]
    ready = coordinator.completion(env.authorized, env.service, graph["id"])
    assert ready["event_id"] != initial["event_id"] and ready["envelope"]["status"] == "awaiting_review"
    for change in ({"source_sha256": initial["envelope"]["verification"]["human_review"]["source_sha256"]},
                   {"expected_revision": graph["revision"] - 1}):
        with pytest.raises(ContractError, match="task_review_"): review_result(env, graph, **change)
    accepted = review_result(env, graph)
    review = accepted["human_review"]
    assert accepted["review_state"] == "accepted" and accepted["human_accepted"]
    assert review["status"] == "accepted" and review["origin"] == "explicit_human_review"
    assert review["quality_claim"] is False and review["source_sha256"] == graph["human_review"]["source_sha256"]
    assert review_result(env, accepted)["deduplicated"] is True
    with pytest.raises(ContractError, match="already_recorded"): review_result(env, accepted, "reject")
    evaluations = list(env.service._all(env.context, EntityKind.EVALUATION))
    reviews = [row for row in evaluations if row.header.entity_id not in automatic]
    assert len(reviews) == 5 and all(row.rubric_key == task_review.RUBRIC for row in reviews)
    assert all(row.header.created_by == env.context.actor for row in reviews)
    assert {row.header.entity_id for row in evaluations if row.rubric_key != task_review.RUBRIC} == automatic
    assert source_tasks == {str(row.header.entity_id): row.ref() for row in env.service._all(env.context, EntityKind.TASK)}
    assert env.service._get(env.context, EntityKind.OUTCOME, graph["outcome_id"]) == original_outcome
    evaluation = env.service._get(env.context, EntityKind.EVALUATION, review["evaluation_id"])
    proof = env.service._json(env.context, evaluation.evidence)
    snapshot = env.service._json(env.context, proof["source_snapshot"])
    assert len(snapshot["sources"]) == 4 and len(snapshot["result"]["contributions"]) == 3
    assert snapshot["authority"]["device_confirmed"] and snapshot["errors"] == []
    completed = coordinator.completion(env.authorized, env.service, graph["id"])
    assert completed["event_id"] != ready["event_id"] and completed["envelope"]["status"] == "completed"
    assert completed["envelope"]["verification"]["human_accepted"] is True
    assert completed["envelope"]["provenance"]["rating_effect"] == "none"
    assert completed["envelope"]["provenance"]["local_test_receipts"] == 4
    history = domain_gateway.access(env.world.scope, read_only=True)
    assert coordinator.validate_history_envelope(history, completed["envelope"]) == completed


def test_individual_rejection_remains_visible_and_blocks_aggregate_acceptance(scenario):
    env = scenario
    _, _, _, started = approved(env)
    graph = finish(env, started["graph"]["id"])
    root = env.service.task_detail(context=env.context, task_id=graph["root_task"]["entity_id"])
    assert review_result(env, root, "reject")["human_review"]["status"] == "rejected"
    graph = delegation.projection(env.authorized, env.service, graph["id"])
    assert graph["human_review"]["required_reviews"][0]["status"] == "rejected"
    assert graph["human_review"]["blocked_reason"] == "delegation_required_reviews_not_accepted"
    with pytest.raises(ContractError, match="task_review_result_required"): review_result(env, graph)
    assert graph["result"]["verified_fact_transfer"] is True and graph["human_accepted"] is False


def test_revoked_grant_blocks_aggregate_acceptance_without_erasing_individual_reviews(scenario):
    env = scenario
    _, _, _, started = approved(env)
    graph = accept_individuals(env, finish(env, started["graph"]["id"]))
    assert graph["human_review"]["status"] == "pending"
    automation_authority.revoke(env.authorized, env.service, started["grant_ref"])
    with pytest.raises(ContractError, match="task_review_result_required"): review_result(env, graph)
    graph = delegation.projection(env.authorized, env.service, graph["id"])
    assert graph["human_review"]["blocked_reason"] == "automation_approval_revoked"
    assert all(row["status"] == "accepted" for row in graph["human_review"]["required_reviews"])
    assert not graph["human_accepted"]


@pytest.mark.parametrize("change", ["revoked", "flag_off", "connection", "cancelled"])
def test_current_truth_distinguishes_execution_authority_from_accepted_evidence(scenario, change):
    env = scenario
    _, _, _, started = approved(env)
    graph = accept_individuals(env, finish(env, started["graph"]["id"]))
    accepted = review_result(env, graph)
    record = env.service._get(env.context, EntityKind.EVALUATION, accepted["human_review"]["evaluation_id"])
    if change == "revoked": automation_authority.revoke(env.authorized, env.service, started["grant_ref"])
    elif change == "flag_off":
        from app.ai_control_center import live_gateway
        env.world.monkeypatch.setenv(live_gateway.MECHANISMS_ENV, env.world.mechanisms("AI_EXECUTION_V2"))
    elif change == "connection": env.service.disconnect(context=env.context, model_id=env.models[0]["id"])
    else: delegation.cancel(env.authorized, env.service, graph["id"])
    history = domain_gateway.access(env.world.scope, read_only=True)
    historical_service = domain_gateway.history_models(history)
    stale = delegation.projection(history, historical_service, graph["id"])
    if change in {"revoked", "flag_off"}:
        assert stale["human_review"]["status"] == "accepted" and stale["human_accepted"]
        assert stale["human_review"]["source_sha256"] == accepted["human_review"]["source_sha256"]
        assert stale["human_review"]["current_execution_authority"]["blocked_reason"]
    else:
        assert stale["human_review"]["status"] == "stale" and not stale["human_accepted"]
        assert stale["human_review"]["recorded_status"] == "accepted"
    assert stale["human_review"]["evaluation_id"] == str(record.header.entity_id)
    assert env.service._get(env.context, EntityKind.EVALUATION, record.header.entity_id) == record
    assert env.service._json(env.context, record.evidence)["source_sha256"] == accepted["human_review"]["source_sha256"]
    if change in {"connection", "cancelled"}:
        with pytest.raises(ContractError, match="task_review_"): review_result(env, stale)


def test_test_executor_opt_in_is_for_new_work_not_historical_receipts(scenario, monkeypatch):
    env = scenario
    view = root_ready(env)
    task = env.service._get(env.context, EntityKind.TASK, view["root_task_id"])
    checkpoint = env.service._json(env.context, task.checkpoint)
    receipt = env.service._json(env.context, checkpoint["receipt"])
    assert receipt["source"] == "local_test_executor" and receipt["synthetic"] is True
    assert checkpoint["synthetic"] is False  # real server-created task, not a Preview task
    monkeypatch.setenv(test_executor.ENV, "")
    history = domain_gateway.access(env.world.scope, read_only=True)
    service = domain_gateway.history_models(history)
    proof = result_handoff.verified_model_data(service, history["context"], view["root_task_id"])
    assert proof["synthetic"] is True and proof["provenance"]["live_provider_confirmed"] is False
    assert coordinator.projection(history, service, view["id"])["root_synthetic"] is True
    with pytest.raises(ContractError, match="test_workspace_opt_in_required"):
        request(env, "preview_commission", view["id"], {})
    assert coordinator.projection(history, service, view["id"])["graph"] is None


@pytest.mark.parametrize("change", [
    {"executor": "untrusted-name", "actual_model": "untrusted-name"},
    {"executor": None}, {"external_call": True}, {"request_sha256": "0" * 64},
    {"source": "provider_response"}, {"cost_usd": 0.01}, {"paid_call": True}])
def test_arbitrary_synthetic_or_changed_receipt_never_becomes_a_data_root(scenario, monkeypatch, change):
    env = scenario
    view = root_ready(env)
    task = env.service._get(env.context, EntityKind.TASK, view["root_task_id"])
    checkpoint = env.service._json(env.context, task.checkpoint)
    read = env.service._json
    original = read(env.context, checkpoint["receipt"])
    monkeypatch.setattr(env.service, "_json", lambda context, ref: {**original, **change}
        if ref == checkpoint["receipt"] else read(context, ref))
    with pytest.raises(ContractError, match="handoff_data_"):
        result_handoff.verified_model_data(env.service, env.context, view["root_task_id"])


def test_historical_named_local_false_marker_is_projected_without_rewriting(scenario, monkeypatch):
    env = scenario
    # Emulate the previous producer on a normal new isolated request. No ready
    # graph, completed state or source receipt is inserted directly into DB.
    from app.ai_control_center.model_service import ModelService
    clean = ModelService._clean_receipt
    def legacy_receipt(*args, **kwargs):
        receipt = clean(*args, **kwargs)
        receipt = {**receipt, "source": "provider_response", "synthetic": False}
        receipt.pop("source_kind", None)
        return receipt
    monkeypatch.setattr(ModelService, "_clean_receipt", staticmethod(legacy_receipt))
    view = root_ready(env)
    task = env.service._get(env.context, EntityKind.TASK, view["root_task_id"])
    checkpoint = env.service._json(env.context, task.checkpoint)
    original = env.service._json(env.context, checkpoint["receipt"])
    proof = result_handoff.verified_model_data(env.service, env.context, view["root_task_id"])
    assert original["synthetic"] is False and proof["synthetic"] is True
    old = {**proof, "synthetic": False}
    assert result_handoff.same_data_source(old, proof)
    assert not result_handoff.same_data_source({**old, "facts_sha256": "0" * 64}, proof)
    assert env.service._json(env.context, checkpoint["receipt"]) == original


def _events(env):
    from app.ai_control_center.repositories import PageRequest
    cursor, rows = None, []
    while True:
        page = env.service.repository.events.list(context=env.context, page=PageRequest(limit=100, cursor=cursor))
        rows.extend(page.items)
        if not page.next_cursor: return rows
        cursor = page.next_cursor


def test_related_completion_is_read_only_and_ack_uses_a_real_scoped_event(scenario, monkeypatch):
    env = scenario
    _, _, _, started = approved(env)
    graph = finish(env, started["graph"]["id"])
    root = env.service.task_detail(context=env.context, task_id=graph["root_task"]["entity_id"])
    reviewed = review_result(env, root)
    events = _events(env)
    tasks = {row.ref() for row in env.service._all(env.context, EntityKind.TASK)}
    saved = coordinator.related_completions(env.authorized, env.service, root["id"])
    assert saved["blocked"] == [] and len(saved["deliveries"]) == 1
    completion = saved["deliveries"][0]
    review_event = next(event for event in events if event.subject.entity_id == UUID(reviewed["human_review"]["evaluation_id"]))
    assert UUID(completion["event_id"]) == review_event.event_id
    assert events == _events(env) and tasks == {row.ref() for row in env.service._all(env.context, EntityKind.TASK)}
    assert coordinator.related_completions(env.authorized, env.service, graph["id"]) == saved
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", lambda *a, **kw: {"ok": True})
    values = {key: completion[key] for key in ("task_id", "event_id", "checkpoint_sha256")}
    with pytest.raises(ContractError, match="coordinator_delivery_unconfirmed"):
        coordinator.deliver(env.authorized, env.service, **values, events=SimpleNamespace(acknowledge=lambda **kw: False))
    result = coordinator.deliver(env.authorized, env.service, **values, events=env.service.repository.events)
    assert result["status"] == "delivered"
    assert env.service.repository.events.is_acknowledged(context=env.context,
        consumer=coordinator.delivery_consumer(graph["id"]), event_id=review_event.event_id)
    assert not env.service.repository.events.is_acknowledged(context=env.context,
        consumer=coordinator.delivery_consumer(uuid4()), event_id=review_event.event_id)
    assert coordinator.deliver(env.authorized, env.service, **values, events=env.service.repository.events)["replayed"] is True


def test_two_graphs_share_root_review_event_but_not_chat_delivery_identity(scenario):
    env = scenario
    root = root_ready(env)
    graphs = []
    for index in (1, 2):
        key = "coordinator-separate-approved-graph-" + str(index)
        payload = {"target_model_ids": [env.models[index]["id"]], "max_depth": 1}
        proposed = request(env, "preview_delegation", root["root_task_id"], payload, key=key)
        approved_graph = request(env, "delegate", root["root_task_id"], {
            **payload, "approved_plan_sha256": proposed["approved_plan_sha256"],
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "max_call_cost_usd": 0.0}, key=key)
        graphs.append(finish(env, approved_graph["id"]))
    detail = env.service.task_detail(context=env.context, task_id=root["root_task_id"])
    reviewed = review_result(env, detail)
    matches = coordinator.related_completions(env.authorized, env.service, root["root_task_id"])
    assert matches["blocked"] == [] and len(matches["deliveries"]) == 2
    deliveries = matches["deliveries"]
    review_event = next(event for event in _events(env)
        if event.subject.entity_id == UUID(reviewed["human_review"]["evaluation_id"]))
    assert {UUID(row["event_id"]) for row in deliveries} == {review_event.event_id}
    assert len({row["envelope"]["request_id"] for row in deliveries}) == 2
    assert len({row["envelope"]["conversation_id"] for row in deliveries}) == 1
    message_ids = set()
    for row in deliveries:
        result = coordinator.deliver(env.authorized, env.service,
            **{key: row[key] for key in ("task_id", "event_id", "checkpoint_sha256")},
            events=env.service.repository.events)
        assert result["status"] == "delivered" and result["replayed"] is False
        assert env.service.repository.events.is_acknowledged(context=env.context,
            consumer=coordinator.delivery_consumer(row["task_id"]), event_id=review_event.event_id)
        messages = chief_agent.read_jsonl(chief_agent._conversation_file(
            row["envelope"]["conversation_id"], scope=env.authorized["chat_scope"]))
        message = next(message for message in messages
            if message.get("request_id") == chief_agent._agent_world_request_key(row["envelope"]["request_id"]))
        assert message["actions"][0]["task_id"] == row["task_id"]
        assert message["actions"][0]["status"] == "awaiting_review"
        assert message["actions"][0]["synthetic"] is True
        message_ids.add(message["message_id"])
    assert len(message_ids) == 2


def _breakdown(env, values="[10,20,30,40,50,60,70,80]", parents=(-1, -1), depth=1):
    env.payload = {**env.payload, "goal": "Разобрать участки переданных чисел",
        "input_text": values, "operation": "numeric_breakdown",
        "target_model_ids": [row["id"] for row in env.models[1:3]],
        "parent_indices": list(parents), "max_depth": depth}
    return env


def test_second_operation_gives_each_specialist_its_own_slice_and_a_new_answer(scenario):
    """Two specialists, two different slices, two different answers.

    The distinguishing property against `verify_fact_transfer` is that no child
    restates what it was handed: each computes statistics over its own part of
    the parent's data, and the same independent verifier grades every one.
    """
    env = _breakdown(scenario)
    view, plan, grant, started = approved(env)
    graph = finish(env, started["graph"]["id"])

    assert [node["depth"] for node in graph["nodes"]] == [1, 1]
    assert graph["result"]["operation"] == "numeric_breakdown"
    assert graph["result"]["produces_new_analysis"] is True

    answers = []
    for node in graph["nodes"]:
        contribution = node["contribution"]
        assert contribution["operation"] == "numeric_breakdown"
        assert contribution["produces_new_analysis"] is True
        assert node["operation_role"] == "segment_analyst"
        assert all(check["passed"] for check in contribution["checks"])
        child = env.service._get(env.context, EntityKind.TASK, node["task_id"])
        checkpoint = env.service._json(env.context, child.checkpoint)
        assert checkpoint["spec"]["rubric_key"] == "json_arithmetic"
        answers.append(checkpoint["spec"]["input"])

    # Disjoint halves that together are the whole root array, in order.
    assert answers == [[10, 20, 30, 40], [50, 60, 70, 80]]
    assert answers[0] != answers[1], "a breakdown whose children share a slice is a restatement"

    # Every child was still reviewed and the aggregate still waits for a human.
    assert graph["review_state"] == "awaiting_required_reviews"
    assert graph["result"]["human_accepted"] is False
    assert graph["result"]["professional_quality_assessed"] is False
    assert graph["result"]["provenance"]["provider_receipts"] == 0


def test_a_breakdown_that_cannot_be_split_is_refused_while_it_is_still_a_proposal(scenario):
    """Four values cannot become two slices the rubric would accept."""
    env = _breakdown(scenario, values="[17,-4,12,9]")
    with pytest.raises(ContractError) as refused:
        request(env, "commission")
    assert refused.value.code == "delegation_segment_too_small"
    assert not list(env.service._all(env.context, EntityKind.DECISION))


def test_an_operation_outside_the_closed_set_is_refused(scenario):
    """The caller names a class of work; it cannot invent one."""
    env = scenario
    env.payload = {**env.payload, "operation": "summarise_however_you_like"}
    with pytest.raises(ContractError) as refused:
        request(env, "commission")
    assert refused.value.code == "coordinator_operation_unsupported"


def test_the_default_operation_is_unchanged_when_none_is_named(scenario):
    """An existing caller that names no operation keeps fact transfer."""
    env = scenario
    assert "operation" not in env.payload
    view = request(env, "commission")
    control = env.service._get(env.context, EntityKind.TASK, view["id"])
    plan = env.service._json(env.context, env.service._json(env.context, control.checkpoint)["plan"])
    assert plan["operation"] == "verify_fact_transfer"
    assert all(node["operation"] == "verify_fact_transfer" for node in plan["nodes"])
    assert all(node["produces_new_analysis"] is False for node in plan["nodes"])
