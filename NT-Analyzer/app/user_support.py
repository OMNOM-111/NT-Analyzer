"""Consent-based user support, session commands and browser telemetry.

The browser security model intentionally prevents silent desktop capture and
system-wide CPU/memory inspection.  This module therefore coordinates explicit
one-time screen-share consent and stores only browser-tab telemetry reported by
the authenticated client.  Completed screenshots are encrypted with Windows
DPAPI and expire automatically.
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from . import account_auth, secure_store


_LOCK = threading.RLock()
_SCREENSHOT_MAGIC = b"NTA-SUPPORT-SCREENSHOT-1\n"
_MAX_SCREENSHOT_BYTES = 700 * 1024
_REQUEST_TTL_SEC = 10 * 60
_SCREENSHOT_RETENTION_SEC = 24 * 60 * 60
_ONLINE_SEC = 35


class UserSupportError(RuntimeError):
    """Safe-to-display support operation error."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _store_path() -> Path:
    return _root() / "data" / "runtime" / "user-support.json"


def _screenshots_dir() -> Path:
    return _root() / "data" / "runtime" / "support-screenshots"


def _audit_path() -> Path:
    return _root() / "data" / "audit" / "user-support.jsonl"


def _now_iso(epoch: Optional[float] = None) -> str:
    return datetime.fromtimestamp(epoch or time.time(), timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _blank() -> Dict[str, Any]:
    return {"version": 1, "commands": [], "screenshot_requests": [], "telemetry": {}, "device_names": {}}


def _load() -> Dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return _blank()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _blank()
    if not isinstance(doc, dict):
        return _blank()
    out = _blank()
    for key in out:
        if isinstance(doc.get(key), type(out[key])):
            out[key] = doc[key]
    return out


def _save(doc: Dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def _audit(event: str, **values: Any) -> None:
    row = {"timestamp": _now_iso(), "event": str(event or "support_event")}
    row.update({key: value for key, value in values.items() if value not in (None, "")})
    path = _audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _safe_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:20]


def _number(value: Any, low: float, high: float, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return max(low, min(high, result))


def _client_id(value: Any) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.:-]", "", str(value or ""))[:96]
    if len(clean) < 8:
        raise UserSupportError("Некорректный идентификатор клиентской сессии.")
    return clean


def _require_owner(owner_id: Any) -> list[Dict[str, Any]]:
    try:
        return list(account_auth.list_users(owner_id).get("users") or [])
    except account_auth.AccountAuthError as exc:
        raise UserSupportError(str(exc), exc.status) from None


def _target_user(owner_id: Any, user_id: Any, *, active: bool = False,
                 allow_owner: bool = True) -> Dict[str, Any]:
    users = _require_owner(owner_id)
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        raise UserSupportError("Некорректный пользователь.") from None
    user = next((row for row in users if int(row.get("user_id") or 0) == uid), None)
    if user is None:
        raise UserSupportError("Пользователь не найден.", 404)
    if user.get("is_owner") and not allow_owner:
        raise UserSupportError("Эта команда предназначена для пользовательских сессий.")
    if active and user.get("status") != "active":
        raise UserSupportError("Пользователь сейчас не активен.", 409)
    return user


def _screenshot_path(request_id: str) -> Path:
    rid = re.sub(r"[^A-Za-z0-9_-]", "", str(request_id or ""))
    if not rid or rid != str(request_id or ""):
        raise UserSupportError("Некорректный идентификатор снимка.")
    return _screenshots_dir() / f"{rid}.dpapi"


def _cleanup(doc: Dict[str, Any]) -> bool:
    now = time.time()
    changed = False
    for row in doc.get("screenshot_requests") or []:
        status = str(row.get("status") or "")
        if status in {"pending", "claimed"} and float(row.get("expires_at") or 0) <= now:
            row["status"] = "expired"
            row["resolved_at_utc"] = _now_iso(now)
            changed = True
        if status == "completed" and float(row.get("retained_until") or 0) <= now:
            try:
                _screenshot_path(str(row.get("request_id") or "")).unlink(missing_ok=True)
            except OSError:
                pass
            row["status"] = "deleted"
            row["deleted_at_utc"] = _now_iso(now)
            changed = True
    telemetry = doc.get("telemetry") if isinstance(doc.get("telemetry"), dict) else {}
    for uid in list(telemetry):
        clients = telemetry.get(uid) if isinstance(telemetry.get(uid), dict) else {}
        for cid in list(clients):
            if now - float((clients.get(cid) or {}).get("reported_at") or 0) > 7 * 24 * 3600:
                clients.pop(cid, None)
                changed = True
        if not clients:
            telemetry.pop(uid, None)
    doc["commands"] = list(doc.get("commands") or [])[-200:]
    doc["screenshot_requests"] = list(doc.get("screenshot_requests") or [])[-100:]
    return changed


def request_screenshot(owner_id: Any, user_id: Any, *, note: str = "",
                       target_client_id: str = "",
                       conversation_id: str = "",
                       owner_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user = _target_user(owner_id, user_id, active=True)
    now = time.time()
    target_client = str(target_client_id or "").strip()
    if target_client:
        target_client = _client_id(target_client)
        with _LOCK:
            current = _load()
            live = ((current.get("telemetry") or {}).get(str(user["user_id"]), {}) or {}).get(target_client) or {}
        if now - float(live.get("reported_at") or 0) > _ONLINE_SEC:
            raise UserSupportError("Выбранное устройство сейчас не в сети.", 409)
    row: Dict[str, Any] = {
        "request_id": _safe_id("screen_"),
        "owner_id": int(owner_id),
        "user_id": int(user["user_id"]),
        "status": "pending",
        "note": str(note or "")[:300],
        "created_at_utc": _now_iso(now),
        "expires_at_utc": _now_iso(now + _REQUEST_TTL_SEC),
        "expires_at": now + _REQUEST_TTL_SEC,
        "conversation_id": str(conversation_id or "")[:100],
        "target_client_id": target_client,
    }
    if owner_scope and conversation_id:
        allowed = {
            "user_id", "workspace_id", "workspace_kind", "uses_owner_runtime",
            "runtime_dir", "membership_role", "is_owner", "display_name",
        }
        row["owner_scope"] = {key: owner_scope.get(key) for key in allowed if key in owner_scope}
    with _LOCK:
        doc = _load()
        _cleanup(doc)
        doc["screenshot_requests"].append(row)
        _save(doc)
    _audit("screenshot_requested", owner_id=int(owner_id), user_id=int(user["user_id"]), request_id=row["request_id"])
    return {"ok": True, "request": _public_request(row)}


def queue_reload(owner_id: Any, user_id: Any, *, session_id: str = "",
                 client_id: str = "", all_sessions: bool = False) -> Dict[str, Any]:
    user = _target_user(owner_id, user_id, active=True)
    uid = int(user["user_id"])
    try:
        sessions = list((account_auth.user_detail(owner_id, uid).get("user") or {}).get("active_sessions") or [])
    except account_auth.AccountAuthError as exc:
        raise UserSupportError(str(exc), exc.status) from None
    wanted = str(session_id or "").strip()
    wanted_client = str(client_id or "").strip()
    if wanted and not any(str(row.get("session_id") or "") == wanted for row in sessions):
        raise UserSupportError("Активная сессия не найдена.", 404)
    now = time.time()
    with _LOCK:
        current = _load()
        live_clients = [
            row for row in ((current.get("telemetry") or {}).get(str(uid), {}) or {}).values()
            if now - float((row or {}).get("reported_at") or 0) <= _ONLINE_SEC
        ]
    if wanted_client and not any(str(row.get("client_id") or "") == wanted_client for row in live_clients):
        raise UserSupportError("Активная клиентская сессия не найдена.", 404)
    targets: list[tuple[str, str]] = []
    if all_sessions:
        targets.extend((str(row.get("session_id") or ""), "") for row in sessions)
        known_sessions = {session for session, _client in targets if session}
        targets.extend(
            (str(row.get("session_id") or ""), str(row.get("client_id") or ""))
            for row in live_clients
            if not row.get("session_id") or str(row.get("session_id")) not in known_sessions
        )
    else:
        targets = [(wanted, wanted_client)]
    targets = list(dict.fromkeys((session, client) for session, client in targets if session or client))
    if not targets:
        raise UserSupportError("У пользователя нет активной сессии приложения.", 409)
    commands = [{
        "command_id": _safe_id("cmd_"), "owner_id": int(owner_id), "user_id": uid,
        "type": "reload", "status": "pending", "target_session_id": target_session,
        "target_client_id": target_client,
        "created_at_utc": _now_iso(now), "expires_at": now + 120,
    } for target_session, target_client in targets]
    with _LOCK:
        doc = _load()
        _cleanup(doc)
        doc["commands"].extend(commands)
        _save(doc)
    _audit("session_reload_queued", owner_id=int(owner_id), user_id=uid, count=len(commands))
    return {"ok": True, "queued": len(commands), "commands": [_public_command(row) for row in commands]}


def record_telemetry(user_id: Any, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    uid = int(user_id)
    cid = _client_id(payload.get("client_id"))
    now = time.time()
    device_id = re.sub(r"[^A-Za-z0-9_.:-]", "", str(payload.get("device_id") or ""))[:96]
    if len(device_id) < 8:
        device_id = cid
    proposed_name = " ".join(str(payload.get("device_name") or "").strip().split())[:64] or "Устройство"
    row = {
        "client_id": cid,
        "user_id": uid,
        "session_id": str(session_id or "")[:80],
        "device_id": device_id,
        "device_name": proposed_name,
        "platform": str(payload.get("platform") or "")[:60],
        "client": str(payload.get("client") or "")[:60],
        "reported_at": now,
        "reported_at_utc": _now_iso(now),
        "page": str(payload.get("page") or "")[:160],
        "visible": bool(payload.get("visible", True)),
        "logical_cores": int(_number(payload.get("logical_cores"), 0, 256)),
        "device_memory_gb": _number(payload.get("device_memory_gb"), 0, 1024),
        "cpu_main_thread_percent": _number(payload.get("cpu_main_thread_percent"), 0, 100),
        "cpu_core_equivalent": _number(payload.get("cpu_core_equivalent"), 0, 1),
        "js_heap_used_mb": _number(payload.get("js_heap_used_mb"), 0, 1024 * 1024),
        "js_heap_limit_mb": _number(payload.get("js_heap_limit_mb"), 0, 1024 * 1024),
        "network_mb_per_min": _number(payload.get("network_mb_per_min"), 0, 1024 * 1024),
        "network_total_mb": _number(payload.get("network_total_mb"), 0, 1024 * 1024),
        "downlink_mbps": _number(payload.get("downlink_mbps"), 0, 100000),
        "rtt_ms": _number(payload.get("rtt_ms"), 0, 600000),
        "effective_type": str(payload.get("effective_type") or "")[:20],
        "memory_available": bool(payload.get("memory_available")),
        "cpu_available": bool(payload.get("cpu_available")),
    }
    with _LOCK:
        doc = _load()
        _cleanup(doc)
        custom_name = str(((doc.get("device_names") or {}).get(str(uid), {}) or {}).get(device_id) or "").strip()
        if custom_name:
            row["device_name"] = custom_name
        telemetry = doc.setdefault("telemetry", {}).setdefault(str(uid), {})
        telemetry[cid] = row
        _save(doc)
    return {"ok": True, "reported_at_utc": row["reported_at_utc"]}


def poll(user_id: Any, session_id: str, client_id: Any) -> Dict[str, Any]:
    uid = int(user_id)
    cid = _client_id(client_id)
    now = time.time()
    with _LOCK:
        doc = _load()
        changed = _cleanup(doc)
        commands = []
        for row in doc.get("commands") or []:
            if int(row.get("user_id") or 0) != uid or row.get("status") != "pending":
                continue
            if float(row.get("expires_at") or 0) <= now:
                row["status"] = "expired"; changed = True; continue
            target = str(row.get("target_session_id") or "")
            if target and target != str(session_id or ""):
                continue
            target_client = str(row.get("target_client_id") or "")
            if target_client and target_client != cid:
                continue
            row["status"] = "delivered"
            row["delivered_to"] = cid
            row["delivered_at_utc"] = _now_iso(now)
            commands.append(_public_command(row))
            changed = True
        screenshot = None
        for row in reversed(doc.get("screenshot_requests") or []):
            if int(row.get("user_id") or 0) != uid:
                continue
            target_client = str(row.get("target_client_id") or "")
            if target_client and target_client != cid:
                continue
            if row.get("status") == "pending":
                row["status"] = "claimed"
                row["claimed_by"] = cid
                row["claimed_session_id"] = str(session_id or "")[:80]
                row["claimed_at_utc"] = _now_iso(now)
                changed = True
            if row.get("status") == "claimed" and str(row.get("claimed_by") or "") == cid:
                screenshot = _public_request(row)
                break
        if changed:
            _save(doc)
    return {"ok": True, "commands": commands, "screenshot_request": screenshot}


def ack_command(user_id: Any, client_id: Any, command_id: Any, *, status: str = "done",
                error: str = "") -> Dict[str, Any]:
    uid = int(user_id)
    cid = _client_id(client_id)
    final = "done" if status == "done" else "error"
    with _LOCK:
        doc = _load()
        row = next((item for item in doc.get("commands") or [] if str(item.get("command_id") or "") == str(command_id or "")), None)
        if row is None or int(row.get("user_id") or 0) != uid:
            raise UserSupportError("Команда не найдена.", 404)
        if row.get("status") not in {"delivered", final} or str(row.get("delivered_to") or "") != cid:
            raise UserSupportError("Команда принадлежит другой клиентской сессии.", 409)
        row["status"] = final
        row["resolved_at_utc"] = _now_iso()
        row["error"] = str(error or "")[:300]
        _save(doc)
    return {"ok": True, "command": _public_command(row)}


def _decode_image(data_url: str) -> tuple[bytes, str]:
    match = re.fullmatch(r"data:image/(png|jpeg);base64,([A-Za-z0-9+/=\r\n]+)", str(data_url or ""), flags=re.IGNORECASE)
    if not match:
        raise UserSupportError("Поддерживаются только PNG/JPEG снимки.")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except ValueError:
        raise UserSupportError("Снимок повреждён.") from None
    kind = match.group(1).lower()
    if len(raw) > _MAX_SCREENSHOT_BYTES:
        raise UserSupportError("Снимок слишком большой; уменьшите выбранную область.", 413)
    if (kind == "png" and not raw.startswith(b"\x89PNG\r\n\x1a\n")) or (kind == "jpeg" and not raw.startswith(b"\xff\xd8\xff")):
        raise UserSupportError("Формат снимка не подтверждён.")
    return raw, ("image/png" if kind == "png" else "image/jpeg")


def respond_screenshot(user_id: Any, client_id: Any, request_id: Any, *, decision: str,
                       data_url: str = "", width: Any = 0, height: Any = 0,
                       error: str = "") -> Dict[str, Any]:
    uid = int(user_id)
    cid = _client_id(client_id)
    decision = str(decision or "").lower()
    if decision not in {"approved", "denied", "error"}:
        raise UserSupportError("Некорректное решение по снимку.")
    raw = b""
    content_type = ""
    if decision == "approved":
        if not secure_store.available():
            raise UserSupportError("Защищённое хранилище DPAPI недоступно; снимок не сохранён.", 503)
        raw, content_type = _decode_image(data_url)
    with _LOCK:
        doc = _load()
        _cleanup(doc)
        row = next((item for item in doc.get("screenshot_requests") or [] if str(item.get("request_id") or "") == str(request_id or "")), None)
        if row is None or int(row.get("user_id") or 0) != uid:
            raise UserSupportError("Запрос снимка не найден.", 404)
        if row.get("status") != "claimed" or str(row.get("claimed_by") or "") != cid:
            raise UserSupportError("Запрос уже обработан или открыт на другом устройстве.", 409)
        now = time.time()
        if decision == "approved":
            try:
                encrypted = secure_store._protect(raw)
                path = _screenshot_path(str(row["request_id"]))
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_bytes(_SCREENSHOT_MAGIC + base64.b64encode(encrypted))
                os.replace(tmp, path)
            except (OSError, secure_store.SecureStoreError) as exc:
                raise UserSupportError(f"Не удалось защищённо сохранить снимок: {exc}", 503) from None
            row.update({
                "status": "completed", "content_type": content_type,
                "size_bytes": len(raw), "width": int(_number(width, 0, 20000)),
                "height": int(_number(height, 0, 20000)),
                "retained_until": now + _SCREENSHOT_RETENTION_SEC,
                "retained_until_utc": _now_iso(now + _SCREENSHOT_RETENTION_SEC),
            })
        else:
            row["status"] = "denied" if decision == "denied" else "error"
            row["error"] = str(error or "")[:300]
        row["resolved_at_utc"] = _now_iso(now)
        _save(doc)
        private = dict(row)
    _audit(f"screenshot_{row['status']}", owner_id=row.get("owner_id"), user_id=uid, request_id=row.get("request_id"))
    return {"ok": True, "request": _public_request(row), "private_request": private}


def _public_command(row: Dict[str, Any]) -> Dict[str, Any]:
    return {key: row.get(key) for key in (
        "command_id", "type", "status", "target_session_id", "target_client_id", "created_at_utc",
        "delivered_at_utc", "resolved_at_utc", "error",
    ) if row.get(key) not in (None, "")}


def _public_request(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {key: row.get(key) for key in (
        "request_id", "user_id", "status", "note", "created_at_utc",
        "expires_at_utc", "claimed_at_utc", "resolved_at_utc",
        "retained_until_utc", "content_type", "size_bytes", "width", "height", "error", "target_client_id",
    ) if row.get(key) not in (None, "")}
    if row.get("status") == "completed":
        out["image_url"] = f"/api/owner/support/screenshots/{row.get('request_id')}"
    return out


def _alerts(row: Dict[str, Any]) -> list[Dict[str, str]]:
    alerts = []
    cpu = float(row.get("cpu_main_thread_percent") or 0)
    heap = float(row.get("js_heap_used_mb") or 0)
    heap_limit = float(row.get("js_heap_limit_mb") or 0)
    network = float(row.get("network_mb_per_min") or 0)
    if row.get("cpu_available") and cpu >= 80:
        alerts.append({"kind": "cpu", "severity": "critical" if cpu >= 95 else "warning", "message": f"Главный поток вкладки занят на {cpu:.0f}%"})
    if row.get("memory_available") and ((heap_limit > 0 and heap / heap_limit >= .85) or heap >= 1024):
        alerts.append({"kind": "memory", "severity": "critical" if heap_limit and heap / heap_limit >= .95 else "warning", "message": f"JS-память вкладки {heap:.0f} МБ"})
    if network >= 50:
        alerts.append({"kind": "network", "severity": "critical" if network >= 200 else "warning", "message": f"Сетевой трафик {network:.1f} МБ/мин"})
    return alerts


def _public_telemetry(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {key: row.get(key) for key in (
        "client_id", "session_id", "reported_at_utc", "page", "visible",
        "device_id", "device_name", "platform", "client",
        "logical_cores", "device_memory_gb", "cpu_main_thread_percent",
        "cpu_core_equivalent", "js_heap_used_mb", "js_heap_limit_mb",
        "network_mb_per_min", "network_total_mb", "downlink_mbps", "rtt_ms",
        "effective_type", "memory_available", "cpu_available",
    )}
    out["online"] = time.time() - float(row.get("reported_at") or 0) <= _ONLINE_SEC
    out["alerts"] = _alerts(row) if out["online"] else []
    return out


def owner_status(owner_id: Any, user_id: Any) -> Dict[str, Any]:
    user = _target_user(owner_id, user_id)
    uid = int(user["user_id"])
    try:
        auth_sessions = list((account_auth.user_detail(owner_id, uid).get("user") or {}).get("active_sessions") or [])
    except account_auth.AccountAuthError as exc:
        raise UserSupportError(str(exc), exc.status) from None
    with _LOCK:
        doc = _load()
        if _cleanup(doc):
            _save(doc)
        rows = list((doc.get("telemetry") or {}).get(str(uid), {}).values())
        requests = [_public_request(row) for row in reversed(doc.get("screenshot_requests") or []) if int(row.get("user_id") or 0) == uid][:20]
        commands = [_public_command(row) for row in reversed(doc.get("commands") or []) if int(row.get("user_id") or 0) == uid][:20]
    sessions = sorted((_public_telemetry(row) for row in rows), key=lambda row: str(row.get("reported_at_utc") or ""), reverse=True)
    telemetry_by_session = {str(row.get("session_id") or ""): row for row in sessions if row.get("session_id")}
    for auth_session in auth_sessions:
        live = telemetry_by_session.get(str(auth_session.get("session_id") or "")) or {}
        auth_session["support_device_id"] = str(live.get("device_id") or "")
        auth_session["device_name"] = str(live.get("device_name") or "Не переименованное устройство")
    alerts = [dict(alert, client_id=row.get("client_id")) for row in sessions for alert in row.get("alerts") or []]
    return {
        "ok": True, "user_id": uid, "sessions": sessions, "online": any(row.get("online") for row in sessions),
        "alerts": alerts, "auth_sessions": auth_sessions, "screenshot_requests": requests, "commands": commands,
        "telemetry_note": "Показатели относятся к вкладке приложения. Системные CPU/RAM других программ браузер не раскрывает.",
        "screenshot_retention_hours": int(_SCREENSHOT_RETENTION_SEC / 3600),
    }


def owner_overview(owner_id: Any) -> Dict[str, Any]:
    users = list(_require_owner(owner_id))
    items = []
    for user in users:
        status = owner_status(owner_id, user.get("user_id"))
        online = [row for row in status["sessions"] if row.get("online")]
        items.append({
            "user_id": int(user["user_id"]), "online": bool(online), "session_count": len(online),
            "cpu_main_thread_percent": max((float(row.get("cpu_main_thread_percent") or 0) for row in online), default=0),
            "js_heap_used_mb": sum(float(row.get("js_heap_used_mb") or 0) for row in online),
            "network_mb_per_min": sum(float(row.get("network_mb_per_min") or 0) for row in online),
            "alert_count": len(status["alerts"]),
        })
    return {"ok": True, "users": items, "online_count": sum(1 for row in items if row["online"]), "alert_count": sum(row["alert_count"] for row in items)}


def screenshot_bytes(owner_id: Any, request_id: Any) -> tuple[bytes, str]:
    _require_owner(owner_id)
    rid = str(request_id or "")
    with _LOCK:
        doc = _load()
        if _cleanup(doc):
            _save(doc)
        row = next((item for item in doc.get("screenshot_requests") or [] if str(item.get("request_id") or "") == rid), None)
    if row is None or row.get("status") != "completed":
        raise UserSupportError("Снимок не найден или уже удалён.", 404)
    try:
        payload = _screenshot_path(rid).read_bytes()
        if not payload.startswith(_SCREENSHOT_MAGIC):
            raise ValueError("unknown format")
        encrypted = base64.b64decode(payload[len(_SCREENSHOT_MAGIC):], validate=True)
        raw = secure_store._unprotect(encrypted)
    except (OSError, ValueError, secure_store.SecureStoreError) as exc:
        raise UserSupportError(f"Не удалось открыть защищённый снимок: {exc}", 503) from None
    return raw, str(row.get("content_type") or "image/jpeg")


def delete_screenshot(owner_id: Any, request_id: Any) -> Dict[str, Any]:
    _require_owner(owner_id)
    rid = str(request_id or "")
    with _LOCK:
        doc = _load()
        row = next((item for item in doc.get("screenshot_requests") or [] if str(item.get("request_id") or "") == rid), None)
        if row is None:
            raise UserSupportError("Снимок не найден.", 404)
        try:
            _screenshot_path(rid).unlink(missing_ok=True)
        except OSError as exc:
            raise UserSupportError(f"Не удалось удалить снимок: {exc}", 500) from None
        row["status"] = "deleted"
        row["deleted_at_utc"] = _now_iso()
        _save(doc)
    _audit("screenshot_deleted", owner_id=int(owner_id), user_id=row.get("user_id"), request_id=rid)
    return {"ok": True, "request": _public_request(row)}


def purge_user(owner_id: Any, user_id: Any) -> Dict[str, Any]:
    """Remove support metadata and encrypted captures before account deletion."""
    user = _target_user(owner_id, user_id, allow_owner=False)
    uid = int(user["user_id"])
    deleted = 0
    with _LOCK:
        doc = _load()
        for row in doc.get("screenshot_requests") or []:
            if int(row.get("user_id") or 0) != uid:
                continue
            try:
                _screenshot_path(str(row.get("request_id") or "")).unlink(missing_ok=True)
                deleted += 1
            except OSError:
                pass
        doc["screenshot_requests"] = [row for row in doc.get("screenshot_requests") or [] if int(row.get("user_id") or 0) != uid]
        doc["commands"] = [row for row in doc.get("commands") or [] if int(row.get("user_id") or 0) != uid]
        doc.setdefault("telemetry", {}).pop(str(uid), None)
        doc.setdefault("device_names", {}).pop(str(uid), None)
        _save(doc)
    _audit("support_data_purged", owner_id=int(owner_id), user_id=uid, count=deleted)
    return {"ok": True, "user_id": uid, "screenshots_deleted": deleted}


def rename_device(owner_id: Any, user_id: Any, device_id: Any, name: Any) -> Dict[str, Any]:
    """Assign an owner-visible label to a browser/device without reconnecting it."""
    user = _target_user(owner_id, user_id)
    uid = int(user["user_id"])
    did = re.sub(r"[^A-Za-z0-9_.:-]", "", str(device_id or ""))[:96]
    label = " ".join(str(name or "").strip().split())
    if len(did) < 8:
        raise UserSupportError("Некорректный идентификатор устройства.")
    if not 1 <= len(label) <= 64 or any(ord(ch) < 32 for ch in label):
        raise UserSupportError("Имя устройства должно содержать от 1 до 64 символов.")
    with _LOCK:
        doc = _load()
        clients = (doc.get("telemetry") or {}).get(str(uid), {}) or {}
        matching = [row for row in clients.values() if str((row or {}).get("device_id") or "") == did]
        if not matching:
            raise UserSupportError("Устройство ещё не передавало телеметрию.", 404)
        doc.setdefault("device_names", {}).setdefault(str(uid), {})[did] = label
        for row in matching:
            row["device_name"] = label
        _save(doc)
    _audit("device_renamed", owner_id=int(owner_id), user_id=uid, device_id=did)
    return {"ok": True, "user_id": uid, "device_id": did, "device_name": label}


def _resolve_chat_user(owner_id: Any, message: str) -> tuple[Optional[Dict[str, Any]], list[Dict[str, Any]]]:
    users = [row for row in _require_owner(owner_id) if not row.get("is_owner")]
    text = str(message or "").lower()
    match = re.search(r"(?:\bid\b|айди|user|пользовател(?:ю|я)?)\s*[#№:]?\s*(\d{1,20})", text, flags=re.IGNORECASE)
    if match:
        uid = int(match.group(1))
        return next((row for row in users if int(row.get("user_id") or 0) == uid), None), users
    matches = []
    for row in users:
        values: Iterable[str] = (
            " ".join(str(row.get(key) or "").strip() for key in ("first_name", "last_name")).strip(),
            str(row.get("first_name") or "").strip(),
            str(row.get("last_name") or "").strip(),
            str(row.get("username") or "").strip().lstrip("@"),
            str(row.get("email") or "").strip(),
        )
        if any(len(value) >= 3 and value.lower() in text for value in values):
            matches.append(row)
    return (matches[0] if len(matches) == 1 else None), users


def chat_command(action: str, owner_id: Any, message: str, *, conversation_id: str = "",
                 owner_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user, users = _resolve_chat_user(owner_id, message)
    if user is None:
        choices = ", ".join(
            f"{' '.join(filter(None, [str(row.get('first_name') or ''), str(row.get('last_name') or '')])).strip() or row.get('username') or 'Пользователь'} (ID {row.get('user_id')})"
            for row in users[:8]
        ) or "активных пользователей нет"
        return {"ok": True, "needs_input": True, "reply": f"Уточните пользователя по имени или ID. Доступны: {choices}.", "actions": [{"name": action, "status": "needs_input", "reason": "user_not_resolved"}]}
    uid = int(user["user_id"])
    label = " ".join(filter(None, [str(user.get("first_name") or ""), str(user.get("last_name") or "")])).strip() or str(user.get("username") or uid)
    if action == "user_screenshot_request":
        out = request_screenshot(owner_id, uid, note="Запрос из чата владельца", conversation_id=conversation_id, owner_scope=owner_scope)
        rid = out["request"]["request_id"]
        return {"ok": True, "reply": f"Запросил снимок экрана у {label} (ID {uid}). Пользователь увидит подтверждение, затем системный выбор экрана; без его согласия снимок не создаётся.", "actions": [{"name": action, "status": "waiting_for_user_consent", "request_id": rid, "user_id": uid}]}
    if action == "user_session_reload":
        out = queue_reload(owner_id, uid, all_sessions=True)
        return {"ok": True, "reply": f"Отправил команду перезагрузки активным сессиям {label}: {out['queued']}.", "actions": [{"name": action, "status": "queued", "count": out["queued"], "user_id": uid}]}
    if action == "user_session_end":
        try:
            out = account_auth.revoke_user_sessions(owner_id, uid, all_sessions=True)
        except account_auth.AccountAuthError as exc:
            raise UserSupportError(str(exc), exc.status) from None
        return {"ok": True, "reply": f"Завершил активные сессии {label}: {out['revoked']}.", "actions": [{"name": action, "status": "completed", "count": out["revoked"], "user_id": uid}]}
    raise UserSupportError("Неизвестная команда поддержки.")
