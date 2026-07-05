"""Telegram-backed accounts and desktop browser sessions.

Identity is anchored to Telegram ``user.id``.  Personal data, login challenges
and session-token hashes are stored in one Windows DPAPI-encrypted document.
Only an owner callback from the configured private bot chat can activate a new
account.  Plain session tokens exist only in the browser cookie and in the
single response that creates them.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Optional, Tuple

from . import secure_store


SESSION_COOKIE = "sf_session"
SESSION_TTL_SEC = 30 * 24 * 60 * 60
CHALLENGE_TTL_SEC = 15 * 60
ROLES = {"read_only", "full_control", "owner"}
_MAGIC = b"STRATFORGE-ACCOUNTS-DPAPI-1\n"
_LOCK = threading.RLock()
_RATE_LOCK = threading.Lock()
_LOGIN_RATE: Dict[str, Deque[float]] = defaultdict(deque)


class AccountAuthError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _store_path() -> Path:
    return _root() / "data" / "integrations" / "accounts.dpapi"


def _remote_config_path() -> Path:
    return _root() / "data" / "integrations" / "telegram.remote-access.json"


def _audit_path() -> Path:
    return _root() / "data" / "audit" / "account-auth.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _default_doc() -> Dict[str, Any]:
    return {"version": 1, "users": [], "challenges": [], "sessions": []}


def _read_doc() -> Dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return _default_doc()
    try:
        raw = path.read_bytes()
        if not raw.startswith(_MAGIC):
            raise AccountAuthError("Неизвестный формат защищённого хранилища аккаунтов.", 500)
        encrypted = base64.b64decode(raw[len(_MAGIC):], validate=True)
        doc = json.loads(secure_store._unprotect(encrypted).decode("utf-8"))
    except AccountAuthError:
        raise
    except secure_store.SecureStoreError as exc:
        raise AccountAuthError(str(exc), 503) from None
    except Exception as exc:
        raise AccountAuthError(f"Не удалось прочитать защищённые аккаунты: {exc}", 500) from None
    if not isinstance(doc, dict):
        raise AccountAuthError("Защищённое хранилище аккаунтов повреждено.", 500)
    for key in ("users", "challenges", "sessions"):
        if not isinstance(doc.get(key), list):
            doc[key] = []
    return doc


def _write_doc(doc: Dict[str, Any]) -> None:
    if not secure_store.available():
        raise AccountAuthError("Windows DPAPI недоступен; аккаунты не могут быть сохранены.", 503)
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plaintext = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        payload = _MAGIC + base64.b64encode(secure_store._protect(plaintext))
    except secure_store.SecureStoreError as exc:
        raise AccountAuthError(str(exc), 503) from None
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(payload)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise AccountAuthError(f"Не удалось сохранить защищённые аккаунты: {exc}", 500) from None


def _remote_config() -> Dict[str, Any]:
    try:
        doc = json.loads(_remote_config_path().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return dict(doc) if isinstance(doc, dict) else {}


def auth_required() -> bool:
    if os.environ.get("NTA_TEST_BYPASS_AUTH") == "1":
        return False
    config = _remote_config()
    return bool(config.get("desktop_auth_required", config.get("remote_enabled", False)))


def set_auth_required(enabled: bool) -> None:
    path = _remote_config_path()
    config = _remote_config()
    config["desktop_auth_required"] = bool(enabled)
    config["updated_at_utc"] = _now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def storage_status() -> Dict[str, Any]:
    return {
        "available": secure_store.available(),
        "backend": secure_store.backend_name(),
        "encrypted": _store_path().is_file(),
        "auth_required": auth_required(),
    }


def _normalize_phone(value: Any) -> str:
    return "".join(re.findall(r"\d", str(value or "")))


def _phone_hash(value: Any) -> str:
    phone = _normalize_phone(value)
    return hashlib.sha256(phone.encode("ascii")).hexdigest() if phone else ""


def _valid_email(value: Any) -> str:
    email = str(value or "").strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise AccountAuthError("Укажите корректный e-mail.")
    return email


def _clean_name(value: Any, label: str) -> str:
    name = " ".join(str(value or "").strip().split())
    if not 1 <= len(name) <= 80 or any(ord(ch) < 32 for ch in name):
        raise AccountAuthError(f"Поле «{label}» обязательно.")
    return name


def _user(doc: Dict[str, Any], user_id: int) -> Optional[Dict[str, Any]]:
    return next((row for row in doc["users"] if int(row.get("user_id") or 0) == int(user_id)), None)


def _profile_complete(user: Dict[str, Any]) -> bool:
    return bool(user.get("first_name") and user.get("last_name") and user.get("email"))


def _public_user(user: Dict[str, Any], *, include_contact: bool = False) -> Dict[str, Any]:
    out = {key: user.get(key) for key in (
        "user_id", "username", "first_name", "last_name", "role", "status",
        "is_owner", "created_at_utc", "approved_at_utc", "revoked_at_utc",
        "last_login_at_utc", "phone_verified_at_utc",
    )}
    out["profile_complete"] = _profile_complete(user)
    if include_contact:
        out["email"] = str(user.get("email") or "")
        phone = str(user.get("phone") or "")
        out["phone_mask"] = ("+•••" + phone[-4:]) if phone else ""
    return out


def ensure_owner(owner_id: Any) -> Optional[Dict[str, Any]]:
    try:
        uid = int(owner_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if not uid:
        return None
    configured_owner = str(os.environ.get("NTA_TELEGRAM_CHAT_ID") or "").strip()
    if not configured_owner or str(uid) != configured_owner:
        raise AccountAuthError("Owner identity не совпадает с настроенным личным чатом Telegram.", 403)
    with _LOCK:
        doc = _read_doc()
        existing = _user(doc, uid)
        changed = False
        if existing is None:
            legacy = _remote_config()
            legacy_user = next((row for row in legacy.get("users") or [] if int(row.get("user_id") or 0) == uid), {})
            existing = {
                "user_id": uid,
                "username": str(legacy_user.get("username") or ""),
                "first_name": str(legacy_user.get("first_name") or ""),
                "last_name": str(legacy_user.get("last_name") or ""),
                "email": "", "phone": "", "phone_hash": str(legacy.get("owner_phone_hash") or ""),
                "role": "owner", "status": "active", "is_owner": True,
                "created_at_utc": _now_iso(), "approved_at_utc": _now_iso(), "revoked_at_utc": "",
            }
            doc["users"].append(existing)
            changed = True
        else:
            if existing.get("role") != "owner" or not existing.get("is_owner") or existing.get("status") != "active":
                existing.update({"role": "owner", "is_owner": True, "status": "active", "revoked_at_utc": ""})
                changed = True
        if changed:
            _write_doc(doc)
        return _public_user(existing, include_contact=True)


def find_active_user(user_id: Any) -> Optional[Dict[str, Any]]:
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    with _LOCK:
        doc = _read_doc()
        user = _user(doc, uid)
        return dict(user) if user and user.get("status") == "active" and _profile_complete(user) else None


def _require_owner_in_doc(doc: Dict[str, Any], owner_id: Any) -> Dict[str, Any]:
    try:
        uid = int(owner_id or 0)
    except (TypeError, ValueError):
        uid = 0
    owner = _user(doc, uid) if uid else None
    if (not owner or owner.get("status") != "active" or not owner.get("is_owner")
            or str(owner.get("user_id")) != str(os.environ.get("NTA_TELEGRAM_CHAT_ID") or "")):
        raise AccountAuthError("Только владелец может просматривать пользователей.", 403)
    return owner


def list_users(owner_id: Any) -> Dict[str, Any]:
    with _LOCK:
        doc = _read_doc()
        _require_owner_in_doc(doc, owner_id)
        users = sorted(doc["users"], key=lambda row: (not bool(row.get("is_owner")), str(row.get("created_at_utc") or "")))
        return {"users": [_public_user(row, include_contact=True) for row in users], "storage": storage_status()}


def update_user(owner_id: Any, user_id: Any, *, role: str = "", revoke: bool = False) -> Dict[str, Any]:
    uid = int(user_id)
    with _LOCK:
        doc = _read_doc()
        try:
            _require_owner_in_doc(doc, owner_id)
        except AccountAuthError:
            raise AccountAuthError("Только владелец может управлять пользователями.", 403) from None
        user = _user(doc, uid)
        if user is None:
            raise AccountAuthError("Пользователь не найден.", 404)
        if user.get("is_owner"):
            raise AccountAuthError("Аккаунт владельца нельзя отозвать или понизить.", 403)
        if revoke:
            user.update({"status": "revoked", "revoked_at_utc": _now_iso()})
            for session in doc["sessions"]:
                if int(session.get("user_id") or 0) == uid:
                    session["revoked"] = True
        elif role:
            if role not in {"read_only", "full_control"}:
                raise AccountAuthError("Неизвестная роль.")
            user["role"] = role
        user["updated_at_utc"] = _now_iso()
        _write_doc(doc)
    _audit("user_revoked" if revoke else "user_role_changed", owner_id=int(owner_id), user_id=uid)
    return list_users(owner_id)


def _cleanup(doc: Dict[str, Any]) -> None:
    now = time.time()
    doc["challenges"] = [row for row in doc["challenges"] if float(row.get("expires_at") or 0) > now][-100:]
    doc["sessions"] = [row for row in doc["sessions"] if float(row.get("expires_at") or 0) > now and not row.get("revoked")][-100:]


def _login_rate(ip: str) -> None:
    now = time.time()
    key = str(ip or "unknown")
    with _RATE_LOCK:
        q = _LOGIN_RATE[key]
        while q and q[0] <= now - 60:
            q.popleft()
        if len(q) >= 10:
            raise AccountAuthError("Слишком много попыток входа. Повторите через минуту.", 429)
        q.append(now)


def start_login(*, bot_username: str, ip: str, user_agent: str = "") -> Dict[str, Any]:
    _login_rate(ip)
    username = str(bot_username or "").strip().lstrip("@")
    if not username:
        raise AccountAuthError("Telegram-бот не настроен.", 503)
    challenge_id = secrets.token_urlsafe(24)
    code = secrets.token_hex(4).upper()
    now = time.time()
    with _LOCK:
        doc = _read_doc()
        _cleanup(doc)
        doc["challenges"].append({
            "challenge_id": challenge_id, "code": code, "status": "created",
            "created_at_utc": _now_iso(), "expires_at": now + CHALLENGE_TTL_SEC,
            "ip_hash": hashlib.sha256(str(ip or "").encode()).hexdigest(),
            "ua_hash": hashlib.sha256(str(user_agent or "").encode()).hexdigest(),
        })
        _write_doc(doc)
    _audit("login_started", ip=ip)
    return {
        "challenge_id": challenge_id, "status": "created", "expires_in_sec": CHALLENGE_TTL_SEC,
        "bot_url": f"https://t.me/{username}?start=login_{code}",
    }


def _challenge(doc: Dict[str, Any], *, challenge_id: str = "", code: str = "",
               user_id: int = 0, statuses: Tuple[str, ...] = ()) -> Optional[Dict[str, Any]]:
    now = time.time()
    for row in reversed(doc["challenges"]):
        if float(row.get("expires_at") or 0) <= now:
            continue
        if statuses and str(row.get("status") or "") not in statuses:
            continue
        if challenge_id and hmac.compare_digest(str(row.get("challenge_id") or ""), challenge_id):
            return row
        if code and hmac.compare_digest(str(row.get("code") or "").upper(), code.upper()):
            return row
        if user_id and int(row.get("user_id") or 0) == user_id:
            return row
    return None


def _required_fields(user: Optional[Dict[str, Any]]) -> list[str]:
    if not user:
        return ["first_name", "last_name", "email"]
    return [key for key in ("first_name", "last_name", "email") if not str(user.get(key) or "").strip()]


def login_state(challenge_id: str) -> Dict[str, Any]:
    with _LOCK:
        doc = _read_doc()
        challenge = _challenge(doc, challenge_id=str(challenge_id or ""))
        if challenge is None:
            raise AccountAuthError("Запрос входа истёк. Начните заново.", 410)
        user = _user(doc, int(challenge.get("user_id") or 0)) if challenge.get("user_id") else None
        return {
            "challenge_id": challenge.get("challenge_id"), "status": challenge.get("status"),
            "required_fields": _required_fields(user),
            "profile": {
                "first_name": str((user or {}).get("first_name") or ""),
                "last_name": str((user or {}).get("last_name") or ""),
                "email": str((user or {}).get("email") or ""),
            } if challenge.get("status") == "awaiting_profile" else {},
        }


def complete_profile(challenge_id: str, profile: Dict[str, Any], *,
                     api_call: Callable[..., Any], owner_chat_id: str) -> Dict[str, Any]:
    first_name = _clean_name(profile.get("first_name"), "Имя")
    last_name = _clean_name(profile.get("last_name"), "Фамилия")
    email = _valid_email(profile.get("email"))
    with _LOCK:
        doc = _read_doc()
        challenge = _challenge(doc, challenge_id=str(challenge_id or ""), statuses=("awaiting_profile",))
        if challenge is None:
            raise AccountAuthError("Профиль уже обработан или запрос истёк.", 409)
        user = _user(doc, int(challenge.get("user_id") or 0))
        if user is None:
            raise AccountAuthError("Telegram identity не найдена.", 409)
        user.update({"first_name": first_name, "last_name": last_name, "email": email, "updated_at_utc": _now_iso()})
        if user.get("status") == "active":
            challenge["status"] = "login_approved"
        else:
            challenge["status"] = "pending_owner"
        _write_doc(doc)
        pending_owner = challenge["status"] == "pending_owner"
        snapshot = dict(user)
        cid = str(challenge.get("challenge_id") or "")
    if pending_owner:
        _send_owner_approval(api_call, owner_chat_id, snapshot, cid)
        api_call("sendMessage", {"chat_id": int(snapshot["user_id"]), "text": "Профиль заполнен. Запрос отправлен владельцу StratForge AI."})
    return login_state(challenge_id)


def _send_owner_approval(api_call: Callable[..., Any], owner_chat_id: str,
                         user: Dict[str, Any], challenge_id: str) -> None:
    label = html.escape(f"{user.get('first_name', '')} {user.get('last_name', '')}".strip())
    api_call("sendMessage", {
        "chat_id": owner_chat_id, "parse_mode": "HTML",
        "text": (
            "🔐 <b>Новый аккаунт StratForge AI</b>\n"
            f"Пользователь: <b>{label}</b>\n"
            f"Telegram user id: <code>{int(user.get('user_id') or 0)}</code>\n"
            f"Username: @{html.escape(str(user.get('username') or '—'))}\n"
            f"E-mail: <code>{html.escape(str(user.get('email') or ''))}</code>\n"
            "Телефон подтверждён через requestContact.\n\n"
            "Только ваше личное подтверждение активирует аккаунт."
        ),
        "reply_markup": {"inline_keyboard": [[
            {"text": "✅ Разрешить аккаунт", "callback_data": f"account_allow:{challenge_id}"},
            {"text": "⛔ Отклонить", "callback_data": f"account_deny:{challenge_id}"},
        ]]},
    })


def process_update(update: Dict[str, Any], *, api_call: Callable[..., Any], owner_chat_id: str) -> bool:
    callback = update.get("callback_query") if isinstance(update, dict) else None
    if isinstance(callback, dict):
        revoke_match = re.fullmatch(r"account_revoke:(\d{1,20})", str(callback.get("data") or ""))
        if revoke_match:
            actor = int((callback.get("from") or {}).get("id") or 0)
            if str(actor) != str(owner_chat_id):
                api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "Только владелец может отозвать аккаунт.", "show_alert": True})
                return True
            uid = int(revoke_match.group(1))
            try:
                update_user(actor, uid, revoke=True)
                api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "Аккаунт отозван."})
                api_call("sendMessage", {"chat_id": uid, "text": "⛔ Владелец отозвал ваш аккаунт StratForge AI."})
            except AccountAuthError as exc:
                api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": str(exc), "show_alert": True})
            return True
        match = re.fullmatch(r"account_(allow|deny):([A-Za-z0-9_-]{20,})", str(callback.get("data") or ""))
        if not match:
            return False
        actor = int((callback.get("from") or {}).get("id") or 0)
        if str(actor) != str(owner_chat_id):
            api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "Только владелец может подтвердить аккаунт.", "show_alert": True})
            return True
        with _LOCK:
            doc = _read_doc()
            challenge = _challenge(doc, challenge_id=match.group(2), statuses=("pending_owner",))
            if challenge is None:
                api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "Запрос истёк или уже обработан.", "show_alert": True})
                return True
            user = _user(doc, int(challenge.get("user_id") or 0))
            if user is None:
                return True
            allowed = match.group(1) == "allow"
            if allowed:
                user.update({"status": "active", "role": "read_only", "approved_at_utc": _now_iso(), "revoked_at_utc": ""})
                challenge["status"] = "login_approved"
            else:
                user.update({"status": "denied", "revoked_at_utc": _now_iso()})
                challenge["status"] = "denied"
            _write_doc(doc)
            uid = int(user["user_id"])
        api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "Аккаунт разрешён." if allowed else "Запрос отклонён."})
        api_call("sendMessage", {"chat_id": uid, "text": "✅ Аккаунт StratForge AI активирован." if allowed else "⛔ Владелец отклонил создание аккаунта."})
        _audit("account_approved" if allowed else "account_denied", owner_id=actor, user_id=uid)
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
        try:
            users = [row for row in list_users(uid)["users"] if row.get("status") == "active" and not row.get("is_owner")]
        except AccountAuthError:
            users = []
        if not users:
            api_call("sendMessage", {"chat_id": uid, "text": "Активных пользовательских аккаунтов нет."})
            return True
        lines = ["🔐 <b>Аккаунты StratForge AI</b>"]
        buttons = []
        for row in users[:30]:
            label = row.get("username") or row.get("first_name") or row.get("user_id")
            lines.append(f"• {html.escape(str(label))} · <code>{int(row['user_id'])}</code> · {html.escape(str(row.get('role') or 'read_only'))}")
            buttons.append([{"text": f"⛔ Отозвать {label}", "callback_data": f"account_revoke:{int(row['user_id'])}"}])
        api_call("sendMessage", {"chat_id": uid, "text": "\n".join(lines), "parse_mode": "HTML", "reply_markup": {"inline_keyboard": buttons}})
        return True
    start = re.fullmatch(r"/start(?:@[A-Za-z0-9_]+)?\s+login_([A-Fa-f0-9]{8})", text)
    if start:
        with _LOCK:
            doc = _read_doc()
            challenge = _challenge(doc, code=start.group(1), statuses=("created",))
            if challenge is None:
                api_call("sendMessage", {"chat_id": uid, "text": "Ссылка входа истекла или уже использована."})
                return True
            challenge.update({"user_id": uid, "status": "awaiting_contact", "telegram_started_at_utc": _now_iso()})
            challenge["telegram_user"] = {
                "username": str(sender.get("username") or ""),
                "first_name": str(sender.get("first_name") or ""),
                "last_name": str(sender.get("last_name") or ""),
            }
            _write_doc(doc)
        api_call("sendMessage", {
            "chat_id": uid,
            "text": "Подтвердите личность: отправьте свой Telegram-контакт кнопкой ниже. Чужой или введённый вручную номер не принимается.",
            "reply_markup": {"keyboard": [[{"text": "📱 Подтвердить мой номер", "request_contact": True}]], "resize_keyboard": True, "one_time_keyboard": True},
        })
        return True

    contact = message.get("contact")
    if isinstance(contact, dict):
        with _LOCK:
            doc = _read_doc()
            challenge = _challenge(doc, user_id=uid, statuses=("awaiting_contact",))
            if challenge is None:
                return False
            if int(contact.get("user_id") or 0) != uid:
                challenge["status"] = "identity_mismatch"
                _write_doc(doc)
                api_call("sendMessage", {"chat_id": uid, "text": "Контакт не принадлежит вашему Telegram user id. Вход отклонён.", "reply_markup": {"remove_keyboard": True}})
                return True
            phone = _normalize_phone(contact.get("phone_number"))
            if not 7 <= len(phone) <= 15:
                challenge["status"] = "phone_invalid"
                _write_doc(doc)
                return True
            user = _user(doc, uid)
            tg = challenge.get("telegram_user") or {}
            if user and user.get("phone_hash") and not hmac.compare_digest(str(user.get("phone_hash")), _phone_hash(phone)):
                challenge["status"] = "phone_mismatch"
                _write_doc(doc)
                api_call("sendMessage", {"chat_id": uid, "text": "Номер не совпадает с аккаунтом. Вход отклонён.", "reply_markup": {"remove_keyboard": True}})
                return True
            if user is None:
                user = {
                    "user_id": uid, "username": str(tg.get("username") or ""),
                    "first_name": str(tg.get("first_name") or ""), "last_name": str(tg.get("last_name") or ""),
                    "email": "", "phone": phone, "phone_hash": _phone_hash(phone),
                    "role": "read_only", "status": "pending", "is_owner": str(uid) == str(owner_chat_id),
                    "created_at_utc": _now_iso(), "approved_at_utc": "", "revoked_at_utc": "",
                }
                if user["is_owner"]:
                    user.update({"role": "owner", "status": "active", "approved_at_utc": _now_iso()})
                doc["users"].append(user)
            else:
                user.update({
                    "username": str(tg.get("username") or user.get("username") or ""),
                    "phone": phone, "phone_hash": _phone_hash(phone), "phone_verified_at_utc": _now_iso(),
                })
                if not user.get("first_name"):
                    user["first_name"] = str(tg.get("first_name") or "")
                if not user.get("last_name"):
                    user["last_name"] = str(tg.get("last_name") or "")
            user["phone_verified_at_utc"] = _now_iso()
            if user.get("status") in {"revoked", "denied"}:
                user["status"] = "pending"
                challenge["status"] = "pending_owner" if _profile_complete(user) else "awaiting_profile"
            elif _profile_complete(user):
                challenge["status"] = "login_approved" if user.get("status") == "active" else "pending_owner"
            else:
                challenge["status"] = "awaiting_profile"
            _write_doc(doc)
            next_status = challenge["status"]
            cid = str(challenge["challenge_id"])
            snapshot = dict(user)
        if next_status == "pending_owner":
            _send_owner_approval(api_call, owner_chat_id, snapshot, cid)
        messages = {
            "awaiting_profile": "Телефон подтверждён. Вернитесь в приложение и заполните обязательные поля профиля.",
            "login_approved": "Личность подтверждена. Вернитесь в приложение — вход разрешён.",
            "pending_owner": "Личность подтверждена. Ожидайте личного разрешения владельца.",
            "account_blocked": "Этот аккаунт отозван или отклонён владельцем.",
        }
        api_call("sendMessage", {"chat_id": uid, "text": messages[next_status], "reply_markup": {"remove_keyboard": True}})
        _audit("contact_verified", user_id=uid)
        return True
    return False


def create_session_for_challenge(challenge_id: str, *, ip: str, user_agent: str) -> Dict[str, Any]:
    with _LOCK:
        doc = _read_doc()
        challenge = _challenge(doc, challenge_id=str(challenge_id or ""), statuses=("login_approved",))
        if challenge is None:
            return login_state(challenge_id)
        uid = int(challenge.get("user_id") or 0)
        user = _user(doc, uid)
        if not user or user.get("status") != "active" or not _profile_complete(user):
            raise AccountAuthError("Аккаунт ещё не активирован.", 403)
        token = secrets.token_urlsafe(48)
        csrf = secrets.token_urlsafe(32)
        now = time.time()
        doc["sessions"].append({
            "token_hash": hashlib.sha256(token.encode()).hexdigest(), "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(),
            "csrf_token": csrf,
            "user_id": uid, "created_at_utc": _now_iso(), "expires_at": now + SESSION_TTL_SEC,
            "ip_hash": hashlib.sha256(str(ip or "").encode()).hexdigest(),
            "ua_hash": hashlib.sha256(str(user_agent or "").encode()).hexdigest(), "revoked": False,
        })
        challenge["status"] = "consumed"
        user["last_login_at_utc"] = _now_iso()
        _cleanup(doc)
        _write_doc(doc)
    _audit("login_succeeded", user_id=uid, ip=ip)
    return {"status": "authenticated", "session_token": token, "csrf_token": csrf, "user": _public_user(user, include_contact=True)}


def authenticate_session(token: str) -> Optional[Dict[str, Any]]:
    raw = str(token or "")
    if len(raw) < 40:
        return None
    digest = hashlib.sha256(raw.encode()).hexdigest()
    with _LOCK:
        doc = _read_doc()
        now = time.time()
        session = next((row for row in doc["sessions"] if not row.get("revoked") and float(row.get("expires_at") or 0) > now and hmac.compare_digest(str(row.get("token_hash") or ""), digest)), None)
        if session is None:
            return None
        user = _user(doc, int(session.get("user_id") or 0))
        if not user or user.get("status") != "active":
            return None
        return {
            "source": "desktop_session", "user_id": int(user["user_id"]),
            "role": str(user.get("role") or "read_only"), "is_owner": bool(user.get("is_owner")),
            "username": str(user.get("username") or ""),
            "csrf_hash": str(session.get("csrf_hash") or ""),
            "csrf_token": str(session.get("csrf_token") or ""),
            "user": _public_user(user, include_contact=True),
        }


def verify_csrf(context: Dict[str, Any], csrf_token: str) -> bool:
    supplied = hashlib.sha256(str(csrf_token or "").encode()).hexdigest()
    return bool(context.get("csrf_hash") and hmac.compare_digest(str(context["csrf_hash"]), supplied))


def revoke_session(token: str) -> None:
    digest = hashlib.sha256(str(token or "").encode()).hexdigest()
    with _LOCK:
        doc = _read_doc()
        changed = False
        for session in doc["sessions"]:
            if hmac.compare_digest(str(session.get("token_hash") or ""), digest):
                session["revoked"] = True
                changed = True
        if changed:
            _write_doc(doc)


def _audit(event: str, *, user_id: int = 0, owner_id: int = 0, ip: str = "") -> None:
    row = {"timestamp": _now_iso(), "source": "telegram_account_auth", "event": event,
           "user_id": user_id or None, "owner_id": owner_id or None, "ip": str(ip or "")}
    path = _audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
