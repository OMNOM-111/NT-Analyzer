"""Community contour — users among themselves (NOT owner Orchestrator).

Storage: ``data/runtime/community.json`` (messages, posts, strategy cards,
ratings, moderation). Telegram duplicate is a separate optional channel and
must never write into owner Orchestrator topics.
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

from . import runtime_env


class CommunityError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


_LOCK = threading.RLock()
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MAX_MSG = 4000
_MAX_ATTACHMENTS = 3
_MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024
_COLLECTIONS = (
    "accounts", "messages", "posts", "strategies", "copies", "reports", "blocks",
    "shared_reports", "requests",
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


def _empty_doc() -> Dict[str, Any]:
    return {"version": 3, **{key: [] for key in _COLLECTIONS}}


def _root() -> Path:
    return _PROJECT_ROOT


def _store_path() -> Path:
    return runtime_env.data_root(_root()) / "runtime" / "community.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load() -> Dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return _empty_doc()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_doc()
    if not isinstance(doc, dict):
        return _empty_doc()
    for key in _COLLECTIONS:
        rows = doc.get(key)
        doc[key] = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    # Treat the on-disk version as untrusted input as well.  The normalized
    # document is always written in the current format.
    doc["version"] = 3
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
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(_json_safe(doc), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
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
                   display_name: str = "") -> Dict[str, Any]:
    rows = doc.setdefault("accounts", [])
    row = next((item for item in rows
                if _safe_int(item.get("user_id")) == int(user_id)
                and _same_workspace(item, workspace_id)), None)
    now = _now_iso()
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
        rows.append(row)
    else:
        if str(display_name or "").strip():
            row["display_name"] = str(display_name).strip()[:80]
        row["updated_at_utc"] = now
    return row


def feed(*, limit: int = 50, workspace_id: str = "", channel_id: str = "") -> Dict[str, Any]:
    workspace = _workspace_id(workspace_id)
    channel = _channel_id(channel_id) if str(channel_id or "").strip() else ""
    with _LOCK:
        doc = _load()
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
                 attachments: Any = None) -> Dict[str, Any]:
    uid = int(user_id or 0)
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
        if _blocked(doc, uid, workspace):
            raise CommunityError("Вы заблокированы в community.", 403)
        if idem_hash:
            existing = next((item for item in doc.get("messages") or []
                             if _safe_int(item.get("user_id")) == uid
                             and _same_workspace(item, workspace)
                             and item.get("idempotency_key_hash") == idem_hash), None)
            if existing is not None:
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
        if root_id:
            row["thread_root_id"] = root_id
        stored_attachments = _validate_attachments(
            attachments, workspace_id=workspace, owner_id=message_id,
        )
        if stored_attachments:
            row["attachments"] = stored_attachments
        if idem_hash:
            row["idempotency_key_hash"] = idem_hash
        _touch_account(doc, uid, workspace, display_name)
        doc.setdefault("messages", []).append(row)
        doc["messages"] = doc["messages"][-1000:]
        _save(doc)
    return {"ok": True, "message": _public_message(row), "telegram_mirror": False, "deduplicated": False}


def share_report(user_id: Any, *, title: str, summary: str = "", metrics: Any = None,
                 display_name: str = "", workspace_id: str = "", channel_id: str = "reports",
                 attachments: Any = None) -> Dict[str, Any]:
    """Share an explicit user report without turning it into an AI task."""
    uid = int(user_id or 0)
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
                   workspace_id: str = "", channel_id: str = "reports") -> Dict[str, Any]:
    """Create a transparent in-product request for a report, data or screenshot."""
    uid = int(user_id or 0)
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
    if target < 0:
        raise CommunityError("Некорректный получатель запроса.")
    with _LOCK:
        doc = _load()
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
        _touch_account(doc, uid, workspace, display_name)
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
) -> Dict[str, Any]:
    uid = int(user_id or 0)
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
        if _blocked(doc, uid, workspace):
            raise CommunityError("Вы заблокированы в community.", 403)
        if idem_hash:
            existing = next((item for item in doc.get("strategies") or []
                             if _safe_int(item.get("user_id")) == uid
                             and _same_workspace(item, workspace)
                             and item.get("idempotency_key_hash") == idem_hash), None)
            if existing is not None:
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
        if idem_hash:
            row["idempotency_key_hash"] = idem_hash
        _touch_account(doc, uid, workspace, display_name)
        doc.setdefault("strategies", []).append(row)
        doc["strategies"] = doc["strategies"][-500:]
        _save(doc)
    return {"ok": True, "strategy": row, "deduplicated": False}


def copy_strategy(user_id: Any, strategy_id: str, *, workspace_id: str = "",
                  idempotency_key: str = "") -> Dict[str, Any]:
    uid = int(user_id or 0)
    sid = str(strategy_id or "").strip()
    workspace = _workspace_id(workspace_id)
    idem_hash = _idempotency_hash(idempotency_key)
    if uid <= 0:
        raise CommunityError("Требуется вход.", 401)
    with _LOCK:
        doc = _load()
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
            return {
                "ok": True, "copy": existing, "strategy": src, "deduplicated": True,
                "import": _pending_import_contract(existing),
            }
        src["copies"] = max(0, _safe_int(src.get("copies"))) + 1
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
        strategies = [row for row in doc.get("strategies") or [] if _same_workspace(row, workspace)]
    return _ratings_for(strategies)


def report_abuse(user_id: Any, *, target_id: str, reason: str = "",
                 workspace_id: str = "") -> Dict[str, Any]:
    uid = int(user_id or 0)
    workspace = _workspace_id(workspace_id)
    if uid <= 0:
        raise CommunityError("Требуется вход.", 401)
    with _LOCK:
        doc = _load()
        row = {
            "report_id": "crep_" + secrets.token_hex(5),
            "workspace_id": workspace,
            "from_user_id": uid,
            "target_id": str(target_id or "")[:80],
            "reason": str(reason or "")[:500],
            "created_at_utc": _now_iso(),
        }
        doc.setdefault("reports", []).append(row)
        _save(doc)
    return {"ok": True, "report": row}


def moderate_block(owner_id: Any, target_user_id: Any, *, reason: str = "",
                   workspace_id: str = "") -> Dict[str, Any]:
    # Owner check is done by server route.
    tid = int(target_user_id or 0)
    workspace = _workspace_id(workspace_id)
    if tid <= 0:
        raise CommunityError("Пользователь не найден.", 404)
    with _LOCK:
        doc = _load()
        existing = next((row for row in doc.get("blocks") or []
                         if _safe_int(row.get("user_id")) == tid
                         and _same_workspace(row, workspace)), None)
        if existing is not None:
            return {"ok": True, "blocked_user_id": tid, "deduplicated": True}
        doc.setdefault("blocks", []).append({
            "workspace_id": workspace,
            "user_id": tid,
            "by_owner_id": int(owner_id or 0),
            "reason": str(reason or "")[:300],
            "created_at_utc": _now_iso(),
        })
        _save(doc)
    return {"ok": True, "blocked_user_id": tid, "deduplicated": False}


def moderate_delete_message(owner_id: Any, message_id: str, *, workspace_id: str = "") -> Dict[str, Any]:
    mid = str(message_id or "")
    workspace = _workspace_id(workspace_id)
    with _LOCK:
        doc = _load()
        before = len(doc.get("messages") or [])
        doc["messages"] = [row for row in doc.get("messages") or []
                           if not (row.get("message_id") == mid and _same_workspace(row, workspace))]
        _save(doc)
    return {"ok": True, "deleted": before - len(doc.get("messages") or []), "by_owner_id": int(owner_id or 0)}
