"""Real gateway/worker/Chat hooks in disposable data, named local test executor.

No test-side after_model/reconcile/deliver calls. No external provider, paid
request, NinjaTrader report, owner credential or trading command is used.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app import durable, local_worker, worker_router
from app.ai_lab import chief_agent
from app.ai_control_center import coordinator, delegation, domain_gateway as gateway, model_chat
from tests.test_agent_world_automation_revocation import world, human
from tests.test_agent_world_coordinator import scenario, request


def tick():
    worker = "integrated-coordinator-acceptance"
    job = durable.claim_worker_job(local_worker._root(), worker_id=worker)
    if job is None:
        return None
    def heartbeat():
        assert durable.heartbeat_worker_job(local_worker._root(), job["worker_job_id"], worker_id=worker)
    def cancelled():
        return durable.worker_cancel_requested(local_worker._root(), job["worker_job_id"], worker_id=worker)
    result = gateway.execute_worker(job, cancelled, heartbeat)
    durable.finish_worker_job(local_worker._root(), job["worker_job_id"], result, worker_id=worker)
    return job, result


def drain(limit=50):
    jobs = []
    for _ in range(limit):
        item = tick()
        if item is None:
            return jobs
        jobs.append(item)
    raise AssertionError("bounded worker batch did not settle")


def test_gateway_worker_review_chat_is_one_lifecycle_without_manual_continuation(scenario):
    env = scenario
    created = request(env, "commission")
    first_jobs = drain()
    current = coordinator.projection(env.authorized, env.service, created["id"])
    assert current["stage"] == "awaiting_approval" and current["graph"] is None
    assert len([job for job, _ in first_jobs if job["kind"] == "agent_world_model" and not job["payload"].get("phase")]) == 1
    plan = request(env, "preview_commission", created["id"], {})
    accepted = request(env, "approve_commission", created["id"], {
        "approved_plan_sha256": plan["approved_plan_sha256"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), "max_call_cost_usd": 0.0})
    graph_id = accepted["graph"]["id"]
    jobs = drain()
    graph = delegation.projection(env.authorized, env.service, graph_id)
    assert graph["status"] == "review", graph
    assert graph["synthetic"] is True and graph["human_accepted"] is False
    assert len([job for job, _ in jobs if job["payload"].get("phase") == "coordinator_continue"]) == 3
    assert len([job for job, _ in jobs if job["kind"] == "agent_world_model" and not job["payload"].get("phase")]) == 3
    overview = gateway.enrich_overview(env.authorized)
    cards = {row["id"]: row for row in overview["tasks"]}
    assert cards[graph_id]["display_status"] == "awaiting_review"
    assert cards[graph_id]["result_received"] is True
    detail = gateway.task_detail(env.authorized, graph_id)
    assert detail["task"]["display_status"] == cards[graph_id]["display_status"]
    assert detail["human_review"]["blocked_reason"] == "delegation_required_reviews_pending"
    rows = chief_agent.read_jsonl(chief_agent._conversation_file(created["conversation_id"], scope=env.authorized["chat_scope"]))
    reports = [row for row in rows if any(action.get("source_kind") == "bounded_delegation_result" for action in row.get("actions") or [])]
    assert len(reports) == 1 and reports[0]["actions"][0]["status"] == "awaiting_review"
    assert reports[0]["actions"][0]["synthetic"] is True and reports[0]["fulfillment"] == "unset"
    for identity in [created["root_task_id"], *[node["task_id"] for node in graph["nodes"]]]:
        task = gateway.task_detail(env.authorized, identity)["task"]
        result = gateway.mutate(env.authorized, "tasks", identity, "review_result", {
            "payload": {"decision": "accept", "comment": "Явная тестовая проверка конкретного результата.",
                        "source_sha256": task["human_review"]["source_sha256"]},
            "expected_revision": task["revision"], "idempotency_key": "human-review-" + identity})
        assert result["chat_delivery"]["problems"] == [], result
    after_individual = drain()
    task = gateway.task_detail(env.authorized, graph_id)["task"]
    assert task["display_status"] == "awaiting_review" and task["human_review"]["status"] == "pending"
    review = {"payload": {"decision": "accept", "comment": "Принята точность передачи фактов, не качество модели.",
                          "source_sha256": task["human_review"]["source_sha256"]},
              "expected_revision": task["revision"], "idempotency_key": "aggregate-explicit-review"}
    gateway.mutate(env.authorized, "tasks", graph_id, "review_result", review)
    final_jobs = drain()
    assert gateway.task_detail(env.authorized, graph_id)["task"]["display_status"] == "completed"
    overview = gateway.enrich_overview(env.authorized)
    assert next(row for row in overview["tasks"] if row["id"] == graph_id)["display_status"] == "completed"
    rows = chief_agent.read_jsonl(chief_agent._conversation_file(created["conversation_id"], scope=env.authorized["chat_scope"]))
    reports = [row for row in rows if any(action.get("source_kind") == "bounded_delegation_result" for action in row.get("actions") or [])]
    assert reports[-1]["actions"][0]["status"] == "completed"
    assert reports[-1]["actions"][0]["verification"]["human_accepted"] is True
    assert reports[-1]["actions"][0]["verification"]["professional_quality_assessed"] is False
    for job, _ in [*after_individual, *final_jobs]:
        assert job["payload"].get("phase"), "a human review reran the provider"
    gateway.mutate(env.authorized, "tasks", graph_id, "review_result", review)
    assert drain() == []
