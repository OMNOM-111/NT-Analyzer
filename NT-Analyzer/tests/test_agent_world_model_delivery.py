"""Existing worker/inbox/SF Chat restart contracts, disposable roots only."""
from __future__ import annotations

import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app import durable, local_worker, worker_router
from app.ai_lab import chief_agent
from app.ai_control_center import contracts as c, domain_gateway as gateway, model_chat
from app.ai_control_center.model_service import ModelService
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_domain_gateway import ordinary
from tests.test_agent_world_live_gateway import isolated_runtime, owner
from tests.test_agent_world_models import Secrets, response


@pytest.fixture
def delivery(ordinary, tmp_path, monkeypatch, request):
    if getattr(request, "param", "ordinary") == "owner":
        ordinary.scope.update(is_owner=True, uses_owner_runtime=True)
        ordinary.state["user"]["is_owner"] = True
        ordinary.state["workspaces"][ordinary.scope["workspace_id"]]["uses_owner_runtime"] = True
    monkeypatch.setenv("NT_ANALYZER_ROOT", str(tmp_path))
    monkeypatch.setattr(local_worker, "_MODEL_RECOVERY_STATE", {"root": "", "at": 0.0, "after_id": ""})
    monkeypatch.setattr(chief_agent.paths, "REGISTRY_DIR", tmp_path / "chat-registry")
    monkeypatch.setattr(chief_agent.paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chief_agent, "_explicit_production", lambda: False)
    path = tmp_path / "model-contracts.sqlite3"
    calls, secrets = [], Secrets()
    response_text = ['{"count":4,"sum":34,"min":-4,"max":17,"mean":8.5}']

    def repository(auth):
        auth["admit"]()
        return SQLiteAgentWorldRepository(path, read_only=auth.get("read_only", False))

    def execute(**kwargs):
        calls.append(kwargs)
        return response(response_text[0])

    def models(auth, repo=None):
        return ModelService(repo or repository(auth), secrets=secrets, executor=execute,
            admit=lambda context, operation, estimate: gateway._model_admit(auth, context, operation, estimate),
            enqueue=lambda **kw: gateway.enqueue_model(auth, **kw))

    monkeypatch.setattr(gateway, "repository", repository)
    monkeypatch.setattr(gateway, "models", models)
    auth = gateway.access(ordinary.scope)
    service, context = models(auth), auth["context"]
    policy = service._put(context, {"version": "isolated-delivery-fixture"})
    persona = service._ensure(context, c.Persona, uuid4(), uuid4(), policy,
        display_name="Delivery Fixture", profile=service._put(context, {"description": "contract fixture"}))
    service._walk(context, persona, "active")
    model = service.connect(context=context, payload={"label": "Delivery model", "provider": "deepseek",
        "model": "deepseek-v4-flash", "api_key": "isolated-in-memory-secret",
        "persona_id": str(persona.header.entity_id)}, idempotency_key="delivery-connect")
    detail = model_chat.start(auth, service, model["id"], {"rubric_key": "json_arithmetic", "input_text": "[8,13,-4,17]"},
                              "delivery-task")
    return SimpleNamespace(account=ordinary, context=context, authorized=auth, service=service,
        task_id=detail["id"], conversation=detail["conversation_id"], calls=calls, response_text=response_text, root=tmp_path,
        source_id="wj_aw_model_" + UUID(detail["id"]).hex)


def _rows(fixture):
    return chief_agent.read_jsonl(chief_agent._conversation_file(fixture.conversation,
        scope=fixture.authorized["chat_scope"]))


def _reports(fixture):
    return [row for row in _rows(fixture) if row.get("role") == "assistant" and row.get("message_kind") == "report"]


def _delivery_job(fixture):
    return next(row for row in durable.list_worker_jobs(fixture.root, kind="agent_world_model")
                if row["payload"].get("phase") == "delivery")


def _fail_first_history(monkeypatch):
    original, attempts = chief_agent.report_agent_world_live_update, []
    def publish(value, **kwargs):
        if kwargs.get("history_delivery"):
            attempts.append(value)
            if len(attempts) == 1:
                raise OSError("isolated transient chat failure")
        return original(value, **kwargs)
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", publish)
    return attempts


@pytest.mark.parametrize("delivery", ["ordinary", "owner"], indirect=True)
def test_transient_chat_failure_retries_persisted_result_without_second_call(delivery, monkeypatch):
    _fail_first_history(monkeypatch)
    first = local_worker.run_once(worker_id="original-worker")
    assert first["status"] == "succeeded" and first["attempts"] == 1
    assert delivery.service.task_detail(context=delivery.context, task_id=delivery.task_id)["status"] == "succeeded"
    queued = _delivery_job(delivery)
    assert queued["status"] == "queued" and queued["max_attempts"] == 3
    assert len(delivery.calls) == 1 and _reports(delivery) == []
    failed_delivery = local_worker.run_once(worker_id="first-delivery")
    assert failed_delivery["status"] == "queued" and failed_delivery["attempts"] == 1
    budgets = len(delivery.account.calls["budget"])
    monkeypatch.setattr(ModelService, "execute", lambda *a, **kw: pytest.fail("delivery executed the provider again"))
    second = local_worker.run_once(worker_id="restarted-worker")
    assert second["status"] == "succeeded" and second["result"]["status"] == "delivered"
    assert len(delivery.calls) == 1 and len(delivery.account.calls["budget"]) == budgets
    report = _reports(delivery)
    assert len(report) == 1
    action = report[0]["actions"][0]
    assert action["task_id"] == delivery.task_id and action["verification"]["passed"] is True
    assert all(action[field] for field in ("intent_id", "model_id", "contribution_id", "execution_id", "outcome_id", "evaluation_id", "correlation_id"))
    assert report[0]["workspace_id"] == delivery.context.scope.workspace_id
    assert report[0]["user_uuid"] == str(delivery.context.user_uuid)
    assert report[0]["model"] == response()["actual_model"]
    with pytest.raises(ContractError, match="claim_required"):
        gateway.execute_worker(second, lambda: False, lambda: None)
    assert len(_reports(delivery)) == 1 and len(delivery.account.calls["budget"]) == budgets


@pytest.mark.parametrize("rejected", [False, True])
def test_restart_after_completion_before_delivery_enqueue_uses_bounded_existing_scan(delivery, monkeypatch, rejected):
    if rejected:
        delivery.response_text[0] = '{"wrong":"response"}'
    original = gateway.enqueue_model_delivery
    monkeypatch.setattr(gateway, "enqueue_model_delivery", lambda *a, **kw: (_ for _ in ()).throw(OSError("crash before enqueue")))
    assert local_worker.run_once(worker_id="lost-process")["status"] == "failed"
    assert len(durable.list_worker_jobs(delivery.root)) == 1
    assert len(delivery.calls) == 1
    monkeypatch.setattr(gateway, "enqueue_model_delivery", original)
    monkeypatch.setattr(ModelService, "execute", lambda *a, **kw: pytest.fail("restart paid again"))
    local_worker._MODEL_RECOVERY_STATE.update(root="", at=0.0, after_id="")
    recovered = local_worker.run_once(worker_id="new-process")
    assert recovered["status"] == "succeeded" and recovered["payload"]["phase"] == "delivery"
    assert len(_reports(delivery)) == 1 and len(delivery.calls) == 1
    assert _reports(delivery)[0]["actions"][0]["verification"]["passed"] is (not rejected)


def test_unsealed_review_is_not_a_deliverable_model_result(delivery):
    task = delivery.service._get(delivery.context, EntityKind.TASK, delivery.task_id)
    task = delivery.service._change(delivery.context, task, "running")
    delivery.service._change(delivery.context, task, "review")
    assert model_chat.completion(delivery.authorized, delivery.service, delivery.task_id) is None
    assert _reports(delivery) == [] and not delivery.calls


def test_append_before_inbox_ack_is_repaired_idempotently(delivery, monkeypatch):
    events_type = type(delivery.service.repository.events)
    original, seen = events_type.acknowledge, []
    def ack(self, **kwargs):
        if kwargs["consumer"] == model_chat.DELIVERY_CONSUMER and not seen:
            seen.append(True)
            raise OSError("crash after append")
        return original(self, **kwargs)
    monkeypatch.setattr(events_type, "acknowledge", ack)
    assert local_worker.run_once(worker_id="model-source")["status"] == "succeeded"
    assert local_worker.run_once(worker_id="before-crash")["status"] == "queued"
    assert len(_reports(delivery)) == 1
    result = local_worker.run_once(worker_id="after-crash")
    assert result["status"] == "succeeded" and result["result"]["replayed"] is True
    assert len(_reports(delivery)) == 1 and len(delivery.calls) == 1
    assert delivery.service.repository.events.is_acknowledged(context=delivery.context,
        consumer=model_chat.DELIVERY_CONSUMER, event_id=UUID(result["payload"]["event_id"]))


def test_history_delivery_survives_paid_entitlement_expiry_without_new_budget_check(delivery, monkeypatch):
    _fail_first_history(monkeypatch)
    local_worker.run_once(worker_id="execute-once")
    assert local_worker.run_once(worker_id="failed-delivery")["status"] == "queued"
    delivery.account.state["budget_ok"] = False
    delivery.account.state["permissions"].update(role="read_only", capabilities={"ai_lab": False, "ai_pro_models": False})
    budget_count, gate_count = len(delivery.account.calls["budget"]), len(delivery.account.calls["enforce"])
    assert local_worker.run_once(worker_id="history-only")["status"] == "succeeded"
    assert len(delivery.account.calls["budget"]) == budget_count and len(delivery.calls) == 1
    assert all(raw["_request_method"] == "GET" for _, raw in delivery.account.calls["enforce"][gate_count:])
    assert len(_reports(delivery)) == 1


@pytest.mark.parametrize("revoke", ["session", "permission", "identity", "workspace", "flag"])
def test_delivery_revalidates_session_scope_and_flags_fail_closed(delivery, monkeypatch, revoke):
    _fail_first_history(monkeypatch)
    local_worker.run_once(worker_id="execute-once")
    job = _delivery_job(delivery)
    if revoke == "session":
        delivery.account.state["session_active"] = False
    elif revoke == "permission":
        delivery.account.state["permission_denied"] = True
    elif revoke == "identity":
        delivery.account.state["user"]["user_uuid"] = str(uuid4())
    elif revoke == "workspace":
        delivery.account.state["workspaces"].clear()
    else:
        monkeypatch.delenv(gateway.live_gateway.WORKSPACES_ENV)
    with pytest.raises(Exception):
        gateway.execute_worker(job, lambda: False, lambda: None)
    assert _reports(delivery) == [] and len(delivery.calls) == 1


@pytest.mark.parametrize("field", ["scope_user", "scope_workspace", "source", "task", "event"])
def test_delivery_rejects_reforged_source_and_provenance(delivery, monkeypatch, field):
    _fail_first_history(monkeypatch)
    local_worker.run_once(worker_id="execute-once")
    job = copy.deepcopy(_delivery_job(delivery))
    if field == "scope_user":
        job["payload"]["scope"]["user_uuid"] = str(uuid4())
    elif field == "scope_workspace":
        job["payload"]["scope"]["workspace_id"] += "_foreign"
    elif field == "source":
        job["payload"]["source_worker_job_id"] = "wj_aw_model_" + uuid4().hex
    elif field == "task":
        job["payload"]["task_id"] = str(uuid4())
    else:
        job["payload"]["event_id"] = str(uuid4())
    with pytest.raises(ContractError):
        gateway.execute_worker(job, lambda: False, lambda: None)
    assert _reports(delivery) == [] and len(delivery.calls) == 1


@pytest.mark.parametrize("field", ["text", "conversation_id", "task_id", "source_kind", "outcome_id", "request_id"])
def test_chief_history_keyword_accepts_only_exact_owned_terminal_envelope(delivery, field):
    delivery.service.execute(context=delivery.context, task_id=delivery.task_id)
    authorized = gateway.access(delivery.authorized["chat_scope"], read_only=True)
    saved = model_chat.completion(authorized, gateway.history_models(authorized), delivery.task_id)
    forged = copy.deepcopy(saved["envelope"])
    forged[field] = str(uuid4()) if field in {"task_id", "outcome_id"} else "forged"
    with pytest.raises((ContractError, chief_agent.ChiefAgentError)):
        chief_agent.report_agent_world_live_update(forged, history_delivery=True)
    assert _reports(delivery) == []


def test_history_delivery_requires_original_user_message_and_not_just_conversation(delivery, monkeypatch):
    delivery.service.execute(context=delivery.context, task_id=delivery.task_id)
    authorized = gateway.access(delivery.authorized["chat_scope"], read_only=True)
    saved = model_chat.completion(authorized, gateway.history_models(authorized), delivery.task_id)
    original = chief_agent.read_jsonl
    monkeypatch.setattr(chief_agent, "read_jsonl", lambda path: [row for row in original(path) if row.get("role") != "user"])
    with pytest.raises(ContractError, match="message_mismatch"):
        chief_agent.report_agent_world_live_update(saved["envelope"], history_delivery=True)


def test_no_delivery_retry_is_enqueued_while_provider_is_pending(delivery):
    authorized = gateway.access(delivery.authorized["chat_scope"], read_only=True)
    assert gateway.enqueue_model_delivery(authorized, gateway.history_models(authorized), delivery.task_id) is None
    assert len(durable.list_worker_jobs(delivery.root)) == 1 and delivery.calls == []
    claimed = durable.claim_worker_job(delivery.root, worker_id="provider-still-running")
    assert gateway.reconcile_model_deliveries([claimed]) == {"recovered": 0, "denied": 0}
    assert len(durable.list_worker_jobs(delivery.root)) == 1


def test_delivery_retries_are_bounded_even_when_chat_remains_unavailable(delivery, monkeypatch):
    original = chief_agent.report_agent_world_live_update
    def unavailable(value, **kwargs):
        if kwargs.get("history_delivery"):
            raise OSError("chat unavailable")
        return original(value, **kwargs)
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", unavailable)
    assert local_worker.run_once(worker_id="source")["status"] == "succeeded"
    assert [local_worker.run_once(worker_id="retry")["status"] for _ in range(3)] == ["queued", "queued", "failed"]
    local_worker._MODEL_RECOVERY_STATE["at"] = 0.0
    assert local_worker.run_once(worker_id="exhausted") is None
    assert _delivery_job(delivery)["attempts"] == 3
    assert len(durable.list_worker_jobs(delivery.root)) == 2 and len(delivery.calls) == 1


def test_competing_monitor_enqueue_and_worker_claim_publish_once(delivery, monkeypatch):
    assert local_worker.run_once(worker_id="source")["status"] == "succeeded"
    assert _reports(delivery) == []  # source worker never appends final text
    history = gateway.access(delivery.authorized["chat_scope"], read_only=True)
    barrier = threading.Barrier(2)
    def compete(index):
        barrier.wait()
        gateway.enqueue_model_delivery(history, gateway.history_models(history), delivery.task_id)
        return local_worker.run_once(worker_id="delivery-" + str(index))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, range(2)))
    assert sum(row is not None and row["status"] == "succeeded" for row in results) == 1
    assert len(_reports(delivery)) == 1 and len(delivery.calls) == 1
    assert len(durable.list_worker_jobs(delivery.root)) == 2


def test_unclaimed_or_replaced_delivery_claim_cannot_publish(delivery):
    local_worker.run_once(worker_id="source")
    queued = _delivery_job(delivery)
    with pytest.raises(ContractError, match="claim_required"):
        gateway.execute_worker(queued, lambda: False, lambda: None)
    first = durable.claim_worker_job(delivery.root, worker_id="old-worker")
    durable.fail_worker_job(delivery.root, first["worker_job_id"], "lost claim", worker_id="old-worker")
    second = durable.claim_worker_job(delivery.root, worker_id="new-worker")
    with pytest.raises(ContractError, match="claim_required"):
        gateway.execute_worker(first, lambda: False, lambda: None)
    assert _reports(delivery) == []
    assert gateway.execute_worker(second, lambda: False, lambda: None)["status"] == "delivered"
    assert len(_reports(delivery)) == 1


def test_existing_worker_kind_keyset_does_not_hide_old_rows_after_more_than_100_jobs(delivery):
    for index in range(110):
        local_worker.enqueue("noop", job_id=f"zz_foreign_{index:04d}", workspace_id="other")
        local_worker.enqueue("agent_world_model", job_id=f"zz_model_{index:04d}", workspace_id="other")
    first = durable.list_worker_jobs(delivery.root, kind="agent_world_model", after_id="", limit=100)
    second = durable.list_worker_jobs(delivery.root, kind="agent_world_model", after_id=first[-1]["worker_job_id"], limit=100)
    assert len(first) == 100 and len(second) == 11
    assert len({row["worker_job_id"] for row in first + second}) == 111
    assert all(row["kind"] == "agent_world_model" for row in first + second)
    assert delivery.source_id in {row["worker_job_id"] for row in first}
    assert len(durable.list_worker_jobs(delivery.root, limit=100)) == 100
    assert len(durable.list_worker_jobs(delivery.root, kind="agent_world_model", after_id="", workspace_id="other", limit=100)) == 100


def test_existing_worker_recovery_read_is_throttled_and_cursor_is_bounded(delivery, monkeypatch):
    reads, clock = [], [100.0]
    monkeypatch.setattr(local_worker.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(local_worker, "_MODEL_RECOVERY_LIMIT", 2)
    monkeypatch.setattr(gateway, "reconcile_model_deliveries", lambda rows: None)
    def page(root, **kwargs):
        reads.append(kwargs)
        return [{"worker_job_id": "a"}, {"worker_job_id": "b"}] if not kwargs["after_id"] else []
    monkeypatch.setattr(durable, "list_worker_jobs", page)
    local_worker._recover_model_deliveries(delivery.root)
    local_worker._recover_model_deliveries(delivery.root)
    assert len(reads) == 1 and reads[0] == {"kind": "agent_world_model", "after_id": "", "limit": 2}
    clock[0] += 31
    local_worker._recover_model_deliveries(delivery.root)
    assert len(reads) == 2 and reads[1]["after_id"] == "b"
    assert local_worker._MODEL_RECOVERY_STATE["after_id"] == ""
