"""Bounded shared-integration negatives on disposable state only."""
from __future__ import annotations

import copy
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app import worker_router, local_worker
from app.ai_control_center import coordinator, coordinator_delivery, domain_gateway as gateway, test_executor
from app.ai_control_center import contracts as c
from app.ai_control_center import automation_authority, delegation, live_gateway
from app.ai_control_center import model_chat, task_review
from app.ai_lab import chief_agent
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_models import connected, response, setup, task
from tests.test_agent_world_model_provenance import synthetic_setup, synthetic_delivery
from tests.test_agent_world_model_delivery import delivery, _reports
from tests.test_agent_world_domain_gateway import ordinary
from tests.test_agent_world_live_gateway import owner, isolated_runtime
from tests.test_agent_world_automation_revocation import world, OWNER_ID


def _verified_test_connection(fixture):
    service, context, *_ = fixture
    model = connected(fixture)
    pending = service.test(context=context, model_id=model["id"], idempotency_key="verified-test-origin")
    service.execute(context=context, task_id=pending["id"])
    return model


def test_test_only_execution_field_tracks_exact_current_switch_without_claiming_connection(synthetic_setup, monkeypatch):
    service, context, *_ = synthetic_setup
    model = _verified_test_connection(synthetic_setup)
    on = service.model_detail(context=context, model_id=model["id"])
    assert on["connected"] is False and on["test_executor_verified"] is True
    assert on["can_execute_test_only"] is True and on["execution_available"] is True
    monkeypatch.setenv(test_executor.ENV, context.scope.workspace_id + "_foreign")
    off = service.model_detail(context=context, model_id=model["id"])
    assert off["connected"] is False and off["test_executor_verified"] is True
    assert off["can_execute_test_only"] is False and off["execution_available"] is False


def test_historical_synthetic_check_does_not_authorize_a_new_real_task(synthetic_setup, monkeypatch):
    service, context, *_ = synthetic_setup
    model = _verified_test_connection(synthetic_setup)
    monkeypatch.delenv(test_executor.ENV)
    sent = []
    service.executor = lambda **kwargs: sent.append(kwargs) or response()
    with pytest.raises(ContractError, match="model_real_connection_verification_required"):
        task(synthetic_setup, model, key="cannot-promote-test-to-real")
    assert not sent


@pytest.mark.parametrize("connection_test", [False, True])
def test_queued_test_request_cannot_fall_through_to_real_executor_after_switch_off(synthetic_setup, monkeypatch, connection_test):
    service, context, *_ = synthetic_setup
    model = connected(synthetic_setup)
    pending = (service.test(context=context, model_id=model["id"], idempotency_key="pinned-connection-check")
               if connection_test else task(synthetic_setup, model, key="pinned-test-task"))
    monkeypatch.delenv(test_executor.ENV)
    sent = []
    fresh = copy.copy(service)
    fresh.executor = lambda **kwargs: sent.append(kwargs) or response("CONNECTION_OK" if connection_test else response()["response"])
    result = fresh.execute(context=context, task_id=pending["id"])
    assert result["error_code"] == "model_test_executor_disabled"
    assert result["status"] == "blocked" and result["provider_result_received"] is False
    assert not sent


def test_explicit_new_connection_check_after_switch_off_remains_independently_admitted(synthetic_setup, monkeypatch):
    service, context, *_ = synthetic_setup
    model = _verified_test_connection(synthetic_setup)
    monkeypatch.delenv(test_executor.ENV)
    sent = []
    service.executor = lambda **kwargs: sent.append(kwargs) or response("CONNECTION_OK")
    pending = service.test(context=context, model_id=model["id"], idempotency_key="explicit-new-provider-check")
    result = service.execute(context=context, task_id=pending["id"])
    assert result["synthetic"] is False and result["status"] == "succeeded"
    current = service.model_detail(context=context, model_id=model["id"])
    assert current["connected"] is True and current["execution_available"] is True
    assert current["can_execute_test_only"] is False and len(sent) == 1


def test_saved_test_result_after_switch_off_is_history_not_new_transmit(synthetic_setup, monkeypatch):
    service, context, *_ = synthetic_setup
    model = connected(synthetic_setup)
    pending = task(synthetic_setup, model, key="saved-test-origin")
    complete = service.execute(context=context, task_id=pending["id"])
    monkeypatch.delenv(test_executor.ENV)
    service.executor = lambda **kwargs: pytest.fail("history repeated an executor")
    replayed = service.execute(context=context, task_id=pending["id"])
    assert replayed == complete and replayed["synthetic"] is True


def test_retry_keeps_original_test_pin_and_does_not_repair_queue_into_real(synthetic_setup, monkeypatch):
    service, context, _payload, _calls, queued, *_ = synthetic_setup
    model = connected(synthetic_setup)
    pending = service.test(context=context, model_id=model["id"], idempotency_key="repeat-pinned-test")
    checkpoint = service._json(context, service._get(context, EntityKind.TASK, pending["id"]).checkpoint)
    assert checkpoint["test_executor_request"] is True
    queue_count = len(queued)
    monkeypatch.delenv(test_executor.ENV)
    with pytest.raises(ContractError, match="model_test_executor_disabled"):
        service.test(context=context, model_id=model["id"], idempotency_key="repeat-pinned-test")
    unchanged = service._json(context, service._get(context, EntityKind.TASK, pending["id"]).checkpoint)
    assert unchanged == checkpoint and len(queued) == queue_count


def test_interrupted_intent_creation_never_downgrades_saved_test_pin(synthetic_setup, monkeypatch):
    service, context, *_ = synthetic_setup
    model = connected(synthetic_setup)
    original = service._ensure
    def interrupted(context, record_type, *args, **kwargs):
        if record_type is c.Task:
            raise OSError("disposable interruption before Task commit")
        return original(context, record_type, *args, **kwargs)
    monkeypatch.setattr(service, "_ensure", interrupted)
    with pytest.raises(OSError):
        service.test(context=context, model_id=model["id"], idempotency_key="partial-intent-test-pin")
    intent = next(service._all(context, EntityKind.INTENT))
    goal = service._json(context, intent.goal)
    assert goal["test_executor_request"] is True
    monkeypatch.setattr(service, "_ensure", original)
    monkeypatch.delenv(test_executor.ENV)
    with pytest.raises(ContractError, match="model_test_executor_disabled"):
        service.test(context=context, model_id=model["id"], idempotency_key="partial-intent-test-pin")
    assert service.repository.get(context=context, kind=EntityKind.TASK, entity_id=UUID(goal["task_id"])) is None
    assert service._json(context, service._get(context, EntityKind.INTENT, intent.header.entity_id).goal) == goal


@pytest.mark.parametrize("field", ["test_executor_request", "synthetic", "executor", "execution_available"])
def test_browser_payload_cannot_set_execution_origin(synthetic_setup, field):
    service, context, *_ = synthetic_setup
    model = connected(synthetic_setup)
    with pytest.raises(ContractError, match="model_task_field_invalid"):
        service.start_task(context=context, model_id=model["id"], payload={field: False},
                           idempotency_key="no-caller-executor-origin")


def test_switch_rechecked_after_admission_before_executor(synthetic_setup, monkeypatch):
    service, context, _payload, calls, *_ = synthetic_setup
    model = connected(synthetic_setup)
    pending = task(synthetic_setup, model, key="pin-transmit-admission-race")
    original = service.admit
    def admitted(current, operation, estimate):
        original(current, operation, estimate)
        if operation == "provider_transmit":
            monkeypatch.delenv(test_executor.ENV, raising=False)
    service.admit = admitted
    result = service.execute(context=context, task_id=pending["id"])
    assert result["error_code"] == "model_test_executor_disabled"
    assert result["provider_result_received"] is False and calls == []


def _minimal_authority(context):
    scope = {"workspace_id": context.scope.workspace_id, "user_uuid": str(context.user_uuid),
             "user_id": 12345, "auth_session_id": "disposable-confirmed-session"}
    return {"context": context, "chat_scope": scope, "source_scope": {"user_id": 12345}, "admit": lambda: None}


@pytest.mark.parametrize("failure", [OSError, sqlite3.OperationalError])
def test_persisted_review_remains_successful_when_chat_queue_is_unavailable(setup, monkeypatch, failure):
    service, context, *_ = setup
    pending = task(setup, key="review-before-chat-outage")
    detail = service.execute(context=context, task_id=pending["id"])
    authorized = _minimal_authority(context)
    monkeypatch.setattr(gateway, "models", lambda *_: service)
    monkeypatch.setattr(gateway, "history_models", lambda *_: service)
    monkeypatch.setattr(gateway, "domain_admission", lambda *_: lambda: None)
    monkeypatch.setattr(gateway, "refresh_authority", lambda value, **_: value)
    def unavailable(*args, **kwargs):
        raise failure("disposable queue error: must not expose raw detail")
    monkeypatch.setattr(gateway, "enqueue_model_delivery", unavailable)
    result = gateway.mutate(authorized, "tasks", detail["id"], "review_result", {
        "payload": {"decision": "accept", "source_sha256": detail["human_review"]["source_sha256"],
                    "comment": "Exact disposable result, not professional quality."},
        "expected_revision": detail["revision"], "idempotency_key": "review-delivery-outage"})
    assert result["human_review"]["status"] == "accepted"
    assert result["chat_delivery"]["status"] == "pending"
    assert "must not expose" not in str(result)
    assert service.task_detail(context=context, task_id=detail["id"])["human_review"]["status"] == "accepted"


def test_task_count_includes_projected_aggregate_without_changing_model_history(setup, monkeypatch):
    service, context, *_ = setup
    task(setup, key="count-model-and-aggregate")
    authorized = _minimal_authority(context)
    aggregate = {"id": str(uuid4()), "source_kind": "bounded_delegation_result", "updated_at": "2026-09-08T00:00:00Z"}
    monkeypatch.setattr(gateway, "models", lambda *_: service)
    monkeypatch.setattr(gateway, "domain_admission", lambda *_: lambda: None)
    monkeypatch.setattr(gateway, "_aggregate_tasks", lambda *_: [aggregate])
    result = gateway.list_domain(authorized, "tasks")
    assert len(result["items"]) == result["total"] == 2
    assert service.tasks(context=context)["total"] == 1


@pytest.mark.parametrize("mechanism,flag", [("execution_v2", "AI_EXECUTION_V2"),
    ("router", "AI_ROUTER_V2"), ("schedule", "AI_SCHEDULER_V1")])
def test_system_does_not_report_implemented_mechanism_as_missing(ordinary, mechanism, flag):
    result = gateway.system(gateway.access(ordinary.scope, read_only=True))
    item = next(row for row in result["items"] if row["id"] == mechanism)
    assert item["implemented"] is True
    assert item["enabled"] is result["flags"][flag]
    if not item["enabled"]:
        assert item["status"] == "disabled" and item["available"] is False


def test_system_selected_unconfigured_postgres_is_not_sqlite_or_missing_implementation(ordinary, monkeypatch):
    monkeypatch.setenv("STRATFORGE_AGENT_WORLD_STORAGE", "postgres")
    monkeypatch.delenv("STRATFORGE_AGENT_WORLD_DATABASE_URL", raising=False)
    result = gateway.system(gateway.access(ordinary.scope, read_only=True))
    item = next(row for row in result["items"] if row["id"] == "storage")
    assert item["implemented"] is True and item["available"] is False
    assert "postgres" in item["mode"].lower() and "sqlite" not in item["mode"].lower()
    assert "не реализован" not in item["note"]


def test_read_only_history_removes_execution_availability_not_saved_connection_fact(ordinary):
    authorized = gateway.access(ordinary.scope, read_only=True)
    authorized["session_read_only"] = True
    result = gateway.history_projection(authorized, {"items": [{"connected": True,
        "execution_available": True, "can_execute_test_only": True, "actions": ["task"]}]}, domain="models")
    assert result["items"][0] == {"connected": True, "execution_available": False,
        "can_execute_test_only": False, "actions": []}


@pytest.fixture
def claimed_coordinator(setup, monkeypatch):
    service, context, *_ = setup
    authorized = _minimal_authority(context)
    task_id, control_id = str(uuid4()), str(uuid4())
    source_id = "wj_aw_model_" + UUID(task_id).hex
    source = {"worker_job_id": source_id, "kind": "agent_world_model", "user_id": 12345,
        "workspace_id": context.scope.workspace_id, "payload": {"task_id": task_id,
        "scope": copy.deepcopy(authorized["chat_scope"]), "automation_controller_id": control_id}}
    payload = {"phase": coordinator_delivery.CONTINUE, "scope": copy.deepcopy(authorized["chat_scope"]),
        "source_worker_job_id": source_id, "task_id": task_id}
    job_id = coordinator_delivery._identity(coordinator_delivery.CONTINUE, task_id)
    job = {"worker_job_id": job_id, "kind": "agent_world_followup", "user_id": 12345,
        "workspace_id": context.scope.workspace_id, "payload": payload, "status": "running", "worker_id": "isolated-worker",
        "attempts": 1, "locked_until": time.time() + 60, "deadline_at": time.time() + 45, "cancel_requested": False}
    rows, progressed = {source_id: source, job_id: copy.deepcopy(job)}, []
    def get(identity, *, workspace_id):
        row = rows.get(identity)
        return copy.deepcopy(row) if row and row["workspace_id"] == workspace_id else None
    monkeypatch.setattr(worker_router, "get", get)
    monkeypatch.setattr(gateway, "models", lambda _: service)
    monkeypatch.setattr(coordinator, "after_model", lambda *args: progressed.append(args) or {"ok": True})
    monkeypatch.setattr(coordinator_delivery, "related", lambda *_: {"queued": [], "blocked": []})
    return SimpleNamespace(authorized=authorized, job=job, rows=rows, source_id=source_id, job_id=job_id, progressed=progressed)


@pytest.mark.parametrize("field", ["source_workspace", "source_user_id", "source_user_uuid", "source_session", "source_phase",
                                  "source_identity", "payload_scope", "payload_task", "job_user", "extra_payload"])
def test_coordinator_phase_rejects_foreign_or_reforged_source_before_progression(claimed_coordinator, field):
    env = claimed_coordinator
    source = env.rows[env.source_id]
    if field == "source_workspace": source["workspace_id"] += "_foreign"
    elif field == "source_user_id": source["user_id"] += 1
    elif field == "source_user_uuid": source["payload"]["scope"]["user_uuid"] = str(uuid4())
    elif field == "source_session": source["payload"]["scope"]["auth_session_id"] = "foreign-session"
    elif field == "source_phase": source["payload"]["phase"] = "delivery"
    elif field == "source_identity": source["worker_job_id"] = "wj_aw_model_" + uuid4().hex
    elif field == "payload_scope": env.job["payload"]["scope"]["user_uuid"] = str(uuid4())
    elif field == "payload_task": env.job["payload"]["task_id"] = str(uuid4())
    elif field == "job_user": env.job["user_id"] += 1
    else: env.job["payload"]["synthetic"] = False
    with pytest.raises(ContractError):
        coordinator_delivery.execute(env.authorized, env.job, lambda: False, lambda: None)
    assert env.progressed == []


@pytest.mark.parametrize("field,value", [("worker_id", "replacement-worker"), ("attempts", 2), ("cancel_requested", True),
    ("deadline_at", 1), ("locked_until", 1), ("deadline_at", float("nan")), ("locked_until", float("inf")), ("status", "queued")])
def test_coordinator_phase_requires_current_live_claim(claimed_coordinator, field, value):
    env = claimed_coordinator
    env.rows[env.job_id][field] = value
    with pytest.raises(ContractError, match="claim_required"):
        coordinator_delivery.execute(env.authorized, env.job, lambda: False, lambda: None)
    assert env.progressed == []


@pytest.mark.parametrize("reason", ["cancelled", "revoked"])
def test_coordinator_phase_rechecks_cancellation_and_authority(claimed_coordinator, reason):
    env = claimed_coordinator
    if reason == "revoked":
        def denied(): raise ContractError("automation_approval_revoked")
        env.authorized["admit"] = denied
    with pytest.raises(ContractError, match="cancelled|revoked"):
        coordinator_delivery.execute(env.authorized, env.job, lambda: reason == "cancelled", lambda: None)
    assert env.progressed == []


def test_coordinator_continuation_does_not_invoke_model_executor(claimed_coordinator, monkeypatch):
    env = claimed_coordinator
    from app.ai_control_center.model_service import ModelService
    monkeypatch.setattr(ModelService, "execute", lambda *a, **k: pytest.fail("continuation repeated provider"))
    result = coordinator_delivery.execute(env.authorized, env.job, lambda: False, lambda: None)
    assert result["provider_execution_performed"] is False and result["status"] == "continued"
    assert len(env.progressed) == 1


def test_history_ingress_cannot_accept_a_continuation_job_as_delivery_authority(claimed_coordinator):
    with pytest.raises(ContractError, match="model_delivery_job_required"):
        gateway.history_delivery_authority(claimed_coordinator.job)


@pytest.mark.parametrize("field", ["user_id", "workspace_id", "scope_user_uuid"])
def test_history_ingress_binds_header_and_payload_to_authorized_subject(claimed_coordinator, monkeypatch, field):
    env = claimed_coordinator
    job = copy.deepcopy(env.job)
    job["kind"] = "agent_world_model"
    job["payload"] = {**job["payload"], "phase": "delivery", "event_id": str(uuid4()), "checkpoint_sha256": "a" * 64}
    job["worker_job_id"] = gateway._delivery_job_id(job["payload"]["task_id"], job["payload"]["event_id"])
    if field == "user_id": job["user_id"] += 1
    elif field == "workspace_id": job["workspace_id"] += "_foreign"
    else: job["payload"]["scope"]["user_uuid"] = str(uuid4())
    monkeypatch.setattr(gateway, "worker_authority", lambda *a, **k: env.authorized)
    with pytest.raises(ContractError, match="model_delivery_scope_invalid"):
        gateway.history_delivery_authority(job)


@pytest.mark.parametrize("field,value", [("attempts", True), ("deadline_at", float("nan")),
    ("deadline_at", float("inf")), ("locked_until", "invalid"), ("locked_until", 1), ("cancel_requested", True)])
def test_model_history_ingress_rejects_invalid_claim_without_nan_bypass(claimed_coordinator, field, value):
    env = claimed_coordinator
    job = copy.deepcopy(env.job)
    job["kind"] = "agent_world_model"
    env.rows[env.job_id] = copy.deepcopy(job)
    env.rows[env.job_id][field] = value
    if field == "attempts":
        job[field] = value
    with pytest.raises(ContractError, match="model_delivery_claim_required"):
        gateway._require_delivery_claim(job)


def _production_delivery_claim(env):
    job = copy.deepcopy(env.job)
    job["kind"] = "agent_world_model"
    for key in ("worker_id", "locked_until", "deadline_at"):
        job.pop(key, None)
    job.update(lease_owner="production-worker", lease_token=str(uuid4()),
               leased_until=datetime.now(timezone.utc) + timedelta(seconds=60),
               started_at=datetime.now(timezone.utc) - timedelta(seconds=2), timeout_sec=30)
    env.rows[env.job_id] = copy.deepcopy(job)
    return job


def test_production_model_delivery_accepts_current_postgres_lease_without_provider_replay(claimed_coordinator):
    env = claimed_coordinator
    job = _production_delivery_claim(env)
    gateway._require_delivery_claim(job)
    # A heartbeat may extend the same lease without changing its token.
    env.rows[env.job_id]["leased_until"] += timedelta(seconds=30)
    gateway._require_delivery_claim(job)


@pytest.mark.parametrize("field,value", [
    ("lease_owner", "different-worker"), ("lease_token", "replaced-token"),
    ("leased_until", datetime(2020, 1, 1, tzinfo=timezone.utc)),
    ("timeout_sec", 0), ("cancel_requested", True), ("status", "queued"),
])
def test_production_model_delivery_fails_closed_on_stale_or_foreign_lease(claimed_coordinator, field, value):
    env = claimed_coordinator
    job = _production_delivery_claim(env)
    env.rows[env.job_id][field] = value
    with pytest.raises(ContractError, match="model_delivery_claim_required"):
        gateway._require_delivery_claim(job)


def test_accepted_review_delivery_after_entitlement_and_test_switch_expiry_is_history_only(synthetic_delivery, monkeypatch):
    env = synthetic_delivery
    assert local_worker.run_once(worker_id="review-expiry-source")["status"] == "succeeded"
    assert local_worker.run_once(worker_id="review-expiry-first-result")["status"] == "succeeded"
    detail = env.service.task_detail(context=env.context, task_id=env.task_id)
    task_review.submit(env.service, context=env.context, task_id=env.task_id,
        payload={"decision": "accept", "source_sha256": detail["human_review"]["source_sha256"]},
        expected_revision=detail["revision"], idempotency_key="explicit-before-entitlement-expiry")
    gateway.enqueue_model_delivery(env.authorized, env.service, env.task_id)
    env.account.state["budget_ok"] = False
    env.account.state["permissions"].update(role="read_only", capabilities={"ai_lab": False, "ai_pro_models": False})
    monkeypatch.delenv(test_executor.ENV)
    before_budget = len(env.account.calls["budget"])
    from app.ai_control_center.model_service import ModelService
    monkeypatch.setattr(ModelService, "execute", lambda *a, **k: pytest.fail("review delivery executed provider"))
    result = local_worker.run_once(worker_id="review-expiry-history-only")
    assert result["status"] == "succeeded" and result["result"]["status"] == "delivered"
    reports = _reports(env)
    assert len(reports) == 2 and reports[-1]["actions"][0]["status"] == "completed"
    assert reports[-1]["actions"][0]["synthetic"] is True
    assert len(env.calls) == 1 and len(env.account.calls["budget"]) == before_budget


@pytest.fixture
def ordinary_automation_program(world, tmp_path, monkeypatch):
    """Real auth/permission/device/queue stores, an ordinary disposable user.

    The initial registered user/device is fixture state, not registration QA.
    Plans, grants, model tasks, receipts and messages are produced by services.
    """
    from app import account_auth, workspaces
    uid, identity, session_id, device_id = 990101, str(uuid4()), "ordinary-automation-session", str(uuid4())
    doc = account_auth._read_doc()
    doc["users"].append({"user_id": uid, "user_uuid": identity, "is_owner": False, "status": "active",
        "role": "full_control", "ux_mode": "professional", "first_name": "Ordinary", "last_name": "Fixture",
        "email": "ordinary-automation@example.invalid"})
    doc["sessions"].append({"session_id": session_id, "user_id": uid, "expires_at": time.time() + 3600,
        "revoked": False, "device_confirmation_state": "active", "trusted_device_id": device_id,
        "device_trust_mode": "permanent"})
    doc["trusted_devices"].append({"device_id": device_id, "user_uuid": identity, "status": "trusted", "trust_mode": "permanent"})
    account_auth._write_doc(doc)
    for capability in ("ai_lab", "ai_pro_models", "ai_automation"):
        account_auth.set_user_permission(OWNER_ID, uid, capability, True)
    workspace = workspaces.ensure_personal_workspace(uid, require_entitlement=False)["workspace_id"]
    monkeypatch.setenv(live_gateway.WORKSPACES_ENV, workspace)
    monkeypatch.setenv(live_gateway.MECHANISMS_ENV, world.mechanisms("AI_EXECUTION_V2", "AI_DELEGATION_V2").replace(world.workspace, workspace))
    monkeypatch.setenv(test_executor.ENV, workspace)
    monkeypatch.setattr(chief_agent.paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chief_agent.paths, "REGISTRY_DIR", tmp_path / "ordinary-chat")
    scope = {"user_id": uid, "user_uuid": identity, "workspace_id": workspace, "auth_session_id": session_id}
    auth = gateway.access(scope)
    assert auth["chat_scope"]["is_owner"] is False and auth["chat_scope"]["uses_owner_runtime"] is False
    service, context, models = gateway.models(auth), auth["context"], []
    for number in range(2):
        policy = service._put(context, {"fixture": "ordinary trusted delivery"})
        persona = service._ensure(context, c.Persona, uuid4(), uuid4(), policy,
            display_name="Ordinary agent " + str(number), profile=service._put(context, {"description": "disposable"}))
        service._walk(context, persona, "active")
        models.append(service.connect(context=context, payload={"label": "Own test connection " + str(number),
            "provider": "deepseek", "model": "deepseek-v4-flash", "api_key": "ordinary-fixture-only-key",
            "persona_id": str(persona.header.entity_id)}, idempotency_key="ordinary-model-" + str(number)))
    def expire_session():
        current = account_auth._read_doc()
        next(row for row in current["sessions"] if row.get("session_id") == session_id)["expires_at"] = time.time() - 1
        account_auth._write_doc(current)
    return SimpleNamespace(auth=auth, service=service, context=context, scope=scope, models=models,
        expire_session=expire_session, root=tmp_path)


def _actual_tick(before=None):
    from app import durable, local_worker
    worker = "ordinary-shared-security-worker"
    job = durable.claim_worker_job(local_worker._root(), worker_id=worker)
    if job is None:
        return None
    def heartbeat():
        assert durable.heartbeat_worker_job(local_worker._root(), job["worker_job_id"], worker_id=worker)
    def cancelled():
        return durable.worker_cancel_requested(local_worker._root(), job["worker_job_id"], worker_id=worker)
    if before is not None:
        before(job)
    result = gateway.execute_worker(job, cancelled, heartbeat)
    durable.finish_worker_job(local_worker._root(), job["worker_job_id"], result, worker_id=worker)
    return job, result


def test_ordinary_permanent_grant_delivers_child_and_aggregate_after_browser_session_expiry(ordinary_automation_program):
    env = ordinary_automation_program
    payload = {"goal": "Verify exact facts in an ordinary workspace", "input_text": "[17,-4,12,9]",
                    "coordinator_model_id": env.models[0]["id"], "target_model_ids": [env.models[1]["id"]],
                    "parent_indices": [-1], "max_depth": 1}
    clarification = gateway.mutate(env.auth, "automation", "new", "commission", {
        "payload": payload, "idempotency_key": "ordinary-new-commission"})
    assert clarification["status"] == "clarification_required"
    payload["selection"] = {"id": "1", "plan_sha256": clarification["plan_sha256"]}
    created = gateway.mutate(env.auth, "automation", "new", "commission", {
        "payload": payload, "idempotency_key": "ordinary-new-commission"})
    for _ in range(5):
        if _actual_tick() is None:
            break
    plan = gateway.mutate(env.auth, "automation", created["id"], "preview_commission", {
        "payload": {}, "idempotency_key": "ordinary-preview-commission"})
    approved = gateway.mutate(env.auth, "automation", created["id"], "approve_commission", {
        "payload": {"approved_plan_sha256": plan["approved_plan_sha256"], "max_call_cost_usd": 0.0,
                    "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()},
        "idempotency_key": "ordinary-approve-commission"})
    graph_id = approved["graph"]["id"]
    env.expire_session()
    with pytest.raises(ContractError, match="session_expired"):
        gateway.access(env.scope)
    history = automation_authority.access(env.scope, controller_id=graph_id,
        grant_ref=approved["grant_ref"], read_only=True)
    assert history["context"].actor.kind == c.ActorKind.SERVICE
    assert "auth_session_id" not in history["chat_scope"]
    jobs, fenced = [], []
    def check_delivery(job):
        if job["payload"].get("phase") != "coordinator_delivery":
            return
        current = gateway.history_delivery_authority(job)
        assert current["read_only"] is True and current["context"].actor.kind == c.ActorKind.SERVICE
        saved = coordinator.completion(current, gateway.history_models(current), graph_id)
        # The keyword is a claimed-job ingress, not an envelope/browse bypass.
        with pytest.raises(ContractError, match="confirmed_session_required"):
            chief_agent.report_agent_world_live_update(saved["envelope"], history_delivery=True)
        forged = copy.deepcopy(saved["envelope"])
        forged["verification"]["human_accepted"] = True
        with pytest.raises(ContractError, match="evidence_changed"):
            chief_agent.report_agent_world_live_update(forged, history_delivery=True, _delivery_job=job)
        for field in ("task_id", "event_id", "automation_controller_id", "automation_grant_ref"):
            modified = copy.deepcopy(job)
            modified["payload"][field] = str(uuid4()) if field != "automation_grant_ref" else {
                "artifact_id": str(uuid4()), "sha256": "0" * 64, "scope": c.primitive(env.context.scope)}
            with pytest.raises(ContractError):
                gateway.history_delivery_authority(modified)
        fenced.append(job["worker_job_id"])
    for _ in range(20):
        entry = _actual_tick(check_delivery)
        if entry is None:
            break
        jobs.append(entry)
    else:
        pytest.fail("ordinary queue did not drain")
    graph = delegation.projection(history, gateway.history_models(history), graph_id)
    assert graph["status"] == "review" and graph["synthetic"] is True
    assert graph["human_accepted"] is False
    reports = [row for row in chief_agent.read_jsonl(chief_agent._conversation_file(created["conversation_id"], scope=history["chat_scope"]))
               if row.get("message_kind") == "report"]
    assert len(reports) == 3  # root result, child result, aggregate; no fabricated review.
    assert all(row["user_uuid"] == str(env.context.user_uuid) and row["workspace_id"] == env.context.scope.workspace_id for row in reports)
    aggregate = next(row for row in reports if row["actions"][0]["source_kind"] == "bounded_delegation_result")
    assert aggregate["actions"][0]["status"] == "awaiting_review" and aggregate["fulfillment"] == "unset"
    phases = [job["payload"].get("phase") for job, _ in jobs]
    assert "coordinator_continue" in phases and "coordinator_delivery" in phases and "delivery" in phases
    assert len(fenced) == 1
    assert sum(job["kind"] == "agent_world_model" and not job["payload"].get("phase") for job, _ in jobs) == 1
