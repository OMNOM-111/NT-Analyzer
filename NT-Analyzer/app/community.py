"""Community contour — users among themselves (NOT owner Orchestrator).

Development storage is ``data/runtime/community.json``. Explicit Canary and
Production environments route the same compatibility document through the
authoritative PostgreSQL repository without a local fallback. Telegram
duplicate is a separate optional channel and must never write into owner
Orchestrator topics.
"""
from __future__ import annotations

import base64
import binascii
import json
import hashlib
import math
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import auth_identity, runtime_env


class CommunityError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


_LOCK = threading.RLock()
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_STORE_KEY = "community"
_MAX_MSG = 4000
_MAX_ATTACHMENTS = 3
_MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024
_COLLECTIONS = (
    "accounts", "messages", "posts", "strategies", "copies", "reports", "blocks",
    "shared_reports", "requests", "profiles", "follows", "post_reactions",
    "comments", "bookmarks", "social_blocks",
)
_WORKSPACE_RE = re.compile(r"[A-Za-z0-9_.:-]{1,96}")
_CHANNELS = (
    {"id": "general", "label": "Общий чат", "hint": "Обсуждение внутри сообщества"},
    {"id": "study", "label": "Учебная", "hint": "Разборы и вопросы студентов"},
    {"id": "strategy-review", "label": "Стратегии", "hint": "Идеи, результаты и ревью"},
    {"id": "reports", "label": "Отчёты", "hint": "Статистика, файлы и запросы"},
)
_CHANNEL_IDS = frozenset(row["id"] for row in _CHANNELS)
_ATTACHMENT_RE = re.compile(r"^data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=\s]+)$", re.I)
_MIME_EXTENSION = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
_IDENTITY_FIELDS = {
    "accounts": (("user_id", "user_uuid"),),
    "messages": (("user_id", "user_uuid"),),
    "posts": (("user_id", "user_uuid"),),
    "strategies": (("user_id", "user_uuid"),),
    "copies": (("from_user_id", "from_user_uuid"), ("to_user_id", "to_user_uuid")),
    "reports": (("from_user_id", "from_user_uuid"),),
    "shared_reports": (("user_id", "user_uuid"),),
    "requests": (("from_user_id", "from_user_uuid"), ("recipient_user_id", "recipient_user_uuid")),
    "blocks": (("user_id", "user_uuid"), ("by_owner_id", "by_owner_uuid")),
    "profiles": (("user_id", "user_uuid"),),
    "comments": (("user_id", "user_uuid"),),
}


def _empty_doc() -> Dict[str, Any]:
    return {"version": 4, **{key: [] for key in _COLLECTIONS}}


def _root() -> Path:
    return _PROJECT_ROOT


def _store_path() -> Path:
    return runtime_env.data_root(_root()) / "runtime" / "community.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load(*, include_preview: bool = True) -> Dict[str, Any]:
    from . import storage_router
    if storage_router.production_enabled():
        from .production_storage import StorageError
        try:
            doc = storage_router.read_document(_STORE_KEY, _empty_doc())
        except StorageError as exc:
            raise CommunityError(
                f"Production Community repository unavailable ({exc.code}).", 503,
            ) from None
    else:
        path = _store_path()
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = _empty_doc()
    if not isinstance(doc, dict):
        return _empty_doc()
    for key in _COLLECTIONS:
        rows = doc.get(key)
        doc[key] = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    # Treat the on-disk version as untrusted input as well.  The normalized
    # document is always written in the current format.
    doc["version"] = 4
    if include_preview and runtime_env.is_development():
        from .preview_public import overlay
        return overlay(doc)
    return doc


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _save(doc: Dict[str, Any]) -> None:
    from . import storage_router
    from .preview_public import local_only
    payload = _json_safe(local_only(doc))
    if storage_router.production_enabled():
        from .production_storage import StorageError
        try:
            storage_router.write_document(_STORE_KEY, payload)
        except StorageError as exc:
            raise CommunityError(
                f"Production Community repository unavailable ({exc.code}).", 503,
            ) from None
        return
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _workspace_id(value: Any) -> str:
    workspace = str(value or "").strip()
    if workspace and not _WORKSPACE_RE.fullmatch(workspace):
        raise CommunityError("Некорректный workspace_id.")
    return workspace


def _channel_id(value: Any) -> str:
    channel = str(value or "general").strip().lower() or "general"
    if channel not in _CHANNEL_IDS:
        raise CommunityError("Неизвестный канал Community.")
    return channel


def _attachment_dir(workspace_id: str) -> Path:
    scope = workspace_id or "shared"
    return runtime_env.data_root(_root()) / "runtime" / "community_uploads" / scope


def _same_workspace(row: Dict[str, Any], workspace_id: str) -> bool:
    return str(row.get("workspace_id") or "") == workspace_id


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)


def _resolved_user_uuid(user_id: Any, preferred: Any = "") -> str:
    canonical = auth_identity.normalize_user_uuid(preferred)
    if canonical:
        return canonical
    uid = _safe_int(user_id)
    if uid <= 0:
        return ""
    try:
        from . import account_auth
        return account_auth.user_uuid_for_legacy_id(uid)
    except Exception:
        return ""


def _backfill_identity_rows(
    doc: Dict[str, Any], known: Optional[Dict[int, str]] = None,
) -> bool:
    resolved: Dict[int, str] = {}
    for raw_user_id, raw_user_uuid in (known or {}).items():
        user_id = _safe_int(raw_user_id)
        canonical = auth_identity.normalize_user_uuid(raw_user_uuid)
        if user_id > 0 and canonical:
            resolved[user_id] = canonical

    def user_uuid(user_id: Any) -> str:
        numeric = _safe_int(user_id)
        if numeric <= 0:
            return ""
        if numeric not in resolved:
            resolved[numeric] = _resolved_user_uuid(numeric)
        return resolved[numeric]

    changed = False
    for collection, field_pairs in _IDENTITY_FIELDS.items():
        for row in doc.get(collection) or []:
            if not isinstance(row, dict):
                continue
            for user_id_field, user_uuid_field in field_pairs:
                if str(row.get(user_uuid_field) or "").strip():
                    continue
                canonical = user_uuid(row.get(user_id_field))
                if canonical:
                    row[user_uuid_field] = canonical
                    changed = True
    return changed


def _safe_number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(default)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _validated_metrics(metrics: Any) -> Dict[str, float]:
    if metrics is None:
        return {}
    if not isinstance(metrics, dict):
        raise CommunityError("metrics должен быть JSON-объектом с числовыми значениями.")
    if len(metrics) > 64:
        raise CommunityError("Слишком много метрик стратегии.")
    clean: Dict[str, float] = {}
    for raw_key, raw_value in metrics.items():
        key = str(raw_key or "").strip()
        if not key or len(key) > 64 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", key):
            raise CommunityError("Некорректное имя метрики стратегии.")
        if isinstance(raw_value, bool):
            raise CommunityError(f"Метрика {key} должна быть конечным числом.")
        try:
            number = float(raw_value)
        except (TypeError, ValueError, OverflowError):
            raise CommunityError(f"Метрика {key} должна быть конечным числом.") from None
        if not math.isfinite(number):
            raise CommunityError(f"Метрика {key} должна быть конечным числом.")
        clean[key] = number
    return clean


def _idempotency_hash(value: Any) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    if len(clean) > 200:
        raise CommunityError("Idempotency key слишком длинный.")
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def _image_payload_matches_mime(mime: str, payload: bytes) -> bool:
    """Reject a data URL whose declared MIME does not match its file magic."""
    if mime == "image/png":
        return payload.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return payload.startswith(b"\xff\xd8\xff")
    if mime == "image/webp":
        return len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"
    return False


def _validate_attachments(value: Any, *, workspace_id: str, owner_id: str) -> List[Dict[str, Any]]:
    """Persist only small image attachments supplied as data URLs.

    JSON keeps the local UI dependency-free while the resulting message stores
    no base64 payload.  The generated id is later resolved only through the
    authorised Community attachment route.
    """
    if value in (None, ""):
        return []
    if not isinstance(value, list) or len(value) > _MAX_ATTACHMENTS:
        raise CommunityError(f"Можно приложить до {_MAX_ATTACHMENTS} изображений.")
    target_dir = _attachment_dir(workspace_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise CommunityError("Некорректное вложение Community.")
        data_url = str(raw.get("data_url") or "")
        match = _ATTACHMENT_RE.fullmatch(data_url)
        if not match:
            raise CommunityError("Поддерживаются только PNG, JPEG и WebP-изображения.")
        mime = match.group(1).lower()
        try:
            payload = base64.b64decode(match.group(2), validate=True)
        except (ValueError, binascii.Error):
            raise CommunityError("Повреждённые данные изображения.") from None
        if not payload or len(payload) > _MAX_ATTACHMENT_BYTES:
            raise CommunityError("Размер каждого изображения не должен превышать 2 МБ.")
        if not _image_payload_matches_mime(mime, payload):
            raise CommunityError("Содержимое изображения не соответствует MIME-типу.")
        attachment_id = "catt_" + secrets.token_hex(9)
        extension = _MIME_EXTENSION[mime]
        stored_name = f"{owner_id}_{index}{extension}"
        target = (target_dir / stored_name).resolve()
        try:
            target.relative_to(target_dir.resolve())
        except ValueError:  # pragma: no cover - defensive invariant
            raise CommunityError("Некорректный путь вложения.") from None
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, target)
        name = re.sub(r"[\\/:*?\"<>|]+", "_", str(raw.get("name") or "image"))[:120]
        rows.append({
            "attachment_id": attachment_id,
            "name": name or "image",
            "mime_type": mime,
            "size": len(payload),
            "stored_name": stored_name,
            "url": "/api/community/attachment/" + attachment_id,
        })
    return rows


def _public_attachments(value: Any) -> List[Dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    return [
        {
            "attachment_id": str(row.get("attachment_id") or ""),
            "name": str(row.get("name") or "image")[:120],
            "mime_type": str(row.get("mime_type") or ""),
            "size": max(0, _safe_int(row.get("size"))),
            "url": str(row.get("url") or ""),
        }
        for row in rows if isinstance(row, dict)
    ]


def _public_message(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    out["attachments"] = _public_attachments(row.get("attachments"))
    return out


def _blocked(doc: Dict[str, Any], user_id: int, workspace_id: str) -> bool:
    for row in doc.get("blocks") or []:
        if _safe_int(row.get("user_id")) != int(user_id):
            continue
        block_workspace = str(row.get("workspace_id") or "")
        # Legacy blocks had no workspace and intentionally remain global.
        if not block_workspace or block_workspace == workspace_id:
            return True
    return False


def _touch_account(doc: Dict[str, Any], user_id: int, workspace_id: str,
                   display_name: str = "", user_uuid: Any = "") -> Dict[str, Any]:
    rows = doc.setdefault("accounts", [])
    row = next((item for item in rows
                if _safe_int(item.get("user_id")) == int(user_id)
                and _same_workspace(item, workspace_id)), None)
    now = _now_iso()
    canonical = _resolved_user_uuid(user_id, user_uuid)
    if row is None:
        identity = hashlib.sha256(f"{workspace_id}|{int(user_id)}".encode("utf-8")).hexdigest()[:16]
        row = {
            "account_id": "cacc_" + identity,
            "workspace_id": workspace_id,
            "user_id": int(user_id),
            "display_name": str(display_name or f"user_{user_id}")[:80],
            "created_at_utc": now,
            "updated_at_utc": now,
        }
        if canonical:
            row["user_uuid"] = canonical
        rows.append(row)
    else:
        if str(display_name or "").strip():
            row["display_name"] = str(display_name).strip()[:80]
        if canonical and not str(row.get("user_uuid") or "").strip():
            row["user_uuid"] = canonical
        row["updated_at_utc"] = now
    return row


def feed(*, limit: int = 50, workspace_id: str = "", channel_id: str = "") -> Dict[str, Any]:
    workspace = _workspace_id(workspace_id)
    channel = _channel_id(channel_id) if str(channel_id or "").strip() else ""
    with _LOCK:
        doc = _load()
        if _backfill_identity_rows(doc):
            _save(doc)
        scoped_messages = [
            row for row in doc.get("messages") or []
            if _same_workspace(row, workspace) and (not channel or str(row.get("channel_id") or "general") == channel)
        ]
        scoped_strategies = [row for row in doc.get("strategies") or [] if _same_workspace(row, workspace)]
        scoped_posts = [row for row in doc.get("posts") or [] if _same_workspace(row, workspace)]
        scoped_reports = [row for row in doc.get("shared_reports") or [] if _same_workspace(row, workspace)]
        scoped_requests = [row for row in doc.get("requests") or [] if _same_workspace(row, workspace)]
        accounts = [row for row in doc.get("accounts") or [] if _same_workspace(row, workspace)]
        messages = list(reversed(scoped_messages))[: max(1, min(_safe_int(limit, 50), 200))]
        strategies = list(reversed(scoped_strategies))[:50]
        posts = list(reversed(scoped_posts))[:50]
    return {
        "ok": True,
        "contour": "community",
        "workspace_id": workspace,
        "channels": [dict(row) for row in _CHANNELS],
        "selected_channel": channel or "all",
        "accounts": accounts[-200:],
        "messages": [_public_message(row) for row in reversed(messages)],
        "strategies": strategies,
        "posts": posts,
        "shared_reports": [_public_message(row) for row in list(reversed(scoped_reports))[:50]],
        "requests": list(reversed(scoped_requests))[:50],
        "ratings": _ratings_for(scoped_strategies),
    }


def post_message(user_id: Any, *, text: str, display_name: str = "",
                 workspace_id: str = "", idempotency_key: str = "",
                 channel_id: str = "general", thread_root_id: str = "",
                 attachments: Any = None, user_uuid: Any = "") -> Dict[str, Any]:
    uid = int(user_id or 0)
    canonical = _resolved_user_uuid(uid, user_uuid)
    body = str(text or "").strip()
    workspace = _workspace_id(workspace_id)
    channel = _channel_id(channel_id)
    root_id = str(thread_root_id or "").strip()[:80]
    idem_hash = _idempotency_hash(idempotency_key)
    if uid <= 0:
        raise CommunityError("Требуется вход.", 401)
    if not body or len(body) > _MAX_MSG:
        raise CommunityError("Сообщение пустое или слишком длинное.")
    with _LOCK:
        doc = _load()
        backfilled = _backfill_identity_rows(doc, {uid: canonical})
        if _blocked(doc, uid, workspace):
            raise CommunityError("Вы заблокированы в community.", 403)
        if idem_hash:
            existing = next((item for item in doc.get("messages") or []
                             if _safe_int(item.get("user_id")) == uid
                             and _same_workspace(item, workspace)
                             and item.get("idempotency_key_hash") == idem_hash), None)
            if existing is not None:
                if backfilled:
                    _save(doc)
                return {"ok": True, "message": _public_message(existing), "telegram_mirror": False, "deduplicated": True}
        if root_id:
            root = next((item for item in doc.get("messages") or []
                         if item.get("message_id") == root_id and _same_workspace(item, workspace)), None)
            if root is None:
                raise CommunityError("Исходное сообщение ветки не найдено.", 404)
            if str(root.get("channel_id") or "general") != channel:
                raise CommunityError("Ответ должен остаться в том же канале.")
        message_id = "cmsg_" + secrets.token_hex(6)
        row = {
            "message_id": message_id,
            "workspace_id": workspace,
            "channel_id": channel,
            "user_id": uid,
            "display_name": str(display_name or f"user_{uid}")[:80],
            "text": body,
            "created_at_utc": _now_iso(),
            "contour": "community",
        }
        if canonical:
            row["user_uuid"] = canonical
        if root_id:
            row["thread_root_id"] = root_id
        stored_attachments = _validate_attachments(
            attachments, workspace_id=workspace, owner_id=message_id,
        )
        if stored_attachments:
            row["attachments"] = stored_attachments
        if idem_hash:
            row["idempotency_key_hash"] = idem_hash
        _touch_account(doc, uid, workspace, display_name, canonical)
        doc.setdefault("messages", []).append(row)
        doc["messages"] = doc["messages"][-1000:]
        _save(doc)
    return {"ok": True, "message": _public_message(row), "telegram_mirror": False, "deduplicated": False}


def share_report(user_id: Any, *, title: str, summary: str = "", metrics: Any = None,
                 display_name: str = "", workspace_id: str = "", channel_id: str = "reports",
                 attachments: Any = None, user_uuid: Any = "") -> Dict[str, Any]:
    """Share an explicit user report without turning it into an AI task."""
    uid = int(user_id or 0)
    canonical = _resolved_user_uuid(uid, user_uuid)
    workspace = _workspace_id(workspace_id)
    channel = _channel_id(channel_id)
    clean_title = str(title or "").strip()
    if uid <= 0:
        raise CommunityError("Требуется вход.", 401)
    if not clean_title or len(clean_title) > 140:
        raise CommunityError("Укажите название отчёта до 140 символов.")
    clean_metrics = _validated_metrics(metrics)
    with _LOCK:
        doc = _load()
        _backfill_identity_rows(doc, {uid: canonical})
        if _blocked(doc, uid, workspace):
            raise CommunityError("Вы заблокированы в community.", 403)
        report_id = "crshare_" + secrets.token_hex(7)
        row = {
            "report_id": report_id,
            "workspace_id": workspace,
            "channel_id": channel,
            "user_id": uid,
            "display_name": str(display_name or f"user_{uid}")[:80],
            "title": clean_title,
            "summary": str(summary or "")[:4000],
            "metrics": clean_metrics,
            "created_at_utc": _now_iso(),
            "contour": "community",
        }
        if canonical:
            row["user_uuid"] = canonical
            _touch_account(doc, uid, workspace, display_name, canonical)
        stored_attachments = _validate_attachments(
            attachments, workspace_id=workspace, owner_id=report_id,
        )
        if stored_attachments:
            row["attachments"] = stored_attachments
        _touch_account(doc, uid, workspace, display_name)
        doc.setdefault("shared_reports", []).append(row)
        doc["shared_reports"] = doc["shared_reports"][-500:]
        _save(doc)
    return {"ok": True, "report": _public_message(row)}


def create_request(user_id: Any, *, title: str, request_type: str = "report",
                   recipient_user_id: Any = 0, notes: str = "", display_name: str = "",
                   workspace_id: str = "", channel_id: str = "reports",
                   user_uuid: Any = "") -> Dict[str, Any]:
    """Create a transparent in-product request for a report, data or screenshot."""
    uid = int(user_id or 0)
    canonical = _resolved_user_uuid(uid, user_uuid)
    workspace = _workspace_id(workspace_id)
    channel = _channel_id(channel_id)
    clean_title = str(title or "").strip()
    kind = str(request_type or "report").strip().lower()
    if uid <= 0:
        raise CommunityError("Требуется вход.", 401)
    if not clean_title or len(clean_title) > 180:
        raise CommunityError("Укажите запрос до 180 символов.")
    if kind not in {"report", "data", "screenshot"}:
        raise CommunityError("Тип запроса: report, data или screenshot.")
    target = _safe_int(recipient_user_id)
    recipient_uuid = _resolved_user_uuid(target)
    if target < 0:
        raise CommunityError("Некорректный получатель запроса.")
    with _LOCK:
        doc = _load()
        _backfill_identity_rows(doc, {uid: canonical, target: recipient_uuid})
        if _blocked(doc, uid, workspace):
            raise CommunityError("Вы заблокированы в community.", 403)
        row = {
            "request_id": "creq_" + secrets.token_hex(7),
            "workspace_id": workspace,
            "channel_id": channel,
            "from_user_id": uid,
            "from_display_name": str(display_name or f"user_{uid}")[:80],
            "recipient_user_id": target,
            "request_type": kind,
            "title": clean_title,
            "notes": str(notes or "")[:2000],
            "status": "open",
            "created_at_utc": _now_iso(),
        }
        if canonical:
            row["from_user_uuid"] = canonical
        if recipient_uuid:
            row["recipient_user_uuid"] = recipient_uuid
        _touch_account(doc, uid, workspace, display_name, canonical)
        doc.setdefault("requests", []).append(row)
        doc["requests"] = doc["requests"][-500:]
        _save(doc)
    return {"ok": True, "request": row}


def attachment(attachment_id: str, *, workspace_id: str = "") -> Dict[str, Any]:
    """Return a verified attachment record and file path for the HTTP handler."""
    aid = str(attachment_id or "").strip()
    workspace = _workspace_id(workspace_id)
    if not re.fullmatch(r"catt_[a-f0-9]{18}", aid):
        raise CommunityError("Вложение не найдено.", 404)
    with _LOCK:
        doc = _load()
        if _backfill_identity_rows(doc):
            _save(doc)
        candidates = list(doc.get("messages") or []) + list(doc.get("shared_reports") or [])
        owner = next((row for row in candidates if _same_workspace(row, workspace)
                      and any(isinstance(item, dict) and item.get("attachment_id") == aid
                              for item in (row.get("attachments") or []))), None)
        if owner is None:
            raise CommunityError("Вложение не найдено.", 404)
        meta = next(item for item in (owner.get("attachments") or [])
                    if isinstance(item, dict) and item.get("attachment_id") == aid)
        stored_name = str(meta.get("stored_name") or "")
        target_dir = _attachment_dir(workspace).resolve()
        path = (target_dir / stored_name).resolve()
        try:
            path.relative_to(target_dir)
        except ValueError:
            raise CommunityError("Вложение не найдено.", 404) from None
        if not path.is_file():
            raise CommunityError("Файл вложения недоступен.", 404)
        return {
            "path": path,
            "name": str(meta.get("name") or "image")[:120],
            "mime_type": str(meta.get("mime_type") or "application/octet-stream"),
        }


def publish_strategy(
    user_id: Any,
    *,
    title: str,
    metrics: Optional[Dict[str, Any]] = None,
    notes: str = "",
    display_name: str = "",
    workspace_id: str = "",
    idempotency_key: str = "",
    user_uuid: Any = "",
) -> Dict[str, Any]:
    uid = int(user_id or 0)
    canonical = _resolved_user_uuid(uid, user_uuid)
    name = str(title or "").strip()
    workspace = _workspace_id(workspace_id)
    clean_metrics = _validated_metrics(metrics)
    idem_hash = _idempotency_hash(idempotency_key)
    if uid <= 0:
        raise CommunityError("Требуется вход.", 401)
    if not name:
        raise CommunityError("Укажите название стратегии.")
    with _LOCK:
        doc = _load()
        backfilled = _backfill_identity_rows(doc, {uid: canonical})
        if _blocked(doc, uid, workspace):
            raise CommunityError("Вы заблокированы в community.", 403)
        if idem_hash:
            existing = next((item for item in doc.get("strategies") or []
                             if _safe_int(item.get("user_id")) == uid
                             and _same_workspace(item, workspace)
                             and item.get("idempotency_key_hash") == idem_hash), None)
            if existing is not None:
                if backfilled:
                    _save(doc)
                return {"ok": True, "strategy": existing, "deduplicated": True}
        row = {
            "strategy_id": "cstr_" + secrets.token_hex(5),
            "workspace_id": workspace,
            "user_id": uid,
            "display_name": str(display_name or f"user_{uid}")[:80],
            "title": name[:120],
            "notes": str(notes or "")[:2000],
            "metrics": clean_metrics,
            "copies": 0,
            "created_at_utc": _now_iso(),
            "status": "published",
        }
        if canonical:
            row["user_uuid"] = canonical
            _touch_account(doc, uid, workspace, display_name, canonical)
        if idem_hash:
            row["idempotency_key_hash"] = idem_hash
        _touch_account(doc, uid, workspace, display_name)
        doc.setdefault("strategies", []).append(row)
        doc["strategies"] = doc["strategies"][-500:]
        _save(doc)
    return {"ok": True, "strategy": row, "deduplicated": False}


def copy_strategy(user_id: Any, strategy_id: str, *, workspace_id: str = "",
                  idempotency_key: str = "", user_uuid: Any = "") -> Dict[str, Any]:
    uid = int(user_id or 0)
    canonical = _resolved_user_uuid(uid, user_uuid)
    sid = str(strategy_id or "").strip()
    workspace = _workspace_id(workspace_id)
    idem_hash = _idempotency_hash(idempotency_key)
    if uid <= 0:
        raise CommunityError("Требуется вход.", 401)
    with _LOCK:
        doc = _load()
        backfilled = _backfill_identity_rows(doc, {uid: canonical})
        if _blocked(doc, uid, workspace):
            raise CommunityError("Вы заблокированы в community.", 403)
        src = next((row for row in doc.get("strategies") or []
                    if row.get("strategy_id") == sid and _same_workspace(row, workspace)), None)
        if src is None:
            raise CommunityError("Стратегия не найдена.", 404)
        # Until a real portfolio importer consumes the request, a repeated click
        # is the same pending operation and must not inflate popularity counters.
        existing = next((item for item in doc.get("copies") or []
                         if item.get("strategy_id") == sid
                         and _safe_int(item.get("to_user_id")) == uid
                         and _same_workspace(item, workspace)
                         and str(item.get("status") or "pending_import") == "pending_import"), None)
        if existing is not None:
            if backfilled:
                _save(doc)
            return {
                "ok": True, "copy": existing, "strategy": src, "deduplicated": True,
                "import": _pending_import_contract(existing),
            }
        src["copies"] = max(0, _safe_int(src.get("copies"))) + 1
        source_uuid = _resolved_user_uuid(src.get("user_id"), src.get("user_uuid"))
        copy_row = {
            "copy_id": "ccopy_" + secrets.token_hex(5),
            "workspace_id": workspace,
            "strategy_id": sid,
            "from_user_id": _safe_int(src.get("user_id")),
            "to_user_id": uid,
            "title": src.get("title"),
            "metrics": dict(src.get("metrics") or {}) if isinstance(src.get("metrics"), dict) else {},
            "created_at_utc": _now_iso(),
            "status": "pending_import",
            "personal_strategy_created": False,
        }
        if source_uuid:
            copy_row["from_user_uuid"] = source_uuid
        if canonical:
            copy_row["to_user_uuid"] = canonical
            _touch_account(doc, uid, workspace, user_uuid=canonical)
        if idem_hash:
            copy_row["idempotency_key_hash"] = idem_hash
        _touch_account(doc, uid, workspace)
        doc.setdefault("copies", []).append(copy_row)
        _save(doc)
    return {
        "ok": True, "copy": copy_row, "strategy": src, "deduplicated": False,
        "import": _pending_import_contract(copy_row),
    }


def _pending_import_contract(copy_row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "pending",
        "copy_id": str(copy_row.get("copy_id") or ""),
        "personal_strategy_created": False,
        "action_required": "portfolio_import",
        "message": "Запрос копирования сохранён. Личная стратегия ещё не создана; нужен отдельный импорт в портфель.",
    }


def _ratings_for(strategies: List[Dict[str, Any]]) -> Dict[str, Any]:
    def score(row: Dict[str, Any]) -> float:
        m = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        net = _safe_number(m.get("net_profit") if m.get("net_profit") is not None else m.get("return_pct"))
        dd = abs(_safe_number(m.get("max_drawdown") if m.get("max_drawdown") is not None else m.get("drawdown"), 1.0))
        copies = max(0, _safe_int(row.get("copies")))
        # Not only return: reward risk-adjusted + popularity.
        return (net / max(dd, 1.0)) + copies * 0.5

    ranked = sorted(strategies, key=score, reverse=True)
    by_return = sorted(
        strategies,
        key=lambda row: _safe_number((row.get("metrics") or {}).get("net_profit")
                                     if isinstance(row.get("metrics"), dict) else 0),
        reverse=True,
    )
    by_copies = sorted(strategies, key=lambda row: max(0, _safe_int(row.get("copies"))), reverse=True)
    by_new = sorted(strategies, key=lambda row: str(row.get("created_at_utc") or ""), reverse=True)
    authors: Dict[int, Dict[str, Any]] = {}
    for row in strategies:
        uid = _safe_int(row.get("user_id"))
        bucket = authors.setdefault(uid, {"user_id": uid, "display_name": row.get("display_name"), "strategies": 0, "copies": 0})
        canonical = auth_identity.normalize_user_uuid(row.get("user_uuid"))
        if canonical and not bucket.get("user_uuid"):
            bucket["user_uuid"] = canonical
        bucket["strategies"] += 1
        bucket["copies"] += max(0, _safe_int(row.get("copies")))
    return {
        "composite": ranked[:20],
        "by_return": by_return[:20],
        "by_copies": by_copies[:20],
        "newest": by_new[:20],
        "authors": sorted(authors.values(), key=lambda row: row["copies"], reverse=True)[:20],
    }


def ratings(*, workspace_id: str = "") -> Dict[str, Any]:
    workspace = _workspace_id(workspace_id)
    with _LOCK:
        doc = _load()
        if _backfill_identity_rows(doc):
            _save(doc)
        strategies = [row for row in doc.get("strategies") or [] if _same_workspace(row, workspace)]
    return _ratings_for(strategies)


def report_abuse(user_id: Any, *, target_id: str, reason: str = "",
                 workspace_id: str = "", user_uuid: Any = "") -> Dict[str, Any]:
    uid = int(user_id or 0)
    canonical = _resolved_user_uuid(uid, user_uuid)
    workspace = _workspace_id(workspace_id)
    if uid <= 0:
        raise CommunityError("Требуется вход.", 401)
    with _LOCK:
        doc = _load()
        _backfill_identity_rows(doc, {uid: canonical})
        row = {
            "report_id": "crep_" + secrets.token_hex(5),
            "workspace_id": workspace,
            "from_user_id": uid,
            "target_id": str(target_id or "")[:80],
            "reason": str(reason or "")[:500],
            "created_at_utc": _now_iso(),
        }
        if canonical:
            row["from_user_uuid"] = canonical
        doc.setdefault("reports", []).append(row)
        _save(doc)
    return {"ok": True, "report": row}


def moderate_block(owner_id: Any, target_user_id: Any, *, reason: str = "",
                   workspace_id: str = "", owner_user_uuid: Any = "") -> Dict[str, Any]:
    # Owner check is done by server route.
    tid = int(target_user_id or 0)
    target_uuid = _resolved_user_uuid(tid)
    owner_uuid = _resolved_user_uuid(owner_id, owner_user_uuid)
    workspace = _workspace_id(workspace_id)
    if tid <= 0:
        raise CommunityError("Пользователь не найден.", 404)
    with _LOCK:
        doc = _load()
        backfilled = _backfill_identity_rows(doc, {tid: target_uuid, _safe_int(owner_id): owner_uuid})
        existing = next((row for row in doc.get("blocks") or []
                         if _safe_int(row.get("user_id")) == tid
                         and _same_workspace(row, workspace)), None)
        if existing is not None:
            if backfilled:
                _save(doc)
            return {"ok": True, "blocked_user_id": tid, "deduplicated": True}
        row = {
            "workspace_id": workspace,
            "user_id": tid,
            "by_owner_id": int(owner_id or 0),
            "reason": str(reason or "")[:300],
            "created_at_utc": _now_iso(),
        }
        if target_uuid:
            row["user_uuid"] = target_uuid
        if owner_uuid:
            row["by_owner_uuid"] = owner_uuid
        doc.setdefault("blocks", []).append(row)
        _save(doc)
    return {"ok": True, "blocked_user_id": tid, "deduplicated": False}


def moderate_delete_message(owner_id: Any, message_id: str, *, workspace_id: str = "") -> Dict[str, Any]:
    mid = str(message_id or "")
    workspace = _workspace_id(workspace_id)
    with _LOCK:
        doc = _load()
        _backfill_identity_rows(doc)
        before = len(doc.get("messages") or [])
        doc["messages"] = [row for row in doc.get("messages") or []
                           if not (row.get("message_id") == mid and _same_workspace(row, workspace))]
        _save(doc)
    return {"ok": True, "deleted": before - len(doc.get("messages") or []), "by_owner_id": int(owner_id or 0)}


# ---------------------------------------------------------------------------
# Community v2 social layer
# ---------------------------------------------------------------------------
# The original workspace channels above remain the compatibility foundation.
# The v2 layer adds explicit, sanitised publications to the environment-wide
# internal network. A private workspace never crosses this boundary by merely
# existing: only a user-created v2 post is visible in the social feed.

# The same shape as the StratForge account handle
# (``account_auth.normalize_handle``): a member has one name across the
# product, so a legitimate handle like ``sf.trader`` must not silently
# become a generated ``sf_xxxxxxxxxx`` inside Social.
_PROFILE_USERNAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.]{1,30})[A-Za-z0-9]")
_HASHTAG_RE = re.compile(r"(?<![\w#])#([\w-]{2,40})", re.UNICODE)
_REACTIONS = frozenset({"support", "insightful", "fire"})
# "private" keeps a post on its author's own wall: everyone else is refused
# by _post_visible, and social_feed excludes it from Recommendation even for
# the author, because Recommendation is the public surface rather than a
# second copy of the wall.
# --------------------------------------------------------------------------- #
# Permanent record — Original ideas. Permanent history. Transparent corrections.
#
# SF Social's founding rule. Once published, a member cannot delete the
# original, rewrite its content, or change its date or authorship. A mistake is
# corrected by publishing again -- optionally as an explicit correction linked
# to the original -- and both records stand. A timeline you can prune after the
# fact says nothing about a person; it says what they chose to leave standing.
#
# The rule binds the owner as an author exactly as it binds everyone else.
#
# The one exception is administrative removal, and it is disclosed rather than
# hidden: a hidden backdoor would make the public promise a lie, while a
# disclosed procedure that cannot be used without leaving a trace is a stronger
# claim than a promise nobody can audit. It requires owner authority, a reason
# code and a written reason, and it writes an append-only audit record *before*
# it touches anything. Nothing in this module can delete an audit record.
#
# Two operations, deliberately unequal in reach:
#   - `moderation_removal` (the default): the object stops being shown and a
#     tombstone takes its place. Stored content is retained for the record.
#   - `hard_erasure`: the content itself is cleared. Reserved for privacy,
#     legal, security and illegal-content grounds. Even then a non-content
#     audit record remains -- who, when, why, and a hash of what was erased,
#     so the act stays provable after the content is gone.
#
# An AI never holds this authority. An agent may carry out a removal that an
# authenticated owner asked for; the audit record then shows the owner as the
# authority and the agent as the hand. The agent is never written as the owner.
#
# Clearing a Development or test database is a maintenance operation on the
# store as a whole. It is not this flow, and this flow is not a way to reach a
# Production database.
# --------------------------------------------------------------------------- #
PERMANENT_RECORD = True
PERMANENT_RECORD_PRINCIPLE = "Original ideas. Permanent history. Transparent corrections."
PERMANENT_RECORD_NOTICE = (
    "Опубликованное становится частью постоянной истории профиля: удалить или "
    "переписать запись нельзя. Ошибку исправляет новая публикация — обе останутся."
)
TOMBSTONE_POST_TEXT = "Публикация удалена администрацией"
TOMBSTONE_COMMENT_TEXT = "Комментарий удалён администрацией"

_REMOVAL_OPERATIONS = ("moderation_removal", "hard_erasure")
# Reason codes are a closed set so the audit trail can be read as data, and the
# human-readable reason is required alongside so it can be read as an account.
_REMOVAL_REASON_CODES = {
    "legal_request": "Законное требование или решение суда",
    "privacy_request": "Требование об удалении персональных данных",
    "illegal_content": "Незаконное или опасное содержимое",
    "security_incident": "Инцидент безопасности",
    "moderation_policy": "Нарушение правил сообщества",
}
# Clearing content is the heavier act, so it is available only where a policy
# actually demands it. A rules violation is answered by a tombstone.
_HARD_ERASURE_REASON_CODES = frozenset({
    "legal_request", "privacy_request", "illegal_content", "security_incident",
})
_REMOVAL_SOURCES = ("owner_ui", "owner_api", "ai_assisted", "moderation_queue")
_REMOVAL_TARGETS = {"post": ("posts", "post_id"), "comment": ("comments", "comment_id")}

_POST_VISIBILITY = frozenset({"network", "followers", "private"})
_RECOMMENDABLE_VISIBILITY = frozenset({"network", "followers"})
_PROFILE_VISIBILITY = frozenset({"network", "followers"})
_MESSAGE_POLICIES = frozenset({"everyone", "following", "nobody"})


def _profile_id(user_id: Any, user_uuid: Any = "") -> str:
    canonical = _resolved_user_uuid(user_id, user_uuid)
    identity = canonical or f"legacy:{_safe_int(user_id)}"
    return "sfp_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _normalise_username(value: Any, profile_id: str) -> str:
    clean = str(value or "").strip().lstrip("@").lower()
    if _PROFILE_USERNAME_RE.fullmatch(clean):
        return clean
    return "sf_" + profile_id[-10:]


def _profile_row(doc: Dict[str, Any], profile_id: str) -> Optional[Dict[str, Any]]:
    pid = str(profile_id or "").strip()
    return next((row for row in doc.get("profiles") or []
                 if str(row.get("profile_id") or "") == pid), None)


def _profile_by_identity(doc: Dict[str, Any], user_id: Any, user_uuid: Any = "") -> Optional[Dict[str, Any]]:
    canonical = _resolved_user_uuid(user_id, user_uuid)
    uid = _safe_int(user_id)
    for row in doc.get("profiles") or []:
        if canonical and str(row.get("user_uuid") or "") == canonical:
            return row
        if not canonical and uid > 0 and _safe_int(row.get("user_id")) == uid:
            return row
    return None


def _account_registered_at(user_id: Any) -> str:
    """The StratForge account's own registration moment.

    Community has no registration of its own: a profile is created on first
    sight of an existing account and must inherit the date that account was
    actually registered. Stamping the current time would tell a member who
    registered in August that they joined the day they first opened Community.
    """
    uid = _safe_int(user_id)
    if uid <= 0:
        return ""
    try:
        from . import account_auth
        account = account_auth.find_active_user(uid) or {}
        return str(account.get("created_at_utc") or "")
    except Exception:
        return ""


def _ensure_profile_in_doc(
    doc: Dict[str, Any], user_id: Any, *, user_uuid: Any = "",
    display_name: str = "", username: str = "", role_label: str = "Участник",
    joined_at_utc: str = "", has_avatar: bool = False,
) -> Dict[str, Any]:
    uid = _safe_int(user_id)
    if uid <= 0:
        raise CommunityError("Требуется вход.", 401)
    canonical = _resolved_user_uuid(uid, user_uuid)
    from . import account_auth, account_lifecycle
    with account_auth._LOCK:
        account = account_auth._user(account_auth._read_doc_reference(), uid)
        if (account or {}).get("deletion_pending"):
            raise CommunityError("Аккаунт удаляется.", 403)
    if ((canonical and canonical in account_lifecycle.deleted_ids())
            or (not account and uid in account_lifecycle.deleted_legacy_ids())):
        raise CommunityError("Аккаунт удалён.", 403)
    if (account or {}).get("is_owner") and role_label == "Участник":
        role_label = "Владелец"
    row = _profile_by_identity(doc, uid, canonical)
    now = _now_iso()
    if row is None:
        pid = _profile_id(uid, canonical)
        row = {
            "profile_id": pid,
            "user_id": uid,
            "display_name": str(display_name or username or f"Участник {pid[-4:]}").strip()[:80],
            "username": _normalise_username(username, pid),
            "role_label": str(role_label or "Участник").strip()[:40],
            "bio": "",
            "profile_visibility": "network",
            "allow_messages": "everyone",
            "joined_at_utc": str(joined_at_utc or _account_registered_at(uid) or now),
            "created_at_utc": now,
            "updated_at_utc": now,
            "has_avatar": bool(has_avatar),
        }
        if canonical:
            row["user_uuid"] = canonical
        doc.setdefault("profiles", []).append(row)
    else:
        if canonical and not str(row.get("user_uuid") or ""):
            row["user_uuid"] = canonical
        # A profile created before the account date was consulted carries the
        # moment Community first saw the member, not the moment they
        # registered. The field mirrors account data, so correcting it towards
        # the account is a repair, never a rewrite of anything user-authored —
        # and it only ever moves the date earlier.
        registered = _account_registered_at(uid)
        stored_join = str(row.get("joined_at_utc") or "")
        if registered and (not stored_join or stored_join > registered):
            row["joined_at_utc"] = registered
        # Account-sourced fields refresh only while the member has not chosen a
        # custom value. User-edited bio/privacy are never overwritten here.
        if display_name and not str(row.get("display_name") or "").strip():
            row["display_name"] = str(display_name).strip()[:80]
        if username and str(row.get("username") or "").startswith("sf_"):
            candidate = _normalise_username(username, str(row.get("profile_id") or ""))
            if not any(other is not row and str(other.get("username") or "") == candidate
                       for other in doc.get("profiles") or []):
                row["username"] = candidate
        if role_label:
            row["role_label"] = str(role_label).strip()[:40]
        row["has_avatar"] = bool(has_avatar or row.get("has_avatar"))
        row["updated_at_utc"] = now
    _touch_account(doc, uid, "", display_name, canonical)
    return row


def _follows(doc: Dict[str, Any], follower: str, target: str) -> bool:
    return any(
        str(row.get("follower_profile_id") or "") == follower
        and str(row.get("target_profile_id") or "") == target
        for row in doc.get("follows") or []
    )


def _social_blocked(doc: Dict[str, Any], left: str, right: str) -> bool:
    return any(
        {str(row.get("blocker_profile_id") or ""), str(row.get("target_profile_id") or "")}
        == {left, right}
        for row in doc.get("social_blocks") or []
    )


def _current_profile_identity(row):
    """Refresh generated placeholders from the account; preserve chosen names."""
    if row.get("_preview_public_projection"):
        return row
    from . import account_auth
    uid = _safe_int(row.get("user_id"))
    with account_auth._LOCK:
        account = account_auth._user(account_auth._read_doc_reference(), uid) or {}
    name = " ".join(str(account.get(key) or "").strip() for key in ("first_name", "last_name")
                    if str(account.get(key) or "").strip() not in {"", "—", "-"})
    name = name or str(account.get("handle") or account.get("username") or "")
    current = str(row.get("display_name") or "").strip()
    generated = not current or current in {"Участник", "Владелец"} or current.startswith("Участник ")
    out = dict(row)
    if name and generated and not row.get("display_name_custom"):
        out["display_name"] = name[:80]
    if account:
        out["has_avatar"] = account_auth.avatar_file(uid) is not None
    return out


def _profile_payload(
    row: Dict[str, Any], viewer_profile_id: str, *,
    followers: int, following: int, posts: int, blocked: bool,
    viewer_follows: bool, follows_viewer: bool,
) -> Dict[str, Any]:
    """The single public shape of a profile.

    Both read paths land here — the Development document store and the
    Production relational mirrors — so visibility and messaging policy cannot
    be evaluated differently between them. Only the counters and the two
    follow predicates are supplied by the caller, because only their *source*
    differs.
    """
    row = _current_profile_identity(row)
    pid = str(row.get("profile_id") or "")
    is_self = bool(viewer_profile_id and pid == viewer_profile_id)
    profile_visibility = str(row.get("profile_visibility") or "network")
    details_visible = bool(
        profile_visibility == "network" or is_self
        or (viewer_profile_id and viewer_follows)
    )
    policy = str(row.get("allow_messages") or "everyone")
    can_message = bool(viewer_profile_id and viewer_profile_id != pid and not blocked)
    if policy == "nobody":
        can_message = False
    elif policy == "following" and can_message:
        can_message = follows_viewer
    return {
        "profile_id": pid,
        "display_name": str(row.get("display_name") or "Участник")[:80],
        "username": str(row.get("username") or "")[:30],
        "role_label": str(row.get("role_label") or "Участник")[:40],
        "bio": str(row.get("bio") or "")[:500] if details_visible else "",
        "joined_at_utc": str(row.get("joined_at_utc") or row.get("created_at_utc") or ""),
        "has_avatar": bool(row.get("has_avatar")),
        "avatar_url": f"/api/community/v2/profiles/{pid}/avatar" if row.get("has_avatar") else "",
        "stats": {"posts": posts, "followers": followers, "following": following},
        "is_self": is_self,
        "is_following": bool(viewer_profile_id and viewer_follows),
        "follows_you": bool(viewer_profile_id and follows_viewer),
        "can_message": can_message,
        "blocked": blocked,
        "profile_visibility": profile_visibility if is_self else "",
        "allow_messages": policy if is_self else "",
        "details_visible": details_visible,
    }


def _public_profile(doc: Dict[str, Any], row: Dict[str, Any], viewer_profile_id: str = "") -> Dict[str, Any]:
    """Document-store projection: counters come from the loaded document."""
    pid = str(row.get("profile_id") or "")
    return _profile_payload(
        row, viewer_profile_id,
        followers=sum(1 for item in doc.get("follows") or []
                      if str(item.get("target_profile_id") or "") == pid),
        following=sum(1 for item in doc.get("follows") or []
                      if str(item.get("follower_profile_id") or "") == pid),
        posts=sum(1 for item in doc.get("posts") or []
                  if str(item.get("author_profile_id") or "") == pid
                  and not item.get("deleted_at_utc")),
        blocked=bool(viewer_profile_id and _social_blocked(doc, viewer_profile_id, pid)),
        viewer_follows=bool(viewer_profile_id and _follows(doc, viewer_profile_id, pid)),
        follows_viewer=bool(viewer_profile_id and _follows(doc, pid, viewer_profile_id)),
    )


def _relational_profile(relational_row: Dict[str, Any], viewer_profile_id: str) -> Dict[str, Any]:
    """Relational projection: counters come from the indexed mirrors."""
    row = dict(relational_row.get("document") or {})
    if not row.get("profile_id"):
        row["profile_id"] = str(relational_row.get("profile_id") or "")
    return _profile_payload(
        row, viewer_profile_id,
        followers=int(relational_row.get("followers") or 0),
        following=int(relational_row.get("following") or 0),
        posts=int(relational_row.get("posts") or 0),
        blocked=bool(relational_row.get("blocked")),
        viewer_follows=bool(relational_row.get("viewer_follows")),
        follows_viewer=bool(relational_row.get("follows_viewer")),
    )


def ensure_social_profile(
    user_id: Any, *, user_uuid: Any = "", display_name: str = "",
    username: str = "", role_label: str = "Участник", joined_at_utc: str = "",
    has_avatar: bool = False,
) -> Dict[str, Any]:
    with _LOCK:
        doc = _load()
        row = _ensure_profile_in_doc(
            doc, user_id, user_uuid=user_uuid, display_name=display_name,
            username=username, role_label=role_label, joined_at_utc=joined_at_utc,
            has_avatar=has_avatar,
        )
        # The StratForge owner owns the StratForge AI page. It is created once,
        # here, rather than by a separate signup: the organization is a
        # publishing identity, not an account somebody registers.
        if _account_is_owner(user_id):
            _ensure_default_organization(doc, str(row["profile_id"]))
        _save(doc)
        return {"ok": True, "profile": _public_profile(doc, row, str(row["profile_id"]))}


def update_social_profile(
    user_id: Any, *, user_uuid: Any = "", display_name: Any = None,
    username: Any = None, bio: Any = None, profile_visibility: Any = None,
    allow_messages: Any = None,
) -> Dict[str, Any]:
    with _LOCK:
        doc = _load()
        row = _ensure_profile_in_doc(doc, user_id, user_uuid=user_uuid)
        if display_name is not None:
            clean_name = str(display_name or "").strip()
            if not clean_name or len(clean_name) > 80:
                raise CommunityError("Имя профиля должно содержать от 1 до 80 символов.")
            row["display_name"] = clean_name
            row["display_name_custom"] = True
        if username is not None:
            clean_username = str(username or "").strip().lstrip("@").lower()
            if not _PROFILE_USERNAME_RE.fullmatch(clean_username):
                raise CommunityError("Username: 3–32 латинских буквы, цифры, точка или _.")
            if any(other is not row and str(other.get("username") or "") == clean_username
                   for other in doc.get("profiles") or []):
                raise CommunityError("Этот username уже занят.", 409)
            row["username"] = clean_username
        if bio is not None:
            row["bio"] = str(bio or "").strip()[:500]
        if profile_visibility is not None:
            visibility = str(profile_visibility or "").strip().lower()
            if visibility not in _PROFILE_VISIBILITY:
                raise CommunityError("Неизвестная приватность профиля.")
            row["profile_visibility"] = visibility
        if allow_messages is not None:
            policy = str(allow_messages or "").strip().lower()
            if policy not in _MESSAGE_POLICIES:
                raise CommunityError("Неизвестная политика сообщений.")
            row["allow_messages"] = policy
        row["updated_at_utc"] = _now_iso()
        _save(doc)
        return {"ok": True, "profile": _public_profile(doc, row, str(row["profile_id"]))}


def _viewer_profile(doc: Dict[str, Any], user_id: Any, user_uuid: Any = "") -> Dict[str, Any]:
    return _ensure_profile_in_doc(doc, user_id, user_uuid=user_uuid)


def list_social_profiles(
    user_id: Any, *, user_uuid: Any = "", query: str = "", limit: int = 30,
) -> Dict[str, Any]:
    clean_query = str(query or "").strip().lower()[:80]
    lim = max(1, min(100, _safe_int(limit, 30)))
    with _LOCK:
        doc = _load()
        viewer = _viewer_profile(doc, user_id, user_uuid)
        viewer_id = str(viewer["profile_id"])
        rows = []
        for row in doc.get("profiles") or []:
            pid = str(row.get("profile_id") or "")
            if pid != viewer_id and _social_blocked(doc, viewer_id, pid):
                continue
            haystack = " ".join((str(row.get("display_name") or ""), str(row.get("username") or ""))).lower()
            if clean_query and clean_query not in haystack:
                continue
            rows.append(_public_profile(doc, row, viewer_id))
        rows.sort(key=lambda item: (
            not bool(item.get("is_following")),
            -int((item.get("stats") or {}).get("followers") or 0),
            str(item.get("display_name") or "").lower(),
        ))
        _save(doc)
        return {"ok": True, "profiles": rows[:lim], "viewer": _public_profile(doc, viewer, viewer_id)}


def _registration_milestone(
    row: Dict[str, Any], viewer_profile_id: str = "",
) -> Dict[str, Any]:
    """The permanent first entry on a profile wall.

    Derived from the profile's own registration fields rather than stored as a
    post, which makes every property the product asks for true by construction:
    it exists exactly once, cannot be deleted or edited, carries a date nobody
    can change, and neither a restart, a re-login, an import nor a migration can
    produce a second copy. Nothing here is invented — an absent field is
    reported as absent.

    Account status is only ever reported for the member's own profile. Another
    member's wall shows the registration date, which is already public, and
    nothing about the state of their account.
    """
    pid = str(row.get("profile_id") or "")
    # `joined_at_utc` carries the account's registration moment; the profile
    # row's own `created_at_utc` is bookkeeping — it moves whenever the row is
    # rewritten — so it is never reported as a date the member would recognise.
    registered = str(row.get("joined_at_utc") or "")
    is_self = bool(viewer_profile_id and pid == viewer_profile_id)
    activated = ""
    status = ""
    if is_self:
        try:
            from . import account_auth
            account = account_auth.find_active_user(_safe_int(row.get("user_id"))) or {}
            status = str(account.get("status") or "")
            # The account is the source of truth for one's own registration.
            registered = str(account.get("created_at_utc") or "") or registered
            # Activation is only a separate fact when the account was approved
            # at a different moment than it was created. Where the two coincide
            # there is nothing to report, and inventing a second date from
            # unrelated bookkeeping would be worse than showing none.
            approved = str(account.get("approved_at_utc") or "")
            if approved and approved != str(account.get("created_at_utc") or ""):
                activated = approved
        except Exception:
            status = ""
    return {
        "kind": "registration",
        "profile_id": pid,
        "registered_at_utc": registered,
        "activated_at_utc": activated,
        "account_status": status,
        "is_self": is_self,
    }


def social_profile(
    user_id: Any, profile_id: str, *, user_uuid: Any = "", posts_limit: int = 20,
) -> Dict[str, Any]:
    with _LOCK:
        doc = _load()
        viewer = _viewer_profile(doc, user_id, user_uuid)
        viewer_id = str(viewer["profile_id"])
        target = _profile_row(doc, profile_id)
        if target is None or _social_blocked(doc, viewer_id, str(profile_id)):
            raise CommunityError("Профиль не найден.", 404)
        # On your own wall an administratively removed post leaves a tombstone:
        # a record that vanished without a word teaches the author nothing, and
        # they are entitled to know their publication was taken down. Elsewhere
        # -- Recommendation, search, another member's view of this wall -- a
        # removed post is not surfaced at all.
        own_wall = str(profile_id) == viewer_id
        posts = [
            _post_tombstone(row) if row.get("removed_at_utc")
            else _public_social_post(doc, row, viewer_id)
            for row in reversed(doc.get("posts") or [])
            if str(row.get("author_profile_id") or "") == str(profile_id)
            # A post published as an organization belongs to that page, even
            # though a person created it.
            and not str(row.get("publisher_org_id") or "")
            and ((own_wall and row.get("removed_at_utc"))
                 or _post_visible(doc, row, viewer_id))
        ][:max(1, min(100, _safe_int(posts_limit, 20)))]
        _save(doc)
        return {
            "ok": True,
            "profile": _public_profile(doc, target, viewer_id),
            "registration": _registration_milestone(target, viewer_id),
            "posts": posts,
        }


def follow_profile(
    user_id: Any, target_profile_id: str, *, following: bool = True,
    user_uuid: Any = "",
) -> Dict[str, Any]:
    with _LOCK:
        doc = _load()
        viewer = _viewer_profile(doc, user_id, user_uuid)
        viewer_id = str(viewer["profile_id"])
        target = _profile_row(doc, target_profile_id)
        if target is None:
            raise CommunityError("Профиль не найден.", 404)
        target_id = str(target["profile_id"])
        if target_id == viewer_id:
            raise CommunityError("Нельзя подписаться на себя.")
        if _social_blocked(doc, viewer_id, target_id):
            raise CommunityError("Взаимодействие с профилем недоступно.", 403)
        rows = doc.setdefault("follows", [])
        rows[:] = [row for row in rows if not (
            str(row.get("follower_profile_id") or "") == viewer_id
            and str(row.get("target_profile_id") or "") == target_id
        )]
        if following:
            rows.append({
                "follower_profile_id": viewer_id,
                "target_profile_id": target_id,
                "created_at_utc": _now_iso(),
            })
        _save(doc)
        return {
            "ok": True,
            "following": bool(following),
            "profile": _public_profile(doc, target, viewer_id),
        }


def _post_visible(doc: Dict[str, Any], row: Dict[str, Any], viewer_profile_id: str) -> bool:
    if row.get("deleted_at_utc"):
        return False
    author_id = str(row.get("author_profile_id") or "")
    if not author_id or _social_blocked(doc, viewer_profile_id, author_id):
        return False
    if author_id == viewer_profile_id:
        return True
    visibility = str(row.get("visibility") or "network")
    return visibility == "network" or (
        visibility == "followers" and _follows(doc, viewer_profile_id, author_id)
    )


def _post_reaction_summary(doc: Dict[str, Any], post_id: str) -> Dict[str, int]:
    result = {kind: 0 for kind in sorted(_REACTIONS)}
    for row in doc.get("post_reactions") or []:
        if str(row.get("post_id") or "") != post_id:
            continue
        kind = str(row.get("reaction") or "")
        if kind in result:
            result[kind] += 1
    return result


def _tombstone(row: Dict[str, Any], kind: str) -> Dict[str, Any]:
    """What a removed object looks like to every reader.

    The original content is not carried here for anyone: a tombstone reports
    that the record was removed and when, never what it said.
    """
    return {
        "removed": True,
        "removed_at_utc": str(row.get("removed_at_utc") or row.get("deleted_at_utc") or ""),
        "removal_operation": str(row.get("removal_operation") or "moderation_removal"),
        "removal_reason_code": str(row.get("removal_reason_code") or ""),
        "content_erased": bool(row.get("content_erased")),
        "text": TOMBSTONE_POST_TEXT if kind == "post" else TOMBSTONE_COMMENT_TEXT,
        "permanent": True,
        "can_delete": False,
        "is_author": False,
    }


def _post_tombstone(row: Dict[str, Any]) -> Dict[str, Any]:
    marker = _tombstone(row, "post")
    marker.update({
        "post_id": str(row.get("post_id") or ""),
        "kind": "removed",
        "created_at_utc": str(row.get("created_at_utc") or ""),
        "author": None, "attachments": [], "object": None, "hashtags": [],
        "reactions": {}, "viewer_reaction": "", "comment_count": 0,
        "recent_comments": [], "bookmarked": False, "visibility": "network",
    })
    return marker


def _comment_tombstone(row: Dict[str, Any]) -> Dict[str, Any]:
    marker = _tombstone(row, "comment")
    marker.update({
        "comment_id": str(row.get("comment_id") or ""),
        "post_id": str(row.get("post_id") or ""),
        "created_at_utc": str(row.get("created_at_utc") or ""),
        "author": None,
    })
    return marker


def _public_comment(doc: Dict[str, Any], row: Dict[str, Any], viewer_profile_id: str) -> Dict[str, Any]:
    if row.get("removed_at_utc") or row.get("deleted_at_utc"):
        return _comment_tombstone(row)

    author = _profile_row(doc, str(row.get("author_profile_id") or ""))
    return {
        "comment_id": str(row.get("comment_id") or ""),
        "post_id": str(row.get("post_id") or ""),
        "text": str(row.get("text") or "")[:1200],
        "created_at_utc": str(row.get("created_at_utc") or ""),
        "author": _public_profile(doc, author, viewer_profile_id) if author else None,
        "is_author": str(row.get("author_profile_id") or "") == viewer_profile_id,
        # Never true for anyone. Kept in the projection so a client reading the
        # old field cannot infer a control that no longer exists.
        "can_delete": False,
        "permanent": True,
        "removed": False,
    }


def _public_social_post(doc: Dict[str, Any], row: Dict[str, Any], viewer_profile_id: str) -> Dict[str, Any]:
    pid = str(row.get("post_id") or "")
    author = _profile_row(doc, str(row.get("author_profile_id") or ""))
    viewer_reaction = next((
        str(item.get("reaction") or "") for item in doc.get("post_reactions") or []
        if str(item.get("post_id") or "") == pid
        and str(item.get("profile_id") or "") == viewer_profile_id
    ), "")
    # Removed comments stay in the thread as tombstones: a reader who sees a
    # reply to nothing has been told less than one who sees that it was removed.
    comments = [item for item in doc.get("comments") or []
                if str(item.get("post_id") or "") == pid]
    live_comments = [item for item in comments if not item.get("deleted_at_utc")]
    bookmarked = any(
        str(item.get("post_id") or "") == pid
        and str(item.get("profile_id") or "") == viewer_profile_id
        for item in doc.get("bookmarks") or []
    )
    return {
        "post_id": pid,
        "text": str(row.get("text") or "")[:_MAX_MSG],
        "kind": str(row.get("kind") or "text"),
        "visibility": str(row.get("visibility") or "network"),
        "hashtags": [str(tag) for tag in (row.get("hashtags") or [])[:20]],
        "attachments": _public_attachments(row.get("attachments")),
        "object": dict(row.get("object_snapshot") or {}) if isinstance(row.get("object_snapshot"), dict) else None,
        "created_at_utc": str(row.get("created_at_utc") or ""),
        "updated_at_utc": str(row.get("updated_at_utc") or ""),
        "author": _publisher_identity(doc, row, viewer_profile_id),
        "attribution": _post_attribution(doc, row),
        "publisher_org_id": str(row.get("publisher_org_id") or ""),
        "reactions": _post_reaction_summary(doc, pid),
        "viewer_reaction": viewer_reaction,
        "comment_count": len(live_comments),
        "recent_comments": [_public_comment(doc, item, viewer_profile_id) for item in comments[-3:]],
        "bookmarked": bookmarked,
        "is_author": str(row.get("author_profile_id") or "") == viewer_profile_id,
        "can_delete": False,
        "permanent": True,
        "removed": False,
        "corrects_post_id": str(row.get("corrects_post_id") or ""),
        "corrected_by_post_ids": [
            str(item.get("post_id") or "") for item in doc.get("posts") or []
            if str(item.get("corrects_post_id") or "") == pid and not item.get("deleted_at_utc")
        ],
    }


_RESULT_METRIC_FIELDS = (
    ("net_profit_after_commission", "Net P&L"),
    ("net_profit", "Net P&L"),
    ("profit_factor_after_commission", "Profit factor"),
    ("profit_factor", "Profit factor"),
    ("max_drawdown", "Max drawdown"),
    ("trade_count", "Trades"),
    ("winning_pct", "Win rate"),
)


def attested_result_snapshot(
    source_id: str, summary: Dict[str, Any], *, origin: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a public result card exclusively from a scoped server job summary.

    Scope/ownership is checked by the HTTP adapter before this sanitizer is
    called. Only allowlisted summary fields cross into Community; raw trades,
    bars, paths, strategy source and job parameters never do.
    """
    sid = str(source_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", sid):
        raise CommunityError("Некорректный source ID.")
    if not isinstance(summary, dict) or str(summary.get("status") or "") != "done":
        raise CommunityError("Публиковать можно только завершённый результат.", 409)
    source_origin = dict(origin or {})
    result_type = "demo" if str(source_origin.get("type") or "").lower() == "demo" else "backtest"
    raw_metrics = summary.get("metrics") if isinstance(summary.get("metrics"), dict) else {}
    metrics: Dict[str, Any] = {}
    seen_labels = set()
    for key, label in _RESULT_METRIC_FIELDS:
        value = summary.get(key)
        if value is None:
            value = raw_metrics.get(key)
        if value is None or label in seen_labels or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(number):
            continue
        metrics[label] = int(number) if number.is_integer() else round(number, 4)
        seen_labels.add(label)
        if len(metrics) >= 5:
            break
    instrument = str(summary.get("instrument") or "").strip()[:40]
    timeframe = str(summary.get("timeframe") or "").strip()[:40]
    strategy = str(summary.get("strategy_name") or summary.get("class_name") or "Strategy").strip()[:120]
    timestamp = str(summary.get("finished_at_utc") or summary.get("created_at_utc") or "")[:40]
    public = {
        "snapshot_version": 1,
        "kind": "Demo Result" if result_type == "demo" else "Backtest Result",
        "source_type": f"{result_type}_result",
        "source_id": sid,
        "result_type": result_type,
        "timestamp_utc": timestamp,
        "title": " · ".join(value for value in (instrument, strategy) if value)[:180],
        "summary": " · ".join(value for value in (timeframe, "server-attested") if value),
        "metrics": metrics,
    }
    canonical = json.dumps(
        public, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    public["attestation"] = {
        "algorithm": "sha256",
        "digest": hashlib.sha256(canonical).hexdigest(),
    }
    return public


def _account_is_owner(user_id: Any) -> bool:
    """Whether this StratForge account is the platform owner.

    Read from the account store rather than from anything the client sends, so
    ownership of the company page cannot be claimed by asking for it.
    """
    uid = _safe_int(user_id)
    if uid <= 0:
        return False
    try:
        from . import account_auth
        return bool((account_auth.find_active_user(uid) or {}).get("is_owner"))
    except Exception:
        return False


DEFAULT_ORG_HANDLE = "stratforge_ai"
DEFAULT_ORG_NAME = "StratForge AI"
DEFAULT_ORG_DESCRIPTION = (
    "Официальная страница StratForge AI: продукт, релизы и материалы команды."
)
_ORG_ROLES = ("owner", "editor")


def _org_row(doc: Dict[str, Any], org_id: str) -> Optional[Dict[str, Any]]:
    wanted = str(org_id or "").strip()
    if not wanted:
        return None
    for row in doc.get("organizations") or []:
        if str(row.get("org_id") or "") == wanted:
            return row
        if str(row.get("handle") or "").lower() == wanted.lower().lstrip("@"):
            return row
    return None


def _org_role(doc: Dict[str, Any], org: Dict[str, Any], profile_id: str) -> str:
    """The caller's role on an organization, or "" when they have none.

    Roles are read from the stored organization rather than inferred from who
    is asking, so a client cannot claim one. AI publishers are deliberately not
    a role a person can hold: they are agent identities checked separately.
    """
    pid = str(profile_id or "")
    if not pid or not org:
        return ""
    if str(org.get("owner_profile_id") or "") == pid:
        return "owner"
    if pid in [str(value) for value in org.get("editor_profile_ids") or []]:
        return "editor"
    return ""


def _org_can_publish(doc: Dict[str, Any], org: Dict[str, Any], profile_id: str) -> bool:
    return _org_role(doc, org, profile_id) in _ORG_ROLES


def _ensure_default_organization(
    doc: Dict[str, Any], owner_profile_id: str,
) -> Optional[Dict[str, Any]]:
    """Create the StratForge AI page once, owned by the StratForge owner.

    The organization is a publishing identity, not a second account: it has no
    login, no password and no Telegram identity of its own. `created_at_utc` is
    the moment the page itself was created and is never the owner's account
    registration — the two milestones answer different questions.
    """
    pid = str(owner_profile_id or "")
    if not pid:
        return None
    existing = _org_row(doc, DEFAULT_ORG_HANDLE)
    if existing is not None:
        return existing
    now = _now_iso()
    row = {
        "org_id": "sforg_" + secrets.token_hex(8),
        "name": DEFAULT_ORG_NAME,
        "handle": DEFAULT_ORG_HANDLE,
        "description": DEFAULT_ORG_DESCRIPTION,
        "has_logo": False,
        "created_at_utc": now,
        "updated_at_utc": now,
        "owner_profile_id": pid,
        "editor_profile_ids": [],
        # An agent may only publish when it is listed here *and* the flow below
        # is enabled. Both are empty/false until a permissioned Orchestrator
        # path exists, so nothing can publish as the company on AI's behalf yet.
        "ai_publisher_agent_ids": [],
        "ai_publishing_enabled": False,
    }
    doc.setdefault("organizations", []).append(row)
    return row


def _org_follower_count(doc: Dict[str, Any], org_id: str) -> int:
    return sum(1 for row in doc.get("org_follows") or []
               if str(row.get("org_id") or "") == str(org_id))


def _org_follows(doc: Dict[str, Any], profile_id: str, org_id: str) -> bool:
    return any(str(row.get("org_id") or "") == str(org_id)
               and str(row.get("profile_id") or "") == str(profile_id)
               for row in doc.get("org_follows") or [])


def _org_post_count(doc: Dict[str, Any], org_id: str) -> int:
    return sum(1 for row in doc.get("posts") or []
               if str(row.get("publisher_org_id") or "") == str(org_id)
               and not row.get("deleted_at_utc"))


def _organization_milestone(org: Dict[str, Any]) -> Dict[str, Any]:
    """The organization's own first record.

    Deliberately distinct from a member's registration milestone: this is when
    the page was created, not when anybody registered an account.
    """
    return {
        "kind": "organization_created",
        "org_id": str(org.get("org_id") or ""),
        "name": str(org.get("name") or ""),
        "created_at_utc": str(org.get("created_at_utc") or ""),
    }


def _public_organization(
    doc: Dict[str, Any], org: Dict[str, Any], viewer_profile_id: str = "",
) -> Dict[str, Any]:
    org_id = str(org.get("org_id") or "")
    role = _org_role(doc, org, viewer_profile_id)
    return {
        "identity_kind": "organization",
        "org_id": org_id,
        "display_name": str(org.get("name") or DEFAULT_ORG_NAME)[:80],
        "username": str(org.get("handle") or DEFAULT_ORG_HANDLE)[:30],
        "role_label": "Организация",
        "description": str(org.get("description") or "")[:500],
        "has_logo": bool(org.get("has_logo")),
        "avatar_url": "",
        "created_at_utc": str(org.get("created_at_utc") or ""),
        "stats": {
            "posts": _org_post_count(doc, org_id),
            "followers": _org_follower_count(doc, org_id),
            "editors": len([v for v in org.get("editor_profile_ids") or [] if v]),
        },
        "is_following": bool(viewer_profile_id and _org_follows(doc, viewer_profile_id, org_id)),
        "viewer_role": role,
        "can_publish": role in _ORG_ROLES,
        "can_manage": role == "owner",
        # Reported so the interface can say the flow is pending rather than
        # pretending an AI publish path exists.
        "ai_publishing_enabled": bool(org.get("ai_publishing_enabled")),
    }


def _publisher_identity(
    doc: Dict[str, Any], row: Dict[str, Any], viewer_profile_id: str,
) -> Optional[Dict[str, Any]]:
    """Who the reader sees as the author of a post."""
    org_id = str(row.get("publisher_org_id") or "")
    if org_id:
        org = _org_row(doc, org_id)
        return _public_organization(doc, org, viewer_profile_id) if org else None
    author = _profile_row(doc, str(row.get("author_profile_id") or ""))
    if author is None:
        return None
    projected = _public_profile(doc, author, viewer_profile_id)
    projected["identity_kind"] = "profile"
    return projected


def _post_attribution(doc: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    """Who actually created the post, kept apart from who published it.

    A company post shows StratForge AI to readers; this records the person or
    the agent behind it. An agent is never reported as a person — the two are
    separate fields precisely so nothing has to guess.
    """
    actor_id = str(row.get("published_by_profile_id") or row.get("author_profile_id") or "")
    actor = _profile_row(doc, actor_id)
    agent = str(row.get("published_by_ai_agent") or "")
    return {
        "published_by_profile_id": actor_id,
        "published_by": str((actor or {}).get("display_name") or "") if actor else "",
        "published_by_ai_agent": agent,
        "is_ai": bool(agent),
    }


def publishable_identities(
    user_id: Any, *, user_uuid: Any = "",
) -> Dict[str, Any]:
    """Identities the caller may publish as: always their own profile, plus any
    organization on which they hold owner or editor."""
    with _LOCK:
        doc = _load()
        viewer = _viewer_profile(doc, user_id, user_uuid)
        viewer_id = str(viewer["profile_id"])
        rows = [{
            "identity_kind": "profile",
            "id": viewer_id,
            "display_name": str(viewer.get("display_name") or "Участник"),
            "username": str(viewer.get("username") or ""),
        }]
        for org in doc.get("organizations") or []:
            if not _org_can_publish(doc, org, viewer_id):
                continue
            rows.append({
                "identity_kind": "organization",
                "id": str(org.get("org_id") or ""),
                "display_name": str(org.get("name") or ""),
                "username": str(org.get("handle") or ""),
            })
        return {"ok": True, "identities": rows, "viewer_profile_id": viewer_id}


def organization_document(
    user_id: Any, org_id: str, *, user_uuid: Any = "", posts_limit: int = 20,
) -> Dict[str, Any]:
    """The company wall, projected like a member wall so the centre column can
    render either without a second layout."""
    with _LOCK:
        doc = _load()
        viewer = _viewer_profile(doc, user_id, user_uuid)
        viewer_id = str(viewer["profile_id"])
        org = _org_row(doc, org_id)
        if org is None:
            raise CommunityError("Организация не найдена.", 404)
        org_key = str(org.get("org_id") or "")
        posts = [
            _public_social_post(doc, row, viewer_id)
            for row in reversed(doc.get("posts") or [])
            if str(row.get("publisher_org_id") or "") == org_key
            and _post_visible(doc, row, viewer_id)
        ][:max(1, min(100, _safe_int(posts_limit, 20)))]
        _save(doc)
        return {
            "ok": True,
            "organization": _public_organization(doc, org, viewer_id),
            "registration": _organization_milestone(org),
            "posts": posts,
        }


def follow_organization(
    user_id: Any, org_id: str, *, following: bool = True, user_uuid: Any = "",
) -> Dict[str, Any]:
    with _LOCK:
        doc = _load()
        viewer = _viewer_profile(doc, user_id, user_uuid)
        viewer_id = str(viewer["profile_id"])
        org = _org_row(doc, org_id)
        if org is None:
            raise CommunityError("Организация не найдена.", 404)
        org_key = str(org.get("org_id") or "")
        rows = doc.setdefault("org_follows", [])
        rows[:] = [row for row in rows if not (
            str(row.get("org_id") or "") == org_key
            and str(row.get("profile_id") or "") == viewer_id
        )]
        if following:
            rows.append({"org_id": org_key, "profile_id": viewer_id,
                         "created_at_utc": _now_iso()})
        _save(doc)
        return {"ok": True, "organization": _public_organization(doc, org, viewer_id)}


def update_organization(
    user_id: Any, org_id: str, *, user_uuid: Any = "",
    description: Any = None, editors: Any = None,
) -> Dict[str, Any]:
    """Owner-only page management. Editors may publish, never re-assign roles."""
    with _LOCK:
        doc = _load()
        viewer = _viewer_profile(doc, user_id, user_uuid)
        viewer_id = str(viewer["profile_id"])
        org = _org_row(doc, org_id)
        if org is None:
            raise CommunityError("Организация не найдена.", 404)
        if _org_role(doc, org, viewer_id) != "owner":
            raise CommunityError("Управлять страницей может только владелец.", 403)
        if description is not None:
            org["description"] = str(description or "").strip()[:500]
        if editors is not None:
            wanted = []
            for value in list(editors)[:50]:
                pid = str(value or "").strip()
                if not pid or pid == str(org.get("owner_profile_id") or ""):
                    continue
                if _profile_row(doc, pid) is None:
                    raise CommunityError("Редактор должен быть участником.", 400)
                if pid not in wanted:
                    wanted.append(pid)
            org["editor_profile_ids"] = wanted
        org["updated_at_utc"] = _now_iso()
        _save(doc)
        return {"ok": True, "organization": _public_organization(doc, org, viewer_id)}


def create_social_post(
    user_id: Any, *, text: str = "", attachments: Any = None,
    visibility: str = "network", workspace_id: str = "", user_uuid: Any = "",
    idempotency_key: str = "", object_snapshot: Any = None,
    trusted_snapshot: bool = False, publish_as: str = "",
    ai_agent_id: str = "", corrects_post_id: str = "",
) -> Dict[str, Any]:
    uid = _safe_int(user_id)
    body = str(text or "").strip()
    if not body and not attachments and not object_snapshot:
        raise CommunityError("Публикация не может быть пустой.")
    if len(body) > _MAX_MSG:
        raise CommunityError("Текст публикации слишком длинный.")
    clean_visibility = str(visibility or "network").strip().lower()
    if clean_visibility not in _POST_VISIBILITY:
        raise CommunityError("Неизвестная видимость публикации.")
    if object_snapshot and not trusted_snapshot:
        raise CommunityError("Объект должен быть подтверждён сервером.", 403)
    workspace = _workspace_id(workspace_id)
    idem_hash = _idempotency_hash(idempotency_key)
    with _LOCK:
        doc = _load()
        author = _viewer_profile(doc, uid, user_uuid)
        author_id = str(author["profile_id"])
        if idem_hash:
            existing = next((row for row in doc.get("posts") or []
                             if str(row.get("author_profile_id") or "") == author_id
                             and str(row.get("idempotency_key_hash") or "") == idem_hash), None)
            if existing:
                return {"ok": True, "post": _public_social_post(doc, existing, author_id), "deduplicated": True}
        # A correction points at one of the author's own standing publications.
        # It never edits it: the original keeps its text, date and authorship,
        # and the two are read together.
        corrected = ""
        if str(corrects_post_id or "").strip():
            original = next((item for item in doc.get("posts") or []
                             if str(item.get("post_id") or "") == str(corrects_post_id).strip()), None)
            if original is None or original.get("deleted_at_utc"):
                raise CommunityError("Исправляемая публикация не найдена.", 404)
            if str(original.get("author_profile_id") or "") != author_id:
                raise CommunityError("Исправить можно только собственную публикацию.", 403)
            corrected = str(original.get("post_id") or "")
        post_id = "cpost_" + secrets.token_hex(8)
        stored_attachments = _validate_attachments(
            attachments, workspace_id=workspace, owner_id=post_id,
        )
        # Publishing as an organization is a permission, checked here on the
        # server. The client only names the identity it wants; it cannot grant
        # itself one.
        organization = None
        if str(publish_as or "").strip():
            organization = _org_row(doc, str(publish_as).strip())
            if organization is None:
                raise CommunityError("Организация не найдена.", 404)
            if str(ai_agent_id or "").strip():
                # An agent needs both an explicit allowlist entry and the flow
                # switched on. Neither is true yet, so this refuses rather than
                # letting an AI publish under the company name.
                allowed = [str(v) for v in organization.get("ai_publisher_agent_ids") or []]
                if not organization.get("ai_publishing_enabled") or str(ai_agent_id) not in allowed:
                    raise CommunityError("Публикация от имени AI ещё не разрешена.", 403)
            elif not _org_can_publish(doc, organization, author_id):
                raise CommunityError("Нет прав публиковать от имени организации.", 403)
        row = {
            "post_id": post_id,
            "author_profile_id": author_id,
            "workspace_id": workspace,
            "text": body,
            "kind": "object" if object_snapshot else ("image" if stored_attachments else "text"),
            "visibility": clean_visibility,
            "hashtags": sorted(set(tag.lower() for tag in _HASHTAG_RE.findall(body)))[:20],
            "attachments": stored_attachments,
            "created_at_utc": _now_iso(),
            "updated_at_utc": _now_iso(),
        }
        if corrected:
            row["corrects_post_id"] = corrected
        if organization is not None:
            # Publisher and actor are stored apart: readers see the company,
            # the audit trail keeps the person or the agent who created it.
            row["publisher_org_id"] = str(organization.get("org_id") or "")
            row["published_by_profile_id"] = author_id
            if str(ai_agent_id or "").strip():
                row["published_by_ai_agent"] = str(ai_agent_id).strip()[:80]
        if object_snapshot:
            row["object_snapshot"] = _json_safe(dict(object_snapshot))
        if idem_hash:
            row["idempotency_key_hash"] = idem_hash
        doc.setdefault("posts", []).append(row)
        doc["posts"] = doc["posts"][-5000:]
        _save(doc)
        return {"ok": True, "post": _public_social_post(doc, row, author_id), "deduplicated": False}


def social_feed(
    user_id: Any, *, user_uuid: Any = "", scope: str = "for-you",
    cursor: str = "", limit: int = 20, query: str = "", hashtag: str = "",
    saved_only: bool = False,
) -> Dict[str, Any]:
    lim = max(1, min(50, _safe_int(limit, 20)))
    mode = str(scope or "for-you").strip().lower()
    if mode not in {"for-you", "following"}:
        raise CommunityError("Неизвестный режим ленты.")
    offset = 0
    token = str(cursor or "").strip()
    if token:
        match = re.fullmatch(r"c_(\d{1,8})", token)
        if not match:
            raise CommunityError("Некорректный cursor.")
        offset = int(match.group(1))
    clean_query = str(query or "").strip().lower()[:120]
    clean_hashtag = str(hashtag or "").strip().lstrip("#").lower()[:40]
    with _LOCK:
        doc = _load()
        viewer = _viewer_profile(doc, user_id, user_uuid)
        viewer_id = str(viewer["profile_id"])
        saved_ids = {
            str(row.get("post_id") or "") for row in doc.get("bookmarks") or []
            if str(row.get("profile_id") or "") == viewer_id
        }
        rows = []
        for row in reversed(doc.get("posts") or []):
            # Recommendation carries only what may be shown publicly. A post
            # kept to its own wall never enters it — not even for its author,
            # who would otherwise be the one person seeing a private post in a
            # feed that is supposed to be the public surface.
            if str(row.get("visibility") or "network") not in _RECOMMENDABLE_VISIBILITY:
                continue
            if not _post_visible(doc, row, viewer_id):
                continue
            author_id = str(row.get("author_profile_id") or "")
            if mode == "following" and author_id != viewer_id and not _follows(doc, viewer_id, author_id):
                continue
            if saved_only and str(row.get("post_id") or "") not in saved_ids:
                continue
            if clean_hashtag and clean_hashtag not in [str(tag).lower() for tag in row.get("hashtags") or []]:
                continue
            if clean_query:
                author = _profile_row(doc, author_id) or {}
                haystack = " ".join((
                    str(row.get("text") or ""), str(author.get("display_name") or ""),
                    str(author.get("username") or ""), " ".join(row.get("hashtags") or []),
                )).lower()
                if clean_query not in haystack:
                    continue
            rows.append(row)
        page = rows[offset:offset + lim]
        next_offset = offset + len(page)
        profiles = [
            _public_profile(doc, row, viewer_id) for row in doc.get("profiles") or []
            if str(row.get("profile_id") or "") != viewer_id
            and not _social_blocked(doc, viewer_id, str(row.get("profile_id") or ""))
        ]
        profiles.sort(key=lambda item: (
            item.get("is_following", False),
            -int((item.get("stats") or {}).get("followers") or 0),
        ))
        _save(doc)
        return {
            "ok": True,
            "scope": mode,
            "viewer": _public_profile(doc, viewer, viewer_id),
            "posts": [_public_social_post(doc, row, viewer_id) for row in page],
            "next_cursor": f"c_{next_offset}" if next_offset < len(rows) else "",
            "recommended_profiles": profiles[:8],
            "total_visible": len(rows),
            # One source of truth for the rule, so the interface states exactly
            # what the server enforces rather than a paraphrase of it.
            "permanent_record": PERMANENT_RECORD,
            "permanence_notice": PERMANENT_RECORD_NOTICE,
        }


def react_to_post(
    user_id: Any, post_id: str, *, reaction: str = "support", user_uuid: Any = "",
) -> Dict[str, Any]:
    kind = str(reaction or "").strip().lower()
    if kind and kind not in _REACTIONS:
        raise CommunityError("Неизвестная реакция.")
    with _LOCK:
        doc = _load()
        viewer = _viewer_profile(doc, user_id, user_uuid)
        viewer_id = str(viewer["profile_id"])
        post = next((row for row in doc.get("posts") or []
                     if str(row.get("post_id") or "") == str(post_id or "")), None)
        if post is None or not _post_visible(doc, post, viewer_id):
            raise CommunityError("Публикация не найдена.", 404)
        rows = doc.setdefault("post_reactions", [])
        rows[:] = [row for row in rows if not (
            str(row.get("post_id") or "") == str(post_id)
            and str(row.get("profile_id") or "") == viewer_id
        )]
        if kind:
            rows.append({"post_id": str(post_id), "profile_id": viewer_id,
                         "reaction": kind, "created_at_utc": _now_iso()})
        _save(doc)
        return {"ok": True, "post": _public_social_post(doc, post, viewer_id)}


def comment_on_post(
    user_id: Any, post_id: str, *, text: str, user_uuid: Any = "",
) -> Dict[str, Any]:
    body = str(text or "").strip()
    if not body or len(body) > 1200:
        raise CommunityError("Комментарий пустой или слишком длинный.")
    with _LOCK:
        doc = _load()
        viewer = _viewer_profile(doc, user_id, user_uuid)
        viewer_id = str(viewer["profile_id"])
        post = next((row for row in doc.get("posts") or []
                     if str(row.get("post_id") or "") == str(post_id or "")), None)
        if post is None or not _post_visible(doc, post, viewer_id):
            raise CommunityError("Публикация не найдена.", 404)
        row = {
            "comment_id": "ccom_" + secrets.token_hex(7),
            "post_id": str(post_id),
            "author_profile_id": viewer_id,
            "user_id": _safe_int(user_id),
            "text": body,
            "created_at_utc": _now_iso(),
        }
        canonical = _resolved_user_uuid(user_id, user_uuid)
        if canonical:
            row["user_uuid"] = canonical
        doc.setdefault("comments", []).append(row)
        doc["comments"] = doc["comments"][-10000:]
        _save(doc)
        return {"ok": True, "comment": _public_comment(doc, row, viewer_id),
                "post": _public_social_post(doc, post, viewer_id)}


def bookmark_post(
    user_id: Any, post_id: str, *, bookmarked: bool = True, user_uuid: Any = "",
) -> Dict[str, Any]:
    with _LOCK:
        doc = _load()
        viewer = _viewer_profile(doc, user_id, user_uuid)
        viewer_id = str(viewer["profile_id"])
        post = next((row for row in doc.get("posts") or []
                     if str(row.get("post_id") or "") == str(post_id or "")), None)
        if post is None or not _post_visible(doc, post, viewer_id):
            raise CommunityError("Публикация не найдена.", 404)
        rows = doc.setdefault("bookmarks", [])
        rows[:] = [row for row in rows if not (
            str(row.get("post_id") or "") == str(post_id)
            and str(row.get("profile_id") or "") == viewer_id
        )]
        if bookmarked:
            rows.append({"post_id": str(post_id), "profile_id": viewer_id,
                         "created_at_utc": _now_iso()})
        _save(doc)
        return {"ok": True, "bookmarked": bool(bookmarked),
                "post": _public_social_post(doc, post, viewer_id)}


def delete_social_post(
    user_id: Any, post_id: str, *, user_uuid: Any = "", moderator: bool = False,
) -> Dict[str, Any]:
    """Refuse author deletion; owner moderation hides reported content only.

    See the permanent-record contract above. Nothing here erases a row.
    """
    with _LOCK:
        doc = _load()
        viewer = _viewer_profile(doc, user_id, user_uuid)
        viewer_id = str(viewer["profile_id"])
        post = next((row for row in doc.get("posts") or []
                     if str(row.get("post_id") or "") == str(post_id or "")), None)
        if post is None or post.get("deleted_at_utc"):
            raise CommunityError("Публикация не найдена.", 404)
        if str(post.get("author_profile_id") or "") == viewer_id:
            raise CommunityError(PERMANENT_RECORD_NOTICE, 403)
        if not moderator:
            raise CommunityError("Нельзя удалить чужую публикацию.", 403)
        post["hidden_at_utc"] = _now_iso()
        post["deleted_at_utc"] = post["hidden_at_utc"]
        post["deleted_by_profile_id"] = viewer_id
        post["moderated"] = True
        _save(doc)
        return {
            "ok": True, "post_id": str(post_id), "deleted": True,
            "soft_delete": True, "moderated": True, "record_retained": True,
        }


def delete_social_comment(
    user_id: Any, comment_id: str, *, user_uuid: Any = "", moderator: bool = False,
) -> Dict[str, Any]:
    """Refuse author deletion; owner moderation hides reported content only."""
    with _LOCK:
        doc = _load()
        viewer = _viewer_profile(doc, user_id, user_uuid)
        viewer_id = str(viewer["profile_id"])
        comment = next((row for row in doc.get("comments") or []
                        if str(row.get("comment_id") or "") == str(comment_id or "")), None)
        if comment is None or comment.get("deleted_at_utc"):
            raise CommunityError("Комментарий не найден.", 404)
        if str(comment.get("author_profile_id") or "") == viewer_id:
            raise CommunityError(PERMANENT_RECORD_NOTICE, 403)
        if not moderator:
            raise CommunityError("Нельзя удалить чужой комментарий.", 403)
        comment["hidden_at_utc"] = _now_iso()
        comment["deleted_at_utc"] = comment["hidden_at_utc"]
        comment["deleted_by_profile_id"] = viewer_id
        comment["moderated"] = True
        post = next((row for row in doc.get("posts") or []
                     if str(row.get("post_id") or "") == str(comment.get("post_id") or "")), None)
        _save(doc)
        return {
            "ok": True, "comment_id": str(comment_id), "deleted": True,
            "soft_delete": True, "moderated": True, "record_retained": True,
            "post": _public_social_post(doc, post, viewer_id) if post else None,
        }


def _content_hash(row: Dict[str, Any]) -> str:
    """A fingerprint of what a removal covered.

    Keeping the hash rather than the text is the point of a hard erasure: the
    request is honoured in full, and a later claim about what the record said
    can still be checked against the audit trail.
    """
    payload = json.dumps({
        "text": str(row.get("text") or ""),
        "attachments": _json_safe(row.get("attachments") or []),
        "object": _json_safe(row.get("object_snapshot") or {}),
    }, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _removal_target(doc: Dict[str, Any], target_type: str, target_id: str):
    kind = str(target_type or "").strip().lower()
    if kind not in _REMOVAL_TARGETS:
        raise CommunityError("Удалить можно публикацию или комментарий.", 400)
    collection, key = _REMOVAL_TARGETS[kind]
    row = next((item for item in doc.get(collection) or []
                if str(item.get(key) or "") == str(target_id or "")), None)
    if row is None:
        raise CommunityError("Запись не найдена.", 404)
    return kind, row


def _removal_record(row: Dict[str, Any], kind: str) -> Dict[str, Any]:
    """What the interface (or an agent) is told before anything is removed.

    An administrative removal is shown before it is performed: which object,
    whose it is, when it was published. The content itself is not echoed back.
    """
    author = str(row.get("author_profile_id") or "")
    return {
        "target_type": kind,
        "target_id": str(row.get("post_id") or row.get("comment_id") or ""),
        "author_profile_id": author,
        "created_at_utc": str(row.get("created_at_utc") or ""),
        "object_version": str(row.get("updated_at_utc") or row.get("created_at_utc") or ""),
        "content_hash": _content_hash(row),
        "content_length": len(str(row.get("text") or "")),
        "attachment_count": len(list(row.get("attachments") or [])),
        "already_removed": bool(row.get("removed_at_utc") or row.get("deleted_at_utc")),
        "content_erased": bool(row.get("content_erased")),
    }


def _apply_removal(
    doc: Dict[str, Any], kind: str, row: Dict[str, Any], *,
    operation: str, reason_code: str, reason: str, source: str,
    actor: str, ai_agent_id: str, authority_user_id: Any,
    authority_user_uuid: str, correlation_id: str,
) -> Dict[str, Any]:
    """Write the audit record, then remove. Never the other way round.

    The ledger entry is appended before the object is touched, so a removal
    interrupted halfway still leaves its trace. Nothing in this module deletes
    from `audit_log`.
    """
    audit_id = "sfa_" + secrets.token_hex(8)
    chain = [f"owner:{_safe_int(authority_user_id)}"]
    if actor == "ai":
        # The agent is the hand, never the authority. It is appended to the
        # chain rather than replacing the owner at the head of it.
        chain.append(f"ai:{ai_agent_id}")
    entry = dict(_removal_record(row, kind))
    entry.update({
        "audit_id": audit_id,
        "correlation_id": str(correlation_id or "").strip()[:64] or audit_id,
        "operation": operation,
        "reason_code": reason_code,
        "reason_label": _REMOVAL_REASON_CODES[reason_code],
        "reason": str(reason or "").strip()[:1000],
        "source": source,
        "actor": actor,
        "ai_agent_id": ai_agent_id,
        "authority_user_id": _safe_int(authority_user_id),
        "authority_user_uuid": str(authority_user_uuid or ""),
        "actor_chain": chain,
        "occurred_at_utc": _now_iso(),
    })
    doc.setdefault("audit_log", []).append(entry)

    now = entry["occurred_at_utc"]
    row["removed_at_utc"] = now
    # Kept in step so every existing visibility filter keeps excluding the row.
    row["deleted_at_utc"] = now
    row["removal_operation"] = operation
    row["removal_reason_code"] = reason_code
    row["removal_audit_id"] = audit_id
    row["removed_by_user_id"] = _safe_int(authority_user_id)
    row["moderated"] = True
    if operation == "hard_erasure":
        row["content_erased"] = True
        row["text"] = ""
        row["hashtags"] = []
        row["attachments"] = []
        row.pop("object_snapshot", None)
    return entry


def preview_owner_removal(
    owner_id: Any, target_type: str, target_id: str,
) -> Dict[str, Any]:
    """Show what an administrative removal would cover, changing nothing.

    This is the step an AI must take before acting on an owner's instruction:
    name the object and the grounds, then let the owner's authority carry it.
    """
    if not _account_is_owner(owner_id):
        raise CommunityError("Административное удаление доступно только владельцу.", 403)
    with _LOCK:
        doc = _load()
        kind, row = _removal_target(doc, target_type, target_id)
        author = _profile_row(doc, str(row.get("author_profile_id") or ""))
        preview = _removal_record(row, kind)
    preview["author_display_name"] = str((author or {}).get("display_name") or "")
    preview["author_username"] = str((author or {}).get("username") or "")
    preview["reason_codes"] = dict(_REMOVAL_REASON_CODES)
    preview["hard_erasure_reason_codes"] = sorted(_HARD_ERASURE_REASON_CODES)
    preview["default_operation"] = "moderation_removal"
    return {"ok": True, "preview": preview}


def owner_remove_content(
    owner_id: Any, target_type: str, target_id: str, *,
    reason_code: str, reason: str, operation: str = "moderation_removal",
    actor: str = "owner", ai_agent_id: str = "", source: str = "owner_api",
    correlation_id: str = "", owner_user_uuid: Any = "",
) -> Dict[str, Any]:
    """The disclosed administrative exception to the permanent record.

    Owner authority is read from the account store, never from what the caller
    claims. A reason code and a written reason are both required: the code so
    the trail can be read as data, the text so it can be read as an account of
    a decision. Clearing content is available only on grounds that demand it.
    """
    if not _account_is_owner(owner_id):
        raise CommunityError("Административное удаление доступно только владельцу.", 403)
    op = str(operation or "moderation_removal").strip().lower()
    if op not in _REMOVAL_OPERATIONS:
        raise CommunityError("Неизвестный тип операции удаления.", 400)
    code = str(reason_code or "").strip().lower()
    if code not in _REMOVAL_REASON_CODES:
        raise CommunityError("Укажите код основания удаления.", 400)
    if op == "hard_erasure" and code not in _HARD_ERASURE_REASON_CODES:
        raise CommunityError(
            "Полное стирание содержимого допустимо только по правовым, "
            "приватным или security-основаниям.", 400,
        )
    grounds = str(reason or "").strip()
    if len(grounds) < 8:
        raise CommunityError("Укажите основание удаления (не короче 8 символов).", 400)
    who = str(actor or "owner").strip().lower()
    if who not in ("owner", "ai"):
        raise CommunityError("Неизвестный исполнитель удаления.", 400)
    agent = str(ai_agent_id or "").strip()[:64]
    if who == "ai" and not agent:
        raise CommunityError("Для удаления по просьбе владельца укажите агента.", 400)
    origin = str(source or "owner_api").strip().lower()
    if origin not in _REMOVAL_SOURCES:
        raise CommunityError("Неизвестный источник запроса.", 400)

    with _LOCK:
        doc = _load()
        kind, row = _removal_target(doc, target_type, target_id)
        if row.get("removed_at_utc") and op != "hard_erasure":
            raise CommunityError("Запись уже удалена администрацией.", 409)
        if row.get("content_erased"):
            raise CommunityError("Содержимое уже стёрто.", 409)
        entry = _apply_removal(
            doc, kind, row, operation=op, reason_code=code, reason=grounds,
            source=origin, actor=who, ai_agent_id=agent,
            authority_user_id=owner_id,
            authority_user_uuid=_resolved_user_uuid(owner_id, owner_user_uuid),
            correlation_id=correlation_id,
        )
        _save(doc)
        return {"ok": True, "removed": True, "operation": op, "audit": dict(entry)}


def owner_audit_log(owner_id: Any, *, limit: int = 100) -> Dict[str, Any]:
    """The append-only record of every administrative removal.

    Owner-visible and never pruned. There is deliberately no function here that
    removes an entry: an audit trail a user can edit is not an audit trail.
    """
    if not _account_is_owner(owner_id):
        raise CommunityError("Журнал удалений доступен только владельцу.", 403)
    lim = max(1, min(500, _safe_int(limit, 100)))
    with _LOCK:
        doc = _load()
        entries = list(doc.get("audit_log") or [])
    return {
        "ok": True, "entries": entries[-lim:][::-1], "total": len(entries),
        "reason_codes": dict(_REMOVAL_REASON_CODES),
    }


def block_social_profile(
    user_id: Any, target_profile_id: str, *, blocked: bool = True, user_uuid: Any = "",
) -> Dict[str, Any]:
    with _LOCK:
        doc = _load()
        viewer = _viewer_profile(doc, user_id, user_uuid)
        viewer_id = str(viewer["profile_id"])
        target = _profile_row(doc, target_profile_id)
        if target is None:
            raise CommunityError("Профиль не найден.", 404)
        target_id = str(target["profile_id"])
        if target_id == viewer_id:
            raise CommunityError("Нельзя заблокировать себя.")
        rows = doc.setdefault("social_blocks", [])
        rows[:] = [row for row in rows if not (
            str(row.get("blocker_profile_id") or "") == viewer_id
            and str(row.get("target_profile_id") or "") == target_id
        )]
        if blocked:
            rows.append({"blocker_profile_id": viewer_id, "target_profile_id": target_id,
                         "created_at_utc": _now_iso()})
            # Blocking severs both follow directions immediately.
            doc["follows"] = [row for row in doc.get("follows") or [] if {
                str(row.get("follower_profile_id") or ""),
                str(row.get("target_profile_id") or ""),
            } != {viewer_id, target_id}]
        _save(doc)
        return {"ok": True, "blocked": bool(blocked), "profile_id": target_id}


def report_social_target(
    user_id: Any, target_id: str, *, target_type: str = "post", reason: str = "",
    user_uuid: Any = "",
) -> Dict[str, Any]:
    clean_type = str(target_type or "post").strip().lower()
    if clean_type not in {"post", "profile", "comment"}:
        raise CommunityError("Неизвестный тип жалобы.")
    clean_target = str(target_id or "").strip()[:100]
    clean_reason = str(reason or "").strip()[:500]
    if not clean_target or not clean_reason:
        raise CommunityError("Укажите объект и причину жалобы.")
    with _LOCK:
        doc = _load()
        viewer = _viewer_profile(doc, user_id, user_uuid)
        row = {
            "report_id": "crep_" + secrets.token_hex(7),
            "from_profile_id": str(viewer["profile_id"]),
            "target_id": clean_target,
            "target_type": clean_type,
            "reason": clean_reason,
            "status": "open",
            "created_at_utc": _now_iso(),
        }
        doc.setdefault("reports", []).append(row)
        _save(doc)
        return {"ok": True, "report_id": row["report_id"], "status": "open"}


def social_moderation_queue(*, status: str = "open", limit: int = 100) -> Dict[str, Any]:
    """Owner-facing safe moderation queue; reporter account identifiers stay private."""
    wanted = str(status or "open").strip().lower()
    if wanted not in {"open", "resolved", "dismissed", "all"}:
        raise CommunityError("Неизвестный статус moderation queue.")
    lim = max(1, min(500, _safe_int(limit, 100)))
    with _LOCK:
        doc = _load()
        rows = []
        for row in reversed(doc.get("reports") or []):
            row_status = str(row.get("status") or "open")
            if wanted != "all" and row_status != wanted:
                continue
            rows.append({
                "report_id": str(row.get("report_id") or ""),
                "target_id": str(row.get("target_id") or ""),
                "target_type": str(row.get("target_type") or "unknown"),
                "reason": str(row.get("reason") or "")[:500],
                "status": row_status,
                "resolution": str(row.get("resolution") or ""),
                "created_at_utc": str(row.get("created_at_utc") or ""),
                "resolved_at_utc": str(row.get("resolved_at_utc") or ""),
            })
            if len(rows) >= lim:
                break
        return {"ok": True, "reports": rows, "status": wanted}


def moderate_social_report(
    owner_id: Any, report_id: str, *, action: str = "resolve", note: str = "",
    owner_user_uuid: str = "",
) -> Dict[str, Any]:
    """Resolve/dismiss a report and optionally soft-delete reported content."""
    decision = str(action or "resolve").strip().lower()
    if decision not in {"resolve", "dismiss", "remove"}:
        raise CommunityError("Неизвестное действие модерации.")
    with _LOCK:
        doc = _load()
        report = next((row for row in doc.get("reports") or []
                       if str(row.get("report_id") or "") == str(report_id or "")), None)
        if report is None:
            raise CommunityError("Жалоба не найдена.", 404)
        removed = False
        if decision == "remove":
            target_id = str(report.get("target_id") or "")
            target_type = str(report.get("target_type") or "")
            collection = "posts" if target_type == "post" else "comments" if target_type == "comment" else ""
            if not collection:
                raise CommunityError("Для профиля доступно только решение жалобы; блокировка аккаунта выполняется через управление пользователями.")
            target_key = "post_id" if collection == "posts" else "comment_id"
            target = next((row for row in doc.get(collection) or []
                           if str(row.get(target_key) or "") == target_id), None)
            if target is None:
                raise CommunityError("Объект жалобы не найден.", 404)
            if not target.get("deleted_at_utc"):
                # One removal path, one audit trail: content taken down from
                # the report queue is recorded exactly like any other.
                grounds = str(note or "").strip()
                if len(grounds) < 8:
                    raise CommunityError(
                        "Укажите основание удаления (не короче 8 символов).", 400,
                    )
                _apply_removal(
                    doc, "post" if collection == "posts" else "comment", target,
                    operation="moderation_removal", reason_code="moderation_policy",
                    reason=grounds, source="moderation_queue", actor="owner",
                    ai_agent_id="", authority_user_id=owner_id,
                    authority_user_uuid=_resolved_user_uuid(owner_id, owner_user_uuid),
                    correlation_id=str(report_id or ""),
                )
                removed = True
        now = _now_iso()
        report["status"] = "dismissed" if decision == "dismiss" else "resolved"
        report["resolution"] = decision
        report["moderation_note"] = str(note or "").strip()[:500]
        report["resolved_at_utc"] = now
        report["moderated_by_user_id"] = _safe_int(owner_id)
        canonical = _resolved_user_uuid(owner_id, owner_user_uuid)
        if canonical:
            report["moderated_by_user_uuid"] = canonical
        _save(doc)
        return {
            "ok": True, "report_id": str(report_id), "status": report["status"],
            "resolution": decision, "content_removed": removed,
        }


def _identity_refresh_needed(
    row: Dict[str, Any], *, user_uuid: str, display_name: str,
    username: str, role_label: str,
) -> bool:
    """Would `_ensure_profile_in_doc` change anything a reader can observe?

    Mirrors that function's update rules one for one. `updated_at_utc` is
    deliberately not counted: bumping it on every poll is write amplification
    with nothing behind it.
    """
    if user_uuid and not str(row.get("user_uuid") or ""):
        return True
    if display_name and not str(row.get("display_name") or "").strip():
        return True
    if username and str(row.get("username") or "").startswith("sf_"):
        return True
    if role_label and str(role_label).strip()[:40] != str(row.get("role_label") or ""):
        return True
    return False


def chat_identity(
    user_id: Any, *, user_uuid: Any = "", display_name: str = "",
    username: str = "", role_label: str = "Участник",
) -> Dict[str, Any]:
    """Private service-to-service identity for SF Chat; never serialize raw."""
    from . import storage_router
    if storage_router.production_enabled():
        # SF Chat resolves the caller on every request, including every poll
        # tick, and this used to load *and rewrite* the whole Community
        # document each time. When the stored profile already matches what the
        # account would write, one indexed lookup answers it and nothing is
        # written; anything that would actually change still takes the
        # document path below.
        from .production_storage import StorageError
        try:
            found = storage_router.community_profile_by_identity(
                _safe_int(user_id), _resolved_user_uuid(user_id, user_uuid),
            )
        except StorageError as exc:
            raise CommunityError(
                f"Production Community repository unavailable ({exc.code}).", 503,
            ) from None
        if found is not None:
            row = dict(found.get("document") or {})
            if not row.get("profile_id"):
                row["profile_id"] = str(found.get("profile_id") or "")
            if not _identity_refresh_needed(
                row, user_uuid=_resolved_user_uuid(user_id, user_uuid),
                display_name=display_name, username=username, role_label=role_label,
            ):
                return {
                    "profile_id": str(row["profile_id"]),
                    "user_id": _safe_int(row.get("user_id")),
                    "user_uuid": str(row.get("user_uuid") or ""),
                    "display_name": str(row.get("display_name") or "Участник"),
                    "username": str(row.get("username") or ""),
                }
    with _LOCK:
        doc = _load()
        row = _ensure_profile_in_doc(
            doc, user_id, user_uuid=user_uuid, display_name=display_name,
            username=username, role_label=role_label,
        )
        _save(doc)
        return {
            "profile_id": str(row["profile_id"]),
            "user_id": _safe_int(row.get("user_id")),
            "user_uuid": str(row.get("user_uuid") or ""),
            "display_name": str(row.get("display_name") or "Участник"),
            "username": str(row.get("username") or ""),
        }


def chat_target(sender_profile_id: str, target_profile_id: str) -> Dict[str, Any]:
    """Resolve a permitted human recipient for the unified SF Chat service."""
    sender = str(sender_profile_id or "").strip()
    target_id = str(target_profile_id or "").strip()
    with _LOCK:
        doc = _load()
        target = _profile_row(doc, target_id)
        if target is None or not sender or sender == target_id:
            raise CommunityError("Получатель не найден.", 404)
        if _social_blocked(doc, sender, target_id):
            raise CommunityError("Личные сообщения этому пользователю недоступны.", 403)
        policy = str(target.get("allow_messages") or "everyone")
        if policy == "nobody" or (policy == "following" and not _follows(doc, target_id, sender)):
            raise CommunityError("Пользователь ограничил входящие сообщения.", 403)
        return {
            "profile_id": target_id,
            "user_id": _safe_int(target.get("user_id")),
            "user_uuid": str(target.get("user_uuid") or ""),
            "public": _public_profile(doc, target, sender),
        }


def chat_public_profiles(viewer_profile_id: str, profile_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Profiles for a chat page.

    SF Chat asks for this on every conversation list and every history read.
    In Production it is one indexed statement over the requested ids; it used
    to load the whole Community document — every profile, post, comment,
    reaction and follow of every user — to project a handful of participants.
    """
    wanted = {str(value or "") for value in profile_ids if str(value or "")}
    if not wanted:
        return {}
    from . import storage_router
    if storage_router.production_enabled():
        from .production_storage import StorageError
        try:
            rows = storage_router.community_public_profiles(viewer_profile_id, sorted(wanted))
        except StorageError as exc:
            raise CommunityError(
                f"Production Community repository unavailable ({exc.code}).", 503,
            ) from None
        return {
            str(row.get("profile_id") or ""): _relational_profile(row, viewer_profile_id)
            for row in rows
        }
    with _LOCK:
        doc = _load()
        return {
            str(row.get("profile_id") or ""): _public_profile(doc, row, viewer_profile_id)
            for row in doc.get("profiles") or []
            if str(row.get("profile_id") or "") in wanted
        }


def social_avatar(profile_id: str) -> Optional[Path]:
    """Resolve a profile avatar internally without exposing account identifiers."""
    with _LOCK:
        row = _profile_row(_load(), profile_id)
        if row is None:
            return None
        user_id = _safe_int(row.get("user_id"))
    if user_id <= 0:
        return None
    try:
        from . import account_auth
        return account_auth.avatar_file(user_id)
    except Exception:
        return None
