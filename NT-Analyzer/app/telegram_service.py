"""Telegram notifications for the local StratForge AI backend.

The bot token and paired chat id live only in ``secrets.local.json``. Public
status responses expose configuration flags and delivery health, never secret
values. Incoming trading commands are intentionally not implemented.
"""
from __future__ import annotations

import calendar
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
    for key in ("bot_username", "bot_name", "chat_label", "updated_at_utc"):
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
    if not local_secrets.update({TOKEN_ENV: None, CHAT_ENV: None}):
        raise TelegramServiceError("Не удалось очистить локальные данные Telegram.")
    settings = load_settings()
    for key in ("bot_username", "bot_name", "chat_label"):
        settings.pop(key, None)
    settings["enabled"] = False
    settings["updated_at_utc"] = _now_iso()
    _save_settings(settings)
    with _PAIR_LOCK:
        _PAIRING.clear()
    with _IO_LOCK:
        _write_json(_state_path(), {})
    return status()


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
        _send_raw("✅ <b>StratForge AI подключён</b>\nЭтот чат будет получать выбранные уведомления.")
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


def _send_raw(text: str, *, silent: bool = False) -> Dict[str, Any]:
    chat_id = str(os.environ.get(CHAT_ENV) or "").strip()
    if not chat_id:
        raise TelegramServiceError("Чат Telegram не подключён.")
    message = str(text or "").strip()
    if not message:
        raise TelegramServiceError("Пустое сообщение Telegram.")
    payload = {
        "chat_id": chat_id,
        "text": message[:4096],
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "disable_notification": bool(silent),
    }
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
    with _PAIR_LOCK:
        pairing_active = bool(_PAIRING and time.time() <= float(_PAIRING.get("expires_at") or 0))
    return {
        "configured": configured,
        "status": "connected" if configured else ("token_ready" if token_configured else "not_configured"),
        "token_configured": token_configured,
        "chat_configured": chat_configured,
        "notifications_enabled": configured and bool(settings.get("enabled")),
        "commands_enabled": False,
        "bot_username": str(settings.get("bot_username") or ""),
        "bot_name": str(settings.get("bot_name") or ""),
        "chat_label": str(settings.get("chat_label") or ""),
        "pairing_active": pairing_active,
        "settings": {key: bool(settings.get(key)) for key in DEFAULT_SETTINGS},
        "setting_definitions": [
            {"key": key, "label": label, "description": note}
            for key, label, note in SETTING_DEFINITIONS
        ],
        "last_delivery_at_utc": str(state.get("last_delivery_at_utc") or ""),
        "last_error_at_utc": str(state.get("last_error_at_utc") or ""),
        "last_error": str(state.get("last_error") or ""),
        "note": "Команды управления торговлей и бэктестами отключены до отдельного security-аудита.",
    }


def _notify(setting: str, title: str, lines: List[str], *, urgent: bool = False) -> bool:
    settings = load_settings()
    if not settings.get("enabled") or not settings.get(setting):
        return False
    body = [f"<b>{html.escape(title)}</b>"]
    body.extend(html.escape(str(line)) for line in lines if str(line).strip())
    try:
        _send_raw("\n".join(body), silent=not urgent)
        return True
    except TelegramServiceError as exc:
        _record_delivery(success=False, error=str(exc))
        return False


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

    live = integrations.live_news(max_age_min=90, limit=50)
    high_live = [item for item in live.get("items") or [] if str(item.get("severity") or "").lower() == "high"]
    seen_live = set(str(value) for value in state.get("seen_live_news") or [])
    current_live = [str(item.get("id") or f"{item.get('source')}|{item.get('title')}") for item in high_live]
    if initialized:
        for item, key in zip(high_live, current_live):
            if key in seen_live:
                continue
            _notify("important_news", "🔴 Важная новость", [
                str(item.get("title") or ""),
                f"Источник: {item.get('source') or 'не указан'}",
            ], urgent=True)
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
                f"Возраст heartbeat: {'нет данных' if age is None else f'{age} сек.'}",
                "Проверьте NinjaTrader и NTAnalyzerBridge.",
            ], urgent=True)
    state["nt_connected"] = connected

    current_strategies = _strategy_snapshot()
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
