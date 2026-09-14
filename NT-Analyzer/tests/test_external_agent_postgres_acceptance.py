"""Opt-in P1-5 native PG acceptance, separate from historical storage PASS.

Uses the same disposable-only DB admission as the repository suite. The native
gateway and durable worker execute synthetic tasks; spawned processes exercise
the actual transaction advisory lock, not a SQL-recording fake.
"""
from dataclasses import replace
from datetime import datetime, timezone
import multiprocessing
import os
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.ai_control_center import domain_gateway as gateway, live_gateway
from app import account_auth, workspaces
from app.ai_lab import chief_agent
from app.ai_control_center.external_agent_repository import NativeExternalRepository
from app.ai_control_center.postgres_repository import PostgresAgentWorldRepository
from app.ai_control_center.states import ContractError, EntityKind
from app.production_storage.core import PostgresClient
from tests.test_agent_world_postgres import database, repo  # noqa: F401
from tests.test_agent_world_automation_revocation import world, OWNER_ID  # noqa: F401
from tests.test_external_agent_native_e2e import (
    MECHANISMS, act, connected, drain,
    test_an_ordinary_user_adds_verifies_dispatches_and_reads_the_result,
    test_the_performance_it_earns_is_its_own_and_never_a_model_score,
    test_revoking_ends_it_and_the_next_dispatch_is_refused,
)
from tests.test_external_agent_native_hardening import (
    test_revoking_before_the_worker_claims_stops_the_dispatch,
    test_rotating_the_secret_retires_the_connection_until_it_is_verified_again,
)


@pytest.fixture
def external(world, repo, monkeypatch, tmp_path):  # noqa: F811
    # Persist an ordinary non-owner, confirmed device/session and personal
    # workspace. Initial registration is fixture state, not registration QA.
    monkeypatch.setattr(chief_agent.paths, "REGISTRY_DIR", tmp_path / "external-chat-registry")
    monkeypatch.setattr(chief_agent.paths, "PROJECT_ROOT", tmp_path)
    uid, identity, device = 990102, str(uuid4()), str(uuid4())
    session = "pg-external-ordinary-session"
    document = account_auth._read_doc()
    document["users"].append({"user_id": uid, "user_uuid": identity, "is_owner": False,
        "status": "active", "role": "full_control", "ux_mode": "professional",
        "first_name": "PG external", "last_name": "Fixture", "email": "pg-external@example.invalid"})
    document["sessions"].append({"session_id": session, "user_id": uid, "expires_at": time.time() + 3600,
        "revoked": False, "device_confirmation_state": "active", "trusted_device_id": device,
        "device_trust_mode": "permanent"})
    document["trusted_devices"].append({"device_id": device, "user_uuid": identity,
        "status": "trusted", "trust_mode": "permanent"})
    account_auth._write_doc(document)
    for capability in ("ai_lab", "ai_pro_models"):
        account_auth.set_user_permission(OWNER_ID, uid, capability, True)
    workspace = workspaces.ensure_personal_workspace(uid, require_entitlement=False)["workspace_id"]
    monkeypatch.setenv(live_gateway.WORKSPACES_ENV, workspace)
    monkeypatch.setenv(live_gateway.MECHANISMS_ENV,
                       world.mechanisms(*MECHANISMS).replace(world.workspace, workspace))
    monkeypatch.setenv("STRATFORGE_AGENT_WORLD_STORAGE", "postgres")
    monkeypatch.setenv("STRATFORGE_AGENT_WORLD_DATABASE_URL",
                       os.environ["STRATFORGE_TEST_AGENT_WORLD_POSTGRES_URL"])
    monkeypatch.setattr(live_gateway, "_SNAPSHOTS", {})
    authorized = gateway.access({"user_id": uid, "user_uuid": identity,
        "workspace_id": workspace, "auth_session_id": session})
    assert authorized["chat_scope"]["is_owner"] is False
    assert authorized["chat_scope"]["uses_owner_runtime"] is False
    service = gateway.models(authorized)
    assert isinstance(service.repository, PostgresAgentWorldRepository)
    return SimpleNamespace(world=world, authorized=authorized, service=service,
                           context=authorized["context"])


def test_pg_history_survives_new_repository_and_is_private(external):
    detail = connected(external, "restart-isolation")
    started = act(external, detail["id"], "task", {"input_text": "[7,8,9]"}, key="pg-restart-task")
    assert drain()[0][1]["ok"]
    live_gateway._SNAPSHOTS.clear()
    restarted = gateway.models(external.authorized)
    assert restarted.repository is not external.service.repository
    identity = UUID(detail["id"])
    assert restarted.repository.get(context=external.context, kind=EntityKind.EXTERNAL_AGENT_CONNECTION,
                              entity_id=identity) is not None
    public = gateway.list_domain(external.authorized, "external_agents", identity=detail["id"])
    assert public["tasks"][0]["id"] == started["started_task_id"]
    assert public["statistics"]["tasks_completed"] == 1
    assert public["performance"]["sample_size"] == 1
    foreign_id = uuid4()
    foreign = replace(external.context, user_uuid=foreign_id,
                      actor=replace(external.context.actor, actor_id=foreign_id))
    other_workspace = replace(external.context,
        scope=replace(external.context.scope, workspace_id="ws_foreign_pg_external"))
    for context in (foreign, other_workspace):
        assert restarted.repository.get(context=context, kind=EntityKind.EXTERNAL_AGENT_CONNECTION,
                                  entity_id=identity) is None


def _process(dsn, context, identity, operation, entered, release, results):
    """Independent process, client and transaction; no parent repository handle."""
    repository = PostgresAgentWorldRepository(PostgresClient(dsn), environment=context.scope.environment)
    port = NativeExternalRepository(repository)
    try:
        with port.guard(context, identity, timeout=10):
            row = port.get_external_connection(context=context, connection_id=identity)
            entered.set()
            if operation == "revoke":
                port.commit_external_connection(context=context,
                    connection=row.transition("revoked", now=datetime.now(timezone.utc)),
                    expected_revision=row.header.revision, idempotency_key="pg-process-revoke")
            else:
                results.put("dispatch_admitted" if row.status == "active" else "dispatch_denied")
            if release is not None and not release.wait(10):
                raise RuntimeError("parent_release_timeout")
        results.put("released:" + operation)
    except Exception as error:
        results.put("error:" + type(error).__name__ + ":" + str(error))
        raise


@pytest.mark.parametrize("first", ["dispatch", "revoke"])
def test_pg_actual_process_dispatch_revoke_ordering(external, first):
    detail = connected(external, "race-" + first)
    mp = multiprocessing.get_context("spawn")
    entered, second_entered, release, results = mp.Event(), mp.Event(), mp.Event(), mp.Queue()
    args = (os.environ["STRATFORGE_TEST_AGENT_WORLD_POSTGRES_URL"], external.context, detail["id"])
    second = "revoke" if first == "dispatch" else "dispatch"
    holder = mp.Process(target=_process, args=(*args, first, entered, release, results))
    waiter = mp.Process(target=_process, args=(*args, second, second_entered, None, results))
    holder.start()
    try:
        assert entered.wait(15), "first process failed to take real PostgreSQL guard"
        waiter.start()
        assert not second_entered.wait(1), "second process entered while first owns transaction guard"
        release.set()
        holder.join(15)
        waiter.join(15)
        assert holder.exitcode == waiter.exitcode == 0
        outputs = [results.get(timeout=5) for _ in range(3)]
        assert ("dispatch_admitted" if first == "dispatch" else "dispatch_denied") in outputs
        assert "released:revoke" in outputs and "released:dispatch" in outputs
        row = NativeExternalRepository(gateway.repository(external.authorized)).get_external_connection(
            context=external.context, connection_id=detail["id"])
        assert row.status == "revoked"
        with pytest.raises(ContractError, match="external_agent_revoked"):
            act(external, detail["id"], "task", {"input_text": "[1,2]"}, key="pg-denied-" + first)
    finally:
        release.set()
        for process in (holder, waiter):
            if process.pid and process.is_alive():
                process.terminate()
                process.join(5)


def test_pg_guard_releases_after_holder_process_dies(external):
    detail = connected(external, "crashed-holder")
    mp = multiprocessing.get_context("spawn")
    entered, release, results = mp.Event(), mp.Event(), mp.Queue()
    holder = mp.Process(target=_process, args=(os.environ["STRATFORGE_TEST_AGENT_WORLD_POSTGRES_URL"],
        external.context, detail["id"], "dispatch", entered, release, results))
    holder.start()
    try:
        assert entered.wait(15)
        holder.terminate()
        holder.join(10)
        port = NativeExternalRepository(gateway.repository(external.authorized))
        with port.guard(external.context, detail["id"], timeout=5):
            assert port.get_external_connection(context=external.context,
                                               connection_id=detail["id"]).status == "active"
    finally:
        if holder.is_alive():
            holder.terminate()
            holder.join(5)


def test_pg_guard_timeout_is_bounded_and_other_workspace_is_not_blocked(external):
    detail = connected(external, "bounded-guard")
    mp = multiprocessing.get_context("spawn")
    entered, release, results = mp.Event(), mp.Event(), mp.Queue()
    holder = mp.Process(target=_process, args=(os.environ["STRATFORGE_TEST_AGENT_WORLD_POSTGRES_URL"],
        external.context, detail["id"], "dispatch", entered, release, results))
    holder.start()
    try:
        assert entered.wait(15)
        port = NativeExternalRepository(gateway.repository(external.authorized))
        with pytest.raises(ContractError, match="external_agent_connection_busy"):
            with port.guard(external.context, detail["id"], timeout=0.1):
                pytest.fail("holder transaction was bypassed")
        foreign = replace(external.context,
            scope=replace(external.context.scope, workspace_id="ws_independent_pg_guard"))
        with port.guard(foreign, detail["id"], timeout=0.2):
            assert port.get_external_connection(context=foreign, connection_id=detail["id"]) is None
        release.set()
        holder.join(10)
        assert holder.exitcode == 0
        with port.guard(external.context, detail["id"], timeout=2):
            assert port.get_external_connection(context=external.context,
                                               connection_id=detail["id"]).status == "active"
    finally:
        release.set()
        if holder.is_alive():
            holder.terminate()
            holder.join(5)


def _native_process(root, chat_roots, scope, identity, operation, entered, release, finished, results):
    """Spawn native gateway/worker with the parent's isolated fixture stores."""
    from pathlib import Path
    from app import secure_store, subscriptions
    from app.ai_control_center import external_agent_development as development
    # Spawn does not inherit monkeypatches. Share the exact disposable paths
    # whose original user message the parent persisted before enqueueing.
    chief_agent.paths.REGISTRY_DIR = Path(chat_roots["registry"])
    chief_agent.paths.PROJECT_ROOT = Path(chat_roots["project"])
    for module in (account_auth, subscriptions, workspaces):
        module._root = lambda: Path(root)
    secure_store.available = lambda: True
    secure_store.backend_name = lambda: "test DPAPI"
    secure_store._protect = lambda value: value[::-1]
    secure_store._unprotect = lambda value: value[::-1]
    account_auth._clear_doc_cache()
    authorized = gateway.access(scope)
    env = SimpleNamespace(authorized=authorized)
    try:
        if operation == "worker":
            original = development.client
            def client(auth):
                result = original(auth)
                transport = result.transport
                def paused(endpoint, **kwargs):
                    if kwargs["packet"]["method"] == "message/send":
                        entered.set()
                        if not release.wait(15):
                            raise RuntimeError("native_dispatch_release_timeout")
                    return transport(endpoint, **kwargs)
                result.transport = paused
                return result
            development.client = client
            jobs = drain()
            assert jobs and jobs[0][1]["ok"], jobs
            results.put("native_worker_completed")
        else:
            entered.set()
            detail = gateway.list_domain(authorized, "external_agents", identity=identity)
            assert act(env, identity, "revoke", revision=detail["revision"],
                       key="native-pg-race-revoke")["status"] == "revoked"
            results.put("native_revoke_completed")
        finished.set()
    except Exception as error:
        results.put("error:" + type(error).__name__ + ":" + str(error))
        raise


def test_pg_native_worker_transmission_and_revoke_in_separate_processes(external):
    detail = connected(external, "native-process-race")
    started = act(external, detail["id"], "task", {"input_text": "[1,3,5]"}, key="native-pg-process-task")
    mp = multiprocessing.get_context("spawn")
    transmitting, revoke_started, release = mp.Event(), mp.Event(), mp.Event()
    worker_done, revoke_done, results = mp.Event(), mp.Event(), mp.Queue()
    chat_roots = {"registry": str(chief_agent.paths.REGISTRY_DIR), "project": str(chief_agent.paths.PROJECT_ROOT)}
    args = (str(account_auth._root()), chat_roots, external.authorized["chat_scope"], detail["id"])
    worker = mp.Process(target=_native_process,
        args=(*args, "worker", transmitting, release, worker_done, results))
    revoke = mp.Process(target=_native_process,
        args=(*args, "revoke", revoke_started, release, revoke_done, results))
    worker.start()
    try:
        assert transmitting.wait(20), "native worker did not reach authenticated transport"
        revoke.start()
        assert revoke_started.wait(10)
        assert not revoke_done.wait(1), "revoke escaped active dispatch transaction guard"
        release.set()
        worker.join(20)
        revoke.join(20)
        assert worker.exitcode == revoke.exitcode == 0
        assert {results.get(timeout=5), results.get(timeout=5)} == {
            "native_worker_completed", "native_revoke_completed"}
        after = gateway.list_domain(external.authorized, "external_agents", identity=detail["id"])
        assert after["status"] == "revoked" and after["statistics"]["tasks_completed"] == 1
        task = gateway.external_agents(external.authorized).task_detail(started["started_task_id"])
        messages = chief_agent.read_jsonl(chief_agent._conversation_file(task["conversation_id"], scope=external.authorized["chat_scope"]))
        assert any(row.get("role") == "user" and row.get("message_id") == task["message_id"] for row in messages)
        delivered = [row for row in messages if row.get("source") == "agent_world_local"]
        assert len(delivered) == 1
        assert delivered[0]["actions"][0]["task_id"] == started["started_task_id"]
        assert delivered[0]["actions"][0]["status"] == "awaiting_review"
        with pytest.raises(ContractError, match="external_agent_revoked"):
            act(external, detail["id"], "task", {"input_text": "[9]"}, key="native-pg-next-denied")
    finally:
        release.set()
        for process in (worker, revoke):
            if process.pid and process.is_alive():
                process.terminate()
                process.join(5)
