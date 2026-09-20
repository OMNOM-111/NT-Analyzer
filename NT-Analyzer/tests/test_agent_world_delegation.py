"""Finite delegation with real disposable domain records and queue claims."""
import copy
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app import durable, local_worker, worker_router
from app.ai_control_center import contracts as c, delegation as d, domain_gateway
from app.ai_control_center.flags import Flag, FlagRule, FlagSnapshot
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_result_handoff import (env, target, model_setup, chat_authorized, queue_service, canonical_queue)


@pytest.fixture
def mechanism(env):
    context, service = env.ctx, env.service
    names = {"AI_CONTROL_CENTER_READ_MODEL", "AI_TASK_GRAPH_V2", "AI_EXECUTION_V2", "AI_DELEGATION_V2", "AI_SCHEDULER_V1"}
    env.authorized["snapshot"] = FlagSnapshot(revision="mechanism-contract", audit_ref=uuid4(),
        rules=tuple(FlagRule(environment=context.scope.environment, workspace_id=workspace, flag=flag, enabled=True)
            for flag in Flag if flag.value in names for workspace in (None, context.scope.workspace_id)))
    env.approval = service._put(context, {"source": "trusted-disposable-grant", "workspace": context.scope.workspace_id})
    env.grant_state = {"active": True, "expires_at": (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat(), "calls": []}
    def admit(**kwargs):
        env.grant_state["calls"].append(kwargs)
        if (not env.grant_state["active"] or kwargs["grant_ref"] != env.approval
                or kwargs["context"].user_uuid != context.user_uuid or kwargs["context"].scope != context.scope):
            raise ContractError("fixture_automation_revoked")
        return {"approved_scope": c.primitive(context.scope), "revision": 1,
                "sha256": env.approval.sha256, "expires_at": env.grant_state["expires_at"]}
    service.mechanism_admit = admit
    service.mechanism_authorized = env.authorized
    service.chat_scope = env.authorized["chat_scope"]
    def enqueue(*, context, task_id):
        identity = "wj_aw_model_" + task_id.replace("-", "")
        payload = {"task_id": task_id, "scope": env.authorized["chat_scope"]}
        try:
            return worker_router.enqueue("agent_world_model", payload,
                job_id=identity, max_attempts=1, timeout_sec=60,
                user_id=env.authorized["source_scope"]["user_id"], workspace_id=context.scope.workspace_id, priority=55)
        except sqlite3.IntegrityError:
            existing = worker_router.get(identity, workspace_id=context.scope.workspace_id)
            assert existing["payload"] == payload and existing["kind"] == "agent_world_model"
            return existing
    service.enqueue = enqueue
    return env


def run_claimed(env):
    """Exercise real queue lease/fence and adapters, never a fake job row."""
    root, worker = local_worker._root(), "mechanism-contract-worker"
    job = durable.claim_worker_job(root, worker_id=worker)
    if job is None: return None
    def heartbeat():
        assert durable.heartbeat_worker_job(root, job["worker_job_id"], worker_id=worker)
    def cancelled():
        return durable.worker_cancel_requested(root, job["worker_job_id"], worker_id=worker)
    phase = job["payload"].get("phase")
    if phase == d.PHASE:
        result = d.execute(env.authorized, env.service, job, cancelled, heartbeat)
    elif phase == "scheduler_occurrence":
        from app.ai_control_center import scheduler
        result = scheduler.execute(env.authorized, env.service, job, cancelled, heartbeat)
    elif job["kind"] == "agent_world_model" and not phase:
        if getattr(env, "use_v2", False):
            from app.ai_control_center import execution_v2
            result = execution_v2.execute(env.authorized, env.service, job, cancelled, heartbeat)
        else:
            result = env.service.execute(context=env.ctx, task_id=job["payload"]["task_id"], cancelled=cancelled)
    else:
        result = domain_gateway.execute_worker(job, cancelled, heartbeat)
    durable.finish_worker_job(root, job["worker_job_id"], result, worker_id=worker)
    return job, result


def start(env, *, targets=None, parents=None, key="finite-delegation-one", depth=3):
    return d.start(env.authorized, env.service, env.source["id"], targets or [env.receiver["id"]], depth, key,
                   grant_ref=env.approval, parent_indices=parents)


def test_explicit_three_level_chain_uses_real_claims_typed_dependencies_and_outcomes(mechanism):
    env = mechanism
    two = target(env.setup, key="chain-target-two")
    three = target(env.setup, key="chain-target-three")
    opened = start(env, targets=[env.receiver["id"], two["id"], three["id"]], parents=[-1, 0, 1])
    root = env.service._get(env.ctx, EntityKind.TASK, env.source["id"])
    for _ in range(20):
        run_claimed(env)
        view = d.reconcile(env.authorized, env.service, opened["id"])
        if view["status"] == "review": break
    assert view["status"] == "review" and len(env.calls) == 3
    assert [node["depth"] for node in view["nodes"]] == [1, 2, 3]
    parent = root
    for node in view["nodes"]:
        task = env.service._get(env.ctx, EntityKind.TASK, node["task_id"])
        assert task.dependencies == (parent.ref(),) and task.header.correlation_id == root.header.correlation_id
        assert task.status == "succeeded"
        parent = task
    assert view["human_accepted"] is view["professional_quality_assessed"] is False
    before = len(env.calls)
    assert start(env, targets=[env.receiver["id"], two["id"], three["id"]], parents=[-1, 0, 1])["status"] == "review"
    assert run_claimed(env) is None and len(env.calls) == before


def test_tree_fanout_and_source_identity_are_bounded_before_creating_controllers(mechanism):
    env = mechanism
    others = [target(env.setup, key="bounded-target-" + str(i))["id"] for i in range(4)]
    root = env.service._get(env.ctx, EntityKind.TASK, env.source["id"])
    source_persona = env.service._json(env.ctx, root.checkpoint)["persona_id"]
    cases = [([env.receiver["id"]] * 2, [-1, 0], 3), (others[:3], [-1, -1, -1], 3),
             (others[:2], [1, -1], 3), (others[:2], [-1, 0], 1), (others[:4], [-1, 0, 1, 2], 3)]
    for ids, parents, depth in cases:
        with pytest.raises(ContractError): d._graph(ids, parents, depth, source_persona, env.service, env.ctx)
    assert len(d._graph(others[:3], [-1, -1, 0], 3, source_persona, env.service, env.ctx)) == 3


def test_duplicate_dispatch_and_restart_do_not_create_another_provider_task(mechanism):
    env = mechanism
    opened = start(env)
    second = start(env)
    assert opened["id"] == second["id"]
    for _ in range(10):
        run_claimed(env)
        if d.reconcile(env.authorized, env.service, opened["id"])["status"] == "review": break
    assert len(env.calls) == 1
    assert d.reconcile(env.authorized, env.service, opened["id"])["status"] == "review"
    assert run_claimed(env) is None and len(env.calls) == 1


@pytest.mark.parametrize("when", ["start", "queued", "provider"])
def test_grant_revocation_stops_new_background_steps(mechanism, when):
    env = mechanism
    if when == "start":
        env.grant_state["active"] = False
        with pytest.raises(ContractError, match="revoked"): start(env)
        assert not env.calls
        return
    opened = start(env)
    if when == "provider":
        for _ in range(10):
            result = run_claimed(env)
            if result and result[0]["payload"].get("phase") == d.PHASE: break
    env.grant_state["active"] = False
    if when == "provider":
        for _ in range(10):
            result = run_claimed(env)
            if result and result[0]["payload"].get("task_id") == str(d._child_id(env.ctx, opened["id"], 0)):
                assert result[1]["status"] == "blocked"
                break
        assert not env.calls
        return
    with pytest.raises(ContractError):
        for _ in range(10):
            if run_claimed(env) is None: break
    assert not env.calls


def test_proposal_is_read_only_and_approval_receives_exact_proposed_plan(mechanism):
    env = mechanism
    before = len(list(env.service._all(env.ctx, EntityKind.TASK)))
    queued = len(durable.list_worker_jobs(local_worker._root()))
    proposed = d.propose(env.authorized, env.service, env.source["id"], [env.receiver["id"]], 3, "proposal-contract")
    assert set(proposed) == {"controller_id", "plan"}
    assert not {"grant_ref", "expires_at"} & set(proposed["plan"])
    assert len(list(env.service._all(env.ctx, EntityKind.TASK))) == before
    assert len(durable.list_worker_jobs(local_worker._root())) == queued
    assert not env.grant_state["calls"] and not env.calls
    opened = start(env, key="proposal-contract")
    admitted = next(row for row in env.grant_state["calls"] if row["operation"] == "delegation_create")
    assert {key: value for key, value in admitted["proposed_plan"].items() if key != "grant_ref"} == proposed["plan"]
    assert opened["id"] == proposed["controller_id"]


def test_background_service_actor_resumes_without_inheriting_human_browser_authority(mechanism):
    env = mechanism
    opened = start(env)
    env.ctx = replace(env.ctx, actor=c.ActorRef(kind=c.ActorKind.SERVICE, actor_id=uuid4(), on_behalf_of=env.ctx.user_uuid))
    env.authorized["context"] = env.ctx
    for _ in range(12):
        run_claimed(env)
        view = d.reconcile(env.authorized, env.service, opened["id"])
        if view["status"] == "review": break
    assert view["status"] == "review" and len(env.calls) == 1
    child = env.service._get(env.ctx, EntityKind.TASK, view["nodes"][0]["task_id"])
    assert child.header.created_by.kind == c.ActorKind.SERVICE
    assert env.calls[0]["context"].actor.on_behalf_of == env.ctx.user_uuid
    job = worker_router.get("wj_aw_delegate_" + d._uuid(opened["id"]).hex + "_0", workspace_id=env.ctx.scope.workspace_id)
    assert set(job["payload"]["scope"]) == {"user_id", "user_uuid", "workspace_id"}


def test_kill_switch_still_permits_cancellation_but_not_new_dispatch(mechanism):
    env = mechanism
    opened = start(env)
    env.authorized["snapshot"] = FlagSnapshot()
    env.grant_state["active"] = False
    assert d.cancel(env.authorized, env.service, opened["id"])["status"] == "cancelled"
    with pytest.raises(ContractError, match="disabled"): d.reconcile(env.authorized, env.service, opened["id"])
    assert not env.calls


def test_mutating_sealed_source_before_provider_transmission_blocks_child(mechanism):
    env = mechanism
    opened = start(env)
    for _ in range(10):
        result = run_claimed(env)
        if result and result[0]["payload"].get("phase") == d.PHASE: break
    # Mutable target profile changed by an independent authorised operation.
    target_model = env.service._get(env.ctx, EntityKind.MODEL, env.receiver["id"])
    env.service._change(env.ctx, target_model, "suspended")
    for _ in range(10):
        if run_claimed(env) is None: break
    child = env.service._get(env.ctx, EntityKind.TASK, d._child_id(env.ctx, opened["id"], 0))
    assert child.status == "blocked" and not env.calls


def test_payload_cannot_inject_changed_source_or_foreign_scope(mechanism):
    env = mechanism
    start(env)
    root = local_worker._root()
    for _ in range(10):
        job = durable.claim_worker_job(root, worker_id="tamper-claim")
        if job["payload"].get("phase") == d.PHASE: break
        durable.finish_worker_job(root, job["worker_job_id"], {}, worker_id="tamper-claim")
    changed = copy.deepcopy(job)
    changed["payload"]["scope"]["workspace_id"] = "ws_foreign"
    with pytest.raises(ContractError): d.execute(env.authorized, env.service, changed, lambda: False, lambda: None)
    changed = copy.deepcopy(job)
    changed["payload"]["plan_sha256"] = "0" * 64
    with pytest.raises(ContractError): d.execute(env.authorized, env.service, changed, lambda: False, lambda: None)
    assert not env.calls


def test_cancellation_is_durable_before_child_transmission(mechanism):
    env = mechanism
    opened = start(env)
    cancelled = d.cancel(env.authorized, env.service, opened["id"])
    assert cancelled["status"] == "cancelled"
    assert d.reconcile(env.authorized, env.service, opened["id"])["status"] == "cancelled" and not env.calls


def test_automation_artifact_alone_is_not_authority(mechanism):
    env = mechanism
    env.service.mechanism_admit = None
    with pytest.raises(ContractError, match="authority_required"): start(env)
    assert not env.calls


@pytest.mark.parametrize("kind", ["delegation", "schedule"])
def test_existing_enqueue_and_execution_v2_fence_real_service_child_without_browser_authority(mechanism, kind):
    from app.ai_control_center import execution_v2, scheduler
    from tests.test_agent_world_scheduler import create as schedule_create
    env = mechanism
    env.use_v2 = True
    env.service.enqueue = lambda **kwargs: domain_gateway.enqueue_model(env.authorized, **kwargs)
    opened = start(env) if kind == "delegation" else schedule_create(env)[2]
    env.ctx = replace(env.ctx, actor=c.ActorRef(kind=c.ActorKind.SERVICE, actor_id=uuid4(), on_behalf_of=env.ctx.user_uuid))
    env.authorized.update(context=env.ctx, automation=True, automation_controller_id=opened["id"],
        automation_grant_ref=c.primitive(env.approval),
        refresh=lambda *, read_only=False: {**env.authorized, "read_only": read_only})
    reconcile = d.reconcile if kind == "delegation" else scheduler.tick
    for _ in range(20):
        reconcile(env.authorized, env.service, opened["id"])
        run_claimed(env)
        view = reconcile(env.authorized, env.service, opened["id"])
        if view["status"] == "review": break
    assert view["status"] == "review" and len(env.calls) == 1
    task_id = view["nodes"][0]["task_id"] if kind == "delegation" else view["occurrences"][0]["task_id"]
    child = env.service._get(env.ctx, EntityKind.TASK, task_id)
    assert child.header.created_by.kind == c.ActorKind.SERVICE and child.status == "succeeded"
    assert execution_v2.projection(env.service, env.ctx, task_id)["status"] == "succeeded"
    _, approved, _ = execution_v2._load(env.service, env.ctx, task_id)
    assert approved["delegation"]["kind"] == ("delegation_v1" if kind == "delegation" else "schedule_v1")
    assert approved["actor"]["kind"] == "service" and approved["commands"] == ["bounded_model_text"]
    original = env.service._execution(env.ctx, task_id)
    origin = env.service._json(env.ctx, original.approval)
    assert origin["source"] == "approved_bounded_automation"


@pytest.mark.parametrize("kind", ["delegation", "schedule"])
def test_reclaim_after_child_enqueue_preserves_one_provider_call_and_rejects_old_claim(mechanism, kind):
    from app.ai_control_center import scheduler
    from tests.test_agent_world_scheduler import create as schedule_create
    env = mechanism
    for _ in range(12):
        if run_claimed(env) is None: break
    opened = start(env) if kind == "delegation" else schedule_create(env)[2]
    module = d if kind == "delegation" else scheduler
    reconcile = d.reconcile if kind == "delegation" else scheduler.tick
    reconcile(env.authorized, env.service, opened["id"])
    root = local_worker._root()
    job = durable.claim_worker_job(root, worker_id="before-crash")
    assert job["payload"]["phase"] == module.PHASE
    first = module.execute(env.authorized, env.service, job, lambda: False, lambda: None)
    assert first["status"] == "child_queued" and not env.calls
    durable.fail_worker_job(root, job["worker_job_id"], "isolated_crash_after_enqueue", worker_id="before-crash", retry=True)
    result = run_claimed(env)
    assert result[0]["kind"] == "agent_world_model" and len(env.calls) == 1
    assert reconcile(env.authorized, env.service, opened["id"])["status"] == "review"
    resumed = durable.claim_worker_job(root, worker_id="after-crash")
    assert resumed["worker_job_id"] == job["worker_job_id"] and resumed["attempts"] == 2
    with pytest.raises(ContractError): module.execute(env.authorized, env.service, job, lambda: False, lambda: None)
    replayed = module.execute(env.authorized, env.service, resumed, lambda: False, lambda: None)
    assert replayed["replayed"] is True and replayed["provider_dispatch"] is False
    durable.finish_worker_job(root, resumed["worker_job_id"], replayed, worker_id="after-crash")
    assert len(env.calls) == 1


@pytest.mark.parametrize("kind", ["delegation", "schedule"])
def test_exhausted_coordination_job_blocks_controller_without_creating_a_new_queue(mechanism, kind):
    from app.ai_control_center import scheduler
    from tests.test_agent_world_scheduler import create as schedule_create
    env = mechanism
    for _ in range(12):
        if run_claimed(env) is None: break
    opened = start(env) if kind == "delegation" else schedule_create(env)[2]
    reconcile = d.reconcile if kind == "delegation" else scheduler.tick
    reconcile(env.authorized, env.service, opened["id"])
    root = local_worker._root()
    for attempt in range(3):
        job = durable.claim_worker_job(root, worker_id="failure-test")
        assert job["attempts"] == attempt + 1
        durable.fail_worker_job(root, job["worker_job_id"], "isolated_pre_enqueue_failure", worker_id="failure-test", retry=True)
    assert durable.get_worker_job(root, job["worker_job_id"])["status"] == "failed"
    current = reconcile(env.authorized, env.service, opened["id"])
    assert current["status"] == "blocked" and not env.calls


@pytest.mark.parametrize("kind", ["delegation", "schedule"])
def test_proposal_pins_connection_before_later_child_enqueue(mechanism, kind):
    from app.ai_control_center import scheduler
    from tests.test_agent_world_scheduler import create as schedule_create
    env = mechanism
    for _ in range(12):
        if run_claimed(env) is None: break
    opened = start(env) if kind == "delegation" else schedule_create(env)[2]
    module = d if kind == "delegation" else scheduler
    if kind == "schedule": scheduler.tick(env.authorized, env.service, opened["id"])
    model = env.service._get(env.ctx, EntityKind.MODEL, env.receiver["id"])
    profile = env.service._json(env.ctx, model.profile)
    env.service._change(env.ctx, model, profile=env.service._put(env.ctx, {**profile, "base_url": "https://example.invalid/v1"}))
    job = durable.claim_worker_job(local_worker._root(), worker_id="changed-approved-connection")
    with pytest.raises(ContractError, match="target_changed"):
        module.execute(env.authorized, env.service, job, lambda: False, lambda: None)
    assert not env.calls
