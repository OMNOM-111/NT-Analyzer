"""Trusted-device registry and step-up security challenges (Phase 4).

A trusted device has an internal random ``device_id`` UUID and a server-side
lifecycle ``pending -> trusted -> revoked|expired``. A brand new browser or
Connector session is registered as ``pending`` and never becomes ``trusted``
automatically. Trust is granted only after a one-time, time-boxed, purpose- and
environment-bound security challenge confirmed through a channel the user has
already verified (Telegram, verified email or a safely linked Google verified
email where the approved architecture allows it as the email factor).

The canonical account key remains the Phase 3 UUID. Sessions are correlated to
a device by a server-side fingerprint (never a client-supplied id); a client can
only reference its own device UUID and every mutation re-checks ownership.

This module stores nothing sensitive in the clear: challenge codes are kept only
as a salted PBKDF2 hash, IP is masked audit metadata (never identity) and no
full device fingerprint, OTP, token or secret is exposed through any API.
Persistence reuses the single DPAPI-encrypted account store and lock owned by
``account_auth`` so device, session and challenge state stay atomic together.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Tuple

from . import account_auth, auth_identity, runtime_env


# Device lifecycle.
STATUS_PENDING = "pending"
STATUS_TRUSTED = "trusted"
STATUS_REVOKED = "revoked"
STATUS_EXPIRED = "expired"
DEVICE_STATUSES = (STATUS_PENDING, STATUS_TRUSTED, STATUS_REVOKED, STATUS_EXPIRED)
_ACTIVE_STATUSES = (STATUS_PENDING, STATUS_TRUSTED)

DEVICE_TYPES = ("phone", "tablet", "desktop", "browser", "connector")

# Challenge purposes. A challenge can only satisfy the exact purpose it was
# created for; a device-confirm challenge can never approve a revoke, etc.
PURPOSE_DEVICE_CONFIRM = "device_confirm"
PURPOSE_STEP_UP = "step_up"
PURPOSE_REVOKE = "revoke"
CHALLENGE_PURPOSES = (PURPOSE_DEVICE_CONFIRM, PURPOSE_STEP_UP, PURPOSE_REVOKE)

STEP_UP_PROVIDERS = ("telegram", "email", "google")

CHALLENGE_TTL_SEC = 10 * 60
CHALLENGE_MAX_ATTEMPTS = 5
# Trust is not permanent: a trusted device that is not used for this long is
# treated as expired and must be re-confirmed. Security metadata retention is
# handled separately (ADR-0003: 180 days for security events).
DEVICE_TRUST_TTL_SEC = 180 * 24 * 60 * 60
_CHALLENGE_RETENTION_SEC = 24 * 60 * 60
_REVOKE_NOTICE_TTL_SEC = 24 * 60 * 60

# Per-account challenge-creation rate limit (defence in depth on top of the
# session/CSRF gate at the HTTP layer).
_CHALLENGE_RATE_MAX = 6
_CHALLENGE_RATE_WINDOW_SEC = 5 * 60
_CHALLENGE_RATE: Dict[str, Deque[float]] = defaultdict(deque)


class SecurityDeviceError(RuntimeError):
    def __init__(self, message: str, status: int = 400, *, code: str = ""):
        super().__init__(message)
        self.status = int(status)
        self.code = str(code or "")


# --------------------------------------------------------------------------- #
# Store helpers (reuse the account_auth DPAPI document + lock).
# --------------------------------------------------------------------------- #
def _devices(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = doc.get("trusted_devices")
    if not isinstance(rows, list):
        rows = []
        doc["trusted_devices"] = rows
    return rows


def _challenges(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = doc.get("security_challenges")
    if not isinstance(rows, list):
        rows = []
        doc["security_challenges"] = rows
    return rows


def _now() -> float:
    return time.time()


def _iso_from_epoch(epoch: float) -> str:
    try:
        moment = datetime.fromtimestamp(float(epoch), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return ""
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def _current_environment() -> str:
    try:
        return runtime_env.deployment_environment()
    except Exception:
        return "development"


def _normalize_uuid(value: Any) -> str:
    return auth_identity.normalize_user_uuid(value)


def _fingerprint(user_uuid: str, raw_fingerprint: str) -> str:
    """Correlate a session to a device without storing a full fingerprint.

    The raw value is the server-side ``account_auth._device_id`` hash. We fold
    the account UUID in so the same browser under two accounts maps to two
    distinct devices, and we keep only a short digest as masked metadata.
    """
    basis = f"{user_uuid}\0{raw_fingerprint}".encode("utf-8", errors="ignore")
    return hashlib.sha256(basis).hexdigest()[:32]


# --------------------------------------------------------------------------- #
# Device classification (best-effort, non-identifying).
# --------------------------------------------------------------------------- #
def _os_family(user_agent: str) -> str:
    low = str(user_agent or "").lower()
    if "windows" in low:
        return "Windows"
    if "android" in low:
        return "Android"
    if "iphone" in low:
        return "iOS"
    if "ipad" in low:
        return "iPadOS"
    if "mac os" in low or "macintosh" in low:
        return "macOS"
    if "linux" in low:
        return "Linux"
    return ""


def _os_version(user_agent: str, os_family: str) -> str:
    ua = str(user_agent or "")
    try:
        if os_family == "Windows":
            m = re.search(r"Windows NT ([0-9]+(?:\.[0-9]+)?)", ua)
            return m.group(1) if m else ""
        if os_family == "Android":
            m = re.search(r"Android ([0-9]+)", ua)
            return m.group(1) if m else ""
        if os_family in {"iOS", "iPadOS"}:
            m = re.search(r"OS ([0-9]+)[_.]", ua)
            return m.group(1) if m else ""
        if os_family == "macOS":
            m = re.search(r"Mac OS X ([0-9]+)[_.]", ua)
            return m.group(1) if m else ""
    except (re.error, IndexError):
        return ""
    return ""


def _classify(user_agent: str, source: str, connector_installation_id: str) -> Dict[str, str]:
    if connector_installation_id or "connector" in str(source or "").lower():
        return {
            "device_type": "connector",
            "os_family": _os_family(user_agent),
            "os_version": "",
            "client": "NinjaTrader Connector",
        }
    os_family = _os_family(user_agent)
    client = account_auth._device_label(user_agent)
    if os_family in {"iOS", "Android"}:
        device_type = "phone"
    elif os_family == "iPadOS":
        device_type = "tablet"
    elif os_family in {"Windows", "macOS", "Linux"}:
        device_type = "desktop"
    else:
        device_type = "browser"
    return {
        "device_type": device_type,
        "os_family": os_family,
        "os_version": _os_version(user_agent, os_family),
        "client": client,
    }


def _display_name(profile: Dict[str, str], source: str) -> str:
    if profile["device_type"] == "connector":
        return "NinjaTrader Connector"
    if profile["device_type"] == "desktop":
        return account_auth._machine_label()
    parts = [p for p in (profile.get("client"), profile.get("os_family")) if p]
    return " · ".join(parts) or "Устройство"


# --------------------------------------------------------------------------- #
# Maintenance.
# --------------------------------------------------------------------------- #
def _expire_stale(doc: Dict[str, Any]) -> bool:
    """Mark inactive trusted devices expired and prune old challenges.

    Never resurrects a revoked device and never downgrades expiry to trust.
    Returns True when the document changed.
    """
    now = _now()
    changed = False
    for device in _devices(doc):
        if not isinstance(device, dict):
            continue
        if device.get("status") == STATUS_TRUSTED:
            expires = float(device.get("expires_at") or 0)
            if expires and expires <= now:
                device["status"] = STATUS_EXPIRED
                device["expired_at_utc"] = account_auth._now_iso()
                changed = True
    kept: List[Dict[str, Any]] = []
    for row in _challenges(doc):
        if not isinstance(row, dict):
            continue
        expires = float(row.get("expires_at") or 0)
        status = str(row.get("status") or "")
        if status == "pending" and expires and expires <= now:
            row["status"] = STATUS_EXPIRED
            changed = True
        # Retain consumed/failed/expired rows briefly for audit + idempotency,
        # then drop them so the store does not grow without bound.
        drop_after = float(row.get("retain_until") or (expires + _CHALLENGE_RETENTION_SEC))
        if status in {"consumed", "failed"} and drop_after <= now:
            changed = True
            continue
        if status == STATUS_EXPIRED and (expires + _CHALLENGE_RETENTION_SEC) <= now:
            changed = True
            continue
        kept.append(row)
    doc["security_challenges"] = kept[-500:]
    return changed


# --------------------------------------------------------------------------- #
# Public masking.
# --------------------------------------------------------------------------- #
def _active_device_ids(doc: Dict[str, Any]) -> frozenset:
    """Device ids that currently have at least one live (non-revoked, unexpired)
    session. This is the only honest ``online`` signal — it never guesses from a
    stale ``last_seen`` timestamp and never invents a heartbeat we do not have.
    """
    now = _now()
    live: set = set()
    for row in doc.get("sessions") or []:
        if not isinstance(row, dict):
            continue
        if row.get("revoked") or float(row.get("expires_at") or 0) <= now:
            continue
        did = str(row.get("trusted_device_id") or "")
        if did:
            live.add(did)
    return frozenset(live)


def _public_device(device: Dict[str, Any], active_ids: frozenset = frozenset()) -> Dict[str, Any]:
    device_id = str(device.get("device_id") or "")
    status = str(device.get("status") or STATUS_PENDING)
    return {
        "device_id": device_id,
        "device_type": str(device.get("device_type") or "browser"),
        "display_name": str(device.get("display_name") or "Устройство"),
        "os_family": str(device.get("os_family") or ""),
        "os_version": str(device.get("os_version") or ""),
        "client": str(device.get("client") or ""),
        "app_version": str(device.get("app_version") or ""),
        "connector_installation_id": str(device.get("connector_installation_id") or ""),
        "status": status,
        # ``online`` is derived only from a live session for this device id, so a
        # revoked/expired device can never report as online.
        "online": bool(device_id) and device_id in active_ids and status in _ACTIVE_STATUSES,
        "confirmation_provider": str(device.get("confirmation_provider") or ""),
        "first_seen_at_utc": str(device.get("first_seen_at_utc") or ""),
        "last_seen_at_utc": str(device.get("last_seen_at_utc") or ""),
        "last_auth_at_utc": str(device.get("last_auth_at_utc") or ""),
        "confirmed_at_utc": str(device.get("confirmed_at_utc") or ""),
        "revoked_at_utc": str(device.get("revoked_at_utc") or ""),
        "expires_at_utc": str(device.get("expires_at_utc") or ""),
        # Masked, coarse origin only. Never the raw IP or a full fingerprint.
        "last_region": str((device.get("audit_metadata") or {}).get("last_ip") or ""),
    }


def _owned_device(doc: Dict[str, Any], user_uuid: str, device_id: str) -> Dict[str, Any]:
    canonical = _normalize_uuid(user_uuid)
    target = str(device_id or "").strip()
    if not canonical:
        raise SecurityDeviceError("Требуется вход.", 401, code="auth_required")
    if not target:
        raise SecurityDeviceError("Не указано устройство.", 400, code="device_required")
    for device in _devices(doc):
        if not isinstance(device, dict):
            continue
        if not hmac.compare_digest(str(device.get("device_id") or ""), target):
            continue
        # Ownership is verified server-side against the canonical UUID: a legacy
        # numeric id or another account can never reach a foreign device.
        if not hmac.compare_digest(_normalize_uuid(device.get("user_uuid")), canonical):
            raise SecurityDeviceError("Устройство не найдено.", 404, code="device_not_found")
        return device
    raise SecurityDeviceError("Устройство не найдено.", 404, code="device_not_found")


# --------------------------------------------------------------------------- #
# Session correlation (called by account_auth during session creation).
# --------------------------------------------------------------------------- #
def observe_session(
    doc: Dict[str, Any],
    session: Dict[str, Any],
    user: Dict[str, Any],
    *,
    ip: str = "",
    user_agent: str = "",
    source: str = "",
    connector_installation_id: str = "",
) -> List[Tuple[str, Dict[str, Any]]]:
    """Register/touch the trusted device for a freshly created session.

    Mutates ``doc`` and ``session`` in place and returns audit events for the
    caller to emit after the document is persisted. A new device is ``pending``;
    a revoked/expired match is never reused — a fresh ``pending`` record is
    created so trust cannot silently return.
    """
    user_uuid = _normalize_uuid(account_auth._user_uuid(user))
    if not user_uuid:
        return []
    raw_fp = account_auth._device_id(user_agent)
    fingerprint = _fingerprint(user_uuid, raw_fp)
    now_iso = account_auth._now_iso()
    profile = _classify(user_agent, source, connector_installation_id)
    masked_ip = account_auth._mask_ip(ip)

    device = None
    for row in reversed(_devices(doc)):
        if not isinstance(row, dict):
            continue
        if not hmac.compare_digest(_normalize_uuid(row.get("user_uuid")), user_uuid):
            continue
        if not hmac.compare_digest(str(row.get("fingerprint") or ""), fingerprint):
            continue
        if str(row.get("status") or "") in _ACTIVE_STATUSES:
            device = row
            break

    events: List[Tuple[str, Dict[str, Any]]] = []
    if device is None:
        device = {
            "device_id": str(uuid.uuid4()),
            "user_uuid": user_uuid,
            "legacy_user_id": int(user.get("user_id") or 0),
            "fingerprint": fingerprint,
            "device_type": profile["device_type"],
            "display_name": _display_name(profile, source),
            "os_family": profile["os_family"],
            "os_version": profile["os_version"],
            "client": profile["client"],
            "app_version": "",
            "connector_installation_id": str(connector_installation_id or ""),
            "status": STATUS_PENDING,
            "confirmation_provider": "",
            "first_seen_at_utc": now_iso,
            "last_seen_at_utc": now_iso,
            "last_auth_at_utc": now_iso,
            "confirmed_at_utc": "",
            "revoked_at_utc": "",
            "expires_at": 0,
            "expires_at_utc": "",
            "audit_metadata": {"last_ip": masked_ip},
        }
        _devices(doc).append(device)
        events.append((
            "device.pending",
            {
                "device_id": device["device_id"],
                "device_type": device["device_type"],
                "environment": _current_environment(),
            },
        ))
    else:
        device["last_seen_at_utc"] = now_iso
        device["last_auth_at_utc"] = now_iso
        device["client"] = profile["client"] or device.get("client") or ""
        if profile["os_family"]:
            device["os_family"] = profile["os_family"]
        if profile["os_version"]:
            device["os_version"] = profile["os_version"]
        if connector_installation_id:
            device["connector_installation_id"] = str(connector_installation_id)
        meta = device.get("audit_metadata") if isinstance(device.get("audit_metadata"), dict) else {}
        meta["last_ip"] = masked_ip
        device["audit_metadata"] = meta
        if device.get("status") == STATUS_TRUSTED:
            # Sliding trust window on continued successful use.
            device["expires_at"] = _now() + DEVICE_TRUST_TTL_SEC
            device["expires_at_utc"] = _iso_from_epoch(device["expires_at"])

    session["trusted_device_id"] = device["device_id"]
    session["device_trust_status"] = device["status"]
    # Keep the last N devices bounded per store without dropping active ones.
    _prune_devices(doc, user_uuid)
    return events


def _prune_devices(doc: Dict[str, Any], user_uuid: str, keep: int = 50) -> None:
    rows = _devices(doc)
    owned = [
        idx for idx, row in enumerate(rows)
        if isinstance(row, dict)
        and hmac.compare_digest(_normalize_uuid(row.get("user_uuid")), user_uuid)
    ]
    if len(owned) <= keep:
        return
    # Drop the oldest *inactive* (revoked/expired) records first.
    inactive = [
        idx for idx in owned
        if str(rows[idx].get("status") or "") not in _ACTIVE_STATUSES
    ]
    drop = set(inactive[: max(0, len(owned) - keep)])
    if drop:
        doc["trusted_devices"] = [row for idx, row in enumerate(rows) if idx not in drop]


# --------------------------------------------------------------------------- #
# Step-up provider availability.
# --------------------------------------------------------------------------- #
def _available_providers(doc: Dict[str, Any], user: Dict[str, Any]) -> List[str]:
    providers: List[str] = []
    if account_auth._telegram_subject_for_user(doc, user) > 0:
        providers.append("telegram")
    verified_email = False
    for row in account_auth._identities_for_user(doc, user):
        if str(row.get("provider") or "") == "email" and row.get("verified_at_utc"):
            verified_email = True
            break
    if verified_email:
        providers.append("email")
    if account_auth.google_linked(user) and str(user.get("google_email") or "").strip():
        providers.append("google")
    return providers


# --------------------------------------------------------------------------- #
# Challenge lifecycle.
# --------------------------------------------------------------------------- #
def _code_hash(challenge_id: str, salt: str, code: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        str(code or "").encode("ascii", errors="ignore"),
        (str(challenge_id) + ":" + str(salt)).encode("utf-8"),
        120_000,
    ).hex()


def _rate_limit(user_uuid: str) -> None:
    now = _now()
    with account_auth._RATE_LOCK:
        q = _CHALLENGE_RATE[user_uuid]
        while q and q[0] <= now - _CHALLENGE_RATE_WINDOW_SEC:
            q.popleft()
        if len(q) >= _CHALLENGE_RATE_MAX:
            raise SecurityDeviceError(
                "Слишком много запросов подтверждения. Повторите позже.",
                429, code="challenge_rate_limited",
            )
        q.append(now)


def _dev_code_echo() -> bool:
    return bool(runtime_env.is_development() and runtime_env.test_auth_enabled())


def create_challenge(
    *,
    user_id: Any,
    purpose: str,
    device_id: str = "",
    provider: str = "",
    action: str = "",
    ip: str = "",
    user_agent: str = "",
) -> Dict[str, Any]:
    """Create a one-time, time-boxed, purpose/environment-bound challenge."""
    purpose_id = str(purpose or "").strip().lower()
    if purpose_id not in CHALLENGE_PURPOSES:
        raise SecurityDeviceError("Недопустимая цель подтверждения.", 400, code="purpose_invalid")
    provider_id = str(provider or "").strip().lower()
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise SecurityDeviceError("Требуется вход.", 401, code="auth_required")

    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(16)
    challenge_id = secrets.token_urlsafe(24)
    environment = _current_environment()
    now = _now()

    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, uid)
        if not user or user.get("status") != "active":
            raise SecurityDeviceError("Аккаунт не активен.", 403, code="account_inactive")
        user_uuid = _normalize_uuid(account_auth._user_uuid(user))
        if not user_uuid:
            raise SecurityDeviceError("Профиль без UUID identity.", 409, code="identity_missing")
        _rate_limit(user_uuid)
        _expire_stale(doc)

        target_device_id = ""
        if purpose_id in {PURPOSE_DEVICE_CONFIRM, PURPOSE_REVOKE}:
            device = _owned_device(doc, user_uuid, device_id)
            if purpose_id == PURPOSE_DEVICE_CONFIRM and device.get("status") != STATUS_PENDING:
                raise SecurityDeviceError(
                    "Устройство не в состоянии ожидания.", 409, code="device_not_pending",
                )
            if device.get("status") == STATUS_REVOKED:
                raise SecurityDeviceError("Устройство отозвано.", 409, code="device_revoked")
            target_device_id = str(device.get("device_id") or "")

        available = _available_providers(doc, user)
        if not provider_id:
            provider_id = available[0] if available else ""
        if not available:
            raise SecurityDeviceError(
                "Нет подтверждённого канала (Telegram или email) для подтверждения.",
                409, code="no_step_up_channel",
            )
        if provider_id not in available:
            raise SecurityDeviceError(
                "Этот канал подтверждения недоступен для аккаунта.",
                409, code="provider_unavailable",
            )

        _challenges(doc).append({
            "challenge_id": challenge_id,
            "user_uuid": user_uuid,
            "legacy_user_id": uid,
            "device_id": target_device_id,
            "purpose": purpose_id,
            "provider": provider_id,
            "action": str(action or "")[:40],
            "environment": environment,
            "code_salt": salt,
            "code_hash": _code_hash(challenge_id, salt, code),
            "status": "pending",
            "attempts": 0,
            "max_attempts": CHALLENGE_MAX_ATTEMPTS,
            "created_at_utc": account_auth._now_iso(),
            "expires_at": now + CHALLENGE_TTL_SEC,
        })
        account_auth._write_doc(doc)

    account_auth._audit(
        "security.challenge_created",
        user_id=uid,
        ip=ip,
        extra={
            "challenge_id": challenge_id,
            "purpose": purpose_id,
            "provider": provider_id,
            "environment": environment,
            "device_id": target_device_id,
        },
    )
    out = {
        "ok": True,
        "challenge_id": challenge_id,
        "purpose": purpose_id,
        "provider": provider_id,
        "environment": environment,
        "expires_in_sec": CHALLENGE_TTL_SEC,
        "delivery": "development_test" if _dev_code_echo() else provider_id,
    }
    # The one-time code is only ever disclosed behind the explicit Development
    # test-auth gate. Real Telegram/email delivery happens out-of-band.
    if _dev_code_echo():
        out["test_code"] = code
    return out


def _consume_challenge(
    doc: Dict[str, Any],
    *,
    challenge_id: str,
    code: str,
    user_uuid: str,
    purpose: str,
    device_id: str = "",
) -> Tuple[Dict[str, Any], List[Tuple[str, Dict[str, Any]]]]:
    """Atomically validate + consume a challenge. Raises on any mismatch."""
    cid = str(challenge_id or "").strip()
    canonical = _normalize_uuid(user_uuid)
    environment = _current_environment()
    now = _now()
    events: List[Tuple[str, Dict[str, Any]]] = []

    challenge = None
    for row in reversed(_challenges(doc)):
        if isinstance(row, dict) and hmac.compare_digest(str(row.get("challenge_id") or ""), cid):
            challenge = row
            break
    if challenge is None:
        raise SecurityDeviceError("Запрос подтверждения не найден или истёк.", 410, code="challenge_not_found")

    status = str(challenge.get("status") or "")
    if status == STATUS_EXPIRED:
        raise SecurityDeviceError("Срок подтверждения истёк.", 410, code="challenge_expired")
    if status != "pending":
        raise SecurityDeviceError("Запрос уже использован.", 410, code="challenge_not_pending")
    if float(challenge.get("expires_at") or 0) <= now:
        challenge["status"] = STATUS_EXPIRED
        events.append(("security.challenge_expired", {"challenge_id": cid}))
        raise SecurityDeviceError("Срок подтверждения истёк.", 410, code="challenge_expired")

    # Bind to user, purpose, device and environment. Any mismatch fails closed
    # and does not consume an attempt against the wrong actor's counter.
    if not hmac.compare_digest(_normalize_uuid(challenge.get("user_uuid")), canonical):
        raise SecurityDeviceError("Чужой запрос подтверждения.", 403, code="challenge_wrong_user")
    if str(challenge.get("purpose") or "") != str(purpose or ""):
        raise SecurityDeviceError("Неверная цель подтверждения.", 409, code="challenge_wrong_purpose")
    if str(challenge.get("environment") or "") != environment:
        raise SecurityDeviceError("Подтверждение из другого окружения.", 409, code="challenge_wrong_environment")
    bound_device = str(challenge.get("device_id") or "")
    if bound_device and str(device_id or "") and not hmac.compare_digest(bound_device, str(device_id or "")):
        raise SecurityDeviceError("Подтверждение для другого устройства.", 409, code="challenge_wrong_device")

    challenge["attempts"] = int(challenge.get("attempts") or 0) + 1
    max_attempts = int(challenge.get("max_attempts") or CHALLENGE_MAX_ATTEMPTS)
    supplied = str(code or "").strip()
    expected = _code_hash(cid, str(challenge.get("code_salt") or ""), supplied)
    code_ok = bool(re.fullmatch(r"[0-9]{6}", supplied)) and hmac.compare_digest(
        str(challenge.get("code_hash") or ""), expected,
    )
    if not code_ok:
        if challenge["attempts"] >= max_attempts:
            challenge["status"] = "failed"
            challenge["retain_until"] = now + _CHALLENGE_RETENTION_SEC
            events.append(("security.challenge_failed", {"challenge_id": cid, "reason": "attempts_exhausted"}))
            raise SecurityDeviceError("Исчерпаны попытки подтверждения.", 429, code="challenge_attempts_exhausted")
        events.append(("security.challenge_failed", {"challenge_id": cid, "reason": "bad_code"}))
        raise SecurityDeviceError("Неверный код подтверждения.", 401, code="challenge_bad_code")

    challenge["status"] = "consumed"
    challenge["consumed_at_utc"] = account_auth._now_iso()
    challenge["retain_until"] = now + _CHALLENGE_RETENTION_SEC
    events.append(("security.challenge_succeeded", {
        "challenge_id": cid,
        "purpose": challenge.get("purpose"),
        "device_id": bound_device,
    }))
    return challenge, events


def _audit_challenge_failure(uid: int, ip: str, challenge_id: str, exc: "SecurityDeviceError") -> None:
    code = exc.code
    if code == "challenge_expired":
        event = "security.challenge_expired"
    elif code in {"challenge_bad_code", "challenge_attempts_exhausted"}:
        event = "security.challenge_failed"
    elif code in {
        "challenge_wrong_user", "challenge_wrong_device",
        "challenge_wrong_purpose", "challenge_wrong_environment",
    }:
        event = "security.challenge_denied"
    else:
        return
    account_auth._audit(event, user_id=uid, ip=ip, extra={"challenge_id": challenge_id, "reason": code})


def _consume_and_persist(
    doc: Dict[str, Any], *, uid: int, ip: str, challenge_id: str, code: str,
    user_uuid: str, purpose: str, device_id: str = "",
) -> Tuple[Dict[str, Any], List[Tuple[str, Dict[str, Any]]]]:
    """Consume a challenge, persisting attempt/expiry state even on failure.

    A wrong or expired attempt must survive so the one-time-use and attempt-cap
    guarantees hold across retries; otherwise each failed try would read a fresh
    zeroed counter.
    """
    try:
        return _consume_challenge(
            doc, challenge_id=challenge_id, code=code, user_uuid=user_uuid,
            purpose=purpose, device_id=device_id,
        )
    except SecurityDeviceError as exc:
        account_auth._write_doc(doc)
        _audit_challenge_failure(uid, ip, challenge_id, exc)
        raise


# --------------------------------------------------------------------------- #
# Session revocation helpers.
# --------------------------------------------------------------------------- #
def _revoke_device_sessions(doc: Dict[str, Any], device: Dict[str, Any], reason: str) -> int:
    device_id = str(device.get("device_id") or "")
    user_uuid = _normalize_uuid(device.get("user_uuid"))
    now = _now()
    revoked = 0
    for session in doc.get("sessions") or []:
        if session.get("revoked"):
            continue
        if not hmac.compare_digest(str(session.get("trusted_device_id") or ""), device_id):
            continue
        # Only this device's sessions for this exact account are touched.
        if user_uuid and not hmac.compare_digest(
            _normalize_uuid(session.get("user_uuid")), user_uuid,
        ):
            continue
        session["revoked"] = True
        session["revoked_at_utc"] = account_auth._now_iso()
        session["revoked_reason"] = reason
        session["revoke_notice_until"] = now + _REVOKE_NOTICE_TTL_SEC
        revoked += 1
    return revoked


# --------------------------------------------------------------------------- #
# Read APIs.
# --------------------------------------------------------------------------- #
def list_devices(user_id: Any) -> Dict[str, Any]:
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise SecurityDeviceError("Требуется вход.", 401, code="auth_required")
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, uid)
        if not user:
            raise SecurityDeviceError("Пользователь не найден.", 404, code="user_not_found")
        if _expire_stale(doc):
            account_auth._write_doc(doc)
        user_uuid = _normalize_uuid(account_auth._user_uuid(user))
        active_ids = _active_device_ids(doc)
        rows = [
            _public_device(row, active_ids) for row in _devices(doc)
            if isinstance(row, dict)
            and hmac.compare_digest(_normalize_uuid(row.get("user_uuid")), user_uuid)
        ]
    rows.sort(key=lambda item: str(item.get("last_seen_at_utc") or ""), reverse=True)
    return {"ok": True, "devices": rows}


def account_security(user_id: Any) -> Dict[str, Any]:
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise SecurityDeviceError("Требуется вход.", 401, code="auth_required")
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, uid)
        if not user:
            raise SecurityDeviceError("Пользователь не найден.", 404, code="user_not_found")
        if _expire_stale(doc):
            account_auth._write_doc(doc)
        user_uuid = _normalize_uuid(account_auth._user_uuid(user))
        active_ids = _active_device_ids(doc)
        devices = [
            _public_device(row, active_ids) for row in _devices(doc)
            if isinstance(row, dict)
            and hmac.compare_digest(_normalize_uuid(row.get("user_uuid")), user_uuid)
        ]
        identities = [
            auth_identity.public_identity(row, user=user)
            for row in account_auth._identities_for_user(doc, user)
        ]
        providers = _available_providers(doc, user)
    devices.sort(key=lambda item: str(item.get("last_seen_at_utc") or ""), reverse=True)
    return {
        "ok": True,
        "identity_model": "uuid",
        "user_uuid": user_uuid,
        "identities": identities,
        "step_up_providers": providers,
        "devices": devices,
        "policy": {
            "device_confirmation_required": True,
            "challenge_ttl_sec": CHALLENGE_TTL_SEC,
            "trust_ttl_sec": DEVICE_TRUST_TTL_SEC,
        },
    }


# --------------------------------------------------------------------------- #
# Mutation APIs.
# --------------------------------------------------------------------------- #
def confirm_challenge(
    *,
    user_id: Any,
    challenge_id: str,
    code: str,
    ip: str = "",
) -> Dict[str, Any]:
    """Confirm a step-up challenge and apply its purpose-bound effect."""
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise SecurityDeviceError("Требуется вход.", 401, code="auth_required")
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, uid)
        if not user or user.get("status") != "active":
            raise SecurityDeviceError("Аккаунт не активен.", 403, code="account_inactive")
        user_uuid = _normalize_uuid(account_auth._user_uuid(user))
        _expire_stale(doc)
        # Resolve the challenge first to learn its purpose, then validate.
        cid = str(challenge_id or "").strip()
        pending = None
        for row in reversed(_challenges(doc)):
            if isinstance(row, dict) and hmac.compare_digest(str(row.get("challenge_id") or ""), cid):
                pending = row
                break
        purpose = str((pending or {}).get("purpose") or PURPOSE_STEP_UP)
        challenge, events = _consume_and_persist(
            doc, uid=uid, ip=ip, challenge_id=cid, code=code,
            user_uuid=user_uuid, purpose=purpose,
        )
        result: Dict[str, Any] = {"ok": True, "purpose": purpose}
        if purpose == PURPOSE_DEVICE_CONFIRM:
            device = _owned_device(doc, user_uuid, str(challenge.get("device_id") or ""))
            _trust_device(device, provider=str(challenge.get("provider") or ""))
            events.append(("device.approved", {
                "device_id": device["device_id"],
                "provider": device.get("confirmation_provider"),
            }))
            result["device"] = _public_device(device)
        elif purpose == PURPOSE_REVOKE:
            device = _owned_device(doc, user_uuid, str(challenge.get("device_id") or ""))
            revoked = _apply_revoke(doc, device, reason="device_revoked")
            events.append(("device.revoked", {"device_id": device["device_id"]}))
            events.append(("session.revoked_by_device", {
                "device_id": device["device_id"], "count": revoked,
            }))
            result["device"] = _public_device(device)
            result["revoked_sessions"] = revoked
        else:
            result["step_up"] = True
            result["action"] = str(challenge.get("action") or "")
        account_auth._write_doc(doc)
    for event, extra in events:
        account_auth._audit(event, user_id=uid, ip=ip, extra=extra)
    return result


def _trust_device(device: Dict[str, Any], *, provider: str) -> None:
    device["status"] = STATUS_TRUSTED
    device["confirmation_provider"] = str(provider or "")
    device["confirmed_at_utc"] = account_auth._now_iso()
    device["expires_at"] = _now() + DEVICE_TRUST_TTL_SEC
    device["expires_at_utc"] = _iso_from_epoch(device["expires_at"])
    device["revoked_at_utc"] = ""


def approve_device(
    *,
    user_id: Any,
    device_id: str,
    challenge_id: str,
    code: str,
    ip: str = "",
) -> Dict[str, Any]:
    """Approve a pending device by confirming a device-confirm challenge."""
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise SecurityDeviceError("Требуется вход.", 401, code="auth_required")
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, uid)
        if not user or user.get("status") != "active":
            raise SecurityDeviceError("Аккаунт не активен.", 403, code="account_inactive")
        user_uuid = _normalize_uuid(account_auth._user_uuid(user))
        _expire_stale(doc)
        device = _owned_device(doc, user_uuid, device_id)
        if device.get("status") != STATUS_PENDING:
            raise SecurityDeviceError("Устройство не в состоянии ожидания.", 409, code="device_not_pending")
        challenge, events = _consume_and_persist(
            doc, uid=uid, ip=ip, challenge_id=challenge_id, code=code,
            user_uuid=user_uuid, purpose=PURPOSE_DEVICE_CONFIRM,
            device_id=str(device.get("device_id") or ""),
        )
        _trust_device(device, provider=str(challenge.get("provider") or ""))
        events.append(("device.approved", {
            "device_id": device["device_id"],
            "provider": device.get("confirmation_provider"),
        }))
        account_auth._write_doc(doc)
        public = _public_device(device)
    for event, extra in events:
        account_auth._audit(event, user_id=uid, ip=ip, extra=extra)
    return {"ok": True, "device": public}


def _apply_revoke(doc: Dict[str, Any], device: Dict[str, Any], *, reason: str) -> int:
    device["status"] = STATUS_REVOKED
    device["revoked_at_utc"] = account_auth._now_iso()
    device["expires_at"] = 0
    return _revoke_device_sessions(doc, device, reason)


def reject_device(*, user_id: Any, device_id: str, ip: str = "") -> Dict[str, Any]:
    """Reject a pending device: block its sessions and revoke it."""
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise SecurityDeviceError("Требуется вход.", 401, code="auth_required")
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, uid)
        if not user:
            raise SecurityDeviceError("Пользователь не найден.", 404, code="user_not_found")
        user_uuid = _normalize_uuid(account_auth._user_uuid(user))
        device = _owned_device(doc, user_uuid, device_id)
        if device.get("status") == STATUS_REVOKED:
            # Idempotent: already rejected/revoked.
            return {"ok": True, "device": _public_device(device), "revoked_sessions": 0}
        if device.get("status") != STATUS_PENDING:
            raise SecurityDeviceError("Отклонить можно только устройство в ожидании.", 409, code="device_not_pending")
        revoked = _apply_revoke(doc, device, reason="device_rejected")
        account_auth._write_doc(doc)
        public = _public_device(device)
    account_auth._audit("device.rejected", user_id=uid, ip=ip, extra={"device_id": public["device_id"]})
    if revoked:
        account_auth._audit(
            "session.revoked_by_device", user_id=uid, ip=ip,
            extra={"device_id": public["device_id"], "count": revoked, "reason": "device_rejected"},
        )
    return {"ok": True, "device": public, "revoked_sessions": revoked}


def revoke_device(*, user_id: Any, device_id: str, ip: str = "") -> Dict[str, Any]:
    """Revoke a device and immediately invalidate only its own sessions."""
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise SecurityDeviceError("Требуется вход.", 401, code="auth_required")
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, uid)
        if not user:
            raise SecurityDeviceError("Пользователь не найден.", 404, code="user_not_found")
        user_uuid = _normalize_uuid(account_auth._user_uuid(user))
        device = _owned_device(doc, user_uuid, device_id)
        if device.get("status") == STATUS_REVOKED:
            return {"ok": True, "device": _public_device(device), "revoked_sessions": 0}
        revoked = _apply_revoke(doc, device, reason="device_revoked")
        account_auth._write_doc(doc)
        public = _public_device(device)
    account_auth._audit("device.revoked", user_id=uid, ip=ip, extra={"device_id": public["device_id"]})
    if revoked:
        account_auth._audit(
            "session.revoked_by_device", user_id=uid, ip=ip,
            extra={"device_id": public["device_id"], "count": revoked, "reason": "device_revoked"},
        )
    return {"ok": True, "device": public, "revoked_sessions": revoked}
