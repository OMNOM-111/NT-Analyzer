"""Telegram Mini App authentication and local remote-access policy.

The browser presents Telegram ``initData`` on every API request.  This module
validates its HMAC using the bot token and then applies a revocable, local
allowlist.  It deliberately does not mint a second bearer token.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterable, Optional, Tuple

from . import account_auth


SOURCE = "telegram_mini_app"
INIT_DATA_HEADER = "X-Telegram-Init-Data"
MAX_AUTH_AGE_SEC = 15 * 60
PAIRING_TTL_SEC = 10 * 60
READ_LIMIT_PER_MINUTE = 180
WRITE_LIMIT_PER_MINUTE = 45
ROLES = {"read_only", "full_control"}
SELF_SERVICE_WRITE_PATHS = {
    "/api/billing/promo/preview",
    "/api/billing/promo/redeem",
    "/api/billing/subscribe",
    "/api/billing/checkout",
    "/api/billing/payment-request",
    "/api/workspaces/personal",
    "/api/workspaces/select",
    "/api/bridge/pair/start",
    "/api/bridge/pair/complete",
    "/api/auth/avatar/refresh",
    "/api/ops/runtime/account-history/classify",
    "/api/ops/runtime/account-history/events",
    "/api/ops/runtime/account-history/import",
    # Batch chart-bars poll is a read that carries its request list in the body.
    "/api/ops/runtime/bars/batch",
}

_LOCK = threading.RLock()
_RATE_LOCK = threading.Lock()
_RATE: Dict[Tuple[int, str, str], Deque[float]] = defaultdict(deque)


class RemoteAccessError(RuntimeError):
    def __init__(self, message: str, status: int = 400, context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status = int(status)
        self.context = context


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _access_path() -> Path:
    return _root() / "data" / "integrations" / "telegram.remote-access.json"


def _audit_path() -> Path:
    return _root() / "data" / "audit" / "telegram-mini-app.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read() -> Dict[str, Any]:
    path = _access_path()
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return dict(doc) if isinstance(doc, dict) else {}


def _write(doc: Dict[str, Any]) -> None:
    path = _access_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _document() -> Dict[str, Any]:
    doc = _read()
    doc.setdefault("remote_enabled", False)
    doc.setdefault("public_url", "")
    doc.setdefault("owner_phone_hash", "")
    doc.setdefault("users", [])
    doc.setdefault("pairings", [])
    if not isinstance(doc["users"], list):
        doc["users"] = []
    if not isinstance(doc["pairings"], list):
        doc["pairings"] = []
    return doc


def _normalize_phone(value: Any) -> str:
    return "".join(re.findall(r"\d", str(value or "")))


def _phone_hash(value: Any) -> str:
    normalized = _normalize_phone(value)
    return hashlib.sha256(normalized.encode("ascii")).hexdigest() if normalized else ""


def _public_user(row: Dict[str, Any]) -> Dict[str, Any]:
    return {key: row.get(key) for key in (
        "user_id", "username", "first_name", "last_name", "role", "status",
        "phone_verified", "granted_at_utc", "revoked_at_utc", "updated_at_utc",
    )}


def admin_status() -> Dict[str, Any]:
    with _LOCK:
        doc = _document()
        now = time.time()
        pairings = [
            {key: row.get(key) for key in (
                "request_id", "code", "role", "expected_user_id", "user_id",
                "username", "status", "phone_verified", "created_at_utc", "expires_at_utc",
            )}
            for row in doc["pairings"]
            if float(row.get("expires_at") or 0) > now or row.get("status") in {"pending_owner", "approved"}
        ]
        return {
            "remote_enabled": bool(doc.get("remote_enabled")),
            "public_url": str(doc.get("public_url") or ""),
            "owner_phone_configured": bool(doc.get("owner_phone_hash")),
            "users": [_public_user(row) for row in doc["users"] if isinstance(row, dict)],
            "pairings": pairings,
            "roles": sorted(ROLES),
            "auth_max_age_sec": MAX_AUTH_AGE_SEC,
            "live_trading_allowed": False,
        }


def clear_legacy_identities() -> None:
    """Remove plaintext legacy identity rows after DPAPI account migration."""
    with _LOCK:
        doc = _document()
        doc["users"] = []
        doc["pairings"] = []
        doc["identity_authority"] = "accounts.dpapi"
        doc["updated_at_utc"] = _now_iso()
        _write(doc)


def update_settings(changes: Dict[str, Any]) -> Dict[str, Any]:
    with _LOCK:
        doc = _document()
        if "remote_enabled" in changes:
            if not isinstance(changes["remote_enabled"], bool):
                raise RemoteAccessError("remote_enabled должен быть true или false.")
            doc["remote_enabled"] = changes["remote_enabled"]
        if "public_url" in changes:
            url = str(changes.get("public_url") or "").strip().rstrip("/")
            if url and (not url.startswith("https://") or urllib.parse.urlparse(url).hostname in {"localhost", "127.0.0.1"}):
                raise RemoteAccessError("Mini App URL должен быть публичным HTTPS URL.")
            doc["public_url"] = url
        if "owner_phone" in changes:
            phone = _normalize_phone(changes.get("owner_phone"))
            if phone and not 7 <= len(phone) <= 15:
                raise RemoteAccessError("Неверный формат номера владельца.")
            doc["owner_phone_hash"] = _phone_hash(phone)
        if changes.get("clear_owner_phone") is True:
            doc["owner_phone_hash"] = ""
        doc["updated_at_utc"] = _now_iso()
        _write(doc)
    return admin_status()


def start_pairing(*, bot_username: str, role: str, expected_user_id: Any = 0,
                  require_phone: bool = True) -> Dict[str, Any]:
    role = str(role or "read_only").strip()
    if role not in ROLES:
        raise RemoteAccessError("Неизвестная роль удалённого доступа.")
    username = str(bot_username or "").strip().lstrip("@")
    if not username:
        raise RemoteAccessError("Сначала настройте Telegram-бота.")
    try:
        expected = int(expected_user_id or 0)
    except (TypeError, ValueError):
        raise RemoteAccessError("Telegram user id должен быть целым числом.") from None
    code = secrets.token_hex(4).upper()
    request_id = secrets.token_urlsafe(12)
    now = time.time()
    with _LOCK:
        doc = _document()
        doc["pairings"] = [row for row in doc["pairings"] if float(row.get("expires_at") or 0) > now][-50:]
        doc["pairings"].append({
            "request_id": request_id, "code": code, "role": role,
            "expected_user_id": expected, "require_phone": bool(require_phone),
            "status": "code_issued", "created_at_utc": _now_iso(),
            "expires_at": now + PAIRING_TTL_SEC,
            "expires_at_utc": datetime.fromtimestamp(now + PAIRING_TTL_SEC, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        })
        _write(doc)
    return {
        "ok": True, "request_id": request_id, "code": code, "role": role,
        "expires_in_sec": PAIRING_TTL_SEC,
        "bot_url": f"https://t.me/{username}?start=access_{code}",
    }


def _find_pairing(doc: Dict[str, Any], *, code: str = "", request_id: str = "",
                  user_id: int = 0) -> Optional[Dict[str, Any]]:
    now = time.time()
    for row in reversed(doc["pairings"]):
        if float(row.get("expires_at") or 0) <= now:
            continue
        if code and hmac.compare_digest(str(row.get("code") or "").upper(), code.upper()):
            return row
        if request_id and hmac.compare_digest(str(row.get("request_id") or ""), request_id):
            return row
        if user_id and int(row.get("user_id") or 0) == user_id and row.get("status") == "awaiting_contact":
            return row
    return None


def _send_owner_approval(api_call: Callable[..., Any], owner_chat_id: str,
                         pairing: Dict[str, Any]) -> None:
    uid = int(pairing.get("user_id") or 0)
    username = str(pairing.get("username") or "")
    label = " ".join(str(pairing.get(k) or "").strip() for k in ("first_name", "last_name")).strip()
    who = html.escape(label or (f"@{username}" if username else str(uid)))
    request_id = str(pairing.get("request_id") or "")
    api_call("sendMessage", {
        "chat_id": owner_chat_id,
        "text": (
            "🔐 <b>Запрос доступа к StratForge AI</b>\n"
            f"Пользователь: <b>{who}</b>\nTelegram user id: <code>{uid}</code>\n"
            f"Роль: <b>{pairing.get('role')}</b>\n"
            f"Телефон подтверждён: <b>{'да' if pairing.get('phone_verified') else 'нет'}</b>\n\n"
            "Доступ появится только после вашего подтверждения."
        ),
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": [[
            {"text": "✅ Разрешить доступ", "callback_data": f"remote_allow:{request_id}"},
            {"text": "⛔ Отклонить", "callback_data": f"remote_deny:{request_id}"},
        ]]},
    })


def _approve(doc: Dict[str, Any], pairing: Dict[str, Any]) -> None:
    uid = int(pairing.get("user_id") or 0)
    now = _now_iso()
    existing = next((row for row in doc["users"] if int(row.get("user_id") or 0) == uid), None)
    values = {
        "user_id": uid, "username": str(pairing.get("username") or ""),
        "first_name": str(pairing.get("first_name") or ""),
        "last_name": str(pairing.get("last_name") or ""),
        "role": pairing.get("role"), "status": "active",
        "phone_verified": bool(pairing.get("phone_verified")),
        "granted_at_utc": now, "revoked_at_utc": "", "updated_at_utc": now,
    }
    if existing is None:
        doc["users"].append(values)
    else:
        existing.update(values)
    pairing["status"] = "approved"
    pairing["approved_at_utc"] = now


def process_update(update: Dict[str, Any], *, api_call: Callable[..., Any],
                   owner_chat_id: str) -> bool:
    """Handle pairing/contact/owner callbacks. Returns True when consumed."""
    callback = update.get("callback_query") if isinstance(update, dict) else None
    if isinstance(callback, dict):
        data = str(callback.get("data") or "")
        revoke_match = re.fullmatch(r"remote_revoke:(\d{1,20})", data)
        if revoke_match:
            actor_id = int((callback.get("from") or {}).get("id") or 0)
            if str(actor_id) != str(owner_chat_id):
                api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "Только владелец может отозвать доступ.", "show_alert": True})
                return True
            uid = int(revoke_match.group(1))
            try:
                revoke_user(uid)
                api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "Доступ отозван."})
                api_call("sendMessage", {"chat_id": uid, "text": "⛔ Владелец отозвал доступ к StratForge AI."})
            except RemoteAccessError as exc:
                api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": str(exc), "show_alert": True})
            return True
        match = re.fullmatch(r"remote_(allow|deny):([A-Za-z0-9_-]{8,})", data)
        if not match:
            return False
        actor_id = int((callback.get("from") or {}).get("id") or 0)
        if str(actor_id) != str(owner_chat_id):
            api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "Только владелец может подтвердить доступ.", "show_alert": True})
            return True
        with _LOCK:
            doc = _document()
            pairing = _find_pairing(doc, request_id=match.group(2))
            if not pairing or pairing.get("status") != "pending_owner":
                api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "Запрос истёк или уже обработан.", "show_alert": True})
                return True
            allowed = match.group(1) == "allow"
            if allowed:
                _approve(doc, pairing)
            else:
                pairing["status"] = "denied"
                pairing["denied_at_utc"] = _now_iso()
            _write(doc)
        api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "Доступ разрешён." if allowed else "Запрос отклонён."})
        api_call("sendMessage", {"chat_id": int(pairing.get("user_id") or 0), "text": "✅ Доступ к StratForge AI разрешён." if allowed else "⛔ Владелец отклонил запрос доступа."})
        return True

    message = update.get("message") if isinstance(update, dict) else None
    if not isinstance(message, dict):
        return False
    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    uid = int(sender.get("id") or 0)
    if not uid or sender.get("is_bot") or str(chat.get("type") or "") != "private":
        return False
    text = " ".join(str(message.get("text") or "").strip().split())
    if re.fullmatch(r"/access(?:@[A-Za-z0-9_]+)?", text, flags=re.IGNORECASE) and str(uid) == str(owner_chat_id):
        status = admin_status()
        active = [row for row in status["users"] if row.get("status") == "active"]
        if not active:
            api_call("sendMessage", {"chat_id": uid, "text": "Активных Mini App пользователей нет."})
            return True
        lines = ["🔐 <b>Доступ к StratForge AI</b>"]
        buttons = []
        for row in active[:30]:
            label = row.get("username") or row.get("first_name") or row.get("user_id")
            lines.append(f"• {html.escape(str(label))} · <code>{int(row['user_id'])}</code> · {html.escape(str(row.get('role') or 'read_only'))}")
            buttons.append([{"text": f"⛔ Отозвать {label}", "callback_data": f"remote_revoke:{int(row['user_id'])}"}])
        api_call("sendMessage", {"chat_id": uid, "text": "\n".join(lines), "parse_mode": "HTML", "reply_markup": {"inline_keyboard": buttons}})
        return True
    start = re.fullmatch(r"/start(?:@[A-Za-z0-9_]+)?\s+access_([A-Fa-f0-9]{8})", text)
    if start:
        with _LOCK:
            doc = _document()
            pairing = _find_pairing(doc, code=start.group(1))
            if not pairing or pairing.get("status") != "code_issued":
                api_call("sendMessage", {"chat_id": uid, "text": "Код доступа недействителен или уже использован."})
                return True
            expected = int(pairing.get("expected_user_id") or 0)
            if expected and expected != uid:
                pairing["status"] = "identity_mismatch"
                _write(doc)
                api_call("sendMessage", {"chat_id": uid, "text": "Telegram user id не совпадает с ожидаемым. Доступ отклонён."})
                return True
            pairing.update({
                "user_id": uid, "username": str(sender.get("username") or ""),
                "first_name": str(sender.get("first_name") or ""),
                "last_name": str(sender.get("last_name") or ""),
            })
            needs_phone = bool(pairing.get("require_phone") or doc.get("owner_phone_hash"))
            pairing["status"] = "awaiting_contact" if needs_phone else "pending_owner"
            _write(doc)
        if needs_phone:
            api_call("sendMessage", {
                "chat_id": uid,
                "text": "Для проверки личности отправьте свой номер кнопкой ниже. Введённый вручную номер не принимается.",
                "reply_markup": {"keyboard": [[{"text": "📱 Отправить мой номер", "request_contact": True}]], "resize_keyboard": True, "one_time_keyboard": True},
            })
        else:
            _send_owner_approval(api_call, owner_chat_id, pairing)
            api_call("sendMessage", {"chat_id": uid, "text": "Запрос отправлен владельцу на подтверждение."})
        return True

    contact = message.get("contact")
    if isinstance(contact, dict):
        with _LOCK:
            doc = _document()
            pairing = _find_pairing(doc, user_id=uid)
            if not pairing:
                return False
            if int(contact.get("user_id") or 0) != uid:
                pairing["status"] = "identity_mismatch"
                _write(doc)
                api_call("sendMessage", {"chat_id": uid, "text": "Контакт должен принадлежать вашему Telegram user id."})
                return True
            actual_hash = _phone_hash(contact.get("phone_number"))
            owner_hash = str(doc.get("owner_phone_hash") or "")
            if owner_hash and not hmac.compare_digest(actual_hash, owner_hash):
                pairing["status"] = "phone_mismatch"
                _write(doc)
                api_call("sendMessage", {"chat_id": uid, "text": "Номер не совпадает с заранее указанным владельцем номером. Доступ отклонён.", "reply_markup": {"remove_keyboard": True}})
                return True
            pairing["phone_verified"] = True
            pairing["status"] = "pending_owner"
            _write(doc)
        _send_owner_approval(api_call, owner_chat_id, pairing)
        api_call("sendMessage", {"chat_id": uid, "text": "Личность проверена. Ожидайте подтверждения владельца.", "reply_markup": {"remove_keyboard": True}})
        return True
    return False


def set_user_role(user_id: Any, role: str) -> Dict[str, Any]:
    role = str(role or "")
    if role not in ROLES:
        raise RemoteAccessError("Неизвестная роль.")
    uid = int(user_id)
    with _LOCK:
        doc = _document()
        user = next((row for row in doc["users"] if int(row.get("user_id") or 0) == uid), None)
        if user is None:
            raise RemoteAccessError("Пользователь не найден.", 404)
        user["role"] = role
        user["updated_at_utc"] = _now_iso()
        _write(doc)
    return admin_status()


def revoke_user(user_id: Any) -> Dict[str, Any]:
    uid = int(user_id)
    with _LOCK:
        doc = _document()
        user = next((row for row in doc["users"] if int(row.get("user_id") or 0) == uid), None)
        if user is None:
            raise RemoteAccessError("Пользователь не найден.", 404)
        user["status"] = "revoked"
        user["revoked_at_utc"] = _now_iso()
        user["updated_at_utc"] = _now_iso()
        _write(doc)
    return admin_status()


def configure_menu_button(api_call: Callable[..., Any]) -> Dict[str, Any]:
    doc = _document()
    url = str(doc.get("public_url") or "").rstrip("/")
    if not url:
        raise RemoteAccessError("Сначала сохраните публичный HTTPS URL.")
    api_call("setChatMenuButton", {"menu_button": {"type": "web_app", "text": "StratForge AI", "web_app": {"url": f"{url}/ui/"}}})
    return {"ok": True, "url": f"{url}/ui/"}


def validate_init_data(raw: str, bot_token: str, *, now: Optional[float] = None,
                       max_age_sec: int = MAX_AUTH_AGE_SEC) -> Dict[str, Any]:
    if not raw:
        raise RemoteAccessError("Telegram initData отсутствует.", 401)
    if not bot_token:
        raise RemoteAccessError("Telegram bot token не настроен.", 503)
    try:
        pairs = urllib.parse.parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise RemoteAccessError("Некорректный Telegram initData.", 401) from None
    values = dict(pairs)
    supplied_hash = str(values.pop("hash", ""))
    if not re.fullmatch(r"[0-9a-fA-F]{64}", supplied_hash):
        raise RemoteAccessError("Некорректная подпись Telegram initData.", 401)
    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied_hash.lower()):
        raise RemoteAccessError("Подпись Telegram initData не прошла проверку.", 401)
    try:
        auth_date = int(values.get("auth_date") or 0)
    except ValueError:
        raise RemoteAccessError("Некорректный auth_date Telegram.", 401) from None
    current = time.time() if now is None else float(now)
    if auth_date <= 0 or auth_date > current + 30 or current - auth_date > max_age_sec:
        raise RemoteAccessError("Telegram initData истёк. Переоткройте Mini App.", 401)
    try:
        user = json.loads(values.get("user") or "{}")
    except ValueError:
        raise RemoteAccessError("Telegram user отсутствует в initData.", 401) from None
    if not isinstance(user, dict) or not int(user.get("id") or 0):
        raise RemoteAccessError("Telegram user отсутствует в initData.", 401)
    return {"user": user, "auth_date": auth_date, "query_id": str(values.get("query_id") or "")}


def _rate_check(user_id: int, ip: str, method: str, *, now: Optional[float] = None) -> None:
    current = time.time() if now is None else float(now)
    bucket = "read" if method.upper() in {"GET", "HEAD"} else "write"
    limit = READ_LIMIT_PER_MINUTE if bucket == "read" else WRITE_LIMIT_PER_MINUTE
    key = (user_id, ip, bucket)
    with _RATE_LOCK:
        q = _RATE[key]
        while q and q[0] <= current - 60:
            q.popleft()
        if len(q) >= limit:
            raise RemoteAccessError("Слишком много запросов. Повторите позже.", 429)
        q.append(current)


def authorize(raw: str, bot_token: str, *, method: str, path: str, tunnel_ip: str,
              forwarded_ip: str = "") -> Dict[str, Any]:
    verified = validate_init_data(raw, bot_token)
    tg_user = verified["user"]
    uid = int(tg_user["id"])
    context = {
        "source": SOURCE, "user_id": uid, "role": "",
        "username": str(tg_user.get("username") or ""),
        "tunnel_ip": tunnel_ip, "forwarded_ip": forwarded_ip,
        "auth_date": verified["auth_date"],
    }
    with _LOCK:
        doc = _document()
        if not doc.get("remote_enabled"):
            raise RemoteAccessError("Удалённый доступ выключен владельцем.", 403, context)
        account = account_auth.find_active_user(uid)
        user = account
        # One-time compatibility before the encrypted account store is
        # bootstrapped. Once it exists, the legacy JSON whitelist is never an
        # authority again.
        if user is None and not account_auth.storage_status().get("encrypted"):
            user = next((row for row in doc["users"] if int(row.get("user_id") or 0) == uid), None)
        if not user or user.get("status") != "active":
            raise RemoteAccessError("Пользователь не входит в whitelist.", 403, context)
        role = str(user.get("role") or "read_only")
        if role == "owner":
            role = "full_control"
        context["role"] = role
        context["username"] = str(tg_user.get("username") or user.get("username") or "")
    if (method.upper() not in {"GET", "HEAD"} and role != "full_control" and path not in SELF_SERVICE_WRITE_PATHS
            and not path.startswith("/api/bridge/connections/")):
        raise RemoteAccessError("Для этого действия нужна роль «полное управление».", 403, context)
    if path.startswith("/api/telegram/") and path != "/api/telegram/remote/me":
        raise RemoteAccessError("Управление доступом разрешено только в desktop UI.", 403, context)
    if method.upper() not in {"GET", "HEAD"} and (
        path.startswith("/api/ops/live/") or path == "/api/server/restart"
    ):
        raise RemoteAccessError("Это действие запрещено из Telegram Mini App.", 403, context)
    try:
        # Rate limiting keys on the authenticated user and the direct tunnel
        # peer. X-Forwarded-For is audit context only; it must not let a client
        # rotate a spoofable header to evade the limiter.
        _rate_check(uid, tunnel_ip, method)
    except RemoteAccessError as exc:
        exc.context = context
        raise
    return context


def audit(*, method: str, path: str, status: int, context: Optional[Dict[str, Any]],
          tunnel_ip: str, forwarded_ip: str = "", error: str = "") -> None:
    row = {
        "timestamp": _now_iso(), "source": SOURCE,
        "user_id": (context or {}).get("user_id"),
        "role": (context or {}).get("role"), "method": method.upper(), "path": path,
        "status": int(status), "tunnel_ip": tunnel_ip,
        "forwarded_ip": forwarded_ip, "error": str(error or "")[:300],
    }
    path_obj = _audit_path()
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path_obj.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
