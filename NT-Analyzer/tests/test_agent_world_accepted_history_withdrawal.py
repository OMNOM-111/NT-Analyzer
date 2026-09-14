"""AW-FINAL-1: historical acceptance is not permission to execute again.

Real disposable graph/worker records; deterministic diagnostic executor only.
"""
import pytest
from copy import deepcopy

from app import durable, local_worker
from app.ai_control_center import coordinator, delegation, domain_gateway
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_coordinator import (
    scenario, world, approved, finish, accept_individuals, review_result, request,
)


def test_accepted_completed_graph_survives_later_automation_withdrawal(scenario):
    env = scenario
    _, _, _, started = approved(env)
    graph = accept_individuals(env, finish(env, started["graph"]["id"]))
    accepted = review_result(env, graph)
    before = coordinator.completion(env.authorized, env.service, graph["id"])
    review_id = accepted["human_review"]["evaluation_id"]
    record = env.service._get(env.context, EntityKind.EVALUATION, review_id)
    assert accepted["human_accepted"] and before["envelope"]["status"] == "completed"

    assert env.world.capability(None) is False
    history = domain_gateway.access(env.world.scope, read_only=True)
    service = domain_gateway.history_models(history)
    after = delegation.projection(history, service, graph["id"])
    assert after["human_review"]["status"] == "accepted"
    assert after["human_accepted"] and after["review_state"] == "accepted"
    assert after["human_review"]["source_sha256"] == accepted["human_review"]["source_sha256"]
    assert after["human_review"]["evaluation_id"] == review_id
    assert all(row["status"] == "accepted" for row in after["human_review"]["required_reviews"])
    assert service._get(history["context"], EntityKind.EVALUATION, review_id) == record
    delivered = coordinator.validate_history_envelope(history, before["envelope"])
    assert before["envelope"]["scope"]["capabilities"]["ai_automation"] is True
    assert delivered["envelope"]["scope"]["capabilities"]["ai_automation"] is False
    # Only refreshed transport authority may differ, not a byte of result proof.
    expected = deepcopy(before)
    expected["envelope"]["scope"]["capabilities"] = history["chat_scope"]["capabilities"]
    assert delivered == expected
    # Ignoring obsolete capabilities must not ignore tenant, session or evidence.
    for field, value in (("workspace_id", "foreign-workspace"), ("user_id", -1),
                         ("user_uuid", "00000000-0000-4000-8000-000000000001"),
                         ("auth_session_id", "foreign-session")):
        forged = deepcopy(before["envelope"])
        forged["scope"][field] = value
        with pytest.raises(ContractError, match="coordinator_delivery_evidence_changed"):
            coordinator.validate_history_envelope(history, forged)
    forged = deepcopy(before["envelope"])
    forged["verification"]["human_accepted"] = False
    with pytest.raises(ContractError, match="coordinator_delivery_evidence_changed"):
        coordinator.validate_history_envelope(history, forged)
    # The same browser authority cannot start more work after withdrawal.
    tasks = {row.header.entity_id for row in service._all(history["context"], EntityKind.TASK)}
    with pytest.raises(ContractError, match="automation_entitlement_required"):
        request(env, "commission", key="after-automation-withdrawal")
    assert {row.header.entity_id for row in service._all(history["context"], EntityKind.TASK)} == tasks


def test_automation_withdrawal_denies_claimed_graph_resume(scenario):
    env = scenario
    _, _, _, started = approved(env)
    identity = "wj_aw_delegate_" + started["graph"]["id"].replace("-", "") + "_0"
    for _ in range(4):
        job = durable.claim_worker_job(local_worker._root(), worker_id="withdrawal-resume")
        assert job is not None
        if job["worker_job_id"] == identity:
            break
        assert job["payload"].get("phase") == "delivery"
        result = domain_gateway.execute_worker(job, lambda: False, lambda: durable.heartbeat_worker_job(
            local_worker._root(), job["worker_job_id"], worker_id="withdrawal-resume"))
        durable.finish_worker_job(local_worker._root(), job["worker_job_id"], result, worker_id="withdrawal-resume")
    assert job["worker_job_id"] == identity
    worker = domain_gateway.worker_authority(job)
    assert worker["admit"]() is None
    tasks = {row.header.entity_id for row in env.service._all(env.context, EntityKind.TASK)}
    assert env.world.capability(None) is False
    with pytest.raises(ContractError, match="automation_entitlement_required"):
        worker["admit"]()
    with pytest.raises(ContractError, match="automation_entitlement_required"):
        domain_gateway.worker_authority(job)
    assert {row.header.entity_id for row in env.service._all(env.context, EntityKind.TASK)} == tasks
