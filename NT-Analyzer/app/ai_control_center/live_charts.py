"""Receipts for the existing Desktop command queue and scoped SF Chat store.

No headless renderer or alternate market-data source is used. A requested
snapshot stays pending until the real Desktop reports a saved image. Durable
receipt history is read from SF Chat, not a competing task/artifact database.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from uuid import UUID, uuid5

from .. import market_data
from .states import ContractError
from .http_api import decode_chart_png

_NAMESPACE = UUID("bbba699f-4c54-460a-926f-531e43bf58dc")
_CAPTURE_LOCK = threading.RLock()
PERSONA = {"id": "ivan", "key": "ivan", "display_name": "Иван", "role": "Рабочий стол и графики", "avatar_key": "ivan", "synthetic": False}


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _owned(row, authorized):
    if not isinstance(row, dict):
        return False
    payload, scope = row.get("payload") or {}, row.get("scope") or {}
    return (payload.get("agent_world") is True and payload.get("owner_user_uuid") == str(authorized["context"].user_uuid)
            and scope.get("workspace_id") == authorized["context"].scope.workspace_id
            and str(scope.get("user_id")) == str(authorized["source_scope"]["user_id"]))


def commands(authorized):
    authorized["admit"]()
    # Read only: list_chart_commands also expires rows, which belongs to the
    # existing command worker, not the AI Center GET projection.
    with market_data._LOCK:
        return [row for row in market_data._load_commands_doc().get("commands", []) if _owned(row, authorized)]


def start(*, message, authorized, conversation_id, request_id):
    match = re.search(r"\b([A-Z][A-Z0-9]{0,9})\s+(\d{2}-\d{2})\b", message)
    timeframe = re.search(r"\b([1-9]\d{0,3})\s*(?:m|мин(?:ут(?:ы)?)?)\b", message, re.I)
    if not match or not timeframe:
        raise ContractError("desktop_chart_explicit_instrument_timeframe_required")
    instrument, tf = match[1] + " " + match[2], timeframe[1] + "m"
    try:
        tf = market_data.normalize_timeframe(tf)
    except market_data.MarketDataError:
        raise ContractError("desktop_chart_supported_timeframe_required") from None
    from . import live_gateway
    live_gateway.access(authorized["chat_scope"])
    key = _sha([str(authorized["context"].user_uuid), authorized["context"].scope.workspace_id, request_id])
    request_sha = _sha([message, conversation_id])
    existing = next((row for row in commands(authorized) if (row.get("payload") or {}).get("request_key") == key), None)
    if existing and existing["payload"].get("request_sha256") != request_sha:
        raise ContractError("desktop_chart_idempotency_conflict")
    if not existing:
        authorized["admit"]()
        existing = market_data.enqueue_chart_command({"type": "snapshot", "instrument": instrument, "timeframe": tf,
                "conversation_id": conversation_id, "agent_id": "ivan", "scope": authorized["chat_scope"],
                "payload": {"agent_world": True, "fit": False, "mirror_to_telegram": False,
                            "request_key": key, "request_sha256": request_sha,
                            "owner_user_uuid": str(authorized["context"].user_uuid)},
                "note": "Снимок отображаемого графика; без headless подмены и без Telegram."})["command"]
    return {"status": "queued", "command_id": existing["id"], "task_id": str(uuid5(_NAMESPACE, existing["id"])),
            "verification": {"passed": False, "capture": {"instrument": instrument, "timeframe": tf}},
            "text": "Команда передана рабочему столу: " + instrument + " · " + tf
                    + ". Откройте «Рабочий стол» в этом Local. Дождусь реальных баров и снимка текущего вида; затем изображение появится в этом диалоге. Telegram не используется."}


def _capture(body, command):
    capture = body.get("capture")
    if not isinstance(capture, dict) or capture.get("surface") != "desktop_chart" or capture.get("view_preserved") is not True:
        raise ContractError("desktop_capture_required")
    if (body.get("conversation_id") != command.get("conversation_id") or body.get("instrument") != command.get("instrument")
            or body.get("timeframe") != command.get("timeframe") or capture.get("instrument") != command.get("instrument")
            or capture.get("timeframe") != command.get("timeframe") or body.get("mirror_to_telegram") is not False):
        raise ContractError("desktop_capture_context_mismatch")
    rendered, total = capture.get("rendered_bar_count"), capture.get("total_bar_count")
    if (type(rendered) is not int or type(total) is not int or not 0 < rendered <= total <= 1_000_000
            or not isinstance(capture.get("window_id"), str) or not 0 < len(capture["window_id"]) <= 160):
        raise ContractError("desktop_capture_bars_required")
    try:
        captured = datetime.fromisoformat(str(capture.get("captured_at_utc") or "").replace("Z", "+00:00"))
        if captured.tzinfo is None or abs((datetime.now(timezone.utc) - captured).total_seconds()) > 300:
            raise ValueError
    except (TypeError, ValueError):
        raise ContractError("desktop_capture_stale") from None
    # Bounded descriptive client observations, never permission/freshness grants.
    for key in ("series_hash", "first_bar_time_utc", "last_bar_time_utc", "provider_connection_state", "history_status", "transport"):
        if capture.get(key) is not None and (not isinstance(capture[key], str) or len(capture[key]) > 160):
            raise ContractError("desktop_capture_invalid_metadata")
    if capture.get("price_marker_live") is not None and type(capture["price_marker_live"]) is not bool:
        raise ContractError("desktop_capture_invalid_metadata")
    allowed = {"surface", "window_id", "instrument", "timeframe", "view_preserved", "captured_at_utc", "rendered_bar_count", "total_bar_count",
               "first_bar_time_utc", "last_bar_time_utc", "series_hash", "price_marker_live", "provider_connection_state", "history_status", "transport"}
    if set(capture) - allowed:
        raise ContractError("desktop_capture_invalid_metadata")
    return dict(capture)


def complete(body, authorized):
    # Serialize this Local capture/receipt only. Never hold the market-data
    # lock while entering chat: chat ingress queues commands in reverse order.
    with _CAPTURE_LOCK:
        return _complete_locked(body, authorized)


def _complete_locked(body, authorized):
    from ..ai_lab import chief_agent
    authorized["admit"]()
    command = next((row for row in commands(authorized) if row.get("id") == body.get("command_id")), None)
    if not command or command.get("type") != "snapshot":
        raise ContractError("desktop_command_scope_required")
    # Browser retry after an uncertain response must not save another image or
    # append another result. The existing queue keeps the saved receipt.
    saved_receipt = (command.get("result") or {}).get("agent_world_receipt")
    if isinstance(saved_receipt, dict) and saved_receipt.get("command_id") == command["id"]:
        report = chief_agent.report_agent_world_live_update(saved_receipt["envelope"])
        return {"ok": True, "command_id": command["id"], "snapshot": saved_receipt["snapshot"], "report": report}
    if command.get("status") != "pending":
        raise ContractError("desktop_command_not_pending")
    capture = _capture(body, command)
    image = body.get("image")
    content = decode_chart_png(image)
    saved = market_data.save_snapshot(image, meta={"instrument": command["instrument"], "timeframe": command["timeframe"],
                                                  "conversation_id": command["conversation_id"], "outcome": "agent_world_desktop"})
    digest = hashlib.sha256(content).hexdigest()
    verification = {"passed": True, "state": "verified", "synthetic": False, "source_kind": "desktop_chart",
                    "snapshot_sha256": digest, "snapshot": saved, "capture": capture,
                    "provenance": "authenticated_desktop_canvas_receipt", "model_quality_assessed": False}
    envelope = {"request_id": "aw.desktop." + command["id"], "conversation_id": command["conversation_id"],
                "scope": authorized["chat_scope"], "agent_id": "ivan", "agent_name": "Иван",
                "task_id": str(uuid5(_NAMESPACE, command["id"])), "command_id": command["id"], "synthetic": False,
                "source_kind": "desktop_chart", "status": "completed", "verification": verification,
                "text": "Снимок рабочего стола: " + command["instrument"] + " · " + command["timeframe"]
                        + ". Отображаемых баров: " + str(capture["rendered_bar_count"]) + " из " + str(capture["total_bar_count"])
                        + ". Текущий вид сохранён. Изображение приложено.\nSHA256: " + digest
                        + "\nЭто снимок реального Desktop; он не доказывает, что котировки поступают прямо сейчас. Качество LLM не оценивалось.",
                "attachments": [{"type": "image", "url": saved["url"], "caption": command["instrument"] + " · " + command["timeframe"]}]}
    receipt = {"command_id": command["id"], "snapshot": saved, "envelope": envelope}
    # Persist the receipt before chat append: a retry recovers publication from
    # this same authoritative command result, even after process restart.
    acknowledged = market_data.ack_chart_command(command["id"], status="done", result={"ok": True, "agent_world_receipt": receipt})
    if not acknowledged.get("acked"):
        raise ContractError("desktop_saved_receipt_required")
    report = chief_agent.report_agent_world_live_update(envelope)
    return {"ok": True, "command_id": command["id"], "snapshot": saved, "report": report}


def acknowledge(body, authorized):
    command = next((row for row in commands(authorized) if row.get("id") == body.get("id")), None)
    if not command:
        raise ContractError("desktop_command_scope_required")
    receipt = (command.get("result") or {}).get("agent_world_receipt")
    if receipt:
        # Browser ACK must not overwrite the server-verified receipt with a
        # smaller arbitrary client result. The server already recorded done.
        return {"acked": True, "id": command["id"], "command": command}
    if body.get("status") == "done":
        raise ContractError("desktop_saved_receipt_required")
    return market_data.ack_chart_command(command["id"], status="failed", result={"ok": False, "error": str((body.get("result") or {}).get("error") or "Desktop capture failed")[:300]})


def reconcile(authorized):
    from ..ai_lab import chief_agent
    authorized["admit"]()
    market_data.list_chart_commands(status="all")  # existing TTL/expiry authority; never called by GET
    delivered = 0
    for command in commands(authorized):
        receipt = (command.get("result") or {}).get("agent_world_receipt")
        if receipt:
            authorized["admit"]()
            chief_agent.report_agent_world_live_update(receipt["envelope"])
            delivered += 1
        elif command.get("status") in {"failed", "expired"}:
            chief_agent.report_agent_world_live_update({
                "request_id": "aw.desktop." + command["id"] + "." + command["status"],
                "conversation_id": command["conversation_id"], "scope": authorized["chat_scope"],
                "agent_id": "ivan", "agent_name": "Иван", "task_id": str(uuid5(_NAMESPACE, command["id"])),
                "command_id": command["id"], "synthetic": False, "source_kind": "desktop_chart", "status": "blocked",
                "text": "Снимок рабочего стола не получен: " + str((command.get("result") or {}).get("error") or command["status"])
                        + ". Откройте рабочий стол, дождитесь баров и повторите поручение.",
            })
    return {"delivered": delivered}


def details(authorized, *, command_id=None):
    from ..ai_lab import chief_agent
    if command_id is not None and not re.fullmatch(r"cc_[0-9a-f]{32}", str(command_id)):
        raise ContractError("desktop_command_scope_required")
    pending = {row["id"]: row for row in commands(authorized) if command_id is None or row["id"] == command_id}
    receipts = {}
    for row in chief_agent.agent_world_live_messages(scope=authorized["chat_scope"]):
        for action in row.get("actions") or []:
            if (action.get("source_kind") == "desktop_chart"
                    and re.fullmatch(r"cc_[0-9a-f]{32}", str(action.get("command_id") or ""))
                    and (command_id is None or action.get("command_id") == command_id)):
                receipts[action["command_id"]] = (row, action)
    result = []
    for command_id in set(pending) | set(receipts):
        command = pending.get(command_id) or {}
        row, action = receipts.get(command_id, ({}, {}))
        verification = action.get("verification") or {}
        saved = verification.get("snapshot") or {}
        capture = verification.get("capture") or {}
        verified = verification.get("passed") is True
        if verified:
            path = market_data.snapshot_path(saved.get("file"))
            verified = bool(path and not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest() == verification.get("snapshot_sha256"))
        state = "succeeded" if verified else "review" if saved else "failed" if command.get("status") in {"failed", "expired"} or action.get("status") in {"blocked", "failed"} else "queued"
        instrument, timeframe = command.get("instrument") or capture.get("instrument"), command.get("timeframe") or capture.get("timeframe")
        title = "Снимок Desktop · " + str(instrument or "") + " · " + str(timeframe or "")
        task_id = str(uuid5(_NAMESPACE, command_id))
        task = {"id": task_id, "title": title, "status": state, "stage": "Изображение проверено" if verified else "Ожидание/проверка снимка Desktop",
                "summary": str(row.get("content") or command.get("note") or ""), "lead": dict(PERSONA), "participants": [dict(PERSONA)],
                "created_at": command.get("created_at_utc") or row.get("timestamp_utc"), "updated_at": row.get("timestamp_utc") or command.get("created_at_utc"),
                "progress_pct": 100 if verified else None, "cost_usd": None, "synthetic": False, "source_kind": "desktop_chart",
                "command_id": command_id, "conversation_id": command.get("conversation_id") or row.get("conversation_id"), "evidence_count": 1 if verified else 0}
        artifact = {"id": saved.get("id"), "title": title, "url": saved.get("url"), "media_type": saved.get("mime"),
                    "sha256": verification.get("snapshot_sha256"), "synthetic": False, "source_kind": "desktop_chart"} if saved else None
        result.append({"task": task, "result_text": task["summary"], "activity": [], "contributions": [], "evaluations": [], "decisions": [],
                       "artifacts": [artifact] if artifact else [], "outcomes": [], "verification": {**verification, "passed": verified},
                       "errors": [] if verified or not saved else [{"message": "Сохранённый снимок отсутствует или изменился; повторите capture."}]})
    return sorted(result, key=lambda item: str(item["task"]["updated_at"] or ""), reverse=True)[:100]
