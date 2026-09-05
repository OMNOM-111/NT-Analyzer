"""Explicit fact handoff: disposable app bytes, SF Chat and model worker seam.

No live owner data, providers, credentials, browser, trading or external calls.
"""
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ai_control_center import contracts as c, application_chat, live_charts, model_chat, result_handoff
from app.ai_control_center.states import ContractError, EntityKind
from app.ai_lab import chief_agent
from tests.test_agent_world_models import setup as model_setup, context, response
from tests.test_agent_world_application_chat import (authorized as chat_authorized, _plan,
    queue_service, canonical_queue, _terminal, _body)


def target(model_setup, *, key="handoff-target-one", same_persona=False):
    service, ctx, payload, *_ = model_setup
    if same_persona:
        identity = payload["persona_id"]
    else:
        policy = service._put(ctx, {"synthetic": False, "fixture": "handoff-only"})
        persona = service._ensure(ctx, c.Persona, uuid4(), uuid4(), policy, display_name="Получатель " + key,
            profile=service._put(ctx, {"description": "isolated handoff test persona"}))
        persona = service._walk(ctx, persona, "active")
        identity = str(persona.header.entity_id)
    return service.connect(context=ctx, payload={**payload, "persona_id": identity,
        "label": "Receiving model", "api_key": "separate-fixture-target-key"}, idempotency_key=key)


@pytest.fixture
def env(model_setup, chat_authorized, queue_service, request):
    service, ctx, *_ = model_setup
    kind = getattr(request, "param", "chart")
    _, source = _plan(model_setup, chat_authorized, kind=kind)
    dispatch = application_chat.finish_dispatch(chat_authorized, service, source)
    if kind == "chart":
        live_charts.complete(_body({"command_id": dispatch["source_id"]}), chat_authorized)
    else:
        _terminal({"job_id": dispatch["source_id"]})
    assert application_chat.reconcile(chat_authorized, service)["completed"] == [source["id"]]
    source = service.task_detail(context=ctx, task_id=source["id"])
    receiver = target(model_setup)
    calls, enqueued = [], []
    def execute(**kwargs):
        calls.append(kwargs)
        return response(kwargs["prompt"].split("Data: ", 1)[1])
    service.executor = execute
    service.enqueue = lambda **kwargs: enqueued.append(kwargs["task_id"])
    service.chat_scope = dict(chat_authorized["chat_scope"])
    return SimpleNamespace(setup=model_setup, service=service, ctx=ctx, authorized=chat_authorized,
        source=source, receiver=receiver, calls=calls, enqueued=enqueued)


def start(env, *, key="explicit-handoff-one", **kwargs):
    return result_handoff.start(env.authorized, env.service, kwargs.get("task_id", env.source["id"]),
        kwargs.get("target_model_id", env.receiver["id"]), key)


def messages(env):
    return chief_agent.read_jsonl(chief_agent._conversation_file(env.source["conversation_id"],
        scope=env.authorized["chat_scope"]))


def test_handoff_seals_dependency_and_correlations_before_enqueue_in_same_existing_chat(env):
    original = messages(env)
    source_task = env.service._get(env.ctx, EntityKind.TASK, env.source["id"])
    assert env.source["actions"] == ["handoff"]
    captured = []
    def enqueue(**kwargs):
        child = env.service._get(env.ctx, EntityKind.TASK, kwargs["task_id"])
        assert child.dependencies == (source_task.ref(),) and child.status == "ready"
        checkpoint = env.service._json(env.ctx, child.checkpoint)
        assert checkpoint["handoff"]["parent_task"] == c.primitive(source_task.ref())
        captured.append(child)
    env.service.enqueue = enqueue
    result = start(env)
    assert len(captured) == 1 and not env.calls and result["status"] == "ready"
    assert result["actions"] == ["cancel"]
    child = captured[0]
    assert child.header.correlation_id == source_task.header.correlation_id
    assert result["conversation_id"] == env.source["conversation_id"]
    assert result["message_id"] != env.source["message_id"]
    assert result["handoff"]["source_message_id"] == env.source["message_id"]
    assert result["handoff"]["parent_task_id"] == env.source["id"]
    assert result["handoff"]["target_persona_id"] == env.receiver["persona_id"]
    intent = env.service._get(env.ctx, EntityKind.INTENT, child.intent.entity_id)
    execution = env.service._execution(env.ctx, child.header.entity_id)
    decision = env.service._get(env.ctx, EntityKind.DECISION, execution.decision.entity_id)
    assert all(row.header.correlation_id == child.header.correlation_id for row in (intent, execution, decision))
    current = messages(env)
    assert current[:len(original)] == original and len(current) == len(original) + 2
    assert env.source["id"] in current[-1]["content"]
    assert "→" in current[-1]["content"] and result_handoff.LIMITATION in current[-1]["content"]


def test_provider_gets_only_allowlisted_facts_and_existing_single_delivery_appends_final(env):
    secrets_before = dict(env.service.secrets.values)
    pending = start(env)
    result = env.service.execute(context=env.ctx, task_id=pending["id"])
    assert result["status"] == "succeeded" and result["evaluation"]["passed"]
    assert "handoff" not in result["actions"]
    assert result["application_evaluation"] is None and result["task_class"] == "extract_facts"
    assert result_handoff.LIMITATION in result["result_text"]
    assert len(env.calls) == 1 and env.calls[0]["model"].header.entity_id.hex == env.receiver["id"].replace("-", "")
    facts = result["handoff"]["facts"]
    assert set(facts) == {"source_kind", "source_id", "source_sha256", "instrument", "timeframe", "rendered_bar_count", "total_bar_count"}
    assert facts["rendered_bar_count"] == "40" and facts["total_bar_count"] == "200"
    assert "separate-fixture-target-key" not in env.calls[0]["prompt"]
    assert "capture" not in env.calls[0]["prompt"] and "image/png" not in env.calls[0]["prompt"]
    assert dict(env.service.secrets.values) == secrets_before
    assert env.service.evaluations(context=env.ctx, model_id=env.receiver["id"])["sample_size"] == 0
    saved = model_chat.completion(env.authorized, env.service, result["id"])
    count = len(messages(env))
    delivered = model_chat.deliver(env.authorized, env.service, task_id=result["id"],
        event_id=saved["event_id"], checkpoint_sha256=saved["checkpoint_sha256"], events=env.service.repository.events)
    assert delivered["status"] == "delivered" and len(messages(env)) == count + 1
    assert result_handoff.LIMITATION in messages(env)[-1]["content"]
    replay = model_chat.deliver(env.authorized, env.service, task_id=result["id"],
        event_id=saved["event_id"], checkpoint_sha256=saved["checkpoint_sha256"], events=env.service.repository.events)
    assert replay["replayed"] and len(messages(env)) == count + 1 and len(env.calls) == 1


@pytest.mark.parametrize("env", ["backtest"], indirect=True)
def test_backtest_handoff_names_commission_basis_and_omits_source_files(env):
    pending = start(env)
    facts = pending["handoff"]["facts"]
    assert facts["strategy"] == "AWRegisteredStrategy" and facts["instrument"] == "MNQ 09-26"
    assert facts["source_kind"] == "ninjatrader_report" and facts["trades"] == "2"
    assert "net_profit_after_commission" in facts
    assert not {"report_url", "trades_json", "bars", "raw_result", "prompt", "memory"} & set(facts)
    result = env.service.execute(context=env.ctx, task_id=pending["id"])
    assert result["status"] == "succeeded" and len(env.calls) == 1


def test_duplicate_ingress_and_execute_never_add_second_child_or_call(env):
    one = start(env)
    original = messages(env)
    two = start(env)
    assert one["id"] == two["id"] and messages(env) == original
    assert env.enqueued == [one["id"]]
    first = env.service.execute(context=env.ctx, task_id=one["id"])
    second = env.service.execute(context=env.ctx, task_id=one["id"])
    assert first == second and len(env.calls) == 1


def test_same_idempotency_key_cannot_change_target_after_acknowledgment(env):
    start(env)
    other = target(env.setup, key="handoff-target-two")
    original = messages(env)
    with pytest.raises(ContractError, match="idempotency_conflict"):
        start(env, target_model_id=other["id"])
    assert messages(env) == original and not env.calls and len(env.enqueued) == 1


def test_changed_target_rejected_after_only_user_ingress_was_persisted(env, monkeypatch):
    original = env.service.start_task
    monkeypatch.setattr(env.service, "start_task", lambda **kwargs: (_ for _ in ()).throw(OSError("fixture crash before domain write")))
    with pytest.raises(OSError):
        start(env)
    assert not env.enqueued
    monkeypatch.setattr(env.service, "start_task", original)
    other = target(env.setup, key="handoff-target-two")
    with pytest.raises(ContractError, match="idempotency_conflict"):
        start(env, target_model_id=other["id"])
    restored = start(env)
    assert restored["status"] == "ready" and env.enqueued == [restored["id"]] and not env.calls


def test_same_request_recovers_crash_after_intent_before_task(env, monkeypatch):
    original = env.service._ensure
    def interrupted(context, cls, *args, **kwargs):
        if cls is c.Task and kwargs.get("dependencies"):
            raise OSError("fixture partial intent")
        return original(context, cls, *args, **kwargs)
    monkeypatch.setattr(env.service, "_ensure", interrupted)
    with pytest.raises(OSError):
        start(env)
    assert not env.enqueued
    monkeypatch.setattr(env.service, "_ensure", original)
    result = start(env)
    assert result["status"] == "ready" and env.enqueued == [result["id"]]


def revise_source(env, monkeypatch):
    # Finalized tasks are immutable in the real repository. Inject a stale
    # read to prove that a future adapter/store fault cannot silently resnapshot.
    original = env.service.repository.get
    def stale(**kwargs):
        row = original(**kwargs)
        if row is not None and str(row.header.entity_id) == env.source["id"]:
            return replace(row, header=replace(row.header, revision=row.header.revision + 1))
        return row
    monkeypatch.setattr(env.service.repository, "get", stale)


def test_source_revision_changed_while_queued_blocks_before_transmit(env, monkeypatch):
    pending = start(env)
    revise_source(env, monkeypatch)
    result = env.service.execute(context=env.ctx, task_id=pending["id"])
    assert result["status"] == "blocked" and result["error_code"] == "handoff_source_changed"
    assert result["evaluation"] is None and not env.calls


def test_same_key_does_not_resnapshot_changed_source(env, monkeypatch):
    start(env)
    revise_source(env, monkeypatch)
    original = messages(env)
    with pytest.raises(ContractError, match="idempotency_conflict"):
        start(env)
    assert messages(env) == original and len(env.enqueued) == 1


def test_source_artifact_disappearing_while_queued_cannot_trigger_provider(env, monkeypatch):
    pending = start(env)
    missing = env.source["application_evaluation"]["artifact_ids"][0]
    original = env.service.repository.get_artifact
    def unavailable(**kwargs):
        return None if str(kwargs["reference"].artifact_id) == missing else original(**kwargs)
    monkeypatch.setattr(env.service.repository, "get_artifact", unavailable)
    result = env.service.execute(context=env.ctx, task_id=pending["id"])
    assert result["error_code"] == "handoff_source_unavailable" and not env.calls


@pytest.mark.parametrize("foreign", ["user", "workspace"])
def test_foreign_source_denied_without_chat_or_queue_write(env, foreign):
    other = context(user=uuid4()) if foreign == "user" else context(workspace="ws_handoff_foreign", user=env.ctx.user_uuid)
    original = messages(env)
    with pytest.raises(ContractError, match="not_found"):
        result_handoff.start({**env.authorized, "context": other}, env.service, env.source["id"],
            env.receiver["id"], "foreign-source-denied")
    assert messages(env) == original and not env.calls and not env.enqueued


@pytest.mark.parametrize("same", ["model", "persona"])
def test_target_must_be_a_different_persona_not_just_different_connection(env, same):
    destination = env.source["model_id"] if same == "model" else target(env.setup, key="same-persona-other-model", same_persona=True)["id"]
    with pytest.raises(ContractError, match="different_persona_required"):
        start(env, target_model_id=destination)
    assert not env.enqueued and not env.calls


@pytest.mark.parametrize("phase", ["start", "execute"])
def test_inactive_target_cannot_receive_facts(env, phase):
    pending = start(env) if phase == "execute" else None
    env.service.disconnect(context=env.ctx, model_id=env.receiver["id"])
    if pending:
        result = env.service.execute(context=env.ctx, task_id=pending["id"])
        assert result["error_code"] == "model_connection_inactive"
    else:
        with pytest.raises(ContractError, match="target_inactive"):
            start(env)
    assert not env.calls


def test_child_cannot_delegate_again(env):
    child = start(env)
    completed = env.service.execute(context=env.ctx, task_id=child["id"])
    assert completed["status"] == "succeeded"
    with pytest.raises(ContractError, match="recursive_denied"):
        start(env, task_id=child["id"], target_model_id=env.source["model_id"], key="recursive-denied")
    assert len(env.enqueued) == len(env.calls) == 1


def test_pending_application_and_plan_only_are_not_handoff_sources(model_setup, chat_authorized):
    service, ctx, *_ = model_setup
    _, source = _plan(model_setup, chat_authorized)
    assert "handoff" not in source["actions"]
    receiver = target(model_setup)
    with pytest.raises(ContractError, match="verified_source_required"):
        result_handoff.start(chat_authorized, service, source["id"], receiver["id"], "pending-not-source")


@pytest.mark.parametrize("operation", ["task", "provider_transmit"])
def test_fresh_capability_or_budget_denial_prevents_transmit(env, operation):
    pending = start(env) if operation == "provider_transmit" else None
    original = env.service.admit
    def denied(context, current, estimate):
        if current == operation:
            raise ContractError("model_budget_exhausted")
        return original(context, current, estimate)
    env.service.admit = denied
    with pytest.raises(ContractError, match="budget_exhausted"):
        env.service.execute(context=env.ctx, task_id=pending["id"]) if pending else start(env)
    assert not env.calls


def test_revoked_session_at_ingress_and_after_queue_never_transmits(env):
    child = start(env)
    def revoked(*args):
        raise ContractError("agent_world_session_expired")
    env.authorized["admit"] = revoked
    with pytest.raises(ContractError, match="session_expired"):
        start(env, key="revoked-session-ingress")
    env.service.admit = revoked
    with pytest.raises(ContractError, match="session_expired"):
        env.service.execute(context=env.ctx, task_id=child["id"])
    assert not env.calls


def test_read_only_history_access_cannot_create_handoff(env):
    with pytest.raises(ContractError, match="human_required"):
        result_handoff.start({**env.authorized, "read_only": True}, env.service, env.source["id"],
            env.receiver["id"], "read-only-denied")
    assert not env.enqueued


def test_source_must_have_its_own_actual_user_message(env, monkeypatch):
    original = chief_agent.read_jsonl
    monkeypatch.setattr(chief_agent, "read_jsonl", lambda *args, **kwargs:
        [row for row in original(*args, **kwargs) if row.get("message_id") != env.source["message_id"]])
    with pytest.raises(ContractError, match="source_message_required"):
        start(env)
    assert not env.enqueued and not env.calls


@pytest.mark.parametrize("which", ["source", "child"])
def test_deleted_source_or_child_message_after_enqueue_blocks_paid_call(env, monkeypatch, which):
    child = start(env)
    missing = env.source["message_id"] if which == "source" else child["message_id"]
    original = chief_agent.read_jsonl
    monkeypatch.setattr(chief_agent, "read_jsonl", lambda *args, **kwargs:
        [row for row in original(*args, **kwargs) if row.get("message_id") != missing])
    result = env.service.execute(context=env.ctx, task_id=child["id"])
    assert result["status"] == "blocked" and result["error_code"] == "handoff_source_message_required"
    assert not env.calls


@pytest.mark.parametrize("scope", [None, {}, {"workspace_id": "ws_handoff_wrong", "user_uuid": "wrong"}])
def test_handoff_requires_trusted_composition_chat_scope_not_task_payload(env, scope):
    child = start(env)
    env.service.chat_scope = scope
    result = env.service.execute(context=env.ctx, task_id=child["id"])
    assert result["error_code"] == "handoff_chat_scope_required" and not env.calls


@pytest.mark.parametrize("field", ["conversation_id", "message_id"])
def test_missing_chat_identity_does_not_offer_handoff_action(env, monkeypatch, field):
    source = env.service._get(env.ctx, EntityKind.TASK, env.source["id"])
    original = env.service._json
    def missing(context, ref):
        value = original(context, ref)
        if ref == source.checkpoint:
            value[field] = None
        return value
    monkeypatch.setattr(env.service, "_json", missing)
    assert "handoff" not in env.service.task_detail(context=env.ctx, task_id=env.source["id"])["actions"]


@pytest.mark.parametrize("mutation", ["facts", "dependencies", "missing_packet"])
def test_corrupted_queued_packet_or_dependency_does_not_transmit(env, mutation):
    child = start(env)
    task = env.service._get(env.ctx, EntityKind.TASK, child["id"])
    checkpoint = env.service._json(env.ctx, task.checkpoint)
    if mutation == "dependencies":
        env.service._change(env.ctx, task, dependencies=())
    else:
        if mutation == "facts":
            checkpoint["handoff"]["facts"]["instrument"] = "OTHER 09-26"
        else:
            checkpoint.pop("handoff")
        env.service._change(env.ctx, task, checkpoint=env.service._put(env.ctx, checkpoint))
    result = env.service.execute(context=env.ctx, task_id=child["id"])
    assert result["status"] == "blocked" and result["evaluation"] is None and not env.calls


def test_http_style_payload_cannot_forge_trusted_dependency(env):
    for payload in ({"rubric_key": "extract_facts", "input_text": "x=1\ny=2", "handoff": {}},):
        with pytest.raises(ContractError, match="field_invalid"):
            env.service.start_task(context=env.ctx, model_id=env.receiver["id"], payload=payload,
                idempotency_key="forged-http-request")
    with pytest.raises(ContractError, match="sealed_source_required"):
        env.service.start_task(context=env.ctx, model_id=env.receiver["id"],
            payload={"rubric_key": "extract_facts", "input_text": "x=1\ny=2"},
            idempotency_key="forged-internal-record", _handoff={"parent": env.source["id"]})
    assert not env.enqueued and not env.calls
