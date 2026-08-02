"""Telegram-backed accounts and desktop browser sessions.

Identity is anchored to Telegram ``user.id`` (login factor). Google OAuth is
**not** required for ordinary app use (demo, practice, community, AI, etc.).
Google + a fresh Telegram confirmation are required only before NinjaTrader
control actions (personal bridge, live/paper commands that drive NT) — see
``nt_action_gate`` / ``require_nt_dual_auth``.

Personal data, login challenges and session-token hashes are stored in one
Windows DPAPI-encrypted document. Only an owner callback from the configured
private bot chat can activate a new account. Plain session tokens exist only in
the browser cookie and in the single response that creates them.

Staging-only helpers: virtual users, test-auth sessions, owner impersonation
(see ``runtime_env`` / ``test_auth``).
"""
from __future__ import annotations

import base64
import copy
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

from . import legal, runtime_env, secure_store


SESSION_COOKIE = "sf_session"
SESSION_TTL_SEC = 30 * 24 * 60 * 60
CHALLENGE_TTL_SEC = 15 * 60
OWNER_APPROVAL_TTL_SEC = 7 * 24 * 60 * 60
ADMIN_REVOKE_NOTICE_TTL_SEC = 24 * 60 * 60
IMPERSONATION_TTL_SEC = 4 * 60 * 60
NT_STEP_UP_TTL_SEC = 30 * 60
NT_CONFIRM_TTL_SEC = 10 * 60
UX_MODES = ("beginner", "professional")
ACCOUNT_STORE_VERSION = 2
ROLES = {"read_only", "full_control", "owner"}
# Owner-toggleable capabilities. The ids match the Aurora navigation ids so the
# client can gate the left rail directly. ``personal_nt`` gates the "connect my
# own NinjaTrader" flow. The owner always has every feature enabled.
FEATURES: Dict[str, Dict[str, Any]] = {
    "backtest":    {"label": "Бэктест",        "default": True},
    "trading":     {"label": "Торговля",       "default": True},
    "desktop":     {"label": "Рабочий стол",   "default": True},
    "performance": {"label": "Финансы",        "default": True},
    "strategies":  {"label": "Стратегии",      "default": True},
    "ai":          {"label": "AI Lab",          "default": True},
    "agents":      {"label": "AI Agents",       "default": False},
    "news":        {"label": "Новости",         "default": True},
    "topstep":     {"label": "TopStep",         "default": False},
    "docs":        {"label": "Документы",       "default": False},
    "personal_nt": {"label": "Свой NinjaTrader", "default": True},
}
_MAGIC = b"STRATFORGE-ACCOUNTS-DPAPI-1\n"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOCK = threading.RLock()
_RATE_LOCK = threading.Lock()
_LOGIN_RATE: Dict[str, Deque[float]] = defaultdict(deque)
_UNREADABLE_STORE_SUFFIX = ".unreadable"
# Decrypting the DPAPI account store is comparatively expensive on Windows.
# A first-page load makes several authenticated requests in parallel, so each
# one used to decrypt the same immutable file and contend on ``_LOCK``. Keep
# only a copy of the current file version in this process. The cache key
# includes the full path and stat marker, so a write or outside replacement
# cannot leak stale access or revoked-session state.
_DOC_CACHE_KEY: Optional[Tuple[str, int, int]] = None
_DOC_CACHE_DOC: Optional[Dict[str, Any]] = None


class AccountAuthError(RuntimeError):
    def __init__(self, message: str, status: int = 400, *, code: str = ""):
        super().__init__(message)
        self.status = int(status)
        self.code = str(code or "")


def _root() -> Path:
    return _PROJECT_ROOT


def _store_path() -> Path:
    return runtime_env.data_path("integrations", "accounts.dpapi", project_root=_root())


def _doc_cache_key(path: Path) -> Optional[Tuple[str, int, int]]:
    try:
        stat = path.stat()
    except OSError:
        return None
    identity = path if path.is_absolute() else path.resolve()
    return (str(identity), int(stat.st_mtime_ns), int(stat.st_size))


def _clear_doc_cache() -> None:
    global _DOC_CACHE_KEY, _DOC_CACHE_DOC
    with _LOCK:
        _DOC_CACHE_KEY = None
        _DOC_CACHE_DOC = None


def _cache_doc(path: Path, doc: Dict[str, Any]) -> None:
    global _DOC_CACHE_KEY, _DOC_CACHE_DOC
    key = _doc_cache_key(path)
    if key is None:
        _clear_doc_cache()
        return
    with _LOCK:
        _DOC_CACHE_KEY = key
        _DOC_CACHE_DOC = copy.deepcopy(doc)


def _remote_config_path() -> Path:
    return runtime_env.data_path("integrations", "telegram.remote-access.json", project_root=_root())


def _audit_path() -> Path:
    return runtime_env.data_path("audit", "account-auth.jsonl", project_root=_root())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalized_future_utc(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise AccountAuthError("Срок доступа должен быть UTC ISO-8601.") from None
    if parsed.tzinfo is None:
        raise AccountAuthError("Срок доступа должен содержать UTC offset.")
    normalized = parsed.astimezone(timezone.utc)
    if normalized <= datetime.now(timezone.utc):
        raise AccountAuthError("Срок административного доступа должен быть в будущем.")
    return normalized.isoformat(timespec="seconds").replace("+00:00", "Z")


def _default_doc() -> Dict[str, Any]:
    return {"version": ACCOUNT_STORE_VERSION, "users": [], "challenges": [], "sessions": []}


def _migrate_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Apply compatibility defaults without confusing old users with new signups.

    UX modes were introduced in schema v2.  Accounts that already existed in a
    v1 store had the professional product surface before the upgrade, so they
    keep it.  New v2 accounts deliberately start without ``ux_mode`` and must
    pass the beginner/professional choice screen.
    """
    try:
        version = int(doc.get("version") or 1)
    except (TypeError, ValueError):
        version = 1
    if version < 2:
        for user in doc.get("users") or []:
            if not isinstance(user, dict):
                continue
            if str(user.get("ux_mode") or "").strip().lower() not in UX_MODES:
                user["ux_mode"] = "professional"
                user["ux_mode_migrated_at_utc"] = _now_iso()
        doc["version"] = ACCOUNT_STORE_VERSION
    return doc


def _quarantine_unreadable_store(path: Path, reason: str) -> None:
    """Keep a copied/foreign DPAPI file as evidence and start a fresh local doc.

    DPAPI CurrentUser blobs are intentionally not portable across Windows users
    or computers. When a whole app folder is copied to PC2, the old
    ``accounts.dpapi`` should not brick the login flow; it is preserved under a
    timestamped name and the new machine can create its own protected store.
    """
    _clear_doc_cache()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = path.with_name(f"{path.name}{_UNREADABLE_STORE_SUFFIX}-{stamp}.bak")
    try:
        os.replace(path, target)
    except OSError as exc:
        raise AccountAuthError(
            f"Не удалось изолировать DPAPI-файл аккаунтов, перенесённый с другого ПК: {exc}",
            503,
        ) from None
    note = {
        "timestamp": _now_iso(),
        "event": "accounts_dpapi_quarantined",
        "backup": target.name,
        "reason": str(reason or "")[:300],
        "message_ru": (
            "Файл accounts.dpapi был создан другим Windows-пользователем или ПК. "
            "Он сохранён рядом как backup; для этого компьютера будет создан новый "
            "локальный защищённый store после Telegram-проверки."
        ),
    }
    try:
        note_path = path.with_name("accounts.dpapi.recovery.json")
        note_path.write_text(json.dumps(note, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    try:
        _audit("accounts_dpapi_quarantined")
    except OSError:
        pass


def _read_doc() -> Dict[str, Any]:
    if runtime_env.is_production() and runtime_env.environment_explicit():
        from . import storage_router
        from .production_storage import StorageError
        try:
            doc = storage_router.read_document("auth", _default_doc())
        except StorageError as exc:
            raise AccountAuthError(
                f"Production account repository unavailable ({exc.code}).",
                503, code=exc.code,
            ) from None
        if not isinstance(doc, dict):
            raise AccountAuthError("Production account repository returned invalid data.", 500)
        for key in ("users", "challenges", "sessions"):
            if not isinstance(doc.get(key), list):
                doc[key] = []
        return _migrate_doc(doc)
    path = _store_path()
    cache_key = _doc_cache_key(path)
    if cache_key is None:
        _clear_doc_cache()
        return _default_doc()
    with _LOCK:
        if _DOC_CACHE_KEY == cache_key and _DOC_CACHE_DOC is not None:
            # Callers may amend the returned document before an explicit
            # _write_doc. Never expose the cache object itself.
            return copy.deepcopy(_DOC_CACHE_DOC)
    try:
        raw = path.read_bytes()
        if not raw.startswith(_MAGIC):
            raise AccountAuthError("Неизвестный формат защищённого хранилища аккаунтов.", 500)
        encrypted = base64.b64decode(raw[len(_MAGIC):], validate=True)
        doc = json.loads(secure_store._unprotect(encrypted).decode("utf-8"))
    except AccountAuthError:
        raise
    except secure_store.SecureStoreError as exc:
        if secure_store.available():
            _quarantine_unreadable_store(path, str(exc))
            return _default_doc()
        raise AccountAuthError(str(exc), 503) from None
    except Exception as exc:
        raise AccountAuthError(f"Не удалось прочитать защищённые аккаунты: {exc}", 500) from None
    if not isinstance(doc, dict):
        raise AccountAuthError("Защищённое хранилище аккаунтов повреждено.", 500)
    for key in ("users", "challenges", "sessions"):
        if not isinstance(doc.get(key), list):
            doc[key] = []
    doc = _migrate_doc(doc)
    _cache_doc(path, doc)
    return doc


def _read_doc_reference() -> Dict[str, Any]:
    """Internal read-only view of the current local cache.

    Mutation paths keep using ``_read_doc`` and therefore receive an isolated
    deep copy.  Lookup paths may inspect this object only while ``_LOCK`` is
    held and must copy the selected row before returning it.
    """
    if runtime_env.is_production() and runtime_env.environment_explicit():
        return _read_doc()
    path = _store_path()
    key = _doc_cache_key(path)
    with _LOCK:
        if key is not None and _DOC_CACHE_KEY == key and _DOC_CACHE_DOC is not None:
            return _DOC_CACHE_DOC
        loaded = _read_doc()
        if key is not None and _DOC_CACHE_KEY == _doc_cache_key(path) and _DOC_CACHE_DOC is not None:
            return _DOC_CACHE_DOC
        return loaded


def _write_doc(doc: Dict[str, Any]) -> None:
    if runtime_env.is_production() and runtime_env.environment_explicit():
        from . import storage_router
        from .production_storage import StorageError
        try:
            storage_router.write_document("auth", doc)
            _clear_doc_cache()
            return
        except StorageError as exc:
            raise AccountAuthError(
                f"Production account repository write denied ({exc.code}).",
                503, code=exc.code,
            ) from None
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
        # Keep cache semantics identical to a subsequent _read_doc: legacy
        # v1 records receive the in-memory v2 UX migration before use.
        _cache_doc(path, _migrate_doc(copy.deepcopy(doc)))
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
    # Mandatory Telegram verification for every login (owner included). This is a
    # security invariant that must NOT depend on a mutable flag which can be reset
    # in the config file. Once the public Mini App is exposed (remote_enabled),
    # authentication is ALWAYS required; disabling it there would let any Telegram
    # visitor inherit access. With no remote access configured it still defaults
    # to required. Only the explicit test bypass turns it off.
    if os.environ.get("NTA_TEST_BYPASS_AUTH") == "1":
        return False
    config = _remote_config()
    if config.get("remote_enabled"):
        return True
    return bool(config.get("desktop_auth_required", True))


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
    if runtime_env.is_production() and runtime_env.environment_explicit():
        from . import storage_router
        return storage_router.storage_status()
    return {
        "available": secure_store.available(),
        "backend": secure_store.backend_name(),
        "encrypted": _store_path().is_file(),
        "auth_required": auth_required(),
    }


def dual_auth_enforced() -> bool:
    """Google is required for NinjaTrader control actions (not for login).

    Kept for admin migration lists. Override with ``NTA_NT_GOOGLE_REQUIRED=0``
    to disable the Google half of the NT gate (Telegram step-up still applies
    unless also disabled via ``NTA_NT_TELEGRAM_CONFIRM_REQUIRED=0``).
    """
    flag = str(os.environ.get("NTA_NT_GOOGLE_REQUIRED") or os.environ.get("NTA_DUAL_AUTH_REQUIRED") or "1").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    return True


def telegram_nt_confirm_required() -> bool:
    flag = str(os.environ.get("NTA_NT_TELEGRAM_CONFIRM_REQUIRED") or "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def user_needs_google(user: Optional[Dict[str, Any]]) -> bool:
    """Informational: user has no Google link and NT actions will require it.

    Never blocks login or general app sections.
    """
    if not user or user.get("is_owner"):
        return False
    if str(user.get("google_sub") or "").strip():
        return False
    if user.get("dual_auth_exempt"):
        return False
    return dual_auth_enforced()


def google_linked(user: Optional[Dict[str, Any]]) -> bool:
    if not user:
        return False
    if str(user.get("google_sub") or "").strip():
        return True
    # Auth context often carries ``_public_user`` (no raw google_sub).
    return bool(user.get("google_linked"))


def effective_ux_mode(user: Optional[Dict[str, Any]]) -> str:
    """Owner is always professional; others use stored ux_mode or empty."""
    if not user:
        return ""
    if user.get("is_owner"):
        return "professional"
    mode = str(user.get("ux_mode") or "").strip().lower()
    return mode if mode in UX_MODES else ""


def needs_ux_mode_choice(user: Optional[Dict[str, Any]]) -> bool:
    if not user or user.get("is_owner"):
        return False
    return effective_ux_mode(user) not in UX_MODES


def set_ux_mode(user_id: Any, mode: str, *, confirm_downgrade: bool = False) -> Dict[str, Any]:
    """Set student/professional. Downgrade to the student terminal requires confirmation."""
    uid = int(user_id or 0)
    clean = str(mode or "").strip().lower()
    if clean not in UX_MODES:
        raise AccountAuthError("Режим должен быть beginner или professional.", 400, code="ux_mode_invalid")
    with _LOCK:
        doc = _read_doc()
        user = _user(doc, uid)
        if not user:
            raise AccountAuthError("Пользователь не найден.", 404)
        if user.get("is_owner"):
            user["ux_mode"] = "professional"
            _write_doc(doc)
            return {"ok": True, "user": _public_user(user, include_contact=True), "ux_mode": "professional"}
        prev = str(user.get("ux_mode") or "").strip().lower()
        if prev == "professional" and clean == "beginner" and not confirm_downgrade:
            raise AccountAuthError(
                "Переход в режим «Студент» скроет стратегии, ИИ и NinjaTrader. "
                "Подтвердите действие явно.",
                409,
                code="ux_mode_confirm_required",
            )
        user["ux_mode"] = clean
        user["ux_mode_set_at_utc"] = _now_iso()
        _write_doc(doc)
        public = _public_user(user, include_contact=True)
    _audit("ux_mode_set", user_id=uid, extra={"ux_mode": clean, "previous": prev})
    return {"ok": True, "user": public, "ux_mode": clean, "previous": prev}


def _session_nt_elevated(session: Optional[Dict[str, Any]]) -> bool:
    if not session:
        return False
    try:
        until = float(session.get("nt_elevated_until") or 0)
    except (TypeError, ValueError):
        until = 0.0
    return until > time.time()


def nt_action_gate(
    user: Optional[Dict[str, Any]],
    *,
    session: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Whether the user may perform NinjaTrader control actions right now."""
    user = user or ((context or {}).get("user") if isinstance((context or {}).get("user"), dict) else {}) or {}
    if user.get("is_owner") or (context or {}).get("is_owner"):
        return {
            "ok": True, "ready": True, "google_ok": True, "telegram_ok": True,
            "google_required": False, "telegram_confirm_required": False,
            "code": "", "message": "",
            "nt_elevated_until": 0,
            "policy": "owner_exempt",
        }
    google_req = dual_auth_enforced()
    tg_req = telegram_nt_confirm_required()
    g_ok = (not google_req) or google_linked(user)
    sess = session
    if sess is None and context:
        # Elevation flag may be mirrored onto auth context.
        try:
            until = float(context.get("nt_elevated_until") or 0)
        except (TypeError, ValueError):
            until = 0.0
        tg_ok = (not tg_req) or until > time.time()
        elevated_until = until
    else:
        tg_ok = (not tg_req) or _session_nt_elevated(sess)
        try:
            elevated_until = float((sess or {}).get("nt_elevated_until") or 0)
        except (TypeError, ValueError):
            elevated_until = 0.0
    ready = g_ok and tg_ok
    code = ""
    message = ""
    if not g_ok:
        code = "nt_google_required"
        message = (
            "Чтобы управлять NinjaTrader (личный или рабочий контур), "
            "подключите Google-аккаунт. Остальные разделы доступны без Google."
        )
    elif not tg_ok:
        code = "nt_telegram_confirm_required"
        message = (
            "Подтвердите действие повторно в Telegram — "
            "это нужно перед любыми командами в NinjaTrader."
        )
    return {
        "ok": ready, "ready": ready, "google_ok": g_ok, "telegram_ok": tg_ok,
        "google_required": google_req, "telegram_confirm_required": tg_req,
        "google_linked": google_linked(user),
        "code": code, "message": message,
        "nt_elevated_until": elevated_until if tg_ok else 0,
        "policy": "nt_actions_only",
    }


def require_nt_dual_auth(context: Optional[Dict[str, Any]]) -> None:
    """Enforce Google + Telegram step-up for NinjaTrader control actions.

    Defense in depth: reload the user from the encrypted store by ``user_id``
    and ignore a forged ``google_linked`` flag on the public session payload.
    Elevation still comes from the authenticated session / context.
    """
    context = dict(context or {})
    try:
        uid = int(context.get("user_id") or 0)
    except (TypeError, ValueError):
        uid = 0
    raw_user: Optional[Dict[str, Any]] = None
    if uid > 0:
        with _LOCK:
            stored = _user(_read_doc(), uid)
            if stored is not None:
                raw_user = dict(stored)
                # Never trust a client/public google_linked without google_sub in store.
                if not str(raw_user.get("google_sub") or "").strip():
                    raw_user["google_linked"] = False
                context["user"] = raw_user
    gate = nt_action_gate(raw_user, context=context)
    if not gate.get("ok"):
        raise AccountAuthError(
            str(gate.get("message") or "Нужна двухфакторная проверка для NinjaTrader."),
            403,
            code=str(gate.get("code") or "nt_dual_auth"),
        )


def path_requires_nt_dual_auth(path: str, method: str = "POST") -> bool:
    """Sensitive NT control routes (not read-only observation)."""
    if str(method or "GET").upper() in {"GET", "HEAD"}:
        return False
    p = str(path or "")
    if p in {"/api/ops/runtime/command", "/api/workspaces/personal"}:
        return True
    if p.startswith("/api/bridge/pair/"):
        return True
    if p.startswith("/api/bridge/connections/"):
        return True
    if p.startswith("/api/bridge/commands"):
        return True
    if p.startswith("/api/ops/live/"):
        return True
    if p.startswith("/api/profiles/ninjatrader/"):
        return True
    if p == "/api/profiles/archive/remove-from-nt":
        return True
    # Paper/live strategy control against a connected NinjaTrader runtime.
    if p.startswith("/api/ops/strategies/") and any(
        marker in p for marker in ("/paper/", "/live/", "/arm", "/start", "/stop", "/pause", "/resume")
    ):
        return True
    return False


def google_migration_users(owner_id: Any) -> Dict[str, Any]:
    """Owner list: who still needs Google for NT actions / who linked."""
    with _LOCK:
        doc = _read_doc()
        _require_owner_in_doc(doc, owner_id)
        rows = []
        for user in doc.get("users") or []:
            if user.get("is_owner"):
                continue
            rows.append({
                "user_id": int(user.get("user_id") or 0),
                "username": str(user.get("username") or ""),
                "first_name": str(user.get("first_name") or ""),
                "status": str(user.get("status") or ""),
                "google_linked": bool(str(user.get("google_sub") or "").strip()),
                "google_email": str(user.get("google_email") or ""),
                "google_linked_at_utc": str(user.get("google_linked_at_utc") or ""),
                "needs_google": user_needs_google(user),
                "is_virtual": bool(user.get("is_virtual")),
                "created_at_utc": str(user.get("created_at_utc") or ""),
            })
    linked = sum(1 for row in rows if row["google_linked"])
    return {
        "ok": True,
        "users": rows,
        "without_google": [row for row in rows if not row["google_linked"]],
        "linked_count": linked,
        "pending_count": len(rows) - linked,
        "dual_auth_enforced": dual_auth_enforced(),
        "policy": "nt_actions_only",
        "note": "Google нужен только для управления NinjaTrader, не для входа в приложение.",
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


def _device_label(user_agent: Any) -> str:
    """A short, non-identifying device label parsed from a User-Agent."""
    ua = str(user_agent or "")
    if not ua:
        return "—"
    low = ua.lower()
    if "telegram" in low:
        return "Telegram Mini App"
    browser = ("Edge" if "edg/" in low else
               "Chrome" if "chrome" in low else
               "Firefox" if "firefox" in low else
               "Safari" if "safari" in low else "Браузер")
    os_name = ("Windows" if "windows" in low else
               "Android" if "android" in low else
               "iPhone" if "iphone" in low else
               "iPad" if "ipad" in low else
               "macOS" if ("mac os" in low or "macintosh" in low) else
               "Linux" if "linux" in low else "")
    return f"{browser}{(' · ' + os_name) if os_name else ''}"


def _machine_label() -> str:
    raw = (os.environ.get("NTA_DEVICE_LABEL")
           or os.environ.get("COMPUTERNAME")
           or os.environ.get("HOSTNAME")
           or "Этот компьютер")
    label = " ".join(str(raw or "").strip().split())
    label = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "", label)
    return label[:64] or "Этот компьютер"


def _device_id(user_agent: Any) -> str:
    basis = "|".join((
        _machine_label().lower(),
        str(os.environ.get("USERNAME") or os.environ.get("USER") or "").lower(),
        _device_label(user_agent).lower(),
    ))
    return hashlib.sha256(basis.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _upsert_device(user: Dict[str, Any], *, source: str, ip: str = "",
                   user_agent: str = "", email: str = "") -> None:
    now = _now_iso()
    device_id = _device_id(user_agent)
    device = _device_label(user_agent)
    machine = _machine_label()
    rows = user.get("devices") if isinstance(user.get("devices"), list) else []
    existing = next((row for row in rows if str(row.get("device_id") or "") == device_id), None)
    if existing is None:
        existing = {
            "device_id": device_id,
            "label": machine,
            "client": device,
            "first_seen_at_utc": now,
        }
        rows.append(existing)
    existing.update({
        "label": machine,
        "client": device,
        "last_seen_at_utc": now,
        "last_source": source,
        "last_ip": _mask_ip(ip),
    })
    profile_email = str(email or "").strip().lower()
    if profile_email:
        existing["email"] = profile_email
    user["devices"] = rows[-20:]
    user["last_login_device_id"] = device_id
    user["last_login_machine"] = machine


def _mask_ip(ip: Any) -> str:
    """Mask an IP so the owner sees a coarse origin without storing full PII."""
    text = str(ip or "").strip()
    if not text:
        return ""
    if ":" in text:  # IPv6
        parts = [p for p in text.split(":") if p]
        return ":".join(parts[:2]) + ":••••" if parts else "••••"
    parts = text.split(".")
    if len(parts) == 4:
        return ".".join(parts[:2]) + ".•.•"
    return "•••"


def _append_login(user: Dict[str, Any], *, source: str, ip: str = "",
                  user_agent: str = "", email: str = "") -> None:
    now = _now_iso()
    device = _device_label(user_agent)
    machine = _machine_label()
    device_id = _device_id(user_agent)
    user["last_login_at_utc"] = now
    user["last_login_source"] = source
    user["last_login_device"] = device
    user["last_login_machine"] = machine
    user["last_login_device_id"] = device_id
    _upsert_device(user, source=source, ip=ip, user_agent=user_agent,
                   email=email or str(user.get("email") or ""))
    history = user.get("login_history") if isinstance(user.get("login_history"), list) else []
    history.append({
        "at": now, "source": source, "device": device,
        "machine": machine, "device_id": device_id, "ip": _mask_ip(ip),
    })
    user["login_history"] = history[-20:]


def _user(doc: Dict[str, Any], user_id: int) -> Optional[Dict[str, Any]]:
    return next((row for row in doc["users"] if int(row.get("user_id") or 0) == int(user_id)), None)


def _profile_complete(user: Dict[str, Any]) -> bool:
    return bool(user.get("first_name") and user.get("last_name") and user.get("email"))


def feature_catalog() -> list[Dict[str, Any]]:
    return [{"id": fid, "label": meta["label"], "default": bool(meta["default"])} for fid, meta in FEATURES.items()]


def effective_features(user: Dict[str, Any]) -> Dict[str, bool]:
    if user.get("is_owner"):
        return {fid: True for fid in FEATURES}
    overrides = user.get("feature_overrides") if isinstance(user.get("feature_overrides"), dict) else {}
    out: Dict[str, bool] = {}
    for fid, meta in FEATURES.items():
        value = overrides.get(fid)
        out[fid] = bool(value) if isinstance(value, bool) else bool(meta["default"])
    return out


def _avatars_dir() -> Path:
    directory = runtime_env.data_path("integrations", "avatars", project_root=_root())
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def avatar_file(user_id: Any) -> Optional[Path]:
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    with _LOCK:
        doc = _read_doc()
        user = _user(doc, uid)
    ext = str((user or {}).get("avatar_ext") or "")
    if not user or not ext:
        return None
    path = _avatars_dir() / f"{uid}.{ext}"
    return path if path.is_file() else None


def _avatar_data_url(user: Dict[str, Any]) -> str:
    ext = str(user.get("avatar_ext") or "")
    try:
        uid = int(user.get("user_id") or 0)
    except (TypeError, ValueError):
        uid = 0
    if not ext or uid <= 0:
        return ""
    path = _avatars_dir() / f"{uid}.{ext}"
    try:
        blob = path.read_bytes()
    except OSError:
        return ""
    if not blob or len(blob) > 500_000:
        return ""
    mime = "image/png" if ext == "png" else "image/webp" if ext == "webp" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(blob).decode("ascii")


def _public_user(user: Dict[str, Any], *, include_contact: bool = False,
                 include_avatar: bool = False) -> Dict[str, Any]:
    out = {key: user.get(key) for key in (
        "user_id", "username", "first_name", "last_name", "role", "status",
        "is_owner", "created_at_utc", "approved_at_utc", "revoked_at_utc",
        "last_login_at_utc", "phone_verified_at_utc",
        "last_login_source", "last_login_device", "last_login_machine",
        "last_login_device_id", "blocked_at_utc",
        "google_linked_at_utc", "google_email", "is_virtual", "virtual_preset",
        "ux_mode",
    )}
    out["profile_complete"] = _profile_complete(user)
    out["google_linked"] = bool(str(user.get("google_sub") or "").strip())
    # needs_google = informational for NT actions only; never a login blocker.
    out["needs_google"] = user_needs_google(user)
    out["dual_auth_complete"] = True  # login is Telegram-only
    out["nt_google_required"] = bool(user_needs_google(user))
    mode = effective_ux_mode(user)
    out["ux_mode"] = mode
    out["needs_ux_mode"] = needs_ux_mode_choice(user)
    out["has_avatar"] = bool(user.get("avatar_ext"))
    out["avatar_updated_at_utc"] = str(user.get("avatar_updated_at_utc") or "")
    if out["has_avatar"]:
        try:
            uid = int(user.get("user_id") or 0)
        except (TypeError, ValueError):
            uid = 0
        version = re.sub(r"[^0-9]", "", out["avatar_updated_at_utc"]) or "1"
        out["avatar_url"] = f"/api/auth/avatar/{uid}?v={version}"
    else:
        out["avatar_url"] = ""
    out["features"] = effective_features(user)
    if not user.get("is_owner"):
        overrides = user.get("feature_overrides") if isinstance(user.get("feature_overrides"), dict) else {}
        out["feature_overrides"] = {key: bool(value) for key, value in overrides.items() if key in FEATURES}
        perm_ov = user.get("permission_overrides") if isinstance(user.get("permission_overrides"), dict) else {}
        out["permission_overrides"] = {key: bool(value) for key, value in perm_ov.items() if isinstance(value, bool)}
        from . import permissions  # lazy import avoids a load-time dependency cycle
        admin_grants = user.get("admin_permission_grants")
        admin_grants = admin_grants if isinstance(admin_grants, dict) else {}
        out["admin_permission_grants"] = {
            key: {
                "enabled": bool(value.get("enabled")),
                "granted_at_utc": str(value.get("granted_at_utc") or ""),
                "expires_at_utc": str(value.get("expires_at_utc") or ""),
            }
            for key, value in admin_grants.items()
            if key in permissions.ADMIN_CAPABILITY_IDS and isinstance(value, dict)
        }
    if include_contact:
        out["email"] = str(user.get("email") or "")
        phone = str(user.get("phone") or "")
        out["phone_mask"] = ("+•••" + phone[-4:]) if phone else ""
        devices = user.get("devices") if isinstance(user.get("devices"), list) else []
        out["devices"] = [dict(row) for row in reversed(devices[-20:]) if isinstance(row, dict)]
        out["device_count"] = len(devices)
        # Never expose raw google_sub to non-owner clients in lists; ok in own profile.
        out["google_sub_suffix"] = str(user.get("google_sub") or "")[-8:]
    if include_avatar:
        out["avatar_data_url"] = _avatar_data_url(user)
    return out


def refresh_avatar(user_id: Any, *, fetcher: Callable[[int], Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    """Best-effort refresh of a user's avatar from a fetcher callable.

    ``fetcher(user_id)`` returns ``{"bytes", "ext", "file_unique_id"}`` or None.
    Never raises; a missing photo is a normal, expected outcome.
    """
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        return {"ok": False, "reason": "no_user"}
    with _LOCK:
        doc = _read_doc()
        user = _user(doc, uid)
        current_unique = str((user or {}).get("avatar_file_unique_id") or "")
    if user is None:
        return {"ok": False, "reason": "not_found"}
    try:
        result = fetcher(uid)
    except Exception:
        result = None
    if not result or not result.get("bytes"):
        return {"ok": False, "reason": "no_photo"}
    file_unique_id = str(result.get("file_unique_id") or "")
    ext = str(result.get("ext") or "jpg").lower()
    if ext not in ("jpg", "png", "webp"):
        ext = "jpg"
    directory = _avatars_dir()
    existing = directory / f"{uid}.{ext}"
    if file_unique_id and file_unique_id == current_unique and existing.is_file():
        with _LOCK:
            doc = _read_doc()
            snap = _user(doc, uid)
        return {"ok": True, "unchanged": True, "user": _public_user(snap or {}, include_contact=True, include_avatar=True)}
    for stale in directory.glob(f"{uid}.*"):
        try:
            stale.unlink()
        except OSError:
            pass
    try:
        existing.write_bytes(bytes(result["bytes"]))
    except OSError:
        return {"ok": False, "reason": "write_failed"}
    with _LOCK:
        doc = _read_doc()
        user = _user(doc, uid)
        if user is None:
            return {"ok": False, "reason": "not_found"}
        user["avatar_ext"] = ext
        user["avatar_file_unique_id"] = file_unique_id
        user["avatar_updated_at_utc"] = _now_iso()
        _write_doc(doc)
        snapshot = dict(user)
    _audit("avatar_refreshed", user_id=uid)
    return {"ok": True, "user": _public_user(snapshot, include_contact=True, include_avatar=True)}


def set_user_feature(owner_id: Any, user_id: Any, feature: str, enabled: bool) -> Dict[str, Any]:
    fid = str(feature or "")
    if fid not in FEATURES:
        raise AccountAuthError("Неизвестный параметр.")
    uid = int(user_id)
    with _LOCK:
        doc = _read_doc()
        try:
            _require_owner_in_doc(doc, owner_id)
        except AccountAuthError:
            raise AccountAuthError("Только владелец может управлять параметрами.", 403) from None
        user = _user(doc, uid)
        if user is None:
            raise AccountAuthError("Пользователь не найден.", 404)
        if user.get("is_owner"):
            raise AccountAuthError("У владельца все параметры включены.", 400)
        overrides = user.get("feature_overrides") if isinstance(user.get("feature_overrides"), dict) else {}
        overrides[fid] = bool(enabled)
        user["feature_overrides"] = overrides
        user["updated_at_utc"] = _now_iso()
        _write_doc(doc)
    _audit("user_feature_changed", owner_id=int(owner_id), user_id=uid)
    return list_users(owner_id)


def set_user_permission(owner_id: Any, user_id: Any, capability: str, enabled: Any) -> Dict[str, Any]:
    """Owner grant/revoke of a single subscription capability for one user.

    ``enabled`` may be True/False to override, or None to clear the override and
    fall back to the user's plan. Capability ids are validated against the
    central permission catalog.
    """
    from . import permissions  # lazy import avoids a load-time dependency cycle
    cap = str(capability or "")
    if cap not in permissions.CAPABILITY_IDS:
        raise AccountAuthError("Неизвестная привилегия.")
    uid = int(user_id)
    with _LOCK:
        doc = _read_doc()
        try:
            _require_owner_in_doc(doc, owner_id)
        except AccountAuthError:
            raise AccountAuthError("Только владелец может управлять разрешениями.", 403) from None
        user = _user(doc, uid)
        if user is None:
            raise AccountAuthError("Пользователь не найден.", 404)
        if user.get("is_owner"):
            raise AccountAuthError("У владельца все разрешения включены.", 400)
        overrides = user.get("permission_overrides") if isinstance(user.get("permission_overrides"), dict) else {}
        if enabled is None:
            overrides.pop(cap, None)
        else:
            overrides[cap] = bool(enabled)
        user["permission_overrides"] = overrides
        user["updated_at_utc"] = _now_iso()
        _write_doc(doc)
    _audit("user_permission_changed", owner_id=int(owner_id), user_id=uid)
    return list_users(owner_id)


def set_user_admin_permission(
    owner_id: Any,
    user_id: Any,
    capability: str,
    enabled: Any,
    *,
    expires_at_utc: Any = "",
) -> Dict[str, Any]:
    """Owner-only grant/revoke of a control-plane capability.

    Administrative access never comes from a subscription.  A grant may be
    permanent (empty expiry) or expire at a timezone-aware UTC instant.
    """
    from . import permissions  # lazy import avoids a load-time dependency cycle
    cap = str(capability or "")
    if cap not in permissions.ADMIN_CAPABILITY_IDS:
        raise AccountAuthError("Неизвестное административное разрешение.")
    if not isinstance(enabled, bool):
        raise AccountAuthError("Поле enabled должно быть boolean.")
    uid = int(user_id)
    expiry = _normalized_future_utc(expires_at_utc) if enabled else ""
    with _LOCK:
        doc = _read_doc()
        try:
            _require_owner_in_doc(doc, owner_id)
        except AccountAuthError:
            raise AccountAuthError(
                "Только владелец может выдавать административные разрешения.", 403,
            ) from None
        user = _user(doc, uid)
        if user is None:
            raise AccountAuthError("Пользователь не найден.", 404)
        if user.get("is_owner"):
            raise AccountAuthError("У владельца все административные разрешения включены.")
        grants = user.get("admin_permission_grants")
        grants = grants if isinstance(grants, dict) else {}
        if enabled:
            grants[cap] = {
                "enabled": True,
                "granted_at_utc": _now_iso(),
                "expires_at_utc": expiry,
                "granted_by": str(owner_id),
            }
        else:
            grants.pop(cap, None)
        user["admin_permission_grants"] = grants
        user["updated_at_utc"] = _now_iso()
        _write_doc(doc)
    _audit(
        "user_admin_permission_changed",
        owner_id=int(owner_id),
        user_id=uid,
        extra={
            "capability": cap,
            "enabled": bool(enabled),
            "expires_at_utc": expiry,
        },
    )
    return list_users(owner_id)


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
        return _public_user(existing, include_contact=True, include_avatar=True)


def find_active_user(user_id: Any) -> Optional[Dict[str, Any]]:
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    with _LOCK:
        doc = _read_doc_reference()
        user = _user(doc, uid)
        if not user or user.get("status") != "active":
            return None
        # The configured owner is always active. Their identity is anchored to
        # NTA_TELEGRAM_CHAT_ID via ensure_owner, so they must never be locked out
        # of their own app just because a profile field is blank.
        if user.get("is_owner") or _profile_complete(user):
            return copy.deepcopy(user)
        return None


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


def _require_admin_capability_in_doc(
    doc: Dict[str, Any], actor_id: Any, capability: str,
) -> Dict[str, Any]:
    """Require an active owner or an active explicitly-granted staff actor."""
    try:
        uid = int(actor_id or 0)
    except (TypeError, ValueError):
        uid = 0
    actor = _user(doc, uid) if uid else None
    if not actor or actor.get("status") != "active":
        raise AccountAuthError("Администратор не авторизован.", 403)
    if actor.get("is_owner"):
        return _require_owner_in_doc(doc, uid)
    from . import permissions  # lazy import avoids a load-time dependency cycle
    if not permissions.resolve_admin_capabilities(actor).get(str(capability or "")):
        raise AccountAuthError("Административное разрешение не выдано или истекло.", 403)
    return actor


def list_users(owner_id: Any) -> Dict[str, Any]:
    with _LOCK:
        doc = _read_doc()
        _require_admin_capability_in_doc(doc, owner_id, "users.manage")
        users = sorted(doc["users"], key=lambda row: (not bool(row.get("is_owner")), str(row.get("created_at_utc") or "")))
        return {
            "users": [_public_user(row, include_contact=True, include_avatar=True) for row in users],
            "feature_catalog": feature_catalog(),
            "storage": storage_status(),
        }


def update_user(owner_id: Any, user_id: Any, *, role: str = "", revoke: bool = False) -> Dict[str, Any]:
    uid = int(user_id)
    with _LOCK:
        doc = _read_doc()
        try:
            _require_admin_capability_in_doc(doc, owner_id, "users.manage")
        except AccountAuthError:
            raise AccountAuthError("Нет разрешения управлять пользователями.", 403) from None
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


def record_login(user_id: Any, *, source: str, ip: str = "", user_agent: str = "",
                 throttle_sec: int = 0) -> None:
    """Best-effort login-history record. ``throttle_sec`` skips writing a new row
    (and any DPAPI write) when the same source logged in recently — used for the
    Mini App which re-checks auth on every navigation."""
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        return
    if uid <= 0:
        return
    try:
        with _LOCK:
            doc = _read_doc()
            user = _user(doc, uid)
            if user is None:
                return
            if throttle_sec > 0:
                history = user.get("login_history") if isinstance(user.get("login_history"), list) else []
                last = next((row for row in reversed(history) if row.get("source") == source), None)
                if last:
                    try:
                        last_ts = datetime.fromisoformat(str(last.get("at")).replace("Z", "+00:00")).timestamp()
                    except ValueError:
                        last_ts = 0.0
                    if last_ts and (time.time() - last_ts) < throttle_sec:
                        return
            _append_login(user, source=source, ip=ip, user_agent=user_agent)
            _write_doc(doc)
    except AccountAuthError:
        return


def set_user_status(owner_id: Any, user_id: Any, status: str) -> Dict[str, Any]:
    """Owner block/unblock. ``blocked`` temporarily suspends access and revokes
    live sessions; ``active`` restores it. The account row is preserved."""
    new_status = str(status or "")
    if new_status not in {"active", "blocked"}:
        raise AccountAuthError("Недопустимый статус.")
    uid = int(user_id)
    with _LOCK:
        doc = _read_doc()
        try:
            _require_admin_capability_in_doc(doc, owner_id, "users.manage")
        except AccountAuthError:
            raise AccountAuthError("Нет разрешения управлять пользователями.", 403) from None
        user = _user(doc, uid)
        if user is None:
            raise AccountAuthError("Пользователь не найден.", 404)
        if user.get("is_owner"):
            raise AccountAuthError("Аккаунт владельца нельзя заблокировать.", 403)
        if not _profile_complete(user) and new_status == "active":
            raise AccountAuthError("Профиль не заполнен — активировать нельзя.", 400)
        user["status"] = new_status
        user["updated_at_utc"] = _now_iso()
        if new_status == "blocked":
            user["blocked_at_utc"] = _now_iso()
            for session in doc["sessions"]:
                if int(session.get("user_id") or 0) == uid:
                    session["revoked"] = True
        else:
            user["blocked_at_utc"] = ""
        _write_doc(doc)
    _audit("user_blocked" if new_status == "blocked" else "user_unblocked", owner_id=int(owner_id), user_id=uid)
    return list_users(owner_id)


def delete_user(owner_id: Any, user_id: Any) -> Dict[str, Any]:
    """Permanently remove a user, their sessions, challenges and avatar files."""
    uid = int(user_id)
    with _LOCK:
        doc = _read_doc()
        try:
            _require_admin_capability_in_doc(doc, owner_id, "users.manage")
        except AccountAuthError:
            raise AccountAuthError("Нет разрешения удалять пользователей.", 403) from None
        user = _user(doc, uid)
        if user is None:
            raise AccountAuthError("Пользователь не найден.", 404)
        if user.get("is_owner"):
            raise AccountAuthError("Аккаунт владельца нельзя удалить.", 403)
        doc["users"] = [row for row in doc["users"] if int(row.get("user_id") or 0) != uid]
        doc["sessions"] = [row for row in doc["sessions"] if int(row.get("user_id") or 0) != uid]
        doc["challenges"] = [row for row in doc["challenges"] if int(row.get("user_id") or 0) != uid]
        _write_doc(doc)
    for stale in _avatars_dir().glob(f"{uid}.*"):
        try:
            stale.unlink()
        except OSError:
            pass
    _audit("user_deleted", owner_id=int(owner_id), user_id=uid)
    return list_users(owner_id)


def user_detail(owner_id: Any, user_id: Any) -> Dict[str, Any]:
    """Full admin view of one user, including login history."""
    uid = int(user_id)
    with _LOCK:
        doc = _read_doc()
        _require_admin_capability_in_doc(doc, owner_id, "users.manage")
        user = _user(doc, uid)
        if user is None:
            raise AccountAuthError("Пользователь не найден.", 404)
        pub = _public_user(user, include_contact=True, include_avatar=True)
        history = user.get("login_history") if isinstance(user.get("login_history"), list) else []
        pub["login_history"] = list(reversed(history))[:20]
        pub["blocked_at_utc"] = str(user.get("blocked_at_utc") or "")
        pub["active_sessions"] = _public_sessions(doc, uid)
    return {"user": pub, "feature_catalog": feature_catalog(), "storage": storage_status()}


def _session_id(session: Dict[str, Any]) -> str:
    sid = str(session.get("session_id") or "").strip()
    if sid:
        return sid
    digest = str(session.get("token_hash") or "")
    return hashlib.sha256(digest.encode()).hexdigest()[:16] if digest else ""


def _public_sessions(doc: Dict[str, Any], user_id: int) -> list[Dict[str, Any]]:
    now = time.time()
    out = []
    for row in doc.get("sessions") or []:
        if int(row.get("user_id") or 0) != int(user_id):
            continue
        if row.get("revoked") or float(row.get("expires_at") or 0) <= now:
            continue
        out.append({
            "session_id": _session_id(row),
            "device_id": str(row.get("device_id") or ""),
            "created_at_utc": str(row.get("created_at_utc") or ""),
            "expires_at": float(row.get("expires_at") or 0),
            "client": str(row.get("client") or ""),
            "machine": str(row.get("machine") or ""),
            "ip": str(row.get("ip") or ""),
        })
    out.sort(key=lambda item: str(item.get("created_at_utc") or ""), reverse=True)
    return out[:50]


def revoke_user_sessions(owner_id: Any, user_id: Any, *, session_id: str = "",
                         device_id: str = "", all_sessions: bool = False) -> Dict[str, Any]:
    uid = int(user_id)
    target_session = str(session_id or "").strip()
    target_device = str(device_id or "").strip()
    if not (target_session or target_device or all_sessions):
        raise AccountAuthError("Укажите session_id, device_id или all_sessions=true.")
    with _LOCK:
        doc = _read_doc()
        try:
            _require_admin_capability_in_doc(doc, owner_id, "users.manage")
        except AccountAuthError:
            raise AccountAuthError("Нет разрешения отзывать сессии.", 403) from None
        user = _user(doc, uid)
        if user is None:
            raise AccountAuthError("Пользователь не найден.", 404)
        revoked = 0
        for session in doc["sessions"]:
            if int(session.get("user_id") or 0) != uid:
                continue
            if all_sessions:
                matched = True
            elif target_session:
                matched = hmac.compare_digest(_session_id(session), target_session)
            else:
                matched = hmac.compare_digest(str(session.get("device_id") or ""), target_device)
            if matched and not session.get("revoked"):
                session["revoked"] = True
                session["revoked_at_utc"] = _now_iso()
                session["revoked_reason"] = "admin"
                session["revoked_by_owner_id"] = int(owner_id)
                # Keep notice TTL so the client can show «Сессия завершена администратором».
                session["revoke_notice_until"] = time.time() + ADMIN_REVOKE_NOTICE_TTL_SEC
                revoked += 1
        _write_doc(doc)
        sessions = _public_sessions(doc, uid)
    _audit("session_revoked", owner_id=int(owner_id), user_id=uid)
    return {"ok": True, "revoked": revoked, "sessions": sessions}


def _cleanup(doc: Dict[str, Any]) -> None:
    now = time.time()
    doc["challenges"] = [row for row in doc["challenges"] if float(row.get("expires_at") or 0) > now][-100:]
    kept_sessions = []
    for row in doc.get("sessions") or []:
        expires = float(row.get("expires_at") or 0)
        if expires > now and not row.get("revoked"):
            kept_sessions.append(row)
            continue
        # Retain admin-revoked rows briefly so /api/auth/status can return a clear code.
        notice_until = float(row.get("revoke_notice_until") or 0)
        if row.get("revoked") and row.get("revoked_reason") == "admin" and notice_until > now:
            kept_sessions.append(row)
    doc["sessions"] = kept_sessions[-200:]


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
        "code": code,
        "manual_command": f"/login {code}",
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
                     api_call: Callable[..., Any], owner_chat_id: str,
                     ip: str = "", user_agent: str = "") -> Dict[str, Any]:
    first_name = _clean_name(profile.get("first_name"), "Имя")
    last_name = _clean_name(profile.get("last_name"), "Фамилия")
    email = _valid_email(profile.get("email"))
    if not bool(profile.get("accept_terms")):
        raise AccountAuthError("Необходимо принять условия использования.")
    with _LOCK:
        doc = _read_doc()
        challenge = _challenge(doc, challenge_id=str(challenge_id or ""), statuses=("awaiting_profile",))
        if challenge is None:
            raise AccountAuthError("Профиль уже обработан или запрос истёк.", 409)
        user = _user(doc, int(challenge.get("user_id") or 0))
        if user is None:
            raise AccountAuthError("Telegram identity не найдена.", 409)
        prior_status = str(user.get("status") or "")
        previous_email = str(user.get("email") or "").strip().lower()
        user.update({
            "first_name": first_name,
            "last_name": last_name,
            "email": previous_email or email,
            "updated_at_utc": _now_iso(),
        })
        if previous_email and previous_email != email:
            user["last_submitted_email"] = email
            user["last_submitted_email_at_utc"] = _now_iso()
        _upsert_device(user, source="profile_completed", ip=ip,
                       user_agent=user_agent, email=email)
        user["terms_accepted_at_utc"] = _now_iso()
        user["terms_version"] = legal.TERMS_VERSION
        if user.get("status") in {"revoked", "denied", "blocked"}:
            # Owner explicitly removed access — completing the profile again does
            # not restore it.
            challenge["status"] = "account_blocked"
        elif user.get("is_owner") or str(user.get("user_id") or "") == str(owner_chat_id or ""):
            user["status"] = "active"
            if not user.get("approved_at_utc"):
                user["approved_at_utc"] = _now_iso()
            challenge["status"] = "login_approved"
        else:
            # New accounts wait for the owner's personal confirmation after
            # Telegram + profile. Free Preview opens only after allow.
            user["status"] = "pending"
            challenge["status"] = "pending_owner"
            challenge["expires_at"] = time.time() + OWNER_APPROVAL_TTL_SEC
        _write_doc(doc)
        activated = challenge["status"] == "login_approved"
        awaiting_owner = challenge["status"] == "pending_owner"
        newly = activated and prior_status != "active"
        snapshot = dict(user)
        cid = str(challenge.get("challenge_id") or "")
    if activated:
        if newly and not snapshot.get("is_owner"):
            _notify_owner_new_user(api_call, owner_chat_id, snapshot)
        api_call("sendMessage", {"chat_id": int(snapshot["user_id"]), "text": "Профиль заполнен. Открыт ознакомительный доступ — вернитесь в приложение."})
    elif awaiting_owner:
        _send_owner_approval(api_call, owner_chat_id, snapshot, cid)
        api_call("sendMessage", {"chat_id": int(snapshot["user_id"]), "text": "Профиль заполнен. Ожидайте личного подтверждения владельца — мы сообщим, когда доступ откроется."})
    else:
        api_call("sendMessage", {"chat_id": int(snapshot["user_id"]), "text": "Доступ к StratForge AI ограничен владельцем."})
    return login_state(challenge_id)


def _notify_owner_new_user(api_call: Callable[..., Any], owner_chat_id: str,
                           user: Dict[str, Any]) -> None:
    label = html.escape(f"{user.get('first_name', '')} {user.get('last_name', '')}".strip())
    uid = int(user.get("user_id") or 0)
    api_call("sendMessage", {
        "chat_id": owner_chat_id, "parse_mode": "HTML",
        "text": (
            "🆕 <b>Новый пользователь StratForge AI</b>\n"
            f"<b>{label}</b> · id <code>{uid}</code> · @{html.escape(str(user.get('username') or '—'))}\n"
            f"E-mail: <code>{html.escape(str(user.get('email') or ''))}</code>\n"
            "Открыт ознакомительный доступ (Free Preview). Управляйте доступом и тарифом в кабинете."
        ),
        "reply_markup": {"inline_keyboard": [[
            {"text": "⛔ Заблокировать", "callback_data": f"account_revoke:{uid}"},
        ]]},
    })


def register_via_telegram(tg_user: Dict[str, Any], *, email: str = "",
                          first_name: str = "", last_name: str = "",
                          accept_terms: bool = False,
                          api_call: Optional[Callable[..., Any]] = None,
                          owner_chat_id: str = "") -> Dict[str, Any]:
    """Register from a verified Telegram Mini App identity (initData).

    New non-owner accounts stay ``pending`` until the owner confirms. Returning
    active users keep their access. The caller MUST have validated initData.
    """
    try:
        uid = int(tg_user.get("id") or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise AccountAuthError("Некорректная Telegram identity.", 400)
    if not accept_terms:
        raise AccountAuthError("Необходимо принять условия использования.")
    owner_env = str(owner_chat_id or os.environ.get("NTA_TELEGRAM_CHAT_ID") or "").strip()
    is_owner = bool(owner_env) and str(uid) == owner_env
    fn = _clean_name(first_name or tg_user.get("first_name") or "—", "Имя")
    ln = _clean_name(last_name or tg_user.get("last_name") or "—", "Фамилия")
    em = _valid_email(email)
    now = _now_iso()
    challenge_id = ""
    with _LOCK:
        doc = _read_doc()
        user = _user(doc, uid)
        prior_status = str((user or {}).get("status") or "")
        if user and not is_owner and user.get("status") in {"revoked", "denied", "blocked"}:
            raise AccountAuthError("Доступ к StratForge AI ограничен владельцем.", 403)
        if user is None:
            user = {
                "user_id": uid, "username": str(tg_user.get("username") or ""),
                "first_name": fn, "last_name": ln, "email": em,
                "phone": "", "phone_hash": "",
                "role": "owner" if is_owner else "read_only",
                "status": "active" if is_owner else "pending", "is_owner": is_owner,
                "created_at_utc": now,
                "approved_at_utc": now if is_owner else "",
                "revoked_at_utc": "",
            }
            doc["users"].append(user)
        else:
            previous_email = str(user.get("email") or "").strip().lower()
            user.update({
                "username": str(tg_user.get("username") or user.get("username") or ""),
                "first_name": fn, "last_name": ln, "email": previous_email or em,
                "updated_at_utc": now,
            })
            if previous_email and previous_email != em:
                user["last_submitted_email"] = em
                user["last_submitted_email_at_utc"] = now
            if is_owner:
                user.update({"role": "owner", "is_owner": True, "status": "active",
                             "approved_at_utc": user.get("approved_at_utc") or now})
            elif user.get("status") == "active":
                pass  # returning active user — keep access
            else:
                user["status"] = "pending"
        user["terms_accepted_at_utc"] = now
        user["terms_version"] = legal.TERMS_VERSION
        user["identity_verified_via"] = "mini_app_initdata"
        _append_login(user, source="telegram_mini_app", user_agent="Telegram Mini App", email=em)

        status_out = "active" if user.get("status") == "active" else "pending_owner"
        if status_out == "pending_owner":
            challenge_id = secrets.token_urlsafe(24)
            doc["challenges"].append({
                "challenge_id": challenge_id, "code": "", "status": "pending_owner",
                "user_id": uid, "created_at_utc": now,
                "expires_at": time.time() + OWNER_APPROVAL_TTL_SEC,
                "source": "mini_app_register",
            })
        _write_doc(doc)
        snapshot = dict(user)
    if status_out == "pending_owner" and api_call is not None:
        try:
            _send_owner_approval(api_call, owner_env, snapshot, challenge_id)
        except Exception:  # noqa: BLE001 — notification is best-effort
            pass
    elif prior_status != "active" and snapshot.get("status") == "active" and not is_owner and api_call is not None:
        try:
            _notify_owner_new_user(api_call, owner_env, snapshot)
        except Exception:  # noqa: BLE001
            pass
    _audit("miniapp_registered", user_id=uid)
    return {
        "ok": True,
        "authenticated": status_out == "active",
        "status": status_out,
        "challenge_id": challenge_id,
        "user": _public_user(snapshot, include_contact=True, include_avatar=True),
    }


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


def _claim_login_challenge(doc: Dict[str, Any], *, code: str, uid: int,
                           sender: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    challenge = _challenge(doc, code=code, statuses=("created",))
    if challenge is None:
        return None
    challenge.update({"user_id": uid, "status": "awaiting_contact", "telegram_started_at_utc": _now_iso()})
    challenge["telegram_user"] = {
        "username": str(sender.get("username") or ""),
        "first_name": str(sender.get("first_name") or ""),
        "last_name": str(sender.get("last_name") or ""),
    }
    return challenge


def _send_contact_request(api_call: Callable[..., Any], uid: int) -> None:
    api_call("sendMessage", {
        "chat_id": uid,
        "text": "Подтвердите личность: отправьте свой Telegram-контакт кнопкой ниже. Чужой или введённый вручную номер не принимается.",
        "reply_markup": {"keyboard": [[{"text": "📱 Подтвердить мой номер", "request_contact": True}]], "resize_keyboard": True, "one_time_keyboard": True},
    })


def process_update(update: Dict[str, Any], *, api_call: Callable[..., Any], owner_chat_id: str) -> bool:
    callback = update.get("callback_query") if isinstance(update, dict) else None
    if isinstance(callback, dict):
        nt_match = re.fullmatch(r"nt_(confirm|deny):([A-Za-z0-9_-]{20,})", str(callback.get("data") or ""))
        if nt_match:
            actor = int((callback.get("from") or {}).get("id") or 0)
            allowed = nt_match.group(1) == "confirm"
            with _LOCK:
                doc = _read_doc()
                result, uid = _apply_nt_confirm_callback(
                    doc, challenge_id=nt_match.group(2), allowed=allowed, actor_id=actor,
                )
                if result in {"confirmed", "denied"}:
                    _write_doc(doc)
            if result == "forbidden":
                api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "Подтверждать может только владелец этого аккаунта.", "show_alert": True})
                return True
            if result == "expired":
                api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "Запрос истёк или уже обработан.", "show_alert": True})
                return True
            api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "Подтверждено." if allowed else "Отклонено."})
            if uid:
                api_call("sendMessage", {
                    "chat_id": uid,
                    "text": (
                        "✅ Управление NinjaTrader подтверждено на 30 минут. Вернитесь в приложение."
                        if allowed else
                        "⛔ Запрос на управление NinjaTrader отклонён."
                    ),
                })
                _audit("nt_confirm_ok" if allowed else "nt_confirm_denied", user_id=uid)
            return True
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
    manual_login = re.fullmatch(r"/(?:login|code)(?:@[A-Za-z0-9_]+)?\s+(?:login_)?([A-Fa-f0-9]{8})", text, flags=re.IGNORECASE)
    if start or manual_login:
        code = (start or manual_login).group(1)
        with _LOCK:
            doc = _read_doc()
            challenge = _claim_login_challenge(doc, code=code, uid=uid, sender=sender)
            if challenge is None:
                api_call("sendMessage", {"chat_id": uid, "text": "Ссылка входа истекла или уже использована."})
                return True
            _write_doc(doc)
        _send_contact_request(api_call, uid)
        return True

    if re.fullmatch(r"/start(?:@[A-Za-z0-9_]+)?", text, flags=re.IGNORECASE):
        api_call("sendMessage", {
            "chat_id": uid,
            "text": (
                "Для входа нужна одноразовая ссылка из окна StratForge AI. "
                "Если браузер открыл Telegram без кода, вернитесь в приложение, нажмите "
                "«Начать заново» и введите здесь ручную команду вида /login ABCD1234."
            ),
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
            prior_status = str(user.get("status") or "")
            if user.get("status") in {"revoked", "denied", "blocked"}:
                # Owner explicitly removed access — re-verification does not restore it.
                challenge["status"] = "account_blocked"
            elif _profile_complete(user):
                # Telegram-verified users enter immediately in Free Preview.
                user["status"] = "active"
                if not user.get("approved_at_utc"):
                    user["approved_at_utc"] = _now_iso()
                challenge["status"] = "login_approved"
            else:
                user["status"] = "pending"
                challenge["status"] = "awaiting_profile"
            _write_doc(doc)
            next_status = challenge["status"]
            cid = str(challenge["challenge_id"])
            newly_activated = next_status == "login_approved" and prior_status != "active"
            snapshot = dict(user)
        if newly_activated and not snapshot.get("is_owner"):
            _notify_owner_new_user(api_call, owner_chat_id, snapshot)
        messages = {
            "awaiting_profile": "Телефон подтверждён. Вернитесь в приложение и заполните обязательные поля профиля.",
            "login_approved": "Личность подтверждена. Вернитесь в приложение — открыт ознакомительный доступ (Free Preview).",
            "account_blocked": "Доступ к StratForge AI ограничен владельцем.",
        }
        api_call("sendMessage", {"chat_id": uid, "text": messages.get(next_status, "Готово."), "reply_markup": {"remove_keyboard": True}})
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
            "session_id": "sess_" + secrets.token_hex(8),
            "token_hash": hashlib.sha256(token.encode()).hexdigest(), "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(),
            "csrf_token": csrf,
            "user_id": uid, "created_at_utc": _now_iso(), "expires_at": now + SESSION_TTL_SEC,
            "ip_hash": hashlib.sha256(str(ip or "").encode()).hexdigest(),
            "ua_hash": hashlib.sha256(str(user_agent or "").encode()).hexdigest(), "revoked": False,
            "device_id": _device_id(user_agent), "client": _device_label(user_agent),
            "machine": _machine_label(), "ip": _mask_ip(ip),
        })
        challenge["status"] = "consumed"
        _append_login(user, source="desktop_session", ip=ip, user_agent=user_agent)
        _cleanup(doc)
        _write_doc(doc)
    _audit("login_succeeded", user_id=uid, ip=ip)
    return {"status": "authenticated", "session_token": token, "csrf_token": csrf, "user": _public_user(user, include_contact=True, include_avatar=True)}


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
        ctx = {
            "source": str(session.get("source") or "desktop_session"),
            "user_id": int(user["user_id"]),
            "role": str(user.get("role") or "read_only"),
            "is_owner": bool(user.get("is_owner")),
            "username": str(user.get("username") or ""),
            "session_id": _session_id(session),
            "device_id": str(session.get("device_id") or ""),
            "csrf_hash": str(session.get("csrf_hash") or ""),
            "csrf_token": str(session.get("csrf_token") or ""),
            "user": _public_user(user, include_contact=True, include_avatar=True),
            "needs_google": user_needs_google(user),
            "dual_auth_complete": True,
            "nt_elevated_until": float(session.get("nt_elevated_until") or 0),
        }
        ctx["nt_access"] = nt_action_gate(user, session=session, context=ctx)
        if session.get("impersonator_owner_id"):
            ctx["impersonating"] = True
            ctx["impersonator_owner_id"] = int(session.get("impersonator_owner_id") or 0)
            ctx["impersonation_started_at_utc"] = str(session.get("impersonation_started_at_utc") or "")
            ctx["impersonation_preset"] = str(session.get("impersonation_preset") or "")
        return ctx


def start_nt_telegram_confirm(
    user_id: Any,
    *,
    session_id: str = "",
    api_call: Optional[Callable[..., Any]] = None,
    purpose: str = "ninjatrader",
) -> Dict[str, Any]:
    """Send Telegram buttons asking the user to re-confirm NT control actions."""
    uid = int(user_id or 0)
    if uid <= 0:
        raise AccountAuthError("Требуется вход.", 401)
    with _LOCK:
        doc = _read_doc()
        user = _user(doc, uid)
        if not user or user.get("status") != "active":
            raise AccountAuthError("Аккаунт не активен.", 403)
        if dual_auth_enforced() and not google_linked(user) and not user.get("is_owner"):
            raise AccountAuthError(
                "Сначала подключите Google-аккаунт, затем подтвердите действие в Telegram.",
                403, code="nt_google_required",
            )
        sid = str(session_id or "").strip()
        if not user.get("is_owner"):
            session = next((
                row for row in doc["sessions"]
                if _session_id(row) == sid
                and int(row.get("user_id") or 0) == uid
                and not row.get("revoked")
                and float(row.get("expires_at") or 0) > time.time()
            ), None)
            if not sid or session is None:
                raise AccountAuthError(
                    "Для Telegram-подтверждения нужна активная сессия этого устройства.",
                    409, code="nt_session_required",
                )
        challenge_id = secrets.token_urlsafe(24)
        doc["challenges"].append({
            "challenge_id": challenge_id,
            "code": "",
            "status": "nt_confirm_pending",
            "kind": "nt_step_up",
            "purpose": str(purpose or "ninjatrader")[:40],
            "user_id": uid,
            "session_id": sid[:80],
            "created_at_utc": _now_iso(),
            "expires_at": time.time() + NT_CONFIRM_TTL_SEC,
        })
        _cleanup(doc)
        _write_doc(doc)
        public = _public_user(user)
    if api_call is not None and not public.get("is_owner"):
        try:
            api_call("sendMessage", {
                "chat_id": uid,
                "text": (
                    "🔐 <b>Подтверждение NinjaTrader</b>\n"
                    "Запрошен доступ к управлению NinjaTrader в StratForge.\n"
                    "Если это вы — подтвердите. Если нет — отклоните."
                ),
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": [[
                    {"text": "✅ Подтвердить", "callback_data": f"nt_confirm:{challenge_id}"},
                    {"text": "⛔ Отклонить", "callback_data": f"nt_deny:{challenge_id}"},
                ]]},
            })
        except Exception:
            pass
    _audit("nt_confirm_started", user_id=uid, extra={"challenge_id": challenge_id, "purpose": purpose})
    return {
        "ok": True,
        "challenge_id": challenge_id,
        "status": "nt_confirm_pending",
        "expires_in_sec": NT_CONFIRM_TTL_SEC,
        "message": "Подтвердите действие в Telegram.",
    }


def nt_confirm_status(challenge_id: str, *, user_id: Any = 0) -> Dict[str, Any]:
    with _LOCK:
        doc = _read_doc()
        challenge = _challenge(doc, challenge_id=str(challenge_id or ""))
        if challenge is None:
            return {"ok": False, "status": "expired", "message": "Запрос истёк."}
        if int(user_id or 0) and int(challenge.get("user_id") or 0) != int(user_id):
            raise AccountAuthError("Чужой запрос подтверждения.", 403)
        status = str(challenge.get("status") or "")
        out = {
            "ok": True,
            "challenge_id": challenge.get("challenge_id"),
            "status": status,
            "purpose": challenge.get("purpose") or "ninjatrader",
        }
        if status == "nt_confirmed":
            out["nt_elevated_until"] = float(challenge.get("nt_elevated_until") or 0)
            out["ready"] = True
        return out


def elevate_session_for_nt(session_id: str, *, user_id: Any, ttl_sec: int = 0) -> Dict[str, Any]:
    sid = str(session_id or "").strip()
    uid = int(user_id or 0)
    ttl = int(ttl_sec) if int(ttl_sec or 0) > 0 else NT_STEP_UP_TTL_SEC
    with _LOCK:
        doc = _read_doc()
        session = next((row for row in doc["sessions"] if _session_id(row) == sid and not row.get("revoked")), None)
        if session is None or int(session.get("user_id") or 0) != uid:
            raise AccountAuthError("Сессия не найдена.", 404)
        until = time.time() + ttl
        session["nt_elevated_until"] = until
        session["nt_elevated_at_utc"] = _now_iso()
        _write_doc(doc)
    return {"ok": True, "nt_elevated_until": until, "ttl_sec": ttl}


def grant_nt_elevation_staging(user_id: Any, *, session_id: str = "") -> Dict[str, Any]:
    """Staging helper: skip Telegram button and mark session elevated."""
    runtime_env.require_test_auth()
    uid = int(user_id or 0)
    with _LOCK:
        doc = _read_doc()
        sessions = [row for row in doc["sessions"] if int(row.get("user_id") or 0) == uid and not row.get("revoked")]
        if session_id:
            sessions = [row for row in sessions if _session_id(row) == str(session_id)]
        if not sessions:
            raise AccountAuthError("Нет активной сессии для elevation.", 404)
        until = time.time() + NT_STEP_UP_TTL_SEC
        for row in sessions:
            row["nt_elevated_until"] = until
            row["nt_elevated_at_utc"] = _now_iso()
        _write_doc(doc)
    return {"ok": True, "nt_elevated_until": until, "staging": True}


def _apply_nt_confirm_callback(doc: Dict[str, Any], *, challenge_id: str, allowed: bool, actor_id: int) -> Tuple[str, int]:
    challenge = _challenge(doc, challenge_id=challenge_id, statuses=("nt_confirm_pending",))
    if challenge is None:
        return "expired", 0
    uid = int(challenge.get("user_id") or 0)
    if actor_id != uid:
        return "forbidden", uid
    if not allowed:
        challenge["status"] = "nt_denied"
        return "denied", uid
    until = time.time() + NT_STEP_UP_TTL_SEC
    challenge["status"] = "nt_confirmed"
    challenge["nt_elevated_until"] = until
    challenge["confirmed_at_utc"] = _now_iso()
    sid = str(challenge.get("session_id") or "")
    if not sid:
        challenge["status"] = "nt_session_missing"
        return "session_missing", uid
    matched = False
    for row in doc["sessions"]:
        if int(row.get("user_id") or 0) != uid or row.get("revoked"):
            continue
        if _session_id(row) != sid:
            continue
        matched = True
        row["nt_elevated_until"] = until
        row["nt_elevated_at_utc"] = _now_iso()
    if not matched:
        challenge["status"] = "nt_session_missing"
        return "session_missing", uid
    return "confirmed", uid


def session_auth_failure(token: str) -> Optional[Dict[str, Any]]:
    """Explain why a cookie no longer authenticates (admin revoke, etc.)."""
    raw = str(token or "")
    if len(raw) < 40:
        return None
    digest = hashlib.sha256(raw.encode()).hexdigest()
    with _LOCK:
        doc = _read_doc()
        now = time.time()
        for row in doc.get("sessions") or []:
            if not hmac.compare_digest(str(row.get("token_hash") or ""), digest):
                continue
            if row.get("revoked") and row.get("revoked_reason") == "admin":
                notice_until = float(row.get("revoke_notice_until") or 0)
                if notice_until and notice_until < now:
                    return None
                return {
                    "code": "session_admin_revoked",
                    "error": "Сессия завершена администратором.",
                    "revoked_at_utc": str(row.get("revoked_at_utc") or ""),
                    "user_id": int(row.get("user_id") or 0),
                }
            return None
    return None


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
                session["revoked_at_utc"] = _now_iso()
                if not session.get("revoked_reason"):
                    session["revoked_reason"] = "logout"
                changed = True
        if changed:
            _write_doc(doc)


def _audit(event: str, *, user_id: int = 0, owner_id: int = 0, ip: str = "",
           extra: Optional[Dict[str, Any]] = None) -> None:
    if runtime_env.is_production() and runtime_env.environment_explicit():
        from . import storage_router
        from .production_storage import StorageError
        values: Dict[str, Any] = {
            "user_id": int(user_id or 0),
            "owner_id": int(owner_id or 0),
            "ip": str(ip or "")[:120],
        }
        if extra:
            values.update(extra)
        try:
            storage_router.append_audit("telegram_account_auth", event, values)
            return
        except StorageError as exc:
            raise AccountAuthError(
                f"Production account audit unavailable ({exc.code}).",
                503, code=exc.code,
            ) from None
    row = {"timestamp": _now_iso(), "source": "telegram_account_auth", "event": event,
           "user_id": user_id or None, "owner_id": owner_id or None, "ip": str(ip or "")}
    if extra:
        row.update({k: v for k, v in extra.items() if k not in row})
    path = _audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _find_user_by_google(doc: Dict[str, Any], google_sub: str) -> Optional[Dict[str, Any]]:
    sub = str(google_sub or "").strip()
    if not sub:
        return None
    for user in doc.get("users") or []:
        if hmac.compare_digest(str(user.get("google_sub") or ""), sub):
            return user
    return None


def link_google_identity(
    user_id: Any,
    *,
    google_sub: str,
    google_email: str = "",
    google_name: str = "",
    source: str = "google_oauth",
) -> Dict[str, Any]:
    uid = int(user_id)
    sub = str(google_sub or "").strip()
    email = str(google_email or "").strip().lower()
    if not sub:
        raise AccountAuthError("google_sub обязателен.")
    with _LOCK:
        doc = _read_doc()
        user = _user(doc, uid)
        if user is None:
            raise AccountAuthError("Пользователь не найден.", 404)
        if user.get("status") not in {"active", "pending"}:
            raise AccountAuthError("Аккаунт недоступен для привязки Google.", 403)
        other = _find_user_by_google(doc, sub)
        if other is not None and int(other.get("user_id") or 0) != uid:
            raise AccountAuthError("Этот Google-аккаунт уже привязан к другому профилю.", 409)
        # One Telegram ↔ one Google: if user already linked a different sub, refuse.
        existing_sub = str(user.get("google_sub") or "").strip()
        if existing_sub and not hmac.compare_digest(existing_sub, sub):
            raise AccountAuthError("К профилю уже привязан другой Google-аккаунт.", 409)
        user["google_sub"] = sub
        user["google_email"] = email
        user["google_name"] = str(google_name or "")[:120]
        user["google_linked_at_utc"] = _now_iso()
        user["google_link_source"] = str(source or "google_oauth")[:40]
        if email and not str(user.get("email") or "").strip():
            user["email"] = email
        _write_doc(doc)
        public = _public_user(user, include_contact=True, include_avatar=True)
    _audit("google_linked", user_id=uid, extra={"source": source, "google_email": email})
    return {"ok": True, "user": public}


def unlink_google_identity(owner_id: Any, user_id: Any) -> Dict[str, Any]:
    """Owner recovery helper: clear Google factor (user must re-link)."""
    uid = int(user_id)
    with _LOCK:
        doc = _read_doc()
        _require_owner_in_doc(doc, owner_id)
        user = _user(doc, uid)
        if user is None:
            raise AccountAuthError("Пользователь не найден.", 404)
        user["google_sub"] = ""
        user["google_email"] = ""
        user["google_name"] = ""
        user["google_linked_at_utc"] = ""
        user["google_unlinked_at_utc"] = _now_iso()
        _write_doc(doc)
        public = _public_user(user, include_contact=True)
    _audit("google_unlinked", user_id=uid, owner_id=int(owner_id))
    return {"ok": True, "user": public}


def create_session_for_user(
    user_id: Any,
    *,
    ip: str,
    user_agent: str = "",
    source: str = "desktop_session",
    require_google: bool = True,
    skip_dual_auth_gate: bool = False,
    impersonator_owner_id: int = 0,
    impersonation_preset: str = "",
    ttl_sec: int = 0,
) -> Dict[str, Any]:
    uid = int(user_id)
    with _LOCK:
        doc = _read_doc()
        user = _user(doc, uid)
        if not user:
            raise AccountAuthError("Пользователь не найден.", 404)
        if user.get("status") != "active":
            raise AccountAuthError("Аккаунт не активен.", 403)
        if require_google and not skip_dual_auth_gate and user_needs_google(user) and not impersonator_owner_id:
            # Still issue a session so the client can show the Google link step.
            pass
        token = secrets.token_urlsafe(48)
        csrf = secrets.token_urlsafe(32)
        now = time.time()
        ttl = int(ttl_sec) if int(ttl_sec or 0) > 0 else (
            IMPERSONATION_TTL_SEC if impersonator_owner_id else SESSION_TTL_SEC
        )
        row = {
            "session_id": "sess_" + secrets.token_hex(8),
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(),
            "csrf_token": csrf,
            "user_id": uid,
            "created_at_utc": _now_iso(),
            "expires_at": now + ttl,
            "ip_hash": hashlib.sha256(str(ip or "").encode()).hexdigest(),
            "ua_hash": hashlib.sha256(str(user_agent or "").encode()).hexdigest(),
            "revoked": False,
            "device_id": _device_id(user_agent),
            "client": _device_label(user_agent),
            "machine": _machine_label(),
            "ip": _mask_ip(ip),
            "source": str(source or "desktop_session")[:40],
        }
        if impersonator_owner_id:
            row["impersonator_owner_id"] = int(impersonator_owner_id)
            row["impersonation_started_at_utc"] = _now_iso()
            row["impersonation_preset"] = str(impersonation_preset or "")[:40]
        doc["sessions"].append(row)
        _append_login(user, source=str(source or "desktop_session"), ip=ip, user_agent=user_agent)
        _cleanup(doc)
        _write_doc(doc)
        public = _public_user(user, include_contact=True, include_avatar=True)
    _audit(
        "impersonation_started" if impersonator_owner_id else "login_succeeded",
        user_id=uid,
        owner_id=int(impersonator_owner_id or 0),
        ip=ip,
        extra={"source": source},
    )
    return {
        "status": "authenticated",
        "session_token": token,
        "csrf_token": csrf,
        "user": public,
        "needs_google": user_needs_google(user),
        "impersonating": bool(impersonator_owner_id),
    }


def create_or_update_virtual_user(
    *,
    user_id: int,
    username: str,
    first_name: str,
    last_name: str = "",
    email: str = "",
    role: str = "read_only",
    status: str = "active",
    google_linked: bool = False,
    google_sub: str = "",
    google_email: str = "",
    virtual: bool = True,
    preset: str = "",
    terms_accepted: bool = True,
    ux_mode: Optional[str] = None,
) -> Dict[str, Any]:
    runtime_env.require_staging("Virtual users")
    uid = int(user_id)
    role_id = str(role or "read_only")
    if role_id not in ROLES or role_id == "owner":
        role_id = "read_only"
    status_id = str(status or "active")
    if ux_mode is None:
        mode = "professional"
    else:
        mode = str(ux_mode or "").strip().lower()
        if mode and mode not in UX_MODES:
            mode = ""
    with _LOCK:
        doc = _read_doc()
        user = _user(doc, uid)
        if user is None:
            user = {
                "user_id": uid,
                "username": str(username or f"virtual_{uid}")[:64],
                "first_name": str(first_name or "Virtual")[:80],
                "last_name": str(last_name or "")[:80],
                "email": str(email or "").strip().lower(),
                "phone": "",
                "phone_hash": "",
                "role": role_id,
                "status": status_id,
                "is_owner": False,
                "created_at_utc": _now_iso(),
                "approved_at_utc": _now_iso() if status_id == "active" else "",
                "revoked_at_utc": "",
                "is_virtual": bool(virtual),
                "virtual_preset": str(preset or "")[:40],
                "ux_mode": mode,
            }
            if mode:
                user["ux_mode_set_at_utc"] = _now_iso()
            if terms_accepted:
                user["terms_accepted_at_utc"] = _now_iso()
                user["terms_version"] = str(getattr(legal, "TERMS_VERSION", "1") or "1")
            doc["users"].append(user)
        else:
            user.update({
                "username": str(username or user.get("username") or f"virtual_{uid}")[:64],
                "first_name": str(first_name or user.get("first_name") or "Virtual")[:80],
                "last_name": str(last_name or user.get("last_name") or "")[:80],
                "email": str(email or user.get("email") or "").strip().lower(),
                "role": role_id,
                "status": status_id,
                "is_virtual": bool(virtual),
                "virtual_preset": str(preset or user.get("virtual_preset") or "")[:40],
            })
            if status_id == "active" and not user.get("approved_at_utc"):
                user["approved_at_utc"] = _now_iso()
            if ux_mode is not None:
                user["ux_mode"] = mode
                if mode:
                    user["ux_mode_set_at_utc"] = user.get("ux_mode_set_at_utc") or _now_iso()
        if google_linked:
            user["google_sub"] = str(google_sub or f"test-google-{uid}")
            user["google_email"] = str(google_email or email or f"virtual{uid}@staging.stratforge.local").lower()
            user["google_linked_at_utc"] = user.get("google_linked_at_utc") or _now_iso()
            user["google_link_source"] = "test_auth"
        else:
            user["google_sub"] = ""
            user["google_email"] = ""
            user["google_linked_at_utc"] = ""
        _write_doc(doc)
        public = _public_user(user, include_contact=True, include_avatar=True)
    _audit("virtual_user_upsert", user_id=uid, extra={"preset": preset, "ux_mode": mode})
    return public


def list_virtual_users() -> list[Dict[str, Any]]:
    runtime_env.require_staging("Virtual users")
    with _LOCK:
        doc = _read_doc()
        return [
            _public_user(user, include_contact=True)
            for user in doc.get("users") or []
            if user.get("is_virtual")
        ]


def start_impersonation(
    owner_id: Any,
    target_user_id: Any,
    *,
    ip: str = "127.0.0.1",
    user_agent: str = "owner-impersonation",
    preset: str = "",
) -> Dict[str, Any]:
    runtime_env.require_impersonation()
    oid = int(owner_id)
    tid = int(target_user_id)
    with _LOCK:
        doc = _read_doc()
        owner = _require_owner_in_doc(doc, oid)
        target = _user(doc, tid)
        if target is None:
            raise AccountAuthError("Пользователь не найден.", 404)
        if target.get("is_owner"):
            raise AccountAuthError("Нельзя войти как владелец через impersonation.", 400)
        target_first = str(target.get("first_name") or "")
        target_last = str(target.get("last_name") or "")
        target_preset = str(preset or target.get("virtual_preset") or "")
        owner_label = str(owner.get("first_name") or owner.get("username") or oid)
    session = create_session_for_user(
        tid,
        ip=ip,
        user_agent=user_agent,
        source="impersonation",
        skip_dual_auth_gate=True,
        impersonator_owner_id=oid,
        impersonation_preset=target_preset,
    )
    _audit(
        "impersonation_started",
        user_id=tid,
        owner_id=oid,
        ip=ip,
        extra={"preset": target_preset},
    )
    return {
        "ok": True,
        "impersonating": True,
        "target_user_id": tid,
        "owner_id": oid,
        "owner_label": owner_label,
        "banner": (
            f"Тестовый режим. Вы вошли как пользователь: "
            f"{target_first} {target_last} "
            f"(id {tid})."
        ).strip(),
        **session,
    }


def end_impersonation(token: str, *, owner_id: Any, ip: str = "", user_agent: str = "") -> Dict[str, Any]:
    """End impersonation session and restore a fresh owner session."""
    runtime_env.require_impersonation()
    oid = int(owner_id)
    digest = hashlib.sha256(str(token or "").encode()).hexdigest()
    target_uid = 0
    with _LOCK:
        doc = _read_doc()
        _require_owner_in_doc(doc, oid)
        for session in doc.get("sessions") or []:
            if hmac.compare_digest(str(session.get("token_hash") or ""), digest):
                if int(session.get("impersonator_owner_id") or 0) != oid:
                    raise AccountAuthError("Сессия impersonation не принадлежит владельцу.", 403)
                target_uid = int(session.get("user_id") or 0)
                session["revoked"] = True
                session["revoked_at_utc"] = _now_iso()
                session["revoked_reason"] = "impersonation_end"
                _write_doc(doc)
                break
        else:
            raise AccountAuthError("Сессия impersonation не найдена.", 404)
    restored = create_session_for_user(
        oid,
        ip=ip or "127.0.0.1",
        user_agent=user_agent or "owner-return",
        source="impersonation_return",
        skip_dual_auth_gate=True,
    )
    _audit("impersonation_ended", user_id=target_uid, owner_id=oid, ip=ip)
    return {"ok": True, "impersonating": False, "restored_owner": True, **restored}


def active_sessions_overview(owner_id: Any) -> Dict[str, Any]:
    """Flat list of all active auth sessions across users (Monitoring tab)."""
    with _LOCK:
        doc = _read_doc()
        _require_owner_in_doc(doc, owner_id)
        now = time.time()
        users_by_id = {int(u.get("user_id") or 0): u for u in doc.get("users") or []}
        rows = []
        for session in doc.get("sessions") or []:
            if session.get("revoked") or float(session.get("expires_at") or 0) <= now:
                continue
            uid = int(session.get("user_id") or 0)
            user = users_by_id.get(uid) or {}
            rows.append({
                "session_id": _session_id(session),
                "user_id": uid,
                "username": str(user.get("username") or ""),
                "first_name": str(user.get("first_name") or ""),
                "last_name": str(user.get("last_name") or ""),
                "is_owner": bool(user.get("is_owner")),
                "is_virtual": bool(user.get("is_virtual")),
                "created_at_utc": str(session.get("created_at_utc") or ""),
                "client": str(session.get("client") or ""),
                "machine": str(session.get("machine") or ""),
                "ip": str(session.get("ip") or ""),
                "source": str(session.get("source") or "desktop_session"),
                "impersonating": bool(session.get("impersonator_owner_id")),
            })
    rows.sort(key=lambda item: str(item.get("created_at_utc") or ""), reverse=True)
    return {"ok": True, "sessions": rows, "count": len(rows)}
