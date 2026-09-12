"""Exact test-executor receipt admission; no external model/application calls."""
from __future__ import annotations

import copy

import pytest

from app.ai_control_center import deviation_control as deviations, execution_v2 as v2, test_executor
from tests.test_agent_world_execution_v2 import (
    claim, execution, isolated_runtime, ordinary, owner, project, run_claim,
)
from tests.test_agent_world_model_provenance import _enable


WORKSPACE = "ws_synthetic_deviation"
TASK = "20000000-0000-4000-8000-000000000001"


def approved():
    return {"task_id": TASK, "request_sha256": "a" * 64, "max_output_tokens": 512,
        "environment": "development", "workspace_id": WORKSPACE,
        "approved_task": {"entity_id": TASK, "kind": "task", "revision": 3,
            "scope": {"environment": "development", "workspace_id": WORKSPACE}}}


def receipt(*, legacy=False):
    result = {"task_id": TASK, "request_id": TASK, "request_sha256": "a" * 64,
        "source": "local_test_executor", "source_kind": "synthetic_model_response", "synthetic": True,
        "actual_model": test_executor.EXECUTOR, "executor": test_executor.EXECUTOR,
        "external_call": False, "cost_usd": 0.0, "output_tokens": 24}
    if legacy:
        result.update(source="provider_response", synthetic=False)
        result.pop("source_kind")
    return result


@pytest.fixture(autouse=True)
def development(monkeypatch):
    _enable(monkeypatch, WORKSPACE)


@pytest.mark.parametrize("legacy", [False, True])
def test_exact_current_and_historical_markers_remain_scoped(legacy, monkeypatch):
    assert deviations.inspect_provider(approved(), receipt(legacy=legacy)) is None
    monkeypatch.delenv(test_executor.ENV)
    assert deviations.inspect_provider(approved(), receipt(legacy=legacy)) == "execution_gate_disabled"
    # A read/closeout of already-received bytes cannot dispatch anything.
    assert deviations.inspect_provider(approved(), receipt(legacy=legacy), check_test_executor_enabled=False) is None


@pytest.mark.parametrize("setting,value", [
    ("STRATFORGE_AGENT_WORLD_TEST_EXECUTOR", "*"),
    ("STRATFORGE_AGENT_WORLD_TEST_EXECUTOR", WORKSPACE + "_different"),
    ("STRATFORGE_PREVIEW_SANDBOX", "1"),
    ("STRATFORGE_ENV", "production"),
    ("DEPLOYMENT_ENV", "canary"),
])
def test_new_action_requires_exact_current_development_opt_in(setting, value, monkeypatch):
    monkeypatch.setenv(setting, value)
    if setting in {"STRATFORGE_ENV", "DEPLOYMENT_ENV"}:
        monkeypatch.setenv("STRATFORGE_ENV", value)
        monkeypatch.setenv("DEPLOYMENT_ENV", value)
    if setting == "STRATFORGE_PREVIEW_SANDBOX":
        monkeypatch.setenv("STRATFORGE_PREVIEW_ID", "ab" * 12)
    assert deviations.inspect_provider(approved(), receipt()) == "execution_gate_disabled"


@pytest.mark.parametrize("change", [
    {"task_id": TASK.replace("2", "3", 1)}, {"request_id": "foreign-task"},
    {"request_sha256": "b" * 64}, {"source": "arbitrary_executor"},
    {"synthetic": False}, {"source_kind": "real_model_response"},
    {"executor": "unrecognized-test-executor"}, {"actual_model": "configured-real-model"},
    {"executor": None}, {"actual_model": None}, {"external_call": True}, {"external_call": None},
    {"paid_call": True}, {"cost_usd": 0.001}, {"cost_usd": None}, {"cost_usd": False},
    {"cost_usd": -1}, {"cost_usd": float("nan")}, {"cost_usd": float("inf")},
])
@pytest.mark.parametrize("historical", [False, True])
def test_synthetic_marker_never_bypasses_request_origin_or_cost_guards(change, historical):
    assert deviations.inspect_provider(approved(), {**receipt(), **change},
        check_test_executor_enabled=not historical) == "provider_receipt_mismatch"


@pytest.mark.parametrize("field,value", [("environment", "production"), ("workspace_id", "ws_foreign")])
@pytest.mark.parametrize("historical", [False, True])
def test_approval_scope_is_not_relaxed_even_for_history(field, value, historical):
    value_ = approved()
    value_[field] = value
    assert deviations.inspect_provider(value_, receipt(), check_test_executor_enabled=not historical) == "provider_receipt_mismatch"


def test_approved_task_reference_must_match():
    value = approved()
    value["approved_task"]["entity_id"] = "foreign-task"
    assert deviations.inspect_provider(value, receipt(), check_test_executor_enabled=False) == "provider_receipt_mismatch"


@pytest.mark.parametrize("output", [513, -1, "24", True])
@pytest.mark.parametrize("legacy", [False, True])
def test_same_output_limit_applies_to_named_executor(legacy, output):
    assert deviations.inspect_provider(approved(), {**receipt(legacy=legacy), "output_tokens": output}) == "provider_output_limit_exceeded"


def test_unmarked_real_provider_contract_is_unchanged(monkeypatch):
    monkeypatch.delenv(test_executor.ENV)
    real = {**receipt(), "source": "provider_response", "synthetic": False,
            "source_kind": "real_model_response", "actual_model": "provider-reported-name",
            "executor": None, "external_call": True, "cost_usd": 0.0002}
    assert deviations.inspect_provider(approved(), real) is None


def _executor(execution, monkeypatch, *, disable_after=False):
    _enable(monkeypatch, execution.context.scope.workspace_id)

    def execute(**kwargs):
        execution.calls.append(kwargs)
        result = test_executor.execute(**kwargs)
        if disable_after:
            monkeypatch.delenv(test_executor.ENV)
        return result

    execution.service.executor = execute


@pytest.mark.parametrize("disable_after", [False, True])
def test_existing_claimed_v2_closes_named_receipt_and_does_not_reclassify_history(execution, monkeypatch, disable_after):
    _executor(execution, monkeypatch, disable_after=disable_after)
    initial = project(execution)
    job = claim(execution)
    run_claim(execution, job)
    result = execution.service.task_detail(context=execution.context, task_id=execution.task_id)
    assert result["synthetic"] is True and result["evaluation"]["synthetic"] is True
    assert result["actual_model"] == test_executor.EXECUTOR and result["external_call"] is False
    assert result["display_status"] == "awaiting_review" and result["human_review"]["status"] == "pending"
    final = project(execution)
    assert final["status"] == "succeeded" and final["phase"] == "verified_result"
    assert final["approved_scope_sha256"] == initial["approved_scope_sha256"]
    assert final["deviation_count"] == 0 and final["human_accepted"] is False
    assert len(execution.calls) == 1
    monkeypatch.delenv(test_executor.ENV, raising=False)
    assert v2.observe(execution.auth, execution.service, execution.task_id) == final
    assert project(execution) == final and len(execution.calls) == 1


@pytest.mark.parametrize("path", ["proof", "verification"])
def test_application_verification_is_not_relaxed_by_local_model_executor(path):
    authorization = approved()
    request = {"kind": "chart", "request_sha256": "c" * 64}
    authorization["application_request"] = request
    checkpoint = {"application_request": request, "application_dispatch": {"source_id": "chart-test"}}
    result = {"verified": True, "source_id": "chart-test", "source_kind": "desktop_chart",
        "evaluation": {"task_id": TASK, "source": "existing_application_receipt", "synthetic": False,
            "verification": {"verified": True, "synthetic": False, "request_sha256": "c" * 64,
                "source_id": "chart-test"}}}
    assert deviations.inspect_application(authorization, checkpoint, result) is None
    invalid = copy.deepcopy(result)
    target = invalid["evaluation"] if path == "proof" else invalid["evaluation"]["verification"]
    target["synthetic"] = True
    assert deviations.inspect_application(authorization, checkpoint, invalid) == "application_receipt_mismatch"
