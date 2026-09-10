"""Selected Persona -> same SF Chat store -> existing worker, disposable only.

The actual named local executor echoes text, not a solution. These are API/
repository/worker contract tests, not a visual pass or a credentialed model run.
"""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app import durable, local_worker
from app.ai_lab import chief_agent
from app.ai_control_center import contracts as c
from app.ai_control_center import domain_gateway as gateway, model_chat, model_evaluation, test_executor
from app.ai_control_center.model_service import ModelService
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_domain_gateway import ordinary
from tests.test_agent_world_live_gateway import isolated_runtime, owner
from tests.test_agent_world_models import Secrets, context as make_context


MESSAGE = "Объясни разницу между полученным ответом и решением человека по нему."


@pytest.fixture
def persona_chat(ordinary, tmp_path, monkeypatch):
    monkeypatch.setenv("NT_ANALYZER_ROOT", str(tmp_path))
    monkeypatch.setenv(test_executor.ENV, ordinary.scope["workspace_id"])
    monkeypatch.setattr(local_worker, "_MODEL_RECOVERY_STATE", {"root": "", "at": 0.0, "after_id": ""})
    monkeypatch.setattr(chief_agent.paths, "REGISTRY_DIR", tmp_path / "chat-registry")
    monkeypatch.setattr(chief_agent.paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chief_agent, "_explicit_production", lambda: False)
    path, secrets, calls, running = tmp_path / "persona-chat.sqlite", Secrets(), [], []
    authorized = gateway.access(ordinary.scope)

    def repository(auth):
        auth["admit"]()
        return SQLiteAgentWorldRepository(path, read_only=auth.get("read_only", False))

    def execute(**kwargs):
        calls.append(kwargs)
        running.append(service.task_detail(context=authorized["context"], task_id=kwargs["request_id"]))
        return test_executor.execute(**kwargs)

    def models(auth, repo=None):
        return ModelService(repo or repository(auth), secrets=secrets, executor=execute,
            admit=lambda context, operation, estimate: gateway._model_admit(auth, context, operation, estimate),
            enqueue=lambda **kwargs: gateway.enqueue_model(auth, **kwargs))

    monkeypatch.setattr(gateway, "repository", repository)
    monkeypatch.setattr(gateway, "models", models)
    service, context = models(authorized), authorized["context"]
    policy = service._put(context, {"version": "isolated-persona-chat-fixture"})
    persona = service._ensure(context, c.Persona, uuid4(), uuid4(), policy,
        display_name="Ответчик · isolated fixture", profile=service._put(context,
            {"description": "Synthetic test identity only", "style": "Коротко и с ограничениями."}))
    persona = service._walk(context, persona, "active")
    payload = {"label": "Selected Persona connection", "provider": "deepseek", "model": "deepseek-v4-flash",
        "api_key": "isolated-in-memory-secret", "persona_id": str(persona.header.entity_id)}
    model = service.connect(context=context, payload=payload, idempotency_key="persona-chat-connect")
    conversation = "AW-persona-" + uuid4().hex[:20]
    chief_agent.create_conversation("Isolated Persona chat", conversation_id=conversation,
        scope=authorized["chat_scope"])
    return SimpleNamespace(account=ordinary, root=tmp_path, context=context, authorized=authorized,
        service=service, model=model, persona=persona, payload=payload, conversation=conversation,
        calls=calls, running=running, secrets=secrets)


def _rows(fixture):
    return chief_agent.read_jsonl(chief_agent._conversation_file(fixture.conversation,
        scope=fixture.authorized["chat_scope"]))


def _jobs(fixture):
    return durable.list_worker_jobs(fixture.root, kind="agent_world_model")


def _start(fixture, *, key="persona-chat-request", message=MESSAGE, revision=None, persona_id=None):
    return model_chat.try_persona(message=message, authorized=fixture.authorized,
        service=fixture.service, persona_id=persona_id or str(fixture.persona.header.entity_id),
        persona_revision=fixture.persona.header.revision if revision is None else revision,
        conversation_id=fixture.conversation, request_id=key, user_message="@Ответчик: " + message)


def test_selected_persona_uses_saved_user_message_and_normal_worker_then_awaits_review(persona_chat):
    fixture = persona_chat
    accepted = _start(fixture)
    assert accepted["ok"] is True and accepted["conversation_id"] == fixture.conversation
    task_id = accepted["task_id"]
    rows = _rows(fixture)
    users = [row for row in rows if row.get("role") == "user"]
    assert len(users) == 1 and users[0]["content"] == "@Ответчик: " + MESSAGE
    assert users[0]["user_uuid"] == str(fixture.context.user_uuid)
    assert users[0]["workspace_id"] == fixture.context.scope.workspace_id
    pending = fixture.service.task_detail(context=fixture.context, task_id=task_id)
    assert pending["message_id"] == users[0]["message_id"]  # Preserve existing legacy MSG identifiers.
    assert pending["conversation_id"] == fixture.conversation
    assert pending["persona_id"] == str(fixture.persona.header.entity_id)
    assert pending["lead"]["display_name"] == fixture.persona.display_name
    assert pending["display_status"] == "queued" and pending["task_class"] == "assistant_response"
    assert pending["verification_scope"] == pending["task"]["verification_scope"] == "transport_only"
    assert len(_jobs(fixture)) == 1 and not fixture.calls
    assert _jobs(fixture)[0]["worker_job_id"] == "wj_aw_model_" + UUID(task_id).hex

    source_job = local_worker.run_once(worker_id="persona-source-worker")
    assert source_job["status"] == "succeeded" and len(fixture.calls) == 1
    assert len(fixture.running) == 1 and fixture.running[0]["display_status"] == "running"
    assert fixture.calls[0]["max_output_tokens"] <= 512 and "tools" not in fixture.calls[0]
    result = fixture.service.task_detail(context=fixture.context, task_id=task_id)
    assert result["display_status"] == "awaiting_review"
    assert result["verification_scope"] == result["task"]["verification_scope"] == "transport_only"
    assert result["human_review"]["status"] == "pending"
    assert result["source_kind"] == "synthetic_model_response" and result["synthetic"] is True
    assert result["actual_model"] == test_executor.EXECUTOR and result["external_call"] is False
    assert result["result_text"].startswith("SYNTHETIC")
    proof = result["evaluation"]
    assert proof["evaluator"] == "transport_response_verifier"
    assert proof["observed_score_pct"] is None and proof["quality_claim"] is False
    assert proof["semantic_verified"] is False and proof["rating_effect"] == "none"
    assert proof["requires_human_review"] is True

    delivery_job = local_worker.run_once(worker_id="persona-history-worker")
    assert delivery_job["status"] == "succeeded" and delivery_job["result"]["status"] == "delivered"
    reports = [row for row in _rows(fixture) if row.get("role") == "assistant" and row.get("message_kind") == "report"]
    assert len(reports) == 1
    report = reports[0]
    assert report["user_uuid"] == str(fixture.context.user_uuid)
    action = next(item for item in report["actions"] if item.get("task_id") == task_id)
    assert action["status"] == "awaiting_review"
    assert action["verification"]["scope"] == "transport_only"
    assert action["verification"]["quality_claim"] is False
    assert action["verification"]["semantic_verified"] is False
    assert "автоматически не оценены" in report["content"]
    assert "Проверка владельцем: ожидается" in report["content"]
    assert "Независимая проверка: PASS" not in report["content"]

    # Existing ingress and the worker cannot re-run the provider on retry.
    replayed = _start(fixture)
    assert replayed["task_id"] == task_id
    assert len([row for row in _rows(fixture) if row.get("role") == "user"]) == 1
    assert len(fixture.calls) == 1
    observations = fixture.service.evaluations(context=fixture.context,
        model_id=fixture.model["id"], rubric_key="assistant_response")
    assert observations["score_pct"] is None and observations["sample_size"] == 0


def _enable_persona_v2(persona_chat, monkeypatch):
    from app.ai_control_center.flags import Flag, FlagRule

    original_flags = gateway.live_gateway.flag_snapshot

    def flags(context):
        snapshot = original_flags(context)
        rules = tuple(rule for rule in snapshot.rules if rule.flag != Flag.AI_EXECUTION_V2)
        rules += tuple(FlagRule(environment=context.scope.environment, workspace_id=workspace,
            flag=Flag.AI_EXECUTION_V2, enabled=True) for workspace in (None, context.scope.workspace_id))
        return replace(snapshot, rules=rules)

    monkeypatch.setattr(gateway.live_gateway, "flag_snapshot", flags)
    persona_chat.authorized["snapshot"] = flags(persona_chat.context)


def test_selected_persona_with_execution_v2_uses_same_approved_identity(persona_chat, monkeypatch):
    """Browser regression: valid selection traverses the actual enabled V2.

    This is the normal Chat/queue/worker path with the existing V2 gate enabled
    for this disposable scope. No scope verifier or transport is bypassed.
    """
    _enable_persona_v2(persona_chat, monkeypatch)
    test_selected_persona_uses_saved_user_message_and_normal_worker_then_awaits_review(persona_chat)
    from app.ai_control_center import execution_v2
    task_id = _jobs(persona_chat)[0]["payload"]["task_id"]
    controller = execution_v2.projection(persona_chat.service, persona_chat.context, task_id)
    assert controller["status"] == "succeeded" and controller["human_accepted"] is False


@pytest.mark.parametrize("change", ["revision", "entity_id", "remove"])
def test_execution_v2_still_refuses_changed_selected_persona_checkpoint(persona_chat, monkeypatch, change):
    from app.ai_control_center import execution_v2

    fixture = persona_chat
    _enable_persona_v2(fixture, monkeypatch)
    accepted = _start(fixture)
    task_id = accepted["task_id"]
    _, approved, _ = execution_v2._load(fixture.service, fixture.context, task_id)
    task = fixture.service._get(fixture.context, EntityKind.TASK, task_id)
    checkpoint = fixture.service._json(fixture.context, task.checkpoint)
    if change == "remove":
        checkpoint.pop("persona_selection")
    else:
        checkpoint["persona_selection"][change] = 999 if change == "revision" else str(uuid4())
    fixture.service._change(fixture.context, task, checkpoint=fixture.service._put(fixture.context, checkpoint))
    with pytest.raises(ContractError, match="execution_v2_approved_scope_changed"):
        execution_v2._scope(fixture.service, fixture.context, task_id, approved)
    assert fixture.calls == []
    assert len(_jobs(fixture)) == 1  # History/queue is not erased to hide the refusal.


def test_selection_revision_changed_before_ingress_denies_without_enqueue(persona_chat):
    fixture = persona_chat
    fixture.service._change(fixture.context, fixture.persona, display_name="Changed after selection")
    with pytest.raises(ContractError, match="persona_selection_changed"):
        _start(fixture)
    assert not _jobs(fixture) and not fixture.calls
    assert not [row for row in _rows(fixture) if row.get("role") == "user"]


def test_persona_changed_between_chat_selection_and_task_constructor_denies(persona_chat, monkeypatch):
    fixture, original = persona_chat, persona_chat.service.start_task

    def changed_before_constructor(**kwargs):
        fixture.service._change(fixture.context, fixture.persona, display_name="Changed immediately before enqueue")
        return original(**kwargs)

    monkeypatch.setattr(fixture.service, "start_task", changed_before_constructor)
    with pytest.raises(ContractError, match="persona_selection_changed"):
        _start(fixture)
    assert not _jobs(fixture) and not fixture.calls
    assert len([row for row in _rows(fixture) if row.get("role") == "user"]) == 1
    assert not [row for row in _rows(fixture) if row.get("role") == "assistant"]


def test_persona_revision_changed_after_enqueue_blocks_before_transmission(persona_chat):
    fixture = persona_chat
    accepted = _start(fixture)
    fixture.service._change(fixture.context, fixture.persona, display_name="Changed while queued")
    local_worker.run_once(worker_id="persona-cas-worker")
    result = fixture.service.task_detail(context=fixture.context, task_id=accepted["task_id"])
    assert result["status"] in {"failed", "blocked"}
    assert result["error_code"] == "persona_selection_changed"
    assert not fixture.calls and result["evaluation"] is None
    assert result["lead"]["display_name"] == fixture.persona.display_name


@pytest.mark.parametrize("state", ["unbound", "ambiguous", "suspended", "foreign_owner", "foreign_workspace"])
def test_unavailable_or_ambiguous_persona_never_falls_back_to_another_model(persona_chat, state):
    fixture = persona_chat
    selected_id, expected = str(fixture.persona.header.entity_id), "persona_selection_unavailable"
    if state == "unbound":
        fixture.service.disconnect(context=fixture.context, model_id=fixture.model["id"])
        expected = "persona_model_required"
    elif state == "ambiguous":
        fixture.service.connect(context=fixture.context, payload={**fixture.payload, "label": "Second binding"},
            idempotency_key="persona-ambiguous-binding")
        expected = "persona_model_ambiguous"
    elif state == "suspended":
        fixture.service._change(fixture.context, fixture.persona, "suspended")
        expected = "persona_selection_inactive"
    else:
        other = make_context(workspace=fixture.context.scope.workspace_id if state == "foreign_owner" else "ws_other_persona",
            user=uuid4() if state == "foreign_owner" else fixture.context.user_uuid)
        policy = fixture.service._put(other, {"version": "foreign-test-data"})
        foreign = fixture.service._ensure(other, c.Persona, uuid4(), uuid4(), policy,
            display_name="Foreign test Persona", profile=fixture.service._put(other, {"description": "Not owned here"}))
        fixture.service._walk(other, foreign, "active")
        selected_id = str(foreign.header.entity_id)
    with pytest.raises(ContractError, match=expected):
        _start(fixture, persona_id=selected_id)
    assert not _jobs(fixture) and not fixture.calls
    assert not [row for row in _rows(fixture) if row.get("role") == "user"]


@pytest.mark.parametrize("reference", ["dict", "wrong_kind", "foreign_scope"])
def test_persona_constructor_accepts_only_exact_typed_same_scope_reference(persona_chat, reference):
    fixture = persona_chat
    ref = fixture.persona.ref()
    if reference == "dict":
        ref = c.primitive(ref)
    elif reference == "wrong_kind":
        ref = replace(ref, kind=EntityKind.MODEL)
    else:
        ref = replace(ref, scope=c.TenantScope(environment=c.Environment.DEVELOPMENT, workspace_id="ws_other_persona"))
    with pytest.raises(ContractError, match="persona_selection_invalid"):
        fixture.service.start_task(context=fixture.context, model_id=fixture.model["id"],
            payload={"rubric_key": "assistant_response", "input_text": MESSAGE},
            idempotency_key="persona-constructor-" + reference, _persona=ref)
    assert not _jobs(fixture) and not fixture.calls


@pytest.mark.parametrize("keyword", ["_routing", "_delegation", "_handoff", "_comparison_spec",
                                    "comparison_id", "comparison_title", "_sealed_spec"])
def test_assistant_request_cannot_be_routed_delegated_or_inserted_into_comparison(persona_chat, keyword):
    fixture = persona_chat
    spec = model_evaluation.prepare("assistant_response", MESSAGE)
    value = spec if keyword == "_sealed_spec" else "forbidden" if keyword in {"comparison_id", "comparison_title"} else {}
    with pytest.raises(ContractError, match="assistant_response_direct_only"):
        fixture.service.start_task(context=fixture.context, model_id=fixture.model["id"],
            payload={"rubric_key": "assistant_response", "input_text": MESSAGE},
            idempotency_key="persona-direct-" + keyword, **{keyword: value})
    assert not _jobs(fixture) and not fixture.calls


def test_comparison_public_service_path_rejects_assistant_response_before_any_child(persona_chat):
    fixture = persona_chat
    other = fixture.service.connect(context=fixture.context, payload={**fixture.payload, "label": "Comparison binding"},
        idempotency_key="persona-comparison-other")
    with pytest.raises(ContractError, match="assistant_response_direct_only"):
        fixture.service.start_comparison(context=fixture.context,
            payload={"title": "Not a quality experiment", "model_ids": [fixture.model["id"], other["id"]],
                "rubric_key": "assistant_response", "input_text": MESSAGE}, idempotency_key="persona-no-comparison")
    assert not _jobs(fixture) and not fixture.calls
    assert not list(fixture.service._all(fixture.context, EntityKind.TASK))


def test_selected_persona_v2_result_is_reviewed_to_completion_without_a_second_call(persona_chat, monkeypatch):
    """The whole path a person walks: select, ask, read, decide.

    Execution V2 is actually enabled, nothing is bypassed, and the decision is
    taken through the same gateway mutation the panel uses. Accepting a result
    is a human record, not a re-run and not a quality claim.
    """
    fixture = persona_chat
    _enable_persona_v2(fixture, monkeypatch)
    test_selected_persona_uses_saved_user_message_and_normal_worker_then_awaits_review(fixture)
    task_id = _jobs(fixture)[0]["payload"]["task_id"]

    pending = fixture.service.task_detail(context=fixture.context, task_id=task_id)
    assert pending["display_status"] == "awaiting_review"
    assert pending["human_review"]["status"] == "pending"
    identity = (pending["persona_id"], pending["lead"]["display_name"])
    assert identity == (str(fixture.persona.header.entity_id), fixture.persona.display_name)

    accepted = gateway.mutate(fixture.authorized, "tasks", task_id, "review_result", {
        "payload": {"decision": "accept", "source_sha256": pending["human_review"]["source_sha256"],
                    "comment": "Явная проверка полученного ответа, не оценка качества модели."},
        "expected_revision": pending["revision"], "idempotency_key": "persona-chat-human-review"})
    assert accepted["chat_delivery"]["problems"] == [], accepted

    done = fixture.service.task_detail(context=fixture.context, task_id=task_id)
    assert done["display_status"] == "completed"
    assert done["human_review"]["status"] == "accepted"
    assert done["human_review"]["quality_claim"] is False
    # The identity that answered is the identity on the completed record.
    assert (done["persona_id"], done["lead"]["display_name"]) == identity
    assert done["source_kind"] == "synthetic_model_response" and done["synthetic"] is True
    assert done["actual_model"] == test_executor.EXECUTOR and done["external_call"] is False
    # Deciding on a result never asks the provider again.
    assert len(fixture.calls) == 1

    from app.ai_control_center import execution_v2
    controller = execution_v2.projection(fixture.service, fixture.context, task_id)
    assert controller["status"] == "succeeded"

    overview = gateway.enrich_overview(fixture.authorized)
    row = next(item for item in overview["tasks"] if item["id"] == task_id)
    assert row["display_status"] == "completed" and row["needs_attention"] is False
    assert not [item for item in overview["attention"] if item["id"] == task_id]

    # Replaying the same decision is not a second acceptance.
    gateway.mutate(fixture.authorized, "tasks", task_id, "review_result", {
        "payload": {"decision": "accept", "source_sha256": pending["human_review"]["source_sha256"],
                    "comment": "Явная проверка полученного ответа, не оценка качества модели."},
        "expected_revision": pending["revision"], "idempotency_key": "persona-chat-human-review"})
    assert fixture.service.task_detail(context=fixture.context,
                                       task_id=task_id)["display_status"] == "completed"
    assert len(fixture.calls) == 1
