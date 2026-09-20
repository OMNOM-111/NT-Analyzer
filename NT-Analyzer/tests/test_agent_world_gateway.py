"""Owner-review admission + real Handler regression, no real credentials."""
from __future__ import annotations

from contextlib import closing
from collections import defaultdict, deque
import base64
import binascii
import http.client
import json
import struct
import sqlite3
import threading
import zlib
from http.server import ThreadingHTTPServer
from uuid import UUID
from types import SimpleNamespace

import pytest

from app import account_auth, permissions, preview_sandbox, runtime_env, server
from app.ai_control_center import gateway
from app.ai_control_center.flags import Flag, resolve
from app.ai_control_center.http_api import decode_chart_png
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError
from tests.test_preview_sandbox import preview_env  # shared accepted isolated fixture


def png_data_url():
    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", binascii.crc32(kind + value) & 0xffffffff)
    content = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\xff")) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(content).decode()


@pytest.fixture()
def active(preview_env, monkeypatch):
    monkeypatch.setattr(account_auth, "_LOGIN_RATE", defaultdict(deque))
    out = preview_sandbox.activate_scenario("trusted_device", device_credential="world-gateway-test-device")
    raw = account_auth.authenticate_session(out["session_token"])
    raw = server.Handler._decorate_workspace_context(object(), raw)
    gateway._SNAPSHOTS.clear()
    return {"raw": raw, "token": out["session_token"], "root": preview_env["root"]}


def test_only_controlled_active_synthetic_workspace_enables_fixed_flags(active, monkeypatch):
    context = gateway.request_context(active["raw"], control_authorized=True)
    snapshot = gateway.flag_snapshot(context)
    enabled = {flag for flag in Flag if resolve(flag, scope=context.scope, snapshot=snapshot).enabled}
    assert enabled == {Flag.AI_COMMAND_CENTER_UI, Flag.AI_CONTROL_CENTER_READ_MODEL,
                       Flag.AI_TASK_GRAPH_V2, Flag.AI_EVALUATION_SHADOW}
    assert gateway.navigation(active["raw"], control_authorized=False)["enabled"] is False
    assert not (active["root"] / "agent-world.sqlite3").exists(), "navigation does not create a DB"
    for environment in ("canary", "production"):
        monkeypatch.setenv("DEPLOYMENT_ENV", environment)
        assert gateway.navigation(active["raw"], control_authorized=True)["enabled"] is False


@pytest.mark.parametrize("change", [
    {"is_owner": True}, {"device_confirmation_state": "pending"},
    {"role": "read_only"},
    {"capabilities": {"ai_lab": False}}, {"ux_mode": "beginner"},
    {"active_membership": {}}, {"user_uuid": "not-a-uuid"},
    {"workspace_id": "ws_other_tenant"},
    {"user": {"is_preview_user": True, "preview_sandbox_id": "b" * 24}},
])
def test_forged_or_stale_context_fails_closed(active, change):
    assert gateway.navigation({**active["raw"], **change}, control_authorized=True)["enabled"] is False


def test_new_prefix_uses_existing_product_permissions():
    assert permissions.required_capability("/api/ai-control-center/overview") == "ai_lab"
    assert "/api/ai-control-center/" in permissions.BEGINNER_DENIED_PREFIXES


def test_screenshot_is_real_bounded_crc_checked_png():
    valid = png_data_url()
    assert decode_chart_png(valid).startswith(b"\x89PNG")
    raw = decode_chart_png(valid)
    for broken in (valid + "garbage", "data:image/svg+xml;base64,AAAA", "data:image/png;base64,!!!!",
                   "data:image/png;base64," + base64.b64encode(raw[:-1]).decode(),
                   "data:image/png;base64," + base64.b64encode(raw + b"<script>").decode(),
                   "data:image/png;base64," + "A" * 350_001):
        with pytest.raises(ContractError, match="invalid_chart_screenshot"):
            decode_chart_png(broken)


def test_screenshot_rejects_crc_valid_missing_or_invalid_image_data():
    content = decode_chart_png(png_data_url())
    header, end = content[:33], content[-12:]
    for data in (b"", b"not-zlib", zlib.compress(b"\x00" * 50000), zlib.compress(b"\x05\x00\x00\x00\xff")):
        chunk = struct.pack(">I", len(data)) + b"IDAT" + data + struct.pack(">I", binascii.crc32(b"IDAT" + data) & 0xffffffff)
        encoded = "data:image/png;base64," + base64.b64encode(header + chunk + end).decode()
        with pytest.raises(ContractError, match="invalid_chart_screenshot"):
            decode_chart_png(encoded)


@pytest.fixture()
def http_preview(active):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]

    def request(path, body=None, *, control=True, csrf=True, origin=None):
        headers = {"Cookie": runtime_env.session_cookie_name() + "=" + active["token"]}
        if control:
            headers["Cookie"] += "; " + preview_sandbox.control_cookie_name() + "=" + preview_sandbox.control_cookie_value()
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Origin"] = origin or f"http://127.0.0.1:{port}"
            if csrf:
                headers["X-CSRF-Token"] = active["raw"]["csrf_token"]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        try:
            conn.request("POST" if body is not None else "GET", path,
                         body=json.dumps(body) if body is not None else None, headers=headers)
            response = conn.getresponse()
            data = response.read()
            ctype = response.getheader("Content-Type", "")
            return response.status, json.loads(data) if "json" in ctype else data
        finally:
            conn.close()

    yield request
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=3)


def test_http_flow_real_tasks_artifacts_chat_and_replay(http_preview):
    status, page = http_preview('/ui/ai-command-center.html')
    assert status == 200 and b'id="aw-center"' in page, page
    status, initial = http_preview(gateway.PREFIX + "overview")
    assert status == 200, initial
    assert initial["scope"]["synthetic"] is True
    status, result = http_preview(gateway.PREFIX + "demo-runs", {"idempotency_key": "gateway-test-run-001"})
    assert status == 200, result
    task_id = result["run"]["task_ids"][0]
    status, detail = http_preview(gateway.PREFIX + "tasks/" + task_id)
    assert status == 200, detail
    status, repeated = http_preview(gateway.PREFIX + "demo-runs", {"idempotency_key": "gateway-test-run-001"})
    assert status == 200 and repeated["run"]["replayed"] is True, repeated
    status, chat = http_preview(gateway.PREFIX + "tasks/" + task_id + "/chat", {})
    assert status == 200 and chat["conversation_id"].startswith("AW-"), chat
    status, same_chat = http_preview(gateway.PREFIX + "tasks/" + task_id + "/chat", {})
    assert status == 200 and same_chat["replayed"] is True, same_chat
    for identifier in result["run"]["task_ids"]:
        _, task = http_preview(gateway.PREFIX + "tasks/" + identifier)
        for artifact in task.get("artifacts", []):
            if (artifact.get("media_type") or artifact.get("mime_type")) == "image/svg+xml":
                aid = str(artifact.get("id") or artifact.get("artifact_id"))
                assert http_preview(gateway.PREFIX + "artifacts/" + aid)[0] == 200
                assert http_preview(gateway.PREFIX + "artifacts/" + aid, control=False)[0] == 403
                code, image_chat = http_preview(gateway.PREFIX + "tasks/" + identifier + "/chat",
                                               {"image_data_url": png_data_url()})
                assert code == 200, image_chat
                break
        else:
            continue
        break
    else:
        pytest.fail("No computed SVG evidence")


def test_http_rejects_scope_injection_csrf_and_uncontrolled_preview(http_preview):
    assert http_preview(gateway.PREFIX + "overview", control=False)[0] == 403
    assert http_preview(gateway.PREFIX + "demo-runs", {"idempotency_key": "test-run-001"}, csrf=False)[0] == 403
    assert http_preview(gateway.PREFIX + "demo-runs", {"idempotency_key": "test-run-001"}, origin="https://untrusted.invalid")[0] == 403
    code, result = http_preview(gateway.PREFIX + "demo-runs", {"idempotency_key": "test-run-001", "workspace_id": "ws_other_tenant"})
    assert code == 409 and result.get("code") == "invalid_demo_fields", result


def test_chat_projection_recovers_post_append_failure_and_old_replays(active, monkeypatch):
    from app.ai_lab import chief_agent
    handler = SimpleNamespace(_remote_context=active["raw"])
    scope = server.Handler._ai_conversation_scope(handler)
    args = dict(conversation_id="AW-recovery-check", title="Preview recovery", text="Verified synthetic result",
                request_id="aw.recovery.request", agent_id="ivan", agent_name="Иван", scope=scope)
    original = chief_agent._touch_conversation
    monkeypatch.setattr(chief_agent, "_touch_conversation", lambda *a, **kw: (_ for _ in ()).throw(OSError("injected post append failure")))
    with pytest.raises(OSError):
        chief_agent.report_local_preview_result(**args)
    monkeypatch.setattr(chief_agent, "_touch_conversation", original)
    path = chief_agent._conversation_file(args["conversation_id"], scope=scope)
    for i in range(501):
        chief_agent.append_jsonl(path, {"role": "user", "content": "Later message", "request_id": f"later.{i}"})
    assert chief_agent.report_local_preview_result(**args)["replayed"] is True
    rows = chief_agent.read_jsonl(path)
    assert len(rows) == 502
    assert sum(row.get("request_id") == args["request_id"] for row in rows) == 1
    row = next(row for row in chief_agent.list_conversations(scope=scope) if row["conversation_id"] == args["conversation_id"])
    assert row["message_count"] == 502 and row["work_state"] == "completed"


def test_preview_reset_waits_for_sqlite_operation_before_wiping(active, monkeypatch):
    database = active["root"] / "agent-world.sqlite3"
    SQLiteAgentWorldRepository(database)
    entered, release, reset_started, wiped = (threading.Event() for _ in range(4))
    errors = []
    original = preview_sandbox._wipe_isolated_root

    def wipe():
        wiped.set()
        original()

    monkeypatch.setattr(preview_sandbox, "_wipe_isolated_root", wipe)

    def operation():
        try:
            with preview_sandbox.data_operation():
                with closing(sqlite3.connect(database)) as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    entered.set()
                    assert release.wait(5)
                    conn.commit()
        except BaseException as exc:
            errors.append(exc)

    def reset():
        try:
            reset_started.set()
            preview_sandbox.reset("new_user", device_credential="world-reset-test-device")
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=operation)
    resetter = threading.Thread(target=reset)
    worker.start()
    assert entered.wait(3)
    resetter.start()
    assert reset_started.wait(3)
    assert not wiped.wait(0.05)
    release.set()
    worker.join(5)
    resetter.join(5)
    assert not worker.is_alive() and not resetter.is_alive()
    assert not errors
    assert wiped.is_set() and not database.exists()
    assert account_auth.authenticate_session(active["token"]) is None
