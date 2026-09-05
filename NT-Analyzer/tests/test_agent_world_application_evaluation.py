"""Disposable receipt/rating contracts; all provider/source data are fixtures.

These tests do not contact a provider, open a browser, trade, or mutate Local
owner state. They prove projection boundaries, not live application execution.
"""
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest

from app.ai_control_center import model_evaluation as evaluation
from app.ai_control_center.model_service import ModelService
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_models import setup as model_setup, connected, context, response
from tests.test_agent_world_live_backtests import _spec as backtest_spec


def plan(model_setup, *, key="application-observation", kind="chart", spec=None, model=None):
    service, ctx, *_ = model_setup
    model = model or connected(model_setup)
    spec = spec or ({"instrument": "MNQ 09-26", "timeframe": "5m"} if kind == "chart" else backtest_spec())
    pending = service.plan_application(context=ctx, model_id=model["id"], spec=spec, kind=kind,
        idempotency_key=key, conversation_id="evaluation-history", message_id="MSG-" + uuid4().hex)
    service.executor = lambda **kwargs: response(kwargs["prompt"].split("Specification: ", 1)[1])
    return model, service.execute(context=ctx, task_id=pending["id"])


def complete(model_setup, *, source_id="fixture_chart_receipt", **kwargs):
    service, ctx, *_ = model_setup
    model, pending = plan(model_setup, **kwargs)
    kind = pending["application_request"]["kind"]
    # Opaque surrogate bytes exercise the trusted adapter seam only. The real
    # PNG/report validators have their own integration tests.
    ref = service._put(ctx, {"disposable_fixture": source_id})
    proof = {"verified": True, "synthetic": False,
        "source_kind": "ninjatrader_report" if kind == "backtest" else "desktop_chart",
        "source_id": source_id, "sha256": ref.sha256,
        "request_sha256": pending["application_request"]["request_sha256"]}
    service.record_application_result(context=ctx, task_id=pending["id"], source_id=source_id,
        verification=proof, artifact_refs=(ref,))
    return model, service.task_detail(context=ctx, task_id=pending["id"])


def stats(model_setup, model):
    service, ctx, *_ = model_setup
    return service.evaluations(context=ctx, model_id=model["id"], rubric_key="application_execution")


def test_application_receipt_automatically_appears_in_task_evaluations_and_history(model_setup):
    service, ctx, *_ = model_setup
    model, finished = complete(model_setup)
    assert finished["status"] == "succeeded"
    assert finished["evaluation"]["rubric_key"] == "chart_spec"  # compatibility: plan != execution
    assert [row["rubric_key"] for row in finished["evaluations"]] == ["chart_spec", "application_execution"]
    proof = finished["application_evaluation"]
    assert proof["application_kind"] == "chart" and proof["source_kind"] == "desktop_chart"
    assert proof["evaluation_id"] == finished["application_evaluation_id"]
    assert proof["market_performance_claim"] is proof["general_model_quality_claim"] is False
    assert service.tasks(context=ctx)["items"][0]["application_evaluation"] == proof
    value = stats(model_setup, model)
    assert value["sample_size"] == value["receipt_count"] == 1
    assert value["score_pct"] is None and value["confidence"] == "not_pooled"
    assert value["classes"][1]["sample_size"] == 1 and value["classes"][1]["label"] == "NEW"
    assert service.evaluations(context=ctx, model_id=model["id"])["sample_size"] == 0


def test_class_scores_do_not_pool_backtest_and_chart_or_inflate_replays(model_setup):
    service, ctx, *_ = model_setup
    model = connected(model_setup)
    for index, timeframe in enumerate(("1m", "5m", "15m")):
        complete(model_setup, model=model, key=f"chart-distinct-{index}", source_id=f"chart_fixture_{index}",
                 spec={"instrument": "MNQ 09-26", "timeframe": timeframe})
    _, backtest = complete(model_setup, model=model, key="backtest-distinct", kind="backtest", source_id="backtest_fixture")
    complete(model_setup, model=model, key="same-chart-new-receipt", source_id="chart_repeated_spec",
             spec={"instrument": "MNQ 09-26", "timeframe": "5m"})
    value = stats(model_setup, model)
    backtest_stats, chart_stats = value["classes"]
    assert value["sample_size"] == 4 and value["receipt_count"] == 5 and value["score_pct"] is None
    assert backtest_stats["sample_size"] == 1 and backtest_stats["score_pct"] is None
    assert backtest_stats["application_kind"] == "backtest" and backtest_stats["source_kind"] == "ninjatrader_report"
    assert chart_stats["sample_size"] == 3 and chart_stats["receipt_count"] == 4
    assert chart_stats["score_pct"] == 100 and chart_stats["confidence"] == "low"
    assert chart_stats["label"] == "OBSERVED" and chart_stats["application_kind"] == "chart"
    assert value["routing_effect"] == "none" and value["denominator"] == "distinct_verified_application_requests"
    # Read/restart/replay adds no observation, event or execution.
    assert stats(model_setup, model) == value
    assert evaluation.application_reputation([backtest["application_evaluation"]] * 4)["receipt_count"] == 1
    fresh = ModelService(service.repository, admit=service.admit, executor=service.executor, secrets=service.secrets)
    assert fresh.evaluations(context=ctx, model_id=model["id"], rubric_key="application_execution") == value


@pytest.mark.parametrize("state", ["waiting", "failed", "cancelled"])
def test_missing_receipt_never_becomes_successful_application_observation(model_setup, state):
    service, ctx, *_ = model_setup
    model, pending = plan(model_setup)
    if state != "waiting":
        task = service._get(ctx, EntityKind.TASK, pending["id"])
        changes = {}
        if state == "failed":
            checkpoint = {**service._json(ctx, task.checkpoint), "application_error": "source_fixture_failed"}
            changes["checkpoint"] = service._put(ctx, checkpoint)
        service._change(ctx, task, state, **changes)
    detail = service.task_detail(context=ctx, task_id=pending["id"])
    assert detail["status"] == state and detail["application_evaluation"] is None
    assert len(detail["evaluations"]) == 1 and detail["evaluations"][0]["rubric_key"] == "chart_spec"
    assert stats(model_setup, model)["sample_size"] == 0
    assert stats(model_setup, model)["score_pct"] is None
    assert service.tasks(context=ctx)["items"][0]["status"] == state


@pytest.mark.parametrize("changes", [
    {"synthetic": True}, {"self_scored": True}, {"evaluator": "model_self_report"},
    {"evaluator": "independent_local_evidence_verifier"}, {"source": "demo"},
    {"passed": False}, {"observed_score_pct": True}, {"observed_score_pct": 90},
    {"rubric_key": "json_arithmetic"}, {"input_sha256": "invalid"}, {"source_kind": "model_text"},
    {"source_kind": []}, {"source_id": ""}, {"model_id": None}, {"task_id": None},
    {"artifact_ids": []}, {"artifact_ids": [[]]}, {"verification": None},
])
def test_synthetic_self_scored_or_incomplete_proofs_cannot_enter_aggregate(model_setup, changes):
    _, detail = complete(model_setup)
    proof = {**detail["application_evaluation"], **changes}
    assert evaluation.application_reputation([proof])["sample_size"] == 0


@pytest.mark.parametrize("changes", [
    {"synthetic": True}, {"verified": False}, {"source_kind": "ninjatrader_report"},
    {"source_id": "other_source"}, {"request_sha256": ""}, {"sha256": "not-a-sha"},
])
def test_nested_source_verification_is_required(model_setup, changes):
    _, detail = complete(model_setup)
    proof = deepcopy(detail["application_evaluation"])
    proof["verification"].update(changes)
    assert evaluation.application_reputation([proof])["sample_size"] == 0


@pytest.mark.parametrize("field,value", [
    ("task_id", "wrong-task"), ("model_id", "wrong-model"), ("input_sha256", "a" * 64),
    ("source_kind", "ninjatrader_report"), ("artifact_ids", ["missing-artifact"]),
])
def test_service_rechecks_typed_task_model_request_and_artifact_lineage(model_setup, monkeypatch, field, value):
    service, ctx, *_ = model_setup
    model, detail = complete(model_setup)
    original = service._json
    evaluation_row = service._get(ctx, EntityKind.EVALUATION, detail["application_evaluation_id"])
    def altered(context, ref):
        result = original(context, ref)
        if ref == evaluation_row.evidence:
            result[field] = value
            if field == "source_kind":
                result["verification"]["source_kind"] = value
        return result
    monkeypatch.setattr(service, "_json", altered)
    with pytest.raises(ContractError, match="application_evaluation_mismatch"):
        stats(model_setup, model)


def test_service_rechecks_evaluation_model_link_not_only_payload(model_setup, monkeypatch):
    service, ctx, *_ = model_setup
    model, detail = complete(model_setup)
    other = connected(model_setup, key="other-model-link")
    other_model = service._get(ctx, EntityKind.MODEL, other["id"])
    original = service.repository.get
    def altered(**kwargs):
        row = original(**kwargs)
        if row is not None and str(row.header.entity_id) == detail["application_evaluation_id"]:
            return replace(row, model=other_model.ref())
        return row
    monkeypatch.setattr(service.repository, "get", altered)
    with pytest.raises(ContractError, match="application_evaluation_mismatch"):
        service.task_detail(context=ctx, task_id=detail["id"])


def test_missing_immutable_source_is_not_counted(model_setup, monkeypatch):
    service, ctx, *_ = model_setup
    model, detail = complete(model_setup)
    missing = detail["application_evaluation"]["artifact_ids"][0]
    original = service.repository.get_artifact
    def unavailable(**kwargs):
        return None if str(kwargs["reference"].artifact_id) == missing else original(**kwargs)
    monkeypatch.setattr(service.repository, "get_artifact", unavailable)
    with pytest.raises(ContractError, match="application_evidence_unavailable"):
        stats(model_setup, model)


def test_application_observations_are_read_only_scoped_and_do_not_call_provider(model_setup):
    service, ctx, *_ = model_setup
    model, detail = complete(model_setup)
    service.executor = lambda **_: pytest.fail("projection cannot call provider")
    with service.repository._transaction() as db:
        before = tuple(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                       for table in ("aw_revisions", "aw_events", "aw_artifacts"))
    for _ in range(3):
        assert stats(model_setup, model)["receipt_count"] == 1
        assert service.tasks(context=ctx)["items"][0]["application_evaluation"]
    with service.repository._transaction() as db:
        after = tuple(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                      for table in ("aw_revisions", "aw_events", "aw_artifacts"))
    assert before == after
    for foreign in (context(user=uuid4()), context(workspace="ws_other_workspace", user=ctx.user_uuid)):
        with pytest.raises(ContractError, match="not_found"):
            service.evaluations(context=foreign, model_id=model["id"], rubric_key="application_execution")


def test_application_rubric_is_projection_only_not_a_provider_task(model_setup):
    service, ctx, *_ = model_setup
    model = connected(model_setup)
    with pytest.raises(ContractError, match="rubric_not_supported"):
        service.start_task(context=ctx, model_id=model["id"], payload={"rubric_key": "application_execution"},
                           idempotency_key="cannot-self-evaluate")
