"""A deterministic local executor for one explicitly named Development workspace.

Verifying a scheduled run end to end needs a model that actually answers. It
cannot be a loopback stub: `model_transport.validate_target` refuses any
non-global address on purpose, and relaxing that to run a test would remove an
SSRF guard. The seam that remains is the executor itself, which is where the
suite has always substituted one.

This executor is off unless an operator names the exact workspace in
`STRATFORGE_AGENT_WORLD_TEST_EXECUTOR`; it exists only in Development, never
inside a preview sandbox. It answers bounded data rubrics and explicitly echoes
one-off assistant text for delivery tests; that echo is not a model answer or
an autonomous scheduled task. It performs no network call of any kind, so the zero
cost it reports is a fact rather than an assumption.

What it does **not** relax: the flag, grant, device, budget, cancellation and
review checks around it are untouched, its answer is graded by the same
independent verifier as any provider's, and every receipt names this executor so
an observation can always be traced back to a test run rather than a provider.
"""
from __future__ import annotations

import json
import os
import re
import time

from .. import preview_sandbox, runtime_env
from .states import ContractError

ENV = "STRATFORGE_AGENT_WORLD_TEST_EXECUTOR"
EXECUTOR = "agent-world-local-test-executor-v1"
# The bounded data rubrics a schedule may carry, the connection check, and the
# application plan rubrics -- which only ever echo the specification the server
# built, because the server validates and executes it independently.
SUPPORTED = frozenset({"connection_exact", "json_arithmetic", "extract_facts",
                       "backtest_spec", "chart_spec", "assistant_response"})


def workspaces() -> frozenset[str]:
    """Exact workspace ids only. A wildcard or a malformed entry disables it."""
    if not runtime_env.is_development() or preview_sandbox.enabled():
        return frozenset()
    entries = [item.strip() for item in os.environ.get(ENV, "").split(",") if item.strip()]
    if not entries or any(not re.fullmatch(r"ws_[A-Za-z0-9_-]{3,93}", item) for item in entries):
        return frozenset()
    return frozenset(entries)


def enabled(workspace_id: str = "") -> bool:
    allowed = workspaces()
    return bool(allowed) and (workspace_id in allowed if workspace_id else True)


def _answer(prompt: str) -> str:
    """Compute the bounded answer locally, from the prompt the server built."""
    if prompt.startswith("Assistant request (text only):\n"):
        return ("SYNTHETIC — тестовый ответ механизма доставки, не решение задания моделью. "
                "Получен текст поручения: " + prompt.split("\n", 1)[1][:600])
    if "Reply with exactly: CONNECTION_OK" in prompt:
        return "CONNECTION_OK"
    if "Array: " in prompt:
        values = json.loads(prompt.split("Array: ", 1)[1])
        if not isinstance(values, list) or not values:
            raise ContractError("model_provider_response_invalid")
        return json.dumps({"count": len(values), "sum": sum(values), "min": min(values),
                           "max": max(values), "mean": sum(values) / len(values)})
    if "Data: " in prompt:
        # The extract_facts rubric asks for the given object back, unchanged.
        # Values are data: they are re-serialised, never interpreted.
        facts = json.loads(prompt.split("Data: ", 1)[1])
        if not isinstance(facts, dict):
            raise ContractError("model_provider_response_invalid")
        return json.dumps({str(key): str(value) for key, value in facts.items()}, ensure_ascii=False)
    if "Specification: " in prompt:
        # An application plan is returned exactly as the server composed it.
        # Nothing is added, and nothing here executes anything: the server
        # validates the plan again and runs it through its own adapters.
        spec = json.loads(prompt.split("Specification: ", 1)[1])
        if not isinstance(spec, dict):
            raise ContractError("model_provider_response_invalid")
        return json.dumps(spec, ensure_ascii=False)
    raise ContractError("model_test_executor_rubric_unsupported")


def execute(*, context, model, account, profile, prompt, system_prompt, request_id,
            conversation_id, max_output_tokens, purpose, cancelled, admit):
    """Answer locally, under the same admissions a provider call would face."""
    if not enabled(context.scope.workspace_id):
        raise ContractError("model_test_executor_disabled")
    started = time.monotonic()
    # The same checkpoint a real transmission takes, in the same order: current
    # authority first, then cancellation, and nothing is produced after either.
    admit(context, "provider_transmit", 0.0)
    if callable(cancelled) and cancelled():
        raise ContractError("model_cancelled")
    answer = _answer(str(prompt or ""))
    if len(answer) > int(max_output_tokens or 512) * 8:
        raise ContractError("model_provider_response_invalid")
    admit(context, "provider_transmit", 0.0)
    if callable(cancelled) and cancelled():
        raise ContractError("model_cancelled")
    return {"ok": True, "response": answer, "request_id": str(request_id),
            "actual_model": EXECUTOR, "executor": EXECUTOR, "provider": "local_test_executor",
            "elapsed_sec": max(0.0, time.monotonic() - started),
            # No call was made, so this is a measured zero, not an estimate.
            "cost_known": True, "cost_usd": 0.0,
            "input_tokens": len(str(prompt or "")) // 4, "output_tokens": len(answer) // 4,
            "external_call": False, "paid_call": False, "purpose": str(purpose or "")}
