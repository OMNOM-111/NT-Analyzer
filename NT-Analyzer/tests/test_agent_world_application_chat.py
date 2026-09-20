"""No live owner/runtime/network: real queue + SF Chat + SQLite in tmp roots."""
from __future__ import annotations

import hashlib
import json
from uuid import UUID

import pytest

from app import durable, jobqueue, local_worker, market_data
from app.ai_lab import chief_agent
from app.ai_control_center import application_chat as app_chat, domain_gateway, live_gateway, live_charts
from app.ai_control_center import model_chat
from app.ai_control_center.states import ContractError, EntityKind

from tests.test_agent_world_models import setup as model_setup, connected, response
from tests.test_agent_world_live_backtests import service as canonical_queue, _terminal
from tests.test_agent_world_live_charts import _body, _png


@pytest.fixture
def queue_service(canonical_queue, monkeypatch):
    monkeypatch.setattr(jobqueue, "read_templates_catalog", lambda: {
        "trading_hours_templates": [{"name": "CME US Index Futures RTH", "supported": True}],
        "commission_templates": [{"name": "NinjaTrader Brokerage Free", "supported": True}, {"name": "None", "supported": True}],
    })
    return canonical_queue


@pytest.fixture
def authorized(model_setup, monkeypatch, tmp_path):
    service, ctx, payload, *_ = model_setup
    scope = {"user_id": 123, "user_uuid": str(ctx.user_uuid), "workspace_id": ctx.scope.workspace_id,
             "is_owner": True, "uses_owner_runtime": True, "membership_role": "owner", "workspace_kind": "owner"}
    auth = {"context": ctx, "chat_scope": scope, "source_scope": {"user_id": 123, "workspace_id": ctx.scope.workspace_id,
            "allow_legacy": False}, "admit": lambda: None}
    def access(value, *, read_only=False):
        if any(value.get(key) != scope[key] for key in ("user_id", "user_uuid", "workspace_id", "is_owner", "uses_owner_runtime")):
            raise ContractError("application_test_scope_denied")
        return {**auth, "read_only": read_only}
    monkeypatch.setattr(domain_gateway, "access", access)
    monkeypatch.setattr(live_gateway, "access", access)
    monkeypatch.setattr(live_gateway, "configured", lambda value="": value == ctx.scope.workspace_id)
    monkeypatch.setattr(domain_gateway, "models", lambda *_: service)
    monkeypatch.setenv("NT_ANALYZER_ROOT", str(tmp_path))
    monkeypatch.setattr(domain_gateway, "repository", lambda auth: service.repository)
    monkeypatch.setattr(domain_gateway, "history_models", lambda auth: service)
    service.enqueue = lambda **kwargs: domain_gateway.enqueue_model(auth, **kwargs)
    registry = tmp_path / "chat-registry"
    registry.mkdir()
    runtime = tmp_path / "chart-runtime"
    runtime.mkdir()
    monkeypatch.setattr(chief_agent.paths, "REGISTRY_DIR", registry)
    monkeypatch.setattr(chief_agent.paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chief_agent, "_explicit_production", lambda: False)
    monkeypatch.setattr(market_data, "_runtime_dir", lambda: runtime)
    monkeypatch.setattr(market_data, "render_chart_snapshot", lambda *a, **kw: pytest.fail("headless forbidden"))
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("network forbidden"))
    return auth


def _model(model_setup, name="Иван", key="connect-one"):
    service, ctx, payload, *_ = model_setup
    persona = service._get(ctx, EntityKind.PERSONA, payload["persona_id"])
    profile = {**service._json(ctx, persona.profile), "application_role": "chart_researcher" if name == "Иван" else "backtest_researcher"}
    service._change(ctx, persona, display_name=name, profile=service._put(ctx, profile))
    return connected(model_setup, key=key)


def _plan(model_setup, authorized, *, kind="chart", request="owner-app-request"):
    service, ctx, *_ = model_setup
    _model(model_setup, "Иван" if kind == "chart" else "Толик")
    message = ("Иван, сделай снимок рабочего стола MNQ 09-26, 5m" if kind == "chart" else
               "Толик, запусти бэктест AWRegisteredStrategy на MNQ 09-26, 5m, с 2026-08-24 по 2026-08-29, Period=5")
    reply = app_chat.try_chat(message, scope=authorized["chat_scope"], conversation_id="chart-real-1",
                             request_id=request, source="app")
    task_id = reply["actions"][0]["task_id"]
    service.executor = lambda **kw: response(kw["prompt"].split("Specification: ", 1)[1])
    result = service.execute(context=ctx, task_id=task_id)
    # This fixture executes the model synchronously; complete its real queue
    # receipt so only the separately claimed delivery phase can append finals.
    claimed = durable.claim_worker_job(None, worker_id="fixture-source")
    assert claimed["worker_job_id"] == "wj_aw_model_" + UUID(task_id).hex
    durable.finish_worker_job(None, claimed["worker_job_id"], {"task_id": task_id}, worker_id="fixture-source")
    assert result["model_plan_verified"]
    return reply, result


def test_chat_actual_message_identity_precedes_provider_plan(model_setup, authorized):
    service, ctx, *_ = model_setup
    reply, plan = _plan(model_setup, authorized)
    assert reply["ok"] and plan["message_id"].startswith("MSG-")
    assert plan["conversation_id"] == "chart-real-1"
    assert plan["status"] == "waiting" and live_charts.commands(authorized) == []
    rows = chief_agent.agent_world_live_messages(scope=authorized["chat_scope"])
    assert len(rows) == 1 and rows[0]["actions"][0]["status"] == "queued"


def test_chart_full_chain_queue_canvas_receipt_model_result_and_retry(model_setup, authorized):
    service, ctx, *_ = model_setup
    _, plan = _plan(model_setup, authorized)
    dispatch = app_chat.finish_dispatch(authorized, service, plan)
    assert dispatch["dispatched"] and len(live_charts.commands(authorized)) == 1
    assert app_chat.finish_dispatch(authorized, service, plan)["source_id"] == dispatch["source_id"]
    pending = app_chat.reconcile(authorized, service)
    assert not pending["completed"] and not pending["errors"]
    live_charts.complete(_body({"command_id": dispatch["source_id"]}), authorized)
    completed = app_chat.reconcile(authorized, service)
    assert completed["completed"] == [plan["id"]] and not completed["errors"]
    detail = service.task_detail(context=ctx, task_id=plan["id"])
    assert detail["status"] == "succeeded" and detail["stage"] == "application_verified"
    assert detail["command_id"] == dispatch["source_id"]
    image = next(row for row in detail["artifacts"] if row["mime_type"] == "image/png")
    assert image["sha256"] == hashlib.sha256(_png()).hexdigest()
    assert "40 из 200" in detail["result_text"]
    assert detail["source_kind"] == "real_model_response"  # authority is unchanged
    assert detail["outcomes"][0]["id"] == detail["application_result"]["outcome_id"]
    envelope = model_chat.envelope(authorized, detail, request_id="view-chart-result")
    attachment = next(row for row in envelope["attachments"] if row["mime_type"] == "image/png")
    assert attachment["type"] == "image" and attachment["sha256"] == image["sha256"]
    count = len(chief_agent.agent_world_live_messages(scope=authorized["chat_scope"]))
    app_chat.reconcile(authorized, service)
    assert len(chief_agent.agent_world_live_messages(scope=authorized["chat_scope"])) == count


def test_backtest_full_chain_uses_original_queue_report_hash_not_generated_result(model_setup, authorized, queue_service):
    service, ctx, *_ = model_setup
    _, plan = _plan(model_setup, authorized, kind="backtest")
    dispatch = app_chat.finish_dispatch(authorized, service, plan)
    assert dispatch["dispatched"], dispatch
    job_id = dispatch["source_id"]
    source = jobqueue.find_job_dir(job_id)[1]
    job = json.loads((source / "job.json").read_text())
    assert job["strategy"]["class_name"] == "AWRegisteredStrategy"
    assert job["origin"]["agent_world"]["conversation_id"] == "chart-real-1"
    assert not app_chat.reconcile(authorized, service)["completed"]
    folder, _ = _terminal({"job_id": job_id})
    original_hash = hashlib.sha256((folder / "result.json").read_bytes()).hexdigest()
    completed = app_chat.reconcile(authorized, service)
    assert completed["completed"] == [plan["id"]]
    detail = service.task_detail(context=ctx, task_id=plan["id"])
    assert detail["source_job_id"] == job_id and detail["report_url"]
    proof = detail["application_result"]["evaluation"]["verification"]
    assert proof["source_sha256"] == original_hash and proof["representation"] == "verified_existing_report_summary"
    assert detail["application_result"]["evaluation"]["self_scored"] is False
    assert "-53.8" in detail["result_text"]  # actual fixture's after-commission value
    assert detail["source_kind"] == "real_model_response"
    assert detail["outcomes"][0]["id"] == detail["application_result"]["outcome_id"]
    assert detail["outcomes"][0]["detail"] == detail["result_text"]
    assert detail["outcomes"][0]["status"] == "verified"
    envelope = model_chat.envelope(authorized, detail, request_id="view-backtest-result")
    assert envelope["attachments"] and all(row["type"] == "artifact" for row in envelope["attachments"])
    assert envelope["source_kind"] == "real_model_response" and envelope["report_url"] == detail["report_url"]
    assert hashlib.sha256((folder / "result.json").read_bytes()).hexdigest() == original_hash


def test_pending_application_never_projects_plan_as_completed_application(model_setup, authorized):
    service, ctx, *_ = model_setup
    _, plan = _plan(model_setup, authorized)
    detail = service.task_detail(context=ctx, task_id=plan["id"])
    assert detail["status"] == "waiting" and not detail["artifacts"]
    assert detail["outcomes"][0]["title"] == "Проверка ответа модели"
    assert detail["outcomes"][0]["id"] == detail["outcome_id"]
    # Provenance identifies the model's plan response, never completed work
    # by NinjaTrader/Desktop. Pending application still has no such receipt.
    assert detail["outcomes"][0]["source_kind"] == "real_model_response"
    assert detail["outcomes"][0]["source_kind"] not in {"ninjatrader_report", "desktop_chart"}
    assert not model_chat.envelope(authorized, detail, request_id="pending-view")["verification"]["passed"]


def test_dispatch_source_then_checkpoint_failure_repairs_without_second_command(model_setup, authorized, monkeypatch):
    service, ctx, *_ = model_setup
    _, plan = _plan(model_setup, authorized)
    original = service._change
    def fail(context, record, status=None, **changes):
        if record.KIND == EntityKind.TASK and "checkpoint" in changes:
            raise OSError("simulated checkpoint interruption")
        return original(context, record, status, **changes)
    monkeypatch.setattr(service, "_change", fail)
    with pytest.raises(OSError):
        app_chat.finish_dispatch(authorized, service, plan)
    assert len(live_charts.commands(authorized)) == 1
    first_id = live_charts.commands(authorized)[0]["id"]
    monkeypatch.setattr(service, "_change", original)
    assert app_chat.finish_dispatch(authorized, service, plan)["source_id"] == first_id
    assert len(live_charts.commands(authorized)) == 1


def test_dispatch_saved_before_publication_failure_repair(model_setup, authorized, monkeypatch):
    service, ctx, *_ = model_setup
    _, plan = _plan(model_setup, authorized)
    original = chief_agent.report_agent_world_live_update
    def fail(*_):
        raise OSError("simulated chat outage")
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", fail)
    with pytest.raises(OSError):
        app_chat.finish_dispatch(authorized, service, plan)
    assert service.task_detail(context=ctx, task_id=plan["id"])["application_dispatch"]
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", original)
    app_chat.finish_dispatch(authorized, service, plan)
    assert len(live_charts.commands(authorized)) == 1


@pytest.mark.parametrize("answer", [
    '{"instrument":"MGC 12-26","timeframe":"5m"}',
    '```json\n{"application":{"request":{"instrument":"MNQ 09-26","timeframe":"5m"},"authorizations":[]}}\n```',
    '{"instrument":"MNQ 09-26","timeframe":"5m","tool":"place_order"}',
])
def test_model_wrong_plan_reports_failure_without_queue_or_fallback(model_setup, authorized, monkeypatch, answer):
    service, ctx, *_ = model_setup
    _model(model_setup)
    reply = app_chat.try_chat("Иван, сделай снимок рабочего стола MNQ 09-26, 5m", scope=authorized["chat_scope"],
                             conversation_id="chart-real-1", request_id="wrong-model-plan", source="app")
    calls = []
    def execute(**kwargs):
        calls.append(kwargs)
        return response(answer)
    service.executor = execute
    assert local_worker.run_once(worker_id="rejected-plan-source")["status"] == "succeeded"
    plan = service.task_detail(context=ctx, task_id=reply["actions"][0]["task_id"])
    assert plan["status"] == "review"
    assert app_chat.finish_dispatch(authorized, service, plan)["dispatched"] is False
    assert not live_charts.commands(authorized)
    monkeypatch.setattr(service, "execute", lambda **_: pytest.fail("delivery retried the rejected model"))
    delivered = local_worker.run_once(worker_id="rejected-plan-delivery")
    assert delivered["status"] == "succeeded" and delivered["result"]["status"] == "delivered"
    rows = chief_agent.agent_world_live_messages(scope=authorized["chat_scope"])
    reports = [row for row in rows if row.get("message_kind") == "report"]
    assert len(reports) == 1 and len(calls) == 1
    assert "Команда приложению не отправлена" in reports[0]["content"]
    assert reports[0]["actions"][0]["verification"]["passed"] is False
    assert service.task_detail(context=ctx, task_id=plan["id"])["status"] == "review"
    assert not live_charts.commands(authorized)


def test_ambiguous_active_models_explicit_error_not_hidden_fallback(model_setup, authorized):
    _model(model_setup)
    connected(model_setup, key="connect-second")
    with pytest.raises(ContractError, match="selection_ambiguous"):
        app_chat.try_chat("Иван, сделай снимок рабочего стола MNQ 09-26, 5m", scope=authorized["chat_scope"],
                         conversation_id="chart-real-1", request_id="ambiguous-plan", source="app")
    assert not live_charts.commands(authorized)


def test_source_failure_never_becomes_model_done(model_setup, authorized, queue_service):
    service, ctx, *_ = model_setup
    _, plan = _plan(model_setup, authorized, kind="backtest")
    dispatch = app_chat.finish_dispatch(authorized, service, plan)
    _terminal({"job_id": dispatch["source_id"]}, status="failed")
    result = app_chat.reconcile(authorized, service)
    assert result["errors"][0]["code"] == "application_backtest_unverified"
    detail = service.task_detail(context=ctx, task_id=plan["id"])
    assert detail["status"] == "failed" and not detail.get("application_result")


def test_tampered_desktop_source_denied_before_copy(model_setup, authorized):
    service, ctx, *_ = model_setup
    _, plan = _plan(model_setup, authorized)
    dispatch = app_chat.finish_dispatch(authorized, service, plan)
    done = live_charts.complete(_body({"command_id": dispatch["source_id"]}), authorized)
    market_data.snapshot_path(done["snapshot"]["file"]).write_bytes(b"not-the-captured-image")
    result = app_chat.reconcile(authorized, service)
    assert result["errors"][0]["code"] == "application_chart_unverified" and not result["completed"]
    assert service.task_detail(context=ctx, task_id=plan["id"])["status"] == "failed"


def test_authoritative_scope_rechecked_before_dispatch(model_setup, authorized):
    service, ctx, *_ = model_setup
    _, plan = _plan(model_setup, authorized)
    wrong = {**authorized, "chat_scope": {**authorized["chat_scope"], "user_id": 999}}
    with pytest.raises(ContractError, match="scope_denied"):
        app_chat.finish_dispatch(wrong, service, plan)
    assert not live_charts.commands(authorized)


def test_explicit_requests_only_and_no_model_is_honest_noop(model_setup, authorized):
    for message, source in (("Привет, Иван", "app"), ("Иван, сделай снимок рабочего стола MNQ 09-26, 5m", "telegram"),
                            ("Иван, сделай снимок рабочего стола MNQ 09-26, 5m", "app")):
        assert app_chat.try_chat(message, scope=authorized["chat_scope"], conversation_id="chart-real-1", request_id="noop-message", source=source) is None
    assert not live_charts.commands(authorized)


def test_model_cancel_before_application_dispatch_prevents_real_command(model_setup, authorized):
    service, ctx, *_ = model_setup
    _, plan = _plan(model_setup, authorized)
    service.cancel(context=ctx, task_id=plan["id"])
    assert app_chat.finish_dispatch(authorized, service, plan)["dispatched"] is False
    assert not live_charts.commands(authorized)


def test_cancel_pending_chart_uses_existing_queue_and_cannot_complete(model_setup, authorized):
    service, ctx, *_ = model_setup
    _, plan = _plan(model_setup, authorized)
    dispatch = app_chat.finish_dispatch(authorized, service, plan)
    result = app_chat.cancel_dispatch(authorized, service, task_id=plan["id"])
    assert result["status"] == "cancelled" and not result.get("application_result")
    task = service._get(ctx, EntityKind.TASK, plan["id"])
    assert service._get(ctx, EntityKind.INTENT, task.intent.entity_id).status == "cancelled"
    assert live_charts.commands(authorized)[0]["status"] == "failed"
    with pytest.raises(ContractError):
        live_charts.complete(_body({"command_id": dispatch["source_id"]}), authorized)
    assert app_chat.cancel_dispatch(authorized, service, task_id=plan["id"])["status"] == "cancelled"


def test_cancel_verified_chart_receipt_is_too_late_and_never_overwrites(model_setup, authorized):
    service, ctx, *_ = model_setup
    _, plan = _plan(model_setup, authorized)
    dispatch = app_chat.finish_dispatch(authorized, service, plan)
    saved = live_charts.complete(_body({"command_id": dispatch["source_id"]}), authorized)
    before = live_charts.commands(authorized)[0]["result"]
    with pytest.raises(ContractError, match="cancel_too_late"):
        app_chat.cancel_dispatch(authorized, service, task_id=plan["id"])
    assert live_charts.commands(authorized)[0]["result"] == before
    assert market_data.snapshot_path(saved["snapshot"]["file"]).read_bytes() == _png()
    assert app_chat.reconcile(authorized, service)["completed"] == [plan["id"]]


def test_cancel_pending_backtest_uses_canonical_cancelled_state(model_setup, authorized, queue_service, monkeypatch):
    from app import connector_backtest
    monkeypatch.setattr(connector_backtest, "routes_through_connector", lambda: False)
    service, ctx, *_ = model_setup
    _, plan = _plan(model_setup, authorized, kind="backtest")
    dispatch = app_chat.finish_dispatch(authorized, service, plan)
    result = app_chat.cancel_dispatch(authorized, service, task_id=plan["id"])
    assert result["status"] == "cancelled" and jobqueue.find_job_dir(dispatch["source_id"])[0] == "cancelled"
    assert not result.get("application_result")


@pytest.mark.parametrize("terminal", ["cancelled", "done"])
def test_cancel_running_nt_remains_pending_until_actual_terminal(model_setup, authorized, queue_service, monkeypatch, terminal):
    from app import connector_backtest
    monkeypatch.setattr(connector_backtest, "routes_through_connector", lambda: False)
    service, ctx, *_ = model_setup
    _, plan = _plan(model_setup, authorized, kind="backtest")
    dispatch = app_chat.finish_dispatch(authorized, service, plan)
    source = jobqueue.find_job_dir(dispatch["source_id"])[1]
    running = jobqueue.jobs_dir() / "running" / source.name
    running.parent.mkdir(parents=True, exist_ok=True)
    source.rename(running)
    jobqueue.reset_caches()
    result = app_chat.cancel_dispatch(authorized, service, task_id=plan["id"])
    assert result["status"] == "waiting" and result["stage"] == "application_cancel_requested"
    assert (running / "cancel.flag").exists()
    assert not app_chat.reconcile(authorized, service)["cancelled"]
    _terminal({"job_id": dispatch["source_id"]}, status=terminal)
    reconciled = app_chat.reconcile(authorized, service)
    detail = service.task_detail(context=ctx, task_id=plan["id"])
    assert detail["status"] == ("cancelled" if terminal == "cancelled" else "succeeded")
    assert reconciled["cancelled" if terminal == "cancelled" else "completed"] == [plan["id"]]


def test_cancel_source_is_scope_checked_before_mutation(model_setup, authorized, queue_service, monkeypatch):
    service, ctx, *_ = model_setup
    _, plan = _plan(model_setup, authorized, kind="backtest")
    app_chat.finish_dispatch(authorized, service, plan)
    other = {**authorized, "chat_scope": {**authorized["chat_scope"], "user_id": 999}}
    monkeypatch.setattr(jobqueue, "cancel_job", lambda *_: pytest.fail("cancel before authorization"))
    with pytest.raises(ContractError, match="scope_denied"):
        app_chat.cancel_dispatch(other, service, task_id=plan["id"])


def test_final_chat_write_failure_repaired_and_inbox_ends_republication(model_setup, authorized, monkeypatch):
    service, ctx, *_ = model_setup
    _, plan = _plan(model_setup, authorized)
    dispatch = app_chat.finish_dispatch(authorized, service, plan)
    live_charts.complete(_body({"command_id": dispatch["source_id"]}), authorized)
    original = chief_agent.report_agent_world_live_update
    def unavailable(value, **kwargs):
        if kwargs.get("history_delivery"):
            raise OSError("temporary chat outage")
        return original(value, **kwargs)
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", unavailable)
    before = len(chief_agent.agent_world_live_messages(scope=authorized["chat_scope"]))
    assert not app_chat.reconcile(authorized, service)["errors"]
    assert service.task_detail(context=ctx, task_id=plan["id"])["status"] == "succeeded"
    assert len(chief_agent.agent_world_live_messages(scope=authorized["chat_scope"])) == before
    assert local_worker.run_once(worker_id="first-delivery")["status"] == "queued"
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", original)
    assert not app_chat.reconcile(authorized, service)["errors"]
    assert local_worker.run_once(worker_id="restarted-delivery")["status"] == "succeeded"
    monkeypatch.setattr(app_chat.model_chat, "publish", lambda *_: pytest.fail("already acknowledged"))
    assert app_chat.reconcile(authorized, service)["examined"] == 0


def test_bounded_reconciliation_cursor_does_not_starve_later_tasks(model_setup, authorized, monkeypatch):
    service, ctx, *_ = model_setup
    monkeypatch.setattr(app_chat, "_READ_LIMIT", 2)
    app_chat._READ_CURSORS.clear()
    plans = [_plan(model_setup, authorized, request="cursor-request-" + str(i))[1] for i in range(3)]
    assert app_chat.reconcile(authorized, service)["examined"] == 2
    assert len(live_charts.commands(authorized)) == 2
    assert app_chat.reconcile(authorized, service)["examined"] == 2
    assert len(live_charts.commands(authorized)) == 3
    assert all(service.task_detail(context=ctx, task_id=plan["id"])["application_dispatch"] for plan in plans)


@pytest.mark.parametrize("timeframe", ["2m", "10m", "60m"])
def test_unsupported_desktop_timeframe_rejected_before_model_task(model_setup, authorized, timeframe):
    service, ctx, *_ = model_setup
    _model(model_setup)
    with pytest.raises(ContractError, match="application_spec_invalid"):
        app_chat.try_chat("Иван, сделай снимок рабочего стола MNQ 09-26, " + timeframe, scope=authorized["chat_scope"],
            conversation_id="chart-real-1", request_id="invalid-timeframe", source="app")
    assert not service.tasks(context=ctx)["items"] and not live_charts.commands(authorized)


def test_named_chart_receipt_survives_more_than_100_newer_commands(model_setup, authorized, monkeypatch):
    service, ctx, *_ = model_setup
    _, plan = _plan(model_setup, authorized)
    dispatch = app_chat.finish_dispatch(authorized, service, plan)
    live_charts.complete(_body({"command_id": dispatch["source_id"]}), authorized)
    original = live_charts.commands(authorized)[0]
    # Only the fixture read projection contains these extra pending commands;
    # the source receipt/PNG and task remain the actual tmp queue outputs.
    additional = [{**original, "id": "cc_" + format(index, "032x"), "status": "pending", "result": {},
                   "created_at_utc": "2099-01-01T00:00:00Z"} for index in range(101)]
    monkeypatch.setattr(live_charts, "commands", lambda *_: [original] + additional)
    listing = live_charts.details(authorized)
    assert len(listing) == 100 and dispatch["source_id"] not in {row["task"]["command_id"] for row in listing}
    named = live_charts.details(authorized, command_id=dispatch["source_id"])
    assert len(named) == 1 and named[0]["task"]["status"] == "succeeded"
    assert app_chat.reconcile(authorized, service)["completed"] == [plan["id"]]
    assert live_charts.details(authorized, command_id="cc_" + "f" * 32) == []
    with pytest.raises(ContractError, match="scope_required"):
        live_charts.details(authorized, command_id="../../another")
