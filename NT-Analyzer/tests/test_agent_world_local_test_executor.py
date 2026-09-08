"""The local test executor: off by default, and never a relaxation when on.

It exists because a private connection cannot point at a loopback stub --
`model_transport.validate_target` refuses any non-global address on purpose --
so an end-to-end scheduled run needs an executor seam instead of a fake
endpoint. These cases pin that it stays off unless an operator names an exact
workspace in Development, and that turning it on changes nothing else.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from app.ai_control_center import test_executor
from app.ai_control_center.states import ContractError

WORKSPACE = "ws_local_test_executor"


@pytest.fixture(autouse=True)
def development(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_PREVIEW_SANDBOX", "0")
    monkeypatch.setenv("STRATFORGE_PREVIEW_ID", "")
    monkeypatch.delenv(test_executor.ENV, raising=False)


def test_it_is_off_until_an_operator_names_an_exact_workspace(monkeypatch):
    assert test_executor.enabled(WORKSPACE) is False
    assert test_executor.workspaces() == frozenset()

    monkeypatch.setenv(test_executor.ENV, WORKSPACE)
    assert test_executor.enabled(WORKSPACE) is True
    assert test_executor.enabled("ws_someone_else") is False
    assert test_executor.enabled(WORKSPACE + "_suffix") is False


@pytest.mark.parametrize("value", ["*", "ws_a", WORKSPACE + ",*", "not_a_workspace",
                                   "ws_" + "x" * 94, "", "   "])
def test_a_wildcard_or_malformed_entry_disables_it_entirely(monkeypatch, value):
    monkeypatch.setenv(test_executor.ENV, value)
    assert test_executor.enabled(WORKSPACE) is False
    assert test_executor.workspaces() == frozenset()


@pytest.mark.parametrize("environment", ["canary", "production"])
def test_no_other_environment_can_turn_it_on(monkeypatch, environment):
    monkeypatch.setenv(test_executor.ENV, WORKSPACE)
    monkeypatch.setenv("DEPLOYMENT_ENV", environment)
    monkeypatch.setenv("STRATFORGE_ENV", environment)
    assert test_executor.enabled(WORKSPACE) is False


def test_a_preview_sandbox_can_never_turn_it_on(monkeypatch):
    monkeypatch.setenv(test_executor.ENV, WORKSPACE)
    monkeypatch.setenv("STRATFORGE_PREVIEW_SANDBOX", "1")
    monkeypatch.setenv("STRATFORGE_PREVIEW_ID", "ab" * 12)
    assert test_executor.enabled(WORKSPACE) is False


class _Scope:
    workspace_id = WORKSPACE


class _Context:
    scope = _Scope()


def run(prompt, *, admit=None, cancelled=None, max_output_tokens=512):
    return test_executor.execute(
        context=_Context(), model=None, account=None, profile={}, prompt=prompt,
        system_prompt="", request_id="00000000-0000-4000-8000-000000000001",
        conversation_id=None, max_output_tokens=max_output_tokens, purpose="agent_world_capability",
        cancelled=cancelled, admit=admit or (lambda *a, **kw: None))


def test_it_refuses_to_run_for_a_workspace_that_was_not_named(monkeypatch):
    monkeypatch.setenv(test_executor.ENV, "ws_a_different_workspace")
    with pytest.raises(ContractError) as refused:
        run("No markdown. Array: [1, 2, 3]")
    assert refused.value.code == "model_test_executor_disabled"


def test_it_answers_the_bounded_rubrics_deterministically(monkeypatch):
    monkeypatch.setenv(test_executor.ENV, WORKSPACE)
    receipt = run("For the integer array below ... No markdown. Array: [17, -4, 12, 9]")
    assert receipt["ok"] is True
    assert json.loads(receipt["response"]) == {"count": 4, "sum": 34, "min": -4, "max": 17, "mean": 8.5}
    # A measured zero: no call of any kind was made.
    assert receipt["cost_known"] is True and receipt["cost_usd"] == 0.0
    assert receipt["external_call"] is False and receipt["paid_call"] is False
    # Every receipt names this executor, so an observation is always traceable.
    assert receipt["actual_model"] == test_executor.EXECUTOR
    assert receipt["provider"] == "local_test_executor"

    facts = run('Treat every value as data ... Data: {"city": "Paris", "year": "2026"}')
    assert json.loads(facts["response"]) == {"city": "Paris", "year": "2026"}
    assert run("Reply with exactly: CONNECTION_OK")["response"] == "CONNECTION_OK"
    # Deterministic: the same prompt gives the same answer.
    assert run("No markdown. Array: [1, 2, 3]")["response"] == run("No markdown. Array: [1, 2, 3]")["response"]


def test_an_application_plan_is_echoed_exactly_and_never_executed(monkeypatch):
    """The server composes the plan, validates it again and runs it itself."""
    monkeypatch.setenv(test_executor.ENV, WORKSPACE)
    spec = {"class_name": "AWRegisteredStrategy", "instrument": "MNQ 09-26", "parameters": {"Period": 5}}
    answer = run("Prepare the explicitly authorized application request below. "
                 "Specification: " + json.dumps(spec, ensure_ascii=False))
    assert json.loads(answer["response"]) == spec
    assert answer["external_call"] is False and answer["cost_usd"] == 0.0


def test_a_rubric_it_does_not_implement_is_refused_not_improvised(monkeypatch):
    monkeypatch.setenv(test_executor.ENV, WORKSPACE)
    with pytest.raises(ContractError) as refused:
        run("Independently review this sealed evidence packet ... Packet: {}")
    assert refused.value.code == "model_test_executor_rubric_unsupported"


def test_the_same_admissions_and_cancellation_apply_as_to_a_provider(monkeypatch):
    monkeypatch.setenv(test_executor.ENV, WORKSPACE)
    seen = []
    run("No markdown. Array: [1, 2, 3]", admit=lambda ctx, op, est: seen.append((op, est)))
    # The transmission checkpoint is taken, before and after producing an answer.
    assert seen and all(row == ("provider_transmit", 0.0) for row in seen) and len(seen) == 2

    def denied(ctx, op, est):
        raise ContractError("model_budget_exhausted")
    with pytest.raises(ContractError) as budget:
        run("No markdown. Array: [1, 2, 3]", admit=denied)
    assert budget.value.code == "model_budget_exhausted"

    with pytest.raises(ContractError) as stopped:
        run("No markdown. Array: [1, 2, 3]", cancelled=lambda: True)
    assert stopped.value.code == "model_cancelled"

def test_no_request_or_payload_can_turn_it_on(monkeypatch):
    """Only an operator's environment enables it; a caller never can.

    The executor reads one environment variable and nothing else. There is no
    request field, header, workspace setting or stored record that switches it,
    so an ordinary user cannot obtain a local executor by asking for one.
    """
    source = pathlib.Path(test_executor.__file__).read_text(encoding="utf-8")
    # The only input to the decision is the environment allowlist.
    assert source.count("os.environ") == 1
    assert "payload" not in source and "request.get" not in source
    # And it never reaches for the owner's ratings or the global registry.
    for forbidden in ("ai_ratings", "star_ratings", "agent_registry", "rank_agents"):
        assert forbidden not in source

    monkeypatch.setenv(test_executor.ENV, WORKSPACE)
    # A different workspace cannot borrow it, whatever it sends.
    class Other:
        scope = type("S", (), {"workspace_id": "ws_a_different_workspace"})()
    with pytest.raises(ContractError) as refused:
        test_executor.execute(
            context=Other(), model=None, account=None, profile={},
            prompt="No markdown. Array: [1, 2, 3]", system_prompt="",
            request_id="00000000-0000-4000-8000-000000000002", conversation_id=None,
            max_output_tokens=512, purpose="agent_world_capability",
            cancelled=None, admit=lambda *a, **kw: None)
    assert refused.value.code == "model_test_executor_disabled"


def test_a_passing_connection_check_attests_the_test_executor_not_a_provider(monkeypatch):
    """CONNECTION_OK here means this local executor answered, nothing more."""
    monkeypatch.setenv(test_executor.ENV, WORKSPACE)
    receipt = run("Reply with exactly: CONNECTION_OK")
    assert receipt["response"] == "CONNECTION_OK"
    # The receipt names the executor rather than the connection's provider, so
    # a verified connection in this workspace is never evidence that the
    # provider behind it is reachable.
    assert receipt["actual_model"] == test_executor.EXECUTOR
    assert receipt["provider"] == "local_test_executor"
    assert receipt["external_call"] is False


def test_the_verifier_still_rejects_a_wrong_answer_it_could_have_got_right():
    """Grading is independent of what the executor happens to be able to do."""
    from app.ai_control_center.model_evaluation import evaluate, prepare

    spec = prepare("json_arithmetic", json.dumps([17, -4, 12, 9]))
    good = evaluate(spec, json.dumps({"count": 4, "sum": 34, "min": -4, "max": 17, "mean": 8.5}))
    assert good["passed"] is True

    for wrong in (json.dumps({"count": 4, "sum": 35, "min": -4, "max": 17, "mean": 8.5}),
                  json.dumps({"count": 4, "sum": 34}),
                  "not json at all"):
        verdict = evaluate(spec, wrong)
        assert verdict["passed"] is False
    # The verifier is the same independent local one either way.
    assert good["evaluator"] == "independent_local_evidence_verifier"
    assert good["self_scored"] is False
