"""Correlated Development application chain, never a professional model benchmark.

Only disposable account/connection bootstrap is reused. No result, Decision,
Contribution, Outcome or Evaluation is constructed by this harness. SF Chat
ingress, the normal durable worker, explicit review and domain APIs produce them.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import durable, local_worker
from app.ai_lab import chief_agent
from app.ai_control_center import coordinator, domain_gateway as gateway, test_executor, scheduler, live_gateway
from app.ai_control_center.states import EntityKind, ContractError
from app.ai_control_center import contracts as c, automation_authority
from app.ai_control_center import delegation
from tests.test_agent_world_automation_revocation import world, human  # noqa: F401
from tests.test_agent_world_coordinator import scenario  # noqa: F401


def _drain():
    ledger = []
    for _ in range(60):
        job = durable.claim_worker_job(local_worker._root(), worker_id="canonical-program")
        if job is None:
            return ledger
        identity = job["worker_job_id"]
        def heartbeat():
            assert durable.heartbeat_worker_job(local_worker._root(), identity, worker_id="canonical-program")
        def cancelled():
            return durable.worker_cancel_requested(local_worker._root(), identity, worker_id="canonical-program")
        result = local_worker._execute(job, heartbeat=heartbeat, cancelled=cancelled)
        durable.finish_worker_job(local_worker._root(), identity, result, worker_id="canonical-program")
        ledger.append({"job_id": identity, "kind": job["kind"], "payload": job["payload"], "result": result})
    pytest.fail("canonical worker did not settle")


def _mutate(env, domain, identity, action, payload, revision=None, key=None):
    return gateway.mutate(env.authorized, domain, identity, action, {
        "payload": payload, "expected_revision": revision,
        "idempotency_key": key or "canonical-" + action + "-" + identity})


@pytest.fixture
def completed_program(scenario):
    env = scenario
    env.world.monkeypatch.setenv(live_gateway.MECHANISMS_ENV,
        env.world.mechanisms("AI_DELEGATION_V2", "AI_EXECUTION_V2", "AI_SCHEDULER_V1", "AI_ROUTER_SHADOW_V2"))
    env.authorized = gateway.access(env.world.scope)
    env.service = gateway.models(env.authorized)
    payload = dict(env.payload)
    goal = payload.pop("goal")
    reply = chief_agent.handle_message("Координатор: " + goal + "\n" + json.dumps(payload),
        source="app", mirror_to_telegram=False, conversation_id="canonical-program-chat",
        scope=env.world.scope, request_id="canonical-program-request")
    assert reply["status"] == "clarification_required" and reply["actions"] == []
    payload["selection"] = {"id": "1", "plan_sha256": reply["clarification"]["plan_sha256"]}
    reply = chief_agent.handle_message("Координатор: " + goal + "\n" + json.dumps(payload),
        source="app", mirror_to_telegram=False, conversation_id="canonical-program-chat",
        scope=env.world.scope, request_id="canonical-program-confirmed-request")
    assert reply["ok"] is True and "task_id" in reply, reply
    env.ledger = {"synthetic": True, "professional_quality_assessed": False,
                  "conversation_id": reply["conversation_id"], "root_task_id": reply["task_id"],
                  "coordinator_id": reply["coordinator_id"], "jobs": _drain()}
    control = coordinator.projection(env.authorized, env.service, reply["coordinator_id"])
    assert control["stage"] == "awaiting_approval"
    plan = _mutate(env, "automation", control["id"], "preview_commission", {})
    opened = _mutate(env, "automation", control["id"], "approve_commission", {
        "approved_plan_sha256": plan["approved_plan_sha256"], "max_call_cost_usd": 0.0,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
    env.ledger["jobs"] += _drain()
    graph = coordinator.projection(env.authorized, env.service, control["id"])["graph"]
    tasks = [reply["task_id"], *[node["task_id"] for node in graph["nodes"]]]
    env.ledger["task_ids"] = tasks
    for identity in tasks:
        detail = gateway.task_detail(env.authorized, identity)["task"]
        assert detail["display_status"] == "awaiting_review"
        _mutate(env, "tasks", identity, "review_result", {
            "decision": "accept", "comment": "SYNTHETIC · проверен механизм, не качество модели.",
            "source_sha256": detail["human_review"]["source_sha256"]}, detail["revision"])
    env.ledger["jobs"] += _drain()
    detail = gateway.task_detail(env.authorized, graph["id"])["task"]
    _mutate(env, "tasks", graph["id"], "review_result", {
        "decision": "accept", "comment": "SYNTHETIC · подтверждена передача фактов.",
        "source_sha256": detail["human_review"]["source_sha256"]}, detail["revision"])
    env.ledger["jobs"] += _drain()
    assert gateway.task_detail(env.authorized, graph["id"])["task"]["display_status"] == "completed"
    env.ledger["graph_id"] = opened["graph"]["id"]
    return env


def test_canonical_chat_to_typed_evidence_memory_and_process_consent(completed_program, tmp_path):
    env = completed_program
    ctx, service = env.context, env.service
    outcomes = [row for row in service._all(ctx, EntityKind.OUTCOME)
                if str(row.task.entity_id) in env.ledger["task_ids"] and row.status == "verified"]
    assert len(outcomes) == 4
    correlations = set()
    for outcome in outcomes:
        task = service._get(ctx, EntityKind.TASK, outcome.task.entity_id)
        execution = service._get(ctx, EntityKind.EXECUTION, outcome.execution.entity_id)
        decision = service._get(ctx, EntityKind.DECISION, execution.decision.entity_id)
        assert execution.status == "succeeded" and decision.status == "approved"
        assert decision.intent.entity_id == task.intent.entity_id
        assert task.header.correlation_id == outcome.header.correlation_id == execution.header.correlation_id
        correlations.add(str(task.header.correlation_id))
        assert any(row.task.entity_id == task.header.entity_id
                   for row in service._all(ctx, EntityKind.CONTRIBUTION))
    assert len(correlations) == 1
    env.ledger["correlation_id"] = correlations.pop()
    for kind in (EntityKind.CONTRIBUTION, EntityKind.DECISION, EntityKind.EXECUTION, EntityKind.EVALUATION):
        rows = list(service._all(ctx, kind))
        assert rows, kind
        env.ledger[kind.value + "_ids"] = [str(row.header.entity_id) for row in rows]
    env.ledger["outcome_ids"] = [str(row.header.entity_id) for row in outcomes]
    detail = service.task_detail(context=ctx, task_id=env.ledger["root_task_id"])
    assert detail["reputation"]["decision_performance"]["sample_size"] == 1
    assert detail["evaluation"]["synthetic"] is True
    routing = _mutate(env, "router", env.ledger["root_task_id"], "preview", {})
    assert routing["status"] == "blocked" and routing["selected_model_id"] is None
    assert routing["dispatch_performed"] is False and routing["applied"] is False
    assert routing["candidates"] and all(not row["eligible"] for row in routing["candidates"])
    env.ledger["router"] = {"status": "fail_closed_preview", "real_provider_switch": "OWNER_KEY_REQUIRED",
                            "decision_sha256": routing["decision_sha256"]}
    memory = _mutate(env, "memory", "new", "create", {
        "title": "SYNTHETIC · итог проверки цепочки", "content": "Диагностический результат: сумма 34.",
        "purpose": "canonical-program-diagnostic", "retention_days": 1,
        "memory_class": "verified_lesson", "verified_outcome_id": env.ledger["outcome_ids"][0]})["item"]
    memory = _mutate(env, "memory", memory["id"], "promote", {"reason": "Явное тестовое согласие"}, memory["revision"])["item"]
    assert memory["status"] == "active"
    env.ledger["memory_id"] = memory["id"]
    analysis = gateway.list_domain(env.authorized, "routines")["process_intelligence"]
    candidate = next(row for row in analysis["candidates"] if row["source_kind"] == "development_diagnostic")
    assert candidate["synthetic"] and candidate["real_work_observations"] == 0
    routine = _mutate(env, "routines", candidate["id"], "propose", {"source_sha256": candidate["source_sha256"]})["item"]
    assert routine["status"] == "proposed" and routine["automation_enabled"] is False
    routine = _mutate(env, "routines", routine["id"], "accept", {}, routine["revision"])["item"]
    assert routine["status"] == "accepted" and routine["automation_enabled"] is False
    env.ledger["routine_id"] = routine["id"]
    schedule_request = {"source_domain": "routines", "source_task_id": env.ledger["root_task_id"],
        "model_id": env.models[0]["id"], "rubric_key": "json_arithmetic", "input_text": env.payload["input_text"],
        "schedule": {"local_start": (datetime.now(timezone.utc)-timedelta(seconds=1)).replace(tzinfo=None).isoformat(timespec="seconds"),
                     "timezone": "UTC", "interval_seconds": 3600, "occurrences": 2, "grace_seconds": 300},
        "max_call_cost_usd": 0.0}
    proposed = _mutate(env, "automation", routine["id"], "propose", schedule_request, routine["revision"], "canonical-schedule")
    assert proposed["approved"] is False
    assert proposed["plan"]["synthetic"] is True
    scheduled = _mutate(env, "automation", routine["id"], "enable", schedule_request, routine["revision"], "canonical-schedule")
    assert scheduled["approved"] is True
    scheduler.scan_due(env.authorized, env.service)
    env.ledger["jobs"] += _drain()
    state = scheduler.tick(env.authorized, env.service, scheduled["id"])
    assert state["status"] == "waiting"
    assert state["synthetic"] is True and state["occurrences"][0]["synthetic"] is True
    assert len(state["occurrences"]) == 2 and state["occurrences"][0]["task_id"]
    assert state["occurrences"][1]["task_id"] is None
    env.ledger["schedule_id"] = scheduled["id"]
    env.ledger["occurrence_task_id"] = state["occurrences"][0]["task_id"]
    repeated = service.task_detail(context=ctx, task_id=env.ledger["occurrence_task_id"])
    assert repeated["executor"] == test_executor.EXECUTOR and repeated["external_call"] is False
    assert repeated["evaluation"]["synthetic"] is True
    repeated_task = service._get(ctx, EntityKind.TASK, env.ledger["occurrence_task_id"])
    with env.world.monkeypatch.context() as patch:
        patch.delenv(test_executor.ENV)
        with pytest.raises(ContractError, match="schedule_executor_mode_changed"):
            scheduler.validate_execution(service, ctx, repeated_task, service._json(ctx, repeated_task.checkpoint))
    before_jobs = {row["worker_job_id"] for row in durable.list_worker_jobs(local_worker._root())}
    before_tasks = {str(row.header.entity_id) for row in service._all(ctx, EntityKind.TASK)}
    revoked = _mutate(env, "automation", scheduled["id"], "revoke", {"grant_ref": scheduled["grant_ref"]})
    assert revoked["revoked"] is True
    due = datetime.fromisoformat(state["occurrences"][1]["due_at"])
    with pytest.raises(ContractError, match="automation_approval_revoked"):
        scheduler.tick(env.authorized, service, scheduled["id"], now=due)
    scan = scheduler.scan_due(env.authorized, service, now=due)
    denial = next(row for row in scan if row["id"] == scheduled["id"])
    assert denial["status"] == "blocked" and denial["dispatch_performed"] is False
    assert before_jobs == {row["worker_job_id"] for row in durable.list_worker_jobs(local_worker._root())}
    assert before_tasks == {str(row.header.entity_id) for row in service._all(ctx, EntityKind.TASK)}
    history = scheduler.projection(env.authorized, service, scheduled["id"])
    assert history["occurrences"][0]["task_id"] == env.ledger["occurrence_task_id"]
    assert history["occurrences"][1]["task_id"] is None
    env.ledger["revocation"] = {"revoked": True, "next_occurrence_due_at": due.isoformat(),
                                "reason_code": denial["reason_code"], "new_jobs": 0, "new_tasks": 0,
                                "previous_result_retained": True}
    calendar_analysis = gateway.list_domain(env.authorized, "calendar")["process_intelligence"]
    suggestion = next(row for row in calendar_analysis["candidates"] if row["source_kind"] == "development_diagnostic")
    calendar = _mutate(env, "calendar", suggestion["id"], "propose", {"source_sha256": suggestion["source_sha256"]})["item"]
    dismissed = _mutate(env, "calendar", calendar["id"], "dismiss", {}, calendar["revision"])["item"]
    assert dismissed["status"] == "dismissed"
    after_dismiss = gateway.list_domain(env.authorized, "calendar")["process_intelligence"]
    assert not any(row["source_kind"] == "development_diagnostic" for row in after_dismiss["candidates"])
    assert any(row.get("domain") == "calendar" and row.get("reason") == "cooldown" for row in after_dismiss["suppressed"])
    env.ledger["declined_calendar_proposal"] = {"id": calendar["id"], "status": "dismissed", "cooldown_enforced": True}
    # A persisted evidence ledger, not a made-up external report or production write.
    (tmp_path / "canonical-program-evidence.json").write_text(json.dumps(env.ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    _diagnostic_process_security_boundaries(env, env.world.monkeypatch)


def _diagnostic_process_security_boundaries(env, monkeypatch):
    from app.ai_control_center.process_intelligence import ProcessIntelligence
    process = ProcessIntelligence(gateway.domains(env.authorized, env.service.repository), env.service)
    outcome = next(row for row in env.service._all(env.context, EntityKind.OUTCOME)
                   if str(row.task.entity_id) == env.ledger["root_task_id"])
    for mode in ("off", "foreign_workspace", "preview"):
        with monkeypatch.context() as patch:
            if mode == "off":
                patch.delenv(test_executor.ENV)
            elif mode == "foreign_workspace":
                patch.setenv(test_executor.ENV, "ws_other_unrelated_workspace")
            else:
                patch.setenv("STRATFORGE_PREVIEW_SANDBOX", "1")
                patch.setenv("STRATFORGE_PREVIEW_ID", "canonicalpreview123456")
                patch.setenv("NTA_ENABLE_TEST_AUTH", "1")
            with pytest.raises(ContractError, match="process_source_synthetic"):
                process._metadata(env.context, outcome.header.entity_id)
    real_detail = env.service.task_detail
    with monkeypatch.context() as patch:
        patch.setattr(env.service, "task_detail", lambda **kwargs: {**real_detail(**kwargs), "executor": "forged-executor"})
        with pytest.raises(ContractError, match="process_source_unverified"):
            process._metadata(env.context, outcome.header.entity_id)
    _, _, plan = delegation.controller(env.service, env.context, env.ledger["graph_id"], delegation.SOURCE)
    for changed in ({**plan, "root_source": {**plan["root_source"], "source_proof_sha256": "0" * 64}},
                    {**plan, "root_kind": "unverified-client-input"}):
        with pytest.raises(ContractError, match="automation_plan_invalid"):
            automation_authority._execution_provenance(env.context, changed, "delegation", 0, service=env.service)


@pytest.mark.parametrize("mode", ["allowed", "off", "foreign", "preview", "production", "paid", "delegation", "malformed"])
def test_synthetic_schedule_authority_is_exact_zero_cost_development_opt_in(monkeypatch, mode):
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_PREVIEW_SANDBOX", "1" if mode == "preview" else "0")
    monkeypatch.setenv("STRATFORGE_PREVIEW_ID", "canonicalpreview123456" if mode == "preview" else "")
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    monkeypatch.setenv(test_executor.ENV, "" if mode == "off" else "ws_other_scope" if mode == "foreign" else "ws_diagnostic_scope")
    context = SimpleNamespace(scope=c.TenantScope(environment=c.Environment.PRODUCTION if mode == "production"
                              else c.Environment.DEVELOPMENT, workspace_id="ws_diagnostic_scope"))
    args = (context, {"synthetic": "true" if mode == "malformed" else True},
            "delegation" if mode == "delegation" else "schedule", .01 if mode == "paid" else 0.0)
    if mode == "allowed":
        automation_authority._execution_provenance(*args)
    else:
        with pytest.raises(ContractError, match="automation_plan_invalid"):
            automation_authority._execution_provenance(*args)
