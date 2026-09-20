"""Actual command/snapshot/SF Chat mechanisms in disposable roots only."""
from __future__ import annotations

import base64
import copy
import hashlib
import struct
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app import market_data
from app.ai_lab import chief_agent
from app.ai_control_center import live_charts, live_gateway
from app.ai_control_center.contracts import ActorKind, ActorRef, Environment, RequestContext, TenantScope
from app.ai_control_center.states import ContractError


def _authorized(*, user="92cb73cb-7b16-4dcd-85e0-ce2cccdcb98d", user_id=9123, workspace="ws_chart_owner_001"):
    identity = UUID(user)
    context = RequestContext(scope=TenantScope(environment=Environment.DEVELOPMENT, workspace_id=workspace),
                             user_uuid=identity, actor=ActorRef(kind=ActorKind.HUMAN, actor_id=identity))
    scope = {"user_id": user_id, "user_uuid": user, "workspace_id": workspace, "membership_role": "owner",
             "uses_owner_runtime": True, "is_owner": True, "workspace_kind": "owner", "display_name": "Test owner"}
    return {"context": context, "source_scope": {"user_id": user_id, "workspace_id": workspace, "allow_legacy": False},
            "chat_scope": scope, "admit": lambda: None}


@pytest.fixture
def authorized(monkeypatch, tmp_path):
    runtime = tmp_path / "chart-runtime"
    runtime.mkdir()
    registry = tmp_path / "chat-registry"
    registry.mkdir()
    monkeypatch.setattr(market_data, "_runtime_dir", lambda: runtime)
    monkeypatch.setattr(chief_agent.paths, "REGISTRY_DIR", registry)
    monkeypatch.setattr(chief_agent.paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chief_agent, "_explicit_production", lambda: False)
    auth = _authorized()
    def access(scope):
        if any(scope.get(key) != auth["chat_scope"].get(key) for key in ("user_id", "user_uuid", "workspace_id", "is_owner", "uses_owner_runtime")):
            raise ContractError("chart_test_scope_denied")
        auth["admit"]()
        return auth
    monkeypatch.setattr(live_gateway, "access", access)
    monkeypatch.setattr(market_data, "render_chart_snapshot", lambda *a, **k: pytest.fail("no headless substitute allowed"))
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("no external transport allowed"))
    return auth


def _png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    # Four actual RGB pixels, with PNG's filter byte and valid CRC/zlib data.
    pixels = b"\x00" + bytes([30, 45, 60, 50, 90, 130]) + b"\x00" + bytes([15, 25, 35, 100, 160, 220])
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def _start(authorized, *, message="Иван, сделай снимок рабочего стола MNQ 09-26, 5m", request_id="chart-request-1", conversation="chart-real-1"):
    return live_charts.start(message=message, authorized=authorized, conversation_id=conversation, request_id=request_id)


def _body(start):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"command_id": start["command_id"], "agent_world": True, "conversation_id": "chart-real-1",
            "instrument": "MNQ 09-26", "timeframe": "5m", "mirror_to_telegram": False,
            "image": "data:image/png;base64," + base64.b64encode(_png()).decode(),
            "capture": {"surface": "desktop_chart", "view_preserved": True, "window_id": "desk-window-1",
                        "instrument": "MNQ 09-26", "timeframe": "5m", "captured_at_utc": now,
                        "rendered_bar_count": 40, "total_bar_count": 200,
                        "first_bar_time_utc": "2026-09-04T14:00:00Z", "last_bar_time_utc": "2026-09-04T17:15:00Z",
                        "series_hash": "observed-client-series", "price_marker_live": False,
                        "provider_connection_state": "disconnected", "history_status": "available", "transport": "local"}}


def _messages(authorized):
    return chief_agent.agent_world_live_messages(scope=authorized["chat_scope"])


def _snapshot_files():
    return list(market_data._snapshot_dir().glob("cs_*.png"))


def test_start_uses_existing_desktop_queue_preserves_view_and_no_telegram_or_headless(authorized):
    started = _start(authorized)
    assert started["status"] == "queued"
    rows = market_data.list_chart_commands()["commands"]
    assert len(rows) == 1
    command = rows[0]
    assert command["id"] == started["command_id"]
    assert command["type"] == "snapshot" and command["instrument"] == "MNQ 09-26" and command["timeframe"] == "5m"
    assert command["payload"]["fit"] is False
    assert command["payload"]["mirror_to_telegram"] is False
    assert command["payload"].get("headless_backend") is not True
    assert command["scope"]["user_id"] == authorized["source_scope"]["user_id"]
    assert command["payload"]["owner_user_uuid"] == str(authorized["context"].user_uuid)
    assert _snapshot_files() == [] and _messages(authorized) == []


def test_identical_start_replays_command_and_changed_body_conflicts(authorized):
    first = _start(authorized)
    assert _start(authorized)["command_id"] == first["command_id"]
    for changed in ({"message": "Иван, сделай снимок рабочего стола MNQ 09-26, 15m"}, {"conversation": "another-chat"}):
        with pytest.raises(ContractError, match="idempotency_conflict"):
            _start(authorized, **changed)
    assert len(live_charts.commands(authorized)) == 1


@pytest.mark.parametrize("message", ["Иван, сделай снимок рабочего стола", "MNQ 5m", "MNQ 09-26", "MNQ 09-26 0m"])
def test_parser_requires_explicit_instrument_and_timeframe(authorized, message):
    with pytest.raises(ContractError, match="explicit_instrument_timeframe_required"):
        _start(authorized, message=message)
    assert live_charts.commands(authorized) == []


@pytest.mark.parametrize("tf", ["2m", "9999m"])
def test_unsupported_timeframe_cannot_be_silently_queued_as_empty(authorized, tf):
    with pytest.raises(ContractError):
        _start(authorized, message="Иван, сделай снимок рабочего стола MNQ 09-26, " + tf)
    assert live_charts.commands(authorized) == []


@pytest.mark.parametrize("alter", ["user", "workspace", "uuid"])
def test_commands_and_completion_are_private_to_scope_and_owner_uuid(authorized, alter):
    first = _start(authorized)
    foreign = _authorized(user="f89a0f73-5086-41d8-b3a9-17be4fdbecfb" if alter == "uuid" else str(authorized["context"].user_uuid),
                          user_id=9999 if alter == "user" else 9123,
                          workspace="ws_chart_another_001" if alter == "workspace" else "ws_chart_owner_001")
    assert live_charts.commands(foreign) == []
    with pytest.raises(ContractError, match="scope_required"):
        live_charts.complete(_body(first), foreign)
    assert _snapshot_files() == []


@pytest.mark.parametrize("command_id", ["cc_" + "a" * 32, "../../outside", "", "cs_" + "1" * 32])
def test_reforged_command_ids_do_not_create_or_ack_evidence(authorized, command_id):
    started = _start(authorized)
    body = {**_body(started), "command_id": command_id}
    with pytest.raises(ContractError, match="scope_required"):
        live_charts.complete(body, authorized)
    with pytest.raises(ContractError, match="scope_required"):
        live_charts.acknowledge({"id": command_id, "status": "done"}, authorized)
    assert _snapshot_files() == []


@pytest.mark.parametrize("change,code", [
    ({"conversation_id": "foreign"}, "context_mismatch"), ({"instrument": "MGC 12-26"}, "context_mismatch"),
    ({"timeframe": "15m"}, "context_mismatch"), ({"mirror_to_telegram": True}, "context_mismatch"),
    ({"capture": None}, "capture_required"),
])
def test_capture_must_match_original_command_and_disable_telegram(authorized, change, code):
    started = _start(authorized)
    with pytest.raises(ContractError, match=code):
        live_charts.complete({**_body(started), **change}, authorized)
    assert _snapshot_files() == []


@pytest.mark.parametrize("change,code", [
    ({"surface": "headless_renderer"}, "capture_required"), ({"view_preserved": False}, "capture_required"),
    ({"rendered_bar_count": 0}, "bars_required"), ({"rendered_bar_count": True}, "bars_required"),
    ({"rendered_bar_count": 201}, "bars_required"), ({"total_bar_count": 1_000_001}, "bars_required"),
    ({"window_id": ""}, "bars_required"), ({"instrument": "MGC 12-26"}, "context_mismatch"),
    ({"timeframe": "15m"}, "context_mismatch"), ({"captured_at_utc": "not-a-date"}, "capture_stale"),
    ({"captured_at_utc": "2026-01-01T00:00:00"}, "capture_stale"),
    ({"history_status": 1}, "invalid_metadata"), ({"price_marker_live": "true"}, "invalid_metadata"),
    ({"credentials": "not-permitted"}, "invalid_metadata"),
])
def test_capture_requires_bars_recent_time_and_bounded_observations(authorized, change, code):
    body = _body(_start(authorized))
    body["capture"].update(change)
    with pytest.raises(ContractError, match=code):
        live_charts.complete(body, authorized)
    assert _snapshot_files() == []


@pytest.mark.parametrize("minutes", [-6, 6])
def test_capture_rejects_stale_or_future_receipt_timestamp(authorized, minutes):
    body = _body(_start(authorized))
    body["capture"]["captured_at_utc"] = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
    with pytest.raises(ContractError, match="capture_stale"):
        live_charts.complete(body, authorized)


def test_genuine_png_is_saved_before_publication_and_same_chat_receipt_is_durable(authorized, monkeypatch):
    started = _start(authorized)
    original = chief_agent.report_agent_world_live_update
    snapshots = []
    def publish(envelope):
        command = live_charts.commands(authorized)[0]
        receipt = command["result"]["agent_world_receipt"]
        assert command["status"] == "done"
        assert receipt["envelope"] == envelope
        path = market_data.snapshot_path(receipt["snapshot"]["file"])
        assert path.read_bytes() == _png()
        snapshots.append(path)
        return original(envelope)
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", publish)
    out = live_charts.complete(_body(started), authorized)
    assert out["ok"] and out["report"]["ok"]
    assert len(snapshots) == 1 and len(_messages(authorized)) == 1
    detail = live_charts.details(authorized)[0]
    assert detail["task"]["id"] == started["task_id"]
    assert detail["task"]["status"] == "succeeded"
    assert detail["verification"]["snapshot_sha256"] == hashlib.sha256(_png()).hexdigest()
    assert detail["verification"]["capture"]["price_marker_live"] is False
    assert detail["verification"]["model_quality_assessed"] is False
    assert detail["artifacts"][0]["url"].startswith("/api/ops/runtime/snapshots/cs_")


def test_completion_retry_does_not_save_or_append_twice(authorized):
    body = _body(_start(authorized))
    first = live_charts.complete(body, authorized)
    second = live_charts.complete(body, authorized)
    assert first["snapshot"]["id"] == second["snapshot"]["id"]
    assert second["report"]["idempotent_replay"] is True
    assert len(_snapshot_files()) == 1 and len(_messages(authorized)) == 1


def test_receipt_repairs_publication_failure_without_recapture(authorized, monkeypatch):
    body = _body(_start(authorized))
    original = chief_agent.report_agent_world_live_update
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", lambda envelope: (_ for _ in ()).throw(RuntimeError("simulated interrupted publication")))
    with pytest.raises(RuntimeError, match="interrupted publication"):
        live_charts.complete(body, authorized)
    assert len(_snapshot_files()) == 1 and _messages(authorized) == []
    assert live_charts.commands(authorized)[0]["result"]["agent_world_receipt"]
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", original)
    assert live_charts.reconcile(authorized)["delivered"] == 1
    assert len(_snapshot_files()) == 1 and len(_messages(authorized)) == 1
    live_charts.reconcile(authorized)
    assert len(_messages(authorized)) == 1


def test_chat_append_then_index_failure_repairs_without_duplicate_result(authorized, monkeypatch):
    body = _body(_start(authorized))
    original = chief_agent._touch_conversation
    with monkeypatch.context() as patch:
        patch.setattr(chief_agent, "_touch_conversation", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("interrupted after append")))
        with pytest.raises(RuntimeError, match="interrupted after append"):
            live_charts.complete(body, authorized)
    assert chief_agent._touch_conversation is original
    out = live_charts.complete(body, authorized)
    assert out["report"]["idempotent_replay"] is True
    assert len(_snapshot_files()) == 1 and len(_messages(authorized)) == 1


def test_receipt_ack_failure_never_publishes_verified_without_durable_receipt(authorized, monkeypatch):
    started = _start(authorized)
    monkeypatch.setattr(market_data, "ack_chart_command", lambda *a, **k: {"acked": False, "command": None})
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", lambda envelope: pytest.fail("receipt must be durable before publish"))
    with pytest.raises(ContractError):
        live_charts.complete(_body(started), authorized)


def test_client_ack_cannot_overwrite_saved_server_receipt(authorized):
    started = _start(authorized)
    live_charts.complete(_body(started), authorized)
    before = copy.deepcopy(live_charts.commands(authorized)[0]["result"])
    for status in ("done", "failed", "skipped"):
        response = live_charts.acknowledge({"id": started["command_id"], "status": status,
                                          "result": {"agent_world_receipt": {"forged": True}, "error": "overwrite"}}, authorized)
        assert response["acked"] is True
        assert live_charts.commands(authorized)[0]["result"] == before


def test_plain_done_ack_without_saved_image_is_rejected(authorized):
    started = _start(authorized)
    with pytest.raises(ContractError, match="saved_receipt_required"):
        live_charts.acknowledge({"id": started["command_id"], "status": "done", "result": {"ok": True}}, authorized)
    assert live_charts.commands(authorized)[0]["status"] == "pending"


def test_failed_capture_ack_reconciles_a_blocked_message_not_success(authorized):
    started = _start(authorized)
    live_charts.acknowledge({"id": started["command_id"], "status": "failed", "result": {"error": "No rendered bars"}}, authorized)
    live_charts.reconcile(authorized)
    assert _messages(authorized)[0]["actions"][0]["status"] == "blocked"
    assert live_charts.details(authorized)[0]["task"]["status"] == "failed"
    assert _snapshot_files() == []


def test_failed_receipt_does_not_return_to_queued_after_command_pruning(authorized):
    started = _start(authorized)
    live_charts.acknowledge({"id": started["command_id"], "status": "failed", "result": {"error": "No rendered bars"}}, authorized)
    live_charts.reconcile(authorized)
    market_data._write(market_data._commands_path(), {"commands": []})
    assert live_charts.details(authorized)[0]["task"]["status"] in {"failed", "blocked"}


def test_completed_receipt_remains_visible_after_command_queue_pruning(authorized):
    started = _start(authorized)
    live_charts.complete(_body(started), authorized)
    market_data._write(market_data._commands_path(), {"commands": []})
    detail = live_charts.details(authorized)[0]
    assert detail["task"]["id"] == started["task_id"]
    assert detail["task"]["status"] == "succeeded" and detail["verification"]["passed"]


@pytest.mark.parametrize("change", ["missing", "tampered"])
def test_durable_chat_projection_detects_missing_or_changed_image(authorized, change):
    started = _start(authorized)
    out = live_charts.complete(_body(started), authorized)
    market_data._write(market_data._commands_path(), {"commands": []})
    path = market_data.snapshot_path(out["snapshot"]["file"])
    if change == "missing":
        path.unlink()
    else:
        path.write_bytes(b"changed locally in isolated test")
    detail = live_charts.details(authorized)[0]
    assert detail["task"]["status"] == "review" and not detail["verification"]["passed"]
    assert detail["errors"] and detail["task"]["evidence_count"] == 0


@pytest.mark.parametrize("image", ["", "data:image/png;base64,!!!!", "data:text/html;base64,PHNjcmlwdD4="])
def test_invalid_image_encoding_never_creates_receipt(authorized, image):
    body = {**_body(_start(authorized)), "image": image}
    with pytest.raises(ContractError):
        live_charts.complete(body, authorized)
    assert _snapshot_files() == [] and _messages(authorized) == []


def test_png_signature_with_junk_is_not_a_verified_image(authorized):
    fake = b"\x89PNG\r\n\x1a\nnot-png-dataIEND\xaeB`\x82"
    body = {**_body(_start(authorized)), "image": "data:image/png;base64," + base64.b64encode(fake).decode()}
    with pytest.raises(ContractError, match="invalid_chart_screenshot"):
        live_charts.complete(body, authorized)
    assert _snapshot_files() == []


def test_parallel_retry_has_one_saved_snapshot_and_one_receipt(authorized, monkeypatch):
    body = _body(_start(authorized))
    original = market_data.save_snapshot
    entered = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    calls = []
    def controlled_save(*args, **kwargs):
        with lock:
            calls.append(1)
            first = len(calls) == 1
        if first:
            entered.set()
            assert release.wait(5), "test failed to release first capture"
        return original(*args, **kwargs)
    monkeypatch.setattr(market_data, "save_snapshot", controlled_save)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(live_charts.complete, body, authorized)
        assert entered.wait(5)
        second = pool.submit(live_charts.complete, body, authorized)
        release.set()
        replies = [first.result(timeout=10), second.result(timeout=10)]
    assert len(calls) == 1
    assert replies[0]["snapshot"]["id"] == replies[1]["snapshot"]["id"]
    assert len(_snapshot_files()) == 1 and len(_messages(authorized)) == 1


def test_details_does_not_publish_or_expire_commands_on_read(authorized, monkeypatch):
    _start(authorized)
    doc = market_data._load_commands_doc()
    doc["commands"][0]["created_at_utc"] = "2020-01-01T00:00:00Z"
    market_data._write(market_data._commands_path(), doc)
    before = market_data._commands_path().read_bytes()
    monkeypatch.setattr(chief_agent, "report_agent_world_live_update", lambda envelope: pytest.fail("GET must not publish"))
    live_charts.details(authorized)
    assert market_data._commands_path().read_bytes() == before


def test_existing_monitor_expires_unfulfilled_capture_without_desktop_polling(authorized):
    _start(authorized)
    doc = market_data._load_commands_doc()
    doc["commands"][0]["created_at_utc"] = "2020-01-01T00:00:00Z"
    market_data._write(market_data._commands_path(), doc)
    live_charts.reconcile(authorized)
    assert live_charts.details(authorized)[0]["task"]["status"] in {"failed", "blocked"}
    assert _messages(authorized)[0]["actions"][0]["status"] == "blocked"


def test_revoked_admission_prevents_capture_write(authorized):
    started = _start(authorized)
    def denied():
        raise ContractError("access_revoked")
    authorized["admit"] = denied
    with pytest.raises(ContractError, match="access_revoked"):
        live_charts.complete(_body(started), authorized)
    assert _snapshot_files() == []
