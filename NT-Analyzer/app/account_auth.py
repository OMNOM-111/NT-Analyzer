"""Unified accounts and desktop browser sessions.

The canonical internal identity is an opaque UUID. Telegram ``user.id``,
Google ``sub`` and a normalized verified email are external provider subjects.
The legacy numeric ``user_id`` remains dual-written during the expand/cutover
window so existing workspaces, conversations and Connector records keep their
references. Google OAuth is **not** required for ordinary app use.
Google + a fresh Telegram confirmation are required only before NinjaTrader
control actions (personal bridge, live/paper commands that drive NT) — see
``nt_action_gate`` / ``require_nt_dual_auth``.

Personal data, login challenges and session-token hashes are stored in one
Windows DPAPI-encrypted document. A verified human registration with accepted
terms activates a professional account and one non-renewing seven-day full
trial. Plain session tokens exist only in the browser cookie and in the single
response that creates them.

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
import shutil
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Optional, Tuple

from . import auth_identity, legal, qr_code, runtime_env, secure_store


SESSION_COOKIE = "sf_session"
SESSION_TTL_SEC = 30 * 24 * 60 * 60
CHALLENGE_TTL_SEC = 15 * 60
# Login challenge lifecycle. Opening is repeatable while the TTL lasts;
# only an explicit confirmation spends the challenge, and only the browser
# that owns it can exchange the result for a session.
LOGIN_PENDING = "created"        # QR on screen, nothing has happened yet
LOGIN_OPENED = "opened"          # deep link opened, awaiting confirmation
LOGIN_CONFIRMED = "login_approved"
LOGIN_CONSUMED = "consumed"      # session issued: single-use, spent
LOGIN_CANCELLED = "denied"
# A single Telegram bot serves every environment, and Production owns the
# webhook. A callback_query carries no message text to route on, so the
# environment that issued the challenge is stamped into the callback data
# itself -- otherwise Production answers a Canary confirmation against its
# own store, finds nothing, and the waiting browser hangs forever.
ENVIRONMENT_TAGS = {
    runtime_env.DEVELOPMENT: "d",
    runtime_env.CANARY: "c",
    runtime_env.PRODUCTION: "p",
}
ENVIRONMENT_BY_TAG = {tag: name for name, tag in ENVIRONMENT_TAGS.items()}
# A browser login QR is shown on screen and is a bearer token for one
# account, so it lives for minutes rather than a quarter of an hour. The
# login page refreshes it in place when it lapses.
LOGIN_CHALLENGE_TTL_SEC = 10 * 60
OWNER_APPROVAL_TTL_SEC = 7 * 24 * 60 * 60
ADMIN_REVOKE_NOTICE_TTL_SEC = 24 * 60 * 60
IMPERSONATION_TTL_SEC = 4 * 60 * 60
NT_STEP_UP_TTL_SEC = 30 * 60
NT_CONFIRM_TTL_SEC = 10 * 60
UX_MODES = ("beginner", "professional")
ACCOUNT_STORE_VERSION = 3
EMAIL_CHALLENGE_TTL_SEC = 10 * 60
EMAIL_MAX_ATTEMPTS = 5
# Session revoke reasons that keep a short notice window so the client can show
# a clear "session ended" message instead of a bare 401.
_REVOKE_NOTICE_REASONS = frozenset({"admin", "device_revoked", "device_rejected"})
EXTERNAL_LEGACY_ID_FLOOR = 8_000_000_000_000_000
EXTERNAL_LEGACY_ID_CEILING = 8_900_000_000_000_000
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
    return {
        "version": ACCOUNT_STORE_VERSION,
        "users": [],
        "auth_identities": [],
        "challenges": [],
        "sessions": [],
        "trusted_devices": [],
        "security_challenges": [],
        "identity_schema": {"stage": "dual_write", "canonical_key": "user_uuid"},
    }


def _identity_rows(doc: Dict[str, Any]) -> list[Dict[str, Any]]:
    rows = doc.get("auth_identities")
    if not isinstance(rows, list):
        rows = []
        doc["auth_identities"] = rows
    return rows


def _user_uuid(user: Optional[Dict[str, Any]]) -> str:
    return auth_identity.normalize_user_uuid((user or {}).get("user_uuid"))


def _identity(
    doc: Dict[str, Any], provider: Any, subject: Any,
) -> Optional[Dict[str, Any]]:
    try:
        provider_id = auth_identity.normalize_provider(provider)
        normalized = auth_identity.normalize_subject(provider_id, subject)
    except auth_identity.IdentityError:
        return None
    for row in _identity_rows(doc):
        if not isinstance(row, dict):
            continue
        try:
            row_provider = auth_identity.normalize_provider(row.get("provider"))
            row_subject = auth_identity.normalize_subject(row_provider, row.get("provider_subject"))
        except auth_identity.IdentityError:
            continue
        if row_provider == provider_id and hmac.compare_digest(row_subject, normalized):
            return row
    return None


def _identities_for_user(doc: Dict[str, Any], user: Dict[str, Any]) -> list[Dict[str, Any]]:
    canonical = _user_uuid(user)
    if not canonical:
        return []
    return [
        row for row in _identity_rows(doc)
        if isinstance(row, dict) and hmac.compare_digest(
            auth_identity.normalize_user_uuid(row.get("user_uuid")), canonical,
        )
    ]


def _link_identity_in_doc(
    doc: Dict[str, Any],
    user: Dict[str, Any],
    *,
    provider: Any,
    subject: Any,
    verified_at_utc: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    source: str = "migration",
    touch: bool = True,
) -> Dict[str, Any]:
    try:
        provider_id = auth_identity.normalize_provider(provider)
        normalized = auth_identity.normalize_subject(provider_id, subject)
    except auth_identity.IdentityError as exc:
        raise AccountAuthError(str(exc), 400, code="identity_invalid") from None
    canonical = _user_uuid(user)
    if not canonical:
        canonical = auth_identity.new_user_uuid()
        user["user_uuid"] = canonical
    existing = _identity(doc, provider_id, normalized)
    if existing is not None and not hmac.compare_digest(
        auth_identity.normalize_user_uuid(existing.get("user_uuid")), canonical,
    ):
        raise AccountAuthError(
            "Этот способ входа уже связан с другим профилем.", 409,
            code="identity_already_linked",
        )
    # A verified address belongs to one account across every provider that can
    # carry one. Without this, the same mailbox could be an e-mail identity on
    # one account and the address behind a Google sub on another -- two
    # accounts one person can prove ownership of, which is the silent merge the
    # model forbids. The database enforces the same rule; this exists so the
    # caller gets a specific error instead of a constraint violation.
    claimed_email = ""
    if provider_id == "email":
        claimed_email = normalized
    elif isinstance(metadata, dict) and metadata.get("email"):
        try:
            claimed_email = auth_identity.normalize_email(metadata.get("email"))
        except auth_identity.IdentityError:
            claimed_email = ""
    if claimed_email and (verified_at_utc or provider_id == "email"):
        for row in _identity_rows(doc):
            if not isinstance(row, dict) or row.get("revoked_at_utc"):
                continue
            if not row.get("verified_at_utc"):
                continue
            other = str((row.get("metadata") or {}).get("email") or "")
            if str(row.get("provider") or "") == "email":
                other = str(row.get("provider_subject") or "")
            if not other:
                continue
            try:
                other = auth_identity.normalize_email(other)
            except auth_identity.IdentityError:
                continue
            if other != claimed_email:
                continue
            if not hmac.compare_digest(
                auth_identity.normalize_user_uuid(row.get("user_uuid")), canonical,
            ):
                raise AccountAuthError(
                    "Этот e-mail уже подтверждён в другом профиле.", 409,
                    code="email_already_verified_elsewhere",
                )
    now = _now_iso()
    if existing is None:
        existing = {
            "identity_id": auth_identity.deterministic_identity_id(provider_id, normalized),
            "user_uuid": canonical,
            "legacy_user_id": int(user.get("user_id") or 0),
            "provider": provider_id,
            "provider_subject": normalized,
            "linked_at_utc": now,
            "verified_at_utc": str(verified_at_utc or now),
            "last_used_at_utc": now if touch else "",
            "link_source": str(source or "migration")[:60],
            "metadata": dict(metadata or {}),
        }
        _identity_rows(doc).append(existing)
    else:
        if touch:
            existing["last_used_at_utc"] = now
        if verified_at_utc and not existing.get("verified_at_utc"):
            existing["verified_at_utc"] = str(verified_at_utc)
        if metadata:
            current = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}
            current.update(dict(metadata))
            existing["metadata"] = current
    return existing


def _allocate_external_legacy_user_id(doc: Dict[str, Any]) -> int:
    used = {int(row.get("user_id") or 0) for row in doc.get("users") or [] if isinstance(row, dict)}
    span = EXTERNAL_LEGACY_ID_CEILING - EXTERNAL_LEGACY_ID_FLOOR
    for _ in range(64):
        candidate = EXTERNAL_LEGACY_ID_FLOOR + secrets.randbelow(span)
        if candidate not in used:
            return candidate
    raise AccountAuthError("Не удалось выделить compatibility id.", 503, code="legacy_id_exhausted")


def _sync_user_identity_summary(doc: Dict[str, Any], user: Dict[str, Any]) -> None:
    identities = sorted(
        _identities_for_user(doc, user),
        key=lambda row: (str(row.get("provider") or ""), str(row.get("linked_at_utc") or "")),
    )
    user["linked_providers"] = [
        auth_identity.public_identity(row, user=user) for row in identities
    ]
    user["identity_count"] = len(identities)


def _telegram_subject_for_user(doc: Dict[str, Any], user: Dict[str, Any]) -> int:
    for row in _identities_for_user(doc, user):
        if str(row.get("provider") or "") != "telegram":
            continue
        try:
            return int(auth_identity.normalize_subject("telegram", row.get("provider_subject")))
        except (auth_identity.IdentityError, TypeError, ValueError):
            return 0
    try:
        return int(user.get("telegram_user_id") or 0)
    except (TypeError, ValueError):
        return 0


def telegram_subject_for_user(user_id: Any) -> int:
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        return 0
    with _LOCK:
        doc = _read_doc_reference()
        user = _user(doc, uid)
        return _telegram_subject_for_user(doc, user) if user else 0


def user_uuid_for_legacy_id(user_id: Any) -> str:
    """Resolve a compatibility BIGINT account key to its canonical UUID."""
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        return ""
    if uid <= 0:
        return ""
    with _LOCK:
        user = _user(_read_doc_reference(), uid)
        return _user_uuid(user) if user else ""


def _identity_migration_backup(path: Path) -> None:
    if not path.is_file():
        return
    backup = path.with_name(path.name + ".identity-v2-backup")
    if backup.exists():
        return
    try:
        shutil.copy2(path, backup)
        try:
            os.chmod(backup, 0o600)
        except OSError:
            pass
    except OSError as exc:
        raise AccountAuthError(
            f"Не удалось создать encrypted backup перед UUID migration: {exc}",
            503,
            code="identity_backup_failed",
        ) from None


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
    legacy_identity_model = version < 3
    if version < 2:
        for user in doc.get("users") or []:
            if not isinstance(user, dict):
                continue
            if str(user.get("ux_mode") or "").strip().lower() not in UX_MODES:
                user["ux_mode"] = "professional"
                user["ux_mode_migrated_at_utc"] = _now_iso()
    if not isinstance(doc.get("auth_identities"), list):
        doc["auth_identities"] = []
    migrated_at = str((doc.get("identity_schema") or {}).get("migrated_at_utc") or "")
    for user in doc.get("users") or []:
        if not isinstance(user, dict):
            continue
        try:
            legacy_id = int(user.get("user_id") or user.get("legacy_user_id") or 0)
        except (TypeError, ValueError):
            legacy_id = 0
        if legacy_id <= 0:
            raise AccountAuthError("Account store contains an invalid legacy user id.", 500)
        user["user_id"] = legacy_id
        user["legacy_user_id"] = legacy_id
        canonical = _user_uuid(user)
        if not canonical:
            canonical = auth_identity.new_user_uuid()
            user["user_uuid"] = canonical
        telegram_subject = str(user.get("telegram_user_id") or "").strip()
        if legacy_identity_model and not user.get("is_virtual"):
            telegram_subject = str(legacy_id)
        if telegram_subject:
            user["telegram_user_id"] = int(telegram_subject)
            _link_identity_in_doc(
                doc,
                user,
                provider="telegram",
                subject=telegram_subject,
                verified_at_utc=str(user.get("phone_verified_at_utc") or user.get("created_at_utc") or _now_iso()),
                metadata={"username": str(user.get("username") or "")},
                source="v2_backfill" if legacy_identity_model else "dual_write_repair",
                touch=False,
            )
        elif legacy_identity_model and user.get("is_virtual"):
            _link_identity_in_doc(
                doc,
                user,
                provider="test",
                subject=f"legacy-{legacy_id}",
                verified_at_utc=str(user.get("created_at_utc") or _now_iso()),
                source="v2_backfill",
                touch=False,
            )
        google_sub = str(user.get("google_sub") or "").strip()
        if google_sub:
            _link_identity_in_doc(
                doc,
                user,
                provider="google",
                subject=google_sub,
                verified_at_utc=str(user.get("google_linked_at_utc") or _now_iso()),
                metadata={"email": str(user.get("google_email") or "").casefold()},
                source="legacy_google_backfill",
                touch=False,
            )
    by_legacy = {
        int(user.get("user_id") or 0): _user_uuid(user)
        for user in doc.get("users") or [] if isinstance(user, dict)
    }
    for collection in ("sessions", "challenges"):
        rows = doc.get(collection)
        if not isinstance(rows, list):
            rows = []
            doc[collection] = rows
        for row in rows:
            if not isinstance(row, dict) or auth_identity.normalize_user_uuid(row.get("user_uuid")):
                continue
            try:
                legacy_id = int(row.get("user_id") or 0)
            except (TypeError, ValueError):
                legacy_id = 0
            if legacy_id in by_legacy:
                row["user_uuid"] = by_legacy[legacy_id]
    for user in doc.get("users") or []:
        if isinstance(user, dict):
            _sync_user_identity_summary(doc, user)
    doc["identity_schema"] = {
        "stage": "dual_write",
        "canonical_key": "user_uuid",
        "legacy_key": "user_id",
        "migrated_at_utc": migrated_at or _now_iso(),
    }
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


def _authoritative_storage() -> bool:
    """True when account state must be read/written through PostgreSQL.

    Canary and Production both declare an explicit server environment and must
    never fall back to local DPAPI just because they are not literally
    ``production``.
    """
    from . import storage_router
    return storage_router.production_enabled()


def _read_doc() -> Dict[str, Any]:
    if _authoritative_storage():
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
        for key in ("users", "auth_identities", "challenges", "sessions"):
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
    for key in ("users", "auth_identities", "challenges", "sessions"):
        if not isinstance(doc.get(key), list):
            doc[key] = []
    try:
        original_version = int(doc.get("version") or 1)
    except (TypeError, ValueError):
        original_version = 1
    doc = _migrate_doc(doc)
    if original_version < ACCOUNT_STORE_VERSION:
        # The encrypted source remains recoverable byte-for-byte until a later
        # owner-approved contract phase removes the legacy mapping.
        _identity_migration_backup(path)
        _write_doc(doc)
        return doc
    _cache_doc(path, doc)
    return doc


def _read_doc_reference() -> Dict[str, Any]:
    """Internal read-only view of the current local cache.

    Mutation paths keep using ``_read_doc`` and therefore receive an isolated
    deep copy.  Lookup paths may inspect this object only while ``_LOCK`` is
    held and must copy the selected row before returning it.
    """
    if _authoritative_storage():
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


# The owner bootstrap is idempotent and, in a healthy deployment, changes
# nothing. It was still reading the entire account document -- from Postgres,
# with no cache on that path, then migrating it -- on every authenticated
# poll, which measured about 37 ms of server time per request against 0.9 ms
# for an endpoint that touches no auth at all. Remembering that the owner row
# was already correct is enough; it cannot spontaneously stop being true, and
# any write in this process clears it immediately.
_OWNER_BOOTSTRAP_TTL_SEC = 30.0
_OWNER_BOOTSTRAP_LOCK = threading.Lock()
_OWNER_BOOTSTRAP: Dict[str, Any] = {"uid": 0, "until": 0.0, "user": None}


def _forget_owner_bootstrap() -> None:
    with _OWNER_BOOTSTRAP_LOCK:
        _OWNER_BOOTSTRAP["uid"] = 0
        _OWNER_BOOTSTRAP["until"] = 0.0
        _OWNER_BOOTSTRAP["user"] = None


def _write_doc(doc: Dict[str, Any]) -> None:
    # Any mutation of the account store invalidates what the bootstrap
    # remembered, so the memo can never outlive a change made here.
    _forget_owner_bootstrap()
    doc = _migrate_doc(copy.deepcopy(doc))
    if _authoritative_storage():
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
    tmp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        tmp.write_bytes(payload)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        # Windows scanners/readers can briefly hold the destination without
        # FILE_SHARE_DELETE. Preserve the old encrypted document and retry only
        # the atomic replacement; never fall back to truncating the live store.
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.02 * (attempt + 1))
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
    # Authentication remains fail-closed, but the retired Mini App flag no longer
    # participates in the current product's security decision.
    if os.environ.get("NTA_TEST_BYPASS_AUTH") == "1":
        return False
    config = _remote_config()
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
    if _authoritative_storage():
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
    # Phase 5: the independent identity factor is a verified email, satisfiable
    # by a verified email login identity or a safely linked Google verified
    # email. ``email_factor_ok`` is precomputed by ``require_nt_dual_auth`` from
    # the encrypted store; direct callers fall back to the Google link.
    g_ok = (not google_req) or bool(user.get("email_factor_ok")) or google_linked(user)
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
            "подтвердите e-mail или подключите Google. Остальные разделы доступны без этого."
        )
    elif not tg_ok:
        code = "nt_telegram_confirm_required"
        message = (
            "Подтвердите действие повторно в Telegram — "
            "это нужно перед любыми командами в NinjaTrader."
        )
    return {
        "ok": ready, "ready": ready, "google_ok": g_ok, "telegram_ok": tg_ok,
        "email_factor_ok": g_ok,
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
            doc = _read_doc()
            stored = _user(doc, uid)
            if stored is not None:
                raw_user = dict(stored)
                # Never trust a client/public google_linked without google_sub in store.
                if not str(raw_user.get("google_sub") or "").strip():
                    raw_user["google_linked"] = False
                # Phase 5: a verified email login identity also satisfies the
                # independent identity factor (not only Google).
                from . import personal_nt_security
                raw_user["email_factor_ok"] = personal_nt_security.email_factor_ok(doc, stored)
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


# --------------------------------------------------------------------------- #
# StratForge handle (the account's own public name).
# --------------------------------------------------------------------------- #
# ``username`` mirrors whatever Telegram reports and is rewritten on every
# Telegram login, so it cannot be the name the person chose here. The handle is
# owned by StratForge: the user picks it during registration, external identity
# providers may only *suggest* it, and nothing but an explicit user action ever
# changes it.
HANDLE_MIN_LEN = 3
HANDLE_MAX_LEN = 32
_HANDLE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_.]*[a-z0-9])?$", re.ASCII)
_HANDLE_RESERVED = frozenset({
    "admin", "administrator", "root", "owner", "support", "help", "security",
    "stratforge", "stratforgeai", "system", "moderator", "staff", "official",
    "billing", "payments", "api", "bot", "null", "undefined", "me", "you",
})


def normalize_handle(value: Any, *, required: bool = True) -> str:
    """Validate and canonicalise a StratForge handle.

    The canonical form is lowercase; the user may type `@name` or `Name`.
    """
    raw = str(value or "").strip().lstrip("@").strip()
    if not raw:
        if required:
            raise AccountAuthError(
                "Придумайте имя пользователя StratForge.", 400, code="handle_required",
            )
        return ""
    handle = raw.lower()
    if not HANDLE_MIN_LEN <= len(handle) <= HANDLE_MAX_LEN:
        raise AccountAuthError(
            f"Имя пользователя — от {HANDLE_MIN_LEN} до {HANDLE_MAX_LEN} символов.",
            400, code="handle_length",
        )
    if not _HANDLE_RE.match(handle):
        raise AccountAuthError(
            "Разрешены латинские буквы, цифры, точка и подчёркивание; "
            "начинаться и заканчиваться — буквой или цифрой.",
            400, code="handle_format",
        )
    if ".." in handle or "__" in handle:
        raise AccountAuthError(
            "Уберите повторяющиеся точки или подчёркивания.", 400, code="handle_format",
        )
    if handle in _HANDLE_RESERVED:
        raise AccountAuthError(
            "Это имя пользователя зарезервировано.", 409, code="handle_reserved",
        )
    return handle


def _handle_owner_uuid(doc: Dict[str, Any], handle: str) -> str:
    for row in doc.get("users") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("handle") or "").strip().lower() == handle:
            return _user_uuid(row)
    return ""


def handle_available(value: Any, *, user_uuid: str = "") -> Dict[str, Any]:
    """Public availability probe used by the registration form."""
    try:
        handle = normalize_handle(value)
    except AccountAuthError as exc:
        return {
            "handle": str(value or "").strip().lstrip("@").lower()[:HANDLE_MAX_LEN],
            "available": False,
            "reason": str(exc),
            "code": getattr(exc, "code", "") or "handle_invalid",
        }
    with _LOCK:
        doc = _read_doc()
        owner = _handle_owner_uuid(doc, handle)
    taken = bool(owner) and owner != str(user_uuid or "")
    return {
        "handle": handle,
        "available": not taken,
        "reason": "Это имя пользователя уже занято." if taken else "",
        "code": "handle_taken" if taken else "",
    }


def _assign_handle_in_doc(doc: Dict[str, Any], user: Dict[str, Any], value: Any) -> str:
    """Claim a handle for exactly one account, or fail closed."""
    handle = normalize_handle(value)
    owner = _handle_owner_uuid(doc, handle)
    if owner and owner != _user_uuid(user):
        raise AccountAuthError(
            "Это имя пользователя уже занято.", 409, code="handle_taken",
        )
    user["handle"] = handle
    user["handle_set_at_utc"] = user.get("handle_set_at_utc") or _now_iso()
    user["updated_at_utc"] = _now_iso()
    return handle


def suggest_handle(*, email: Any = "", username: Any = "", name: Any = "") -> str:
    """A safe starting point for the field; never applied without the user."""
    for candidate in (
        str(username or "").strip().lstrip("@"),
        str(email or "").split("@", 1)[0],
        str(name or "").strip().replace(" ", "_"),
    ):
        cleaned = re.sub(r"[^a-z0-9_.]+", "", str(candidate or "").lower())
        cleaned = re.sub(r"[._]{2,}", "_", cleaned).strip("._")
        if len(cleaned) < HANDLE_MIN_LEN:
            continue
        cleaned = cleaned[:HANDLE_MAX_LEN]
        try:
            normalized = normalize_handle(cleaned)
        except AccountAuthError:
            continue
        if handle_available(normalized)["available"]:
            return normalized
    return ""


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


DEVICE_CREDENTIAL_BYTES = 32


def new_device_credential() -> str:
    """Opaque per-browser credential. Only its HMAC is ever stored."""
    return secrets.token_urlsafe(DEVICE_CREDENTIAL_BYTES)


def _device_id(user_agent: Any = "", *, device_credential: Any = "") -> str:
    """Stable identity for one browser profile.

    The credential is a random value the browser holds in an httpOnly cookie,
    so one browser profile is one device across refresh, logout and re-login,
    and two different browsers are never the same device.

    It must never be derived from the server's hostname or account name — those
    are identical for every user of a deployment, which both split one browser
    into several devices whenever its User-Agent changed and collapsed
    different users' browsers onto one record.  The User-Agent is display
    metadata only.  A client with no cookie jar (the Connector) supplies its own
    credential; without either, the caller gets a per-session value that never
    silently merges with another device.
    """
    credential = str(device_credential or "").strip()
    if not credential:
        return "anon:" + secrets.token_hex(8)
    return hashlib.sha256(
        ("device-credential/v1\0" + credential).encode("utf-8", errors="ignore")
    ).hexdigest()[:32]


def _upsert_device(user: Dict[str, Any], *, source: str, ip: str = "",
                   user_agent: str = "", email: str = "",
                   device_credential: str = "") -> None:
    """Record last-login metadata only.

    Devices themselves live in one place — ``doc["trusted_devices"]``, managed
    by ``security_devices``.  The per-user ``devices`` list this function used
    to maintain was a second, unconstrained store of the same thing, and the
    Cabinet showed both, which is where the duplicates came from.
    """
    user.pop("devices", None)
    user["last_login_device_id"] = _device_id(user_agent, device_credential=device_credential)
    user["last_login_at_utc"] = _now_iso()
    user["last_login_source"] = str(source or "")
    user["last_login_ip"] = _mask_ip(ip)
    profile_email = str(email or "").strip().lower()
    if profile_email:
        user["last_login_email"] = profile_email


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
                  user_agent: str = "", email: str = "",
                  device_credential: str = "") -> None:
    now = _now_iso()
    device = _device_label(user_agent)
    machine = _machine_label()
    device_id = _device_id(user_agent, device_credential=device_credential)
    user["last_login_at_utc"] = now
    user["last_login_source"] = source
    user["last_login_device"] = device
    user["last_login_machine"] = machine
    user["last_login_device_id"] = device_id
    _upsert_device(user, source=source, ip=ip, user_agent=user_agent,
                   email=email or str(user.get("email") or ""),
                   device_credential=device_credential)
    history = user.get("login_history") if isinstance(user.get("login_history"), list) else []
    history.append({
        "at": now, "source": source, "device": device,
        "machine": machine, "device_id": device_id, "ip": _mask_ip(ip),
    })
    user["login_history"] = history[-20:]


def _observe_session_device(
    doc: Dict[str, Any], session: Dict[str, Any], user: Dict[str, Any], *,
    ip: str = "", user_agent: str = "", source: str = "",
    connector_installation_id: str = "", device_credential: str = "",
) -> list:
    """Register the trusted device for a new session (Phase 4).

    Deferred import avoids an import cycle: ``security_devices`` depends on this
    module's store helpers. Returns audit events for the caller to emit after
    the document is persisted. Impersonation sessions never register a device.
    """
    if session.get("impersonator_owner_id"):
        session["device_confirmation_exempt"] = True
        session["device_confirmation_required"] = False
        session["device_confirmation_state"] = "active"
        session["device_trust_mode"] = "exempt"
        return []
    from . import security_devices
    try:
        events = security_devices.observe_session(
            doc, session, user, ip=ip, user_agent=user_agent, source=source,
            connector_installation_id=connector_installation_id,
            device_credential=device_credential,
        )
    except security_devices.SecurityDeviceError as exc:
        raise AccountAuthError(
            "Не удалось безопасно зарегистрировать новый доступ.",
            503, code=exc.code or "device_security_unavailable",
        ) from None
    except Exception:
        raise AccountAuthError(
            "Не удалось безопасно зарегистрировать новый доступ.",
            503, code="device_security_unavailable",
        ) from None
    if (not session.get("device_confirmation_exempt")
            and not session.get("trusted_device_id")):
        raise AccountAuthError(
            "Не удалось безопасно зарегистрировать новый доступ.",
            503, code="device_security_unavailable",
        )
    return events


def _user(doc: Dict[str, Any], user_id: int) -> Optional[Dict[str, Any]]:
    return next((row for row in doc["users"] if int(row.get("user_id") or 0) == int(user_id)), None)


def _user_by_uuid(doc: Dict[str, Any], user_uuid: Any) -> Optional[Dict[str, Any]]:
    canonical = auth_identity.normalize_user_uuid(user_uuid)
    if not canonical:
        return None
    return next((
        row for row in doc.get("users") or []
        if isinstance(row, dict) and hmac.compare_digest(_user_uuid(row), canonical)
    ), None)


def _profile_complete(user: Dict[str, Any]) -> bool:
    return bool(user.get("first_name") and user.get("last_name") and user.get("email"))


def _activate_verified_human_in_doc(user: Dict[str, Any], *, source: str) -> bool:
    """Activate one verified human account and queue its one initial trial.

    Workspace membership remains the data/write boundary: a full-control trial
    user is still a viewer in the owner's workspace and an owner only in their
    isolated personal workspace. Returning active accounts are intentionally
    not altered or queued, so deploying this model cannot restart old access.
    """
    if user.get("is_owner") or user.get("is_service_account"):
        return False
    if str(user.get("status") or "") in {"revoked", "denied", "blocked", "deleted"}:
        return False
    newly_activated = str(user.get("status") or "") != "active"
    if not newly_activated:
        return False
    now = _now_iso()
    user.update({
        "status": "active",
        "role": "full_control",
        "ux_mode": "professional",
        "approved_at_utc": user.get("approved_at_utc") or now,
        "revoked_at_utc": "",
        "updated_at_utc": now,
        "initial_trial_pending": True,
        "initial_trial_source": str(source or "verified_registration")[:80],
    })
    return True


def _ensure_registration_trial(user: Dict[str, Any], *, source: str = "") -> Dict[str, Any]:
    """Complete the cross-store registration outbox, idempotently."""
    snapshot = dict(user or {})
    if (not snapshot.get("initial_trial_pending") or snapshot.get("is_owner")
            or snapshot.get("is_service_account")):
        return {}
    uid = int(snapshot.get("user_id") or 0)
    if uid <= 0 or str(snapshot.get("status") or "") != "active":
        return {}
    from . import subscriptions  # lazy import keeps authentication/storage layers acyclic
    try:
        granted = subscriptions.ensure_initial_trial(
            uid,
            user_uuid=_user_uuid(snapshot),
            source=str(source or snapshot.get("initial_trial_source") or "verified_registration"),
        )
        # The registration outbox provisions the user's own container too.
        # Preview registration uses this exact path, including entitlement
        # admission; neither registration path attaches private AI work to
        # the owner's training workspace.
        from . import workspaces
        granted["workspace"] = workspaces.ensure_personal_workspace(uid)
    except subscriptions.SubscriptionError as exc:
        raise AccountAuthError(
            f"Аккаунт подтверждён, но trial пока не сохранён: {exc}",
            getattr(exc, "status", 503),
            code="initial_trial_unavailable",
        ) from None
    with _LOCK:
        doc = _read_doc()
        current = _user(doc, uid)
        if current and _user_uuid(current) == _user_uuid(snapshot) and current.get("initial_trial_pending"):
            current["initial_trial_pending"] = False
            current["initial_trial_granted_at_utc"] = _now_iso()
            current["initial_trial_entitlement_id"] = str(
                (granted.get("entitlement") or {}).get("entitlement_id") or ""
            )
            current["updated_at_utc"] = _now_iso()
            _write_doc(doc)
    return granted


def _ensure_pending_registration_trial(user_id: Any) -> Dict[str, Any]:
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        return {}
    with _LOCK:
        doc = _read_doc_reference()
        user = _user(doc, uid)
        snapshot = copy.deepcopy(user) if user and user.get("initial_trial_pending") else {}
    return _ensure_registration_trial(snapshot)


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




def _public_user(user: Dict[str, Any], *, include_contact: bool = False,
                 include_legacy: bool = False) -> Dict[str, Any]:
    out = {key: user.get(key) for key in (
        "username", "handle", "first_name", "last_name", "role", "status",
        "is_owner", "created_at_utc", "approved_at_utc", "revoked_at_utc",
        "last_login_at_utc", "phone_verified_at_utc",
        "last_login_source", "last_login_device", "last_login_machine",
        "last_login_device_id", "blocked_at_utc",
        "google_linked_at_utc", "google_email", "email_verified_at_utc",
        "primary_login_provider", "is_virtual", "virtual_preset",
        "is_preview_user", "preview_sandbox_id", "ux_mode",
    )}
    out["id"] = str(user.get("user_uuid") or "")
    if include_legacy:
        out["user_id"] = int(user.get("user_id") or 0)
        out["legacy_user_id"] = int(user.get("legacy_user_id") or user.get("user_id") or 0)
        out["telegram_user_id"] = int(user.get("telegram_user_id") or 0)
    out["linked_providers"] = [
        dict(row) for row in (user.get("linked_providers") or []) if isinstance(row, dict)
    ]
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
        # Devices are served by /api/account/devices from the single
        # trusted-device store; echoing a second copy here is what made one
        # browser appear twice in the Cabinet.
        out["devices"] = []
        out["device_count"] = 0
        # Never expose raw google_sub to non-owner clients in lists; ok in own profile.
        out["google_sub_suffix"] = str(user.get("google_sub") or "")[-8:]
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
        return {"ok": True, "unchanged": True, "user": _public_user(snap or {}, include_contact=True)}
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
    return {"ok": True, "user": _public_user(snapshot, include_contact=True)}


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
        if user.get("is_owner") and cap != "ai_automation":
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


CANONICAL_OWNER_UUID_ENV = "STRATFORGE_CANONICAL_OWNER_UUID"


class OwnerIdentityConflict(AccountAuthError):
    """The configured owner disagrees with the owner already in the store.

    Raised instead of quietly repairing, because both silent outcomes are
    wrong: minting a second owner splits the account in two, and rewriting the
    existing one destroys whichever identity was already there.
    """


def canonical_owner_uuid() -> str:
    """The immutable UUID that defines the owner, if this deployment names one.

    Deliberately configuration, not a constant: it is a real personal
    identifier and belongs in a local secret store, never in the repository.
    Empty means "this deployment has not been told", and the behaviour then
    falls back to whichever owner already exists.
    """
    return auth_identity.normalize_user_uuid(
        os.environ.get(CANONICAL_OWNER_UUID_ENV) or ""
    )


def _active_owner_rows(doc: Dict[str, Any]) -> list:
    return [
        u for u in (doc.get("users") or [])
        if isinstance(u, dict) and u.get("is_owner") and u.get("status") == "active"
    ]


def owner_claim(
    doc: Dict[str, Any], *,
    provider: Any = "", subject: Any = "",
    user_id: Any = 0, user: Optional[Dict[str, Any]] = None,
    owner_chat_id: Any = "",
) -> bool:
    """The single authority on "is this login the owner", for every provider.

    Owner identity is a person, not an environment variable. A deployment that
    simply forgot to export ``NTA_TELEGRAM_CHAT_ID`` used to turn the canonical
    owner into an ordinary verified human, which then ran the registration
    trial branch and greeted the owner with Free Preview. The chat id is one
    *identity of* the owner; the canonical UUID is who they are.

    Resolution order, first match wins:

    * the stored row already says owner -- the store is authoritative and a
      missing variable must never demote an existing owner;
    * the row's UUID is the configured canonical owner UUID;
    * the presented provider identity is linked to the canonical owner UUID,
      which is what makes the same human resolve identically in LOCAL, Canary
      and Production;
    * the legacy chat-id comparison, kept so existing deployments that only
      configure ``NTA_TELEGRAM_CHAT_ID`` keep working unchanged.
    """
    if isinstance(user, dict) and user.get("is_owner"):
        return True
    canonical = canonical_owner_uuid()
    if canonical:
        if isinstance(user, dict) and hmac.compare_digest(_user_uuid(user), canonical):
            return True
        row = _identity(doc, provider, subject) if provider and subject else None
        if row is not None:
            linked = _user_by_uuid(doc, row.get("user_uuid"))
            if linked is None:
                try:
                    linked = _user(doc, int(row.get("legacy_user_id") or 0)) or None
                except (TypeError, ValueError):
                    linked = None
            if linked is not None and hmac.compare_digest(_user_uuid(linked), canonical):
                return True
    configured = str(owner_chat_id or os.environ.get("NTA_TELEGRAM_CHAT_ID") or "").strip()
    return bool(configured) and str(user_id or "").strip() == configured


def owner_user_uuid_for_new_row(is_owner: bool) -> str:
    """A recognised owner keeps the canonical UUID instead of a fresh one.

    Minting a new UUID for an owner the deployment already names is how one
    human became two identities across environments.
    """
    if is_owner:
        canonical = canonical_owner_uuid()
        if canonical:
            return canonical
    return auth_identity.new_user_uuid()


def ensure_owner(owner_id: Any) -> Optional[Dict[str, Any]]:
    """Make sure the configured owner exists, without ever inventing a second.

    The owner is defined by an immutable UUID. A Telegram chat id, a Google
    account or an e-mail are *identities of* that UUID, not the thing that
    decides who the owner is. Treating a development convenience variable as
    the definition is what produced a synthetic owner on LOCAL while the real
    one lived in another store.

    So this refuses loudly in the two cases it used to paper over:

    * an owner already exists under a different account id -- creating one for
      the configured chat id would give the deployment two owners;
    * an owner exists whose UUID disagrees with the configured canonical UUID
      -- rewriting it would destroy real identity state.

    Both raise OwnerIdentityConflict with the values named, which is a problem
    an operator can act on. Silently repairing was not.
    """
    try:
        uid = int(owner_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if not uid:
        return None
    configured_owner = str(os.environ.get("NTA_TELEGRAM_CHAT_ID") or "").strip()
    if not configured_owner or str(uid) != configured_owner:
        raise AccountAuthError("Owner identity не совпадает с настроенным личным чатом Telegram.", 403)
    canonical = canonical_owner_uuid()

    now = time.time()
    with _OWNER_BOOTSTRAP_LOCK:
        remembered = (
            _OWNER_BOOTSTRAP["user"]
            if _OWNER_BOOTSTRAP["uid"] == uid and now < _OWNER_BOOTSTRAP["until"]
            else None
        )
    if remembered is not None:
        # Nothing is authorised here. This says the owner row exists and is
        # already correct; every session check still reads the store.
        return copy.deepcopy(remembered)

    with _LOCK:
        doc = _read_doc()
        existing = _user(doc, uid)
        owners = _active_owner_rows(doc)

        if existing is None and owners:
            # The case that created the synthetic LOCAL owner. A configuration
            # change must not mint a rival account.
            raise OwnerIdentityConflict(
                "Владелец уже существует под другим account id "
                f"({', '.join(str(u.get('user_id')) for u in owners)}), "
                f"а настроен {uid}. Второй владелец не создаётся. "
                "Приведите NTA_TELEGRAM_CHAT_ID в соответствие или выполните "
                "перенос владельца.",
                409,
            )

        if existing is not None and canonical:
            current_uuid = auth_identity.normalize_user_uuid(existing.get("user_uuid"))
            if current_uuid and current_uuid != canonical:
                raise OwnerIdentityConflict(
                    f"UUID владельца в хранилище ({current_uuid}) не совпадает "
                    f"с каноническим ({canonical}). Аккаунт не переписывается "
                    "автоматически: это уничтожило бы существующие identities.",
                    409,
                )

        changed = False
        if existing is None:
            legacy = _remote_config()
            legacy_user = next((row for row in legacy.get("users") or [] if int(row.get("user_id") or 0) == uid), {})
            existing = {
                "user_id": uid,
                "legacy_user_id": uid,
                # The canonical UUID when this deployment names one, so a fresh
                # store comes up as the same owner rather than a new person.
                "user_uuid": canonical or auth_identity.new_user_uuid(),
                "telegram_user_id": uid,
                "username": str(legacy_user.get("username") or ""),
                "first_name": str(legacy_user.get("first_name") or ""),
                "last_name": str(legacy_user.get("last_name") or ""),
                "email": "", "phone": "", "phone_hash": str(legacy.get("owner_phone_hash") or ""),
                "role": "owner", "status": "active", "is_owner": True,
                "primary_login_provider": "telegram",
                "created_at_utc": _now_iso(), "approved_at_utc": _now_iso(), "revoked_at_utc": "",
            }
            doc["users"].append(existing)
            changed = True
        else:
            if int(existing.get("telegram_user_id") or 0) != uid:
                existing["telegram_user_id"] = uid
                changed = True
            if existing.get("role") != "owner" or not existing.get("is_owner") or existing.get("status") != "active":
                existing.update({"role": "owner", "is_owner": True, "status": "active", "revoked_at_utc": ""})
                changed = True
        if _identity(doc, "telegram", str(uid)) is None:
            _link_identity_in_doc(
                doc, existing, provider="telegram", subject=str(uid),
                verified_at_utc=str(existing.get("phone_verified_at_utc") or _now_iso()),
                metadata={"username": str(existing.get("username") or "")},
                source="owner_bootstrap",
                touch=False,
            )
            changed = True
        _sync_user_identity_summary(doc, existing)
        if changed:
            _write_doc(doc)
        public = _public_user(existing, include_contact=True)
        if not changed:
            # Only a run that had nothing to fix may be remembered. One that
            # repaired something says nothing about the next call.
            with _OWNER_BOOTSTRAP_LOCK:
                _OWNER_BOOTSTRAP["uid"] = uid
                _OWNER_BOOTSTRAP["until"] = time.time() + _OWNER_BOOTSTRAP_TTL_SEC
                _OWNER_BOOTSTRAP["user"] = copy.deepcopy(public)
        return public


def _primary_owner_row() -> Optional[Dict[str, Any]]:
    configured = str(os.environ.get("NTA_TELEGRAM_CHAT_ID") or "").strip()
    with _LOCK:
        doc = _read_doc_reference()
        owners = [
            u for u in (doc.get("users") or [])
            if isinstance(u, dict) and u.get("is_owner") and u.get("status") == "active"
        ]
    if not owners:
        return None
    # The canonical UUID outranks the chat id: it is the same authority the
    # login paths use, so LOCAL opens as exactly the owner Canary and
    # Production resolve rather than merely the lowest-numbered one.
    canonical = canonical_owner_uuid()
    if canonical:
        match = next(
            (u for u in owners if hmac.compare_digest(_user_uuid(u), canonical)),
            None,
        )
        if match:
            return match
    if configured:
        match = next((u for u in owners if str(u.get("user_id") or "") == configured), None)
        if match:
            return match
    named = [u for u in owners if str(u.get("first_name") or "").strip()]
    return min(named or owners, key=lambda u: int(u.get("user_id") or 0))


def primary_owner_id() -> int:
    """Return the canonical local owner's legacy user id (0 if none)."""
    row = _primary_owner_row()
    return int((row or {}).get("user_id") or 0)


def primary_owner() -> Optional[Dict[str, Any]]:
    """Return the canonical local owner account (Development convenience).

    Prefers the owner whose id matches ``NTA_TELEGRAM_CHAT_ID``, then any active
    owner that has a real name, then the lowest active owner id. Used to give a
    localhost Development session the real owner profile and data even when the
    Telegram chat id is not exported into the environment, instead of falling
    back to an empty synthetic ``ws_local_owner`` scope.
    """
    row = _primary_owner_row()
    if row is None:
        return None
    return _public_user(row, include_contact=True)


def ensure_service_account_user(
    user_id: int, *, first_name: str, last_name: str = "", username: str = "",
) -> Dict[str, Any]:
    """Create/refresh a Development-only service account (Claude/GPT).

    The row itself is not a global owner; owner-equivalent authority is granted
    only inside the localhost Development request context. A distinct ``user_id``
    keeps every audit record attributable to the service account rather than the
    human owner. Never available outside Development.
    """
    runtime_env.require_staging("Service accounts")
    uid = int(user_id)
    with _LOCK:
        doc = _read_doc()
        user = _user(doc, uid)
        now = _now_iso()
        if user is None:
            user = {
                "user_id": uid,
                "legacy_user_id": uid,
                "user_uuid": auth_identity.new_user_uuid(),
                "username": str(username or f"service_{uid}")[:64],
                "first_name": str(first_name or "Service")[:80],
                "last_name": str(last_name or "")[:80],
                "email": "", "phone": "", "phone_hash": "",
                "role": "read_only", "status": "active", "is_owner": False,
                "is_service_account": True,
                "primary_login_provider": "dev_service",
                "created_at_utc": now, "approved_at_utc": now, "revoked_at_utc": "",
                "ux_mode": "professional",
                "terms_accepted_at_utc": now,
                "terms_version": str(getattr(legal, "TERMS_VERSION", "1") or "1"),
                "terms_digest": str(getattr(legal, "TERMS_DIGEST", "") or ""),
            }
            doc["users"].append(user)
        else:
            user.update({
                "first_name": str(first_name or user.get("first_name") or "Service")[:80],
                "last_name": str(last_name or user.get("last_name") or "")[:80],
                "status": "active", "is_service_account": True,
                "primary_login_provider": "dev_service",
                "revoked_at_utc": "",
            })
            if not user.get("approved_at_utc"):
                user["approved_at_utc"] = now
        _sync_user_identity_summary(doc, user)
        _write_doc(doc)
        return _public_user(user, include_contact=True)


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


def find_active_user_by_uuid(user_uuid: Any) -> Optional[Dict[str, Any]]:
    """The active account behind a canonical user UUID, as ``find_active_user``."""
    with _LOCK:
        user = _user_by_uuid(_read_doc_reference(), user_uuid)
        if not user:
            return None
        uid = user.get("user_id") or user.get("id")
    return find_active_user(uid)


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
            "users": [
                _public_user(row, include_contact=True, include_legacy=True)
                for row in users
            ],
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


def account_footprint(owner_id: Any, user_id: Any) -> Dict[str, Any]:
    """Read-only dependency check for one account, before deleting it.

    The FK constraints on ``user_uuid`` are declared NOT VALID in the
    relational mirror, so nothing downstream refuses a delete that would strand
    rows. This reports the footprint explicitly instead.
    """
    uid = int(user_id)
    with _LOCK:
        doc = _read_doc()
        _require_admin_capability_in_doc(doc, owner_id, "users.manage")
        user = _user(doc, uid)
        if user is None:
            raise AccountAuthError("Пользователь не найден.", 404)
        canonical = _user_uuid(user)
        counts = {
            "identities": len(_identities_for_user(doc, user)),
            "sessions": len(_rows_for_account(doc, "sessions", canonical, uid)),
            "challenges": len(_rows_for_account(doc, "challenges", canonical, uid)),
            "trusted_devices": len(_rows_for_account(doc, "trusted_devices", canonical, uid)),
            "security_challenges": len(_rows_for_account(doc, "security_challenges", canonical, uid)),
        }
        is_owner = bool(user.get("is_owner"))
    from . import workspaces
    try:
        workspace_footprint = workspaces.user_footprint(canonical, uid)
    except Exception:
        workspace_footprint = {"safe_to_delete": True, "shared_workspaces": []}
    return {
        "user_id": uid,
        "user_uuid": canonical,
        "is_owner": is_owner,
        "account": counts,
        "workspaces": workspace_footprint,
        "safe_to_delete": bool(
            not is_owner and workspace_footprint.get("safe_to_delete", True)
        ),
    }


def _rows_for_account(
    doc: Dict[str, Any], key: str, user_uuid: str, legacy_user_id: int,
) -> list[Dict[str, Any]]:
    """Rows in ``doc[key]`` belonging to one account, by UUID or legacy id.

    Rows written before the Phase 3 backfill carry only the legacy id and rows
    written after it carry only the UUID, so a delete keyed on one of them
    leaves the other half behind.
    """
    out = []
    for row in doc.get(key) or []:
        if not isinstance(row, dict):
            continue
        row_uuid = auth_identity.normalize_user_uuid(row.get("user_uuid"))
        if user_uuid and row_uuid:
            if hmac.compare_digest(row_uuid, user_uuid):
                out.append(row)
            continue
        try:
            legacy = int(row.get("user_id") or row.get("legacy_user_id") or 0)
        except (TypeError, ValueError):
            legacy = 0
        if legacy_user_id and legacy == legacy_user_id:
            out.append(row)
    return out


def delete_user(owner_id: Any, user_id: Any) -> Dict[str, Any]:
    """Permanently remove a user and everything keyed to that account.

    Sessions and avatars were never the whole footprint: an account also owns
    auth identities, trusted devices and step-up challenges keyed by
    ``user_uuid``. Leaving an identity row behind is not cosmetic — the subject
    stays bound to a user that no longer exists, so it can never be linked to a
    real account again (``identity_already_linked``).
    """
    uid = int(user_id)
    from . import workspaces
    # The workspace store is a separate document, so its refusal has to happen
    # before this one is mutated -- otherwise a shared-workspace rejection
    # leaves the account deleted and its workspaces orphaned.
    report = account_footprint(owner_id, uid)
    # Owner protection outranks every other reason to refuse: the owner account
    # is never deletable, whatever its workspaces look like.
    if report["is_owner"]:
        raise AccountAuthError("Аккаунт владельца нельзя удалить.", 403)
    shared = report["workspaces"].get("shared_workspaces") or []
    if shared:
        raise AccountAuthError(
            "Аккаунт владеет рабочей областью с другими участниками: "
            + ", ".join(shared) + ". Передайте её другому владельцу.",
            409, code="workspace_shared",
        )
    # Workspaces go first. sf_workspaces.owner_user_id is ON DELETE RESTRICT,
    # so pruning sf_users while a workspace still names the account raises a
    # foreign key violation that rolls the whole document write back. Purging
    # afterwards -- as this did -- could therefore never succeed: the write it
    # was waiting for had already failed.
    workspaces.purge_user(report["user_uuid"], uid)
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
        canonical = _user_uuid(user)
        removed = {
            "identities": len(_identities_for_user(doc, user)),
            "sessions": len(_rows_for_account(doc, "sessions", canonical, uid)),
            "challenges": len(_rows_for_account(doc, "challenges", canonical, uid)),
            "trusted_devices": len(_rows_for_account(doc, "trusted_devices", canonical, uid)),
            "security_challenges": len(_rows_for_account(doc, "security_challenges", canonical, uid)),
        }
        doc["users"] = [row for row in doc["users"] if int(row.get("user_id") or 0) != uid]
        for key in ("sessions", "challenges", "trusted_devices", "security_challenges"):
            doomed = {id(row) for row in _rows_for_account(doc, key, canonical, uid)}
            doc[key] = [row for row in doc.get(key) or [] if id(row) not in doomed]
        if canonical:
            doc["auth_identities"] = [
                row for row in _identity_rows(doc)
                if not hmac.compare_digest(
                    auth_identity.normalize_user_uuid(row.get("user_uuid")), canonical,
                )
            ]
        _write_doc(doc)
    for stale in _avatars_dir().glob(f"{uid}.*"):
        try:
            stale.unlink()
        except OSError:
            pass
    # The audit actor is the owner who performed the deletion, never the
    # account just removed: storage_router.append_audit turns values["user_id"]
    # into the scope that fills sf_audit_events.user_id, which is a foreign key
    # to sf_users. Naming the deleted account there fails the INSERT outright --
    # ON DELETE SET NULL governs deletes of the parent, not inserts pointing at
    # a row that is already gone. The deleted identity stays as plain payload.
    _audit("user_deleted", owner_id=int(owner_id), user_id=0,
           extra={"deleted_user_uuid": canonical, "deleted_legacy_user_id": uid,
                  "removed": removed})
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
        pub = _public_user(user, include_contact=True, include_legacy=True)
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


def revoke_own_session(user_id: Any, session_id: str) -> Dict[str, Any]:
    """End one of the caller's own sessions.

    Separate from ``revoke_user_sessions``, which is the administrative action
    and requires ``users.manage``. An account ending its own session needs no
    capability, but it also cannot name a subject: the owner of the session is
    taken from the authenticated caller, never from the request, so a session id
    is not enough to reach someone else's login.
    """
    uid = int(user_id or 0)
    target = str(session_id or "").strip()
    if uid <= 0:
        raise AccountAuthError("Требуется вход.", 401)
    if not target:
        raise AccountAuthError("Не указана сессия.", 400)
    with _LOCK:
        doc = _read_doc()
        user = _user(doc, uid)
        if user is None:
            raise AccountAuthError("Пользователь не найден.", 404)
        revoked = 0
        for session in doc["sessions"]:
            if int(session.get("user_id") or 0) != uid:
                continue
            if not hmac.compare_digest(_session_id(session), target):
                continue
            if session.get("revoked"):
                break
            session["revoked"] = True
            session["revoked_at_utc"] = _now_iso()
            session["revoked_reason"] = "self_service"
            revoked += 1
            break
        if revoked:
            _write_doc(doc)
    if revoked:
        _audit("session.revoked", user_id=uid, extra={"reason": "self_service"})
    return {"ok": True, "revoked": revoked}


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
        if row.get("revoked") and row.get("revoked_reason") in _REVOKE_NOTICE_REASONS and notice_until > now:
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
    environment = runtime_env.deployment_environment()
    with _LOCK:
        doc = _read_doc()
        _cleanup(doc)
        doc["challenges"].append({
            "challenge_id": challenge_id, "code": code, "status": "created",
            "kind": "provider_auth", "provider": "telegram", "purpose": "login",
            # The environment is part of the challenge, not just of the deep
            # link text, so a code scanned into the wrong bot/environment is
            # rejected by the store rather than by a string comparison.
            "environment": environment,
            "created_at_utc": _now_iso(),
            "expires_at": now + LOGIN_CHALLENGE_TTL_SEC,
            "ip_hash": hashlib.sha256(str(ip or "").encode()).hexdigest(),
            "ua_hash": hashlib.sha256(str(user_agent or "").encode()).hexdigest(),
        })
        _write_doc(doc)
    _audit("login_started", ip=ip)
    canary_login = environment == runtime_env.CANARY
    start_payload = f"canary_login_{code}" if canary_login else f"login_{code}"
    manual_command = f"/login [CANARY] {code}" if canary_login else f"/login {code}"
    # The https form still matters: it is what a browser can follow, what a
    # desktop falls back to, and what works when Telegram is not installed.
    deep_link = f"https://t.me/{username}?start={start_payload}"
    # ...but it is the wrong thing to put in a QR. The iOS Camera app does not
    # honour Universal Links: it hands https URLs to Safari, so scanning the
    # t.me form lands in a browser first and the user has to continue into
    # Telegram by hand. The tg: scheme is registered by the installed app, so
    # the camera offers Telegram directly on iOS, and Android resolves it by
    # intent. That makes the app scheme the correct QR payload, with the https
    # link kept visible underneath for the no-Telegram case.
    app_link = f"tg://resolve?domain={username}&start={start_payload}"
    out = {
        "challenge_id": challenge_id, "status": "created",
        "expires_in_sec": LOGIN_CHALLENGE_TTL_SEC,
        "bot_url": deep_link,
        "app_url": app_link,
        "qr_payload": app_link,
        "web_fallback_url": deep_link,
        "code": code,
        "manual_command": manual_command,
    }
    try:
        out["qr_svg"] = qr_code.svg(app_link, size_px=232, title="Вход через Telegram")
    except qr_code.QRError:
        # A QR is a convenience; the deep link and manual code still work.
        out["qr_svg"] = ""
    return out


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
            # Expired or swept: the page starts a fresh, independent attempt.
            raise AccountAuthError("Запрос входа истёк. Начните заново.", 410)
        if str(challenge.get("status") or "") == LOGIN_CONSUMED:
            raise AccountAuthError("Эта ссылка входа уже использована.", 410)
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
        user["terms_digest"] = legal.TERMS_DIGEST
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
            _activate_verified_human_in_doc(user, source="telegram_profile")
            challenge["status"] = "login_approved"
        _write_doc(doc)
        activated = challenge["status"] == "login_approved"
        awaiting_owner = challenge["status"] == "pending_owner"
        newly = activated and prior_status != "active"
        snapshot = dict(user)
        cid = str(challenge.get("challenge_id") or "")
    if activated:
        if snapshot.get("initial_trial_pending"):
            _ensure_registration_trial(snapshot, source="telegram_profile")
        if newly and not snapshot.get("is_owner"):
            _notify_owner_new_user(api_call, owner_chat_id, snapshot)
        api_call("sendMessage", {"chat_id": int(snapshot["user_id"]), "text": (
            "Профиль заполнен. Полный доступ владельца — вернитесь в приложение."
            if snapshot.get("is_owner")
            else "Профиль заполнен. Открыт полный пробный доступ на 7 дней — вернитесь в приложение."
        )})
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
            "Открыт полный пробный доступ на 7 дней. Продлить период можно в карточке пользователя."
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

    New non-owner accounts activate after verified initData + accepted terms.
    Returning active users keep their original access clock. The caller MUST
    have validated initData.
    """
    try:
        uid = int(tg_user.get("id") or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise AccountAuthError("Некорректная Telegram identity.", 400)
    if not accept_terms:
        raise AccountAuthError("Необходимо принять условия использования.")
    fn = _clean_name(first_name or tg_user.get("first_name") or "—", "Имя")
    ln = _clean_name(last_name or tg_user.get("last_name") or "—", "Фамилия")
    em = _valid_email(email)
    now = _now_iso()
    challenge_id = ""
    with _LOCK:
        doc = _read_doc()
        user = _user(doc, uid)
        # Owner resolution happens against the store, so a linked canonical
        # identity counts even when this deployment exports no chat id.
        is_owner = owner_claim(
            doc, provider="telegram", subject=uid,
            user_id=uid, user=user, owner_chat_id=owner_chat_id,
        )
        prior_status = str((user or {}).get("status") or "")
        if user and not is_owner and user.get("status") in {"revoked", "denied", "blocked"}:
            raise AccountAuthError("Доступ к StratForge AI ограничен владельцем.", 403)
        if user is None:
            user = {
                "user_id": uid, "legacy_user_id": uid,
                "user_uuid": owner_user_uuid_for_new_row(is_owner),
                "telegram_user_id": uid,
                "username": str(tg_user.get("username") or ""),
                "first_name": fn, "last_name": ln, "email": em,
                "phone": "", "phone_hash": "",
                "role": "owner" if is_owner else "read_only",
                "status": "active" if is_owner else "pending", "is_owner": is_owner,
                "primary_login_provider": "telegram",
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
                _activate_verified_human_in_doc(user, source="telegram_mini_app")
            user["telegram_user_id"] = uid
        user["terms_accepted_at_utc"] = now
        user["terms_version"] = legal.TERMS_VERSION
        user["terms_digest"] = legal.TERMS_DIGEST
        user["identity_verified_via"] = "mini_app_initdata"
        _link_identity_in_doc(
            doc, user, provider="telegram", subject=str(uid),
            verified_at_utc=now,
            metadata={"username": str(user.get("username") or "")},
            source="telegram_mini_app",
        )
        _sync_user_identity_summary(doc, user)
        _append_login(user, source="telegram_mini_app", user_agent="Telegram Mini App", email=em)

        if not is_owner and user.get("status") != "active":
            _activate_verified_human_in_doc(user, source="telegram_mini_app")

        status_out = "active" if user.get("status") == "active" else "pending_owner"
        if status_out == "pending_owner":
            challenge_id = secrets.token_urlsafe(24)
            doc["challenges"].append({
                "challenge_id": challenge_id, "code": "", "status": "pending_owner",
                "user_id": uid, "user_uuid": _user_uuid(user), "created_at_utc": now,
                "expires_at": time.time() + OWNER_APPROVAL_TTL_SEC,
                "source": "mini_app_register",
            })
        _write_doc(doc)
        snapshot = dict(user)
    if snapshot.get("initial_trial_pending"):
        _ensure_registration_trial(snapshot, source="telegram_mini_app")
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
        "user": _public_user(snapshot, include_contact=True),
    }


def _send_owner_approval(api_call: Callable[..., Any], owner_chat_id: str,
                         user: Dict[str, Any], challenge_id: str) -> None:
    label = html.escape(f"{user.get('first_name', '')} {user.get('last_name', '')}".strip())
    provider = str(user.get("primary_login_provider") or "telegram").lower()
    provider_label = {"telegram": "Telegram", "google": "Google", "email": "Email OTP"}.get(
        provider, provider,
    )
    telegram_id = int(user.get("telegram_user_id") or 0)
    telegram_line = (
        f"Telegram user id: <code>{telegram_id}</code>\n"
        if telegram_id else "Telegram: <i>не привязан</i>\n"
    )
    username_line = (
        f"Username: @{html.escape(str(user.get('username') or '—'))}\n"
        if telegram_id else ""
    )
    api_call("sendMessage", {
        "chat_id": owner_chat_id, "parse_mode": "HTML",
        "text": (
            "🔐 <b>Новый аккаунт StratForge AI</b>\n"
            f"Пользователь: <b>{label}</b>\n"
            f"Первичная identity: <b>{html.escape(provider_label)}</b>\n"
            f"{telegram_line}{username_line}"
            f"E-mail: <code>{html.escape(str(user.get('email') or ''))}</code>\n"
            "Provider identity подтверждена; совпадение email само по себе аккаунты не объединяет.\n\n"
            "Только ваше личное подтверждение активирует аккаунт."
        ),
        "reply_markup": {"inline_keyboard": [[
            {"text": "✅ Разрешить аккаунт", "callback_data": f"account_allow:{challenge_id}"},
            {"text": "⛔ Отклонить", "callback_data": f"account_deny:{challenge_id}"},
        ]]},
    })


_ENVIRONMENT_APP_ORIGINS = {
    runtime_env.CANARY: "https://canary.stratforges.com",
    runtime_env.PRODUCTION: "https://app.stratforges.com",
}


def _app_open_url() -> str:
    """Public https URL of this environment's StratForge, or "" when there is none.

    Feeds a plain Telegram URL button, never a Web App button: the retired Mini
    App container must not come back through the bot.  Development has no public
    origin, so it gets no button at all rather than a loopback link Telegram
    would reject.
    """
    try:
        origin = str(runtime_env.deployment_config().public_origin or "").strip()
    except Exception:
        origin = ""
    if not origin.startswith("https://"):
        origin = _ENVIRONMENT_APP_ORIGINS.get(runtime_env.deployment_environment(), "")
    if not origin.startswith("https://"):
        return ""
    return origin.rstrip("/") + "/"


def _claim_refusal_text(doc: Dict[str, Any], *, code: str, uid: int) -> str:
    """Explain precisely why a scanned code was not accepted."""
    for row in reversed(doc.get("challenges") or []):
        if not isinstance(row, dict):
            continue
        if not hmac.compare_digest(str(row.get("code") or "").upper(), str(code or "").upper()):
            continue
        status = str(row.get("status") or "")
        bound = str(row.get("environment") or "")
        if bound and bound != runtime_env.deployment_environment():
            return "Эта ссылка входа выдана для другого окружения StratForge AI."
        if status == LOGIN_CONSUMED:
            return "Эта ссылка входа уже использована. Откройте новый QR-код."
        if status == LOGIN_CANCELLED:
            return "Этот вход был отменён. Откройте новый QR-код."
        if status == LOGIN_CONFIRMED:
            return "Этот вход уже подтверждён — вернитесь в браузер."
        if status == "awaiting_profile":
            # Confirmed, but the account still owes a profile. Saying "expired"
            # here sends the user to make a new QR that will stop at the same
            # place.
            return "Вход подтверждён. Вернитесь в приложение и заполните профиль."
        if status == "account_blocked":
            return "Доступ к StratForge AI ограничен владельцем."
        opener = int(row.get("user_id") or 0)
        if opener and opener != int(uid):
            return "Эта ссылка входа принадлежит другому аккаунту Telegram."
        break
    return "Ссылка входа истекла. Откройте новый QR-код в приложении."


def _claim_login_challenge(doc: Dict[str, Any], *, code: str, uid: int,
                           sender: Dict[str, Any],
                           status: str = "awaiting_contact") -> Optional[Dict[str, Any]]:
    """Open a login challenge. Opening is repeatable; only confirming spends it.

    Scanning a QR, or opening the deep link twice because Telegram was closed,
    must not invalidate a login nobody has confirmed yet. So an already-opened
    challenge is returned again unchanged instead of being refused, and the
    single-use transition lives in the confirmation step alone.
    """
    challenge = _challenge(doc, code=code, statuses=(LOGIN_PENDING, LOGIN_OPENED))
    if challenge is None:
        return None
    # A challenge is bound to the environment that issued it. A code scanned
    # against the wrong environment is refused rather than silently accepted.
    bound = str(challenge.get("environment") or "")
    if bound and bound != runtime_env.deployment_environment():
        return None
    # Once a Telegram account has opened a challenge it belongs to them; a
    # second person scanning the same screen cannot take it over.
    opener = int(challenge.get("user_id") or 0)
    if opener and opener != int(uid):
        return None
    challenge.update({"user_id": uid, "status": status, "telegram_started_at_utc": _now_iso()})
    challenge["telegram_user"] = {
        "username": str(sender.get("username") or ""),
        "first_name": str(sender.get("first_name") or ""),
        "last_name": str(sender.get("last_name") or ""),
    }
    return challenge


def _send_contact_request(api_call: Callable[..., Any], uid: int) -> None:
    marker = runtime_env.telegram_environment_marker()
    api_call("sendMessage", {
        "chat_id": uid,
        "text": (
            f"{marker}Подтвердите личность: отправьте свой Telegram-контакт кнопкой ниже. "
            "Чужой или введённый вручную номер не принимается."
        ),
        "reply_markup": {"keyboard": [[{"text": "📱 Подтвердить мой номер", "request_contact": True}]], "resize_keyboard": True, "one_time_keyboard": True},
    })


CONFIRM_LABEL = "✅ Подтвердить вход"
REJECT_LABEL = "⛔ Это не я"
# A tapped reply-keyboard button sends its own label as an ordinary message,
# and message text is the one thing the shared bot's owner already routes
# between environments. An inline button sends a callback_query instead, which
# carries no text at all -- so it is answered by whichever environment owns the
# bot, against that environment's store, no matter who owns the challenge.
_CONFIRM_RE = re.compile(
    r"^(?:✅|⛔)?\s*(Подтвердить вход|Это не я)"
    r"(?:\s+\[CANARY\])?(?:\s+\[DEV\])?\s+([A-Fa-f0-9]{8})$"
)


def _confirm_button_label(label: str, code: str) -> str:
    """A label that is also a routable message.

    The environment marker has to sit inside the text, because the text is what
    the bot owner routes on when it decides which environment should handle it.
    """
    marker = runtime_env.telegram_environment_marker().strip()
    return f"{label} {marker} {code}".replace("  ", " ").strip() if marker else f"{label} {code}"


def _send_login_confirm_request(api_call: Callable[..., Any], uid: int,
                                challenge_id: str, code: str = "") -> None:
    marker = runtime_env.telegram_environment_marker()
    api_call("sendMessage", {
        "chat_id": uid,
        "text": (
            f"{marker}Вход в StratForge AI. Подтвердите, что это вы — "
            "браузер войдёт автоматически."
        ),
        "reply_markup": {
            "keyboard": [
                [{"text": _confirm_button_label(CONFIRM_LABEL, code)}],
                [{"text": _confirm_button_label(REJECT_LABEL, code)}],
            ],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        },
    })


def _finish_login_confirmation(api_call: Callable[..., Any], *, uid: int, result: str,
                               snapshot: Dict[str, Any], owner_chat_id: str) -> None:
    texts = {
        "expired": "Запрос входа истёк или уже использован. Откройте новый QR-код.",
        "forbidden": "Подтвердить может только тот, кто открыл ссылку.",
        "denied": "Вход отклонён.",
        "blocked": "Доступ к StratForge AI ограничен владельцем.",
        "awaiting_profile": "Вернитесь в приложение и заполните обязательные поля профиля.",
    }
    if result == "login_approved":
        if snapshot.get("initial_trial_pending"):
            _ensure_registration_trial(snapshot, source="telegram_qr_login")
        if str(snapshot.get("_prior_status") or "") != "active" and not snapshot.get("is_owner"):
            _notify_owner_new_user(api_call, owner_chat_id, snapshot)
        api_call("sendMessage", {
            "chat_id": uid,
            "text": (
                "✅ Вход подтверждён — полный доступ владельца."
                if snapshot.get("is_owner")
                else "✅ Вход подтверждён. Вернитесь в приложение."
            ),
            "reply_markup": {"remove_keyboard": True},
        })
        _audit("login_confirmed", user_id=uid)
        return
    api_call("sendMessage", {
        "chat_id": uid,
        "text": texts.get(result, "Готово."),
        "reply_markup": {"remove_keyboard": True},
    })


def _apply_login_confirm(doc: Dict[str, Any], *, challenge_id: str, actor_id: int,
                         allowed: bool, owner_chat_id: str) -> Tuple[str, Dict[str, Any]]:
    """Resolve a one-tap login confirmation. Fail-closed on every mismatch."""
    challenge = _challenge(doc, challenge_id=challenge_id, statuses=(LOGIN_OPENED,))
    if challenge is None:
        return "expired", {}
    # The tap must come from the same Telegram account that opened the link,
    # so a forwarded button cannot approve somebody else's browser.
    if int(challenge.get("user_id") or 0) != int(actor_id or 0):
        return "forbidden", {}
    bound = str(challenge.get("environment") or "")
    if bound and bound != runtime_env.deployment_environment():
        return "expired", {}
    if not allowed:
        challenge["status"] = "denied"
        return "denied", {}

    uid = int(actor_id)
    user = _user(doc, uid)
    is_owner = owner_claim(
        doc, provider="telegram", subject=uid, user_id=uid, user=user,
        owner_chat_id=owner_chat_id,
    )
    tg = challenge.get("telegram_user") or {}
    if user is None:
        user = {
            "user_id": uid, "legacy_user_id": uid,
            "user_uuid": owner_user_uuid_for_new_row(is_owner),
            "telegram_user_id": uid,
            "username": str(tg.get("username") or ""),
            "first_name": str(tg.get("first_name") or ""),
            "last_name": str(tg.get("last_name") or ""),
            "email": "", "phone": "", "phone_hash": "",
            "role": "owner" if is_owner else "read_only",
            "status": "active" if is_owner else "pending",
            "is_owner": is_owner,
            "primary_login_provider": "telegram",
            "created_at_utc": _now_iso(),
            "approved_at_utc": _now_iso() if is_owner else "",
            "revoked_at_utc": "",
        }
        doc["users"].append(user)
    else:
        if not user.get("first_name"):
            user["first_name"] = str(tg.get("first_name") or "")
        if not user.get("last_name"):
            user["last_name"] = str(tg.get("last_name") or "")
        user["telegram_user_id"] = uid
        if is_owner and not user.get("is_owner"):
            user.update({
                "role": "owner", "is_owner": True, "status": "active",
                "approved_at_utc": user.get("approved_at_utc") or _now_iso(),
                "revoked_at_utc": "", "initial_trial_pending": False,
                "updated_at_utc": _now_iso(),
            })
    if user.get("status") in {"revoked", "denied", "blocked"}:
        challenge["status"] = "account_blocked"
        return "blocked", dict(user)

    _link_identity_in_doc(
        doc, user, provider="telegram", subject=str(uid),
        verified_at_utc=_now_iso(),
        metadata={"username": str(user.get("username") or "")},
        source="telegram_qr_login",
    )
    _sync_user_identity_summary(doc, user)
    challenge["user_uuid"] = _user_uuid(user)
    prior_status = str(user.get("status") or "")
    if _profile_complete(user):
        _activate_verified_human_in_doc(user, source="telegram_qr_login")
        challenge["status"] = "login_approved"
    else:
        user["status"] = user.get("status") or "pending"
        challenge["status"] = "awaiting_profile"
    snapshot = dict(user)
    snapshot["_prior_status"] = prior_status
    return challenge["status"], snapshot


def process_update(update: Dict[str, Any], *, api_call: Callable[..., Any], owner_chat_id: str) -> bool:
    callback = update.get("callback_query") if isinstance(update, dict) else None
    if isinstance(callback, dict):
        login_match = re.fullmatch(
            r"login_(ok|no):([dcp]):([A-Za-z0-9_-]{20,})", str(callback.get("data") or ""))
        if login_match:
            stamped = ENVIRONMENT_BY_TAG.get(login_match.group(2), "")
            if stamped and stamped != runtime_env.deployment_environment():
                # Belongs to another environment. Leave it entirely alone so it
                # can be routed there, instead of answering against this store.
                return False
            actor = int((callback.get("from") or {}).get("id") or 0)
            allowed = login_match.group(1) == "ok"
            with _LOCK:
                doc = _read_doc()
                result, snapshot = _apply_login_confirm(
                    doc, challenge_id=login_match.group(3), actor_id=actor,
                    allowed=allowed, owner_chat_id=owner_chat_id,
                )
                if result not in {"expired", "forbidden"}:
                    _write_doc(doc)
            answers = {
                "expired": "Запрос входа истёк или уже использован.",
                "forbidden": "Подтвердить может только тот, кто открыл ссылку.",
                "denied": "Вход отклонён.",
                "blocked": "Доступ к StratForge AI ограничен владельцем.",
                "awaiting_profile": "Осталось заполнить профиль в приложении.",
                "login_approved": "Готово — вернитесь в браузер.",
            }
            api_call("answerCallbackQuery", {
                "callback_query_id": callback.get("id"),
                "text": answers.get(result, "Готово."),
                "show_alert": result in {"expired", "forbidden", "blocked"},
            })
            if result == "login_approved":
                if snapshot.get("initial_trial_pending"):
                    _ensure_registration_trial(snapshot, source="telegram_qr_login")
                newly = str(snapshot.get("_prior_status") or "") != "active"
                if newly and not snapshot.get("is_owner"):
                    _notify_owner_new_user(api_call, owner_chat_id, snapshot)
                api_call("sendMessage", {"chat_id": actor, "text": (
                    "✅ Вход подтверждён — полный доступ владельца."
                    if snapshot.get("is_owner")
                    else "✅ Вход подтверждён. Вернитесь в приложение."
                )})
                _audit("login_confirmed", user_id=actor)
            elif result == "awaiting_profile":
                api_call("sendMessage", {"chat_id": actor, "text": (
                    "Вернитесь в приложение и заполните обязательные поля профиля."
                )})
            return True
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
                telegram_id = telegram_subject_for_user(uid)
                update_user(actor, uid, revoke=True)
                api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "Аккаунт отозван."})
                if telegram_id:
                    api_call("sendMessage", {"chat_id": telegram_id, "text": "⛔ Владелец отозвал ваш аккаунт StratForge AI."})
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
                _activate_verified_human_in_doc(user, source="legacy_owner_approval")
                next_challenge_status = "login_approved"
            else:
                user.update({"status": "denied", "revoked_at_utc": _now_iso()})
                next_challenge_status = "denied"
            # A user can legitimately retry an external-provider login while the
            # first owner request is still pending. Approve or deny every live
            # request for that canonical account so no polling window hangs.
            challenge_user_id = int(user.get("user_id") or 0)
            now_epoch = time.time()
            for pending in doc.get("challenges") or []:
                if not isinstance(pending, dict):
                    continue
                if int(pending.get("user_id") or 0) != challenge_user_id:
                    continue
                if str(pending.get("status") or "") != "pending_owner":
                    continue
                if float(pending.get("expires_at") or 0) <= now_epoch:
                    continue
                pending["status"] = next_challenge_status
            telegram_id = _telegram_subject_for_user(doc, user)
            _write_doc(doc)
            uid = int(user["user_id"])
            snapshot = dict(user)
        if allowed and snapshot.get("initial_trial_pending"):
            _ensure_registration_trial(snapshot, source="legacy_owner_approval")
        api_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "Аккаунт разрешён." if allowed else "Запрос отклонён."})
        if telegram_id:
            api_call("sendMessage", {"chat_id": telegram_id, "text": "✅ Аккаунт StratForge AI активирован." if allowed else "⛔ Владелец отклонил создание аккаунта."})
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
    confirm = _CONFIRM_RE.match(text)
    if confirm:
        allowed = confirm.group(1) == "Подтвердить вход"
        code = confirm.group(2)
        with _LOCK:
            doc = _read_doc()
            target = _challenge(doc, code=code, statuses=(LOGIN_OPENED,))
            if target is None:
                api_call("sendMessage", {
                    "chat_id": uid,
                    "text": _claim_refusal_text(doc, code=code, uid=uid),
                    "reply_markup": {"remove_keyboard": True},
                })
                return True
            result, snapshot = _apply_login_confirm(
                doc, challenge_id=str(target.get("challenge_id") or ""),
                actor_id=uid, allowed=allowed, owner_chat_id=owner_chat_id,
            )
            if result not in {"expired", "forbidden"}:
                _write_doc(doc)
        _finish_login_confirmation(
            api_call, uid=uid, result=result, snapshot=snapshot,
            owner_chat_id=owner_chat_id,
        )
        return True
    start = re.fullmatch(r"/start(?:@[A-Za-z0-9_]+)?\s+(login|canary_login)_([A-Fa-f0-9]{8})", text)
    manual_login = re.fullmatch(r"/(?:login|code)(?:@[A-Za-z0-9_]+)?\s+(?:\[CANARY\]\s+)?(?:login_)?([A-Fa-f0-9]{8})", text, flags=re.IGNORECASE)
    if start or manual_login:
        if start and start.group(1).lower() == "canary_login" and runtime_env.deployment_environment() != runtime_env.CANARY:
            return False
        if manual_login and "[CANARY]" in text.upper() and runtime_env.deployment_environment() != runtime_env.CANARY:
            return False
        code = start.group(2) if start else manual_login.group(1)
        with _LOCK:
            doc = _read_doc()
            challenge = _claim_login_challenge(
                doc, code=code, uid=uid, sender=sender, status=LOGIN_OPENED,
            )
            if challenge is None:
                api_call("sendMessage", {
                    "chat_id": uid,
                    "text": _claim_refusal_text(doc, code=code, uid=uid),
                })
                return True
            challenge_id = str(challenge.get("challenge_id") or "")
            _write_doc(doc)
        # One tap. Telegram already proved control of this account when it
        # delivered the deep link to this chat, so a contact is not asked for
        # on every login; a phone identity is a separate, later step.
        _send_login_confirm_request(api_call, uid, challenge_id, code)
        return True

    if re.fullmatch(r"/start(?:@[A-Za-z0-9_]+)?", text, flags=re.IGNORECASE):
        payload: Dict[str, Any] = {
            "chat_id": uid,
            "text": (
                "Для входа нужна одноразовая ссылка из окна StratForge AI. "
                "Если браузер открыл Telegram без кода, вернитесь в приложение, нажмите "
                "«Начать заново» и введите здесь ручную команду вида /login ABCD1234."
            ),
        }
        # A plain URL button opens StratForge in the normal browser.  It is
        # deliberately not a Web App button: the Mini App container is retired
        # and the bot must not be the way it comes back.
        open_url = _app_open_url()
        if open_url:
            payload["text"] = (
                "StratForge AI открывается в браузере — кнопкой ниже.\n\n"
                "Для входа нужна одноразовая ссылка из окна StratForge AI. "
                "Если браузер открыл Telegram без кода, вернитесь в приложение, нажмите "
                "«Начать заново» и введите здесь ручную команду вида /login ABCD1234."
            )
            payload["reply_markup"] = {"inline_keyboard": [[
                {"text": "🚀 Открыть StratForge", "url": open_url},
            ]]}
        api_call("sendMessage", payload)
        return True

    contact = message.get("contact")
    if isinstance(contact, dict):
        with _LOCK:
            doc = _read_doc()
            # Sending a contact still completes a login and still records the
            # phone identity -- it is simply no longer demanded on every login,
            # because the one-tap confirmation already proves the account.
            challenge = _challenge(
                doc, user_id=uid, statuses=("awaiting_contact", LOGIN_OPENED),
            )
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
            claim_is_owner = owner_claim(
                doc, provider="telegram", subject=uid,
                user_id=uid, user=user, owner_chat_id=owner_chat_id,
            )
            # Re-verifying the owner's own contact must be able to refresh a
            # stored number; it is the same person proving the same identity.
            owner_contact_refresh = bool(user and claim_is_owner)
            if (
                user and user.get("phone_hash")
                and not hmac.compare_digest(str(user.get("phone_hash")), _phone_hash(phone))
                and not owner_contact_refresh
            ):
                challenge["status"] = "phone_mismatch"
                _write_doc(doc)
                api_call("sendMessage", {"chat_id": uid, "text": "Номер не совпадает с аккаунтом. Вход отклонён.", "reply_markup": {"remove_keyboard": True}})
                return True
            if user is None:
                user = {
                    "user_id": uid, "legacy_user_id": uid,
                    "user_uuid": owner_user_uuid_for_new_row(claim_is_owner),
                    "telegram_user_id": uid,
                    "username": str(tg.get("username") or ""),
                    "first_name": str(tg.get("first_name") or ""), "last_name": str(tg.get("last_name") or ""),
                    "email": "", "phone": phone, "phone_hash": _phone_hash(phone),
                    "role": "read_only", "status": "pending", "is_owner": claim_is_owner,
                    "primary_login_provider": "telegram",
                    "created_at_utc": _now_iso(), "approved_at_utc": "", "revoked_at_utc": "",
                }
                if user["is_owner"]:
                    user.update({"role": "owner", "status": "active", "approved_at_utc": _now_iso()})
                doc["users"].append(user)
            else:
                user.update({
                    "username": str(tg.get("username") or user.get("username") or ""),
                    "phone": phone, "phone_hash": _phone_hash(phone), "phone_verified_at_utc": _now_iso(),
                    "telegram_user_id": uid,
                })
                if not user.get("first_name"):
                    user["first_name"] = str(tg.get("first_name") or "")
                if not user.get("last_name"):
                    user["last_name"] = str(tg.get("last_name") or "")
                if claim_is_owner and not user.get("is_owner"):
                    # An environment that could not name its owner earlier had
                    # already stored them as an ordinary verified human. Adopt
                    # the row rather than leaving the owner on a trial, and
                    # clear the registration-trial outbox that never applied.
                    user.update({
                        "role": "owner", "is_owner": True, "status": "active",
                        "approved_at_utc": user.get("approved_at_utc") or _now_iso(),
                        "revoked_at_utc": "",
                        "initial_trial_pending": False,
                        "updated_at_utc": _now_iso(),
                    })
            user["phone_verified_at_utc"] = _now_iso()
            _link_identity_in_doc(
                doc, user, provider="telegram", subject=str(uid),
                verified_at_utc=str(user.get("phone_verified_at_utc") or _now_iso()),
                metadata={"username": str(user.get("username") or "")},
                source="telegram_contact",
            )
            _sync_user_identity_summary(doc, user)
            challenge["user_uuid"] = _user_uuid(user)
            prior_status = str(user.get("status") or "")
            if user.get("status") in {"revoked", "denied", "blocked"}:
                # Owner explicitly removed access — re-verification does not restore it.
                challenge["status"] = "account_blocked"
            elif _profile_complete(user):
                _activate_verified_human_in_doc(user, source="telegram_contact")
                challenge["status"] = "login_approved"
            else:
                user["status"] = "pending"
                challenge["status"] = "awaiting_profile"
            _write_doc(doc)
            next_status = challenge["status"]
            cid = str(challenge["challenge_id"])
            newly_activated = next_status == "login_approved" and prior_status != "active"
            snapshot = dict(user)
        if snapshot.get("initial_trial_pending"):
            _ensure_registration_trial(snapshot, source="telegram_contact")
        if newly_activated and not snapshot.get("is_owner"):
            _notify_owner_new_user(api_call, owner_chat_id, snapshot)
        messages = {
            "awaiting_profile": "Телефон подтверждён. Вернитесь в приложение и заполните обязательные поля профиля.",
            # The owner has no trial and no preview to be granted, so they are
            # never told they were given one.
            "login_approved": (
                "Личность подтверждена. Вернитесь в приложение — полный доступ владельца."
                if snapshot.get("is_owner")
                else "Личность подтверждена. Вернитесь в приложение — открыт полный пробный доступ на 7 дней."
            ),
            "account_blocked": "Доступ к StratForge AI ограничен владельцем.",
        }
        api_call("sendMessage", {"chat_id": uid, "text": messages.get(next_status, "Готово."), "reply_markup": {"remove_keyboard": True}})
        _audit("contact_verified", user_id=uid)
        return True
    return False


def create_session_for_challenge(challenge_id: str, *, ip: str, user_agent: str,
                                 device_credential: str = "") -> Dict[str, Any]:
    with _LOCK:
        preflight_doc = _read_doc_reference()
        preflight_challenge = _challenge(
            preflight_doc,
            challenge_id=str(challenge_id or ""),
            statuses=("login_approved", "pending_owner"),
        )
        preflight_uid = int((preflight_challenge or {}).get("user_id") or 0)
    if preflight_uid:
        _ensure_pending_registration_trial(preflight_uid)
    with _LOCK:
        doc = _read_doc()
        challenge = _challenge(
            doc,
            challenge_id=str(challenge_id or ""),
            statuses=("login_approved", "pending_owner"),
        )
        if challenge is None:
            return login_state(challenge_id)
        uid = int(challenge.get("user_id") or 0)
        user = _user(doc, uid)
        if str(challenge.get("status") or "") == "pending_owner":
            if not user or user.get("status") != "active" or not _profile_complete(user):
                return login_state(challenge_id)
            # Compatibility for an approval completed from another concurrently
            # issued challenge for the same account.
            challenge["status"] = "login_approved"
        if not user or user.get("status") != "active" or not _profile_complete(user):
            raise AccountAuthError("Аккаунт ещё не активирован.", 403)
        provider = str(challenge.get("provider") or "").strip().lower()
        source = f"{provider}_login" if provider in auth_identity.LOGIN_PROVIDERS else "desktop_session"
        token = secrets.token_urlsafe(48)
        csrf = secrets.token_urlsafe(32)
        now = time.time()
        session = {
            "session_id": "sess_" + secrets.token_hex(8),
            "token_hash": hashlib.sha256(token.encode()).hexdigest(), "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(),
            "csrf_token": csrf,
            "user_id": uid, "user_uuid": _user_uuid(user),
            "created_at_utc": _now_iso(), "expires_at": now + SESSION_TTL_SEC,
            "normal_expires_at": now + SESSION_TTL_SEC,
            "ip_hash": hashlib.sha256(str(ip or "").encode()).hexdigest(),
            "ua_hash": hashlib.sha256(str(user_agent or "").encode()).hexdigest(), "revoked": False,
            "device_id": _device_id(user_agent, device_credential=device_credential),
            "client": _device_label(user_agent),
            "machine": _machine_label(), "ip": _mask_ip(ip),
            "source": source,
            "device_confirmation_exempt": False,
        }
        _stamp_identity_proof(session, source)
        doc["sessions"].append(session)
        challenge["status"] = "consumed"
        _append_login(user, source=source, ip=ip, user_agent=user_agent,
                      device_credential=device_credential)
        device_events = _observe_session_device(
            doc, session, user, ip=ip, user_agent=user_agent, source=source,
            device_credential=device_credential,
        )
        _cleanup(doc)
        _write_doc(doc)
    _audit("login_succeeded", user_id=uid, ip=ip)
    for _event, _extra in device_events:
        _audit(_event, user_id=uid, ip=ip, extra=_extra)
    access = _device_access_snapshot(session)
    return {
        "status": "authenticated",
        "session_token": token,
        "csrf_token": csrf,
        "user": _public_user(user, include_contact=True),
        "device_access": access,
        "session_cookie_persistent": access["trust_mode"] == "permanent",
    }


def _session_pending_deadline(session: Dict[str, Any]) -> float:
    deadline = float(session.get("pending_expires_at") or 0)
    if deadline:
        return deadline
    created = str(session.get("created_at_utc") or "").strip()
    try:
        created_at = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        created_at = 0.0
    if not created_at:
        return 0.0
    from . import security_devices
    return created_at + security_devices.PENDING_SESSION_TTL_SEC


def _session_confirmation_state(session: Dict[str, Any]) -> str:
    if session.get("device_confirmation_exempt"):
        return "active"
    # Sessions issued before the trusted-client registry existed have no
    # client UUID to confirm. Preserve them until their already-recorded expiry
    # instead of turning a rollout into an account-wide forced logout. Every
    # newly issued session goes through device observation and cannot take this
    # compatibility branch.
    if (not session.get("trusted_device_id")
            and "device_confirmation_state" not in session
            and "device_confirmation_required" not in session):
        return "active"
    explicit = str(session.get("device_confirmation_state") or "")
    if explicit == "active":
        return explicit
    if str(session.get("device_trust_status") or "") == "trusted":
        return "active"
    deadline = _session_pending_deadline(session)
    return "expired" if deadline and deadline <= time.time() else "pending"


def _device_access_snapshot(session: Dict[str, Any]) -> Dict[str, Any]:
    state = _session_confirmation_state(session)
    deadline = _session_pending_deadline(session) if state == "pending" else 0.0
    return {
        "required": state == "pending",
        "state": state,
        "trust_mode": str(session.get("device_trust_mode") or (
            "permanent" if str(session.get("device_trust_status") or "") == "trusted" else ""
        )),
        "session_id": _session_id(session),
        "client_id": str(session.get("trusted_device_id") or ""),
        "physical_device_id": str(session.get("physical_device_id") or ""),
        "pending_expires_at": deadline,
        "pending_expires_at_utc": (
            datetime.fromtimestamp(deadline, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            if deadline else ""
        ),
        "session_expires_at": float(session.get("expires_at") or 0),
    }


def _session_context(user: Dict[str, Any], session: Dict[str, Any]) -> Dict[str, Any]:
    """Build the public request context from one already-validated session."""
    ctx = {
        "source": str(session.get("source") or "desktop_session"),
        "user_id": int(user["user_id"]),
        "user_uuid": _user_uuid(user),
        "role": str(user.get("role") or "read_only"),
        "is_owner": bool(user.get("is_owner")),
        "username": str(user.get("username") or ""),
        "session_id": _session_id(session),
        "device_id": str(session.get("device_id") or ""),
        "csrf_hash": str(session.get("csrf_hash") or ""),
        "csrf_token": str(session.get("csrf_token") or ""),
        "trusted_device_id": str(session.get("trusted_device_id") or ""),
        "physical_device_id": str(session.get("physical_device_id") or ""),
        "device_confirmation_state": _session_confirmation_state(session),
        "device_confirmation_required": bool(
            not session.get("device_confirmation_exempt")
            and _session_confirmation_state(session) == "pending"
        ),
        "device_trust_mode": str(session.get("device_trust_mode") or ""),
        "pending_expires_at": _session_pending_deadline(session),
        "device_access": _device_access_snapshot(session),
        "user": _public_user(user, include_contact=True),
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


def _authenticate_authoritative_session(digest: str) -> Optional[Dict[str, Any]]:
    """Authenticate against the normalized PostgreSQL mirrors in one read.

    The old request path loaded and deep-copied the complete auth repository for
    every browser poll, then reconciled every user UUID before looking up one
    token.  The normalized mirrors are written in the same transaction as that
    document.  Reading the one session and user row therefore preserves the
    authoritative revoke, expiry and account-status checks without caching any
    security decision between requests.
    """
    from .production_storage import Scope, StorageError, get_client

    try:
        with get_client(production=True).transaction(
            Scope.global_service_scope(), read_only=True,
        ) as conn:
            row = conn.execute(
                """
                SELECT s.session_id, s.user_id, s.user_uuid,
                       EXTRACT(EPOCH FROM s.expires_at) AS expires_at_epoch,
                       s.document AS session_document,
                       u.user_uuid AS canonical_user_uuid,
                       u.status AS user_status, u.is_owner,
                       u.document AS user_document
                FROM sf_auth_sessions AS s
                JOIN sf_users AS u ON u.user_id=s.user_id
                WHERE s.token_hash=%s
                  AND s.revoked=FALSE
                  AND s.expires_at > clock_timestamp()
                  AND u.status='active'
                LIMIT 1
                """,
                (digest,),
            ).fetchone()
    except StorageError as exc:
        raise AccountAuthError(
            f"Production account repository unavailable ({exc.code}).",
            503, code=exc.code,
        ) from None
    if not row:
        return None
    raw_session = row.get("session_document")
    raw_user = row.get("user_document")
    if not isinstance(raw_session, dict) or not isinstance(raw_user, dict):
        raise AccountAuthError(
            "Production account session mirror returned invalid data.", 500,
            code="storage_constraint",
        )
    session = copy.deepcopy(raw_session)
    user = copy.deepcopy(raw_user)
    session.update({
        "session_id": str(row.get("session_id") or ""),
        "user_id": int(row.get("user_id") or 0),
        "user_uuid": str(row.get("user_uuid") or ""),
        "expires_at": float(row.get("expires_at_epoch") or 0),
        "revoked": False,
    })
    user.update({
        "user_id": int(row.get("user_id") or 0),
        "legacy_user_id": int(row.get("user_id") or 0),
        "user_uuid": str(row.get("canonical_user_uuid") or ""),
        "status": str(row.get("user_status") or ""),
        "is_owner": bool(row.get("is_owner")),
    })
    if _session_confirmation_state(session) == "expired":
        return None
    return _session_context(user, session)


def authenticate_session(token: str) -> Optional[Dict[str, Any]]:
    raw = str(token or "")
    if len(raw) < 40:
        return None
    digest = hashlib.sha256(raw.encode()).hexdigest()
    if _authoritative_storage():
        return _authenticate_authoritative_session(digest)
    with _LOCK:
        doc = _read_doc()
        now = time.time()
        session = next((row for row in doc["sessions"] if not row.get("revoked") and float(row.get("expires_at") or 0) > now and hmac.compare_digest(str(row.get("token_hash") or ""), digest)), None)
        if session is None:
            return None
        if _session_confirmation_state(session) == "expired":
            return None
        user = _user(doc, int(session.get("user_id") or 0))
        if not user or user.get("status") != "active":
            return None
        return _session_context(user, session)


def local_session_is_active(session_id: str, user_id: Any) -> bool:
    """Revalidate a previously admitted Local worker without persisting tokens.

    This is a read-only lease check, never authentication or session creation.
    PostgreSQL-backed environments use their own authority and fail closed here.
    """
    if not runtime_env.is_development() or _authoritative_storage():
        return False
    sid = str(session_id or "")
    if not sid or len(sid) > 80:
        return False
    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        return False
    with _LOCK:
        doc = _read_doc()
        user = _user(doc, uid)
        if not user or user.get("status") != "active":
            return False
        return any(_session_id(row) == sid and int(row.get("user_id") or 0) == uid
                   and not row.get("revoked") and float(row.get("expires_at") or 0) > time.time()
                   and _session_confirmation_state(row) == "active" for row in doc.get("sessions", []))


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
        telegram_id = _telegram_subject_for_user(doc, user)
        if not user.get("is_owner") and not telegram_id:
            raise AccountAuthError(
                "Для подтверждения NinjaTrader сначала привяжите Telegram.",
                403,
                code="nt_telegram_link_required",
            )
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
            "user_uuid": _user_uuid(user),
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
                "chat_id": telegram_id,
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
            if _session_confirmation_state(row) == "expired":
                return {
                    "code": "device_confirmation_expired",
                    "error": "Время подтверждения доступа истекло. Войдите снова.",
                    "user_id": int(row.get("user_id") or 0),
                }
            if row.get("revoked") and row.get("revoked_reason") in _REVOKE_NOTICE_REASONS:
                notice_until = float(row.get("revoke_notice_until") or 0)
                if notice_until and notice_until < now:
                    return None
                reason = str(row.get("revoked_reason") or "")
                if reason in {"device_revoked", "device_rejected"}:
                    return {
                        "code": "session_device_revoked",
                        "error": "Устройство отозвано. Сессия завершена.",
                        "revoked_at_utc": str(row.get("revoked_at_utc") or ""),
                        "user_id": int(row.get("user_id") or 0),
                    }
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
    if _authoritative_storage():
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
    identity = _identity(doc, "google", sub)
    if identity is not None:
        return _user_by_uuid(doc, identity.get("user_uuid"))
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
        _link_identity_in_doc(
            doc,
            user,
            provider="google",
            subject=sub,
            verified_at_utc=str(user.get("google_linked_at_utc") or _now_iso()),
            metadata={"email": email, "name": str(google_name or "")[:120]},
            source=source,
        )
        _sync_user_identity_summary(doc, user)
        if email and not str(user.get("email") or "").strip():
            user["email"] = email
        _write_doc(doc)
        public = _public_user(user, include_contact=True)
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
        identities = _identities_for_user(doc, user)
        remaining_login = [
            row for row in identities
            if str(row.get("provider") or "") in auth_identity.LOGIN_PROVIDERS
            and str(row.get("provider") or "") != "google"
        ]
        if not remaining_login:
            raise AccountAuthError("Нельзя удалить последний способ входа.", 409)
        canonical = _user_uuid(user)
        doc["auth_identities"] = [
            row for row in _identity_rows(doc)
            if not (
                isinstance(row, dict)
                and hmac.compare_digest(auth_identity.normalize_user_uuid(row.get("user_uuid")), canonical)
                and str(row.get("provider") or "") == "google"
            )
        ]
        user["google_sub"] = ""
        user["google_email"] = ""
        user["google_name"] = ""
        user["google_linked_at_utc"] = ""
        user["google_unlinked_at_utc"] = _now_iso()
        _sync_user_identity_summary(doc, user)
        _write_doc(doc)
        public = _public_user(user, include_contact=True)
    _audit("google_unlinked", user_id=uid, owner_id=int(owner_id))
    return {"ok": True, "user": public}


def list_account_identities(user_id: Any) -> Dict[str, Any]:
    """Self-service: the caller's own linked login methods (masked)."""
    uid = int(user_id or 0)
    with _LOCK:
        doc = _read_doc()
        user = _user(doc, uid)
        if user is None:
            raise AccountAuthError("Пользователь не найден.", 404)
        rows = [
            auth_identity.public_identity(row, user=user)
            for row in _identities_for_user(doc, user)
        ]
    return {"ok": True, "identities": rows}


def unlink_identity_self(user_id: Any, *, identity_id: str) -> Dict[str, Any]:
    """Self-service unlink of one of the caller's own login methods.

    Ownership is enforced by canonical UUID: an ``identity_id`` that does not
    belong to this account is simply not found. The last usable login method can
    never be removed.
    """
    uid = int(user_id or 0)
    target = str(identity_id or "").strip()
    if not target:
        raise AccountAuthError("Не указан способ входа.", 400, code="identity_required")
    with _LOCK:
        doc = _read_doc()
        user = _user(doc, uid)
        if user is None:
            raise AccountAuthError("Пользователь не найден.", 404)
        canonical = _user_uuid(user)
        identities = _identities_for_user(doc, user)
        row = next(
            (r for r in identities if hmac.compare_digest(str(r.get("identity_id") or ""), target)),
            None,
        )
        if row is None:
            raise AccountAuthError("Способ входа не найден.", 404, code="identity_not_found")
        provider = str(row.get("provider") or "")
        remaining_login = [
            r for r in identities
            if str(r.get("provider") or "") in auth_identity.LOGIN_PROVIDERS
            and not hmac.compare_digest(str(r.get("identity_id") or ""), target)
        ]
        if not remaining_login:
            raise AccountAuthError(
                "Нельзя удалить последний способ входа.", 409, code="last_login_method",
            )
        doc["auth_identities"] = [
            r for r in _identity_rows(doc)
            if not (
                isinstance(r, dict)
                and hmac.compare_digest(str(r.get("identity_id") or ""), target)
                and hmac.compare_digest(auth_identity.normalize_user_uuid(r.get("user_uuid")), canonical)
            )
        ]
        if provider == "google":
            user["google_sub"] = ""
            user["google_email"] = ""
            user["google_name"] = ""
            user["google_linked_at_utc"] = ""
            user["google_unlinked_at_utc"] = _now_iso()
        _sync_user_identity_summary(doc, user)
        _write_doc(doc)
        public = _public_user(user, include_contact=True)
    _audit("identity_unlinked", user_id=uid, extra={"provider": provider, "identity_id": target})
    return {"ok": True, "user": public, "provider": provider}


# Sources whose handshake proves the person's identity at the moment the
# session is created: Telegram approval, Google sign-in, an e-mail one-time
# code, or the code spent to finish registration. A session from one of these
# carries the proof for a short while, and the first device confirmation may
# lean on it instead of asking for a second code minutes later.
IDENTITY_VERIFIED_SOURCES = frozenset({
    "telegram_login", "telegram_qr_login", "google_login",
    "email_otp_login", "email_otp_link", "email_verified_registration",
    "registration",
})


def _stamp_identity_proof(row: Dict[str, Any], source: str) -> None:
    """Record when and how this session proved the identity behind it."""
    name = str(source or "").strip().lower()
    # Every provider handshake ends in a "<provider>_login" source; the explicit
    # set covers the registration paths that spell their source differently.
    if not name.endswith("_login") and name not in IDENTITY_VERIFIED_SOURCES:
        return
    row["identity_verified_at_utc"] = _now_iso()
    row["identity_provider"] = name.split("_", 1)[0]


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
    device_credential: str = "",
    device_confirmation_required: bool = True,
) -> Dict[str, Any]:
    uid = int(user_id)
    if not impersonator_owner_id:
        _ensure_pending_registration_trial(uid)
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
            "user_uuid": _user_uuid(user),
            "created_at_utc": _now_iso(),
            "expires_at": now + ttl,
            "normal_expires_at": now + ttl,
            "ip_hash": hashlib.sha256(str(ip or "").encode()).hexdigest(),
            "ua_hash": hashlib.sha256(str(user_agent or "").encode()).hexdigest(),
            "revoked": False,
            "device_id": _device_id(user_agent, device_credential=device_credential),
            "client": _device_label(user_agent),
            "machine": _machine_label(),
            "ip": _mask_ip(ip),
            "source": str(source or "desktop_session")[:40],
            "device_confirmation_exempt": not bool(device_confirmation_required),
        }
        _stamp_identity_proof(row, str(source or ""))
        if impersonator_owner_id:
            row["impersonator_owner_id"] = int(impersonator_owner_id)
            row["impersonation_started_at_utc"] = _now_iso()
            row["impersonation_preset"] = str(impersonation_preset or "")[:40]
        doc["sessions"].append(row)
        _append_login(user, source=str(source or "desktop_session"), ip=ip,
                      user_agent=user_agent, device_credential=device_credential)
        device_events = _observe_session_device(
            doc, row, user, ip=ip, user_agent=user_agent,
            source=str(source or "desktop_session"),
            device_credential=device_credential,
        )
        _cleanup(doc)
        _write_doc(doc)
        public = _public_user(user, include_contact=True)
    _audit(
        "impersonation_started" if impersonator_owner_id else "login_succeeded",
        user_id=uid,
        owner_id=int(impersonator_owner_id or 0),
        ip=ip,
        extra={"source": source},
    )
    for _event, _extra in device_events:
        _audit(_event, user_id=uid, ip=ip, extra=_extra)
    access = _device_access_snapshot(row)
    return {
        "status": "authenticated",
        "session_token": token,
        "csrf_token": csrf,
        "user": public,
        "device_access": access,
        "session_cookie_persistent": access["trust_mode"] == "permanent",
        "needs_google": user_needs_google(user),
        "impersonating": bool(impersonator_owner_id),
    }


EMAIL_PROVIDER_RESEND = "resend"
_RESEND_ENDPOINT = "https://api.resend.com/emails"
_RESEND_USER_AGENT = "StratForge-Auth/1 (+https://app.stratforges.com)"


def _resend_api_key() -> str:
    """Platform secret, from the external per-environment store."""
    from . import platform_secrets
    try:
        return platform_secrets.get("NTA_RESEND_API_KEY").strip()
    except platform_secrets.PlatformSecretError:
        return ""


def _email_provider_config() -> Dict[str, str]:
    return {
        "provider": str(os.environ.get("NTA_EMAIL_AUTH_PROVIDER") or "").strip().lower(),
        "api_key": _resend_api_key(),
        "sender": str(os.environ.get("NTA_EMAIL_AUTH_FROM") or "").strip(),
    }


def _email_provider_live() -> bool:
    cfg = _email_provider_config()
    return bool(
        cfg["provider"] == EMAIL_PROVIDER_RESEND and cfg["api_key"] and cfg["sender"]
    )


def email_auth_status() -> Dict[str, Any]:
    test_backend = bool(runtime_env.is_development() and runtime_env.test_auth_enabled())
    configured_provider = str(os.environ.get("NTA_EMAIL_AUTH_PROVIDER") or "").strip().lower()
    if _email_provider_live():
        # A configured transactional provider wins over the Development test
        # backend so a real code is delivered instead of being disclosed.
        return {
            "available": True,
            "operational": True,
            "provider": EMAIL_PROVIDER_RESEND,
            "test_backend": False,
            "production_ready": True,
            "code": "ok",
        }
    return {
        "available": test_backend,
        "operational": test_backend,
        "provider": (
            "preview_synthetic" if runtime_env.preview_sandbox_enabled()
            else "development_test"
        ) if test_backend else (configured_provider or "unconfigured"),
        "test_backend": test_backend,
        "production_ready": False,
        "code": "ok" if test_backend else "transactional_provider_not_configured",
    }


_EMAIL_CODE_ACTIONS = {
    "link": "привязки e-mail",
    "login": "входа в StratForge",
    # Step-up purposes owned by ``security_devices``.
    "device_confirm": "подтверждения нового устройства в StratForge",
    "step_up": "подтверждения действия в StratForge",
    "revoke": "отзыва устройства в StratForge",
}


def _email_code_message(code: str, purpose: str, *, ttl_sec: int = 0) -> Tuple[str, str, str]:
    action = _EMAIL_CODE_ACTIONS.get(str(purpose or ""), "входа в StratForge")
    subject = f"StratForge: код {code}"
    minutes = max(1, int(ttl_sec or EMAIL_CHALLENGE_TTL_SEC) // 60)
    text = (
        f"Код для {action}: {code}\n\n"
        f"Код действителен {minutes} минут и используется один раз.\n"
        "Если вы не запрашивали этот код, просто проигнорируйте письмо."
    )
    body = html.escape(text).replace("\n", "<br>")
    return subject, text, f"<div style=\"font-family:system-ui,sans-serif\">{body}</div>"


def _deliver_email_code(
    recipient: str, code: str, *, purpose: str, ttl_sec: int = 0,
    send: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Send the one-time code through the configured transactional provider."""
    cfg = _email_provider_config()
    subject, text, html_body = _email_code_message(code, purpose, ttl_sec=ttl_sec)
    payload = {
        "from": cfg["sender"],
        "to": [recipient],
        "subject": subject,
        "text": text,
        "html": html_body,
    }
    def _post(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        import urllib.error
        import urllib.request

        request = urllib.request.Request(
            _RESEND_ENDPOINT,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {cfg['api_key']}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Cloudflare fronts api.resend.com and rejects the default
                # Python-urllib agent with error 1010 before Resend sees the
                # request, so the client must identify itself explicitly.
                "User-Agent": _RESEND_USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8", "replace")
                status = int(response.status)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace") if exc.fp else ""
            status = int(exc.code)
        try:
            return status, json.loads(raw)
        except Exception:
            return status, {}

    # Any transport failure becomes one service error.  Provider responses and
    # exception messages can echo the API key, so nothing from them reaches the
    # caller — the audit log records the outcome instead.
    try:
        if send is not None:
            status, document = 200, send(payload)
        else:
            status, document = _post(payload)
    except Exception:
        raise AccountAuthError(
            "Не удалось отправить код на e-mail. Повторите попытку позже.",
            503,
            code="email_delivery_failed",
        ) from None
    if status >= 300 or not isinstance(document, dict) or not document.get("id"):
        raise AccountAuthError(
            "Не удалось отправить код на e-mail. Повторите попытку позже.",
            503,
            code="email_delivery_failed",
        )
    return {"provider": EMAIL_PROVIDER_RESEND, "message_id": str(document.get("id") or "")}


def _email_code_hash(challenge_id: str, salt: str, code: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        str(code or "").encode("ascii", errors="ignore"),
        (str(challenge_id) + ":" + str(salt)).encode("utf-8"),
        120_000,
    ).hex()


def start_email_auth(
    email: Any,
    *,
    ip: str,
    user_agent: str = "",
    purpose: str = "login",
    actor_user_id: Any = 0,
) -> Dict[str, Any]:
    status = email_auth_status()
    if not status["available"]:
        raise AccountAuthError(
            "Email login недоступен: transactional provider не настроен.",
            503,
            code="email_provider_unavailable",
        )
    _login_rate(ip)
    normalized = _valid_email(email)
    purpose_id = str(purpose or "login").strip().lower()
    if purpose_id not in {"login", "link"}:
        raise AccountAuthError("Недопустимая цель email challenge.")
    try:
        actor_id = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor_id = 0
    if purpose_id == "link" and actor_id <= 0:
        raise AccountAuthError("Для привязки email требуется активная сессия.", 401)
    challenge_id = secrets.token_urlsafe(24)
    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(16)
    magic_token = secrets.token_urlsafe(32)
    with _LOCK:
        doc = _read_doc()
        _cleanup(doc)
        actor = _user(doc, actor_id) if actor_id else None
        if purpose_id == "link" and (not actor or actor.get("status") != "active"):
            raise AccountAuthError("Аккаунт для привязки email не активен.", 403)
        doc["challenges"].append({
            "challenge_id": challenge_id,
            "kind": "provider_auth",
            "provider": "email",
            "purpose": purpose_id,
            "provider_subject": normalized,
            "status": "email_code_sent",
            "user_id": actor_id or None,
            "user_uuid": _user_uuid(actor) if actor else "",
            "code_salt": salt,
            "code_hash": _email_code_hash(challenge_id, salt, code),
            "magic_token_hash": hashlib.sha256(magic_token.encode("utf-8")).hexdigest(),
            "attempts": 0,
            "created_at_utc": _now_iso(),
            "expires_at": time.time() + EMAIL_CHALLENGE_TTL_SEC,
            "ip_hash": hashlib.sha256(str(ip or "").encode()).hexdigest(),
            "ua_hash": hashlib.sha256(str(user_agent or "").encode()).hexdigest(),
        })
        _write_doc(doc)
    delivery = (
        "preview_synthetic" if runtime_env.preview_sandbox_enabled()
        else "development_test"
    )
    message_id = ""
    if _email_provider_live():
        receipt = _deliver_email_code(normalized, code, purpose=purpose_id)
        delivery = str(receipt.get("provider") or EMAIL_PROVIDER_RESEND)
        message_id = str(receipt.get("message_id") or "")
    _audit(
        "email_auth_started",
        user_id=actor_id,
        ip=ip,
        extra={
            "purpose": purpose_id,
            "email_hash": hashlib.sha256(normalized.encode()).hexdigest(),
            "delivery": delivery,
            "message_id": message_id,
        },
    )
    out = {
        "ok": True,
        "challenge_id": challenge_id,
        "status": "email_code_sent",
        "expires_in_sec": EMAIL_CHALLENGE_TTL_SEC,
        "delivery": delivery,
    }
    if delivery in {"development_test", "preview_synthetic"}:
        # Test credentials are disclosed only behind the explicit Development
        # test auth gate. A real provider delivers them out-of-band instead.
        out["test_code"] = code
        out["test_magic_token"] = magic_token
    return out


def _email_challenge_verified(
    challenge: Dict[str, Any], *, code: Any = "", magic_token: Any = "",
) -> bool:
    supplied_magic = str(magic_token or "").strip()
    if supplied_magic:
        return hmac.compare_digest(
            str(challenge.get("magic_token_hash") or ""),
            hashlib.sha256(supplied_magic.encode("utf-8")).hexdigest(),
        )
    supplied_code = str(code or "").strip()
    if not re.fullmatch(r"[0-9]{6}", supplied_code):
        return False
    expected = _email_code_hash(
        str(challenge.get("challenge_id") or ""),
        str(challenge.get("code_salt") or ""),
        supplied_code,
    )
    return hmac.compare_digest(str(challenge.get("code_hash") or ""), expected)


def _new_external_user(
    doc: Dict[str, Any], *, provider: str, first_name: str, last_name: str,
    email: str,
) -> Dict[str, Any]:
    legacy_id = _allocate_external_legacy_user_id(doc)
    now = _now_iso()
    user = {
        "user_id": legacy_id,
        "legacy_user_id": legacy_id,
        "user_uuid": auth_identity.new_user_uuid(),
        "username": "",
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "email_verified_at_utc": now,
        "phone": "",
        "phone_hash": "",
        "role": "read_only",
        "status": "pending",
        "is_owner": False,
        "primary_login_provider": provider,
        "identity_verified_via": provider,
        "created_at_utc": now,
        "approved_at_utc": "",
        "revoked_at_utc": "",
        "terms_accepted_at_utc": now,
        "terms_version": legal.TERMS_VERSION,
        "terms_digest": legal.TERMS_DIGEST,
    }
    if runtime_env.preview_sandbox_enabled():
        # The Preview process owns a separate data root and can never become an
        # owner.  Persist an explicit marker as defence in depth and for visual
        # audit evidence; this field is never inferred from client input.
        user.update({
            "is_virtual": True,
            "is_preview_user": True,
            "virtual_preset": "preview_sandbox",
            "preview_sandbox_id": str(
                os.environ.get("STRATFORGE_PREVIEW_ID") or ""
            )[:48],
        })
    _activate_verified_human_in_doc(user, source=f"{provider}_verified_registration")
    doc["users"].append(user)
    return user


def verify_email_auth(
    challenge_id: Any,
    *,
    code: Any = "",
    magic_token: Any = "",
    profile: Optional[Dict[str, Any]] = None,
    ip: str,
    user_agent: str = "",
    actor_user_id: Any = 0,
    api_call: Optional[Callable[..., Any]] = None,
    owner_chat_id: str = "",
    device_credential: str = "",
) -> Dict[str, Any]:
    profile = profile if isinstance(profile, dict) else {}
    cid = str(challenge_id or "")
    try:
        actor_id = int(actor_user_id or 0)
    except (TypeError, ValueError):
        actor_id = 0
    notify: Optional[Tuple[Dict[str, Any], str]] = None
    active_uid = 0
    verified_uid = 0
    with _LOCK:
        doc = _read_doc()
        challenge = _challenge(doc, challenge_id=cid, statuses=("email_code_sent",))
        if challenge is None or str(challenge.get("provider") or "") != "email":
            raise AccountAuthError("Email challenge истёк или уже использован.", 410)
        challenge["attempts"] = int(challenge.get("attempts") or 0) + 1
        if challenge["attempts"] > EMAIL_MAX_ATTEMPTS or not _email_challenge_verified(
            challenge, code=code, magic_token=magic_token,
        ):
            if challenge["attempts"] >= EMAIL_MAX_ATTEMPTS:
                challenge["status"] = "denied"
            _write_doc(doc)
            raise AccountAuthError("Неверный или истёкший email code.", 401, code="email_code_invalid")
        email = auth_identity.normalize_subject("email", challenge.get("provider_subject"))
        purpose = str(challenge.get("purpose") or "login")
        if purpose == "link":
            expected_actor = int(challenge.get("user_id") or 0)
            if actor_id <= 0 or actor_id != expected_actor:
                raise AccountAuthError("Чужой email link challenge.", 403)
            user = _user(doc, actor_id)
            if not user or user.get("status") != "active":
                raise AccountAuthError("Аккаунт не активен.", 403)
            _link_identity_in_doc(
                doc, user, provider="email", subject=email,
                verified_at_utc=_now_iso(), metadata={"email": email}, source="email_otp_link",
            )
            user["email_verified_at_utc"] = _now_iso()
            if not str(user.get("email") or "").strip():
                user["email"] = email
            _sync_user_identity_summary(doc, user)
            challenge["status"] = "consumed"
            _write_doc(doc)
            public = _public_user(user, include_contact=True)
            _audit("email_linked", user_id=actor_id, ip=ip)
            return {"ok": True, "status": "linked", "user": public}

        identity = _identity(doc, "email", email)
        user = _user_by_uuid(doc, identity.get("user_uuid")) if identity else None
        if user is None:
            if not bool(profile.get("accept_terms")):
                raise AccountAuthError("Необходимо принять условия использования.")
            first_name = _clean_name(profile.get("first_name"), "Имя")
            last_name = _clean_name(profile.get("last_name"), "Фамилия")
            user = _new_external_user(
                doc, provider="email", first_name=first_name,
                last_name=last_name, email=email,
            )
            _link_identity_in_doc(
                doc, user, provider="email", subject=email,
                verified_at_utc=_now_iso(), metadata={"email": email}, source="email_otp_login",
            )
            notify = (dict(user), cid)
        elif user.get("status") in {"revoked", "denied", "blocked", "deleted"}:
            challenge["status"] = "account_blocked"
            _write_doc(doc)
            raise AccountAuthError("Доступ к аккаунту ограничен владельцем.", 403)
        else:
            _link_identity_in_doc(
                doc, user, provider="email", subject=email,
                verified_at_utc=_now_iso(), metadata={"email": email}, source="email_otp_login",
            )
            user["email_verified_at_utc"] = user.get("email_verified_at_utc") or _now_iso()
        challenge["user_id"] = int(user.get("user_id") or 0)
        challenge["user_uuid"] = _user_uuid(user)
        verified_uid = int(user.get("user_id") or 0)
        _sync_user_identity_summary(doc, user)
        if user.get("status") == "pending" and _profile_complete(user):
            _activate_verified_human_in_doc(user, source="email_verified_registration")
        if user.get("status") == "active":
            challenge["status"] = "login_approved"
            active_uid = int(user.get("user_id") or 0)
        else:
            challenge["status"] = "pending_owner"
            challenge["expires_at"] = time.time() + OWNER_APPROVAL_TTL_SEC
        public = _public_user(user, include_contact=True)
        registration_snapshot = dict(user)
        _write_doc(doc)
    if registration_snapshot.get("initial_trial_pending"):
        _ensure_registration_trial(registration_snapshot, source="email_verified_registration")
    if notify and api_call is not None:
        try:
            _notify_owner_new_user(api_call, owner_chat_id, notify[0])
        except Exception:
            pass
    if active_uid:
        return create_session_for_challenge(
            cid, ip=ip, user_agent=user_agent, device_credential=device_credential,
        )
    _audit("email_identity_verified", user_id=verified_uid, ip=ip)
    state = login_state(cid)
    state["user"] = public
    return state


# --------------------------------------------------------------------------- #
# Staged registration: identity first, consent and account creation last.
# --------------------------------------------------------------------------- #
REGISTRATION_TTL_SEC = 15 * 60


def stage_google_registration(
    *, google_sub: Any, google_email: Any, google_name: Any = "",
    email_verified: bool, ip: str = "", user_agent: str = "",
) -> Dict[str, Any]:
    """Hold a verified Google identity until the person accepts the terms.

    Sign-up must not create an account the moment Google answers: consent is
    the last step of registration, so the verified identity waits in the same
    short-lived, single-use challenge store the other providers use.
    """
    sub = str(google_sub or "").strip()
    if not sub:
        raise AccountAuthError("Google identity не содержит subject.", 400)
    if not email_verified:
        raise AccountAuthError("Email Google не подтверждён.", 403)
    email = _valid_email(google_email)
    registration_id = secrets.token_urlsafe(24)
    with _LOCK:
        doc = _read_doc()
        _cleanup(doc)
        if _identity(doc, "google", sub):
            raise AccountAuthError(
                "Этот Google-аккаунт уже зарегистрирован.", 409, code="google_already_registered",
            )
        doc["challenges"].append({
            "challenge_id": registration_id,
            "status": "awaiting_registration",
            "purpose": "google_registration",
            "provider": "google",
            "provider_subject": sub,
            "google_email": email,
            "google_name": str(google_name or "")[:120],
            "environment": runtime_env.deployment_environment(),
            "created_at_utc": _now_iso(),
            "expires_at": time.time() + REGISTRATION_TTL_SEC,
            "ip_hash": hashlib.sha256(str(ip or "").encode()).hexdigest(),
            "ua_hash": hashlib.sha256(str(user_agent or "").encode()).hexdigest(),
        })
        _write_doc(doc)
    _audit("google_registration_staged", ip=ip)
    return {
        "registration_id": registration_id,
        "provider": "google",
        "email": email,
        "name": str(google_name or "")[:120],
        "expires_in_sec": REGISTRATION_TTL_SEC,
    }


def registration_state(registration_id: Any) -> Dict[str, Any]:
    """What the final registration step may show about a staged identity."""
    cid = str(registration_id or "")
    with _LOCK:
        doc = _read_doc()
        challenge = _challenge(
            doc, challenge_id=cid, statuses=("awaiting_registration",),
        )
    if challenge is None:
        raise AccountAuthError(
            "Подтверждение личности истекло. Начните регистрацию заново.",
            410, code="registration_expired",
        )
    email = str(challenge.get("google_email") or "")
    return {
        "registration_id": cid,
        "provider": str(challenge.get("provider") or ""),
        "email": email,
        "name": str(challenge.get("google_name") or ""),
        "suggested_handle": suggest_handle(email=email, name=challenge.get("google_name")),
    }


def _finish_google_registration(
    registration_id: str, *, handle: str, first_name: str, last_name: str,
    ip: str, user_agent: str, api_call: Optional[Callable[..., Any]],
    owner_chat_id: str, device_credential: str,
) -> Dict[str, Any]:
    with _LOCK:
        doc = _read_doc()
        challenge = _challenge(
            doc, challenge_id=registration_id, statuses=("awaiting_registration",),
        )
        if challenge is None or str(challenge.get("provider") or "") != "google":
            raise AccountAuthError(
                "Подтверждение личности истекло. Начните регистрацию заново.",
                410, code="registration_expired",
            )
        # Single use: the staged identity is spent before the account exists,
        # so a replayed request cannot create a second account.
        challenge["status"] = "consumed"
        google_sub = str(challenge.get("provider_subject") or "")
        google_email = str(challenge.get("google_email") or "")
        google_name = str(challenge.get("google_name") or "")
        _write_doc(doc)
    out = login_via_google_identity(
        google_sub=google_sub,
        google_email=google_email,
        google_name=google_name or f"{first_name} {last_name}".strip(),
        email_verified=True,
        accept_terms=True,
        ip=ip,
        user_agent=user_agent,
        api_call=api_call,
        owner_chat_id=owner_chat_id,
        device_credential=device_credential,
    )
    with _LOCK:
        doc = _read_doc()
        user = _user_by_uuid(doc, str((out.get("user") or {}).get("id") or ""))
        if user is not None:
            user["first_name"] = first_name
            user["last_name"] = last_name
            _assign_handle_in_doc(doc, user, handle)
            _write_doc(doc)
            out["user"] = _public_user(user, include_contact=True)
    return out


def complete_registration(
    *,
    method: Any,
    challenge_id: Any,
    handle: Any,
    first_name: Any,
    last_name: Any = "",
    code: Any = "",
    email: Any = "",
    accept_terms: bool = False,
    ip: str = "",
    user_agent: str = "",
    api_call: Optional[Callable[..., Any]] = None,
    owner_chat_id: str = "",
    device_credential: str = "",
) -> Dict[str, Any]:
    """Create the account only after the person has seen and accepted terms.

    Identity verification (Telegram, Google, e-mail code) has already happened
    in the previous step; this is the single call every registration method
    ends with, so consent and the StratForge handle are always applied to the
    account that is being created.
    """
    provider = str(method or "").strip().lower()
    if provider not in {"email", "telegram", "google"}:
        raise AccountAuthError("Неизвестный способ регистрации.", 400, code="method_invalid")
    if not accept_terms:
        raise AccountAuthError(
            "Необходимо принять условия использования.", 400, code="terms_required",
        )
    wanted_handle = normalize_handle(handle)
    probe = handle_available(wanted_handle)
    if not probe["available"]:
        raise AccountAuthError(
            probe["reason"] or "Это имя пользователя уже занято.",
            409, code=probe["code"] or "handle_taken",
        )
    clean_first = _clean_name(first_name, "Имя")
    # A family name is optional for the person; the account model still wants a
    # value, so an omitted one is stored as an explicit dash rather than a
    # guess derived from the login provider.
    clean_last = _clean_name(last_name, "Фамилия") if str(last_name or "").strip() else "—"
    cid = str(challenge_id or "")

    if provider == "google":
        return _finish_google_registration(
            cid, handle=wanted_handle, first_name=clean_first, last_name=clean_last,
            ip=ip, user_agent=user_agent, api_call=api_call,
            owner_chat_id=owner_chat_id, device_credential=device_credential,
        )

    if provider == "email":
        try:
            out = verify_email_auth(
                cid,
                code=str(code or ""),
                profile={
                    "first_name": clean_first,
                    "last_name": clean_last,
                    "accept_terms": True,
                },
                ip=ip, user_agent=user_agent, api_call=api_call,
                owner_chat_id=owner_chat_id, device_credential=device_credential,
            )
        except AccountAuthError as exc:
            if exc.status == 410:
                # Match the staged-provider contract: the final screen can
                # return to verification instead of retrying a spent proof.
                # Do not refresh the OTP TTL or consume/accept anything here.
                raise AccountAuthError(
                    "Код подтверждения e-mail истёк или уже использован. Запросите новый код.",
                    410, code="registration_expired",
                ) from exc
            raise
    else:
        out = complete_profile(
            cid,
            {
                "first_name": clean_first,
                "last_name": clean_last,
                "email": email,
                "accept_terms": True,
            },
            api_call=api_call, owner_chat_id=owner_chat_id,
            ip=ip, user_agent=user_agent,
        )
        # The legacy profile endpoint intentionally leaves the approved
        # challenge for its polling browser.  The rebuilt consolidated
        # registration endpoint, however, must finish the same challenge and
        # return the authenticated session just like e-mail and Google do.
        if str(out.get("status") or "") == "login_approved":
            out = create_session_for_challenge(
                cid,
                ip=ip,
                user_agent=user_agent,
                device_credential=device_credential,
            )

    canonical = str((out.get("user") or {}).get("id") or "")
    with _LOCK:
        doc = _read_doc()
        user = _user_by_uuid(doc, canonical) if canonical else None
        if user is None:
            challenge = _challenge(doc, challenge_id=cid)
            user = _user(doc, int((challenge or {}).get("user_id") or 0))
        if user is not None:
            _assign_handle_in_doc(doc, user, wanted_handle)
            _write_doc(doc)
            out["user"] = _public_user(user, include_contact=True)
    return out


def login_via_google_identity(
    *,
    google_sub: Any,
    google_email: Any,
    google_name: Any = "",
    email_verified: bool,
    accept_terms: bool,
    ip: str,
    user_agent: str = "",
    api_call: Optional[Callable[..., Any]] = None,
    owner_chat_id: str = "",
    device_credential: str = "",
) -> Dict[str, Any]:
    sub = str(google_sub or "").strip()
    if not sub:
        raise AccountAuthError("Google identity не содержит subject.", 400)
    if not email_verified:
        raise AccountAuthError("Email Google не подтверждён.", 403)
    email = _valid_email(google_email)
    notify: Optional[Tuple[Dict[str, Any], str]] = None
    active_uid = 0
    with _LOCK:
        doc = _read_doc()
        identity = _identity(doc, "google", sub)
        user = _user_by_uuid(doc, identity.get("user_uuid")) if identity else None
        if user is None:
            if not accept_terms:
                raise AccountAuthError("Необходимо принять условия использования.")
            parts = " ".join(str(google_name or "").strip().split()).split(" ")
            local = email.split("@", 1)[0]
            first_name = _clean_name(parts[0] if parts and parts[0] else local, "Имя")
            last_name = _clean_name(" ".join(parts[1:]) if len(parts) > 1 else "—", "Фамилия")
            user = _new_external_user(
                doc, provider="google", first_name=first_name,
                last_name=last_name, email=email,
            )
            user["google_sub"] = sub
            user["google_email"] = email
            user["google_name"] = str(google_name or "")[:120]
            user["google_linked_at_utc"] = _now_iso()
            user["google_link_source"] = "google_login"
            _link_identity_in_doc(
                doc, user, provider="google", subject=sub,
                verified_at_utc=_now_iso(),
                metadata={"email": email, "name": str(google_name or "")[:120]},
                source="google_login",
            )
            challenge_id = ""
            active_uid = int(user["user_id"])
            notify = (dict(user), challenge_id)
        elif user.get("status") in {"revoked", "denied", "blocked", "deleted"}:
            raise AccountAuthError("Доступ к аккаунту ограничен владельцем.", 403)
        else:
            user["google_sub"] = sub
            user["google_email"] = email
            user["google_name"] = str(google_name or user.get("google_name") or "")[:120]
            user["google_linked_at_utc"] = user.get("google_linked_at_utc") or _now_iso()
            user["email_verified_at_utc"] = user.get("email_verified_at_utc") or _now_iso()
            _link_identity_in_doc(
                doc, user, provider="google", subject=sub,
                verified_at_utc=_now_iso(),
                metadata={"email": email, "name": str(google_name or "")[:120]},
                source="google_login",
            )
            if user.get("status") == "pending" and _profile_complete(user):
                _activate_verified_human_in_doc(user, source="google_verified_registration")
            if user.get("status") == "active":
                active_uid = int(user.get("user_id") or 0)
                challenge_id = ""
            else:
                challenge_id = secrets.token_urlsafe(24)
                doc["challenges"].append({
                    "challenge_id": challenge_id,
                    "code": "",
                    "status": "pending_owner",
                    "kind": "provider_auth",
                    "provider": "google",
                    "purpose": "login",
                    "user_id": int(user["user_id"]),
                    "user_uuid": _user_uuid(user),
                    "created_at_utc": _now_iso(),
                    "expires_at": time.time() + OWNER_APPROVAL_TTL_SEC,
                })
        _sync_user_identity_summary(doc, user)
        registration_snapshot = dict(user)
        _write_doc(doc)
    if registration_snapshot.get("initial_trial_pending"):
        _ensure_registration_trial(registration_snapshot, source="google_verified_registration")
    if notify and api_call is not None:
        try:
            _notify_owner_new_user(api_call, owner_chat_id, notify[0])
        except Exception:
            pass
    if active_uid:
        return create_session_for_user(
            active_uid, ip=ip, user_agent=user_agent,
            source="google_login", require_google=False,
            device_credential=device_credential,
            device_confirmation_required=True,
        )
    _audit("google_login_pending", user_id=int(user.get("user_id") or 0), ip=ip)
    return {
        "ok": True,
        "status": "pending_owner",
        "challenge_id": challenge_id,
        "user": _public_user(user, include_contact=True),
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
                "legacy_user_id": uid,
                "user_uuid": auth_identity.new_user_uuid(),
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
                "primary_login_provider": "test",
                "virtual_preset": str(preset or "")[:40],
                "ux_mode": mode,
            }
            if mode:
                user["ux_mode_set_at_utc"] = _now_iso()
            if terms_accepted:
                user["terms_accepted_at_utc"] = _now_iso()
                user["terms_version"] = str(getattr(legal, "TERMS_VERSION", "1") or "1")
                user["terms_digest"] = str(getattr(legal, "TERMS_DIGEST", "") or "")
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
            _link_identity_in_doc(
                doc, user, provider="google", subject=user["google_sub"],
                verified_at_utc=str(user.get("google_linked_at_utc") or _now_iso()),
                metadata={"email": user["google_email"]}, source="test_auth",
            )
        else:
            user["google_sub"] = ""
            user["google_email"] = ""
            user["google_linked_at_utc"] = ""
            canonical = _user_uuid(user)
            doc["auth_identities"] = [
                row for row in _identity_rows(doc)
                if not (
                    isinstance(row, dict)
                    and hmac.compare_digest(auth_identity.normalize_user_uuid(row.get("user_uuid")), canonical)
                    and str(row.get("provider") or "") == "google"
                )
            ]
        _link_identity_in_doc(
            doc, user, provider="test", subject=f"virtual-{uid}",
            verified_at_utc=str(user.get("created_at_utc") or _now_iso()),
            source="test_auth",
        )
        _sync_user_identity_summary(doc, user)
        _write_doc(doc)
        public = _public_user(user, include_contact=True, include_legacy=True)
    _audit("virtual_user_upsert", user_id=uid, extra={"preset": preset, "ux_mode": mode})
    return public


def list_virtual_users() -> list[Dict[str, Any]]:
    runtime_env.require_staging("Virtual users")
    with _LOCK:
        doc = _read_doc()
        return [
            _public_user(user, include_contact=True, include_legacy=True)
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
        device_confirmation_required=False,
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
        device_confirmation_required=False,
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
