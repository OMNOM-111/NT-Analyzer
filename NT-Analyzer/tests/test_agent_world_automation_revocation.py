"""Automation authority end to end, on the real account/workspace/flag stack.

Nothing here is stubbed out: the owner row, the workspace, the capability
override, the feature flags, the budget check, the durable job payload and the
Agent World records are all the real ones, on a disposable data root. No
provider is called, no network socket is opened and no owner data is touched.

Three sides of the same rule are pinned, because passing only one of them would
be a defect in the other direction:

  * without an explicit ``ai_automation`` grant nothing may be approved or run;
  * with a live grant plus the mechanism flag, an approved plan and budget head
    room, a run is admitted -- the withheld capability is not a blanket ban;
  * after the grant is withdrawn, new runs stop, including inside a worker that
    was already holding an open handle and inside one that restarts from an old
    durable checkpoint.

Records obtained before the withdrawal stay readable: revocation stops future
work, it does not erase what already happened.
"""
from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import account_auth, permissions, secure_store, subscriptions, workspaces
from app.ai_control_center import contracts as c
from app.ai_control_center import automation_authority, delegation, domain_gateway, live_gateway
from app.ai_control_center.model_evaluation import digest
from app.ai_control_center.model_service import _id, _key
from app.ai_control_center.states import ContractError, EntityKind

OWNER_ID = 990100
OWNER_UUID = "aa000000-0000-4000-8000-000000000101"
GRANT_KEY = "automation-authority-scenario"


def _mechanisms(workspace_id, *names):
    return json.dumps({"environment": "development",
                       "flags": {name: [workspace_id] for name in names}})


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "development"))
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "production-disabled"))
    monkeypatch.setenv("STRATFORGE_CANARY_DATA_ROOT", str(tmp_path / "canary-disabled"))
    monkeypatch.setenv("NT_ANALYZER_SQLITE_PATH", str(tmp_path / "durable.sqlite3"))
    monkeypatch.setenv("STRATFORGE_PREVIEW_SANDBOX", "0")
    monkeypatch.setenv("STRATFORGE_PREVIEW_ID", "")
    monkeypatch.setenv("STRATFORGE_AGENT_WORLD_STORAGE", "sqlite")
    # The owner identity the account store recognises for owner-only writes.
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", str(OWNER_ID))
    monkeypatch.setattr(live_gateway, "_SNAPSHOTS", {})
    monkeypatch.setattr(socket, "create_connection",
                        lambda *a, **kw: pytest.fail("automation contracts must not open sockets"))
    for module in (account_auth, subscriptions, workspaces):
        monkeypatch.setattr(module, "_root", lambda _base=tmp_path: _base)
    monkeypatch.setattr(secure_store, "available", lambda: True)
    monkeypatch.setattr(secure_store, "backend_name", lambda: "test DPAPI")
    monkeypatch.setattr(secure_store, "_protect", lambda value: value[::-1])
    monkeypatch.setattr(secure_store, "_unprotect", lambda value: value[::-1])

    account_auth._clear_doc_cache()
    account_auth._write_doc({"version": 2, "users": [{
        "user_id": OWNER_ID, "user_uuid": OWNER_UUID, "first_name": "Scenario",
        "role": "owner", "status": "active", "is_owner": True}],
        "challenges": [], "sessions": [], "trusted_devices": []})
    workspace = workspaces.ensure_owner_workspace(OWNER_ID)["workspace_id"]
    monkeypatch.setenv(live_gateway.WORKSPACES_ENV, workspace)
    monkeypatch.setenv(live_gateway.MECHANISMS_ENV,
                       _mechanisms(workspace, "AI_DELEGATION_V2", "AI_EXECUTION_V2"))

    scope = {"user_id": OWNER_ID, "user_uuid": OWNER_UUID, "workspace_id": workspace}

    def capability(value):
        """Grant (True) or withdraw (None) ai_automation as the owner would."""
        account_auth.set_user_permission(OWNER_ID, OWNER_ID, "ai_automation", value)
        return permissions.resolve_for_user_id(
            OWNER_ID, account_auth.find_active_user(OWNER_ID))["capabilities"]["ai_automation"]

    return SimpleNamespace(scope=scope, workspace=workspace, capability=capability,
                           mechanisms=lambda *names: _mechanisms(workspace, *names),
                           monkeypatch=monkeypatch)


def human(world):
    """A normal authorized owner session, resolved through the real gateway."""
    authorized = domain_gateway.access(world.scope)
    return authorized, domain_gateway.models(authorized)


def proposal(context, *, key=GRANT_KEY):
    controller = _id(context, "delegation:" + _key(key))
    plan = {"version": delegation.VERSION, "synthetic": False, "nodes": [],
            "note": "isolated automation scenario"}
    return controller, plan


def approve(world, *, key=GRANT_KEY, hours=2, ceiling=0.01):
    authorized, service = human(world)
    context = authorized["context"]
    controller, plan = proposal(context, key=key)
    grant = automation_authority.approve(
        authorized, service, proposal={"controller_id": str(controller), "plan": plan},
        kind="delegation", expires_at=(datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(),
        max_call_cost_usd=ceiling, approved_plan_sha256=digest(plan), idempotency_key=key)
    return SimpleNamespace(authorized=authorized, service=service, context=context,
                           controller=controller, plan=plan, grant=grant)


def sealed(session):
    """The controller task a real ``delegation.start`` would leave behind."""
    control = delegation.create_controller(
        session.service, session.context, session.controller,
        {**session.plan, "grant_ref": session.grant}, source=delegation.SOURCE, correlation=uuid4())
    return control


def run(session, operation="delegation_step", **kwargs):
    """Drive the mechanism's own call site, not the authority helper directly."""
    reference = c.EntityRef(kind=EntityKind.TASK, entity_id=session.controller,
                            revision=1, scope=session.context.scope)
    return delegation.authority(session.service, session.context, reference,
                                session.grant, operation, proposed_plan=session.plan, **kwargs)


def worker_job(world, session, *, phase="delegation_step"):
    """The durable payload a restarted worker would claim from the queue."""
    return {"kind": "agent_world_model", "workspace_id": world.workspace, "user_id": OWNER_ID,
            "worker_job_id": "wj_aw_delegate_scenario",
            "payload": {"phase": phase, "controller_id": str(session.controller),
                        "grant_ref": session.grant, "scope": world.scope,
                        "task_id": str(session.controller)}}


def test_owner_without_an_explicit_grant_can_neither_approve_nor_run_automation(world):
    authorized, service = human(world)
    context = authorized["context"]
    resolved = permissions.resolve_for_user_id(OWNER_ID, account_auth.find_active_user(OWNER_ID))
    # Being the owner grants everything else and still withholds this one.
    assert resolved["capabilities"]["ai_automation"] is False
    assert all(value for key, value in resolved["capabilities"].items() if key != "ai_automation")

    controller, plan = proposal(context)
    with pytest.raises(ContractError) as approval:
        automation_authority.approve(
            authorized, service, proposal={"controller_id": str(controller), "plan": plan},
            kind="delegation", expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            max_call_cost_usd=0.01, approved_plan_sha256=digest(plan), idempotency_key=GRANT_KEY)
    assert approval.value.code == "automation_entitlement_required"

    # Worker ingress fails on the same capability rather than on a missing
    # record, so a forged payload cannot mint authority either.
    with pytest.raises(ContractError) as ingress:
        automation_authority.access(world.scope, controller_id=str(controller),
                                    grant_ref={"artifact_id": str(controller), "sha256": "0" * 64,
                                               "scope": c.primitive(context.scope)})
    assert ingress.value.code == "automation_entitlement_required"


def test_granted_owner_approves_once_and_a_worker_runs_bound_to_that_grant(world):
    assert world.capability(True) is True
    session = approve(world)
    assert set(session.grant) == {"artifact_id", "sha256", "scope"}
    assert session.grant["scope"] == c.primitive(session.context.scope)

    admitted = run(session, "delegation_create")
    assert admitted["approved_scope"] == c.primitive(session.context.scope)
    assert admitted["sha256"] == session.grant["sha256"] and admitted["revision"] >= 1

    sealed(session)
    worker = domain_gateway.worker_authority(worker_job(world, session))
    assert worker["automation"] is True
    assert worker["context"].actor.kind == c.ActorKind.SERVICE
    assert worker["context"].actor.on_behalf_of == session.context.user_uuid
    assert worker["automation_controller_id"] == str(session.controller)
    # The service actor is derived, never carried in from the job payload.
    assert worker["context"].actor.actor_id != session.context.user_uuid


def test_withdrawing_the_capability_stops_an_open_worker_and_a_restarted_one(world):
    assert world.capability(True) is True
    session = approve(world)
    run(session, "delegation_create")
    sealed(session)
    job = worker_job(world, session)
    worker = domain_gateway.worker_authority(job)
    assert worker["admit"]() is None

    assert world.capability(None) is False

    # The handle the running worker already holds re-resolves live authority on
    # its next step instead of trusting the context it was created with.
    with pytest.raises(ContractError) as open_handle:
        worker["admit"]()
    assert open_handle.value.code == "automation_entitlement_required"

    with pytest.raises(ContractError) as next_step:
        run(session)
    assert next_step.value.code == "automation_entitlement_required"

    # Restart: the identical durable payload is claimed again from the queue.
    # An old checkpoint must not restore what was withdrawn.
    with pytest.raises(ContractError) as restarted:
        domain_gateway.worker_authority(job)
    assert restarted.value.code == "automation_entitlement_required"

    # What already happened stays readable and stays owned by the same human.
    history = domain_gateway.worker_authority(job, read_only=True)
    assert history["read_only"] is True and history["automation"] is True
    decision = domain_gateway.history_models(history)._get(
        history["context"], EntityKind.DECISION,
        _id(session.context, "automation-approval:" + str(session.controller)))
    assert decision.status == "approved"
    assert decision.header.created_by.kind == c.ActorKind.HUMAN


def test_a_withdrawn_capability_is_not_a_permanent_ban_on_automation(world):
    assert world.capability(True) is True
    session = approve(world)
    run(session, "delegation_create")
    sealed(session)
    job = worker_job(world, session)

    assert world.capability(None) is False
    with pytest.raises(ContractError):
        run(session)

    # Granting it again resumes the same approved plan under the same grant:
    # the stop is a live authority check, not a one-way latch.
    assert world.capability(True) is True
    assert run(session)["sha256"] == session.grant["sha256"]
    assert domain_gateway.worker_authority(job)["automation"] is True


def test_the_grant_alone_is_not_authority_flag_plan_and_budget_gate_every_step(world):
    assert world.capability(True) is True
    session = approve(world, ceiling=0.01)
    run(session, "delegation_create")
    sealed(session)

    # A cost above the approved per-call ceiling is refused even though the
    # workspace budget itself is not exhausted.
    with pytest.raises(ContractError) as budget:
        automation_authority.admit(
            session.authorized, session.service, context=session.context,
            controller=c.EntityRef(kind=EntityKind.TASK, entity_id=session.controller,
                                   revision=1, scope=session.context.scope),
            grant_ref=delegation.snapshot(session.context, session.grant),
            operation="delegation_step", estimated_cost_usd=0.5, proposed_plan=session.plan)
    assert budget.value.code == "automation_budget_denied"

    # An operation outside the approved kind is refused.
    with pytest.raises(ContractError) as operation:
        run(session, "schedule_step")
    assert operation.value.code == "automation_operation_denied"

    # A plan edited after approval is refused.
    with pytest.raises(ContractError) as changed:
        reference = c.EntityRef(kind=EntityKind.TASK, entity_id=session.controller,
                                revision=1, scope=session.context.scope)
        delegation.authority(session.service, session.context, reference, session.grant,
                             "delegation_step", proposed_plan={**session.plan, "nodes": [{"index": 0}]})
    assert changed.value.code == "automation_plan_changed"

    # Withdrawing the mechanism flag stops runs while the grant still stands.
    world.monkeypatch.setenv(live_gateway.MECHANISMS_ENV, world.mechanisms("AI_EXECUTION_V2"))
    live_gateway._SNAPSHOTS.clear()
    with pytest.raises(ContractError) as disabled:
        run(session)
    assert disabled.value.code == "automation_disabled"

    world.monkeypatch.setenv(live_gateway.MECHANISMS_ENV,
                             world.mechanisms("AI_DELEGATION_V2", "AI_EXECUTION_V2"))
    live_gateway._SNAPSHOTS.clear()
    assert run(session)["sha256"] == session.grant["sha256"]


def test_explicit_grant_revocation_stops_new_runs_without_erasing_the_record(world):
    assert world.capability(True) is True
    session = approve(world)
    run(session, "delegation_create")
    sealed(session)
    job = worker_job(world, session)

    authorized, service = human(world)
    revoked = automation_authority.revoke(
        authorized, service, delegation.snapshot(session.context, session.grant))
    assert revoked == {"revoked": True, "controller_id": str(session.controller)}

    for attempt in (lambda: run(session), lambda: domain_gateway.worker_authority(job)):
        with pytest.raises(ContractError) as stopped:
            attempt()
        assert stopped.value.code == "automation_approval_revoked"

    # Superseded, not deleted: the approval and its human author survive, and a
    # read-only worker may still deliver what the run already produced.
    history = domain_gateway.worker_authority(job, read_only=True)
    decision = domain_gateway.history_models(history)._get(
        history["context"], EntityKind.DECISION,
        _id(session.context, "automation-approval:" + str(session.controller)))
    assert decision.status == "superseded"
    assert decision.header.created_by.actor_id == session.context.user_uuid
    assert decision.approval == delegation.snapshot(session.context, session.grant)
