"""The external-agent route an ordinary user actually walks, end to end.

Add a connection, verify it, let the Coordinator pick a compatible role,
dispatch through the existing durable worker, and read back the Contribution,
Outcome and Evaluation it produced — then revoke it and watch the next dispatch
be refused.

Everything goes through `domain_gateway`, the same entry the HTTP route uses,
and through real worker jobs claimed from the durable queue. Nothing here calls
a repository directly, because a route that only works when a test drives its
internals is not a route.

Disposable data root, development-only synthetic agent, zero sockets.
"""
from __future__ import annotations

import socket
from types import SimpleNamespace
from uuid import UUID

import pytest

from app import durable, local_worker
from app.ai_control_center import domain_gateway as gateway, external_agent_development as dev
from app.ai_control_center import live_gateway, reputation
from app.ai_control_center.external_agent_protocol import CAPABILITIES, PROTOCOL
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_automation_revocation import human, world  # noqa: F401


CAPABILITY = sorted(CAPABILITIES)[0]
MECHANISMS = ("AI_EXTERNAL_AGENT_V1", "AI_EXTERNAL_AGENT_TEST_V1", "AI_EXECUTION_V2", "AI_DELEGATION_V2")


@pytest.fixture
def external(world, monkeypatch):  # noqa: F811
    """An owner session with the external-agent mechanisms switched on."""
    assert world.capability(True)
    monkeypatch.setenv(live_gateway.MECHANISMS_ENV, world.mechanisms(*MECHANISMS))
    monkeypatch.setattr(live_gateway, "_SNAPSHOTS", {})
    # A socket here would mean the "synthetic" agent reached the network.
    monkeypatch.setattr(socket, "create_connection",
                        lambda *a, **kw: pytest.fail("the development agent must not open a socket"))
    authorized, service = human(world)
    return SimpleNamespace(world=world, authorized=authorized, service=service,
                           context=authorized["context"])


def act(env, identity, action, payload=None, revision=None, key=None):
    body = {"payload": payload or {}, "idempotency_key": key or f"external-{action}-{identity}"}
    if revision is not None:
        body["expected_revision"] = revision
    return gateway.mutate(env.authorized, "external_agents", identity, action, body)


def drain(limit=25):
    """Claim and run real worker jobs, exactly as the local worker does."""
    worker, jobs = "external-agent-acceptance", []
    for _ in range(limit):
        job = durable.claim_worker_job(local_worker._root(), worker_id=worker)
        if job is None:
            return jobs
        def heartbeat():
            durable.heartbeat_worker_job(local_worker._root(), job["worker_job_id"], worker_id=worker)
        def cancelled():
            return durable.worker_cancel_requested(local_worker._root(), job["worker_job_id"], worker_id=worker)
        try:
            result = gateway.execute_worker(job, cancelled, heartbeat)
        except ContractError as error:
            result = {"ok": False, "error_code": error.code}
        durable.finish_worker_job(local_worker._root(), job["worker_job_id"], result, worker_id=worker)
        jobs.append((job, result))
    raise AssertionError("bounded worker batch did not settle")


def connected(env, key="e2e"):
    """Add and verify one development connection, through the gateway."""
    created = act(env, "new", "create", {
        "display_name": "Development · внешний агент", "protocol": PROTOCOL,
        "endpoint": dev.ENDPOINT, "credential": dev.CREDENTIAL,
        "allowed_capabilities": [CAPABILITY]}, key=f"external-create-{key}")
    active = act(env, created["id"], "verify", revision=created["revision"],
                 key=f"external-verify-{key}")
    return active


def test_an_ordinary_user_adds_verifies_dispatches_and_reads_the_result(external):
    env = external

    listing = gateway.list_domain(env.authorized, "external_agents")
    assert listing["items"] == [] and listing["protocols"] == [PROTOCOL]
    assert listing["test_connection"]["synthetic"] is True

    detail = connected(env)
    assert detail["status"] == "active" and detail["verification_state"] == "verified"
    assert detail["allowed_capabilities"] == [CAPABILITY]
    assert detail["last_verification"] and detail["provenance"]["card_sha256"]
    # It is never a Model, and says so in the shape the page reads.
    assert detail["model_id"] is None and detail["model"] == "unknown / externally managed"
    assert detail["real_benchmark_eligible"] is False
    assert "task" in detail["actions"]

    started = act(env, detail["id"], "task", {"input_text": "[17,-4,12,9]"},
                  key="external-task-one")
    task_id = started["started_task_id"]
    jobs = drain()
    assert [job["kind"] for job, _ in jobs] == ["agent_world_external"], jobs
    assert jobs[0][1]["ok"] is True, jobs[0][1]

    after = gateway.list_domain(env.authorized, "external_agents", identity=detail["id"])
    rows = {row["id"]: row for row in after["tasks"]}
    assert task_id in rows
    finished = rows[task_id]
    assert finished["status"] == "review" and finished["error_code"] is None
    assert finished["contribution_id"] and finished["evaluation_id"]
    assert finished["synthetic"] is True and finished["requires_human_review"] is True
    assert after["statistics"]["tasks_completed"] == 1
    assert after["current_task"] is None

    # The evaluation is about the connection, not about any model.
    evaluation = env.service._get(env.context, EntityKind.EVALUATION, finished["evaluation_id"])
    assert evaluation.subject.kind is EntityKind.EXTERNAL_AGENT_CONNECTION
    assert str(evaluation.subject.entity_id) == detail["id"]
    proof = env.service._json(env.context, evaluation.evidence)
    assert proof["model_id"] is None and proof["performance_scope"] == "external_agent_performance"
    assert proof["synthetic"] is True and proof["external_call"] is False


def test_the_performance_it_earns_is_its_own_and_never_a_model_score(external):
    env = external
    detail = connected(env, key="scope")
    for index in range(3):
        act(env, detail["id"], "task", {"input_text": "[1,2,3]"}, key=f"external-scope-{index}")
        drain()

    view = gateway.list_domain(env.authorized, "external_agents", identity=detail["id"])["performance"]
    assert view["scope"] == "external_agent_performance"
    assert view["subject"]["kind"] == "external_agent_connection"
    assert view["subject"]["id"] == detail["id"]
    assert view["sample_size"] == 3 and view["status"] == "measured"
    # Three runs of a development agent are a diagnostic, not field performance.
    assert view["basis"] == "diagnostic"
    assert view["provenance"]["measured_observations"] == 0

    # The scope belongs to this kind alone, and no model scope can reach it.
    assert reputation.SCOPES["external_agent_performance"] is EntityKind.EXTERNAL_AGENT_CONNECTION
    for scope, kind in reputation.SCOPES.items():
        if scope == "external_agent_performance":
            continue
        other = env.service.reputation(context=env.context, subject_kind=kind,
                                       subject_id=UUID(detail["id"]), task_class="json_arithmetic")
        assert other["sample_size"] == 0, f"{scope} is counting an external agent's rows"


def test_revoking_ends_it_and_the_next_dispatch_is_refused(external):
    env = external
    detail = connected(env, key="revoke")
    act(env, detail["id"], "task", {"input_text": "[4,5,6]"}, key="external-before-revoke")
    drain()

    current = gateway.list_domain(env.authorized, "external_agents", identity=detail["id"])
    revoked = act(env, detail["id"], "revoke", revision=current["revision"], key="external-revoke")
    assert revoked["status"] == "revoked"
    assert revoked["allowed_capabilities"] == [] and revoked["availability"] == "unavailable"
    assert "task" not in revoked["actions"] and revoked["actions"] == []

    with pytest.raises(ContractError) as refused:
        act(env, detail["id"], "task", {"input_text": "[7,8,9]"}, key="external-after-revoke")
    # Refused for the reason that is actually true. "No compatible role" would
    # also have been true and would have told the person nothing.
    assert refused.value.code == "external_agent_revoked"

    # The history it already earned survives the revocation.
    after = gateway.list_domain(env.authorized, "external_agents", identity=detail["id"])
    assert after["statistics"]["tasks_completed"] == 1
    assert after["performance"]["sample_size"] == 1
