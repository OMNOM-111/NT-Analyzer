"""What must still hold when the external agent, the clock or the user misbehave.

Each case drives the native route — gateway in, durable worker out — and then
asserts the thing that would actually hurt: a revoked connection that still got
dispatched, a rotated secret that an in-flight task kept using, a capability the
agent was never granted, a second dispatch from one idempotency key, a cleanup
that gave up after one failure.

Disposable data root, development-only synthetic agent, zero sockets.
"""
from __future__ import annotations

import threading
import time

import pytest

from app.ai_control_center import domain_gateway as gateway, external_agent_development as dev
from app.ai_control_center import external_agent_protocol as protocol
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_automation_revocation import human, world  # noqa: F401
from tests.test_external_agent_native_e2e import (  # noqa: F401
    CAPABILITY, act, connected, drain, external)


def detail_of(env, identity):
    return gateway.list_domain(env.authorized, "external_agents", identity=identity)


def task_row(env, identity, task_id):
    rows = {row["id"]: row for row in detail_of(env, identity)["tasks"]}
    return rows.get(task_id)


# --- revocation beats anything still in flight --------------------------------

def test_revoking_before_the_worker_claims_stops_the_dispatch(external):
    """The job is already queued. It must not reach the agent anyway."""
    env = external
    conn = connected(env, key="revoke-claim")
    started = act(env, conn["id"], "task", {"input_text": "[1,2,3]"}, key="revoke-claim-task")
    act(env, conn["id"], "revoke", revision=detail_of(env, conn["id"])["revision"],
        key="revoke-claim-revoke")

    jobs = drain()
    external_jobs = [result for job, result in jobs if job["kind"] == "agent_world_external"]
    assert external_jobs and external_jobs[0]["ok"] is False
    row = task_row(env, conn["id"], started["started_task_id"])
    assert row["status"] == "blocked"
    assert row["error_code"] == "external_agent_revoked_or_changed"
    assert row["evaluation_id"] is None, "a stopped dispatch must not earn an evaluation"


def test_revoking_while_the_agent_is_answering_still_denies_the_result(external, monkeypatch):
    """Revocation lands mid-call. The reply must not become evidence."""
    env = external
    conn = connected(env, key="revoke-inflight")
    started = act(env, conn["id"], "task", {"input_text": "[2,4,6]"}, key="revoke-inflight-task")

    original = dev.client
    def revoking_client(authorized):
        client = original(authorized)
        inner = client.transport
        def transport(endpoint, *, credential, packet, timeout):
            if packet.get("method") == "message/send":
                # The user revokes while the agent is mid-answer.
                act(env, conn["id"], "revoke", revision=detail_of(env, conn["id"])["revision"],
                    key="revoke-inflight-revoke")
            return inner(endpoint, credential=credential, packet=packet, timeout=timeout)
        client.transport = transport
        return client
    monkeypatch.setattr(dev, "client", revoking_client)

    drain()
    row = task_row(env, conn["id"], started["started_task_id"])
    assert row["status"] == "blocked", row
    assert row["evaluation_id"] is None
    assert detail_of(env, conn["id"])["statistics"]["tasks_completed"] == 0


# --- credentials --------------------------------------------------------------

def test_rotating_the_secret_retires_the_connection_until_it_is_verified_again(external):
    env = external
    conn = connected(env, key="rotate")
    rotated = act(env, conn["id"], "rotate", {"credential": dev.CREDENTIAL},
                  revision=detail_of(env, conn["id"])["revision"], key="rotate-once")

    assert rotated["status"] == "disabled"
    assert rotated["allowed_capabilities"] == []
    assert rotated["last_error"] == "external_agent_reverification_required"
    assert "task" not in rotated["actions"], "a rotated connection must not stay dispatchable"

    with pytest.raises(ContractError) as refused:
        act(env, conn["id"], "task", {"input_text": "[1,2,3]"}, key="rotate-task-denied")
    assert refused.value.code == "external_agent_not_active"

    reverified = act(env, conn["id"], "verify", revision=rotated["revision"], key="rotate-verify")
    assert reverified["status"] == "active" and reverified["allowed_capabilities"] == [CAPABILITY]


def test_a_task_pinned_to_the_old_revision_refuses_after_a_rotation(external):
    """The in-flight task was approved against a connection that no longer exists."""
    env = external
    conn = connected(env, key="stale")
    started = act(env, conn["id"], "task", {"input_text": "[5,5,5]"}, key="stale-task")
    act(env, conn["id"], "rotate", {"credential": dev.CREDENTIAL},
        revision=detail_of(env, conn["id"])["revision"], key="stale-rotate")

    drain()
    row = task_row(env, conn["id"], started["started_task_id"])
    assert row["status"] == "blocked"
    assert row["error_code"] == "external_agent_revoked_or_changed"


# --- capabilities -------------------------------------------------------------

def test_an_agent_cannot_widen_its_own_capabilities_at_verification(external, monkeypatch):
    """The card is the agent's claim, not the grant. The grant is the user's."""
    env = external
    created = act(env, "new", "create", {
        "display_name": "Development · расширение", "protocol": protocol.PROTOCOL,
        "endpoint": dev.ENDPOINT, "credential": dev.CREDENTIAL,
        "allowed_capabilities": [CAPABILITY]}, key="escalation-create")

    original = dev.client
    def greedy_client(authorized):
        client = original(authorized)
        inner = client.transport
        def transport(endpoint, *, credential, packet, timeout):
            reply = inner(endpoint, credential=credential, packet=packet, timeout=timeout)
            card = reply.get("result") or {}
            if "skills" in card:
                card["skills"] = list(card["skills"]) + [
                    {"id": "stratforge.trade_execution.v1", "name": "Trading",
                     "description": "Not granted", "tags": ["escalation"]}]
            return reply
        client.transport = transport
        return client
    monkeypatch.setattr(dev, "client", greedy_client)

    # Verification succeeds — the agent is allowed to describe itself — but the
    # extra skill is simply never granted. The grant is the intersection of what
    # the user asked for and what the agent proves, and an agent adding a line
    # to its own card cannot move that.
    verified = act(env, created["id"], "verify", revision=created["revision"], key="escalation-verify")
    assert verified["status"] == "active"
    assert verified["allowed_capabilities"] == [CAPABILITY]
    assert "stratforge.trade_execution.v1" not in verified["allowed_capabilities"]

    # And the work it is actually given runs under the granted capability, not
    # the invented one.
    started = act(env, created["id"], "task", {"input_text": "[1,2,3]"}, key="escalation-task")
    drain()
    task = env.service._get(env.context, EntityKind.TASK, started["started_task_id"])
    checkpoint = env.service._json(env.context, task.checkpoint)
    assert checkpoint["capability"] == CAPABILITY

    service = gateway.external_agents(env.authorized)
    row = service.connection(created["id"])
    from app.ai_control_center.external_agent_contracts import candidate
    role = env.service._get(env.context, EntityKind.AGENT_ROLE, task.role.entity_id)
    assert candidate(row, context=env.context, role=role,
                     capability="stratforge.trade_execution.v1") is False
    assert candidate(row, context=env.context, role=role, capability=CAPABILITY) is True


def test_an_agent_that_drops_a_skill_loses_it_rather_than_keeping_the_grant(external, monkeypatch):
    env = external
    conn = connected(env, key="downgrade")
    assert conn["allowed_capabilities"] == [CAPABILITY]

    original = dev.client
    def forgetful_client(authorized):
        client = original(authorized)
        inner = client.transport
        def transport(endpoint, *, credential, packet, timeout):
            reply = inner(endpoint, credential=credential, packet=packet, timeout=timeout)
            card = reply.get("result") or {}
            if "skills" in card:
                card["skills"] = []
            return reply
        client.transport = transport
        return client
    monkeypatch.setattr(dev, "client", forgetful_client)

    with pytest.raises(ContractError):
        act(env, conn["id"], "verify", revision=conn["revision"], key="downgrade-verify")
    after = detail_of(env, conn["id"])
    assert after["allowed_capabilities"] == []
    assert after["status"] != "active"


# --- dispatch identity --------------------------------------------------------

def test_one_idempotency_key_dispatches_once(external):
    env = external
    conn = connected(env, key="dup")
    first = act(env, conn["id"], "task", {"input_text": "[3,3,3]"}, key="dup-task")
    second = act(env, conn["id"], "task", {"input_text": "[3,3,3]"}, key="dup-task")
    assert first["started_task_id"] == second["started_task_id"]

    jobs = drain()
    external_jobs = [job for job, _ in jobs if job["kind"] == "agent_world_external"]
    assert len(external_jobs) == 1, external_jobs
    assert len(detail_of(env, conn["id"])["tasks"]) == 1


def test_the_same_key_with_different_input_is_refused_rather_than_silently_reused(external):
    env = external
    conn = connected(env, key="dup-conflict")
    act(env, conn["id"], "task", {"input_text": "[1,1,1]"}, key="dup-conflict-task")
    with pytest.raises(ContractError) as refused:
        act(env, conn["id"], "task", {"input_text": "[9,9,9]"}, key="dup-conflict-task")
    assert refused.value.code == "external_agent_idempotency_conflict"


# --- the agent misbehaving ----------------------------------------------------

def test_an_agent_that_never_answers_leaves_a_named_failure_not_a_result(external, monkeypatch):
    env = external
    conn = connected(env, key="timeout")
    started = act(env, conn["id"], "task", {"input_text": "[8,8,8]"}, key="timeout-task")

    original = dev.client
    def timing_out_client(authorized):
        client = original(authorized)
        def transport(endpoint, *, credential, packet, timeout):
            raise ContractError("external_agent_timeout")
        client.transport = transport
        return client
    monkeypatch.setattr(dev, "client", timing_out_client)

    drain()
    row = task_row(env, conn["id"], started["started_task_id"])
    assert row["status"] == "blocked" and row["error_code"] == "external_agent_timeout"
    assert row["evaluation_id"] is None
    assert detail_of(env, conn["id"])["performance"]["sample_size"] == 0


# --- cross-process serialisation ---------------------------------------------

def test_the_connection_guard_serialises_two_writers(external):
    """Dispatch and revoke cannot interleave inside one connection."""
    env = external
    conn = connected(env, key="guard")
    service = gateway.external_agents(env.authorized)
    order, hold = [], threading.Event()

    def first():
        with service.repository.guard(env.context, conn["id"]):
            order.append("first-in")
            hold.set()
            time.sleep(0.2)
            order.append("first-out")

    def second():
        hold.wait(2)
        with service.repository.guard(env.context, conn["id"], timeout=5):
            order.append("second-in")

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert order == ["first-in", "first-out", "second-in"], order


# --- cleanup survives a failing secret store ---------------------------------

def test_a_failed_credential_deletion_does_not_report_the_revocation_as_failed(external, monkeypatch):
    """The authority is gone the moment the record says revoked.

    Reporting the whole revocation as failed because a secret blob could not be
    deleted is the one wrong answer here: it invites the user to believe the
    agent still has access, and to go looking for a way to revoke it again.
    """
    env = external
    conn = connected(env, key="cleanup")
    from app import secure_store
    calls = []
    def refusing(key):
        calls.append(key)
        raise OSError("secret store temporarily unavailable")
    monkeypatch.setattr(secure_store, "delete_secret", refusing)

    revoked = act(env, conn["id"], "revoke", revision=detail_of(env, conn["id"])["revision"],
                  key="cleanup-revoke")
    assert revoked["status"] == "revoked"
    assert revoked["credential_cleanup"] == "pending"
    assert calls, "cleanup was never attempted"

    # And the retry is queued on the existing worker, not lost.
    from app import worker_router
    from uuid import UUID
    job = worker_router.get("wj_aw_external_cleanup_" + UUID(conn["id"]).hex,
                            workspace_id=env.context.scope.workspace_id)
    assert job and job["kind"] == "agent_world_external"
    assert job["payload"]["phase"] == "external_cleanup"


def test_the_queued_cleanup_finishes_once_the_secret_store_recovers(external, monkeypatch):
    env = external
    conn = connected(env, key="cleanup-retry")
    from app import secure_store
    real = secure_store.delete_secret
    broken = {"until": 1}
    def flaky(key):
        if broken["until"]:
            broken["until"] -= 1
            raise OSError("temporary")
        return real(key)
    monkeypatch.setattr(secure_store, "delete_secret", flaky)

    act(env, conn["id"], "revoke", revision=detail_of(env, conn["id"])["revision"],
        key="cleanup-retry-revoke")
    results = [result for job, result in drain() if job["payload"].get("phase") == "external_cleanup"]
    assert results and results[0].get("ok") is True, results
    assert broken["until"] == 0
