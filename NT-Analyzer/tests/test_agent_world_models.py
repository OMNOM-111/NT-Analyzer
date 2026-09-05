"""Disposable, no-network evidence for private models and existing-client reuse."""
from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.ai_control_center import contracts as c
from app.ai_control_center import model_evaluation as evaluation
from app.ai_control_center import model_transport as transport
from app.ai_control_center.model_execution import ModelExecutor, PrivateRegistry
from app.ai_control_center.model_service import ModelService, _id, _key
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError, EntityKind
from app.ai_lab import agent_registry, universal_llm


class Secrets:
    def __init__(self):
        self.values = {}

    def available(self):
        return True

    def set_secret(self, key, value):
        self.values[key] = value

    def get_secret(self, key):
        return self.values.get(key)

    def delete_secret(self, key):
        return self.values.pop(key, None) is not None


def context(workspace="ws_models_tests", user=None):
    user = user or uuid4()
    return c.RequestContext(scope=c.TenantScope(environment=c.Environment.DEVELOPMENT, workspace_id=workspace),
                            user_uuid=user, actor=c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=user))


def response(text='{"count":4,"sum":34,"min":-4,"max":17,"mean":8.5}', **changes):
    return {"ok": True, "response": text, "request_id": "REQ-real-fixture", "actual_model": "served-model",
            "elapsed_sec": .125, "cost_known": True, "cost_usd": .0002, "input_tokens": 20,
            "output_tokens": 15, "reasoning": "DO_NOT_STORE_HIDDEN_REASONING", **changes}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    secrets = Secrets()
    repository = SQLiteAgentWorldRepository(tmp_path / "models.sqlite")
    ctx, calls, queued, checks = context(), [], [], []

    def execute(**kwargs):
        calls.append(kwargs)
        return response("CONNECTION_OK" if kwargs["purpose"] == "connection_test" else '{"count":4,"sum":34,"min":-4,"max":17,"mean":8.5}')

    service = ModelService(repository, admit=lambda *args: checks.append(args), secrets=secrets,
        enqueue=lambda **kwargs: queued.append(kwargs), executor=execute)
    policy = service._put(ctx, {"version": "test", "synthetic": False})
    persona = service._ensure(ctx, c.Persona, uuid4(), uuid4(), policy, display_name="Test Persona",
                              profile=service._put(ctx, {"description": "user-created test persona"}))
    persona = service._walk(ctx, persona, "active")
    payload = {"label": "Own connection", "provider": "deepseek", "model": "deepseek-v4-flash",
        "api_key": "never-write-this-secret", "persona_id": str(persona.header.entity_id)}
    return service, ctx, payload, calls, queued, checks, secrets


def connected(setup, key="connect-one"):
    service, ctx, payload, *_ = setup
    return service.connect(context=ctx, payload=payload, idempotency_key=key)


def task(setup, model=None, key="task-default", **payload):
    service, ctx, *_ = setup
    model = model or connected(setup)
    return service.start_task(context=ctx, model_id=model["id"], payload=payload,
                              idempotency_key=key, conversation_id=uuid4(), message_id=uuid4())


def test_private_connect_durable_idempotent_and_secret_absent(setup):
    service, ctx, payload, calls, queued, checks, secrets = setup
    one = connected(setup)
    two = connected(setup)
    assert one["id"] == two["id"]
    assert len(secrets.values) == 1 and not calls
    assert not one["connected"] and one["credentials_configured"]
    assert "api_key" not in json.dumps(service.models(context=ctx))
    with service.repository._transaction() as db:
        for table, column in (("aw_revisions", "payload"), ("aw_events", "payload")):
            assert payload["api_key"] not in " ".join(str(row[0]) for row in db.execute(f"SELECT {column} FROM {table}"))
        assert payload["api_key"].encode() not in b" ".join(bytes(row[0]) for row in db.execute("SELECT content FROM aw_artifacts"))
    assert one["provider_account_id"] != one["id"] != one["persona_id"]


def test_connect_same_key_different_config_conflicts(setup):
    connected(setup)
    service, ctx, payload, *_ = setup
    with pytest.raises(ContractError, match="idempotency_conflict"):
        service.connect(context=ctx, payload={**payload, "label": "Changed"}, idempotency_key="connect-one")


@pytest.mark.parametrize("changes", [
    {"base_url": "http://127.0.0.1"}, {"provider": "custom", "base_url": "https://evil.example/v1"},
    {"base_url": "https://user:pass@api.deepseek.com"}, {"base_url": "https://api.deepseek.com?api_key=leak"},
    {"base_url": "https://api.deepseek.com#fragment"}, {"base_url": "https://api.deepseek.com:8443"},
    {"provider": "made_up"}, {"api_key": "x\nsecret"}, {"global_admin": True},
])
def test_connect_fail_closed_inputs(setup, changes):
    service, ctx, payload, calls, _, _, secrets = setup
    with pytest.raises(ContractError):
        service.connect(context=ctx, payload={**payload, **changes}, idempotency_key="connect-invalid")
    assert not calls and not secrets.values


def test_own_user_workspace_isolation_and_no_global_enumeration(setup, monkeypatch):
    service, ctx, *_ = setup
    model = connected(setup)
    monkeypatch.setattr(agent_registry, "list_agents", lambda: pytest.fail("global registry enumeration"))
    assert len(service.models(context=ctx)["items"]) == 1
    for other in (context(user=uuid4()), context(workspace="ws_other_test", user=ctx.user_uuid)):
        assert not service.models(context=other)["items"]
        for action in (service.disconnect, service.model_detail):
            with pytest.raises(ContractError, match="not_found"):
                action(context=other, model_id=model["id"])


def test_test_and_task_execute_real_callback_full_linkage(setup):
    service, ctx, _, calls, queued, *_ = setup
    model = connected(setup)
    check = service.test(context=ctx, model_id=model["id"], idempotency_key="connection-check")
    assert check["status"] == "ready" and not calls and len(queued) == 1
    check = service.execute(context=ctx, task_id=check["id"])
    assert check["status"] == "succeeded"
    assert service.model_detail(context=ctx, model_id=model["id"])["connected"]
    pending = task(setup, model)
    result = service.execute(context=ctx, task_id=pending["id"])
    assert result["status"] == "succeeded" and result["synthetic"] is False
    assert all(result[key] for key in ("conversation_id", "message_id", "intent_id", "execution_id",
                                       "contribution_id", "outcome_id", "evaluation_id", "correlation_id"))
    assert result["actual_model"] == "served-model"
    assert result["latency_ms"] == 125 and result["cost_usd"] == .0002
    assert result["evaluation"]["passed"] and result["evaluation"]["self_scored"] is False
    assert "DO_NOT_STORE_HIDDEN_REASONING" not in json.dumps(result)
    assert service.evaluations(context=ctx, model_id=model["id"])["label"] == "NEW"
    assert len(calls) == 2


def test_execute_replay_restart_and_concurrency_one_provider_call(setup):
    service, ctx, _, calls, *_ = setup
    pending = task(setup)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: service.execute(context=ctx, task_id=pending["id"]), range(3)))
    assert all(row["status"] == "succeeded" for row in results) and len(calls) == 1
    fresh = ModelService(service.repository, admit=service.admit, executor=service.executor, secrets=service.secrets)
    assert fresh.execute(context=ctx, task_id=pending["id"])["status"] == "succeeded" and len(calls) == 1


def test_wrong_answer_is_review_not_self_scored_success(setup):
    service, ctx, *_ = setup
    pending = task(setup)
    service.executor = lambda **_: response('{"self_score":100,"sum":1}')
    result = service.execute(context=ctx, task_id=pending["id"])
    assert result["status"] == "review" and result["evaluation"]["passed"] is False
    assert result["evaluation"]["observed_score_pct"] < 100


@pytest.mark.parametrize("code", ["model_key_invalid", "model_not_found", "model_endpoint_unavailable", "model_budget_exhausted"])
def test_provider_failures_durable_no_fake_evaluation(setup, code):
    service, ctx, *_ = setup
    pending = task(setup)
    def fail(**kwargs):
        raise ContractError(code)
    service.executor = fail
    result = service.execute(context=ctx, task_id=pending["id"])
    assert result["status"] == "failed" and result["error_code"] == code
    assert result["evaluation"] is None and result["cost_usd"] is None


def test_arbitrary_provider_error_secret_not_persisted(setup):
    service, ctx, payload, *_ = setup
    pending = task(setup)
    def fail(**kwargs):
        raise RuntimeError(payload["api_key"] + " prompt " + kwargs["prompt"])
    service.executor = fail
    result = service.execute(context=ctx, task_id=pending["id"])
    assert result["error_code"] == "model_provider_error" and payload["api_key"] not in json.dumps(result)


def test_cancel_before_and_during_provider_never_publishes_response(setup):
    service, ctx, _, calls, *_ = setup
    pending = task(setup)
    service.cancel(context=ctx, task_id=pending["id"])
    assert service.execute(context=ctx, task_id=pending["id"])["status"] == "cancelled" and not calls
    another = task(setup, key="task-during-cancel")
    def execute(**_):
        service.cancel(context=ctx, task_id=another["id"])
        return response()
    service.executor = execute
    result = service.execute(context=ctx, task_id=another["id"])
    assert result["status"] == "cancelled" and result["result_text"] is None


def test_disconnect_preserves_history_rejects_queued_call(setup):
    service, ctx, _, calls, _, _, secrets = setup
    model = connected(setup)
    pending = task(setup, model)
    service.disconnect(context=ctx, model_id=model["id"])
    result = service.execute(context=ctx, task_id=pending["id"])
    assert result["status"] == "blocked" and result["error_code"] == "model_connection_inactive"
    assert not calls and not secrets.values
    assert len(service.tasks(context=ctx)["items"]) == 1


def test_unknown_cost_is_null_and_invalid_latency_fails(setup):
    service, ctx, *_ = setup
    pending = task(setup)
    service.executor = lambda **_: response(cost_known=False, cost_usd=0)
    assert service.execute(context=ctx, task_id=pending["id"])["cost_usd"] is None
    pending = task(setup, key="task-bad-latency")
    service.executor = lambda **_: response(elapsed_sec=float("nan"))
    assert service.execute(context=ctx, task_id=pending["id"])["error_code"] == "model_provider_latency_invalid"


def test_ambiguous_running_not_redispatched(setup):
    service, ctx, _, calls, *_ = setup
    pending = task(setup)
    record = service._get(ctx, EntityKind.TASK, pending["id"])
    service._change(ctx, record, "running")
    result = service.execute(context=ctx, task_id=pending["id"])
    assert result["status"] == "blocked" and result["error_code"] == "model_execution_state_unknown" and not calls
    assert service.cancel(context=ctx, task_id=pending["id"])["status"] == "cancelled"


def test_comparison_uses_exact_models_same_input_no_fake_results(setup):
    service, ctx, payload, calls, *_ = setup
    first = connected(setup)
    second = service.connect(context=ctx, payload={**payload, "label": "Own second"}, idempotency_key="connect-second")
    comparison = service.start_comparison(context=ctx, payload={"title": "Compare evidence", "model_ids": [first["id"], second["id"]]},
                                          idempotency_key="comparison-test")
    assert comparison["status"] == "running" and len(comparison["results"]) == 2 and not calls
    for item in comparison["results"]:
        service.execute(context=ctx, task_id=item["id"])
    ready = service.experiments(context=ctx)["items"][0]
    assert ready["status"] == "completed" and ready["fields"]["completed"] == 2
    assert len(calls) == 2 and calls[0]["prompt"] == calls[1]["prompt"]


def test_comparison_replay_seals_model_set_even_when_all_models_replaced(setup):
    service, ctx, payload, calls, *_ = setup
    models = [connected(setup, key="compare-connect-" + str(i)) for i in range(4)]
    original = {"title": "Immutable comparison", "model_ids": [item["id"] for item in models[:2]]}
    first = service.start_comparison(context=ctx, payload=original, idempotency_key="sealed-comparison")
    second = service.start_comparison(context=ctx, payload={**original, "model_ids": list(reversed(original["model_ids"]))},
                                      idempotency_key="sealed-comparison")
    assert {row["id"] for row in second["results"]} == {row["id"] for row in first["results"]}
    with pytest.raises(ContractError, match="comparison_idempotency_conflict"):
        service.start_comparison(context=ctx, payload={**original, "model_ids": [item["id"] for item in models[2:]]},
                                 idempotency_key="sealed-comparison")
    assert len(service.tasks(context=ctx)["items"]) == 2 and not calls


def test_three_distinct_inputs_required_and_connection_excluded():
    spec = evaluation.prepare("json_arithmetic")
    proof = evaluation.evaluate(spec, response()["response"])
    assert evaluation.reputation([proof] * 4, rubric_key="json_arithmetic")["sample_size"] == 1
    others = [evaluation.evaluate(evaluation.prepare("json_arithmetic", json.dumps(v)),
        json.dumps({"count": len(v), "sum": sum(v), "min": min(v), "max": max(v), "mean": sum(v)/len(v)}))
        for v in ([1, 2, 3], [-10, 20, 2], [30, 20, 10])]
    assert evaluation.reputation(others, rubric_key="json_arithmetic")["score_pct"] == 100
    assert evaluation.reputation([evaluation.evaluate(evaluation.prepare("connection_exact"), "CONNECTION_OK")],
        rubric_key="connection_exact")["sample_size"] == 0


def test_actual_response_tamper_requires_review_not_cached_rating(setup):
    service, ctx, *_ = setup
    pending = task(setup)
    service.execute(context=ctx, task_id=pending["id"])
    record = service._get(ctx, EntityKind.TASK, pending["id"])
    snapshot = service._json(ctx, record.checkpoint)["receipt"]
    with service.repository._transaction(write=True) as db:
        db.execute("UPDATE aw_artifacts SET content=? WHERE artifact_id=?", (b'{"response":"tampered"}', snapshot["artifact_id"]))
    with pytest.raises(ContractError, match="artifact_integrity"):
        service.task_detail(context=ctx, task_id=pending["id"])


@pytest.mark.parametrize("provider,model_key,endpoint", [
    ("deepseek", "deepseek-v4-flash", "https://api.deepseek.com"),
    ("azure_foundry", "gpt-5-mini", "https://fixture.openai.azure.com/openai/responses?api-version=2025-04-01-preview"),
    ("azure_foundry", "gpt-5-mini", "https://fixture.openai.azure.com/openai/responses?api-version=2024-10-21"),
])
def test_owner_binding_never_copies_or_deletes_global_secret(setup, provider, model_key, endpoint):
    service, ctx, payload, _, _, _, secrets = setup
    assert not secrets.values
    def resolve(context, registry_id):
        assert registry_id == "AGT-approved"
        return {"id": registry_id, "name": "Approved binding", "provider": provider, "model": model_key, "base_url": endpoint}
    bound = service.bind_existing_model(context=ctx, payload={"registry_id": "AGT-approved", "persona_id": payload["persona_id"]},
        idempotency_key="binding-approved", resolve_binding=resolve)
    assert bound["credential_source"] == "owner_registry_binding" and not secrets.values
    assert bound["base_url"] == endpoint
    service.disconnect(context=ctx, model_id=bound["id"])
    assert not secrets.values
    def reject(*_):
        raise ContractError("model_owner_binding_denied")
    with pytest.raises(ContractError, match="binding_denied"):
        service.bind_existing_model(context=ctx, payload={"registry_id": "guessed", "persona_id": payload["persona_id"]},
            idempotency_key="binding-guessed", resolve_binding=reject)


@pytest.mark.parametrize("provider,endpoint", [
    ("deepseek", "https://api.deepseek.com?api-version=2025-04-01-preview"),
    ("azure_foundry", "https://fixture.openai.azure.com?api-key=never-a-query-secret"),
    ("azure_foundry", "https://fixture.openai.azure.com?api-version=2025-04-01-preview&api-key=secret"),
    ("azure_foundry", "https://fixture.openai.azure.com?api-version=2025-04-01-preview&api-version=2024-10-21"),
    ("azure_foundry", "https://fixture.openai.azure.com?api-version=not-a-version"),
    ("azure_foundry", "https://fixture.openai.azure.com?api-version=2025-04-01-preview#secret"),
    ("azure_foundry", "https://user:secret@fixture.openai.azure.com?api-version=2025-04-01-preview"),
    ("azure_foundry", "http://fixture.openai.azure.com?api-version=2025-04-01-preview"),
])
def test_owner_binding_azure_version_does_not_admit_query_credentials(setup, provider, endpoint):
    service, ctx, payload, calls, queued, _, secrets = setup
    with pytest.raises(ContractError, match="model_endpoint_invalid"):
        service.bind_existing_model(context=ctx, payload={"registry_id": "AGT-approved", "persona_id": payload["persona_id"]},
            idempotency_key="invalid-owner-endpoint", resolve_binding=lambda *_: {
                "id": "AGT-approved", "name": "Approved fixture", "provider": provider,
                "model": "fixture-model", "base_url": endpoint})
    assert not calls and not queued and not secrets.values
    assert not service.models(context=ctx)["items"]


def test_judge_packet_isolated_and_schema_score_not_reputation(setup):
    from app.ai_control_center.domain_contracts import JudgeContext, JudgeResult
    service, ctx, _, calls, *_ = setup
    model = connected(setup)
    packet = json.dumps({"claim": "check evidence", "evidence": [{"value": 1}]}, sort_keys=True)
    captured = []
    def execute(**kwargs):
        captured.append(kwargs)
        return response('{"verdict":"abstain","confidence":20,"rationale":"Insufficient proof"}')
    service.executor = execute
    request = JudgeContext(context=ctx, model_id=UUID(model["id"]), case_id=uuid4(), session_id=uuid4(),
        packet_json=packet, packet_sha256=hashlib.sha256(packet.encode()).hexdigest(), run_key="isolated-court-judge")
    vote = service.judge(request)
    assert isinstance(vote, JudgeResult) and vote.verdict == "abstain" and vote.contribution_id
    assert "Other judges and chat history are unavailable" in captured[0]["prompt"]
    assert "No Markdown or code fences" in captured[0]["prompt"]
    saved = service._get(ctx, EntityKind.TASK, captured[0]["request_id"])
    assert service._json(ctx, saved.checkpoint)["spec"]["response_format_version"] == "plain-json-v1"
    assert service.evaluations(context=ctx, model_id=model["id"], rubric_key="court_vote")["sample_size"] == 0


def judge_request(setup, key):
    from app.ai_control_center.domain_contracts import JudgeContext
    model = connected(setup)
    packet = json.dumps({"claim": "bounded historical report, no execution"}, sort_keys=True)
    return JudgeContext(context=setup[1], model_id=UUID(model["id"]), case_id=uuid4(), session_id=uuid4(),
        packet_json=packet, packet_sha256=hashlib.sha256(packet.encode()).hexdigest(), run_key=key)


def test_inline_court_has_one_dispatch_owner_not_a_second_worker_job(setup):
    service, ctx, _, calls, queued, *_ = setup
    request = judge_request(setup, "court-single-dispatch")
    def execute(**kwargs):
        calls.append(kwargs)
        return response('{"verdict":"approve","confidence":80,"rationale":"Evidence only"}')
    service.executor = execute
    vote = service.judge(request)
    assert not queued, "Synchronous Court judge must not also enqueue a worker call"
    assert service.judge(request) == vote and len(calls) == 1 and not queued
    with pytest.raises(ContractError, match="model_rubric_not_supported"):
        service.start_task(context=ctx, model_id=request.model_id,
            payload={"rubric_key": "court_vote"}, idempotency_key="untrusted-court-rubric")


@pytest.mark.parametrize("wrapped", [False, True])
def test_old_court_format_receipt_replay_preserves_identity_and_rejection(setup, wrapped):
    service, ctx, _, calls, queued, *_ = setup
    request = judge_request(setup, "old-court-format")
    spec = {"rubric_key": "court_vote", "version": evaluation.VERSION, "input": json.loads(request.packet_json),
            "session_id": str(request.session_id), "case_id": str(request.case_id),
            "packet_sha256": request.packet_sha256, "policy_version": request.policy_version,
            "prompt_version": request.prompt_version}
    pending = service.start_task(context=ctx, model_id=request.model_id, payload={},
        idempotency_key="judge." + _key(request.run_key), _sealed_spec=spec)
    answer = '{"verdict":"abstain","confidence":20,"rationale":"Insufficient evidence"}'
    if wrapped:
        answer = "```json\n" + answer + "\n```"
    def execute(**kwargs):
        calls.append(kwargs)
        return response(answer)
    service.executor = execute
    service.execute(context=ctx, task_id=pending["id"])
    saved = service._get(ctx, EntityKind.TASK, pending["id"])
    original = service._json(ctx, saved.checkpoint)
    assert "No Markdown or code fences" not in calls[0]["prompt"]
    if wrapped:
        with pytest.raises(ContractError, match="model_judge_response_invalid"):
            service.judge(request)
    else:
        assert service.judge(request).verdict == "abstain"
    after = service.task_detail(context=ctx, task_id=pending["id"])
    assert after["result_text"] == answer
    assert after["status"] == ("review" if wrapped else "succeeded")
    assert len(calls) == 1 and not queued
    assert service._json(ctx, service._get(ctx, EntityKind.TASK, pending["id"]).checkpoint) == original


@pytest.mark.parametrize("mode", ["valid", "invalid_vote", "missing_receipt", "wrong_request", "revoked",
                                 "interrupt_1", "interrupt_2", "interrupt_3", "interrupt_4", "interrupt_5"])
def test_court_legacy_blocked_receipt_recovery_never_transmits_again(setup, mode):
    service, ctx, _, calls, queued, *_ = setup
    request = judge_request(setup, "court-sealed-recovery")
    def execute(**kwargs):
        calls.append(kwargs)
        return response('{"verdict":"approve","confidence":80,"rationale":"Evidence only"}'
                        if mode != "invalid_vote" else '{"self_score":100}')
    service.executor = execute
    finish = service._finish
    service._finish = lambda *args: (_ for _ in ()).throw(InterruptedError("after immutable receipt"))
    with pytest.raises(InterruptedError):
        service.judge(request)
    task_id = UUID(calls[0]["request_id"])
    record = service._get(ctx, EntityKind.TASK, task_id)
    checkpoint = service._json(ctx, record.checkpoint)
    original_receipt = dict(checkpoint["receipt"])
    # Reproduce the old cross-process race: the worker saw an in-flight task
    # while the synchronous caller subsequently persisted its authentic receipt.
    record = service._change(ctx, record, "blocked")
    service._change(ctx, service._execution(ctx, task_id), "review")
    service._change(ctx, service._get(ctx, EntityKind.INTENT, record.intent.entity_id), "blocked")
    if mode == "missing_receipt":
        checkpoint.pop("receipt")
    elif mode == "wrong_request":
        receipt = service._json(ctx, checkpoint["receipt"])
        receipt["request_sha256"] = "0" * 64
        checkpoint["receipt"] = c.primitive(service._put(ctx, receipt))
    if mode in {"missing_receipt", "wrong_request"}:
        record = service._change(ctx, record, checkpoint=service._put(ctx, checkpoint))
    service._finish = finish
    if mode == "revoked":
        service.admit = lambda *_: (_ for _ in ()).throw(ContractError("model_access_denied"))
    if mode.startswith("interrupt_"):
        change, writes = service._change, []
        def interrupt_change(*args, **kwargs):
            saved = change(*args, **kwargs)
            writes.append(saved.ref())
            if len(writes) == int(mode.rsplit("_", 1)[1]):
                raise InterruptedError("during pure receipt recovery")
            return saved
        service._change = interrupt_change
        with pytest.raises(InterruptedError):
            service.judge(request)
        service._change = change
    if mode == "valid" or mode.startswith("interrupt_"):
        vote = service.judge(request)
        assert vote.verdict == "approve"
        assert service.judge(request) == vote
        assert service._get(ctx, EntityKind.TASK, task_id).status == "succeeded"
        assert service._get(ctx, EntityKind.INTENT, record.intent.entity_id).status == "completed"
        assert service._execution(ctx, task_id).status == "succeeded"
    else:
        with pytest.raises(ContractError):
            service.judge(request)
        assert service._get(ctx, EntityKind.TASK, task_id).status == ("review" if mode == "invalid_vote" else "blocked")
    assert len(calls) == 1 and not queued
    if mode in {"valid", "invalid_vote"} or mode.startswith("interrupt_"):
        current = service._get(ctx, EntityKind.TASK, task_id)
        assert service._json(ctx, current.checkpoint)["receipt"] == original_receipt


def test_scoped_registry_nested_thread_isolation_and_default():
    class Adapter:
        def __getattr__(self, key):
            return lambda *a, **kw: key
    one, two = Adapter(), Adapter()
    with universal_llm.registry_scope(one):
        assert universal_llm._registry() is one
        with universal_llm.registry_scope(two):
            assert universal_llm._registry() is two
        assert universal_llm._registry() is one
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(universal_llm._registry).result() is agent_registry
    assert universal_llm._registry() is agent_registry
    class EmptyAdapter(Adapter):
        def __bool__(self):
            return False
    empty = EmptyAdapter()
    with universal_llm.registry_scope(empty):
        assert universal_llm._registry() is empty
    with pytest.raises(RuntimeError):
        with universal_llm.registry_scope(one):
            raise RuntimeError()
    assert universal_llm._registry() is agent_registry


def test_existing_client_budget_usage_no_global_key_and_no_cache(setup, monkeypatch):
    service, ctx, _, _, _, _, secrets = setup
    model_dto = connected(setup)
    model = service._get(ctx, EntityKind.MODEL, model_dto["id"])
    profile = service._json(ctx, model.profile)
    account = service._get(ctx, EntityKind.PROVIDER_ACCOUNT, profile["provider_account_id"])
    usage, seen = [], []
    monkeypatch.setattr(agent_registry, "get_api_key", lambda *_: pytest.fail("global key"))
    monkeypatch.setattr(agent_registry, "list_agents", lambda: pytest.fail("global list"))
    monkeypatch.setattr(universal_llm.response_cache, "get", lambda *_: pytest.fail("global cache"))
    def mocked_request(*args, **kwargs):
        seen.append(kwargs)
        return {"model": "deepseek-v4-flash", "usage": {"prompt_tokens": 10, "completion_tokens": 6},
                "choices": [{"message": {"content": "CONNECTION_OK", "reasoning_content": "NOT_IN_RECEIPT"}}]}
    monkeypatch.setattr(universal_llm, "_request_json", mocked_request)
    executor = ModelExecutor(budget_limits=lambda *_: {"daily_budget_usd": .1, "monthly_budget_usd": .2},
        secrets=secrets, usage_reader=lambda **_: list(usage), usage_writer=usage.append)
    result = executor(context=ctx, model=model, account=account, profile=profile, prompt="Reply CONNECTION_OK",
        system_prompt="Bounded test", request_id="test-request", conversation_id=None, max_output_tokens=128,
        purpose="connection_test", cancelled=None, admit=lambda *_: None)
    assert result["ok"] and result["cost_known"] and "reasoning" not in result
    assert seen[0]["secret"] == "never-write-this-secret"
    assert usage[0]["agent_id"].startswith("aw_model.") and usage[0]["workspace_id"] == ctx.scope.workspace_id
    assert usage[0]["request_source"] == "agent_world.test-request"
    assert "never-write-this-secret" not in json.dumps(usage)
    assert not universal_llm.active_requests()


@pytest.mark.parametrize("limits", [{}, {"daily_budget_usd": 0, "monthly_budget_usd": 1},
    {"daily_budget_usd": 11, "monthly_budget_usd": 20}, {"daily_budget_usd": 1, "monthly_budget_usd": float("nan")}])
def test_private_budget_bounds_fail_closed(setup, limits):
    service, ctx, *_ = setup
    dto = connected(setup)
    model = service._get(ctx, EntityKind.MODEL, dto["id"])
    profile = service._json(ctx, model.profile)
    account = service._get(ctx, EntityKind.PROVIDER_ACCOUNT, dto["provider_account_id"])
    with pytest.raises(ContractError, match="budget"):
        PrivateRegistry(context=ctx, model=model, account=account, profile=profile, limits=limits,
                        secrets=service.secrets, revalidate=lambda: None)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254",
    "0.0.0.0", "224.0.0.1", "::1", "fd00::1", "fe80::1", "::ffff:127.0.0.1", "2001:db8::1"])
def test_transport_private_reserved_loopback_fail_closed(address):
    def resolve(*args, **kwargs):
        return [(None, None, None, None, (address, 443))]
    with pytest.raises(transport.PrivateTransportError):
        transport.validate_target("https://api.example.com/v1/chat/completions", resolver=resolve)


@pytest.mark.parametrize("url", ["http://api.example.com/v1/chat/completions", "https://key@api.example.com/v1/chat/completions",
    "https://api.example.com:444/v1/chat/completions", "https://api.example.com/v1/chat/completions?key=secret",
    "https://api.example.com/v1/chat/completions#x", "https://api.example.com/delete", "https://api.example.com/v1/%2e/chat/completions"])
def test_transport_target_validation_before_dns(url):
    with pytest.raises(transport.PrivateTransportError):
        transport.validate_target(url, resolver=lambda *a, **kw: pytest.fail("unexpected DNS"))


def test_transport_public_pin_no_redirect_and_bounded_response(monkeypatch):
    monkeypatch.setattr(transport.socket, "getaddrinfo", lambda *a, **kw: [(None, None, None, None, ("8.8.8.8", 443))])
    rows = []
    class Connection:
        def __init__(self, host, address, timeout):
            rows.append((host, address, timeout))
        def request(self, *args, **kwargs):
            pass
        def getresponse(self):
            return self
        status = 302
        def read(self, size):
            raise AssertionError("redirect body must not be read")
        def close(self):
            pass
    monkeypatch.setattr(transport, "_PinnedHTTPSConnection", Connection)
    with pytest.raises(transport.PrivateTransportError, match="HTTP 302"):
        transport.request_json("https://api.example.com/v1/chat/completions", payload={})
    assert rows[0] == ("api.example.com", "8.8.8.8", 60)
    Connection.status = 200
    Connection.read = lambda self, size: b"x" * size
    with pytest.raises(transport.PrivateTransportError, match="too large"):
        transport.request_json("https://api.example.com/v1/chat/completions", payload={})


def test_legacy_chat_ids_preserved_and_not_accepted_from_payload(setup):
    service, ctx, *_ = setup
    model = connected(setup)
    pending = service.start_task(context=ctx, model_id=model["id"], payload={}, idempotency_key="legacy-chat-ids",
                                conversation_id="default", message_id="MSG-abcdef123456")
    assert pending["conversation_id"] == "default" and pending["message_id"] == "MSG-abcdef123456"
    with pytest.raises(ContractError, match="field_invalid"):
        service.start_task(context=ctx, model_id=model["id"], payload={"conversation_id": "other"}, idempotency_key="forge-chat-ids")
    with pytest.raises(ContractError):
        service.start_task(context=ctx, model_id=model["id"], payload={}, idempotency_key="bad-chat-token", conversation_id="../x")


def test_pre_dispatch_creation_repair_and_receipt_closeout_repair(setup, monkeypatch):
    service, ctx, _, calls, queued, *_ = setup
    model = connected(setup)
    original = service._prepare_execution
    def unavailable(*_):
        raise OSError("simulated process stop before durable dispatch")
    monkeypatch.setattr(service, "_prepare_execution", unavailable)
    with pytest.raises(OSError):
        service.start_task(context=ctx, model_id=model["id"], payload={}, idempotency_key="repair-create")
    assert not calls and not queued
    monkeypatch.setattr(service, "_prepare_execution", original)
    pending = service.start_task(context=ctx, model_id=model["id"], payload={}, idempotency_key="repair-create")
    assert pending["status"] == "ready" and len(queued) == 1
    finish = service._finish
    monkeypatch.setattr(service, "_finish", unavailable)
    with pytest.raises(OSError):
        service.execute(context=ctx, task_id=pending["id"])
    assert len(calls) == 1
    monkeypatch.setattr(service, "_finish", finish)
    assert service.execute(context=ctx, task_id=pending["id"])["status"] == "succeeded"
    assert len(calls) == 1


def test_new_steps_revalidate_authority_after_enqueue(setup):
    service, ctx, _, calls, *_ = setup
    pending = task(setup)
    def deny(*_):
        raise ContractError("model_access_denied")
    service.admit = deny
    with pytest.raises(ContractError, match="access_denied"):
        service.execute(context=ctx, task_id=pending["id"])
    assert not calls


def test_application_plan_waits_for_real_owned_receipt(setup):
    service, ctx, *_ = setup
    model = connected(setup)
    spec = {"instrument": "MNQ 09-26", "timeframe": "5m"}
    pending = service.plan_application(context=ctx, model_id=model["id"], spec=spec, kind="chart",
        idempotency_key="chart-spec-real", conversation_id="conv_owner", message_id="MSG-aabbcc001122")
    service.executor = lambda **_: response(json.dumps(spec))
    planned = service.execute(context=ctx, task_id=pending["id"])
    assert planned["model_plan_verified"] and planned["status"] == "waiting" and planned["stage"] == "awaiting_application"
    assert planned["application_request"]["spec"] == spec and not planned["application_result"]
    # Isolated actual-source surrogate bytes test the wiring, not a runtime claim.
    artifact = service._put(ctx, {"source": "test_disposable_desktop_receipt", "bars": 20})
    proof = {"verified": True, "synthetic": False, "source_kind": "desktop_chart", "source_id": "chart_command_1",
        "sha256": artifact.sha256, "request_sha256": planned["application_request"]["request_sha256"]}
    result = service.record_application_result(context=ctx, task_id=planned["id"], source_id="chart_command_1",
                                               verification=proof, artifact_refs=(artifact,))
    assert result["verified"]
    assert service.record_application_result(context=ctx, task_id=planned["id"], source_id="chart_command_1",
        verification=proof, artifact_refs=(artifact,)) == result
    finished = service.task_detail(context=ctx, task_id=planned["id"])
    assert finished["status"] == "succeeded" and finished["stage"] == "application_verified"
    with pytest.raises(ContractError, match="conflict"):
        service.record_application_result(context=ctx, task_id=planned["id"], source_id="chart_command_1",
            verification={**proof, "different_source": True}, artifact_refs=(artifact,))


@pytest.mark.parametrize("mutate", ["synthetic", "different_request", "wrong_source", "wrong_hash", "not_verified"])
def test_application_evidence_negative_boundary(setup, mutate):
    service, ctx, *_ = setup
    model = connected(setup)
    spec = {"instrument": "MNQ 09-26", "timeframe": "5m"}
    pending = service.plan_application(context=ctx, model_id=model["id"], spec=spec, kind="chart",
        idempotency_key="negative-chart-spec", conversation_id="default", message_id="MSG-aabb")
    service.executor = lambda **_: response(json.dumps(spec))
    planned = service.execute(context=ctx, task_id=pending["id"])
    artifact = service._put(ctx, {"bounded": "test"})
    proof = {"verified": True, "synthetic": False, "source_kind": "desktop_chart", "source_id": "chart_1",
        "sha256": artifact.sha256, "request_sha256": planned["application_request"]["request_sha256"]}
    proof.update({"synthetic": {"synthetic": True}, "different_request": {"request_sha256": "a" * 64},
        "wrong_source": {"source_id": "other"}, "wrong_hash": {"sha256": "a" * 64},
        "not_verified": {"verified": False}}[mutate])
    with pytest.raises(ContractError):
        service.record_application_result(context=ctx, task_id=planned["id"], source_id="chart_1", verification=proof, artifact_refs=(artifact,))


def test_model_cannot_expand_application_spec_into_orders(setup):
    service, ctx, *_ = setup
    model = connected(setup)
    spec = {"instrument": "MNQ 09-26", "timeframe": "5m"}
    pending = service.plan_application(context=ctx, model_id=model["id"], spec=spec, kind="chart",
        idempotency_key="injected-order-plan", conversation_id="default", message_id="MSG-aabb")
    service.executor = lambda **_: response(json.dumps({**spec, "tool": "place_order"}))
    reviewed = service.execute(context=ctx, task_id=pending["id"])
    assert reviewed["status"] == "review" and not reviewed["model_plan_verified"]


def test_existing_budget_reservation_shared_between_private_adapters(setup, monkeypatch):
    service, ctx, *_ = setup
    dto = connected(setup)
    model = service._get(ctx, EntityKind.MODEL, dto["id"])
    profile = service._json(ctx, model.profile)
    account = service._get(ctx, EntityKind.PROVIDER_ACCOUNT, dto["provider_account_id"])
    def make():
        return PrivateRegistry(context=ctx, model=model, account=account, profile=profile,
            limits={"daily_budget_usd": .1, "monthly_budget_usd": .2}, secrets=service.secrets,
            revalidate=lambda: None, usage_reader=lambda **_: [])
    monkeypatch.setattr(universal_llm, "_RESERVATIONS", {})
    one, two = make(), make()
    with universal_llm.registry_scope(one):
        reservation = universal_llm._reserve(one.get_agent(one.agent_id), .08, allow_disabled=False)
    try:
        with universal_llm.registry_scope(two), pytest.raises(universal_llm.BudgetExceeded):
            universal_llm._reserve(two.get_agent(two.agent_id), .08, allow_disabled=False)
    finally:
        universal_llm._release(reservation)


def test_private_budget_spent_from_existing_usage_ledger_and_unknown_pricing(setup):
    service, ctx, *_ = setup
    dto = connected(setup)
    model = service._get(ctx, EntityKind.MODEL, dto["id"])
    profile = service._json(ctx, model.profile)
    account = service._get(ctx, EntityKind.PROVIDER_ACCOUNT, dto["provider_account_id"])
    agent_id = "aw_model." + str(model.header.entity_id)
    rows = [{"agent_id": agent_id, "workspace_id": ctx.scope.workspace_id, "user_id": str(ctx.user_uuid),
             "timestamp_utc": datetime.now(timezone.utc).isoformat(), "cost_usd": .1}]
    adapter = PrivateRegistry(context=ctx, model=model, account=account, profile=profile,
        limits={"daily_budget_usd": .1, "monthly_budget_usd": .2}, secrets=service.secrets,
        revalidate=lambda: None, usage_reader=lambda **_: rows)
    with universal_llm.registry_scope(adapter), pytest.raises(universal_llm.BudgetExceeded):
        universal_llm._reserve(adapter.get_agent(agent_id), .001, allow_disabled=False)
    with pytest.raises(ContractError, match="pricing_unavailable"):
        PrivateRegistry(context=ctx, model=model, account=account, profile=profile,
            limits={"daily_budget_usd": .1, "monthly_budget_usd": .2}, secrets=service.secrets,
            revalidate=lambda: None, pricing={"pricing_status": "unknown"})


def test_scoped_streaming_and_balance_never_bypass_transport(monkeypatch):
    class Adapter:
        def __getattr__(self, key):
            return lambda *a, **kw: pytest.fail("must deny before credentials")
    with universal_llm.registry_scope(Adapter()):
        with pytest.raises(universal_llm.UniversalLLMError, match="streaming"):
            list(universal_llm._request_stream("http://127.0.0.1", payload={}))
        with pytest.raises(universal_llm.UniversalLLMError, match="balance"):
            universal_llm.sync_credit_balance("forged")


def test_bounded_invocation_policy_resets_and_disallows_hidden_deepseek_retry(monkeypatch):
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": "", "reasoning_content": "hidden"}}], "usage": {"completion_tokens": 12}}
    monkeypatch.setattr(universal_llm, "_request_json", request)
    config = {"provider": "deepseek", "model": "deepseek-v4-flash", "base_url": "https://api.deepseek.com/chat/completions"}
    with universal_llm.invocation_policy(allow_hidden_retries=False):
        assert universal_llm._ALLOW_HIDDEN_RETRIES.get() is False
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(universal_llm._ALLOW_HIDDEN_RETRIES.get).result() is True
        with pytest.raises(universal_llm.UniversalLLMError):
            universal_llm._openai_compatible(config, "isolated-key", "bounded", "", 20, 1)
    assert len(calls) == 1 and universal_llm._ALLOW_HIDDEN_RETRIES.get() is True


@pytest.mark.parametrize("kind", ["chat_text", "chat_parts", "responses_text", "responses_parts"])
def test_existing_provider_formats_extract_only_final_response(monkeypatch, kind):
    expected = '{"instrument":"MNQ 09-26","timeframe":"5m"}'
    bodies = {
        "chat_text": {"choices": [{"message": {"content": expected}}]},
        "chat_parts": {"choices": [{"message": {"content": [{"type": "text", "text": expected}]}}]},
        "responses_text": {"output_text": expected},
        "responses_parts": {"output": [{"type": "reasoning", "summary": [{"text": "NOT_EVIDENCE"}]},
            {"type": "message", "content": [{"type": "output_text", "text": expected}]}]},
    }
    monkeypatch.setattr(universal_llm, "_request_json", lambda *a, **kw: {**bodies[kind], "model": "configured-model", "usage": {}})
    suffix = "responses" if kind.startswith("responses") else "chat/completions"
    value, usage = universal_llm._openai_compatible({"provider": "azure_foundry" if kind.startswith("responses") else "openai", "model": "configured-model",
        "base_url": "https://api.openai.com/v1/" + suffix}, "isolated-key", "spec", "bounded", 128, 1)
    assert value == expected and usage["actual_model"] == "configured-model"


@pytest.mark.parametrize("provider,model_key,endpoint", [
    ("deepseek", "deepseek-v4-flash", "https://api.deepseek.com/chat/completions"),
    ("azure_foundry", "gpt-5-mini", "https://fixture.openai.azure.com/openai/responses?api-version=2025-04-01-preview"),
])
def test_owner_binding_call_uses_original_identity_and_bounded_retry_policy(setup, monkeypatch, provider, model_key, endpoint):
    service, ctx, payload, *_ = setup
    configured = {"id": "AGT-authorized", "name": "Approved owner connection", "provider": provider, "model": model_key,
                  "base_url": endpoint, "pricing_status": "configured"}
    bound = service.bind_existing_model(context=ctx, payload={"registry_id": configured["id"], "persona_id": payload["persona_id"]},
        idempotency_key="owner-policy-binding", resolve_binding=lambda *a: configured)
    model = service._get(ctx, EntityKind.MODEL, bound["id"])
    profile = service._json(ctx, model.profile)
    account = service._get(ctx, EntityKind.PROVIDER_ACCOUNT, profile["provider_account_id"])
    monkeypatch.setattr(agent_registry, "get_agent", lambda identity: configured if identity == configured["id"] else pytest.fail("wrong owner id"))
    seen = []
    def invoke(identity, **kwargs):
        seen.append(identity)
        assert universal_llm._registry() is agent_registry and universal_llm._ALLOW_HIDDEN_RETRIES.get() is False
        kwargs["check"]()
        return response("CONNECTION_OK")
    executor = ModelExecutor(budget_limits=lambda *_: pytest.fail("do not replace owner caps"), owner_binding=lambda *a: configured["id"])
    monkeypatch.setattr(executor, "_call", invoke)
    result = executor(context=ctx, model=model, account=account, profile=profile, prompt="bounded", system_prompt="bounded",
        request_id="owner-policy-task", conversation_id="default", max_output_tokens=128, purpose="connection_test",
        cancelled=None, admit=lambda *a: None)
    assert result["ok"] and seen == [configured["id"]] and universal_llm._ALLOW_HIDDEN_RETRIES.get() is True


def test_application_outcome_before_evaluation_interruption_repairs(setup, monkeypatch):
    service, ctx, *_ = setup
    model = connected(setup)
    spec = {"instrument": "MNQ 09-26", "timeframe": "5m"}
    plan = service.plan_application(context=ctx, model_id=model["id"], spec=spec, kind="chart",
        idempotency_key="repair-application", conversation_id="default", message_id="MSG-aabbcc001122")
    service.executor = lambda **_: response(json.dumps(spec))
    plan = service.execute(context=ctx, task_id=plan["id"])
    ref = service._put(ctx, {"disposable": "real-source-adapter-surrogate"})
    proof = {"verified": True, "synthetic": False, "source_kind": "desktop_chart", "source_id": "cc_test_receipt",
        "sha256": ref.sha256, "request_sha256": plan["application_request"]["request_sha256"]}
    original = service._ensure
    def interrupt(context, cls, *args, **kwargs):
        if cls.KIND == EntityKind.EVALUATION and kwargs.get("rubric_key") == "application_execution":
            raise OSError("simulated closeout interruption")
        return original(context, cls, *args, **kwargs)
    monkeypatch.setattr(service, "_ensure", interrupt)
    with pytest.raises(OSError):
        service.record_application_result(context=ctx, task_id=plan["id"], source_id="cc_test_receipt", verification=proof, artifact_refs=(ref,))
    assert service.task_detail(context=ctx, task_id=plan["id"])["status"] == "waiting"
    monkeypatch.setattr(service, "_ensure", original)
    result = service.record_application_result(context=ctx, task_id=plan["id"], source_id="cc_test_receipt", verification=proof, artifact_refs=(ref,))
    assert result["verified"] and service.task_detail(context=ctx, task_id=plan["id"])["status"] == "succeeded"


def test_parallel_distinct_connection_tests_do_not_lose_model_revision(setup):
    service, ctx, *_ = setup
    model = connected(setup)
    keys = ["parallel-test-0"]
    first_stripe = _id(ctx, "model-task:" + hashlib.sha256(keys[0].encode()).hexdigest()).int % 64
    for index in range(1, 128):
        key = "parallel-test-" + str(index)
        if _id(ctx, "model-task:" + hashlib.sha256(key.encode()).hexdigest()).int % 64 != first_stripe:
            keys.append(key)
            break
    assert len(keys) == 2
    tasks = [service.test(context=ctx, model_id=model["id"], idempotency_key=key) for key in keys]
    barrier = threading.Barrier(2)
    def execute(**_):
        barrier.wait(timeout=10)
        return response("CONNECTION_OK")
    service.executor = execute
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda task: service.execute(context=ctx, task_id=task["id"]), tasks))
    assert all(result["status"] == "succeeded" for result in results)
    assert service.model_detail(context=ctx, model_id=model["id"])["last_test"]["task_id"] in {task["id"] for task in tasks}


def test_partial_connection_preserves_sealed_request_before_secret_replacement(setup, monkeypatch):
    service, ctx, payload, *_ = setup
    original = service._ensure
    def interrupt(context, cls, *args, **kwargs):
        if cls.KIND == EntityKind.MODEL:
            raise OSError("simulated model-create interruption")
        return original(context, cls, *args, **kwargs)
    monkeypatch.setattr(service, "_ensure", interrupt)
    with pytest.raises(OSError):
        service.connect(context=ctx, payload=payload, idempotency_key="partial-connection")
    before = dict(service.secrets.values)
    monkeypatch.setattr(service, "_ensure", original)
    with pytest.raises(ContractError, match="connection_idempotency_conflict"):
        service.connect(context=ctx, payload={**payload, "model": "changed-model", "api_key": "different-secret"},
                        idempotency_key="partial-connection")
    assert service.secrets.values == before
    with pytest.raises(ContractError, match="connection_idempotency_conflict"):
        service.connect(context=ctx, payload={**payload, "api_key": "different-secret"}, idempotency_key="partial-connection")
    assert service.connect(context=ctx, payload=payload, idempotency_key="partial-connection")["status"] == "active"


def test_partial_intent_rejects_changed_task_input_and_repairs_exact_retry(setup, monkeypatch):
    service, ctx, *_ = setup
    model = connected(setup)
    original = service._ensure
    def interrupt(context, cls, *args, **kwargs):
        if cls.KIND == EntityKind.TASK:
            raise OSError("simulated task-create interruption")
        return original(context, cls, *args, **kwargs)
    monkeypatch.setattr(service, "_ensure", interrupt)
    with pytest.raises(OSError):
        service.start_task(context=ctx, model_id=model["id"], payload={}, idempotency_key="partial-intent")
    monkeypatch.setattr(service, "_ensure", original)
    with pytest.raises(ContractError, match="task_idempotency_conflict"):
        service.start_task(context=ctx, model_id=model["id"], payload={"input_text": "[1,2,3]"}, idempotency_key="partial-intent")
    assert service.start_task(context=ctx, model_id=model["id"], payload={}, idempotency_key="partial-intent")["status"] == "ready"


def test_private_explicit_responses_endpoint_is_not_rewritten_to_chat():
    class Adapter:
        def __getattr__(self, key):
            return lambda *a, **kw: key
    config = {"provider": "custom", "model": "configured-model", "base_url": "https://approved.example/v1/responses"}
    with universal_llm.registry_scope(Adapter()):
        assert universal_llm._endpoint(config) == config["base_url"]
