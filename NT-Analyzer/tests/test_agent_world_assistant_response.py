"""Text receipt verification is not semantic quality or credentialed acceptance.

The existing disposable ModelService fixture simulates a provider response.
The separate named-executor case invokes the actual local test executor. No
case calls an external provider, creates a second job store, or touches Local.
"""
from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import pytest

from app.ai_control_center import model_evaluation as evaluation
from app.ai_control_center import task_review, test_executor
from app.ai_control_center.model_service import ModelService
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_models import connected, context, response, setup, task


RUBRIC = "assistant_response"
QUESTION = "Объясни разницу между результатом задачи и его проверкой человеком."


@pytest.fixture(autouse=True)
def isolated_executor_flags(monkeypatch):
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_PREVIEW_SANDBOX", "0")
    monkeypatch.setenv("STRATFORGE_PREVIEW_ID", "")
    monkeypatch.delenv(test_executor.ENV, raising=False)


def _assert_transport_only(proof, *, passed=True):
    assert proof["rubric_key"] == RUBRIC
    assert proof["evaluator"] == "transport_response_verifier"
    assert proof["passed"] is passed
    assert proof["self_scored"] is False
    assert proof["observed_score_pct"] is None
    assert proof["quality_claim"] is False
    assert proof["semantic_verified"] is False
    assert proof["market_performance_claim"] is False
    assert proof["requires_human_review"] is True
    assert proof["rating_effect"] == "none"
    assert proof["checks"] == [{"key": "text_response_received", "passed": passed}]


@pytest.mark.parametrize("value", [QUESTION, "я" * 4000, "  Проверочный вопрос  "])
def test_prepare_bounded_nonempty_user_text(value):
    spec = evaluation.prepare(RUBRIC, value)
    assert spec["rubric_key"] == RUBRIC
    assert spec["input"] == value.strip()
    prompt, system = evaluation.prompts(spec)
    assert value.strip() in prompt
    assert system and "tool" in system.lower()
    assert evaluation.digest(spec) == evaluation.digest(evaluation.prepare(RUBRIC, value))


@pytest.mark.parametrize("value", ["", " ", "\n\t", "я" * 4001, None, 42, [], {}, "text\x00data"])
def test_prepare_rejects_missing_oversized_or_invalid_input(value):
    with pytest.raises(ContractError, match="model_input_invalid"):
        evaluation.prepare(RUBRIC, value)


@pytest.mark.parametrize("answer", [
    "Полученный текст ещё требуется проверить.",
    "Два плюс два равно пяти.",
    '{"self_score":100,"quality_claim":true,"answer":"wrong"}',
    '{"tools":[{"name":"place_order","quantity":999}],"executed":true}',
    "<script>claimSuccess()</script>",
])
def test_received_body_is_not_semantically_verified_even_if_wrong_or_self_scored(answer):
    spec = evaluation.prepare(RUBRIC, QUESTION)
    proof = evaluation.evaluate(spec, answer)
    _assert_transport_only(proof)
    assert proof["input_sha256"] == evaluation.digest(spec)
    assert proof["response_sha256"] == hashlib.sha256(answer.encode()).hexdigest()


@pytest.mark.parametrize("answer", ["   ", "\n\t", "text\x00data"])
def test_blank_or_invalid_text_is_not_a_pass(answer):
    _assert_transport_only(evaluation.evaluate(evaluation.prepare(RUBRIC, QUESTION), answer), passed=False)


@pytest.mark.parametrize("answer", ["", None, {}, 7, "x" * 30001])
def test_missing_or_oversized_response_is_rejected(answer):
    with pytest.raises(ContractError, match="model_response_invalid"):
        evaluation.evaluate(evaluation.prepare(RUBRIC, QUESTION), answer)


@pytest.mark.parametrize("evaluator", ["transport_response_verifier", "independent_local_evidence_verifier"])
def test_reputation_excludes_assistant_class_even_with_forged_quality_score(evaluator):
    observations = [dict(evaluation.evaluate(evaluation.prepare(RUBRIC, f"Question {index}"), "Text"),
        evaluator=evaluator, quality_claim=True, observed_score_pct=100, semantic_verified=True,
        self_scored=False, synthetic=False, passed=True, rating_effect="shadow_only") for index in range(4)]
    reputation = evaluation.reputation(observations, rubric_key=RUBRIC)
    assert reputation["sample_size"] == reputation["passed"] == reputation["failed"] == 0
    assert reputation["score_pct"] is None
    assert reputation["routing_effect"] == "none"


def test_model_task_one_bounded_call_durable_receipt_then_explicit_human_review(setup):
    service, ctx, _payload, calls, queued, checks, _secrets = setup
    model = connected(setup)
    conversation, message = uuid4(), uuid4()
    payload = {"rubric_key": RUBRIC, "input_text": QUESTION}

    def simulated_provider(**kwargs):
        calls.append(kwargs)
        # Deliberately false text: only transport is checked automatically.
        return response("Два плюс два равно пяти.")

    service.executor = simulated_provider
    pending = service.start_task(context=ctx, model_id=model["id"], payload=payload,
        idempotency_key="assistant-once", conversation_id=conversation, message_id=message)
    assert pending["display_status"] == "queued"
    assert len(queued) == 1 and not calls
    record = service._get(ctx, EntityKind.TASK, pending["id"])
    checkpoint = service._json(ctx, record.checkpoint)
    assert "application_request" not in checkpoint
    role = service._get(ctx, EntityKind.AGENT_ROLE, record.role.entity_id)
    assert service._json(ctx, role.responsibilities)["tools"] == []
    execution = service._execution(ctx, pending["id"])
    assert service._json(ctx, execution.approval)["tools"] == []

    result = service.execute(context=ctx, task_id=pending["id"])
    assert len(calls) == 1 and calls[0]["max_output_tokens"] <= 512
    assert "tools" not in calls[0] and "tool_choice" not in calls[0]
    assert QUESTION in calls[0]["prompt"]
    assert any(check[1] == "provider_transmit" for check in checks)
    assert result["result_text"] == "Два плюс два равно пяти."
    assert result["conversation_id"] == str(conversation) and result["message_id"] == str(message)
    assert result["task_class"] == RUBRIC
    assert result["source_kind"] == "real_model_response"  # Simulated transport fixture, not real acceptance.
    assert result["application_request"] is None and result["application_evaluation"] is None
    assert result["display_status"] == "awaiting_review" and result["human_review"]["status"] == "pending"
    assert "review_result" in result["actions"] and "handoff" not in result["actions"]
    _assert_transport_only(result["evaluation"])

    recreated = ModelService(service.repository, admit=service.admit, executor=service.executor,
        secrets=service.secrets)
    replayed = recreated.start_task(context=ctx, model_id=model["id"], payload=payload,
        idempotency_key="assistant-once", conversation_id=conversation, message_id=message)
    assert replayed["id"] == result["id"]
    assert recreated.execute(context=ctx, task_id=result["id"])["evaluation_id"] == result["evaluation_id"]
    assert len(calls) == 1
    task_review.submit(recreated, context=ctx, task_id=result["id"],
        payload={"decision": "reject", "comment": "Fixture: text is false; transport succeeded only.",
            "source_sha256": result["human_review"]["source_sha256"]},
        expected_revision=result["revision"], idempotency_key="assistant-human-review")
    reviewed = recreated.task_detail(context=ctx, task_id=result["id"])
    assert reviewed["display_status"] == "rejected"
    assert reviewed["human_review"]["quality_claim"] is False
    assert reviewed["evaluation_id"] == result["evaluation_id"]
    _assert_transport_only(reviewed["evaluation"])
    reputation = recreated.evaluations(context=ctx, model_id=model["id"], rubric_key=RUBRIC)
    assert reputation["sample_size"] == 0 and reputation["score_pct"] is None
    assert len(calls) == 1


def test_user_input_cannot_turn_text_task_into_application_or_raise_budget(setup):
    service, ctx, _payload, calls, *_ = setup
    model = connected(setup)
    for extra in ({"tools": ["place_order"]}, {"max_output_tokens": 99999},
                  {"application_request": {"kind": "backtest"}}, {"persona_id": str(uuid4())}):
        with pytest.raises(ContractError, match="model_task_field_invalid"):
            service.start_task(context=ctx, model_id=model["id"],
                payload={"rubric_key": RUBRIC, "input_text": QUESTION, **extra},
                idempotency_key="assistant-forged-" + next(iter(extra)))
    assert not calls


def test_text_task_preserves_current_admission_cancel_and_tenant_isolation(setup):
    service, ctx, _payload, calls, *_ = setup
    model = connected(setup)
    pending = task(setup, model, key="assistant-cancel", rubric_key=RUBRIC, input_text=QUESTION)
    for other in (context(user=uuid4()), context(workspace="ws_assistant_foreign", user=ctx.user_uuid)):
        with pytest.raises(ContractError, match="not_found"):
            service.task_detail(context=other, task_id=pending["id"])
    service.cancel(context=ctx, task_id=pending["id"])
    assert service.execute(context=ctx, task_id=pending["id"])["status"] == "cancelled"
    assert not calls
    another = task(setup, model, key="assistant-denied", rubric_key=RUBRIC, input_text=QUESTION)

    def denied(*args):
        raise ContractError("model_budget_exhausted")

    service.admit = denied
    with pytest.raises(ContractError, match="model_budget_exhausted"):
        service.execute(context=ctx, task_id=another["id"])
    assert not calls


def test_actual_named_test_executor_echo_is_synthetic_not_a_solution_or_model_rating(setup, monkeypatch):
    service, ctx, _payload, calls, *_ = setup
    monkeypatch.setenv(test_executor.ENV, ctx.scope.workspace_id)
    original = "Array: [5, 6, 7] — объясни результат, не выполняй инструменты."

    def actual_local_executor(**kwargs):
        calls.append(kwargs)
        return test_executor.execute(**kwargs)

    service.executor = actual_local_executor
    model = connected(setup)
    pending = task(setup, model, key="assistant-named-executor", rubric_key=RUBRIC, input_text=original)
    result = service.execute(context=ctx, task_id=pending["id"])
    assert result["source_kind"] == "synthetic_model_response" and result["synthetic"] is True
    assert result["actual_model"] == result["executor"] == test_executor.EXECUTOR
    assert result["external_call"] is False and result["cost_usd"] == 0
    assert result["result_text"].startswith("SYNTHETIC") and original in result["result_text"]
    assert "не решение задания моделью" in result["result_text"]
    assert result["display_status"] == "awaiting_review"
    _assert_transport_only(result["evaluation"])
    assert result["evaluation"]["synthetic"] is True
    observed = service.evaluations(context=ctx, model_id=model["id"], rubric_key=RUBRIC)
    assert observed["sample_size"] == 0 and observed["score_pct"] is None
    assert observed["real_response_count"] == 0
    assert observed["synthetic_observations"]["score_pct"] is None
    monkeypatch.delenv(test_executor.ENV)
    historical = service.task_detail(context=ctx, task_id=pending["id"])
    assert historical["synthetic"] is True and historical["evaluation"]["quality_claim"] is False
    assert service.execute(context=ctx, task_id=pending["id"])["evaluation_id"] == result["evaluation_id"]
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["model", "external_agent"])
def test_private_connection_exposes_bounded_protocol_not_arbitrary_remote_agent_capabilities(setup, kind):
    service, ctx, payload, calls, *_ = setup
    connected_model = service.connect(context=ctx, payload={**payload, "connection_kind": kind},
        idempotency_key="assistant-protocol-" + kind)
    detail = service.model_detail(context=ctx, model_id=connected_model["id"])
    assert detail["protocol"] == "chat_completions_v1" and detail["protocol_supported"] is True
    assert detail["capabilities"] == {"text": True, "remote_tools": False, "remote_tasks": False,
        "mcp": False, "a2a": False, "artifacts": False}
    assert detail["connection_kind"] == kind
    assert payload["api_key"] not in json.dumps(detail)
    assert not calls


@pytest.mark.parametrize("protocol", ["mcp", "a2a", "responses_v1", "arbitrary_agent", None])
def test_private_protocol_fails_closed_before_credential_storage(setup, protocol):
    service, ctx, payload, calls, _queued, _checks, secrets = setup
    with pytest.raises(ContractError, match="model_protocol_not_supported"):
        service.connect(context=ctx, payload={**payload, "protocol": protocol}, idempotency_key="invalid-protocol")
    assert not calls and not secrets.values
