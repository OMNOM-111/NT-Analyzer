"""Actual Handler/Local facade over disposable canonical jobs and chart receipts.

No credentialed account, NinjaTrader process or external network is used. Only
the established owner context/catalog IO are fixtures; routing, body parsing,
origin/CSRF, fresh gateway admission and DTO projection execute real app code.
GET may emit its single required flag-activation audit, never domain writes.
"""
from __future__ import annotations

import copy
import hashlib
import http.client
import json
import socket
import sqlite3
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from uuid import UUID, uuid5

import pytest

from app import jobqueue, market_data, preview_sandbox, server
from app.ai_lab import chief_agent
from app.ai_control_center import live_backtests, live_charts, live_gateway as gateway
from app.ai_control_center.contracts import ActorKind, ActorRef, Environment, RequestContext, TenantScope
from tests.test_agent_world_gateway import active, http_preview, png_data_url
from tests.test_preview_sandbox import preview_env
from tests.test_agent_world_live_backtests import _spec, _terminal, service as canonical_service
from tests.test_agent_world_live_gateway import USER_ID, USER_UUID, WORKSPACE, OTHER_WORKSPACE, owner


_CONNECT = socket.create_connection
_GET = object()
CSRF = "isolated-http-csrf-token"
CONVERSATION = "http-owner-report"
CHART_CONVERSATION = "http-owner-chart"
COMMAND = "cc_" + "1" * 32
FOREIGN_COMMAND = "cc_" + "2" * 32
FOREIGN_UUID = "12000000-0000-4000-8000-000000000007"


@pytest.fixture(autouse=True)
def isolated_http_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "development"))
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "production-disabled"))
    monkeypatch.setenv("STRATFORGE_CANARY_DATA_ROOT", str(tmp_path / "canary-disabled"))
    monkeypatch.setenv("NT_ANALYZER_SQLITE_PATH", str(tmp_path / "durable.sqlite3"))
    monkeypatch.setenv("STRATFORGE_PREVIEW_SANDBOX", "0")
    monkeypatch.setenv("STRATFORGE_PREVIEW_ID", "")
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    monkeypatch.setattr(gateway, "_SNAPSHOTS", {})


def scope_args(workspace=WORKSPACE, user_id=USER_ID, user_uuid=USER_UUID):
    identity = UUID(user_uuid)
    context = RequestContext(scope=TenantScope(environment=Environment.DEVELOPMENT, workspace_id=workspace),
                             user_uuid=identity, actor=ActorRef(kind=ActorKind.HUMAN, actor_id=identity))
    return {"context": context, "source_scope": {"workspace_id": workspace, "user_id": user_id, "allow_legacy": False},
            "chat_scope": {"workspace_id": workspace, "user_id": user_id, "user_uuid": user_uuid,
                           "is_owner": True, "uses_owner_runtime": True}, "admit": lambda: None}


def manifest(root):
    result = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.name.endswith((".sqlite3-wal", ".sqlite3-shm")):
            continue
        if path.suffix == ".sqlite3":
            # Opening readers can checkpoint an already-written WAL; compare
            # rows/schema rather than physical SQLite page/sidecar placement.
            with sqlite3.connect("file:" + path.as_posix() + "?mode=ro", uri=True) as connection:
                data = "\n".join(connection.iterdump()).encode()
        else:
            data = path.read_bytes()
        result[str(path.relative_to(root))] = hashlib.sha256(data).hexdigest()
    return result


@pytest.fixture()
def http_live(owner, canonical_service, monkeypatch, tmp_path):
    # Seed fake completed source files in the real canonical job layout, not a
    # fabricated facade DTO. These setup writes finish before request evidence.
    own = canonical_service.start(**scope_args(), spec=_spec(), idempotency_key="http-own-setup",
                                  conversation_id=CONVERSATION)
    _terminal(own)
    foreign = canonical_service.start(**scope_args(OTHER_WORKSPACE, 998877, FOREIGN_UUID), spec=_spec(),
                                      idempotency_key="http-foreign-setup", conversation_id="foreign-secret-chat")
    _terminal(foreign)
    saved = market_data.save_snapshot(png_data_url(), meta={"instrument": "MNQ 09-26", "timeframe": "5m"})
    snapshot_path = market_data.snapshot_path(saved["file"])
    capture = {"surface": "desktop_chart", "view_preserved": True, "instrument": "MNQ 09-26", "timeframe": "5m",
               "rendered_bar_count": 3, "total_bar_count": 5}
    verification = {"passed": True, "snapshot": saved, "capture": capture,
                    "snapshot_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest()}
    chart_message = {"conversation_id": CHART_CONVERSATION, "timestamp_utc": "2026-09-05T00:01:00Z",
                     "content": "Stored Desktop screenshot; this is not proof of a live feed.",
                     "actions": [{"source_kind": "desktop_chart", "command_id": COMMAND, "status": "completed",
                                  "verification": verification}]}
    command = {"id": COMMAND, "type": "snapshot", "status": "done", "instrument": "MNQ 09-26", "timeframe": "5m",
               "conversation_id": CHART_CONVERSATION, "scope": {"workspace_id": WORKSPACE, "user_id": USER_ID},
               "payload": {"agent_world": True, "owner_user_uuid": USER_UUID}, "created_at_utc": "2026-09-05T00:00:00Z"}
    foreign_command = {**copy.deepcopy(command), "id": FOREIGN_COMMAND,
                       "scope": {"workspace_id": OTHER_WORKSPACE, "user_id": 998877},
                       "payload": {"agent_world": True, "owner_user_uuid": FOREIGN_UUID}}
    calls = {"starts": [], "reads": [], "chat_reads": [], "observations": []}
    state = {"raw_changes": {}, "chart_message": chart_message, "commands": [command, foreign_command]}

    def local_context(self):
        workspace = copy.deepcopy(owner.state["workspaces"][WORKSPACE])
        user = copy.deepcopy(owner.state["user"])
        membership = {"workspace_id": WORKSPACE, "user_id": USER_ID, "role": "owner"}
        return {"source": "local", "role": "owner", "is_owner": True, "user_id": USER_ID,
                "user_uuid": USER_UUID, "user": user, "workspace_id": WORKSPACE,
                "active_workspace": workspace, "active_membership": membership,
                "capabilities": copy.deepcopy(owner.state["permissions"]["capabilities"]),
                "csrf_hash": hashlib.sha256(CSRF.encode()).hexdigest(), **state["raw_changes"]}

    def chat_messages(*, scope):
        assert scope["workspace_id"] == WORKSPACE and scope["user_uuid"] == USER_UUID
        calls["chat_reads"].append(copy.deepcopy(scope))
        return [copy.deepcopy(state["chart_message"])]

    def forbidden(*args, **kwargs):
        pytest.fail("Read/inspection route attempted a domain write or publish")

    original_start = live_backtests.LiveBacktestService.start

    def start(service, **kwargs):
        calls["starts"].append(kwargs)
        return original_start(service, **kwargs)

    original_detail = live_backtests.LiveBacktestService.task_detail

    def detail(service, **kwargs):
        calls["reads"].append(kwargs)
        return original_detail(service, **kwargs)

    monkeypatch.setattr(server.Handler, "_local_owner_context", local_context)
    monkeypatch.setattr(server.workspaces, "runtime_storage_dir_for_context", lambda context: str(tmp_path / "runtime"))
    monkeypatch.setattr(market_data, "_load_commands_doc", lambda: {"commands": copy.deepcopy(state["commands"])})
    monkeypatch.setattr(chief_agent, "agent_world_live_messages", chat_messages)
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", forbidden)
    monkeypatch.setattr(live_backtests.LiveBacktestService, "reconcile", forbidden)
    monkeypatch.setattr(live_charts, "reconcile", forbidden)
    monkeypatch.setattr(live_backtests.LiveBacktestService, "start", start)
    monkeypatch.setattr(live_backtests.LiveBacktestService, "task_detail", detail)
    monkeypatch.setattr(server.observability, "record_http", lambda *args: calls["observations"].append(args))
    monkeypatch.setattr(socket, "getfqdn", lambda value="": "localhost")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]

    def loopback_only(address, *args, **kwargs):
        assert address == ("127.0.0.1", port), "Only this disposable HTTP server may be contacted"
        return _CONNECT(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", loopback_only)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()

    def request(route, body=_GET, *, csrf=CSRF, origin="same", content_type="application/json", raw_body=None):
        path = route if route.startswith("/") else gateway.PREFIX + route
        headers = {}
        if body is not _GET:
            headers["Content-Type"] = content_type
            if origin is not None:
                headers["Origin"] = f"http://127.0.0.1:{port}" if origin == "same" else origin
            if csrf is not None:
                headers["X-CSRF-Token"] = csrf
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        try:
            connection.request("GET" if body is _GET else "POST", path,
                               body=None if body is _GET else raw_body if raw_body is not None else json.dumps(body), headers=headers)
            response = connection.getresponse()
            content = response.read()
            assert "application/json" in response.getheader("Content-Type", ""), content[:200]
            return response.status, json.loads(content)
        finally:
            connection.close()

    yield SimpleNamespace(request=request, owner=owner, own=own, foreign=foreign, state=state, calls=calls,
                          root=tmp_path, snapshot=saved, chart_id=str(uuid5(live_charts._NAMESPACE, COMMAND)),
                          foreign_chart_id=str(uuid5(live_charts._NAMESPACE, FOREIGN_COMMAND)))
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=3)
    assert not thread.is_alive()
    jobqueue.reset_caches()


def test_actual_handler_overview_projects_real_canonical_report_and_desktop_sources(http_live):
    status, result = http_live.request("overview")
    assert status == 200, result
    assert result["enabled"] is True and result["scope"] == {"environment": "development", "workspace_id": WORKSPACE, "synthetic": False}
    assert result["capabilities"]["can_run_demo"] is False
    assert set(result) >= {"stats", "agents", "tasks", "outcomes", "attention", "activity", "flags", "limitations"}
    assert result["stats"]["completed_tasks"] == 2 and result["stats"]["active_tasks"] == 0
    assert {task["id"] for task in result["tasks"]} == {http_live.own["task_id"], http_live.chart_id}
    assert {value["source_kind"] for value in result["outcomes"]} == {"ninjatrader_report", "desktop_chart"}
    assert all(value["synthetic"] is False for value in result["outcomes"])
    chart = next(value for value in result["outcomes"] if value["source_kind"] == "desktop_chart")
    assert chart["artifact"]["url"] == http_live.snapshot["url"]
    assert chart["artifact"]["media_type"] == "image/png"
    assert len(chart["artifact"]["sha256"]) == 64
    assert all(agent["evaluation"]["score_pct"] is None and agent["evaluation"]["sample_size"] == 0 for agent in result["agents"])
    assert "foreign-secret-chat" not in json.dumps(result)


def test_tasks_detail_chat_and_chart_fallback_have_compatible_dtos(http_live):
    status, work = http_live.request("tasks")
    assert status == 200 and work["next_cursor"] is None and isinstance(work["items"], list)
    for identifier, conversation, kind in [(http_live.own["task_id"], CONVERSATION, "ninjatrader_report"),
                                            (http_live.chart_id, CHART_CONVERSATION, "desktop_chart")]:
        status, detail = http_live.request("tasks/" + identifier)
        assert status == 200, detail
        assert detail["task"]["id"] == identifier
        assert detail["task"]["source_kind"] == kind and detail["task"]["synthetic"] is False
        assert set(detail) >= {"task", "result_text", "activity", "contributions", "outcomes", "evaluations", "artifacts", "decisions"}
        assert detail["verification"]["passed"] is True
        status, chat = http_live.request("tasks/" + identifier + "/chat", {})
        assert status == 200 and chat == {"conversation_id": conversation}, chat
    assert {str(call["entity_id"]) for call in http_live.calls["reads"]} == {http_live.own["task_id"], http_live.chart_id}
    for call in http_live.calls["reads"]:
        assert call["source_scope"] == {"workspace_id": WORKSPACE, "user_id": USER_ID, "allow_legacy": False}
        assert call["context"].user_uuid == UUID(USER_UUID)
    assert http_live.calls["starts"] == []


def test_get_and_open_chat_never_mutate_jobs_or_chat_allow_one_flag_activation_audit(http_live):
    before = manifest(http_live.root)
    for _ in range(2):
        for route in ("overview", "tasks", "tasks/" + http_live.own["task_id"], "tasks/" + http_live.chart_id):
            assert http_live.request(route)[0] == 200
    assert http_live.request("tasks/" + http_live.own["task_id"] + "/chat", {})[0] == 200
    assert manifest(http_live.root) == before
    assert http_live.calls["starts"] == []
    assert len(http_live.owner.calls["audit"]) == 1
    event, data = http_live.owner.calls["audit"][0]
    assert event[1] == "agent_world.local_flags_activated"
    assert set(data["details"]["flags"]) == {"AI_CONTROL_CENTER_READ_MODEL", "AI_COMMAND_CENTER_UI", "AI_TASK_GRAPH_V2",
        "AI_EVALUATION_SHADOW", "AI_MEMORY_V2", "AI_CONSENSUS_V2", "AI_COURT_V1", "AI_SOCIAL_PUBLISH_V1"}
    assert data["details"]["synthetic"] is False


def test_real_scope_cannot_run_synthetic_demo(http_live):
    status, result = http_live.request("demo-runs", {"idempotency_key": "not-real"})
    assert status == 404 and result["code"] == "route_not_found"
    assert http_live.calls["starts"] == []


@pytest.mark.parametrize("mode", ["off", "nonowner", "pending_device", "foreign_identity", "missing_ai", "budget"])
def test_actual_http_admission_revalidates_owner_scope_before_any_domain_access(http_live, monkeypatch, mode):
    if mode == "off":
        monkeypatch.delenv(gateway.WORKSPACES_ENV)
    elif mode == "nonowner":
        http_live.state["raw_changes"]["is_owner"] = False
    elif mode == "pending_device":
        http_live.state["raw_changes"].update(source="browser", device_confirmation_state="pending")
    elif mode == "foreign_identity":
        http_live.state["raw_changes"]["user"] = {**http_live.owner.state["user"], "user_uuid": FOREIGN_UUID}
    elif mode == "missing_ai":
        http_live.owner.state["permissions"]["capabilities"]["ai_lab"] = False
    else:
        http_live.owner.state["budget_ok"] = False
    assert http_live.request("overview")[0] == 403
    assert http_live.request("tasks/" + http_live.own["task_id"] + "/chat", {})[0] == 403
    assert http_live.calls["reads"] == http_live.calls["starts"] == http_live.calls["chat_reads"] == []


def test_read_only_local_history_does_not_grant_backtest_or_domain_mutation(http_live):
    http_live.state["raw_changes"]["role"] = "read_only"
    assert http_live.request("overview")[0] == 200
    assert http_live.request("tasks/" + http_live.own["task_id"])[0] == 200
    status, _ = http_live.request("backtests", {"spec": _spec(), "idempotency_key": "read-only-must-not-run",
        "conversation_id": CONVERSATION})
    assert status == 403
    status, _ = http_live.request("domains/personas/new/create", {
        "payload": {"name": "must-not-create", "description": "", "style": ""}, "idempotency_key": "readonly-domain-reject"})
    assert status == 403 and http_live.calls["starts"] == []


def test_workspace_reader_gets_history_without_owner_runtime_or_write_authority(http_live):
    http_live.owner.state["workspaces"][WORKSPACE]["membership"]["role"] = "viewer"
    status, result = http_live.request("overview")
    assert status == 200 and result["enabled"] is True
    assert result["tasks"] == []  # no access to the global owner's NT/Desktop sources
    status, _ = http_live.request("backtests", {"spec": _spec(), "idempotency_key": "reader-must-not-run",
        "conversation_id": CONVERSATION})
    assert status == 403
    status, _ = http_live.request("domains/personas/new/create", {
        "payload": {"name": "must-not-create", "description": "", "style": ""}, "idempotency_key": "reader-domain-reject"})
    assert status == 403 and http_live.calls["starts"] == []
    assert http_live.calls["reads"] == http_live.calls["chat_reads"] == []


@pytest.mark.parametrize("identifier", ["foreign_job", "foreign_chart", "12000000-0000-4000-8000-000000000099"])
def test_foreign_or_unknown_task_uuid_cannot_read_or_open_foreign_chat(http_live, identifier):
    identifier = http_live.foreign["task_id"] if identifier == "foreign_job" else http_live.foreign_chart_id if identifier == "foreign_chart" else identifier
    for suffix, body in [("", _GET), ("/chat", {})]:
        status, result = http_live.request("tasks/" + identifier + suffix, body)
        assert status == 404 and result["code"] == "task_not_found", result
        assert "foreign-secret-chat" not in json.dumps(result)


@pytest.mark.parametrize("identifier", ["not-a-uuid", "undefined", "%3Cscript%3E"])
def test_invalid_uuid_returns_json_error_not_internal_exception(http_live, identifier):
    status, result = http_live.request("tasks/" + identifier)
    assert status == 400 and result["code"] == "invalid_request", result


@pytest.mark.parametrize("headers", [
    {"csrf": None}, {"csrf": "wrong"}, {"origin": None}, {"origin": "https://attacker.invalid"},
    {"content_type": "text/plain"},
])
def test_existing_handler_origin_csrf_and_content_type_guard_real_post(http_live, headers):
    status, result = http_live.request("tasks/" + http_live.own["task_id"] + "/chat", {}, **headers)
    # A public foreign Origin loses loopback-owner admission first (401);
    # valid owner context with bad/missing CSRF is rejected by the POST gate.
    allowed = {415} if "content_type" in headers else {401, 403} if headers.get("origin") == "https://attacker.invalid" else {403}
    assert status in allowed, result
    assert http_live.calls["reads"] == http_live.calls["starts"] == []


@pytest.mark.parametrize("injection", [
    {"workspace_id": OTHER_WORKSPACE}, {"user_uuid": FOREIGN_UUID}, {"is_owner": True},
    {"scope": {"workspace_id": OTHER_WORKSPACE}}, {"image_data_url": "data:image/png;base64,YQ=="},
])
def test_post_body_cannot_override_authorized_scope_or_preview_chat_action(http_live, injection):
    status, result = http_live.request("tasks/" + http_live.own["task_id"] + "/chat", injection)
    assert status == 409 and result["code"] == "invalid_request", result
    body = {"spec": _spec(), "idempotency_key": "http-body-injection", "conversation_id": CONVERSATION, **injection}
    assert http_live.request("backtests", body)[0] == 403
    assert http_live.calls["reads"] == http_live.calls["starts"] == []


def test_query_scope_injection_never_changes_server_selected_workspace(http_live):
    status, result = http_live.request("overview?workspace_id=" + OTHER_WORKSPACE + "&user_uuid=" + FOREIGN_UUID)
    assert status == 200 and result["scope"]["workspace_id"] == WORKSPACE
    assert http_live.foreign["task_id"] not in {task["id"] for task in result["tasks"]}


@pytest.mark.parametrize("body", [[], None, "text", 1])
def test_non_object_body_is_rejected_by_actual_handler_before_service(http_live, body):
    status, result = http_live.request("backtests", body)
    assert status == 400, result
    assert http_live.calls["starts"] == []


def test_explicit_backtest_post_uses_canonical_queue_and_replays_not_nt_execution(http_live):
    body = {"spec": _spec(), "idempotency_key": "http-submit-owned-job", "conversation_id": CONVERSATION}
    status, first = http_live.request("backtests", body)
    assert status == 200 and first["task"]["status"] == "ready", first
    assert first["task"]["synthetic"] is False and first["task"]["source_status"] == "pending"
    assert first["detail"]["verification"]["passed"] is False
    status, replay = http_live.request("backtests", body)
    assert status == 200 and replay["job_id"] == first["job_id"] and replay["replayed"] is True
    assert len(http_live.calls["starts"]) == 2
    for call in http_live.calls["starts"]:
        assert call["source_scope"] == {"workspace_id": WORKSPACE, "user_id": USER_ID, "allow_legacy": False}
        assert call["chat_scope"]["user_uuid"] == USER_UUID
        assert set(call) == {"context", "source_scope", "chat_scope", "admit", "spec", "idempotency_key", "conversation_id"}
    assert jobqueue.find_job_dir(first["job_id"])[0] == "pending"


def test_preview_dispatch_never_falls_through_to_real_local_facade(http_live, monkeypatch):
    monkeypatch.setattr(preview_sandbox, "enabled", lambda: True)
    monkeypatch.setattr(gateway, "from_handler", lambda handler: pytest.fail("Preview reached real Local admission"))
    for route, body in [("overview", _GET), ("backtests", {"spec": _spec(), "idempotency_key": "preview-forbidden", "conversation_id": CONVERSATION})]:
        status, result = http_live.request(route, body)
        assert status in {403, 404, 409}, result
        if status == 409:
            assert result["code"] == "preview_root_not_isolated"
    assert http_live.calls["reads"] == http_live.calls["starts"] == []


def test_proper_preview_http_stays_synthetic_and_never_enters_real_facade(http_preview, monkeypatch):
    monkeypatch.setattr(gateway, "from_handler", lambda handler: pytest.fail("Synthetic Preview reached real Local admission"))
    status, result = http_preview(gateway.PREFIX + "overview")
    assert status == 200, result
    assert result["scope"]["synthetic"] is True
    assert result["scope"]["workspace_id"] != WORKSPACE
    assert result["capabilities"]["can_run_demo"] is True
    assert all(task["synthetic"] is True for task in result["tasks"])
    assert CONVERSATION not in json.dumps(result) and CHART_CONVERSATION not in json.dumps(result)


PREVIEW_DOMAINS = ("personas", "models", "model_tasks", "tasks", "decisions", "court", "memory", "experiments",
                   "projects", "routines", "calendar", "system", "publications")


@pytest.fixture
def guarded_preview_panels(http_preview, active, monkeypatch):
    from app.ai_control_center import domain_gateway, model_execution
    from app.ai_lab import agent_registry

    def forbidden(*args, **kwargs):
        pytest.fail("Disabled Preview drawer entered Local data, global credentials or model execution")

    for name in ("from_handler", "access", "models", "repository", "social", "list_domain", "mutate"):
        monkeypatch.setattr(domain_gateway, name, forbidden)
    monkeypatch.setattr(gateway, "access", forbidden)
    monkeypatch.setattr(gateway, "from_handler", forbidden)
    monkeypatch.setattr(agent_registry, "list_agents", forbidden)
    monkeypatch.setattr(agent_registry, "get_agent", forbidden)
    monkeypatch.setattr(model_execution.ModelExecutor, "__call__", forbidden)
    original = socket.create_connection

    def loopback_only(address, *args, **kwargs):
        assert address[0] == "127.0.0.1", "Preview panel attempted an external network connection"
        return original(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", loopback_only)
    return SimpleNamespace(request=http_preview, root=active["root"])


def test_known_preview_domain_gets_are_explanatory_disabled_without_files_or_local_data(guarded_preview_panels):
    preview = guarded_preview_panels
    before = {str(path.relative_to(preview.root)) for path in preview.root.rglob("*") if path.is_file()}
    for domain in PREVIEW_DOMAINS:
        status, result = preview.request(gateway.PREFIX + "domains/" + domain)
        assert status == 200, (domain, result)
        assert result["enabled"] is False and result["synthetic"] is True
        assert result["status"] == "EXTERNAL BLOCKED"
        assert result["items"] == result["actions"] == result["source_candidates"] == []
        assert result["limitations"] and "Exit Preview" in result["message"]
        assert result["flags"]["AI_SOCIAL_PUBLISH_V1"] is False
        for owner_data in (USER_UUID, WORKSPACE, CONVERSATION, CHART_CONVERSATION):
            assert owner_data not in json.dumps(result)
    assert not (preview.root / "agent-world.sqlite3").exists()
    assert {str(path.relative_to(preview.root)) for path in preview.root.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("route", [
    "domains/models/new/connect", "domains/models/new/bind_existing", "domains/personas/new/create",
    "domains/memory/new/create", "domains/publications/new/prepare", "domains/publications/new/publish",
])
def test_preview_real_domain_posts_are_forbidden_before_storage_or_external_effects(guarded_preview_panels, route):
    preview = guarded_preview_panels
    before = {str(path.relative_to(preview.root)) for path in preview.root.rglob("*") if path.is_file()}
    status, result = preview.request(gateway.PREFIX + route, {"payload": {}, "idempotency_key": "preview-real-domain-denied"})
    assert status in {403, 404}, result
    assert not (preview.root / "agent-world.sqlite3").exists()
    assert {str(path.relative_to(preview.root)) for path in preview.root.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("suffix", ["models", "memory", "publications"])
def test_preview_disabled_domain_get_still_requires_owner_control_cookie(guarded_preview_panels, suffix):
    status, result = guarded_preview_panels.request(gateway.PREFIX + "domains/" + suffix, control=False)
    assert status == 403, result


def test_unknown_preview_domain_is_not_promoted_to_a_known_disabled_tool(guarded_preview_panels):
    status, result = guarded_preview_panels.request(gateway.PREFIX + "domains/arbitrary-admin")
    assert status == 404 and result["code"] == "route_not_found"
