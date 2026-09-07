"""Execution V2 with real disposable SQLite/queue/worker, synthetic identities.

Only the external provider transport and existing session/account admission
sources are test boundaries. No live keys, sockets, owner data or trading.
"""
from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app import durable, jobqueue, local_worker, market_data, worker_router
from app.ai_lab import chief_agent
from app.ai_control_center import contracts as c, domain_gateway as gateway, execution_v2 as v2
from app.ai_control_center.flags import Flag, FlagRule
from app.ai_control_center.model_service import ModelService
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_domain_gateway import ordinary
from tests.test_agent_world_live_gateway import isolated_runtime, owner
from tests.test_agent_world_models import Secrets, response
from tests.test_agent_world_live_backtests import service as canonical_queue, _terminal


@pytest.fixture
def execution(ordinary, tmp_path, monkeypatch, request):
    if getattr(request, "param", "ordinary") == "owner":
        ordinary.scope.update(is_owner=True, uses_owner_runtime=True)
        ordinary.state["user"]["is_owner"] = True
        ordinary.state["workspaces"][ordinary.scope["workspace_id"]]["uses_owner_runtime"] = True
    monkeypatch.setenv("NT_ANALYZER_ROOT", str(tmp_path))
    monkeypatch.setattr(local_worker, "_MODEL_RECOVERY_STATE", {"root": "", "at": 0.0, "after_id": ""})
    monkeypatch.setattr(chief_agent.paths, "REGISTRY_DIR", tmp_path / "chat-registry")
    monkeypatch.setattr(chief_agent.paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chief_agent, "_explicit_production", lambda: False)
    chart_runtime = tmp_path / "chart-runtime"
    chart_runtime.mkdir()
    monkeypatch.setattr(market_data, "_runtime_dir", lambda: chart_runtime)
    monkeypatch.setattr(market_data, "render_chart_snapshot", lambda *a, **kw: pytest.fail("headless chart forbidden"))
    original_flags = gateway.live_gateway.flag_snapshot
    state = {"enabled": True, "before_send": None, "after_send": None, "complete_error": False}
    def flags(context):
        original = original_flags(context)
        rules = tuple(rule for rule in original.rules if rule.flag != Flag.AI_EXECUTION_V2)
        rules += tuple(FlagRule(environment=context.scope.environment, workspace_id=workspace,
                               flag=Flag.AI_EXECUTION_V2, enabled=state["enabled"])
                       for workspace in (None, context.scope.workspace_id))
        return replace(original, rules=rules)
    monkeypatch.setattr(gateway.live_gateway, "flag_snapshot", flags)
    path, calls, secrets = tmp_path / "execution.sqlite", [], Secrets()
    output = [response()]
    def repository(auth):
        auth["admit"]()
        return SQLiteAgentWorldRepository(path, read_only=auth.get("read_only", False))
    def provider(**kwargs):
        if callable(state["before_send"]):
            state["before_send"]()
        # Real ModelExecutor repeats this immediately before its transport.
        kwargs["admit"](kwargs["context"], "provider_transmit", .0002)
        calls.append(kwargs)
        if callable(state["after_send"]):
            state["after_send"]()
        return copy.deepcopy(output[0])
    def models(auth, repo=None):
        def admit(context, operation, estimate):
            gateway._model_admit(auth, context, operation, estimate)
            if operation == "complete" and state["complete_error"]:
                state["complete_error"] = False
                raise ContractError("model_access_denied")
        result = ModelService(repo or repository(auth), secrets=secrets, executor=provider,
            admit=admit, chat_scope=auth["chat_scope"])
        def enqueue(**kw):
            v2.prepare(auth, result, kw["task_id"])
            return gateway.enqueue_model(auth, **kw)
        result.enqueue = enqueue
        return result
    monkeypatch.setattr(gateway, "repository", repository)
    monkeypatch.setattr(gateway, "models", models)
    auth = gateway.access(ordinary.scope)
    service, context = models(auth), auth["context"]
    policy = service._put(context, {"version": "synthetic-execution-v2-test"})
    persona = service._ensure(context, c.Persona, uuid4(), uuid4(), policy,
        display_name="Synthetic Execution User", profile=service._put(context, {"description": "disposable fixture"}))
    service._walk(context, persona, "active")
    model = service.connect(context=context, payload={"label": "Synthetic connection", "provider": "deepseek",
        "model": "deepseek-v4-flash", "api_key": "IN_MEMORY_TEST_SECRET_ONLY",
        "persona_id": str(persona.header.entity_id)}, idempotency_key="execution-connect")
    fixture = SimpleNamespace(account=ordinary, auth=auth, context=context, service=service,
        model=model, state=state, output=output, calls=calls, root=tmp_path, task_id=None)
    def start(*, key="execution-test-task", sealed=None, managed=True, queue=True):
        service.enqueue = None
        detail = service.start_task(context=context, model_id=model["id"],
            payload={"rubric_key": "json_arithmetic", "input_text": "[8,13,-4,17]"},
            idempotency_key=key, _sealed_spec=sealed)
        fixture.task_id = detail["id"]
        if managed:
            v2.prepare(auth, service, detail["id"])
        if queue:
            gateway.enqueue_model(gateway.access(auth["chat_scope"]), context=context, task_id=detail["id"])
        return detail
    fixture.start = start
    start()
    return fixture


def claim(execution, worker="synthetic-worker"):
    return durable.claim_worker_job(execution.root, worker_id=worker)


def run_claim(execution, job):
    return v2.execute(execution.auth, execution.service, job, lambda: False,
        lambda: durable.heartbeat_worker_job(execution.root, job["worker_job_id"], worker_id=job["worker_id"]))


def project(execution):
    return v2.projection(execution.service, execution.context, execution.task_id)


def test_real_sqlite_worker_claim_completes_scoped_controller_and_separate_review(execution):
    before = project(execution)
    assert before["status"] == "requested" and before["phase"] == "approved"
    assert before["human_accepted"] is False
    task = execution.service._get(execution.context, EntityKind.TASK, execution.task_id)
    source_execution = execution.service._execution(execution.context, execution.task_id)
    assert str(source_execution.header.entity_id) != before["id"]
    result = run_claim(execution, claim(execution))
    after = project(execution)
    assert result["ledger_status"] == "succeeded"
    assert after["status"] == "succeeded" and after["phase"] == "verified_result"
    assert after["approved_scope_sha256"] == before["approved_scope_sha256"]
    assert len(execution.calls) == 1 and after["human_accepted"] is False
    assert execution.service.repository.get_revision(context=execution.context, kind=EntityKind.TASK,
        entity_id=task.header.entity_id, revision=task.header.revision) == task
    assert len(durable.list_worker_jobs(execution.root)) == 1
    assert not after["court_execution"] and after["routing_effect"] == "none"


def test_existing_local_worker_dispatches_managed_task_without_new_queue(execution):
    result = local_worker.run_once(worker_id="v2-existing-worker")
    assert result["status"] == "succeeded", result
    assert result["kind"] == "agent_world_model"
    assert result["worker_job_id"] == "wj_aw_model_" + UUID(execution.task_id).hex
    assert result["max_attempts"] == 3
    assert project(execution)["status"] == "succeeded"
    assert len(execution.calls) == 1


def test_actual_worker_retries_only_persisted_receipt_closeout(execution):
    execution.state["complete_error"] = True
    first = local_worker.run_once(worker_id="receipt-crash-worker")
    assert first["status"] == "queued" and first["attempts"] == 1
    assert len(execution.calls) == 1
    second = local_worker.run_once(worker_id="receipt-recovery-worker")
    assert second["status"] == "succeeded" and second["attempts"] == 2
    assert first["worker_job_id"] == second["worker_job_id"]
    assert project(execution)["status"] == "succeeded" and len(execution.calls) == 1


def test_actual_worker_recovers_pre_transmit_checkpoint_failure(execution, monkeypatch):
    original_save, interrupted = v2._save, []
    def crash_after_queue_checkpoint(*args, **kwargs):
        record = original_save(*args, **kwargs)
        if kwargs.get("status") == "queued" and not interrupted:
            interrupted.append(True)
            raise OSError("synthetic checkpoint interruption")
        return record
    monkeypatch.setattr(v2, "_save", crash_after_queue_checkpoint)
    first = local_worker.run_once(worker_id="pre-transmit-crash")
    assert first["status"] == "queued" and not execution.calls
    second = local_worker.run_once(worker_id="pre-transmit-recovery")
    assert second["status"] == "succeeded" and second["attempts"] == 2
    assert len(execution.calls) == 1 and project(execution)["status"] == "succeeded"


def test_duplicate_concurrent_delivery_of_same_claim_never_calls_twice(execution):
    job = claim(execution)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run_claim(execution, job), range(2)))
    assert all(result["ledger_status"] == "succeeded" for result in results)
    assert len(execution.calls) == 1


def test_prepare_never_takes_worker_lock_under_model_mutation_lock(execution, monkeypatch):
    from app.ai_control_center.model_service import _LOCK
    monkeypatch.setattr(v2, "_lock", lambda *_: pytest.fail("prepare/model-mutation lock inversion"))
    with _LOCK:
        v2.prepare(execution.auth, execution.service, execution.task_id)


def test_prepare_replay_keeps_immutable_approval_and_no_extra_records(execution):
    before = project(execution)
    after = v2.prepare(execution.auth, execution.service, execution.task_id)
    assert before == after
    assert not execution.calls and len(durable.list_worker_jobs(execution.root)) == 1


def test_flag_off_never_falls_back_to_legacy(execution):
    execution.state["enabled"] = False
    job = claim(execution)
    assert v2.is_managed(execution.service, execution.context, execution.task_id)
    with pytest.raises(ContractError, match="gate_disabled"):
        run_claim(execution, job)
    assert not execution.calls
    assert "execution_gate_disabled" in project(execution)["reason_codes"]
    assert project(execution)["automatic_retry_allowed"] is False


def test_missing_or_explicitly_disabled_flag_never_creates_v2_authority(execution):
    assert not v2.enabled({"context": execution.context})
    execution.state["enabled"] = False
    auth = gateway.access(execution.auth["chat_scope"])
    assert not v2.enabled(auth)
    with pytest.raises(ContractError, match="gate_disabled"):
        v2.prepare(auth, execution.service, execution.task_id)


def test_existing_legacy_job_cannot_be_relabelled_v2(execution):
    execution.state["enabled"] = False
    execution.start(key="legacy-source-must-stay-legacy", managed=False)
    assert not v2.is_managed(execution.service, execution.context, execution.task_id)
    execution.state["enabled"] = True
    with pytest.raises(ContractError, match="legacy_adoption_denied"):
        v2.prepare(execution.auth, execution.service, execution.task_id)
    assert not v2.is_managed(execution.service, execution.context, execution.task_id)


def test_high_risk_and_court_are_not_execution_authorization(execution, monkeypatch):
    execution.start(key="court-not-an-executor", managed=False, queue=False,
                    sealed={"rubric_key": "court_vote", "input": {}})
    with pytest.raises(ContractError, match="new_approved_task_required"):
        v2.prepare(execution.auth, execution.service, execution.task_id)
    original_ensure = execution.service._ensure
    def high_risk(*args, **kwargs):
        if args[1] is c.Intent:
            kwargs["risk"] = c.Risk.HIGH
        return original_ensure(*args, **kwargs)
    monkeypatch.setattr(execution.service, "_ensure", high_risk)
    execution.start(key="high-risk-needs-review", managed=False, queue=False)
    with pytest.raises(ContractError, match="high_risk_not_supported"):
        v2.prepare(execution.auth, execution.service, execution.task_id)
    assert not execution.calls


@pytest.mark.parametrize("change", ["deadline", "role", "connection"])
def test_fresh_approved_policy_deadline_and_binding_fail_closed(execution, monkeypatch, change):
    if change == "deadline":
        original_now = v2._now
        monkeypatch.setattr(v2, "_now", lambda: original_now() + timedelta(hours=2))
    elif change == "role":
        task = execution.service._get(execution.context, EntityKind.TASK, execution.task_id)
        role = execution.service._get(execution.context, EntityKind.AGENT_ROLE, task.role.entity_id)
        execution.service._change(execution.context, role, "suspended")
    else:
        model = execution.service._get(execution.context, EntityKind.MODEL, execution.model["id"])
        profile = execution.service._json(execution.context, model.profile)
        profile["model"] = "changed-connection"
        execution.service._change(execution.context, model, profile=execution.service._put(execution.context, profile))
    with pytest.raises(ContractError):
        run_claim(execution, claim(execution))
    assert not execution.calls


@pytest.mark.parametrize("revocation", ["session", "capability", "budget", "workspace", "identity"])
def test_fresh_authority_revocation_denies_claimed_step(execution, revocation):
    job = claim(execution)
    account = execution.account.state
    if revocation == "session":
        account["session_active"] = False
    elif revocation == "capability":
        account["permissions"]["capabilities"]["ai_pro_models"] = False
    elif revocation == "budget":
        account["budget_ok"] = False
    elif revocation == "workspace":
        account["workspaces"].clear()
    else:
        account["user"]["user_uuid"] = str(uuid4())
    with pytest.raises(Exception):
        run_claim(execution, job)
    assert not execution.calls


@pytest.mark.parametrize("revocation", ["session", "flag", "budget"])
def test_authority_rechecked_at_actual_transport_boundary(execution, revocation):
    def revoke():
        if revocation == "session":
            execution.account.state["session_active"] = False
        elif revocation == "flag":
            execution.state["enabled"] = False
        else:
            execution.account.state["budget_ok"] = False
    execution.state["before_send"] = revoke
    try:
        run_claim(execution, claim(execution))
    except Exception:
        pass
    assert not execution.calls
    assert project(execution)["provider_started"] is True  # conservative fence, not proof of a transmitted request


@pytest.mark.parametrize("field", ["worker_id", "attempts", "user_id", "workspace", "session", "status"])
def test_forged_or_stale_claim_denied_before_provider(execution, field):
    job = copy.deepcopy(claim(execution))
    if field in {"worker_id", "attempts", "user_id", "status"}:
        job[field] = "forged"
    elif field == "workspace":
        job["payload"]["scope"]["workspace_id"] = "ws_foreign"
    else:
        job["payload"]["scope"]["auth_session_id"] = "another-session"
    with pytest.raises(ContractError, match="claim_lost"):
        run_claim(execution, job)
    assert not execution.calls


def test_expired_lease_cannot_transmit_even_before_queue_sweeper(execution, monkeypatch):
    job = claim(execution)
    monkeypatch.setattr(v2.time, "time", lambda: job["locked_until"] + 1)
    with pytest.raises(ContractError, match="claim_lost"):
        run_claim(execution, job)
    assert not execution.calls


def test_request_scope_change_stops_and_records_only_hashes(execution):
    task = execution.service._get(execution.context, EntityKind.TASK, execution.task_id)
    checkpoint = execution.service._json(execution.context, task.checkpoint)
    checkpoint["spec"]["input"][0] = 999
    execution.service._change(execution.context, task, checkpoint=execution.service._put(execution.context, checkpoint))
    with pytest.raises(ContractError, match="approved_scope_changed"):
        run_claim(execution, claim(execution))
    assert not execution.calls
    controller, _, state = v2._load(execution.service, execution.context, execution.task_id)
    evidence = execution.service._json(execution.context, state["deviations"][0])
    assert evidence["reason_code"] == "approved_scope_changed"
    assert evidence["approved_scope"]["sha256"] == controller.approval.sha256
    assert "response" not in evidence and "api_key" not in evidence


def test_crash_before_transport_uses_existing_task_transitions_and_one_call(execution):
    task = execution.service._get(execution.context, EntityKind.TASK, execution.task_id)
    execution.service._change(execution.context, task, "running")
    result = run_claim(execution, claim(execution))
    assert result["ledger_status"] == "succeeded" and len(execution.calls) == 1
    assert project(execution)["status"] == "succeeded"


def test_uncertain_external_reply_never_redispatches(execution):
    def uncertain():
        raise OSError("Untrusted provider body IN_MEMORY_TEST_SECRET_ONLY must not persist")
    execution.state["after_send"] = uncertain
    job = claim(execution)
    run_claim(execution, job)
    after = project(execution)
    assert after["status"] == "review" and after["phase"] == "uncertain"
    assert after["automatic_retry_allowed"] is False
    execution.state["after_send"] = None
    run_claim(execution, job)
    assert len(execution.calls) == 1
    with execution.service.repository._transaction() as db:
        persisted = b" ".join(bytes(row[0]) for row in db.execute("SELECT content FROM aw_artifacts"))
    assert b"IN_MEMORY_TEST_SECRET_ONLY" not in persisted and b"Untrusted provider body" not in persisted


def test_persisted_response_recovers_without_second_transmit(execution):
    execution.state["complete_error"] = True
    job = claim(execution)
    with pytest.raises(ContractError, match="model_access_denied"):
        run_claim(execution, job)
    assert len(execution.calls) == 1
    run_claim(execution, job)
    assert project(execution)["status"] == "succeeded" and len(execution.calls) == 1


@pytest.mark.parametrize("session_revoked", [False, True])
def test_receipt_only_closeout_after_paid_access_ends_still_requires_actual_session(execution, monkeypatch, session_revoked):
    original_save, interrupted = v2._save, []
    def crash_before_audit_closeout(*args, **kwargs):
        if kwargs.get("status") == "succeeded" and not interrupted:
            interrupted.append(True)
            raise OSError("synthetic audit write interruption")
        return original_save(*args, **kwargs)
    monkeypatch.setattr(v2, "_save", crash_before_audit_closeout)
    with pytest.raises(OSError):
        run_claim(execution, claim(execution))
    assert len(execution.calls) == 1
    execution.account.state["budget_ok"] = False
    execution.account.state["permissions"].update(role="read_only", capabilities={"ai_lab": False, "ai_pro_models": False})
    if session_revoked:
        execution.account.state["session_active"] = False
    budget_calls = len(execution.account.calls["budget"])
    if session_revoked:
        with pytest.raises(ContractError, match="session_expired"):
            v2.observe(execution.auth, execution.service, execution.task_id)
        assert project(execution)["status"] == "review"
    else:
        v2.observe(execution.auth, execution.service, execution.task_id)
        assert project(execution)["status"] == "succeeded"
    assert len(execution.account.calls["budget"]) == budget_calls
    assert len(execution.calls) == 1


@pytest.mark.parametrize("bad", ["output_limit", "result_rejected"])
def test_observed_result_deviation_stops_controller_without_human_acceptance(execution, bad):
    if bad == "output_limit":
        execution.output[0]["output_tokens"] = 513
    else:
        execution.output[0]["response"] = '{"incorrect":true}'
    run_claim(execution, claim(execution))
    after = project(execution)
    assert after["status"] == "deviated" and after["human_accepted"] is False
    assert after["reason_codes"] == ["provider_output_limit_exceeded" if bad == "output_limit" else "provider_result_rejected"]


def test_cancel_does_not_claim_rollback_and_does_not_transmit(execution):
    execution.service.cancel(context=execution.context, task_id=execution.task_id)
    v2.observe(execution.auth, execution.service, execution.task_id)
    assert project(execution)["status"] == "cancelled"
    assert not execution.calls


def test_read_projection_is_mutation_free_and_cross_scope_hidden(execution):
    before = project(execution)
    for _ in range(3):
        assert project(execution) == before
    foreign_user = uuid4()
    other = c.RequestContext(scope=execution.context.scope, user_uuid=foreign_user,
        actor=c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=foreign_user))
    assert not v2.is_managed(execution.service, other, execution.task_id)
    with pytest.raises(ContractError, match="controller_required"):
        v2.projection(execution.service, other, execution.task_id)


def _chart_plan(execution, kind="chart"):
    from app.ai_control_center import application_chat
    # End the unrelated initial arithmetic source through its real worker.
    job = claim(execution)
    run_claim(execution, job)
    durable.finish_worker_job(execution.root, job["worker_job_id"], {"ok": True}, worker_id=job["worker_id"])
    service, context = execution.service, execution.context
    persona = service._get(context, EntityKind.PERSONA, execution.model["persona_id"])
    profile = {**service._json(context, persona.profile), "application_role": kind + "_researcher"}
    service._change(context, persona, display_name="Иван" if kind == "chart" else "Толик", profile=service._put(context, profile))
    message = ("Иван, сделай снимок рабочего стола MNQ 09-26, 5m" if kind == "chart" else
        "Толик, запусти бэктест AWRegisteredStrategy на MNQ 09-26, 5m, с 2026-08-24 по 2026-08-29, Period=5")
    response = application_chat.try_chat(message,
        scope=execution.auth["chat_scope"], conversation_id="v2-synthetic-chart",
        request_id="v2-chart-request", source="app")
    execution.task_id = response["actions"][0]["task_id"]
    task = service._get(context, EntityKind.TASK, execution.task_id)
    checkpoint = service._json(context, task.checkpoint)
    execution.output[0]["response"] = json.dumps(checkpoint["spec"]["input"])
    return claim(execution, worker="v2-chart-worker")


@pytest.mark.parametrize("execution", ["owner"], indirect=True)
def test_model_to_existing_chart_command_to_actual_fixture_receipt(execution):
    from app.ai_control_center import application_chat, live_charts
    from tests.test_agent_world_live_charts import _body, _png
    job = _chart_plan(execution)
    result = run_claim(execution, job)
    assert result["model_plan_verified"] and result["ledger_status"] == "waiting"
    commands = live_charts.commands(execution.auth)
    assert len(commands) == 1
    assert project(execution)["phase"] == "waiting_result"
    assert project(execution)["status"] == "running"
    capture = {**_body({"command_id": commands[0]["id"]}), "conversation_id": "v2-synthetic-chart"}
    live_charts.complete(capture, execution.auth)
    reconciled = application_chat.reconcile(execution.auth, execution.service)
    assert reconciled["completed"] == [execution.task_id], reconciled
    v2.observe(execution.auth, execution.service, execution.task_id)
    after = project(execution)
    assert after["status"] == "succeeded" and after["human_accepted"] is False
    detail = execution.service.task_detail(context=execution.context, task_id=execution.task_id)
    assert detail["display_status"] == "awaiting_review"
    image = next(row for row in detail["artifacts"] if row["mime_type"] == "image/png")
    found = execution.service.repository.get_artifact_by_id(context=execution.context, artifact_id=UUID(image["id"]))
    assert found[1] == _png()
    assert len(execution.calls) == 2  # arithmetic + one chart plan, never a generated image


@pytest.mark.parametrize("execution", ["owner"], indirect=True)
def test_application_reconcile_cannot_bypass_kill_switch(execution, monkeypatch):
    from app.ai_control_center import application_chat, live_charts
    job = _chart_plan(execution)
    original_dispatch = application_chat.finish_dispatch
    monkeypatch.setattr(application_chat, "finish_dispatch", lambda *args: {"dispatched": False})
    run_claim(execution, job)
    monkeypatch.setattr(application_chat, "finish_dispatch", original_dispatch)
    assert not live_charts.commands(execution.auth)
    execution.state["enabled"] = False
    result = execution.service.task_detail(context=execution.context, task_id=execution.task_id)
    with pytest.raises(ContractError, match="gate_disabled"):
        application_chat.finish_dispatch(execution.auth, execution.service, result)
    assert not live_charts.commands(execution.auth)
    assert "execution_gate_disabled" in project(execution)["reason_codes"]


@pytest.mark.parametrize("execution", ["owner"], indirect=True)
def test_flag_revoked_between_application_entry_and_source_enqueue_is_denied(execution, monkeypatch):
    from app.ai_control_center import live_charts
    job = _chart_plan(execution)
    original_start = live_charts.start
    def revoke_then_start(**kwargs):
        execution.state["enabled"] = False
        return original_start(**kwargs)
    monkeypatch.setattr(live_charts, "start", revoke_then_start)
    run_claim(execution, job)
    assert not live_charts.commands(execution.auth)
    assert "execution_gate_disabled" in project(execution)["reason_codes"]
    assert project(execution)["status"] == "deviated"


@pytest.mark.parametrize("execution", ["owner"], indirect=True)
def test_existing_chart_cancel_is_not_faked_as_successful_execution(execution):
    from app.ai_control_center import application_chat, live_charts
    job = _chart_plan(execution)
    run_claim(execution, job)
    assert len(live_charts.commands(execution.auth)) == 1
    result = application_chat.cancel_dispatch(execution.auth, execution.service, task_id=execution.task_id)
    assert result["ledger_status"] == "cancelled"
    v2.observe(execution.auth, execution.service, execution.task_id)
    assert project(execution)["status"] == "cancelled"
    assert project(execution)["human_accepted"] is False


@pytest.mark.parametrize("execution", ["owner"], indirect=True)
@pytest.mark.parametrize("source_status", ["done", "failed", "cancelled"])
def test_existing_backtest_queue_report_verifier_controls_v2_result(execution, canonical_queue, monkeypatch, source_status):
    from app.ai_control_center import application_chat
    monkeypatch.setattr(jobqueue, "read_templates_catalog", lambda: {
        "trading_hours_templates": [{"name": "CME US Index Futures RTH", "supported": True}],
        "commission_templates": [{"name": "NinjaTrader Brokerage Free", "supported": True}, {"name": "None", "supported": True}],
    })
    job = _chart_plan(execution, kind="backtest")
    run_claim(execution, job)
    task = execution.service._get(execution.context, EntityKind.TASK, execution.task_id)
    dispatch = execution.service._json(execution.context, task.checkpoint)["application_dispatch"]
    source_id = dispatch["source_id"]
    assert jobqueue.find_job_dir(source_id)[0] == "pending"
    assert project(execution)["status"] == "running"
    # Synthetic source receipt in disposable canonical storage, NOT a live
    # NinjaTrader/backtest acceptance claim. No trading/external process runs.
    folder, _ = _terminal({"job_id": source_id}, status=source_status)
    original_bytes = (folder / "result.json").read_bytes()
    application_chat.reconcile(execution.auth, execution.service)
    after = project(execution)
    assert after["status"] == {"done": "succeeded", "failed": "deviated", "cancelled": "cancelled"}[source_status]
    assert after["human_accepted"] is False
    assert (folder / "result.json").read_bytes() == original_bytes
    assert len(execution.calls) == 2
