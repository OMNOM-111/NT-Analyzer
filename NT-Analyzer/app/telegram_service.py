"""Telegram transport for the local StratForge AI backend.

The bot token and paired chat id live only in ``secrets.local.json``. Public
status responses expose configuration flags and delivery health, never secret
values. Incoming messages share one dispatcher for authentication, Vitek and
the allowlisted Orchestrator capabilities. Live trading remains unavailable;
paper/demo actions keep their explicit backend approval gates.
"""
from __future__ import annotations

import calendar
import hashlib
import html
import json
import mimetypes
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import local_secrets
from . import durable
from . import performance
from . import runtime
from . import runtime_env
from . import market_data
from . import telegram_remote
from . import account_auth
from . import workspaces


TOKEN_ENV = "NTA_TELEGRAM_BOT_TOKEN"
CHAT_ENV = "NTA_TELEGRAM_CHAT_ID"
GROUP_ENV = "NTA_TELEGRAM_GROUP_ID"
API_BASE_ENV = "NTA_TELEGRAM_API_BASE"
WEBHOOK_SECRET_ENV = "NTA_TELEGRAM_WEBHOOK_SECRET"
BOT_USERNAME_ENVS = ("STRATFORGE_TELEGRAM_BOT_USERNAME", "NTA_TELEGRAM_BOT_USERNAME")

SETTING_DEFINITIONS = (
    ("enabled", "Уведомления Telegram", "Главный выключатель всех отправок."),
    ("app_status", "Работа приложения", "Запуск backend и состояние мониторинга."),
    ("strategy_state", "Стратегии", "Включение, остановка и изменение состояния стратегии."),
    ("nt_connection", "Связь с NinjaTrader", "Потеря и восстановление heartbeat моста."),
    ("application_errors", "Ошибки", "Новые ошибки, переданные мостом NinjaTrader."),
    ("price_alerts", "Ценовые алерты", "Касание линий, точек и стрелок на рабочем столе."),
    ("important_news", "Важные новости", "Новые high-impact новости и события календаря."),
    ("daily_summary", "Сводка за день", "После 16:00 PT: сделки, P&L, win rate и комиссия."),
    ("weekly_summary", "Сводка за неделю", "По пятницам после 16:05 PT."),
    ("monthly_summary", "Сводка за месяц", "В последний день месяца после 16:10 PT."),
    ("quarterly_summary", "Сводка за квартал", "В последний день квартала после 16:15 PT."),
    ("chief_agent_reports", "Витёк", "Диалог с вашей правой рукой: результаты, рекомендации и решения."),
)
DEFAULT_SETTINGS = {key: True for key, _label, _note in SETTING_DEFINITIONS}
DEFAULT_SETTINGS["enabled"] = False

_IO_LOCK = threading.RLock()
_PAIR_LOCK = threading.RLock()
_PAIRING: Dict[str, Any] = {}
_WORKER_LOCK = threading.Lock()
_WORKER: Optional[threading.Thread] = None
_COMMAND_WORKER: Optional[threading.Thread] = None
_STOP = threading.Event()
_UPDATES_LOCK = threading.Lock()
_UPDATES_LEASE: Any = None
_WEBHOOK_RUN_LOCK = threading.RLock()
_WEBHOOK_ACTIVE: Dict[str, str] = {}
_BOT_USERNAME_CACHE = ""
WEBHOOK_MAX_PARALLEL = 6
WEBHOOK_REORDER_GRACE_SEC = 0.75
REPLY_MAX_ATTEMPTS = 5
REPLY_RETRY_BASE_SEC = 15
REPLY_RETRY_MAX_SEC = 300
COMMUNITY_DEDUPE_TTL_SEC = 10 * 60

_CHIEF_ACTION_STATUS_LABELS = {
    "queued": "Поставлено в очередь", "running": "Выполняется",
    "in_progress": "Выполняется", "needs_input": "Жду ваш ответ",
    "waiting_review": "Жду ваш ответ", "approval_required": "Нужно ваше решение",
    "blocked": "Нужно внимание", "error": "Ошибка",
    "completed": "Выполнено", "confirmed_connected": "Связь подтверждена",
}

_COMMAND_STATE_KEYS = (
    "chief_update_id", "chief_commands_initialized", "chief_command_error",
    "chief_update_inflight", "chief_update_retries", "chief_received_update_id",
    "chief_seen_update_ids",
    "last_command_poll_at_utc", "last_command_update_at_utc",
    "last_command_update_id", "last_command_handler", "last_command_transport",
    "webhook_configured", "webhook_url", "webhook_configured_at_utc", "webhook_error",
)
_DELIVERY_STATE_KEYS = ("last_delivery_at_utc", "last_error_at_utc", "last_error")


class TelegramServiceError(RuntimeError):
    """A safe-to-display Telegram integration error."""


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _settings_path() -> Path:
    return runtime_env.data_path("integrations", "telegram.settings.json", project_root=_root())


def _state_path() -> Path:
    return runtime_env.data_path("integrations", "telegram.state.json", project_root=_root())


def _updates_audit_path() -> Path:
    return runtime_env.data_path("audit", "telegram-updates.jsonl", project_root=_root())


def _topics_path() -> Path:
    return runtime_env.data_path("integrations", "telegram.topics.json", project_root=_root())


def _updates_lease_path() -> Path:
    return runtime_env.data_path("integrations", "telegram.getupdates.lock", project_root=_root())


def _reply_outbox_path() -> Path:
    return runtime_env.data_path("integrations", "telegram.reply-outbox.json", project_root=_root())


def _update_inbox_path() -> Path:
    return runtime_env.data_path("integrations", "telegram.update-inbox.json", project_root=_root())


def _update_conversation_key(update: Dict[str, Any]) -> str:
    message = update.get("message") if isinstance(update.get("message"), dict) else {}
    if not message:
        callback = update.get("callback_query") if isinstance(update.get("callback_query"), dict) else {}
        message = callback.get("message") if isinstance(callback.get("message"), dict) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    chat_id = str(chat.get("id") or "unknown")
    thread_id = str(message.get("message_thread_id") or "default")
    return f"{chat_id}:{thread_id}"


def _seen_update_ids(state: Dict[str, Any]) -> set[int]:
    return {
        int(value) for value in (state.get("chief_seen_update_ids") or [])
        if str(value).lstrip("-").isdigit()
    }


def _remember_update_id(state: Dict[str, Any], update_id: int) -> None:
    if not update_id:
        return
    ordered = [
        int(value) for value in (state.get("chief_seen_update_ids") or [])
        if str(value).lstrip("-").isdigit() and int(value) != update_id
    ]
    # Telegram IDs are used only for exact recent dedupe. Never interpret this
    # list as a high-water mark: parallel webhook deliveries may arrive 102,101.
    state["chief_seen_update_ids"] = [*ordered, update_id][-4096:]


def _server_environment_explicit() -> bool:
    return runtime_env.environment_explicit() and (
        runtime_env.is_server_environment() or runtime_env.is_production()
    )


def _update_message(update: Dict[str, Any]) -> Dict[str, Any]:
    message = update.get("message") if isinstance(update, dict) else None
    return message if isinstance(message, dict) else {}


def _update_target_environment(update: Dict[str, Any]) -> str:
    text = " ".join(str(_update_message(update).get("text") or "").strip().split())
    if not text:
        return ""
    if re.search(r"(?:^|\s)\[CANARY\](?:\s|$)", text, flags=re.IGNORECASE):
        return runtime_env.CANARY
    if re.fullmatch(r"/start(?:@[A-Za-z0-9_]+)?\s+canary_login_[A-Fa-f0-9]{8}", text, flags=re.IGNORECASE):
        return runtime_env.CANARY
    if re.search(r"(?:^|\s)\[DEV\](?:\s|$)", text, flags=re.IGNORECASE):
        return runtime_env.DEVELOPMENT
    return ""


def _forward_origin(environment: str) -> str:
    if environment != runtime_env.CANARY:
        return ""
    internal = str(os.environ.get("STRATFORGE_CANARY_INTERNAL_ORIGIN") or "").strip()
    if internal:
        try:
            parsed = urllib.parse.urlsplit(internal)
            port = parsed.port
        except (TypeError, ValueError):
            return ""
        host = str(parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme == "http"
            and host in {"127.0.0.1", "localhost"}
            and port and 1 <= int(port) <= 65535
            and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
            and parsed.path in {"", "/"}
        ):
            normalized_host = "127.0.0.1" if host == "127.0.0.1" else "localhost"
            return f"http://{normalized_host}:{port}"
        return ""
    raw = str(os.environ.get("STRATFORGE_CANARY_ORIGIN") or "https://canary.stratforges.com").strip()
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
    except (TypeError, ValueError):
        return ""
    host = str(parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or port not in {None, 443} or host != "canary.stratforges.com":
        return ""
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        return ""
    return "https://canary.stratforges.com"


def _forward_secret(environment: str) -> str:
    if environment == runtime_env.CANARY:
        return str(
            os.environ.get("STRATFORGE_CANARY_TELEGRAM_WEBHOOK_SECRET")
            or os.environ.get(WEBHOOK_SECRET_ENV)
            or ""
        ).strip()
    return ""


def _forward_update_to_environment(update: Dict[str, Any], environment: str) -> bool:
    if environment == runtime_env.deployment_environment():
        return False
    origin = _forward_origin(environment)
    secret = _forward_secret(environment)
    if not origin or not secret:
        return False
    try:
        request = urllib.request.Request(
            origin.rstrip("/") + "/api/telegram/webhook",
            data=json.dumps(update, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Host": "canary.stratforges.com"} if origin.startswith("http://127.0.0.1:") or origin.startswith("http://localhost:") else {}),
                "X-Telegram-Bot-Api-Secret-Token": secret,
                "X-StratForge-Telegram-Forwarded": "1",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return 200 <= int(response.status) < 300
    except Exception as exc:
        _record_delivery(success=False, error=f"Telegram environment forward failed: {exc.__class__.__name__}")
        return False


def _should_forward_contact_to_canary(update: Dict[str, Any]) -> bool:
    if runtime_env.deployment_environment() == runtime_env.CANARY:
        return False
    message = _update_message(update)
    if not isinstance(message.get("contact"), dict):
        return False
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    return bool(sender.get("id") and str(chat.get("type") or "") == "private")


def _enqueue_update(update: Dict[str, Any], *, transport: str,
                    handle_owner_commands: Optional[bool] = None) -> bool:
    update_id = int(update.get("update_id") or 0)
    if _server_environment_explicit():
        from . import production_telegram
        return production_telegram.get_queue().enqueue_update(
            update, transport=str(transport or "webhook"),
        )
    with _IO_LOCK:
        doc = _read_json(_update_inbox_path())
        rows = [row for row in (doc.get("items") or []) if isinstance(row, dict)]
        if any(int(row.get("update_id") or 0) == update_id for row in rows):
            return False
        now_iso = _now_iso()
        available_iso = now_iso
        if str(transport or "webhook") == "webhook":
            available_iso = datetime.fromtimestamp(
                time.time() + WEBHOOK_REORDER_GRACE_SEC, timezone.utc,
            ).isoformat().replace("+00:00", "Z")
        rows.append({
            "id": "tgu_" + secrets.token_hex(8),
            "update_id": update_id,
            "conversation_key": _update_conversation_key(update),
            "transport": str(transport or "webhook"),
            "handle_owner_commands": handle_owner_commands,
            "status": "queued",
            "received_at_utc": now_iso,
            "available_at_utc": available_iso,
            "attempts": 0,
            "last_error": "",
            "update": update,
        })
        # Never truncate unfinished work after acknowledging Telegram. Successful
        # items are removed on completion, so this file only grows while there is
        # real queued/running/dead-letter evidence that must not be lost.
        _write_json(_update_inbox_path(), {"items": rows, "updated_at_utc": _now_iso()})
    return True


def recover_interrupted_updates() -> int:
    recovered = 0
    with _IO_LOCK:
        doc = _read_json(_update_inbox_path())
        rows = [row for row in (doc.get("items") or []) if isinstance(row, dict)]
        for row in rows:
            if row.get("status") == "running":
                row["status"] = "queued"
                row["available_at_utc"] = _now_iso()
                row["last_error"] = "Обработка была прервана перезапуском; сообщение возвращено в очередь."
                row.pop("started_at_utc", None)
                recovered += 1
        if recovered:
            _write_json(_update_inbox_path(), {"items": rows, "updated_at_utc": _now_iso()})
    return recovered


def _finish_queued_update(item: Dict[str, Any], *, dispatch: Optional[Dict[str, Any]] = None,
                          error: str = "") -> None:
    item_id = str(item.get("id") or "")
    update_id = int(item.get("update_id") or 0)
    if error:
        attempts = int(item.get("attempts") or 1)
        exhausted = attempts >= 3
        with _IO_LOCK:
            doc = _read_json(_update_inbox_path())
            rows = [row for row in (doc.get("items") or []) if isinstance(row, dict)]
            current = next((row for row in rows if str(row.get("id") or "") == item_id), None)
            if current:
                attempts = int(current.get("attempts") or 1)
                exhausted = attempts >= 3
                current["status"] = "dead_letter" if exhausted else "queued"
                current["last_error"] = str(error)[:1000]
                if exhausted:
                    current["finished_at_utc"] = _now_iso()
                    current.pop("available_at_utc", None)
                else:
                    current["available_at_utc"] = datetime.fromtimestamp(
                        time.time() + min(300, 15 * max(1, attempts)), timezone.utc,
                    ).isoformat().replace("+00:00", "Z")
                current.pop("started_at_utc", None)
                _write_json(_update_inbox_path(), {"items": rows, "updated_at_utc": _now_iso()})
        state = _load_state()
        state["chief_command_error"] = str(error)[:500]
        state["last_command_update_id"] = update_id
        state["last_command_handler"] = "exception"
        _save_command_poll_state(state)
        _append_update_audit({
            "update_id": update_id, "handler": "exception", "consumed": False,
            "error": str(error)[:1000], "transport": item.get("transport") or "webhook",
            "phase": "completed", "retry_scheduled": not exhausted,
            "retry_count": attempts, "dropped": exhausted,
        })
        if exhausted:
            update = item.get("update") if isinstance(item.get("update"), dict) else {}
            message = update.get("message") if isinstance(update.get("message"), dict) else {}
            thread_id = message.get("message_thread_id")
            _chief_command_reply(
                "Дмитрий Сергеевич, последнее сообщение не удалось обработать после нескольких попыток. "
                "Я сохранил его для диагностики и продолжил работу темы. Пожалуйста, повторите просьбу.",
                thread_id=int(thread_id) if str(thread_id or "").isdigit() else None,
                dedupe_key=f"dead-letter:{update_id}",
            )
        return

    result = dict(dispatch or {})
    with _IO_LOCK:
        doc = _read_json(_update_inbox_path())
        rows = [row for row in (doc.get("items") or []) if isinstance(row, dict)]
        rows = [row for row in rows if str(row.get("id") or "") != item_id]
        _write_json(_update_inbox_path(), {"items": rows, "updated_at_utc": _now_iso()})
    state = _load_state()
    _remember_update_id(state, update_id)
    # chief_update_id is the long-poll offset, not a webhook high-water mark.
    # Keeping transports separate lets failover request every still-pending Bot
    # API update; exact seen IDs suppress anything already handled by webhook.
    if str(item.get("transport") or "webhook") == "poll":
        state["chief_update_id"] = max(int(state.get("chief_update_id") or 0), update_id)
    state["chief_commands_initialized"] = True
    state["last_command_update_at_utc"] = _now_iso()
    state["last_command_update_id"] = update_id
    state["last_command_handler"] = str(result.get("handler") or "")
    state["last_command_transport"] = str(item.get("transport") or "webhook")
    if result.get("error"):
        state["chief_command_error"] = str(result.get("error") or "")[:500]
    else:
        state.pop("chief_command_error", None)
    _save_command_poll_state(state)
    _append_update_audit({
        **result, "transport": item.get("transport") or "webhook", "phase": "completed",
    })


def _run_queued_update(item: Dict[str, Any]) -> None:
    key = str(item.get("conversation_key") or "unknown")
    try:
        update = item.get("update") if isinstance(item.get("update"), dict) else {}
        try:
            _auto_discover_group([update])
        except Exception:
            pass
        dispatch = _dispatch_command_update(
            update,
            private_id=str(os.environ.get(CHAT_ENV) or "").strip(),
            gid=group_id(),
            handle_owner_commands=(
                bool(load_settings().get("enabled"))
                if item.get("handle_owner_commands") is None
                else bool(item.get("handle_owner_commands"))
            ),
        )
        _finish_queued_update(item, dispatch=dispatch)
    except Exception as exc:
        _finish_queued_update(item, error=_safe_error(exc))
    finally:
        with _WEBHOOK_RUN_LOCK:
            if _WEBHOOK_ACTIVE.get(key) == str(item.get("id") or ""):
                _WEBHOOK_ACTIVE.pop(key, None)


def _dispatch_update_inbox() -> int:
    if _server_environment_explicit():
        # The independently supervised PostgreSQL consumer owns server dispatch;
        # the API process must never spawn a competing thread.
        return 0
    claimed: List[Dict[str, Any]] = []
    with _WEBHOOK_RUN_LOCK:
        capacity = max(0, WEBHOOK_MAX_PARALLEL - len(_WEBHOOK_ACTIVE))
        if not capacity:
            return 0
        with _IO_LOCK:
            doc = _read_json(_update_inbox_path())
            rows = [row for row in (doc.get("items") or []) if isinstance(row, dict)]
            blocked = set(_WEBHOOK_ACTIVE)
            now_ts = time.time()
            lanes: Dict[str, List[Dict[str, Any]]] = {}
            for row in rows:
                if row.get("status") in {"queued", "running"}:
                    lanes.setdefault(str(row.get("conversation_key") or "unknown"), []).append(row)
            for key, lane in lanes.items():
                # The first unfinished row owns the lane, even during backoff;
                # later messages in the same topic may never overtake it.
                if key in blocked:
                    continue
                blocked.add(key)
                row = min(
                    lane,
                    key=lambda candidate: (
                        int(candidate.get("update_id") or 2**63 - 1),
                        _iso_timestamp(candidate.get("received_at_utc")),
                    ),
                )
                if row.get("status") != "queued":
                    continue
                if _iso_timestamp(row.get("available_at_utc")) > now_ts:
                    continue
                row["status"] = "running"
                row["started_at_utc"] = _now_iso()
                row["attempts"] = int(row.get("attempts") or 0) + 1
                _WEBHOOK_ACTIVE[key] = str(row.get("id") or "")
                claimed.append(dict(row))
                if len(claimed) >= capacity:
                    break
            if claimed:
                _write_json(_update_inbox_path(), {"items": rows, "updated_at_utc": _now_iso()})
    for item in claimed:
        threading.Thread(
            target=_run_queued_update, args=(item,),
            name=f"telegram-update-{item.get('update_id')}", daemon=True,
        ).start()
    return len(claimed)


def _webhook_public_url() -> str:
    remote = telegram_remote.admin_status()
    if not remote.get("remote_enabled"):
        return ""
    return str(remote.get("public_url") or "").strip().rstrip("/")


def _webhook_reachable(public_url: str) -> bool:
    """Probe and self-heal the configured Cloudflare tunnel when possible."""
    if not str(public_url or "").startswith("https://"):
        return False
    try:
        from . import tunnel_manager
        status = tunnel_manager.status(port=8765)
        public = status.get("public") if isinstance(status.get("public"), dict) else {}
        if public.get("reachable"):
            return True
        if status.get("remote_enabled") and (status.get("cloudflared") or {}).get("config_exists"):
            repaired = tunnel_manager.start(port=8765, wait_sec=6)
            repaired_public = repaired.get("public") if isinstance(repaired.get("public"), dict) else {}
            return bool(repaired.get("ready") or repaired_public.get("reachable"))
        return False
    except Exception:
        return False


def ensure_webhook() -> Dict[str, Any]:
    """Configure Telegram webhook when the public tunnel is available."""
    public_url = _webhook_public_url()
    token = str(os.environ.get(TOKEN_ENV) or "").strip()
    if not token or not public_url.startswith("https://"):
        return {"ok": False, "configured": False, "reason": "public_https_unavailable"}
    if not _webhook_reachable(public_url):
        # A configured but dead webhook makes Telegram retain every owner
        # message while getUpdates is forbidden. Remove it without dropping the
        # pending queue so the command worker immediately falls back to long
        # polling; webhook mode will be restored when the tunnel is healthy.
        try:
            _api_call("deleteWebhook", {"drop_pending_updates": False})
        except TelegramServiceError:
            pass
        state = _load_state()
        state["webhook_configured"] = False
        state["webhook_url"] = ""
        state["webhook_error"] = "Публичный tunnel недоступен; используется Telegram long polling."
        state["webhook_configured_at_utc"] = _now_iso()
        _save_command_poll_state(state)
        return {"ok": False, "configured": False, "reason": "public_tunnel_unreachable"}
    secret = str(os.environ.get(WEBHOOK_SECRET_ENV) or "").strip()
    if not secret:
        secret = secrets.token_urlsafe(32)
        if not local_secrets.update({WEBHOOK_SECRET_ENV: secret}):
            return {"ok": False, "configured": False, "reason": "secret_persist_failed"}
        os.environ[WEBHOOK_SECRET_ENV] = secret
    endpoint = public_url + "/api/telegram/webhook"
    result = _api_call("setWebhook", {
        "url": endpoint,
        "secret_token": secret,
        "allowed_updates": ["message", "my_chat_member", "callback_query"],
        "drop_pending_updates": False,
    })
    configured = bool(result is True or (isinstance(result, dict) and result.get("ok", True)))
    state = _load_state()
    state["webhook_configured"] = configured
    state["webhook_url"] = endpoint if configured else ""
    state["webhook_configured_at_utc"] = _now_iso()
    if configured:
        state.pop("chief_command_error", None)
        state.pop("webhook_error", None)
    _save_command_poll_state(state)
    return {"ok": configured, "configured": configured, "url": endpoint}


def process_webhook_update(update: Dict[str, Any], supplied_secret: str) -> Dict[str, Any]:
    """Validate, durably enqueue and immediately acknowledge one update."""
    expected = str(os.environ.get(WEBHOOK_SECRET_ENV) or "").strip()
    supplied = str(supplied_secret or "").strip()
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        raise TelegramServiceError("Некорректная подпись Telegram webhook.")
    update_id = int(update.get("update_id") or 0)
    with _UPDATES_LOCK:
        state = _load_state()
        if update_id and (
            update_id in _seen_update_ids(state)
            or update_id == int(state.get("chief_update_id") or 0)
        ):
            duplicate = {
                "update_id": update_id, "handler": "duplicate_update",
                "consumed": True, "error": "",
            }
            _append_update_audit({**duplicate, "transport": "webhook"})
            return duplicate
        queued = _enqueue_update(update, transport="webhook")
        if not queued:
            duplicate = {
                "update_id": update_id, "handler": "duplicate_update",
                "consumed": True, "error": "",
            }
            _append_update_audit({**duplicate, "transport": "webhook"})
            return duplicate
        state = _load_state()
        _remember_update_id(state, update_id)
        state["chief_received_update_id"] = max(
            int(state.get("chief_received_update_id") or 0), update_id,
        )
        state["chief_commands_initialized"] = True
        state["last_command_update_at_utc"] = _now_iso()
        state["last_command_update_id"] = update_id
        state["last_command_handler"] = "queued"
        state["last_command_transport"] = "webhook"
        _save_command_poll_state(state)
    accepted = {
        "update_id": update_id, "handler": "queued", "consumed": True,
        "queued": True, "error": "", "transport": "webhook", "phase": "accepted",
    }
    _append_update_audit(accepted)
    _dispatch_update_inbox()
    return accepted


def _acquire_updates_lease() -> bool:
    """Ensure only one local backend process owns Telegram getUpdates."""
    global _UPDATES_LEASE
    if _UPDATES_LEASE is not None:
        return True
    path = _updates_lease_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover - production host is Windows
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ImportError):
        handle.close()
        return False
    _UPDATES_LEASE = handle
    return True


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


def bot_username() -> str:
    global _BOT_USERNAME_CACHE
    settings = load_settings()
    username = str(settings.get("bot_username") or "").strip().lstrip("@")
    if username:
        return username
    for name in BOT_USERNAME_ENVS:
        username = str(os.environ.get(name) or "").strip().lstrip("@")
        if username:
            return username
    if _BOT_USERNAME_CACHE:
        return _BOT_USERNAME_CACHE
    if str(os.environ.get(TOKEN_ENV) or "").strip():
        try:
            username = str(_bot_identity().get("username") or "").strip().lstrip("@")
        except TelegramServiceError:
            username = ""
        if username:
            _BOT_USERNAME_CACHE = username
            return username
    return ""


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


def download_file(file_path: str, *, token: Optional[str] = None, timeout: float = 20.0) -> Optional[bytes]:
    """Download a Telegram file by its ``file_path`` via the bot file endpoint.

    Returns raw bytes or ``None``. Never raises: avatar fetching is best-effort
    and must never break login or the cabinet.
    """
    secret_token = str(token or os.environ.get(TOKEN_ENV) or "").strip()
    path = str(file_path or "").strip().lstrip("/")
    if not secret_token or not path:
        return None
    base = str(os.environ.get(API_BASE_ENV) or "https://api.telegram.org").rstrip("/")
    url = f"{base}/file/bot{secret_token}/{path}"
    request = urllib.request.Request(url, headers={"Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            blob = response.read()
        return blob if blob and len(blob) <= 3_000_000 else (blob if blob else None)
    except Exception:  # pragma: no cover - network failure path
        return None


def fetch_user_avatar(user_id: Any, *, size_pref: int = 200) -> Optional[Dict[str, Any]]:
    """Best-effort fetch of a Telegram user's profile photo through the bot.

    Returns ``{"bytes", "ext", "file_unique_id"}`` or ``None``. The bot can read
    ``getUserProfilePhotos`` for any user that has started it (all StratForge
    users authenticate via ``requestContact``). Never raises.
    """
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    if uid <= 0 or not str(os.environ.get(TOKEN_ENV) or "").strip():
        return None
    try:
        photos = _api_call("getUserProfilePhotos", {"user_id": uid, "limit": 1})
    except TelegramServiceError:
        return None
    sets = (photos or {}).get("photos") if isinstance(photos, dict) else None
    if not sets or not isinstance(sets, list) or not sets[0]:
        return None
    sizes = [s for s in sets[0] if isinstance(s, dict) and s.get("file_id")]
    if not sizes:
        return None
    # Prefer the smallest size that is still >= size_pref (a crisp thumbnail);
    # otherwise take the largest available.
    ordered = sorted(sizes, key=lambda s: int(s.get("width") or 0))
    chosen = ordered[-1]
    for size in ordered:
        if int(size.get("width") or 0) >= size_pref:
            chosen = size
            break
    try:
        file_info = _api_call("getFile", {"file_id": chosen.get("file_id")})
    except TelegramServiceError:
        return None
    file_path = (file_info or {}).get("file_path") if isinstance(file_info, dict) else ""
    blob = download_file(str(file_path or ""))
    if not blob:
        return None
    lowered = str(file_path or "").lower()
    ext = "png" if lowered.endswith(".png") else "webp" if lowered.endswith(".webp") else "jpg"
    return {"bytes": blob, "ext": ext, "file_unique_id": str(chosen.get("file_unique_id") or "")}


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
    with _UPDATES_LOCK:
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


def _save_notifier_state(state: Dict[str, Any]) -> None:
    """Save a notifier snapshot without erasing concurrent command/webhook state."""
    with _IO_LOCK:
        latest = _load_state()
        for key in _DELIVERY_STATE_KEYS:
            if key in latest:
                state[key] = latest[key]
        for key in _COMMAND_STATE_KEYS:
            if key in latest:
                state[key] = latest[key]
            else:
                state.pop(key, None)
        _write_json(_state_path(), state)


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


def _append_update_audit(row: Dict[str, Any]) -> None:
    payload = {
        "timestamp": _now_iso(),
        "update_id": int(row.get("update_id") or 0),
        "handler": str(row.get("handler") or ""),
        "consumed": bool(row.get("consumed")),
        "error": str(row.get("error") or "")[:500],
        "retry_count": int(row.get("retry_count") or 0),
        "dropped": bool(row.get("dropped")),
        "phase": str(row.get("phase") or "")[:20],
        "retry_scheduled": bool(row.get("retry_scheduled")),
        "transport": str(row.get("transport") or "poll")[:20],
        "conversation_id": str(row.get("conversation_id") or "")[:64],
        "sender_user_id": int(row.get("sender_user_id") or 0),
        "telegram_message_id": int(row.get("telegram_message_id") or 0),
        "assistant_message_id": str(row.get("assistant_message_id") or "")[:80],
        "delivered": bool(row.get("delivered")),
    }
    path = _updates_audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _IO_LOCK:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


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
    # Keep lookup, remote creation and persistence in one critical section.
    # The first app message can trigger title synchronization and message
    # mirroring concurrently; without this lock both paths could create a topic.
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


def _thread_for_conversation(conversation_id: str, title: str = "", *, strict: bool = False) -> Optional[int]:
    """Resolve (and lazily create) the topic thread id for a conversation.

    In strict mode a mapping failure is propagated so a scoped message can be
    queued and retried instead of being silently delivered to General."""
    if not group_configured():
        return None
    try:
        # Every outbound message is also a cheap reconciliation point. Usually
        # this is only a local name comparison; if an older topic still has the
        # placeholder, it is renamed before the message is sent.
        return int(sync_topic_title(conversation_id, title).get("message_thread_id") or 0) or None
    except TelegramServiceError as exc:
        _record_delivery(success=False, error=str(exc))
        if strict:
            raise
        return None


def _conversation_for_thread(chat_id: str, thread_id: Optional[int]) -> str:
    """Reverse map a (chat_id, message_thread_id) back to the app conversation.

    General-topic messages (no thread) route to the default chat. A non-empty
    but unknown thread is rejected: guessing ``default`` would permanently
    attach the message to the wrong Aurora conversation.
    """
    if not thread_id:
        return DEFAULT_CONVERSATION_ID
    doc = _load_topics()
    for cid, row in (doc.get("conversations") or {}).items():
        if str(row.get("chat_id")) == str(chat_id) and int(row.get("message_thread_id") or 0) == int(thread_id):
            return str(cid)
    raise TelegramServiceError(
        f"Тема Telegram {thread_id} не привязана к диалогу StratForge. Синхронизируйте темы и повторите сообщение."
    )


def list_topics() -> List[Dict[str, Any]]:
    doc = _load_topics()
    rows = list((doc.get("conversations") or {}).values())
    rows.sort(key=lambda r: str(r.get("created_at_utc") or ""))
    return rows


def _send_raw_direct(text: str, *, silent: bool = False,
                     thread_id: Optional[int] = None,
                     chat_id: Optional[str] = None,
                     parse_mode: str = "HTML") -> Dict[str, Any]:
    target = str(chat_id or _primary_chat_id()).strip()
    if not target:
        raise TelegramServiceError("Чат Telegram не подключён.")
    message = str(text or "").strip()
    if not message:
        raise TelegramServiceError("Пустое сообщение Telegram.")
    payload: Dict[str, Any] = {
        "chat_id": target,
        "text": message[:4096],
        "parse_mode": str(parse_mode or "HTML"),
        "link_preview_options": {"is_disabled": True},
        "disable_notification": bool(silent),
    }
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    result = _api_call("sendMessage", payload)
    _record_delivery(success=True)
    return dict(result) if isinstance(result, dict) else {"ok": True}


def _send_raw(text: str, *, silent: bool = False, thread_id: Optional[int] = None,
              chat_id: Optional[str] = None, dedupe_key: str = "",
              parse_mode: str = "HTML") -> Dict[str, Any]:
    # Non-Production environments prepend a visible contour marker so a Canary or
    # Development bot can never be mistaken for the Production owner bot. The
    # marker is empty in Production, so its wording is unchanged there.
    marker = runtime_env.telegram_environment_marker()
    body = str(text or "")
    if marker and not body.startswith(marker):
        body = marker + body
    if _server_environment_explicit():
        from . import production_telegram
        queued = production_telegram.enqueue_text(
            body, silent=silent, thread_id=thread_id,
            chat_id=str(chat_id or ""), dedupe_key=dedupe_key,
            parse_mode=parse_mode,
        )
        return {**queued, "delivery": "production_outbox"}
    return _send_raw_direct(
        body, silent=silent, thread_id=thread_id,
        chat_id=chat_id, parse_mode=parse_mode,
    )


def send_photo_bytes(chat_id: Any, blob: bytes, *, caption: str = "", filename: str = "invite.png") -> bool:
    """Send a raw image (bytes) to a specific chat. Used for shareable artifacts
    like invitation cards. Not gated by chief-agent report settings."""
    token = str(os.environ.get(TOKEN_ENV) or "").strip()
    chat = str(chat_id or "").strip()
    if not token or not chat or not blob:
        return False
    boundary = "----stratforge" + secrets.token_hex(16)
    fields = {"chat_id": chat, "caption": str(caption or "")[:1024]}
    parts: List[bytes] = []
    for key, value in fields.items():
        parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n").encode("utf-8"))
    name = filename or "invite.png"
    ctype = "image/jpeg" if name.lower().endswith((".jpg", ".jpeg")) else "image/png"
    parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{name}\"\r\n"
                  f"Content-Type: {ctype}\r\n\r\n").encode("utf-8"))
    parts.append(bytes(blob))
    parts.append((f"\r\n--{boundary}--\r\n").encode("utf-8"))
    body = b"".join(parts)
    base = str(os.environ.get(API_BASE_ENV) or "https://api.telegram.org").rstrip("/")
    request = urllib.request.Request(
        f"{base}/bot{token}/sendPhoto", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return 200 <= int(response.status) < 300
    except Exception:  # noqa: BLE001 — best-effort delivery
        return False


def send_photo(image_path: Any, caption: str = "", *, conversation_id: Optional[str] = None,
               conversation_title: str = "", silent: bool = True) -> bool:
    """Upload a chart snapshot image into the conversation's Telegram topic."""
    settings = load_settings()
    if not settings.get("enabled") or not settings.get("chief_agent_reports"):
        return False
    token = str(os.environ.get(TOKEN_ENV) or "").strip()
    chat = str(_primary_chat_id()).strip()
    if not token or not chat:
        return False
    try:
        path = Path(str(image_path))
        blob = path.read_bytes()
    except OSError:
        return False
    if not blob:
        return False
    try:
        thread_id = _thread_for_conversation(conversation_id, conversation_title, strict=True) if conversation_id else None
    except TelegramServiceError:
        return False
    boundary = "----stratforge" + secrets.token_hex(16)
    fields: Dict[str, str] = {
        "chat_id": chat,
        "caption": str(caption or "")[:1024],
        "disable_notification": "true" if silent else "false",
    }
    if thread_id:
        fields["message_thread_id"] = str(int(thread_id))
    parts: List[bytes] = []
    for key, value in fields.items():
        parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n").encode("utf-8"))
    name = path.name or "chart.jpg"
    ctype = ("image/jpeg" if name.lower().endswith((".jpg", ".jpeg")) else
             "image/png" if name.lower().endswith(".png") else
             "image/webp" if name.lower().endswith(".webp") else "application/octet-stream")
    parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{name}\"\r\n"
                  f"Content-Type: {ctype}\r\n\r\n").encode("utf-8"))
    parts.append(blob)
    parts.append((f"\r\n--{boundary}--\r\n").encode("utf-8"))
    body = b"".join(parts)
    base = str(os.environ.get(API_BASE_ENV) or "https://api.telegram.org").rstrip("/")
    url = f"{base}/bot{token}/sendPhoto"
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            response.read()
        _record_delivery(success=True)
        return True
    except Exception as exc:  # pragma: no cover - network failure path
        _record_delivery(success=False, error=_safe_error(f"sendPhoto: {exc}", token))
        return False


def send_document(document_path: Any, caption: str = "", *, conversation_id: Optional[str] = None,
                  conversation_title: str = "", silent: bool = True) -> bool:
    """Upload a generated report/document into the bound Telegram topic."""
    settings = load_settings()
    if not settings.get("enabled") or not settings.get("chief_agent_reports"):
        return False
    token = str(os.environ.get(TOKEN_ENV) or "").strip()
    chat = str(_primary_chat_id()).strip()
    if not token or not chat:
        return False
    try:
        path = Path(str(document_path))
        blob = path.read_bytes()
    except OSError:
        return False
    if not blob or len(blob) > 50 * 1024 * 1024:
        return False
    try:
        thread_id = _thread_for_conversation(conversation_id, conversation_title, strict=True) if conversation_id else None
    except TelegramServiceError:
        return False
    boundary = "----stratforge" + secrets.token_hex(16)
    fields: Dict[str, str] = {
        "chat_id": chat,
        "caption": str(caption or "")[:1024],
        "disable_notification": "true" if silent else "false",
    }
    if thread_id:
        fields["message_thread_id"] = str(int(thread_id))
    parts: List[bytes] = []
    for key, value in fields.items():
        parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n").encode("utf-8"))
    name = path.name or "report.txt"
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{name}\"\r\n"
                  f"Content-Type: {ctype}\r\n\r\n").encode("utf-8"))
    parts.append(blob)
    parts.append((f"\r\n--{boundary}--\r\n").encode("utf-8"))
    request = urllib.request.Request(
        f"{str(os.environ.get(API_BASE_ENV) or 'https://api.telegram.org').rstrip('/')}/bot{token}/sendDocument",
        data=b"".join(parts), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            response.read()
        _record_delivery(success=True)
        return True
    except Exception as exc:  # pragma: no cover - network failure path
        _record_delivery(success=False, error=_safe_error(f"sendDocument: {exc}", token))
        return False


def send_test() -> Dict[str, Any]:
    """Validate the configured bot and deliver one explicit test message."""
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
    inbox_rows = [
        row for row in (_read_json(_update_inbox_path()).get("items") or [])
        if isinstance(row, dict)
    ]
    reply_rows = [
        row for row in (_read_json(_reply_outbox_path()).get("items") or [])
        if isinstance(row, dict)
    ]
    return {
        "configured": configured or (token_configured and group_ready),
        "status": "connected" if (configured or (token_configured and group_ready)) else ("token_ready" if token_configured else "not_configured"),
        "token_configured": token_configured,
        "chat_configured": chat_configured,
        "notifications_enabled": (configured or group_ready) and bool(settings.get("enabled")),
        "commands_enabled": configured or group_ready,
        "bot_username": bot_username(),
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
        "last_command_poll_at_utc": str(state.get("last_command_poll_at_utc") or ""),
        "last_command_update_at_utc": str(state.get("last_command_update_at_utc") or ""),
        "last_command_update_id": int(state.get("last_command_update_id") or state.get("chief_update_id") or 0),
        "last_command_handler": str(state.get("last_command_handler") or ""),
        "last_command_error": str(state.get("chief_command_error") or ""),
        "telegram_update_offset": int(state.get("chief_update_id") or 0),
        "telegram_update_received": int(state.get("chief_received_update_id") or state.get("chief_update_id") or 0),
        "telegram_update_inflight": int(state.get("chief_update_inflight") or 0),
        "telegram_update_queue": {
            "queued": sum(1 for row in inbox_rows if row.get("status") == "queued"),
            "running": sum(1 for row in inbox_rows if row.get("status") == "running"),
            "dead_letter": sum(1 for row in inbox_rows if row.get("status") == "dead_letter"),
            "parallel_limit": WEBHOOK_MAX_PARALLEL,
        },
        "telegram_reply_queue": {
            "queued": sum(1 for row in reply_rows if str(row.get("status") or "queued") == "queued"),
            "dead_letter": sum(1 for row in reply_rows if row.get("status") == "dead_letter"),
            "max_attempts": REPLY_MAX_ATTEMPTS,
        },
        "note": (
            "Витёк понимает обычный текст из привязанного личного чата и тем рабочей группы. "
            "Исполняются лишь allowlisted функции; paper/demo требует approve, live заблокирован backend."
        ),
    }


def _notify(setting: str, title: str, lines: List[str], *, urgent: bool = False,
            thread_id: Optional[int] = None, conversation_id: str = "",
            conversation_title: str = "", dedupe_key: str = "",
            queue_on_failure: bool = False) -> bool:
    settings = load_settings()
    if not settings.get("enabled") or not settings.get(setting):
        return False
    body = [f"<b>{html.escape(title)}</b>"]
    body.extend(html.escape(str(line)) for line in lines if str(line).strip())
    if conversation_id and group_configured():
        try:
            thread_id = _thread_for_conversation(
                conversation_id, conversation_title, strict=True,
            )
        except TelegramServiceError as exc:
            _record_delivery(success=False, error=str(exc))
            if queue_on_failure:
                _enqueue_reply_outbox(
                    "\n".join(body), dedupe_key=dedupe_key,
                    conversation_id=conversation_id,
                    conversation_title=conversation_title,
                )
            return False
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
        from . import in_app_notifications
        in_app_notifications.record(
            title,
            list(lines or []),
            urgent=urgent,
            conversation_id=str(conversation_id or ""),
            conversation_title=str(conversation_title or ""),
            dedupe_key=str(dedupe_key or signature),
            kind=str(setting or ""),
        )
    except Exception:
        pass
    try:
        _send_raw(
            "\n".join(body), silent=not urgent, thread_id=thread_id,
            dedupe_key=str(dedupe_key or signature),
        )
        return True
    except TelegramServiceError as exc:
        if not queue_on_failure:
            with _IO_LOCK:
                state = _load_state()
                recent = dict(state.get("recent_delivery_signatures") or {})
                recent.pop(signature, None)
                state["recent_delivery_signatures"] = recent
                _write_json(_state_path(), state)
        _record_delivery(success=False, error=str(exc))
        if queue_on_failure:
            _enqueue_reply_outbox(
                "\n".join(body), thread_id=thread_id, dedupe_key=dedupe_key,
                conversation_id=conversation_id,
                conversation_title=conversation_title,
            )
        return False


def _chief_presentation_lines(lines: List[str], *, model_name: str = "",
                              provider_name: str = "", action_status: str = "") -> List[str]:
    """Build the public metadata footer shared by app and Telegram replies."""
    visible_lines = [str(line) for line in lines]
    metadata = []
    if str(model_name or "").strip():
        model_label = str(model_name).strip()
        if str(provider_name or "").strip():
            model_label += f" ({str(provider_name).strip()})"
        metadata.append("Модель: " + model_label)
    if str(action_status or "").strip():
        status = str(action_status).strip()
        metadata.append("Ход работы: " + _CHIEF_ACTION_STATUS_LABELS.get(status, status))
    if metadata:
        visible_lines.append(" · ".join(metadata))
    return visible_lines


def _chief_presentation_html(title: str, lines: List[str], *, model_name: str = "",
                             provider_name: str = "", action_status: str = "") -> str:
    visible = _chief_presentation_lines(
        lines, model_name=model_name, provider_name=provider_name,
        action_status=action_status,
    )
    body = [f"<b>{html.escape(str(title or 'StratForge Orchestrator'))}</b>"]
    body.extend(html.escape(str(line)) for line in visible if str(line).strip())
    return "\n".join(body)


def _result_action_status(result: Dict[str, Any], assistant: Dict[str, Any]) -> str:
    actions = assistant.get("actions") if isinstance(assistant.get("actions"), list) else result.get("actions")
    statuses = [
        str(row.get("status") or "") for row in (actions or [])
        if isinstance(row, dict) and str(row.get("status") or "")
    ]
    for preferred in (
        "error", "blocked", "approval_required", "needs_input", "waiting_review",
        "running", "in_progress", "queued", "completed",
    ):
        if preferred in statuses:
            return preferred
    return statuses[0] if statuses else ""


def send_chief_report(title: str, lines: List[str], *, urgent: bool = False,
                      model_name: str = "Chief agent / deterministic",
                      provider_name: str = "", action_status: str = "",
                      conversation_id: Optional[str] = None,
                      conversation_title: str = "",
                      dedupe_key: str = "") -> bool:
    """Send a model-attributed chief-agent report through the normal settings gate.

    In group mode the report is delivered into the Telegram forum topic bound to
    the originating app conversation (created once, then reused).

    ``dedupe_key`` uniquely identifies an interactive reply (the assistant
    message id). It bypasses the 24-hour text-dedup that exists only to swallow
    repeated *automatic* notifications, so two identical chat answers (e.g. two
    replies to "Как дела?") are both delivered instead of the second being
    silently dropped.
    """
    visible_lines = _chief_presentation_lines(
        lines, model_name=model_name, provider_name=provider_name,
        action_status=action_status,
    )
    return _notify(
        "chief_agent_reports", title, visible_lines,
        urgent=urgent, conversation_id=str(conversation_id or ""),
        conversation_title=conversation_title, dedupe_key=dedupe_key,
        queue_on_failure=True,
    )


def _canonical_telegram_chat_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not re.fullmatch(r"-?[1-9]\d*", raw):
        return ""
    try:
        return str(int(raw))
    except (TypeError, ValueError, OverflowError):
        return ""


def _claim_community_delivery(signature: str) -> bool:
    """Atomically claim a Community mirror delivery for at-most-once sending."""
    with _IO_LOCK:
        state = _load_state()
        recent = dict(state.get("recent_community_delivery_signatures") or {})
        cutoff = time.time() - COMMUNITY_DEDUPE_TTL_SEC
        recent = {
            key: value for key, value in recent.items()
            if _iso_timestamp(value) >= cutoff
        }
        if signature in recent:
            return False
        recent[signature] = _now_iso()
        state["recent_community_delivery_signatures"] = recent
        _write_json(_state_path(), state)
    return True


def mirror_community_message(text: str, *, display_name: str = "",
                             dedupe_key: str = "", workspace_id: str = "") -> bool:
    """Duplicate community chat into a SEPARATE Telegram chat/group.

    Controlled by ``NTA_COMMUNITY_TELEGRAM_CHAT_ID``. Never uses owner
    Orchestrator topics. Delivery is fail-closed and idempotent: a duplicate
    call returns False without a second Telegram request.
    """
    try:
        from . import runtime_env
        if runtime_env.is_staging() and not runtime_env.allow_owner_telegram_mirror():
            # Staging default: do not touch any Telegram chats.
            return False
    except Exception:
        # A broken/missing safety policy must never become permission to send.
        return False
    chat_id = _canonical_telegram_chat_id(
        os.environ.get("NTA_COMMUNITY_TELEGRAM_CHAT_ID")
    )
    if not chat_id:
        return False
    owner_chat = _canonical_telegram_chat_id(os.environ.get(CHAT_ENV))
    owner_group = _canonical_telegram_chat_id(os.environ.get(GROUP_ENV))
    if chat_id in {value for value in (owner_chat, owner_group) if value}:
        # Community must never leak into the owner private chat or Orchestrator group.
        return False
    if not str(os.environ.get(TOKEN_ENV) or "").strip():
        return False
    try:
        settings = load_settings()
    except Exception:
        return False
    if not settings.get("enabled"):
        return False
    body = str(text or "").strip()
    if not body:
        return False
    who = html.escape(str(display_name or "user")[:80])
    rendered = f"💬 <b>Community · {who}:</b> " + html.escape(body[:3500])
    identity = str(dedupe_key or "").strip()[:200]
    if not identity:
        # Backward-compatible callers do not yet pass a message id. Content
        # identity suppresses immediate retries for ten minutes, while callers
        # with a stable message id get the same protection without conflating
        # intentional later repetitions.
        identity = hashlib.sha256(
            f"{workspace_id}|{display_name}|{body}".encode("utf-8")
        ).hexdigest()
    signature = hashlib.sha256(
        f"community|{chat_id}|{workspace_id}|{identity}".encode("utf-8")
    ).hexdigest()
    try:
        if not _claim_community_delivery(signature):
            return False
        _api_call("sendMessage", {"chat_id": chat_id, "text": rendered, "parse_mode": "HTML"})
        return True
    except Exception:
        # Keep the claim on an ambiguous transport failure: at-most-once is
        # safer than duplicating a user message into Telegram after a timeout.
        return False


def mirror_owner_message(text: str, *, conversation_id: Optional[str] = None,
                         conversation_title: str = "",
                         dedupe_key: str = "") -> bool:
    """Mirror a message the owner typed inside the app into its bound Telegram
    topic, so the Telegram thread shows the full two-way conversation and not
    only the assistant's replies.

    Gated by the same master switch as chief reports; returns False silently
    when the integration is off or not connected. Never called for messages
    that originated in Telegram, so it cannot echo a message back to itself.
    """
    settings = load_settings()
    if not settings.get("enabled") or not settings.get("chief_agent_reports"):
        return False
    try:
        from . import runtime_env
        if not runtime_env.allow_owner_telegram_mirror():
            return False
    except Exception:
        pass
    body = str(text or "").strip()
    if not body:
        return False
    try:
        thread_id = (
            _thread_for_conversation(conversation_id, conversation_title, strict=True)
            if conversation_id else None
        )
    except TelegramServiceError as exc:
        _record_delivery(success=False, error=str(exc))
        _enqueue_reply_outbox(
            "🧑 <b>Вы:</b> " + html.escape(body[:3500]),
            dedupe_key=dedupe_key, conversation_id=str(conversation_id or ""),
            conversation_title=conversation_title,
        )
        return False
    rendered = "🧑 <b>Вы:</b> " + html.escape(body[:3500])
    signature = ""
    if dedupe_key:
        signature = hashlib.sha256(
            f"owner-mirror|{int(thread_id or 0)}|{dedupe_key}".encode("utf-8")
        ).hexdigest()
        with _IO_LOCK:
            state = _load_state()
            recent = dict(state.get("recent_delivery_signatures") or {})
            cutoff = datetime.now(timezone.utc).timestamp() - 24 * 3600
            recent = {key: value for key, value in recent.items() if _iso_timestamp(value) >= cutoff}
            if signature in recent:
                return False
            recent[signature] = _now_iso()
            state["recent_delivery_signatures"] = recent
            _write_json(_state_path(), state)
    try:
        _send_raw(
            rendered,
            silent=True, thread_id=thread_id,
            dedupe_key=str(dedupe_key or signature),
        )
        return True
    except TelegramServiceError as exc:
        _record_delivery(success=False, error=str(exc))
        _enqueue_reply_outbox(
            rendered, thread_id=thread_id, dedupe_key=dedupe_key,
            conversation_id=str(conversation_id or ""),
            conversation_title=conversation_title,
        )
        return False


def send_news_alert(title: str, lines: List[str], *,
                    model_name: str = "deterministic news rules") -> bool:
    """Send one deduplicated news-agent alert through the news setting gate."""
    return _notify(
        "important_news", f"📰 {title}",
        lines, urgent=True,
    )


def _enqueue_reply_outbox(text: str, *, thread_id: Optional[int] = None,
                          dedupe_key: str = "", conversation_id: str = "",
                          conversation_title: str = "") -> None:
    clean = str(text or "")[:4000]
    if not clean:
        return
    with _IO_LOCK:
        doc = _read_json(_reply_outbox_path())
        rows = doc.get("items") if isinstance(doc.get("items"), list) else []
        identity = str(dedupe_key or clean)
        signature = hashlib.sha256(
            f"{conversation_id}|{thread_id}|{identity}".encode("utf-8")
        ).hexdigest()
        if any(str(row.get("signature") or "") == signature for row in rows if isinstance(row, dict)):
            return
        rows.append({
            "id": "tgr_" + secrets.token_hex(8), "signature": signature,
            "text": clean, "thread_id": int(thread_id) if thread_id else None,
            "conversation_id": str(conversation_id or "")[:120],
            "conversation_title": str(conversation_title or "")[:120],
            "status": "queued", "created_at_utc": _now_iso(),
            "available_at_utc": _now_iso(), "attempts": 0, "last_error": "",
        })
        # Telegram may already have accepted the related owner command. Never
        # discard an undelivered reply merely because the local queue is large.
        # Successful items are removed; exhausted items remain as explicit
        # dead-letter evidence until an operator handles them.
        _write_json(_reply_outbox_path(), {"items": rows, "updated_at_utc": _now_iso()})


def _flush_reply_outbox(limit: int = 10) -> Dict[str, int]:
    """Retry due replies independently without letting one topic block another."""
    with _IO_LOCK:
        doc = _read_json(_reply_outbox_path())
        rows = [row for row in (doc.get("items") or []) if isinstance(row, dict)]
    if not rows:
        return {"sent": 0, "pending": 0}
    now_ts = time.time()
    due_rows = [
        row for row in rows
        if str(row.get("status") or "queued") == "queued"
        and _iso_timestamp(row.get("available_at_utc")) <= now_ts
    ][:max(1, int(limit or 10))]
    if not due_rows:
        pending = sum(1 for row in rows if str(row.get("status") or "queued") == "queued")
        return {"sent": 0, "pending": pending}
    sent_ids = set()
    attempted: Dict[str, Dict[str, Any]] = {}
    for row in due_rows:
        row_id = str(row.get("id") or "")
        try:
            thread_id = row.get("thread_id")
            conversation_id = str(row.get("conversation_id") or "")
            if conversation_id and group_configured():
                thread_id = _thread_for_conversation(
                    conversation_id, str(row.get("conversation_title") or ""), strict=True,
                )
                row["thread_id"] = thread_id
            _send_raw(str(row.get("text") or "")[:4000], thread_id=thread_id)
            sent_ids.add(row_id)
        except TelegramServiceError as exc:
            attempts = int(row.get("attempts") or 0) + 1
            row["attempts"] = attempts
            row["last_error"] = _safe_error(exc)
            if attempts >= REPLY_MAX_ATTEMPTS:
                row["status"] = "dead_letter"
                row["finished_at_utc"] = _now_iso()
                row.pop("available_at_utc", None)
            else:
                delay = min(REPLY_RETRY_MAX_SEC, REPLY_RETRY_BASE_SEC * (2 ** max(0, attempts - 1)))
                row["status"] = "queued"
                row["available_at_utc"] = datetime.fromtimestamp(
                    time.time() + delay, timezone.utc,
                ).isoformat().replace("+00:00", "Z")
            attempted[row_id] = dict(row)
            # Continue with other conversations. A deleted or unavailable
            # Telegram topic must not hold every subsequent reply hostage.
            continue
    with _IO_LOCK:
        latest = _read_json(_reply_outbox_path())
        latest_rows = [row for row in (latest.get("items") or []) if isinstance(row, dict)]
        remaining = []
        for row in latest_rows:
            row_id = str(row.get("id") or "")
            if row_id in sent_ids:
                continue
            if row_id in attempted:
                updated = attempted[row_id]
                row.update({key: updated[key] for key in (
                    "status", "attempts", "last_error", "available_at_utc", "finished_at_utc",
                ) if key in updated})
                if "available_at_utc" not in updated:
                    row.pop("available_at_utc", None)
            remaining.append(row)
        _write_json(_reply_outbox_path(), {"items": remaining, "updated_at_utc": _now_iso()})
    pending = sum(1 for row in remaining if str(row.get("status") or "queued") == "queued")
    return {"sent": len(sent_ids), "pending": pending}


def _chief_command_reply(text: str, *, thread_id: Optional[int] = None,
                         dedupe_key: str = "") -> bool:
    try:
        _send_raw(
            str(text or "")[:4000], thread_id=thread_id,
            dedupe_key=str(dedupe_key or ""),
        )
        return True
    except TelegramServiceError:
        _enqueue_reply_outbox(
            str(text or "")[:4000], thread_id=thread_id,
            dedupe_key=dedupe_key,
        )
        return False


def _conversation_scope_for_topic(conversation_id: str, *, sender_user_id: int = 0,
                                  sender_name: str = "") -> Optional[Dict[str, Any]]:
    """Resolve Telegram ingress to the authenticated app workspace.

    A Telegram topic only carries a conversation id.  The sender identity is
    therefore authoritative for the workspace, while durable chat metadata is
    a useful fallback for legacy/test callers.  Production ingress with a
    sender must never silently write into the old unscoped transcript.
    """
    try:
        sender_id = int(sender_user_id or 0)
    except (TypeError, ValueError):
        sender_id = 0
    if sender_id > 0:
        user = account_auth.find_active_user(sender_id)
        if not user:
            raise TelegramServiceError(
                "Не удалось связать ваш Telegram с активным аккаунтом StratForge. "
                "Войдите в приложение через Telegram и повторите сообщение."
            )
        try:
            owner_id = int(str(os.environ.get(CHAT_ENV) or "0").strip() or 0)
        except (TypeError, ValueError):
            owner_id = 0
        context = workspaces.context_for_user(
            sender_id, is_owner=bool(user.get("is_owner")), owner_id=owner_id,
        )
        active = context.get("active_workspace") if isinstance(context.get("active_workspace"), dict) else {}
        membership = context.get("active_membership") if isinstance(context.get("active_membership"), dict) else {}
        workspace_id = str(active.get("workspace_id") or "").strip()
        if not workspace_id:
            raise TelegramServiceError(
                "У вашего аккаунта не выбрана активная рабочая область. "
                "Откройте StratForge, выберите рабочую область и повторите сообщение."
            )
        display_name = " ".join(filter(None, (
            str(user.get("first_name") or "").strip(),
            str(user.get("last_name") or "").strip(),
        ))) or " ".join(str(sender_name or "").split())
        scope = {
            "user_id": sender_id,
            "workspace_id": workspace_id,
            "workspace_kind": str(active.get("kind") or ""),
            "uses_owner_runtime": bool(context.get("uses_owner_runtime")),
            "membership_role": str(membership.get("role") or user.get("role") or ""),
            "is_owner": bool(user.get("is_owner")),
            "display_name": display_name,
        }
        user_uuid = str(user.get("user_uuid") or "").strip()
        if user_uuid:
            scope["user_uuid"] = user_uuid
        # A named topic belongs to one user's private app dialogue.  The default
        # topic is workspace-shared by design, but a named owner dialogue must
        # never be exposed to another member of the same Telegram group.
        expected_scope_id = f"u{sender_id}__{workspace_id}"
        own_row = durable.get_chat_conversation(
            _root(), conversation_id, scope_id=expected_scope_id,
        )
        row = None if own_row else durable.find_chat_conversation(
            _root(), conversation_id, prefer_scoped=True,
        )
        if (row and str(conversation_id or "") != DEFAULT_CONVERSATION_ID
                and str(row.get("scope_id") or "")
                and int(row.get("user_id") or 0) not in {0, sender_id}):
            raise TelegramServiceError(
                "Эта тема привязана к другому пользователю. "
                "Откройте свой чат в StratForge и повторите сообщение там."
            )
        return scope

    row = durable.find_chat_conversation(_root(), conversation_id, prefer_scoped=True)
    if not row or not str(row.get("scope_id") or ""):
        return None
    try:
        user_id = int(row.get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    workspace_id = str(row.get("workspace_id") or "").strip()
    if user_id <= 0 or not workspace_id:
        return None
    role = str(row.get("membership_role") or "").strip()
    scope = {
        "user_id": user_id,
        "workspace_id": workspace_id,
        "membership_role": role,
        "is_owner": role == "owner",
    }
    user_uuid = str(row.get("user_uuid") or "").strip()
    if user_uuid:
        scope["user_uuid"] = user_uuid
    return scope


def _handle_chief_command(text: str, *, conversation_id: Optional[str] = None,
                          thread_id: Optional[int] = None,
                          sender_user_id: int = 0,
                          sender_name: str = "",
                          request_id: str = "") -> Dict[str, Any]:
    """Handle natural owner text through the allowlisted Orchestrator executor.

    ``conversation_id`` binds the incoming Telegram topic to an app chat so the
    context and the reply stay inside the right thread.
    """
    from .ai_lab import chief_agent

    clean = str(text or "").strip()
    try:
        if clean.lower() in {"/chief", "/chief help", "/help"}:
            delivered = _chief_command_reply(
                "<b>Витёк · правая рука руководителя</b>\n"
                "Пишите обычным текстом: попросите запустить исследование, проверить бэктест, "
                "сохранить правило, создать задачу или объяснить состояние.\n"
                "Для дежурного контроля: «Витёк, статус», «Витёк, проверь», "
                "«Витёк, отдыхай 2 часа».\n\n"
                "Paper/demo-действия потребуют подтверждения. Live, shell и изменение кода недоступны.",
                thread_id=thread_id,
            )
            return {"ok": True, "delivered": delivered}
        elif clean.lower().startswith("/start"):
            return {"ok": True, "delivered": True, "ignored": True}
        else:
            target_conversation = conversation_id or chief_agent.DEFAULT_CONVERSATION_ID
            scope = _conversation_scope_for_topic(
                target_conversation, sender_user_id=sender_user_id,
                sender_name=sender_name,
            )
            if scope:
                chief_agent.migrate_legacy_conversation_to_scope(target_conversation, scope)
            if _server_environment_explicit():
                if not scope:
                    raise TelegramServiceError(
                        "Server AI-запрос не привязан к пользователю "
                        "и рабочей области."
                    )
                from . import production_workers

                job = production_workers.enqueue_ai_message(
                    clean,
                    request_id=str(request_id or ""),
                    conversation_id=target_conversation,
                    agent="",
                    scope=scope,
                    mirror_to_telegram=True,
                    source="telegram_async",
                )
                return {
                    "ok": True,
                    "queued": True,
                    # The durable job owns the eventual single reply.  Mark the
                    # ingress handled so the Telegram update can release its
                    # lease without waiting for a provider call.
                    "delivered": True,
                    "conversation_id": target_conversation,
                    "worker_job_id": str(job.get("job_id") or job.get("worker_job_id") or ""),
                }
            result = chief_agent.handle_message(
                clean, source="telegram", mirror_to_telegram=False,
                conversation_id=target_conversation, scope=scope,
                request_id=str(request_id or ""),
            )
            assistant = result.get("message") if isinstance(result.get("message"), dict) else {}
            if scope:
                expected_scope = f"u{int(scope['user_id'])}__{scope['workspace_id']}"
                if str(assistant.get("conversation_scope_id") or "") != expected_scope:
                    raise TelegramServiceError(
                        "Ответ не был сохранён в единой истории. Сообщение оставлено в очереди диагностики; "
                        "повторите запрос после восстановления синхронизации."
                    )
            snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else {}
            image_path = market_data.snapshot_path(snapshot.get("file")) if snapshot.get("file") else None
            topic_row = (_load_topics().get("conversations") or {}).get(target_conversation) or {}
            sent_photo = bool(image_path and send_photo(
                image_path, caption=str(result.get("reply") or "")[:900],
                conversation_id=target_conversation,
                conversation_title=str(topic_row.get("name") or ""),
            ))
            delivered = sent_photo
            if not sent_photo:
                agent = result.get("agent") if isinstance(result.get("agent"), dict) else {}
                agent_name = str(
                    assistant.get("agent_name") or agent.get("name")
                    or result.get("agent_name") or "StratForge Orchestrator"
                )
                rendered_reply = _chief_presentation_html(
                    f"{agent_name} · ответ", [str(result.get("reply") or "")],
                    model_name=str(assistant.get("model") or result.get("model") or ""),
                    provider_name=str(assistant.get("provider") or result.get("provider") or ""),
                    action_status=_result_action_status(result, assistant),
                )
                delivered = _chief_command_reply(
                    rendered_reply,
                    thread_id=thread_id,
                    dedupe_key=str(assistant.get("message_id") or ""),
                )
            return {
                "ok": True, "delivered": bool(delivered), "result": result,
                "conversation_id": target_conversation,
                "assistant_message_id": str(assistant.get("message_id") or ""),
            }
    except Exception as exc:
        delivered = _chief_command_reply(f"⚠️ {html.escape(str(exc)[:500])}", thread_id=thread_id)
        return {"ok": False, "delivered": delivered, "error": _safe_error(exc)}


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


def _dispatch_command_update(update: Dict[str, Any], *, private_id: str, gid: str,
                             handle_owner_commands: bool) -> Dict[str, Any]:
    update_id = int(update.get("update_id") or 0)
    result = {"update_id": update_id, "handler": "ignored", "consumed": False, "error": ""}
    target_environment = _update_target_environment(update)
    if target_environment and target_environment != runtime_env.deployment_environment():
        if _forward_update_to_environment(update, target_environment):
            result.update({
                "handler": f"{target_environment}_forward",
                "consumed": True,
                "forwarded": True,
            })
            return result
    try:
        if private_id and account_auth.process_update(
            update, api_call=_api_call, owner_chat_id=private_id,
        ):
            result.update({"handler": "account_auth", "consumed": True})
            return result
        if private_id and telegram_remote.process_update(
            update, api_call=_api_call, owner_chat_id=private_id,
        ):
            result.update({"handler": "telegram_remote", "consumed": True})
            return result
    except telegram_remote.RemoteAccessError as exc:
        result.update({"handler": "telegram_remote", "consumed": True, "error": str(exc)})
        _record_delivery(success=False, error=str(exc))
        return result

    if _should_forward_contact_to_canary(update):
        if _forward_update_to_environment(update, runtime_env.CANARY):
            result.update({
                "handler": "canary_contact_forward",
                "consumed": True,
                "forwarded": True,
            })
            return result

    message = update.get("message")
    if not isinstance(message, dict):
        result["handler"] = "non_message"
        return result
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    if sender.get("is_bot"):
        result["handler"] = "bot_message"
        return result
    text = str(message.get("text") or "").strip()
    if not text:
        result["handler"] = "empty_message"
        return result
    if text.lower().startswith("/start"):
        # /start with login/access payload is consumed by the handlers above.
        # A plain /start remains explicit in diagnostics instead of silently
        # looking like a broken bot command.
        result["handler"] = "plain_start"
        return result
    if not handle_owner_commands:
        result["handler"] = "commands_disabled"
        return result
    chat_id_str = str(chat.get("id") or "")
    chat_type = str(chat.get("type") or "")
    try:
        sender_user_id = int(sender.get("id") or 0)
    except (TypeError, ValueError):
        sender_user_id = 0
    sender_name = " ".join(filter(None, (
        str(sender.get("first_name") or "").strip(),
        str(sender.get("last_name") or "").strip(),
    ))) or str(sender.get("username") or "").strip()
    result.update({
        "sender_user_id": sender_user_id,
        "telegram_message_id": int(message.get("message_id") or 0),
    })
    if gid and chat_id_str == gid:
        raw_thread = message.get("message_thread_id")
        thread_id = int(raw_thread) if raw_thread else None
        conversation_id = _conversation_for_thread(gid, thread_id)
        handled = _handle_chief_command(
            text, conversation_id=conversation_id, thread_id=thread_id,
            sender_user_id=sender_user_id, sender_name=sender_name,
            request_id=f"telegram:{update_id}",
        ) or {}
        result.update({
            "handler": "chief_group", "consumed": True,
            "error": str(handled.get("error") or ("reply_queued" if not handled.get("delivered", True) else "")),
            "conversation_id": str(handled.get("conversation_id") or conversation_id),
            "assistant_message_id": str(handled.get("assistant_message_id") or ""),
            "delivered": bool(handled.get("delivered")),
        })
        return result
    if private_id and chat_id_str == private_id and chat_type == "private":
        handled = _handle_chief_command(
            text, sender_user_id=sender_user_id, sender_name=sender_name,
            request_id=f"telegram:{update_id}",
        ) or {}
        result.update({
            "handler": "chief_private", "consumed": True,
            "error": str(handled.get("error") or ("reply_queued" if not handled.get("delivered", True) else "")),
            "conversation_id": str(handled.get("conversation_id") or DEFAULT_CONVERSATION_ID),
            "assistant_message_id": str(handled.get("assistant_message_id") or ""),
            "delivered": bool(handled.get("delivered")),
        })
        return result
    result["handler"] = "unmatched_chat"
    return result


def _poll_chief_commands(state: Dict[str, Any], *, long_poll_timeout: int = 0,
                         handle_owner_commands: bool = True) -> None:
    """Read the paired private chat and/or the bound group and route free text
    to the Orchestrator. One shared offset so private and group updates never
    consume each other. Also auto-discovers a new forum group if the bot was
    just added."""
    private_id = str(os.environ.get(CHAT_ENV) or "").strip()
    gid = group_id()
    if not private_id and not gid:
        return
    offset = int(state.get("chief_update_id") or 0) + 1
    poll_timeout = max(0, min(25, int(long_poll_timeout or 0)))
    # Include callbacks for explicit owner approval of Mini App access.
    with _UPDATES_LOCK:
        updates = _api_call(
            "getUpdates",
            {"offset": offset, "limit": 30, "timeout": poll_timeout,
             "allowed_updates": ["message", "my_chat_member", "callback_query"]},
            timeout=max(12, poll_timeout + 5),
        )
    if not isinstance(updates, list) or not updates:
        state["chief_commands_initialized"] = True
        return
    # Webhook and long-poll are two transports into one durable inbox. Advancing
    # the Bot API offset after the local write is safe: a restart can recover the
    # queued item instead of asking Telegram to redeliver it synchronously.
    with _UPDATES_LOCK:
        latest = _load_state()
        for key in _COMMAND_STATE_KEYS:
            if key in latest:
                state[key] = latest[key]
        for update in updates:
            if not isinstance(update, dict):
                continue
            update_id = int(update.get("update_id") or 0)
            already_seen = update_id and update_id in _seen_update_ids(state)
            queued = False if already_seen else _enqueue_update(
                update, transport="poll", handle_owner_commands=handle_owner_commands,
            )
            if queued:
                _remember_update_id(state, update_id)
                state["chief_received_update_id"] = max(
                    int(state.get("chief_received_update_id") or 0), update_id,
                )
                _append_update_audit({
                    "update_id": update_id, "handler": "queued", "consumed": True,
                    "transport": "poll", "phase": "accepted",
                })
            elif not already_seen:
                # The same update is already durable in the inbox (for example
                # webhook -> polling failover between the two local writes).
                _remember_update_id(state, update_id)
            state["chief_update_id"] = max(int(state.get("chief_update_id") or 0), update_id)
            state["last_command_update_id"] = update_id
        state["chief_commands_initialized"] = True
        state["last_command_update_at_utc"] = _now_iso()
        state["last_command_handler"] = "queued"
        state["last_command_transport"] = "poll"
        state.pop("chief_update_inflight", None)
        state.pop("chief_update_retries", None)
        _save_command_poll_state(state)
    _dispatch_update_inbox()


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
                news_agent.observe_items(
                    [item], send_telegram=True,
                    use_llm=not (
                        runtime_env.is_production()
                        and runtime_env.environment_explicit()
                    ),
                )
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
                    chief_agent.enqueue_event("important_news", {
                        "title": item.get("title"), "minutes_until": minutes,
                        "instruments": item.get("instruments"), "event_time_utc": item.get("event_time_utc"),
                        "owner_already_notified": True,
                    })
                except Exception:
                    pass
    state["notified_calendar_events"] = list(notified)[-300:]


def poll_once(*, now_utc: Optional[datetime] = None, announce_start: bool = False,
              include_commands: bool = True) -> Dict[str, Any]:
    """Evaluate notification sources once. Public for deterministic tests."""
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    settings = load_settings()
    state = _load_state()
    try:
        market_data.evaluate_alerts()
        for alert in market_data.pending_agent_alerts():
            from .ai_lab import chief_agent
            chief_agent.enqueue_event("price_alert_agent_task", {
                "alert_id": alert.get("id"), "agent_id": alert.get("agent_id") or "chief",
                "instruction": alert.get("agent_message") or alert.get("label") or "Проверь ценовой уровень.",
                "instrument": alert.get("instrument"), "timeframe": alert.get("timeframe"),
                "level": alert.get("price"), "trigger_price": alert.get("trigger_price"),
                "triggered_at_utc": alert.get("triggered_at_utc"),
            })
            market_data.mark_agent_dispatched(alert.get("id"))
    except Exception as exc:
        state["price_agent_error"] = _safe_error(exc)
    configured = bool(os.environ.get(TOKEN_ENV) and os.environ.get(CHAT_ENV))
    if not configured or not settings.get("enabled"):
        state["monitoring"] = False
        state["initialized"] = False
        state["last_poll_at_utc"] = now.isoformat()
        _save_notifier_state(state)
        return {"ok": True, "active": False}

    initialized = bool(state.get("initialized"))
    if announce_start:
        _notify("app_status", "🟢 StratForge AI запущен", ["Мониторинг Telegram активен."])

    current_strategies = _strategy_snapshot()
    enabled_count = sum(1 for row in current_strategies.values() if row.get("enabled"))
    heartbeat = runtime.read_heartbeat()
    connected = bool(heartbeat.get("fresh"))
    previous_connection = state.get("nt_connected")
    # Heartbeat transitions are produced once by chief_agent._runtime_monitor_tick
    # and then travel through Vitek's durable event bus. Telegram is only a
    # delivery surface here; it must not create a second incident/notification.
    state["nt_connected"] = connected

    previous_strategies = state.get("strategies") if isinstance(state.get("strategies"), dict) else {}
    if initialized and previous_connection is True and connected:
        for key, row in current_strategies.items():
            old = previous_strategies.get(key)
            if old is None and row.get("enabled"):
                try:
                    from .ai_lab import chief_agent
                    chief_agent.enqueue_event("strategy_started", {
                        **row, "strategy_key": key,
                    })
                except Exception:
                    pass
            elif isinstance(old, dict) and bool(old.get("enabled")) != bool(row.get("enabled")):
                active = bool(row.get("enabled"))
                try:
                    from .ai_lab import chief_agent
                    chief_agent.enqueue_event("strategy_started" if active else "strategy_stopped", {
                        **row, "strategy_key": key,
                    })
                except Exception:
                    pass
        for key, old in previous_strategies.items():
            if key not in current_strategies and isinstance(old, dict) and old.get("enabled"):
                try:
                    from .ai_lab import chief_agent
                    chief_agent.enqueue_event("strategy_disappeared", {
                        **old, "strategy_key": key,
                    })
                except Exception:
                    pass
    state["strategies"] = current_strategies

    errors = runtime.read_errors(20)
    latest_error = errors[-1] if errors else None
    latest_signature = _error_signature(latest_error) if isinstance(latest_error, dict) else ""
    if initialized and latest_signature and latest_signature != str(state.get("last_error_signature") or ""):
        try:
            from .ai_lab import chief_agent
            chief_agent.enqueue_event("runtime_error", {
                **latest_error, "error_signature": latest_signature,
            })
        except Exception:
            pass
    state["last_error_signature"] = latest_signature

    try:
        _poll_news(state, now, initialized)
    except Exception as exc:
        state["news_poll_error"] = _safe_error(exc)

    if include_commands:
        try:
            _poll_chief_commands(state)
        except Exception as exc:
            state["chief_command_error"] = _safe_error(exc)

    try:
        for alert in market_data.pending_telegram_alerts():
            price = float(alert.get("price") or 0)
            trigger = float(alert.get("trigger_price") or price)
            if _notify("price_alerts", "🔔 Цена коснулась отметки", [
                f"{alert.get('instrument') or '—'} · {alert.get('timeframe') or '—'}",
                f"{alert.get('label') or 'Ценовой уровень'}: {price:g}",
                f"Текущая цена: {trigger:g}",
            ], urgent=True, dedupe_key="price-alert:" + str(alert.get("id") or "")):
                market_data.mark_telegram_notified(alert.get("id"))
    except Exception as exc:
        state["price_alert_error"] = _safe_error(exc)

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
    _save_notifier_state(state)
    return {"ok": True, "active": True, "connected": connected}


def _worker_loop(interval_sec: int) -> None:
    announce = True
    while not _STOP.is_set():
        try:
            # Incoming chat uses a dedicated long-poll worker. Keeping the
            # notification scan separate prevents news/runtime work from adding
            # latency to owner messages and avoids concurrent getUpdates calls.
            result = poll_once(announce_start=announce, include_commands=False)
            if result.get("active"):
                announce = False
        except Exception as exc:
            try:
                _record_delivery(success=False, error=_safe_error(exc))
            except Exception:
                pass
        _STOP.wait(max(10, int(interval_sec)))


def _save_command_poll_state(state: Dict[str, Any]) -> None:
    """Merge command offsets into the latest notifier state without clobbering it."""
    with _IO_LOCK:
        latest = _load_state()
        for key in _COMMAND_STATE_KEYS:
            if key in state:
                latest[key] = state[key]
            elif key in {"chief_command_error", "chief_update_inflight", "webhook_error"}:
                latest.pop(key, None)
        _write_json(_state_path(), latest)


def _command_worker_loop() -> None:
    """Receive Telegram owner messages continuously via Bot API long polling."""
    recover_interrupted_updates()
    next_webhook_check = 0.0
    webhook_active = False
    while not _STOP.is_set():
        try:
            _dispatch_update_inbox()
        except Exception as exc:
            state = _load_state()
            state["chief_command_error"] = _safe_error(exc)
            _save_command_poll_state(state)
        try:
            _flush_reply_outbox()
        except Exception:
            pass
        if _webhook_public_url():
            if time.time() >= next_webhook_check:
                try:
                    webhook_active = bool(ensure_webhook().get("configured"))
                except Exception as exc:
                    webhook_active = False
                    state = _load_state()
                    state["webhook_error"] = _safe_error(exc)
                    _save_command_poll_state(state)
                next_webhook_check = time.time() + (300 if webhook_active else 30)
            if webhook_active:
                state = _load_state()
                state["last_command_poll_at_utc"] = _now_iso()
                state["last_command_transport"] = "webhook"
                state.pop("chief_command_error", None)
                _save_command_poll_state(state)
                _STOP.wait(1.0)
                continue
        if not _acquire_updates_lease():
            state = _load_state()
            state["chief_command_error"] = "Telegram getUpdates уже обслуживается другим локальным backend-процессом."
            state["last_command_poll_at_utc"] = _now_iso()
            _save_command_poll_state(state)
            _STOP.wait(2.0)
            continue
        settings = load_settings()
        configured = bool(
            os.environ.get(TOKEN_ENV)
            and (str(os.environ.get(CHAT_ENV) or "").strip() or group_id())
        )
        if not configured:
            _STOP.wait(1.0)
            continue
        state = _load_state()
        try:
            _poll_chief_commands(
                state, long_poll_timeout=20,
                handle_owner_commands=bool(settings.get("enabled")),
            )
            state.pop("chief_command_error", None)
            state["last_command_poll_at_utc"] = _now_iso()
            state["last_command_transport"] = "poll"
            _save_command_poll_state(state)
        except Exception as exc:
            state["chief_command_error"] = _safe_error(exc)
            state["last_command_poll_at_utc"] = _now_iso()
            _save_command_poll_state(state)
            _STOP.wait(1.0)


def start_background_notifier(interval_sec: int = 30) -> bool:
    if _server_environment_explicit():
        # Server Telegram is an independently supervised, leased service.
        return False
    global _WORKER, _COMMAND_WORKER
    with _WORKER_LOCK:
        _STOP.clear()
        started = False
        if _COMMAND_WORKER is None or not _COMMAND_WORKER.is_alive():
            _COMMAND_WORKER = threading.Thread(
                target=_command_worker_loop,
                name="nta-telegram-commands",
                daemon=True,
            )
            _COMMAND_WORKER.start()
            started = True
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(
                target=_worker_loop,
                args=(interval_sec,),
                name="nta-telegram-notifier",
                daemon=True,
            )
            _WORKER.start()
            started = True
        return started


def stop_background_notifier() -> None:
    _STOP.set()
