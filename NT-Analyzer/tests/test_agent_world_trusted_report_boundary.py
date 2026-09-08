"""Trusted report boundary; disposable data and loopback HTTP, never NinjaTrader.

The terminal fixtures below are deliberately written by the test process. They
characterize trusted filesystem access, not evidence that NinjaTrader ran.
"""
from __future__ import annotations

import json
import socket
import threading
import urllib.error
from uuid import uuid4

import pytest

from app import connector_backtest, connector_protocol, jobqueue
from app import server as server_mod
from app.ai_control_center import application_chat, live_gateway, live_charts, live_backtests
from app.ai_lab import chief_agent
from app.ai_control_center.flags import FlagSnapshot
from app.ai_control_center.states import ContractError
from tests.test_agent_world_live_backtests import service, _args, _get, _start, _terminal, _write
from tests.test_connector_protocol import connector_store, _enroll, _hello, _http_json
from tests.test_connector_backtest_dispatch import _job_doc


@pytest.fixture
def isolated_connector_http(connector_store, monkeypatch):
    root = connector_store["root"] / "jobs"
    for status in ("pending", "running", "done", "failed", "cancelled", "cancel_requested"):
        (root / status).mkdir(parents=True)
    monkeypatch.setattr(jobqueue, "jobs_dir", lambda: root)
    monkeypatch.setattr(jobqueue, "project_root", lambda: connector_store["root"])
    monkeypatch.setattr(server_mod.observability, "event", lambda *a, **k: None)
    original_connect = socket.create_connection

    def only_loopback(address, *args, **kwargs):
        if address[0] not in {"127.0.0.1", "localhost", "::1"}:
            pytest.fail("external connection forbidden")
        return original_connect(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", only_loopback)
    private, _, _, pending = _enroll(connector_store[42]["workspace_id"])
    welcome = connector_protocol.signed_hello(_hello(private, pending))
    server = server_mod.ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {"root": root, "store": connector_store, "welcome": welcome,
               "base": f"http://127.0.0.1:{server.server_address[1]}"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        jobqueue.reset_caches()


def _snapshot(directory):
    return {str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob("*") if path.is_file()}


@pytest.mark.parametrize("attack", ["foreign_job", "outside_jobs_root"])
def test_enrolled_device_cannot_settle_unbound_job_via_telemetry_key(isolated_connector_http, attack):
    env = isolated_connector_http
    target = (env["root"] / "pending" / "ui_other_user" if attack == "foreign_job"
              else env["store"]["root"] / "boundary-outside")
    target.mkdir(parents=True)
    _write(target / "job.json", {"job_id": target.name,
        "origin": {"user_id": 7, "workspace_id": env["store"][7]["workspace_id"]}})
    _write(target / "dispatch.json", {"command_id": "cmd_other_user", "connection_id": "conn_other_user",
        "transport": "production_connector", "idempotency_key": "backtest:" + target.name})
    (target / "keep.txt").write_text("isolated boundary sentinel", encoding="utf-8")
    before = _snapshot(target)
    # No production path is ever used: the traversal target is a fresh sibling
    # inside this test's own temporary root, prepared above.
    suffix = target.name if attack == "foreign_job" else "../../boundary-outside"
    key = "backtest:" + suffix
    command = connector_protocol.queue_command(42, workspace_id=env["store"][42]["workspace_id"],
        connection_id=env["welcome"]["connection_id"], capability="telemetry", idempotency_key=key,
        payload={"command": "ping"})["command"]
    payload = {"command_id": command["command_id"], "idempotency_key": key, "status": "completed",
        "connector_sequence": 1, "safe_result": {"metrics": {"trade_count": 0}, "trades": []}}
    try:
        status, _, reply = _http_json(env["base"], "/api/connector/v1/commands/result", payload,
                                     token=env["welcome"]["session_token"])
    except urllib.error.HTTPError as exc:
        status, reply = exc.code, json.loads(exc.read())
    assert target.is_dir() and _snapshot(target) == before, "an unrelated server directory was modified"
    assert status in {403, 409} and reply.get("code"), "invalid canonical-job binding must be explicit"


def _withdrawn(service):
    out = _start(service, key="withdrawn-boundary")
    path, report = _terminal(out)
    report["source"] = {"execution_source": "isolated_test_report", "synthetic": True}
    _write(path / "result.json", report)
    jobqueue.reset_caches()
    return out, _get(service, out)


@pytest.mark.parametrize("surface", ["nested_result", "completion_envelope", "overview_outcome"])
def test_refuted_report_origin_propagates_to_every_result_projection(service, monkeypatch, surface):
    out, detail = _withdrawn(service)
    assert detail["verification"]["passed"] is False
    assert detail["verification"]["source_confirmed"] is False
    assert detail["task"]["synthetic"] is True
    if surface == "nested_result":
        projected = detail["result"]
    elif surface == "completion_envelope":
        messages = []
        service.reconcile(**_args(), publish=lambda envelope: messages.append(envelope) or {"ok": True})
        assert len(messages) == 1
        projected = messages[0]
    else:
        monkeypatch.setattr(live_charts, "details", lambda _: [])
        authorized = {**_args(), "snapshot": FlagSnapshot(revision="boundary", audit_ref=uuid4(), rules=())}
        projected = next(row for row in live_gateway.overview(authorized)["outcomes"] if row["task_id"] == out["task_id"])
    assert projected["synthetic"] is True
    assert projected.get("source_confirmed") is False


def test_refuted_source_never_becomes_application_execution_evidence(service):
    out, detail = _withdrawn(service)
    checkpoint = {"conversation_id": detail["task"]["conversation_id"],
        "application_dispatch": {"source_id": out["job_id"], "source_task_id": out["task_id"]}}
    with pytest.raises(ContractError, match="application_backtest_unverified"):
        application_chat._backtest_evidence(_args(), checkpoint)


def test_trusted_unmarked_fixture_acceptance_is_not_an_actual_ninjatrader_run(service):
    out = _start(service, key="trusted-process-fixture")
    _terminal(out)  # direct privileged filesystem writer, not an ordinary API
    detail = _get(service, out)
    assert detail["verification"]["passed"] is True
    assert detail["verification"]["model_quality_assessed"] is False
    rating = service.overview(**_args())["agents"]["items"][0]["evaluation"]
    assert rating["sample_size"] == 0 and rating["score_pct"] is None


def _bound_job(env):
    job_id = "ui_bound_acceptance"
    workspace = env["store"][42]["workspace_id"]
    directory = env["root"] / "pending" / job_id
    directory.mkdir()
    doc = _job_doc(job_id=job_id, origin={"user_id": 42, "workspace_id": workspace})
    _write(directory / "job.json", doc)
    command = connector_protocol.queue_command(42, workspace_id=workspace,
        connection_id=env["welcome"]["connection_id"], capability=connector_backtest.CAPABILITY,
        idempotency_key="backtest:" + job_id, payload=connector_backtest.command_payload(doc))["command"]
    connector_backtest.record_dispatch(directory, command_id=command["command_id"],
        connection_id=command["connection_id"], idempotency_key=command["idempotency_key"],
        queued_at_utc=command["issued_at_utc"], workspace_id=workspace, origin_workspace_id=workspace)
    return job_id, directory, command


def _post_result(env, command, sequence=1, status="completed"):
    return _http_json(env["base"], "/api/connector/v1/commands/result", {
        "command_id": command["command_id"], "idempotency_key": command["idempotency_key"],
        "status": status, "connector_sequence": sequence,
        "safe_result": {"metrics": {"trade_count": 0}, "trades": [],
            "execution_details": {"execution_source": "isolated_test_report", "synthetic": True}}},
        token=env["welcome"]["session_token"])


def test_bound_report_completes_and_replay_keeps_same_files(isolated_connector_http):
    env = isolated_connector_http
    job_id, _, command = _bound_job(env)
    assert _post_result(env, command)[0] == 200
    done = env["root"] / "done" / job_id
    before = _snapshot(done)
    assert json.loads(before["result.json"])["source"]["synthetic"] is True
    status, _, response = _post_result(env, command, sequence=2)
    assert status == 200 and response["idempotent_replay"] is True
    assert _snapshot(done) == before


def test_cancel_receipt_requires_its_own_saved_dispatch_and_preserves_run(isolated_connector_http):
    env = isolated_connector_http
    job_id, directory, _ = _bound_job(env)
    workspace = env["store"][42]["workspace_id"]
    cancel = connector_protocol.queue_command(42, workspace_id=workspace,
        connection_id=env["welcome"]["connection_id"], capability=connector_backtest.CAPABILITY,
        idempotency_key="cancel-backtest:" + job_id,
        payload=connector_backtest.cancel_payload(job_id))["command"]
    before = _snapshot(directory)
    with pytest.raises(urllib.error.HTTPError) as failure:
        _post_result(env, cancel)
    assert failure.value.code == 409 and _snapshot(directory) == before
    connector_backtest.record_dispatch(directory, command_id=cancel["command_id"],
        connection_id=cancel["connection_id"], idempotency_key=cancel["idempotency_key"],
        queued_at_utc=cancel["issued_at_utc"], workspace_id=workspace,
        origin_workspace_id=workspace, cancel=True)
    assert _post_result(env, cancel)[0] == 200
    assert directory.is_dir(), "an acknowledged cancel command is not a completed/cancelled run"
    assert (directory / "cancel_evidence.json").is_file()
    assert not (directory / "result.json").exists()


@pytest.mark.parametrize("change", ["command", "connection", "workspace", "origin_user", "origin_workspace", "payload", "missing_dispatch"])
def test_changed_binding_denies_before_receipt_and_does_not_consume_sequence(isolated_connector_http, change):
    env = isolated_connector_http
    _, directory, command = _bound_job(env)
    dispatch = json.loads((directory / "dispatch.json").read_text(encoding="utf-8"))
    doc = json.loads((directory / "job.json").read_text(encoding="utf-8"))
    if change in {"command", "connection", "workspace"}:
        dispatch[change + "_id"] = "not_the_stored_binding"
        _write(directory / "dispatch.json", dispatch)
    elif change == "missing_dispatch":
        (directory / "dispatch.json").unlink()
    else:
        if change == "origin_user":
            doc["origin"]["user_id"] = 7
        elif change == "origin_workspace":
            doc["origin"]["workspace_id"] = env["store"][7]["workspace_id"]
        else:
            doc["instrument"] = "DIFFERENT"
        _write(directory / "job.json", doc)
    before = _snapshot(directory)
    with pytest.raises(urllib.error.HTTPError) as failure:
        _post_result(env, command)
    assert failure.value.code == 409
    assert json.loads(failure.value.read())["code"] == "backtest_dispatch_mismatch"
    assert _snapshot(directory) == before
    assert not connector_protocol._read_doc()["results"]
    # Restoring the exact server documents permits the same original sequence.
    _write(directory / "job.json", _job_doc(job_id=directory.name,
        origin={"user_id": 42, "workspace_id": env["store"][42]["workspace_id"]}))
    connector_backtest.record_dispatch(directory, command_id=command["command_id"],
        connection_id=command["connection_id"], idempotency_key=command["idempotency_key"],
        queued_at_utc=command["issued_at_utc"])
    assert _post_result(env, command)[0] == 200


@pytest.mark.parametrize("invalid", ["", ".", "..", "../job", "C:/job", "a/b", "a\\b", "job:stream"])
def test_job_name_is_never_a_path(tmp_path, invalid):
    with pytest.raises(connector_backtest.BacktestDispatchError):
        connector_backtest.locate(tmp_path / "jobs", invalid)
    assert not list(tmp_path.iterdir())


def test_transition_never_overwrites_an_existing_history_directory(tmp_path):
    root = tmp_path / "jobs"
    source, destination = root / "pending" / "ui_collision", root / "done" / "ui_collision"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    (source / "keep.txt").write_text("source", encoding="utf-8")
    (destination / "keep.txt").write_text("history", encoding="utf-8")
    before = _snapshot(root)
    with pytest.raises(connector_backtest.ConflictingResultError):
        connector_backtest.move_job(source, root, "done")
    assert _snapshot(root) == before


def test_origin_correction_is_source_bound_and_chat_append_is_idempotent(service, monkeypatch, tmp_path):
    out, detail = _withdrawn(service)
    args = _args()
    monkeypatch.setattr(live_gateway, "access", lambda _: args)
    monkeypatch.setattr(chief_agent.paths, "REGISTRY_DIR", tmp_path / "chat-registry")
    envelope = live_backtests.completion_envelope(detail, args["chat_scope"])
    assert envelope["request_id"].endswith(".origin-v2")
    first = chief_agent.report_agent_world_live_update(envelope)
    second = chief_agent.report_agent_world_live_update(envelope)
    assert second["idempotent_replay"] is True
    assert first["message"]["actions"][0]["synthetic"] is True
    assert first["message"]["actions"][0]["source_confirmed"] is False
    assert first["message"]["fulfillment"] == "failed"
    for key, value in (("text", "replacement"), ("conversation_id", "another"),
                       ("task_id", str(uuid4())), ("status", "completed")):
        with pytest.raises(chief_agent.ChiefAgentError):
            chief_agent.report_agent_world_live_update({**envelope, key: value})
