"""Disposable synthetic/real receipt lineage; no external provider calls.

The production local-test executor is used through ModelService and the
existing durable worker. The real-provider cases use the pre-existing unit
fixture callback and are contract evidence, never credentialed acceptance.
"""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from uuid import UUID, uuid4, uuid5

import pytest

from app import local_worker
from app.ai_control_center import domain_gateway, model_chat, model_service, task_review, test_executor
from app.ai_control_center.model_service import ModelService, receipt_provenance
from app.ai_control_center.states import ContractError, EntityKind
from app.ai_lab import chief_agent
from tests.test_agent_world_models import connected, response, setup, task
from tests.test_agent_world_model_delivery import (
    _reports, _rows, delivery, isolated_runtime, ordinary, owner,
)


def _enable(monkeypatch, workspace):
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_PREVIEW_SANDBOX", "0")
    monkeypatch.setenv("STRATFORGE_PREVIEW_ID", "")
    monkeypatch.setenv(test_executor.ENV, workspace)


@pytest.fixture
def synthetic_setup(setup, monkeypatch):
    service, context, _payload, calls, *_ = setup
    _enable(monkeypatch, context.scope.workspace_id)

    def execute(**kwargs):
        calls.append(kwargs)
        return test_executor.execute(**kwargs)

    service.executor = execute
    return setup


@pytest.fixture
def synthetic_delivery(delivery, monkeypatch):
    _enable(monkeypatch, delivery.context.scope.workspace_id)
    factory = domain_gateway.models

    def execute(**kwargs):
        delivery.calls.append(kwargs)
        return test_executor.execute(**kwargs)

    def models(authorized, repository=None):
        service = factory(authorized, repository)
        service.executor = execute
        return service

    delivery.service.executor = execute
    monkeypatch.setattr(domain_gateway, "models", models)
    return delivery


def _finish(fixture, model=None, key="provenance-task", **payload):
    service, context, *_ = fixture
    pending = task(fixture, model, key=key, **payload)
    return service.execute(context=context, task_id=pending["id"])


def _checkpoint(fixture, detail):
    service, context, *_ = fixture
    record = service._get(context, EntityKind.TASK, detail["id"])
    return record, service._json(context, record.checkpoint)


def test_test_executor_receipt_evaluation_task_and_connection_agree(synthetic_setup):
    service, context, _payload, calls, *_ = synthetic_setup
    model = connected(synthetic_setup)
    pending = service.test(context=context, model_id=model["id"], idempotency_key="synthetic-connection")
    assert pending["result_origin"] == "awaiting_receipt" and not pending["provider_result_received"]
    detail = service.execute(context=context, task_id=pending["id"])
    record, checkpoint = _checkpoint(synthetic_setup, detail)
    receipt = service._json(context, checkpoint["receipt"])
    evaluation = service._get(context, EntityKind.EVALUATION, detail["evaluation_id"])
    proof = service._json(context, evaluation.evidence)
    for value in (receipt, proof, detail, detail["task"], detail["evaluation"], detail["outcomes"][0]):
        assert value["synthetic"] is True
        assert value["source_kind"] == "synthetic_model_response"
    assert receipt["source"] == "local_test_executor"
    assert receipt["executor"] == receipt["actual_model"] == test_executor.EXECUTOR
    assert receipt["external_call"] is False and receipt["cost_usd"] == 0
    assert proof["provider"] == detail["evaluation"]["provider"] == detail["response_provider"] == "local_test_executor"
    assert proof["configured_provider"] == detail["configured_provider"] == "deepseek"
    assert detail["status"] == record.status == "succeeded"
    assert detail["display_status"] == "verified_automatically"  # Connection check only.
    tested = service.model_detail(context=context, model_id=model["id"])
    assert tested["connected"] is False and tested["test_executor_verified"] is True
    assert tested["connection_verification"] == "test_executor_only"
    assert tested["last_test"]["synthetic"] is True
    assert tested["last_test"]["external_call"] is False
    assert tested["provider"] == "deepseek" and tested["synthetic"] is False  # Connection != result.
    assert len(calls) == 1


def test_three_synthetic_successes_never_become_real_model_quality(synthetic_setup):
    service, context, *_ = synthetic_setup
    model = connected(synthetic_setup)
    for number in range(3):
        result = _finish(synthetic_setup, model, key=f"synthetic-rating-{number}",
                         input_text=json.dumps([number, 2, 4]))
        assert result["evaluation"]["passed"] is True
        assert result["display_status"] == "awaiting_review"
        assert "review_result" in result["actions"]
    summary = service.evaluations(context=context, model_id=model["id"])
    assert summary["sample_size"] == summary["real_response_count"] == 0
    assert summary["score_pct"] is None and summary["label"] == "NEW"
    synthetic = summary["synthetic_observations"]
    assert synthetic["sample_size"] == synthetic["passed"] == synthetic["task_count"] == 3
    assert synthetic["score_pct"] is None and synthetic["mode"] == "synthetic_infrastructure"
    assert synthetic["general_model_quality_claim"] is False and synthetic["routing_effect"] == "none"


def test_real_and_synthetic_inputs_stay_in_separate_denominators(synthetic_setup):
    service, context, *_ = synthetic_setup
    model = connected(synthetic_setup)
    _finish(synthetic_setup, model, key="synthetic-before-real", input_text="[17,-4,12,9]")
    service.executor = lambda **kwargs: response()
    _finish(synthetic_setup, model, key="real-contract-after-synthetic", input_text="[17,-4,12,9]")
    summary = service.evaluations(context=context, model_id=model["id"])
    assert summary["sample_size"] == summary["real_response_count"] == 1
    assert summary["synthetic_observations"]["sample_size"] == 1
    assert summary["score_pct"] is None


def test_legacy_false_flags_are_read_only_corrected_from_immutable_executor(synthetic_setup, monkeypatch):
    service, context, *_ = synthetic_setup
    classify = model_service.receipt_provenance
    # Simulate the previous writer, which persisted the executor but forced
    # false everywhere. This is disposable test data, not rewriting user data.
    with monkeypatch.context() as legacy:
        legacy.setattr(model_service, "receipt_provenance", lambda receipt: {
            "source_kind": "real_model_response", "synthetic": False})
        model = connected(synthetic_setup)
        pending = service.test(context=context, model_id=model["id"], idempotency_key="legacy-connect")
        detail = service.execute(context=context, task_id=pending["id"])
        assert detail["synthetic"] is False
        assert service.model_detail(context=context, model_id=model["id"])["connected"] is True
        result = _finish(synthetic_setup, model, key="legacy-rating")
    assert model_service.receipt_provenance is classify
    record, checkpoint = _checkpoint(synthetic_setup, result)
    evaluation = service._get(context, EntityKind.EVALUATION, result["evaluation_id"])
    before = (record.header.revision, record.checkpoint, evaluation.evidence,
              service._json(context, checkpoint["receipt"]), service._json(context, evaluation.evidence))
    assert before[3]["synthetic"] is before[4]["synthetic"] is False
    reread = service.task_detail(context=context, task_id=result["id"])
    assert reread["synthetic"] is reread["evaluation"]["synthetic"] is True
    assert reread["evaluation"]["provider"] == "local_test_executor"
    assert reread["evaluation"]["configured_provider"] == "deepseek"
    assert reread["display_status"] == "awaiting_review"
    assert not service.model_detail(context=context, model_id=model["id"])["connected"]
    assert service.model_detail(context=context, model_id=model["id"])["test_executor_verified"] is True
    assert service.evaluations(context=context, model_id=model["id"])["sample_size"] == 0
    record2, checkpoint2 = _checkpoint(synthetic_setup, result)
    after = (record2.header.revision, record2.checkpoint, evaluation.evidence,
             service._json(context, checkpoint2["receipt"]), service._json(context, evaluation.evidence))
    assert after == before


@pytest.mark.parametrize("field", ["executor", "actual_model"])
def test_legacy_executor_marker_removes_real_credit_even_if_current_flag_off(field, monkeypatch):
    monkeypatch.delenv(test_executor.ENV, raising=False)
    receipt = {field: test_executor.EXECUTOR, "synthetic": False, "external_call": False}
    assert receipt_provenance(receipt) == {"synthetic": True, "source_kind": "synthetic_model_response"}
    assert receipt_provenance({"response": test_executor.EXECUTOR, "actual_model": "provider-runtime-name"})["synthetic"] is False


@pytest.mark.parametrize("external_call", [True, None, "false", 0])
def test_contradictory_or_unknown_new_test_executor_receipt_fails_closed(setup, external_call):
    service, context, *_ = setup
    service.executor = lambda **kwargs: response(actual_model=test_executor.EXECUTOR,
        executor=test_executor.EXECUTOR, external_call=external_call, cost_usd=0)
    result = _finish(setup)
    assert result["status"] == "failed" and result["error_code"] == "model_provider_response_invalid"
    assert result["evaluation"] is None and result["provider_result_received"] is False


def test_normal_provider_contract_preserves_connected_and_real_evidence(setup):
    service, context, *_ = setup
    model = connected(setup)
    pending = service.test(context=context, model_id=model["id"], idempotency_key="real-connection-test")
    service.execute(context=context, task_id=pending["id"])
    assert service.model_detail(context=context, model_id=model["id"])["connected"] is True
    assert service.model_detail(context=context, model_id=model["id"])["test_executor_verified"] is False
    result = _finish(setup, model)
    assert result["synthetic"] is result["evaluation"]["synthetic"] is False
    assert result["source_kind"] == "real_model_response" and result["actual_model"] == "served-model"
    assert result["display_status"] == "awaiting_review"


def test_mixed_comparison_does_not_claim_all_results_are_real(synthetic_setup):
    service, context, *_ = synthetic_setup
    first = _finish(synthetic_setup, key="comparison-synthetic")
    service.executor = lambda **kwargs: response()
    second = _finish(synthetic_setup, key="comparison-real")
    comparison = service._comparison_dto(str(uuid4()), [first, second])
    assert comparison["mixed_provenance"] is True
    assert comparison["source_kinds"] == ["real_model_response", "synthetic_model_response"]
    assert service._comparison_dto(str(uuid4()), [first, first])["synthetic"] is True


@pytest.mark.parametrize("field", ["passed", "input_sha256", "response_sha256", "task_id", "model_id", "receipt"])
def test_read_projection_does_not_relax_independent_evidence_checks(synthetic_setup, field):
    service, context, *_ = synthetic_setup
    result = _finish(synthetic_setup)
    evaluation = service._get(context, EntityKind.EVALUATION, result["evaluation_id"])
    proof = service._json(context, evaluation.evidence)
    proof[field] = not proof[field] if field == "passed" else "tampered-disposable-proof"
    original_json = service._json

    def corrupt(ctx, reference):
        if reference == evaluation.evidence:
            return proof
        return original_json(ctx, reference)

    service._json = corrupt
    with pytest.raises(ContractError, match="model_evaluation_mismatch"):
        service.task_detail(context=context, task_id=result["id"])
    with pytest.raises(ContractError, match="model_evaluation_mismatch"):
        service.evaluations(context=context, model_id=result["model_id"])


def test_chat_synthetic_completion_has_truthful_name_but_pending_is_not_a_result(synthetic_delivery):
    d = synthetic_delivery
    assert _reports(d) == [] and len(d.calls) == 0
    result = d.service.execute(context=d.context, task_id=d.task_id)
    completed = model_chat.completion(d.authorized, d.service, d.task_id)["envelope"]
    assert completed["source_kind"] == "synthetic_model_response" and completed["synthetic"] is True
    assert completed["executor"] == completed["actual_model"] == test_executor.EXECUTOR
    assert completed["provider"] == "local_test_executor" and completed["configured_provider"] == "deepseek"
    assert completed["external_call"] is False and completed["verification"]["synthetic"] is True
    assert completed["status"] == completed["display_status"] == "awaiting_review"
    assert completed["human_review"]["status"] == "pending"
    assert "Внешняя модель не вызывалась" in completed["text"]
    pending = model_chat.envelope(d.authorized, result, request_id="unit-pending", pending=True)
    assert pending["synthetic"] is False and pending["status"] == "queued"
    assert pending["actual_model"] is None and pending["participation_chain"] == []


@pytest.mark.parametrize("field", ["text", "conversation_id", "scope", "task_id", "actual_model",
                                   "executor", "external_call", "synthetic", "source_kind", "request_id"])
def test_synthetic_validator_requires_exact_saved_completion_and_original_scope(synthetic_delivery, field):
    d = synthetic_delivery
    d.service.execute(context=d.context, task_id=d.task_id)
    auth = domain_gateway.access(d.authorized["chat_scope"], read_only=True)
    value = model_chat.completion(auth, domain_gateway.history_models(auth), d.task_id)["envelope"]
    assert model_chat.validate_synthetic_envelope(auth, value)["task_id"] == d.task_id
    changed = copy.deepcopy(value)
    changed[field] = {"workspace_id": "ws_foreign"} if field == "scope" else (
        False if field == "synthetic" else True if field == "external_call" else "tampered")
    with pytest.raises((ContractError, ValueError)):
        model_chat.validate_synthetic_envelope(auth, changed)
    assert not _reports(d) and len(d.calls) == 1


def test_synthetic_validator_cannot_use_write_or_foreign_auth(synthetic_delivery):
    d = synthetic_delivery
    d.service.execute(context=d.context, task_id=d.task_id)
    value = model_chat.completion(d.authorized, d.service, d.task_id)["envelope"]
    with pytest.raises(ContractError, match="history_context_required"):
        model_chat.validate_synthetic_envelope(d.authorized, value)
    auth = domain_gateway.access(d.authorized["chat_scope"], read_only=True)
    other = uuid4()
    foreign = {**auth, "context": replace(auth["context"], user_uuid=other,
                                         actor=replace(auth["context"].actor, actor_id=other))}
    with pytest.raises(ContractError):
        model_chat.validate_synthetic_envelope(foreign, value)


def test_synthetic_validator_requires_the_original_scoped_user_message(synthetic_delivery, monkeypatch):
    d = synthetic_delivery
    d.service.execute(context=d.context, task_id=d.task_id)
    auth = domain_gateway.access(d.authorized["chat_scope"], read_only=True)
    value = model_chat.completion(auth, domain_gateway.history_models(auth), d.task_id)["envelope"]
    monkeypatch.setattr(chief_agent, "read_jsonl", lambda path: [])
    with pytest.raises(ContractError, match="model_delivery_message_mismatch"):
        model_chat.validate_synthetic_envelope(auth, value)


def test_existing_worker_delivers_one_truthful_synthetic_report_without_second_execution(synthetic_delivery):
    d = synthetic_delivery
    source = local_worker.run_once(worker_id="synthetic-contract-source")
    assert source["status"] == "succeeded" and len(d.calls) == 1
    delivered = local_worker.run_once(worker_id="synthetic-contract-delivery")
    assert delivered["status"] == "succeeded"
    reports = _reports(d)
    assert len(reports) == 1 and len(d.calls) == 1
    action = reports[0]["actions"][0]
    assert action["name"] == "synthetic_model_response" and action["synthetic"] is True
    assert action["status"] == "awaiting_review"
    assert reports[0]["model"] == test_executor.EXECUTOR
    assert action["verification"]["passed"] is True
    assert action["executor"] == test_executor.EXECUTOR and action["external_call"] is False
    assert d.service.task_detail(context=d.context, task_id=d.task_id)["display_status"] == "awaiting_review"
    assert len([row for row in _rows(d) if row.get("role") == "user"]) == 1
    assert d.service.evaluations(context=d.context, model_id=action["model_id"])["sample_size"] == 0


@pytest.mark.parametrize("fixture_name", ["delivery", "synthetic_delivery"])
@pytest.mark.parametrize("decision,status", [("accept", "completed"), ("reject", "rejected")])
def test_explicit_review_uses_its_real_event_and_same_task_without_reexecution(request, fixture_name, decision, status):
    d = request.getfixturevalue(fixture_name)
    assert local_worker.run_once(worker_id="review-source")["status"] == "succeeded"
    assert local_worker.run_once(worker_id="initial-result-delivery")["status"] == "succeeded"
    before = model_chat.completion(d.authorized, d.service, d.task_id)
    detail = d.service.task_detail(context=d.context, task_id=d.task_id)
    assert before["envelope"]["status"] == "awaiting_review"
    assert d.service.repository.events.is_acknowledged(context=d.context,
        consumer=model_chat.DELIVERY_CONSUMER, event_id=UUID(before["event_id"]))
    reviewed = task_review.submit(d.service, context=d.context, task_id=d.task_id,
        payload={"decision": decision, "comment": "Explicit disposable review",
                 "source_sha256": detail["human_review"]["source_sha256"]},
        expected_revision=detail["revision"], idempotency_key="explicit-model-review-" + decision)
    after = model_chat.completion(d.authorized, d.service, d.task_id)
    assert after["checkpoint_sha256"] == before["checkpoint_sha256"]
    assert reviewed["revision"] == detail["revision"]
    assert after["event_id"] != before["event_id"]
    assert after["envelope"]["request_id"] != before["envelope"]["request_id"]
    review = d.service._get(d.context, EntityKind.EVALUATION, reviewed["human_review"]["evaluation_id"])
    assert after["event_id"] == str(uuid5(review.header.entity_id, f"revision:{review.header.revision}"))
    assert after["envelope"]["human_review"] == reviewed["human_review"]
    assert after["envelope"]["status"] == reviewed["display_status"] == status
    queued = domain_gateway.enqueue_model_delivery(d.authorized, d.service, d.task_id)
    assert queued["payload"]["event_id"] == after["event_id"]
    assert local_worker.run_once(worker_id="review-delivery")["status"] == "succeeded"
    assert len(d.calls) == 1 and len(_reports(d)) == 2
    assert _reports(d)[0]["actions"][0]["status"] == "awaiting_review"
    assert _reports(d)[1]["actions"][0]["status"] == status
    assert d.service.repository.events.is_acknowledged(context=d.context,
        consumer=model_chat.DELIVERY_CONSUMER, event_id=UUID(after["event_id"]))
    assert domain_gateway.enqueue_model_delivery(d.authorized, d.service, d.task_id) is None
    task_review.submit(d.service, context=d.context, task_id=d.task_id,
        payload={"decision": decision, "comment": "Explicit disposable review",
                 "source_sha256": detail["human_review"]["source_sha256"]},
        expected_revision=detail["revision"], idempotency_key="explicit-model-review-" + decision)
    assert model_chat.completion(d.authorized, d.service, d.task_id) == after


def test_old_pending_review_delivery_is_superseded_before_append(synthetic_delivery):
    d = synthetic_delivery
    d.service.execute(context=d.context, task_id=d.task_id)
    before = model_chat.completion(d.authorized, d.service, d.task_id)
    detail = d.service.task_detail(context=d.context, task_id=d.task_id)
    task_review.submit(d.service, context=d.context, task_id=d.task_id,
        payload={"decision": "accept", "source_sha256": detail["human_review"]["source_sha256"]},
        expected_revision=detail["revision"], idempotency_key="review-before-first-delivery")
    result = model_chat.deliver(d.authorized, d.service, task_id=d.task_id, event_id=before["event_id"],
        checkpoint_sha256=before["checkpoint_sha256"], events=d.service.repository.events)
    assert result["status"] == "superseded" and not _reports(d)
    assert len(d.calls) == 1


def test_chat_append_without_persisted_ack_is_not_claimed_delivered(synthetic_delivery, monkeypatch):
    d = synthetic_delivery
    d.service.execute(context=d.context, task_id=d.task_id)
    saved = model_chat.completion(d.authorized, d.service, d.task_id)
    events = d.service.repository.events
    with monkeypatch.context() as failing:
        failing.setattr(type(events), "acknowledge", lambda *a, **kw: False)
        with pytest.raises(ContractError, match="model_delivery_unconfirmed"):
            model_chat.deliver(d.authorized, d.service, task_id=d.task_id, event_id=saved["event_id"],
                checkpoint_sha256=saved["checkpoint_sha256"], events=events)
    assert len(_reports(d)) == 1 and len(d.calls) == 1
    recovered = model_chat.deliver(d.authorized, d.service, task_id=d.task_id, event_id=saved["event_id"],
        checkpoint_sha256=saved["checkpoint_sha256"], events=events)
    assert recovered["status"] == "delivered" and recovered["replayed"] is True
    assert len(_reports(d)) == 1 and len(d.calls) == 1


def test_connection_check_chat_is_automatic_not_owner_acceptance(synthetic_delivery):
    d = synthetic_delivery
    model_id = d.service.task_detail(context=d.context, task_id=d.task_id)["model_id"]
    pending = model_chat.start(d.authorized, d.service, model_id, {}, "synthetic-chat-connection", test=True)
    detail = d.service.execute(context=d.context, task_id=pending["id"])
    value = model_chat.completion(d.authorized, d.service, pending["id"])["envelope"]
    assert value["status"] == "verified_automatically" and value["human_review"]["status"] == "not_required"
    assert model_chat.publish(d.authorized, detail)["ok"] is True
    rows = chief_agent.read_jsonl(chief_agent._conversation_file(pending["conversation_id"], scope=d.authorized["chat_scope"]))
    report = next(row for row in rows if row.get("message_kind") == "report")
    assert report["actions"][0]["status"] == "verified_automatically"
    conversations = chief_agent.list_conversations(scope=d.authorized["chat_scope"])
    found = next(row for row in conversations if row["conversation_id"] == pending["conversation_id"])
    assert found["work_state"] == "completed"
    assert not d.service.model_detail(context=d.context, model_id=model_id)["connected"]
