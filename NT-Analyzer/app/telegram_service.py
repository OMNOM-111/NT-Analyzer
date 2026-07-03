"""Telegram notifications for the local StratForge AI backend.

The bot token and paired chat id live only in ``secrets.local.json``. Public
status responses expose configuration flags and delivery health, never secret
values. Incoming trading commands are intentionally not implemented.
"""
from __future__ import annotations

import calendar
import hashlib
import html
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import local_secrets
from . import performance
from . import runtime


TOKEN_ENV = "NTA_TELEGRAM_BOT_TOKEN"
CHAT_ENV = "NTA_TELEGRAM_CHAT_ID"
GROUP_ENV = "NTA_TELEGRAM_GROUP_ID"
API_BASE_ENV = "NTA_TELEGRAM_API_BASE"

SETTING_DEFINITIONS = (
    ("enabled", "Уведомления Telegram", "Главный выключатель всех отправок."),
    ("app_status", "Работа приложения", "Запуск backend и состояние мониторинга."),
    ("strategy_state", "Стратегии", "Включение, остановка и изменение состояния стратегии."),
    ("nt_connection", "Связь с NinjaTrader", "Потеря и восстановление heartbeat моста."),
    ("application_errors", "Ошибки", "Новые ошибки, переданные мостом NinjaTrader."),
    ("important_news", "Важные новости", "Новые high-impact новости и события календаря."),
    ("daily_summary", "Сводка за день", "После 16:00 PT: сделки, P&L, win rate и комиссия."),
    ("weekly_summary", "Сводка за неделю", "По пятницам после 16:05 PT."),
    ("monthly_summary", "Сводка за месяц", "В последний день месяца после 16:10 PT."),
    ("quarterly_summary", "Сводка за квартал", "В последний день квартала после 16:15 PT."),
    ("chief_agent_reports", "StratForge Orchestrator", "Диалог, аудит, сомнения, рекомендации и задачи."),
)
DEFAULT_SETTINGS = {key: True for key, _label, _note in SETTING_DEFINITIONS}
DEFAULT_SETTINGS["enabled"] = False

_IO_LOCK = threading.RLock()
_PAIR_LOCK = threading.RLock()
_PAIRING: Dict[str, Any] = {}
_WORKER_LOCK = threading.Lock()
_WORKER: Optional[threading.Thread] = None
_STOP = threading.Event()


class TelegramServiceError(RuntimeError):
    """A safe-to-display Telegram integration error."""


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _settings_path() -> Path:
    return _root() / "data" / "integrations" / "telegram.settings.json"


def _state_path() -> Path:
    return _root() / "data" / "integrations" / "telegram.state.json"


def _topics_path() -> Path:
    return _root() / "data" / "integrations" / "telegram.topics.json"


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return dict(doc) if isinstance(doc, dict) else {}


def _write_json(path: Path, doc: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def load_settings() -> Dict[str, Any]:
    raw = _read_json(_settings_path())
    out: Dict[str, Any] = dict(DEFAULT_SETTINGS)
    for key in DEFAULT_SETTINGS:
        if key in raw:
            out[key] = bool(raw[key])
    for key in ("bot_username", "bot_name", "chat_label", "group_title", "updated_at_utc"):
        if raw.get(key):
            out[key] = str(raw[key])
    return out


def _save_settings(settings: Dict[str, Any]) -> None:
    with _IO_LOCK:
        _write_json(_settings_path(), settings)


def update_settings(changes: Dict[str, Any]) -> Dict[str, Any]:
    settings = load_settings()
    accepted = False
    for key in DEFAULT_SETTINGS:
        if key in changes:
            if not isinstance(changes[key], bool):
                raise TelegramServiceError(f"Настройка {key} должна быть true или false.")
            settings[key] = changes[key]
            accepted = True
    if not accepted:
        raise TelegramServiceError("Нет допустимых настроек Telegram.")
    settings["updated_at_utc"] = _now_iso()
    _save_settings(settings)
    return status()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _iso_timestamp(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _safe_error(error: BaseException, token: str = "") -> str:
    text = str(error or "Ошибка Telegram").strip() or "Ошибка Telegram"
    if token:
        text = text.replace(token, "[скрыто]")
    text = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot[скрыто]", text)
    return text[:500]


def _api_call(method: str, payload: Optional[Dict[str, Any]] = None,
              *, token: Optional[str] = None, timeout: float = 12.0) -> Any:
    secret_token = str(token or os.environ.get(TOKEN_ENV) or "").strip()
    if not secret_token:
        raise TelegramServiceError("Токен Telegram не настроен.")
    base = str(os.environ.get(API_BASE_ENV) or "https://api.telegram.org").rstrip("/")
    url = f"{base}/bot{secret_token}/{method}"
    data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace"))
            detail = str(body.get("description") or "")
        except Exception:
            detail = ""
        raise TelegramServiceError(_safe_error(detail or f"Telegram HTTP {exc.code}", secret_token)) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TelegramServiceError(_safe_error(f"Telegram недоступен: {exc}", secret_token)) from None
    try:
        doc = json.loads(raw)
    except ValueError:
        raise TelegramServiceError("Telegram вернул некорректный ответ.") from None
    if not isinstance(doc, dict) or not doc.get("ok"):
        detail = doc.get("description") if isinstance(doc, dict) else ""
        raise TelegramServiceError(_safe_error(detail or "Запрос Telegram отклонён.", secret_token))
    return doc.get("result")


def _bot_identity(token: Optional[str] = None) -> Dict[str, Any]:
    result = _api_call("getMe", token=token)
    if not isinstance(result, dict) or not result.get("is_bot"):
        raise TelegramServiceError("Токен не принадлежит Telegram-боту.")
    return result


def configure_token(token: str) -> Dict[str, Any]:
    candidate = str(token or "").strip()
    if not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{20,}", candidate):
        raise TelegramServiceError("Неверный формат токена Telegram.")
    identity = _bot_identity(candidate)
    previous = str(os.environ.get(TOKEN_ENV) or "").strip()
    changed = previous != candidate
    updates: Dict[str, Any] = {TOKEN_ENV: candidate}
    if changed:
        updates[CHAT_ENV] = None
    if not local_secrets.update(updates):
        raise TelegramServiceError("Не удалось сохранить токен в локальном хранилище.")
    settings = load_settings()
    settings["bot_username"] = str(identity.get("username") or "")
    settings["bot_name"] = str(identity.get("first_name") or identity.get("username") or "Telegram bot")
    if changed:
        settings.pop("chat_label", None)
    settings["updated_at_utc"] = _now_iso()
    _save_settings(settings)
    if changed:
        with _IO_LOCK:
            _write_json(_state_path(), {})
        with _PAIR_LOCK:
            _PAIRING.clear()
    return status()


def disconnect() -> Dict[str, Any]:
    if not local_secrets.update({TOKEN_ENV: None, CHAT_ENV: None, GROUP_ENV: None}):
        raise TelegramServiceError("Не удалось очистить локальные данные Telegram.")
    settings = load_settings()
    for key in ("bot_username", "bot_name", "chat_label", "group_title"):
        settings.pop(key, None)
    settings["enabled"] = False
    settings["updated_at_utc"] = _now_iso()
    _save_settings(settings)
    with _PAIR_LOCK:
        _PAIRING.clear()
    with _IO_LOCK:
        _write_json(_state_path(), {})
        _write_json(_topics_path(), {})
    return status()


def configure_group(raw_group_id: str) -> Dict[str, Any]:
    """Bind a Telegram supergroup with forum topics as the app's chat mirror."""
    gid = str(raw_group_id or "").strip()
    if not re.fullmatch(r"-?\d{5,}", gid):
        raise TelegramServiceError("Неверный ID группы Telegram (пример: -1001234567890).")
    identity = _bot_identity()
    chat = _api_call("getChat", {"chat_id": gid})
    if not isinstance(chat, dict):
        raise TelegramServiceError("Не удалось получить данные группы.")
    if str(chat.get("type") or "") not in {"supergroup", "group"}:
        raise TelegramServiceError("Указанный чат не является группой.")
    if not chat.get("is_forum"):
        raise TelegramServiceError("В группе не включены темы (Topics). Включите их в настройках группы и повторите.")
    if not local_secrets.update({GROUP_ENV: gid}):
        raise TelegramServiceError("Не удалось сохранить группу в локальном хранилище.")
    settings = load_settings()
    settings["group_title"] = str(chat.get("title") or "")
    settings["updated_at_utc"] = _now_iso()
    _save_settings(settings)
    with _IO_LOCK:
        doc = _load_topics()
        doc["group"] = {
            "chat_id": gid,
            "title": str(chat.get("title") or ""),
            "bot_id": int(identity.get("id") or 0),
            "bound_at_utc": _now_iso(),
        }
        _save_topics(doc)
    return group_status()


def disconnect_group() -> Dict[str, Any]:
    if not local_secrets.update({GROUP_ENV: None}):
        raise TelegramServiceError("Не удалось отвязать группу Telegram.")
    settings = load_settings()
    settings.pop("group_title", None)
    settings["updated_at_utc"] = _now_iso()
    _save_settings(settings)
    with _IO_LOCK:
        _write_json(_topics_path(), {})
    return group_status()


def group_rights() -> Dict[str, Any]:
    """Check that the bot can read, post and manage topics in the bound group."""
    gid = group_id()
    if not gid:
        return {"configured": False}
    doc = _load_topics()
    bot_id = int((doc.get("group") or {}).get("bot_id") or 0)
    if not bot_id:
        try:
            bot_id = int(_bot_identity().get("id") or 0)
        except TelegramServiceError:
            bot_id = 0
    out: Dict[str, Any] = {
        "configured": True, "group_id": gid,
        "group_title": str((doc.get("group") or {}).get("title") or load_settings().get("group_title") or ""),
    }
    try:
        chat = _api_call("getChat", {"chat_id": gid})
        out["is_forum"] = bool(isinstance(chat, dict) and chat.get("is_forum"))
    except TelegramServiceError as exc:
        out["error"] = str(exc)
        out["ready"] = False
        return out
    if bot_id:
        try:
            member = _api_call("getChatMember", {"chat_id": gid, "user_id": bot_id})
            member_status = str(member.get("status") or "") if isinstance(member, dict) else ""
            out["bot_status"] = member_status
            out["is_admin"] = member_status in {"administrator", "creator"}
            out["can_manage_topics"] = bool(member.get("can_manage_topics")) or member_status == "creator"
            # Non-restricted members can post; a restricted member exposes can_send_messages.
            out["can_post_messages"] = member_status != "restricted" or bool(member.get("can_send_messages"))
            out["can_read"] = member_status not in {"left", "kicked"}
        except TelegramServiceError as exc:
            out["error"] = str(exc)
    out["ready"] = bool(out.get("is_forum") and out.get("is_admin") and out.get("can_manage_topics") and out.get("can_post_messages"))
    return out


def group_status() -> Dict[str, Any]:
    doc = _load_topics()
    rights = group_rights()
    return {
        "configured": group_configured(),
        "group_id": group_id(),
        "group_title": str((doc.get("group") or {}).get("title") or load_settings().get("group_title") or ""),
        "topics_count": len((doc.get("conversations") or {})),
        "topics": list_topics(),
        "rights": rights,
    }


def start_pairing() -> Dict[str, Any]:
    identity = _bot_identity()
    username = str(identity.get("username") or "").strip()
    if not username:
        raise TelegramServiceError("У бота нет username, автоматическое подключение чата недоступно.")
    code = secrets.token_hex(4).upper()
    expires_at = time.time() + 600
    with _PAIR_LOCK:
        _PAIRING.clear()
        _PAIRING.update({"code": code, "expires_at": expires_at, "username": username})
    return {
        "ok": True,
        "code": code,
        "expires_in_sec": 600,
        "bot_url": f"https://t.me/{username}?start=connect_{code}",
        "instruction": "Откройте бота, нажмите Start, затем вернитесь и нажмите «Проверить подключение».",
    }


def _pair_text_matches(text: str, code: str) -> bool:
    normalized = " ".join(str(text or "").strip().split())
    patterns = (
        rf"/start(?:@[A-Za-z0-9_]+)?\s+connect_{re.escape(code)}",
        rf"/connect(?:@[A-Za-z0-9_]+)?\s+{re.escape(code)}",
    )
    return any(re.fullmatch(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns)


def complete_pairing() -> Dict[str, Any]:
    with _PAIR_LOCK:
        pairing = dict(_PAIRING)
    if not pairing or time.time() > float(pairing.get("expires_at") or 0):
        raise TelegramServiceError("Код подключения истёк. Создайте новый код.")
    updates = _api_call(
        "getUpdates",
        {"limit": 100, "timeout": 0, "allowed_updates": ["message"]},
        timeout=12,
    )
    code = str(pairing.get("code") or "")
    match: Optional[Dict[str, Any]] = None
    for update in reversed(updates if isinstance(updates, list) else []):
        message = update.get("message") if isinstance(update, dict) else None
        if not isinstance(message, dict) or not _pair_text_matches(str(message.get("text") or ""), code):
            continue
        chat = message.get("chat")
        sender = message.get("from")
        if not isinstance(chat, dict) or chat.get("type") != "private":
            continue
        if isinstance(sender, dict) and sender.get("is_bot"):
            continue
        match = message
        break
    if not match:
        raise TelegramServiceError("Сообщение подключения не найдено. Откройте бота и нажмите Start.")
    chat = match.get("chat") or {}
    chat_id = str(chat.get("id") or "").strip()
    if not chat_id or not local_secrets.update({CHAT_ENV: chat_id}):
        raise TelegramServiceError("Не удалось сохранить подключённый чат.")
    label = " ".join(str(chat.get(key) or "").strip() for key in ("first_name", "last_name")).strip()
    settings = load_settings()
    settings["chat_label"] = label or str(chat.get("username") or "Личный чат")
    settings["updated_at_utc"] = _now_iso()
    _save_settings(settings)
    with _PAIR_LOCK:
        _PAIRING.clear()
    try:
        _send_raw("✅ <b>StratForge AI подключён</b>\nЭтот чат будет получать выбранные уведомления.", chat_id=chat_id)
    except TelegramServiceError as exc:
        # Pairing remains valid even if the confirmation message is delayed or
        # Telegram temporarily rejects the send. The UI exposes this error and
        # the operator can use the explicit test button to retry.
        _record_delivery(success=False, error=str(exc))
    return status()


def _load_state() -> Dict[str, Any]:
    return _read_json(_state_path())


def _record_delivery(*, success: bool, error: str = "") -> None:
    with _IO_LOCK:
        state = _load_state()
        if success:
            state["last_delivery_at_utc"] = _now_iso()
            state["last_error"] = ""
        else:
            state["last_error_at_utc"] = _now_iso()
            state["last_error"] = _safe_error(RuntimeError(error))
        _write_json(_state_path(), state)


# ---------------------------------------------------------------------------
# Group forum-topics mode: each internal app chat (orchestrator conversation)
# maps to a Telegram forum topic (message_thread_id) inside one supergroup.
# ---------------------------------------------------------------------------

DEFAULT_CONVERSATION_ID = "default"


def group_id() -> str:
    return str(os.environ.get(GROUP_ENV) or "").strip()


def group_configured() -> bool:
    return bool(group_id())


def _primary_chat_id() -> str:
    """Where non-conversation notifications go: the group (General) if set,
    otherwise the paired private chat."""
    return group_id() or str(os.environ.get(CHAT_ENV) or "").strip()


def _load_topics() -> Dict[str, Any]:
    doc = _read_json(_topics_path())
    if not isinstance(doc.get("conversations"), dict):
        doc["conversations"] = {}
    if not isinstance(doc.get("group"), dict):
        doc["group"] = {}
    return doc


def _save_topics(doc: Dict[str, Any]) -> None:
    with _IO_LOCK:
        _write_json(_topics_path(), doc)


def _conversation_display_name(conversation_id: str, title: str = "") -> str:
    name = str(title or "").strip()
    if name:
        return name[:120]
    cid = str(conversation_id or "").strip()
    if not cid or cid == DEFAULT_CONVERSATION_ID:
        return "Основной чат"
    return f"Чат {cid[:20]}"


def ensure_topic(conversation_id: str, title: str = "") -> Dict[str, Any]:
    """Return the Telegram topic for an app conversation, creating it once.

    Deduplicated: an existing mapping is returned without creating a second
    topic. Requires group mode; raises otherwise.
    """
    gid = group_id()
    if not gid:
        raise TelegramServiceError("Групповой режим Telegram не настроен.")
    cid = str(conversation_id or "").strip() or DEFAULT_CONVERSATION_ID
    with _IO_LOCK:
        doc = _load_topics()
        existing = doc["conversations"].get(cid)
        if isinstance(existing, dict) and existing.get("message_thread_id") and str(existing.get("chat_id")) == gid:
            return existing
    name = _conversation_display_name(cid, title)
    result = _api_call("createForumTopic", {"chat_id": gid, "name": name})
    thread_id = int(result.get("message_thread_id") or 0) if isinstance(result, dict) else 0
    if not thread_id:
        raise TelegramServiceError("Не удалось создать тему Telegram.")
    record = {
        "conversation_id": cid,
        "chat_id": gid,
        "message_thread_id": thread_id,
        "name": name,
        "created_at_utc": _now_iso(),
    }
    with _IO_LOCK:
        doc = _load_topics()
        doc["conversations"][cid] = record
        _save_topics(doc)
    return record


def sync_topic_title(conversation_id: str, title: str = "") -> Dict[str, Any]:
    """Create a conversation topic or rename the existing one to the app title."""
    record = ensure_topic(conversation_id, title)
    desired = _conversation_display_name(conversation_id, title)
    if str(record.get("name") or "") == desired:
        return record
    _api_call("editForumTopic", {
        "chat_id": record["chat_id"],
        "message_thread_id": int(record["message_thread_id"]),
        "name": desired,
    })
    updated = dict(record)
    updated["name"] = desired
    updated["updated_at_utc"] = _now_iso()
    with _IO_LOCK:
        doc = _load_topics()
        doc["conversations"][str(conversation_id or "").strip() or DEFAULT_CONVERSATION_ID] = updated
        _save_topics(doc)
    return updated


def _thread_for_conversation(conversation_id: str, title: str = "") -> Optional[int]:
    """Resolve (and lazily create) the topic thread id for a conversation.

    Returns None on any failure so sending falls back to the General topic
    instead of dropping the message."""
    if not group_configured():
        return None
    try:
        return int(ensure_topic(conversation_id, title).get("message_thread_id") or 0) or None
    except TelegramServiceError as exc:
        _record_delivery(success=False, error=str(exc))
        return None


def _conversation_for_thread(chat_id: str, thread_id: Optional[int]) -> str:
    """Reverse map a (chat_id, message_thread_id) back to the app conversation.

    General-topic / unbound messages (no thread) route to the default chat.
    """
    if not thread_id:
        return DEFAULT_CONVERSATION_ID
    doc = _load_topics()
    for cid, row in (doc.get("conversations") or {}).items():
        if str(row.get("chat_id")) == str(chat_id) and int(row.get("message_thread_id") or 0) == int(thread_id):
            return str(cid)
    return DEFAULT_CONVERSATION_ID


def list_topics() -> List[Dict[str, Any]]:
    doc = _load_topics()
    rows = list((doc.get("conversations") or {}).values())
    rows.sort(key=lambda r: str(r.get("created_at_utc") or ""))
    return rows


def _send_raw(text: str, *, silent: bool = False, thread_id: Optional[int] = None,
              chat_id: Optional[str] = None) -> Dict[str, Any]:
    target = str(chat_id or _primary_chat_id()).strip()
    if not target:
        raise TelegramServiceError("Чат Telegram не подключён.")
    message = str(text or "").strip()
    if not message:
        raise TelegramServiceError("Пустое сообщение Telegram.")
    payload: Dict[str, Any] = {
        "chat_id": target,
        "text": message[:4096],
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "disable_notification": bool(silent),
    }
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    result = _api_call("sendMessage", payload)
    _record_delivery(success=True)
    return dict(result) if isinstance(result, dict) else {"ok": True}


def send_test() -> Dict[str, Any]:
    identity = _bot_identity()
    _send_raw(
        "✅ <b>Тест StratForge AI</b>\n"
        "Telegram настроен правильно. Уведомления готовы к работе."
    )
    return {"ok": True, "bot_username": str(identity.get("username") or "")}


def status() -> Dict[str, Any]:
    settings = load_settings()
    state = _load_state()
    token_configured = bool(str(os.environ.get(TOKEN_ENV) or "").strip())
    chat_configured = bool(str(os.environ.get(CHAT_ENV) or "").strip())
    configured = token_configured and chat_configured
    group_ready = group_configured()
    with _PAIR_LOCK:
        pairing_active = bool(_PAIRING and time.time() <= float(_PAIRING.get("expires_at") or 0))
    topics_doc = _load_topics()
    return {
        "configured": configured or (token_configured and group_ready),
        "status": "connected" if (configured or (token_configured and group_ready)) else ("token_ready" if token_configured else "not_configured"),
        "token_configured": token_configured,
        "chat_configured": chat_configured,
        "notifications_enabled": (configured or group_ready) and bool(settings.get("enabled")),
        "commands_enabled": configured or group_ready,
        "bot_username": str(settings.get("bot_username") or ""),
        "bot_name": str(settings.get("bot_name") or ""),
        "chat_label": str(settings.get("chat_label") or ""),
        "group_mode": group_ready,
        "group_id": group_id(),
        "group_title": str(settings.get("group_title") or (topics_doc.get("group") or {}).get("title") or ""),
        "topics_count": len(topics_doc.get("conversations") or {}),
        "pairing_active": pairing_active,
        "settings": {key: bool(settings.get(key)) for key in DEFAULT_SETTINGS},
        "setting_definitions": [
            {"key": key, "label": label, "description": note}
            for key, label, note in SETTING_DEFINITIONS
        ],
        "last_delivery_at_utc": str(state.get("last_delivery_at_utc") or ""),
        "last_error_at_utc": str(state.get("last_error_at_utc") or ""),
        "last_error": str(state.get("last_error") or ""),
        "note": (
            "StratForge Orchestrator понимает обычный текст только из привязанного личного чата. "
            "Исполняются лишь allowlisted функции; paper/demo требует approve, live заблокирован backend."
        ),
    }


def _notify(setting: str, title: str, lines: List[str], *, urgent: bool = False,
            thread_id: Optional[int] = None, dedupe_key: str = "") -> bool:
    settings = load_settings()
    if not settings.get("enabled") or not settings.get(setting):
        return False
    body = [f"<b>{html.escape(title)}</b>"]
    body.extend(html.escape(str(line)) for line in lines if str(line).strip())
    signature = hashlib.sha256(
        (dedupe_key or json.dumps(
            [setting, title, lines, int(thread_id or 0)], ensure_ascii=False, sort_keys=True,
        )).encode("utf-8")
    ).hexdigest()
    with _IO_LOCK:
        state = _load_state()
        recent = dict(state.get("recent_delivery_signatures") or {})
        cutoff = datetime.now(timezone.utc).timestamp() - 24 * 3600
        recent = {
            key: value for key, value in recent.items()
            if _iso_timestamp(value) >= cutoff
        }
        if signature in recent:
            return False
        # Claim before network I/O so concurrent workers cannot double-send.
        recent[signature] = _now_iso()
        state["recent_delivery_signatures"] = recent
        _write_json(_state_path(), state)
    try:
        _send_raw("\n".join(body), silent=not urgent, thread_id=thread_id)
        return True
    except TelegramServiceError as exc:
        with _IO_LOCK:
            state = _load_state()
            recent = dict(state.get("recent_delivery_signatures") or {})
            recent.pop(signature, None)
            state["recent_delivery_signatures"] = recent
            _write_json(_state_path(), state)
        _record_delivery(success=False, error=str(exc))
        return False


def send_chief_report(title: str, lines: List[str], *, urgent: bool = False,
                      model_name: str = "Chief agent / deterministic",
                      conversation_id: Optional[str] = None,
                      conversation_title: str = "") -> bool:
    """Send a model-attributed chief-agent report through the normal settings gate.

    In group mode the report is delivered into the Telegram forum topic bound to
    the originating app conversation (created once, then reused).
    """
    thread_id = _thread_for_conversation(conversation_id, conversation_title) if conversation_id else None
    # Model/provider attribution belongs in diagnostics, not in every message
    # to the owner. The parameter remains for API compatibility with older
    # callers, but executive reports intentionally contain only useful facts.
    return _notify(
        "chief_agent_reports", title, lines,
        urgent=urgent, thread_id=thread_id,
    )


def send_news_alert(title: str, lines: List[str], *,
                    model_name: str = "deterministic news rules") -> bool:
    """Send one deduplicated news-agent alert through the news setting gate."""
    return _notify(
        "important_news", f"📰 {title}",
        [f"Модель: {model_name}", *lines], urgent=True,
    )


def _chief_command_reply(text: str, *, thread_id: Optional[int] = None) -> None:
    try:
        _send_raw(str(text or "")[:4000], thread_id=thread_id)
    except TelegramServiceError:
        pass


def _handle_chief_command(text: str, *, conversation_id: Optional[str] = None,
                          thread_id: Optional[int] = None) -> None:
    """Handle natural owner text through the allowlisted Orchestrator executor.

    ``conversation_id`` binds the incoming Telegram topic to an app chat so the
    context and the reply stay inside the right thread.
    """
    from .ai_lab import chief_agent

    clean = str(text or "").strip()
    try:
        if clean.lower() in {"/chief", "/chief help", "/help"}:
            _chief_command_reply(
                "<b>StratForge Orchestrator</b>\n"
                "Пишите обычным текстом: попросите запустить исследование, проверить бэктест, "
                "сохранить правило, создать задачу или объяснить состояние.\n\n"
                "Paper/demo-действия потребуют подтверждения. Live, shell и изменение кода недоступны.",
                thread_id=thread_id,
            )
        elif clean.lower().startswith("/start"):
            return
        else:
            result = chief_agent.handle_message(
                clean, source="telegram", mirror_to_telegram=False,
                conversation_id=conversation_id or chief_agent.DEFAULT_CONVERSATION_ID,
            )
            _chief_command_reply(
                html.escape(str(result.get("reply") or "")),
                thread_id=thread_id,
            )
    except Exception as exc:
        _chief_command_reply(f"⚠️ {html.escape(str(exc)[:500])}", thread_id=thread_id)


def _auto_discover_group(updates: List[Dict[str, Any]]) -> None:
    """If the bot was added to a supergroup with forum-topics in this batch,
    auto-configure the GROUP_ENV so the user doesn't need a manual step."""
    if group_configured():
        return
    for upd in updates:
        mc = upd.get("my_chat_member") if isinstance(upd, dict) else None
        if not isinstance(mc, dict):
            continue
        chat = mc.get("chat") or {}
        new = mc.get("new_chat_member") or {}
        if str(chat.get("type") or "") not in {"supergroup", "group"}:
            continue
        if new.get("status") not in {"member", "administrator", "restricted"}:
            continue
        gid = str(chat.get("id") or "").strip()
        if not gid:
            continue
        # Confirm the group has forum topics enabled and save the config.
        try:
            info = _api_call("getChat", {"chat_id": gid})
            if not isinstance(info, dict) or not info.get("is_forum"):
                # If Topics not enabled yet, store the ID so configure_group can
                # be called when Topics are turned on; for now just note it.
                _record_delivery(success=False,
                                 error=f"Группа {info.get('title') or gid} найдена, но Topics не включены — включите Topics в настройках группы.")
                continue
            configure_group(gid)
            _send_raw(
                f"✅ <b>Группа с темами подключена автоматически</b>\n"
                f"Группа: <b>{html.escape(str(info.get('title') or gid))}</b>\n"
                "Каждый чат приложения будет получать отдельную тему. "
                "Напишите что-нибудь в любую тему группы — бот ответит."
            )
        except TelegramServiceError as exc:
            _record_delivery(success=False, error=str(exc))


def _poll_chief_commands(state: Dict[str, Any]) -> None:
    """Read the paired private chat and/or the bound group and route free text
    to the Orchestrator. One shared offset so private and group updates never
    consume each other. Also auto-discovers a new forum group if the bot was
    just added."""
    private_id = str(os.environ.get(CHAT_ENV) or "").strip()
    gid = group_id()
    if not private_id and not gid:
        return
    offset = int(state.get("chief_update_id") or 0) + 1
    # Include my_chat_member so we can auto-discover when the bot is added to a group.
    updates = _api_call(
        "getUpdates",
        {"offset": offset, "limit": 30, "timeout": 0,
         "allowed_updates": ["message", "my_chat_member"]},
        timeout=12,
    )
    if not isinstance(updates, list) or not updates:
        state["chief_commands_initialized"] = True
        return
    newest = max(int(row.get("update_id") or 0) for row in updates if isinstance(row, dict))
    # Auto-discover a new group even before initialization completes.
    try:
        _auto_discover_group(updates)
    except Exception:
        pass
    if not state.get("chief_commands_initialized"):
        # Do not replay messages sent before command handling was enabled.
        state["chief_update_id"] = newest
        state["chief_commands_initialized"] = True
        return
    for update in updates:
        if not isinstance(update, dict):
            continue
        message = update.get("message")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        if sender.get("is_bot"):
            continue
        text = str(message.get("text") or "").strip()
        if not text or text.lower().startswith("/start"):
            continue
        chat_id_str = str(chat.get("id") or "")
        chat_type = str(chat.get("type") or "")
        if gid and chat_id_str == gid:
            raw_thread = message.get("message_thread_id")
            thread_id = int(raw_thread) if raw_thread else None
            conversation_id = _conversation_for_thread(gid, thread_id)
            _handle_chief_command(text, conversation_id=conversation_id, thread_id=thread_id)
        elif private_id and chat_id_str == private_id and chat_type == "private":
            _handle_chief_command(text)
    state["chief_update_id"] = newest


def _strategy_snapshot() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for index, row in enumerate(runtime.read_strategies_raw()):
        key = str(row.get("runtime_instance_id") or "").strip()
        if not key:
            key = "|".join(str(row.get(name) or "").strip() for name in (
                "account_name", "strategy_class", "instrument", "strategy_name"
            )) or f"strategy-{index}"
        out[key] = {
            "enabled": bool(row.get("enabled")),
            "state": str(row.get("state") or ""),
            "name": str(row.get("display_name") or row.get("strategy_name") or row.get("strategy_class") or key),
            "account": str(row.get("account_name") or ""),
            "instrument": str(row.get("instrument") or ""),
        }
    return out


def _error_signature(row: Dict[str, Any]) -> str:
    return "|".join(str(row.get(key) or "") for key in ("timestamp_utc", "where", "type", "message"))


def _pt_now(now_utc: datetime) -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return now_utc.astimezone(ZoneInfo("America/Los_Angeles"))
    except Exception:
        return now_utc


def _summary_lines(period_name: str, period_key: str) -> List[str]:
    doc = performance.build_performance_response(period=period_key)
    summary = doc.get("strategy_summary") or doc.get("summary") or {}
    win_rate = summary.get("win_rate")
    return [
        f"Период: {period_name}",
        f"Сделок: {int(summary.get('trades') or 0)}",
        f"P&L после комиссии: ${float(summary.get('pnl') or 0):,.2f}",
        f"Комиссия: ${float(summary.get('commission') or 0):,.2f}",
        f"Win rate: {'—' if win_rate is None else f'{float(win_rate):.1f}%'}",
    ]


def _poll_news(state: Dict[str, Any], now_utc: datetime, initialized: bool) -> None:
    from . import integrations  # local import avoids an integrations/status cycle

    enabled_strategies = sum(1 for row in runtime.read_strategies_raw() if row.get("enabled"))
    live = integrations.live_news(max_age_min=90, limit=50)
    high_live = [item for item in live.get("items") or [] if str(item.get("severity") or "").lower() == "high"]
    seen_live = set(str(value) for value in state.get("seen_live_news") or [])
    current_live = [str(item.get("id") or f"{item.get('source')}|{item.get('title')}") for item in high_live]
    if initialized:
        for item, key in zip(high_live, current_live):
            if key in seen_live:
                continue
            try:
                from .ai_lab import news_agent
                news_agent.observe_items([item], send_telegram=True, use_llm=True)
            except Exception:
                pass
    state["seen_live_news"] = list(dict.fromkeys(list(seen_live) + current_live))[-200:]

    events = integrations.news(200).get("items") or []
    notified = set(str(value) for value in state.get("notified_calendar_events") or [])
    for item in events:
        if str(item.get("severity") or "").lower() != "high" or not item.get("is_confirmed"):
            continue
        at = integrations._parse_iso(item.get("event_time_utc"))
        if at is None:
            continue
        remaining = (at - now_utc).total_seconds()
        key = str(item.get("id") or f"{item.get('event_time_utc')}|{item.get('title')}")
        if 0 < remaining <= 3600 and key not in notified and initialized:
            minutes = max(1, round(remaining / 60))
            if _notify("important_news", "⚠️ Важное событие через час", [
                str(item.get("title") or ""),
                f"До события: {minutes} мин.",
                f"Инструменты: {', '.join(item.get('instruments') or []) or 'не указаны'}",
            ], urgent=True):
                notified.add(key)
                try:
                    if enabled_strategies <= 0:
                        continue
                    from .ai_lab import chief_agent
                    chief_agent.enqueue_event("important_calendar_event", {
                        "title": item.get("title"), "minutes_until": minutes,
                        "instruments": item.get("instruments"), "event_time_utc": item.get("event_time_utc"),
                    })
                except Exception:
                    pass
    state["notified_calendar_events"] = list(notified)[-300:]


def poll_once(*, now_utc: Optional[datetime] = None, announce_start: bool = False) -> Dict[str, Any]:
    """Evaluate notification sources once. Public for deterministic tests."""
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    settings = load_settings()
    state = _load_state()
    configured = bool(os.environ.get(TOKEN_ENV) and os.environ.get(CHAT_ENV))
    if not configured or not settings.get("enabled"):
        state["monitoring"] = False
        state["initialized"] = False
        state["last_poll_at_utc"] = now.isoformat()
        with _IO_LOCK:
            _write_json(_state_path(), state)
        return {"ok": True, "active": False}

    initialized = bool(state.get("initialized"))
    if announce_start:
        _notify("app_status", "🟢 StratForge AI запущен", ["Мониторинг Telegram активен."])

    current_strategies = _strategy_snapshot()
    enabled_count = sum(1 for row in current_strategies.values() if row.get("enabled"))
    heartbeat = runtime.read_heartbeat()
    connected = bool(heartbeat.get("fresh"))
    previous_connection = state.get("nt_connected")
    if initialized and previous_connection is not None and connected != bool(previous_connection):
        if connected:
            _notify("nt_connection", "🟢 Связь с NinjaTrader восстановлена", [
                f"Heartbeat: {heartbeat.get('timestamp_utc') or 'получен'}",
            ], urgent=True)
        else:
            age = heartbeat.get("age_sec")
            _notify("nt_connection", "🔴 Потеряна связь с NinjaTrader", [
                f"Heartbeat: {'нет данных' if age is None else f'{age} сек.'} · активных стратегий: {enabled_count}",
                "Проверьте NinjaTrader / Bridge.",
            ], urgent=True)
    state["nt_connected"] = connected

    previous_strategies = state.get("strategies") if isinstance(state.get("strategies"), dict) else {}
    if initialized and previous_connection is True and connected:
        for key, row in current_strategies.items():
            old = previous_strategies.get(key)
            if old is None and row.get("enabled"):
                _notify("strategy_state", "▶️ Стратегия включена", [
                    str(row.get("name") or key),
                    " · ".join(v for v in (row.get("account"), row.get("instrument")) if v),
                ], urgent=True)
            elif isinstance(old, dict) and bool(old.get("enabled")) != bool(row.get("enabled")):
                active = bool(row.get("enabled"))
                _notify("strategy_state", "▶️ Стратегия включена" if active else "⏹️ Стратегия остановлена", [
                    str(row.get("name") or key),
                    f"Состояние: {row.get('state') or ('enabled' if active else 'disabled')}",
                ], urgent=not active)
        for key, old in previous_strategies.items():
            if key not in current_strategies and isinstance(old, dict) and old.get("enabled"):
                _notify("strategy_state", "⏹️ Стратегия исчезла из runtime", [str(old.get("name") or key)], urgent=True)
    state["strategies"] = current_strategies

    errors = runtime.read_errors(20)
    latest_error = errors[-1] if errors else None
    latest_signature = _error_signature(latest_error) if isinstance(latest_error, dict) else ""
    if initialized and latest_signature and latest_signature != str(state.get("last_error_signature") or ""):
        _notify("application_errors", "⚠️ Ошибка NinjaTrader Bridge", [
            str(latest_error.get("where") or latest_error.get("type") or "runtime"),
            str(latest_error.get("message") or "Неизвестная ошибка")[:900],
        ], urgent=True)
    state["last_error_signature"] = latest_signature

    try:
        _poll_news(state, now, initialized)
    except Exception as exc:
        state["news_poll_error"] = _safe_error(exc)

    try:
        _poll_chief_commands(state)
    except Exception as exc:
        state["chief_command_error"] = _safe_error(exc)

    pt = _pt_now(now)
    day_key = pt.date().isoformat()
    if pt.hour >= 16 and state.get("daily_summary_key") != day_key:
        if _notify("daily_summary", "📊 Сводка StratForge AI за день", _summary_lines("сегодня", "today")):
            state["daily_summary_key"] = day_key
    if pt.weekday() == 4 and (pt.hour, pt.minute) >= (16, 5):
        week_key = f"{pt.isocalendar().year}-W{pt.isocalendar().week:02d}"
        if state.get("weekly_summary_key") != week_key:
            if _notify("weekly_summary", "📈 Сводка StratForge AI за неделю", _summary_lines("текущая неделя", "week")):
                state["weekly_summary_key"] = week_key
    last_day = calendar.monthrange(pt.year, pt.month)[1]
    if pt.day == last_day and (pt.hour, pt.minute) >= (16, 10):
        month_key = pt.strftime("%Y-%m")
        if state.get("monthly_summary_key") != month_key:
            if _notify("monthly_summary", "🗓 Сводка StratForge AI за месяц", _summary_lines("текущий месяц", "month")):
                state["monthly_summary_key"] = month_key
    if pt.month in {3, 6, 9, 12} and pt.day == last_day and (pt.hour, pt.minute) >= (16, 15):
        quarter_key = f"{pt.year}-Q{((pt.month - 1) // 3) + 1}"
        if state.get("quarterly_summary_key") != quarter_key:
            if _notify("quarterly_summary", "📚 Сводка StratForge AI за квартал", _summary_lines("квартал", "quarter")):
                state["quarterly_summary_key"] = quarter_key

    state["initialized"] = True
    state["monitoring"] = True
    state["last_poll_at_utc"] = now.isoformat()
    with _IO_LOCK:
        # Preserve delivery fields written by _send_raw while this poll ran.
        delivery = _load_state()
        for key in ("last_delivery_at_utc", "last_error_at_utc", "last_error"):
            if key in delivery:
                state[key] = delivery[key]
        _write_json(_state_path(), state)
    return {"ok": True, "active": True, "connected": connected}


def _worker_loop(interval_sec: int) -> None:
    announce = True
    while not _STOP.is_set():
        try:
            result = poll_once(announce_start=announce)
            if result.get("active"):
                announce = False
        except Exception as exc:
            try:
                _record_delivery(success=False, error=_safe_error(exc))
            except Exception:
                pass
        _STOP.wait(max(10, int(interval_sec)))


def start_background_notifier(interval_sec: int = 30) -> bool:
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER is not None and _WORKER.is_alive():
            return False
        _STOP.clear()
        _WORKER = threading.Thread(
            target=_worker_loop,
            args=(interval_sec,),
            name="nta-telegram-notifier",
            daemon=True,
        )
        _WORKER.start()
        return True


def stop_background_notifier() -> None:
    _STOP.set()
