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
import os
import re
import secrets
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Tuple

from . import account_auth, auth_identity, physical_devices, runtime_env


# Device lifecycle. A client-level ``trusted`` record always means permanent
# trust. Session-only access deliberately remains on the auth-session row so a
# later login can never inherit it by finding the same browser credential.
STATUS_PENDING = "pending"
STATUS_TRUSTED = "trusted"
STATUS_REVOKED = "revoked"
STATUS_EXPIRED = "expired"
DEVICE_STATUSES = (STATUS_PENDING, STATUS_TRUSTED, STATUS_REVOKED, STATUS_EXPIRED)
_ACTIVE_STATUSES = (STATUS_PENDING, STATUS_TRUSTED)

TRUST_MODE_PERMANENT = "permanent"
TRUST_MODE_SESSION = "session"
TRUST_MODES = (TRUST_MODE_PERMANENT, TRUST_MODE_SESSION)

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
# A new login can do nothing except complete confirmation (or log out) during
# this short server-side window. The regular session lifetime is restored only
# after the OTP has been consumed successfully.
#
# Two minutes, not five: an unhurried pass — read the two choices, wait for the
# code, type six digits — was measured at ~22 seconds, and the window still has
# to cover one late code. A resend costs the 30-second cooldown plus delivery
# and typing (~75 seconds), so two minutes leaves that path usable while
# closing an unconfirmed session far sooner than before.
PENDING_SESSION_TTL_SEC = 2 * 60
CHALLENGE_RESEND_COOLDOWN_SEC = 30
CHALLENGE_MAX_RESENDS = 3
# Compatibility only: old trusted-device rows may still carry a sliding expiry
# written by an earlier release. New permanent approvals store no expiry and
# last until explicit revoke, which is what the user-facing promise says.
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
        # Operator-facing cause, audited but never returned to the caller.
        self.detail = ""


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


def _epoch_from_iso(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _current_environment() -> str:
    try:
        return runtime_env.deployment_environment()
    except Exception:
        return "development"


def _normalize_uuid(value: Any) -> str:
    return auth_identity.normalize_user_uuid(value)


def _fingerprint(user_uuid: str, raw_fingerprint: str) -> str:
    """Correlate a session to a device without storing the credential itself.

    The raw value is the digest of the browser-held device credential. We fold
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
    if client.startswith("Браузер") and "mozilla/" not in str(user_agent or "").lower():
        # A User-Agent carrying no browser engine token belongs to an app or an
        # API client. Calling that access "Браузер" in Security would describe
        # the wrong thing; the neutral label states only what is known.
        client = "Приложение" + (f" · {os_family}" if os_family else "")
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
    # A browser User-Agent may describe an OS, but it cannot prove the name or
    # identity of the physical computer. Keep the label at Client level and let
    # a proven Machine receive its own neutral/user-defined name separately.
    return str(profile.get("client") or "Браузер или приложение")


# --------------------------------------------------------------------------- #
# Maintenance.
# --------------------------------------------------------------------------- #
def _expire_stale(doc: Dict[str, Any]) -> bool:
    """Expire legacy time-boxed device rows and prune old challenges.

    Permanent rows created by the current flow have ``expires_at == 0`` and
    therefore stay trusted until revoke. Never resurrects a revoked device and
    never downgrades expiry to trust. Returns True when the document changed.
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
        "trust_mode": (
            str(device.get("trust_mode") or TRUST_MODE_PERMANENT)
            if status == STATUS_TRUSTED else ""
        ),
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
        "location": str((device.get("audit_metadata") or {}).get("location") or ""),
        # Which machine this client runs on, and how that was established. Empty
        # means "no known machine", which is the honest answer for a browser the
        # user has not paired -- not a gap to be filled by guessing.
        "physical_device_id": str(device.get("physical_device_id") or ""),
        "bound_via": str(device.get("bound_via") or ""),
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
    device_credential: str = "",
) -> List[Tuple[str, Dict[str, Any]]]:
    """Register/touch the client device for a freshly created session.

    Mutates ``doc`` and ``session`` in place and returns audit events for the
    caller to emit after the document is persisted. A new device is ``pending``;
    a revoked/expired match is never reused — a fresh ``pending`` record is
    created so trust cannot silently return.

    A Connector additionally identifies the *machine* it runs on, through the
    hardware-bound installation id it was enrolled with. That is the only input
    here that carries machine identity: a browser's User-Agent, IP and the
    server's own hostname deliberately do not, so a browser client is left
    unbound until the user pairs it explicitly (``physical_devices``).
    """
    user_uuid = _normalize_uuid(account_auth._user_uuid(user))
    if not user_uuid:
        return []
    _expire_stale(doc)
    credential = str(device_credential or "")
    if not credential and str(connector_installation_id or "").strip():
        # The Connector has no cookie jar; its installation id is already a
        # stable per-device secret issued during enrollment.
        credential = "connector:" + str(connector_installation_id).strip()
    raw_fp = account_auth._device_id(user_agent, device_credential=credential)
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
    installation_id = str(connector_installation_id or "").strip()
    machine, machine_events = physical_devices.observe_machine(
        doc, user,
        machine_credential=installation_id,
        os_family=profile["os_family"],
        os_version=profile["os_version"],
        # No display name is passed on purpose. The obvious candidate,
        # _machine_label(), is the *server's* COMPUTERNAME -- identical for
        # every user of a deployment and not the machine being described. The
        # machine gets a neutral default the user can rename.
        ip=ip,
    )
    events.extend(machine_events)

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
            "trust_mode": "",
            "confirmation_provider": "",
            "first_seen_at_utc": now_iso,
            "last_seen_at_utc": now_iso,
            "last_auth_at_utc": now_iso,
            "confirmed_at_utc": "",
            "revoked_at_utc": "",
            "expires_at": 0,
            "expires_at_utc": "",
            "audit_metadata": {"last_ip": masked_ip},
            "physical_device_id": "",
            "bound_via": "",
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
            # A legacy trusted row becomes an explicit permanent row the first
            # time it is used by this release. This removes the old sliding-TTL
            # ambiguity without changing its identity or confirmation history.
            device["trust_mode"] = TRUST_MODE_PERMANENT
            device["expires_at"] = 0
            device["expires_at_utc"] = ""

    if machine is not None:
        # The Connector is the client that carries the machine credential, so it
        # is bound to its own machine without a pairing step. Every other client
        # keeps whatever binding it already earned -- re-observing a browser must
        # never quietly move it to a different machine.
        physical_devices.bind_client(
            device, machine, bound_via=physical_devices.BOUND_VIA_CONNECTOR_SELF,
        )

    session["trusted_device_id"] = device["device_id"]
    session["device_trust_status"] = device["status"]
    session["physical_device_id"] = str(device.get("physical_device_id") or "")
    confirmation_required = not bool(session.get("device_confirmation_exempt"))
    session["device_confirmation_required"] = confirmation_required
    if not confirmation_required:
        session["device_confirmation_state"] = "active"
        session["device_trust_mode"] = "exempt"
        session["pending_expires_at"] = 0
        session["pending_expires_at_utc"] = ""
    elif device.get("status") == STATUS_TRUSTED:
        session["device_confirmation_state"] = "active"
        session["device_trust_mode"] = TRUST_MODE_PERMANENT
        session["pending_expires_at"] = 0
        session["pending_expires_at_utc"] = ""
    else:
        now = _now()
        pending_until = now + PENDING_SESSION_TTL_SEC
        normal_expiry = float(session.get("normal_expires_at") or session.get("expires_at") or 0)
        session["normal_expires_at"] = normal_expiry
        session["device_confirmation_state"] = STATUS_PENDING
        session["device_trust_mode"] = ""
        session["pending_expires_at"] = pending_until
        session["pending_expires_at_utc"] = _iso_from_epoch(pending_until)
        session["expires_at"] = min(normal_expiry, pending_until) if normal_expiry else pending_until
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
def _verified_email_target(doc: Dict[str, Any], user: Dict[str, Any]) -> str:
    """Return an address proved by an identity provider, never request input."""
    for row in account_auth._identities_for_user(doc, user):
        if str(row.get("provider") or "") == "email" and row.get("verified_at_utc"):
            return str(row.get("provider_subject") or "").strip().lower()
    # A linked Google identity is allowed to prove ownership of its verified
    # address, but the confirmation channel is still presented as Email. The
    # user never has to understand an internal "google email factor".
    if account_auth.google_linked(user) and user.get("email_verified_at_utc"):
        return str(user.get("google_email") or user.get("email") or "").strip().lower()
    return ""


def _available_providers(
    doc: Dict[str, Any], user: Dict[str, Any], *, purpose: str = "",
) -> List[str]:
    providers: List[str] = []
    if account_auth._telegram_subject_for_user(doc, user) > 0:
        providers.append("telegram")
    if _verified_email_target(doc, user):
        providers.append("email")
    # Keep the legacy Google-named factor for non-device step-up callers. A
    # device confirmation itself offers only Telegram or verified Email.
    if (purpose != PURPOSE_DEVICE_CONFIRM and account_auth.google_linked(user)
            and str(user.get("google_email") or "").strip()):
        providers.append("google")
    return providers


def _mask_channel_target(provider: str, target: str) -> str:
    value = str(target or "").strip()
    if not value:
        return ""
    if provider in {"email", "google"} and "@" in value:
        local, domain = value.split("@", 1)
        shown = (local[:1] + "***") if local else "***"
        return f"{shown}@{domain}"
    digits = "".join(ch for ch in value if ch.isdigit())
    return ("•••" + digits[-2:]) if digits else "•••"


def _confirmation_channels(doc: Dict[str, Any], user: Dict[str, Any]) -> List[Dict[str, str]]:
    rows = []
    for provider in _available_providers(doc, user, purpose=PURPOSE_DEVICE_CONFIRM):
        target = _delivery_target(doc, user, provider)
        rows.append({
            "provider": provider,
            "label": "Telegram" if provider == "telegram" else "Email",
            "masked_target": _mask_channel_target(provider, target),
        })
    return rows


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


# --------------------------------------------------------------------------- #
# Challenge delivery.
#
# The code is generated here, so it must also be *sent* from here: a challenge
# whose code was never delivered is unusable, and reporting it as created would
# be a false success. Delivery targets are resolved from server-side identity
# state only — a client never names the address a code is sent to.
# --------------------------------------------------------------------------- #
_TELEGRAM_TOKEN_ENV = "NTA_TELEGRAM_BOT_TOKEN"

_DELIVERY_PURPOSE_TEXT = {
    PURPOSE_DEVICE_CONFIRM: "подтверждения нового устройства",
    PURPOSE_STEP_UP: "подтверждения действия",
    PURPOSE_REVOKE: "отзыва устройства",
}


def _delivery_target(doc: Dict[str, Any], user: Dict[str, Any], provider: str) -> str:
    """Address for ``provider``, taken from verified identity state only."""
    if provider == "telegram":
        subject = account_auth._telegram_subject_for_user(doc, user)
        return str(subject) if subject > 0 else ""
    if provider == "email":
        return _verified_email_target(doc, user)
    if provider == "google":
        return str(user.get("google_email") or "").strip()
    return ""


def _telegram_configured() -> bool:
    return bool(str(os.environ.get(_TELEGRAM_TOKEN_ENV) or "").strip())


def _delivery_unavailable(reason: str) -> "SecurityDeviceError":
    # ``reason`` names the missing configuration for the audit log only; the
    # caller-visible message and code stay generic.
    exc = SecurityDeviceError(
        "Доставка кода подтверждения недоступна. Обратитесь к владельцу.",
        503, code="challenge_delivery_unavailable",
    )
    exc.detail = str(reason or "")
    return exc


def _delivery_failed() -> "SecurityDeviceError":
    return SecurityDeviceError(
        "Не удалось отправить код подтверждения. Повторите попытку позже.",
        503, code="challenge_delivery_failed",
    )


def _challenge_code_text(code: str, purpose: str, *, ttl_sec: int = CHALLENGE_TTL_SEC) -> str:
    what = _DELIVERY_PURPOSE_TEXT.get(purpose, "подтверждения")
    minutes = max(1, (int(ttl_sec) + 59) // 60)
    return (
        f"{runtime_env.telegram_environment_marker()}Код для {what}: {code}\n\n"
        f"Код действителен {minutes} минут и используется один раз.\n"
        "Если вы этого не запрашивали — не вводите код и отзовите устройство "
        "в разделе «Безопасность»."
    )


def _deliver_telegram_code(
    chat_id: str, code: str, *, purpose: str, ttl_sec: int = CHALLENGE_TTL_SEC,
) -> Dict[str, Any]:
    from . import telegram_service

    try:
        target = int(chat_id)
    except (TypeError, ValueError):
        raise _delivery_unavailable("telegram_subject_invalid") from None
    # Provider errors can echo the bot token, so nothing from them reaches the
    # caller; the audit log records the outcome instead.
    try:
        result = telegram_service._api_call(  # noqa: SLF001
            "sendMessage",
            {"chat_id": target, "text": _challenge_code_text(code, purpose, ttl_sec=ttl_sec)},
        )
    except Exception:
        raise _delivery_failed() from None
    message_id = ""
    if isinstance(result, dict):
        message_id = str(result.get("message_id") or "")
    return {"provider": "telegram", "message_id": message_id}


def _deliver_challenge_code(
    *, provider: str, target: str, code: str, purpose: str,
    ttl_sec: int = CHALLENGE_TTL_SEC,
) -> Dict[str, Any]:
    """Send ``code`` over ``provider``. Raises rather than faking success."""
    if not target:
        raise SecurityDeviceError(
            "Этот канал подтверждения недоступен для аккаунта.",
            409, code="provider_unavailable",
        )
    if provider == "telegram":
        if not _telegram_configured():
            raise _delivery_unavailable("telegram_not_configured")
        return _deliver_telegram_code(target, code, purpose=purpose, ttl_sec=ttl_sec)
    if provider in {"email", "google"}:
        if not account_auth._email_provider_live():
            raise _delivery_unavailable("email_provider_not_configured")
        try:
            receipt = account_auth._deliver_email_code(
                target, code, purpose=purpose, ttl_sec=ttl_sec,
            )
        except account_auth.AccountAuthError:
            raise _delivery_failed() from None
        return {
            "provider": str(receipt.get("provider") or "email"),
            "message_id": str(receipt.get("message_id") or ""),
        }
    raise SecurityDeviceError(
        "Этот канал подтверждения недоступен для аккаунта.",
        409, code="provider_unavailable",
    )


def _fail_challenge(challenge_id: str, *, reason: str) -> None:
    """Make an undelivered challenge permanently unusable."""
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        for row in _challenges(doc):
            if not isinstance(row, dict):
                continue
            if hmac.compare_digest(str(row.get("challenge_id") or ""), str(challenge_id)):
                row["status"] = "failed"
                row["failure_reason"] = str(reason or "")[:40]
                row["retain_until"] = _now() + _CHALLENGE_RETENTION_SEC
                break
        account_auth._write_doc(doc)


def _normalize_trust_mode(value: Any, *, required: bool = False) -> str:
    mode = str(value or "").strip().lower()
    if not mode and not required:
        return ""
    if not mode:
        return TRUST_MODE_PERMANENT
    if mode not in TRUST_MODES:
        raise SecurityDeviceError(
            "Выберите постоянный доступ или доступ до конца сессии.",
            400, code="trust_mode_invalid",
        )
    return mode


def _owned_session(
    doc: Dict[str, Any], *, user_id: int, session_id: str, live: bool = True,
) -> Dict[str, Any]:
    target = str(session_id or "").strip()
    if not target:
        raise SecurityDeviceError("Не указана текущая сессия.", 409, code="session_required")
    now = _now()
    for row in doc.get("sessions") or []:
        if not isinstance(row, dict):
            continue
        if int(row.get("user_id") or 0) != int(user_id):
            continue
        if not hmac.compare_digest(account_auth._session_id(row), target):
            continue
        if live and (row.get("revoked") or float(row.get("expires_at") or 0) <= now):
            raise SecurityDeviceError("Сессия уже завершена.", 401, code="session_expired")
        return row
    raise SecurityDeviceError("Сессия не найдена.", 404, code="session_not_found")


def create_challenge(
    *,
    user_id: Any,
    purpose: str,
    device_id: str = "",
    provider: str = "",
    action: str = "",
    ip: str = "",
    user_agent: str = "",
    trust_mode: str = "",
    session_id: str = "",
    _resend_count: int = 0,
) -> Dict[str, Any]:
    """Create a one-time, time-boxed, purpose/environment-bound challenge."""
    purpose_id = str(purpose or "").strip().lower()
    if purpose_id not in CHALLENGE_PURPOSES:
        raise SecurityDeviceError("Недопустимая цель подтверждения.", 400, code="purpose_invalid")
    provider_id = str(provider or "").strip().lower()
    mode = _normalize_trust_mode(
        trust_mode, required=purpose_id == PURPOSE_DEVICE_CONFIRM,
    )
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
        actor_session = None
        actor_session_id = str(session_id or "").strip()
        if actor_session_id:
            actor_session = _owned_session(
                doc, user_id=uid, session_id=actor_session_id,
            )
        if purpose_id in {PURPOSE_DEVICE_CONFIRM, PURPOSE_REVOKE}:
            device = _owned_device(doc, user_uuid, device_id)
            if purpose_id == PURPOSE_DEVICE_CONFIRM and device.get("status") != STATUS_PENDING:
                raise SecurityDeviceError(
                    "Устройство не в состоянии ожидания.", 409, code="device_not_pending",
                )
            if device.get("status") == STATUS_REVOKED:
                raise SecurityDeviceError("Устройство отозвано.", 409, code="device_revoked")
            target_device_id = str(device.get("device_id") or "")
        if (purpose_id == PURPOSE_DEVICE_CONFIRM and actor_session is not None
                and _session_confirmation_state(actor_session) == STATUS_PENDING
                and not hmac.compare_digest(
                    str(actor_session.get("trusted_device_id") or ""), target_device_id,
                )):
            raise SecurityDeviceError(
                "Сессия в ожидании может подтвердить только свой клиент.",
                403, code="session_device_mismatch",
            )
        if purpose_id == PURPOSE_DEVICE_CONFIRM and mode == TRUST_MODE_SESSION:
            if actor_session is None:
                raise SecurityDeviceError(
                    "Доступ до конца сессии можно выдать только текущей сессии.",
                    409, code="session_required",
                )
            if not hmac.compare_digest(
                str(actor_session.get("trusted_device_id") or ""), target_device_id,
            ):
                raise SecurityDeviceError(
                    "Текущая сессия принадлежит другому клиенту.",
                    409, code="session_device_mismatch",
                )
            if str(actor_session.get("device_confirmation_state") or STATUS_PENDING) != STATUS_PENDING:
                raise SecurityDeviceError(
                    "Эта сессия уже подтверждена.", 409, code="session_not_pending",
                )

        available = _available_providers(doc, user, purpose=purpose_id)
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

        delivery_target = _delivery_target(doc, user, provider_id)
        expires_at = now + CHALLENGE_TTL_SEC
        # A device OTP must never outlive the pending access it is meant to
        # unlock. For first-login confirmation the displayed countdown is
        # therefore the server's actual remaining window, not a client timer.
        if (purpose_id == PURPOSE_DEVICE_CONFIRM and actor_session is not None
                and hmac.compare_digest(
                    str(actor_session.get("trusted_device_id") or ""), target_device_id,
                ) and str(actor_session.get("device_confirmation_state") or "") == STATUS_PENDING):
            pending_until = float(actor_session.get("pending_expires_at") or 0)
            if pending_until:
                expires_at = min(expires_at, pending_until)
        if expires_at <= now:
            raise SecurityDeviceError(
                "Время подтверждения истекло. Войдите снова.",
                401, code="session_expired",
            )

        # One live code for the same actor/session and target. Switching the
        # channel or requesting another code burns the previous one so the UI
        # never has two apparently valid OTPs at once.
        for prior in _challenges(doc):
            if not isinstance(prior, dict) or str(prior.get("status") or "") != "pending":
                continue
            if str(prior.get("purpose") or "") != purpose_id:
                continue
            if not hmac.compare_digest(str(prior.get("device_id") or ""), target_device_id):
                continue
            if not hmac.compare_digest(str(prior.get("session_id") or ""), actor_session_id):
                continue
            prior["status"] = "failed"
            prior["failure_reason"] = "replaced"
            prior["retain_until"] = now + _CHALLENGE_RETENTION_SEC
        _challenges(doc).append({
            "challenge_id": challenge_id,
            "user_uuid": user_uuid,
            "legacy_user_id": uid,
            "device_id": target_device_id,
            "purpose": purpose_id,
            "provider": provider_id,
            "trust_mode": mode,
            "session_id": actor_session_id,
            "action": str(action or "")[:40],
            "environment": environment,
            "code_salt": salt,
            "code_hash": _code_hash(challenge_id, salt, code),
            "status": "pending",
            "attempts": 0,
            "max_attempts": CHALLENGE_MAX_ATTEMPTS,
            "created_at_utc": account_auth._now_iso(),
            "expires_at": expires_at,
            "resend_available_at": now + CHALLENGE_RESEND_COOLDOWN_SEC,
            "resend_count": max(0, int(_resend_count or 0)),
        })
        account_auth._write_doc(doc)

    # Delivery runs outside the store lock (it is network I/O) but before the
    # challenge is reported as created: if the code cannot be sent, the pending
    # challenge is burned and the caller gets the failure instead of a code that
    # will never arrive.
    echo = _dev_code_echo()
    receipt: Dict[str, Any] = {}
    if not echo:
        try:
            receipt = _deliver_challenge_code(
                provider=provider_id, target=delivery_target,
                code=code, purpose=purpose_id,
                ttl_sec=max(1, int(expires_at - now)),
            )
        except SecurityDeviceError as exc:
            _fail_challenge(challenge_id, reason=exc.code or "delivery_failed")
            account_auth._audit(
                "security.challenge_delivery_failed",
                user_id=uid,
                ip=ip,
                extra={
                    "challenge_id": challenge_id,
                    "purpose": purpose_id,
                    "provider": provider_id,
                    "environment": environment,
                    "device_id": target_device_id,
                    "reason": exc.code,
                    "detail": getattr(exc, "detail", ""),
                },
            )
            raise

    delivery = (
        "preview_synthetic"
        if echo and runtime_env.preview_sandbox_enabled()
        else "development_test" if echo
        else str(receipt.get("provider") or provider_id)
    )
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
            "delivery": delivery,
            "message_id": str(receipt.get("message_id") or ""),
        },
    )
    out = {
        "ok": True,
        "challenge_id": challenge_id,
        "purpose": purpose_id,
        "provider": provider_id,
        "trust_mode": mode,
        "environment": environment,
        "expires_in_sec": max(1, int(expires_at - now)),
        "expires_at_utc": _iso_from_epoch(expires_at),
        "resend_available_in_sec": CHALLENGE_RESEND_COOLDOWN_SEC,
        "masked_target": _mask_channel_target(provider_id, delivery_target),
        "delivery": delivery,
    }
    # The one-time code is only ever disclosed behind the explicit Development
    # test-auth gate; every other environment receives it out-of-band above.
    if echo:
        out["test_code"] = code
    return out


def resend_challenge(
    *, user_id: Any, challenge_id: str, session_id: str = "", ip: str = "",
) -> Dict[str, Any]:
    """Replace one device-confirmation code after a server-side cooldown."""
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise SecurityDeviceError("Требуется вход.", 401, code="auth_required")
    cid = str(challenge_id or "").strip()
    now = _now()
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, uid)
        if not user:
            raise SecurityDeviceError("Пользователь не найден.", 404, code="user_not_found")
        user_uuid = _normalize_uuid(account_auth._user_uuid(user))
        row = next((
            item for item in reversed(_challenges(doc))
            if isinstance(item, dict)
            and hmac.compare_digest(str(item.get("challenge_id") or ""), cid)
        ), None)
        if row is None or not hmac.compare_digest(
            _normalize_uuid(row.get("user_uuid")), user_uuid,
        ):
            raise SecurityDeviceError(
                "Запрос подтверждения не найден или истёк.",
                410, code="challenge_not_found",
            )
        if str(row.get("purpose") or "") != PURPOSE_DEVICE_CONFIRM:
            raise SecurityDeviceError(
                "Повторная отправка доступна только для подтверждения доступа.",
                409, code="challenge_wrong_purpose",
            )
        if str(row.get("status") or "") != "pending" or float(row.get("expires_at") or 0) <= now:
            raise SecurityDeviceError(
                "Запрос подтверждения уже завершён или истёк.",
                410, code="challenge_not_pending",
            )
        bound_session = str(row.get("session_id") or "")
        supplied_session = str(session_id or "")
        if bound_session and not hmac.compare_digest(bound_session, supplied_session):
            raise SecurityDeviceError(
                "Запрос создан в другой сессии.", 403, code="challenge_wrong_session",
            )
        retry_at = float(row.get("resend_available_at") or 0)
        if retry_at > now:
            wait = max(1, int(retry_at - now + 0.999))
            raise SecurityDeviceError(
                f"Новый код можно отправить через {wait} сек.",
                429, code="challenge_resend_cooldown",
            )
        count = int(row.get("resend_count") or 0)
        if count >= CHALLENGE_MAX_RESENDS:
            raise SecurityDeviceError(
                "Лимит повторной отправки исчерпан. Войдите снова.",
                429, code="challenge_resend_exhausted",
            )
        params = {
            "purpose": PURPOSE_DEVICE_CONFIRM,
            "device_id": str(row.get("device_id") or ""),
            "provider": str(row.get("provider") or ""),
            "trust_mode": str(row.get("trust_mode") or TRUST_MODE_PERMANENT),
            "session_id": bound_session,
            "action": str(row.get("action") or ""),
        }
        row["status"] = "failed"
        row["failure_reason"] = "resend"
        row["retain_until"] = now + _CHALLENGE_RETENTION_SEC
        account_auth._write_doc(doc)
    return create_challenge(
        user_id=uid, ip=ip, _resend_count=count + 1, **params,
    )


def _consume_challenge(
    doc: Dict[str, Any],
    *,
    challenge_id: str,
    code: str,
    user_uuid: str,
    purpose: str,
    device_id: str = "",
    trust_mode: str = "",
    session_id: str = "",
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
    bound_mode = str(challenge.get("trust_mode") or "")
    supplied_mode = str(trust_mode or "")
    if bound_mode and supplied_mode and not hmac.compare_digest(bound_mode, supplied_mode):
        raise SecurityDeviceError(
            "Подтверждение создано для другого режима доступа.",
            409, code="challenge_wrong_trust_mode",
        )
    bound_session = str(challenge.get("session_id") or "")
    supplied_session = str(session_id or "")
    if bound_session and not hmac.compare_digest(bound_session, supplied_session):
        raise SecurityDeviceError(
            "Подтверждение создано в другой сессии.",
            403, code="challenge_wrong_session",
        )

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
        "challenge_wrong_trust_mode", "challenge_wrong_session",
    }:
        event = "security.challenge_denied"
    else:
        return
    account_auth._audit(event, user_id=uid, ip=ip, extra={"challenge_id": challenge_id, "reason": code})


def _consume_and_persist(
    doc: Dict[str, Any], *, uid: int, ip: str, challenge_id: str, code: str,
    user_uuid: str, purpose: str, device_id: str = "",
    trust_mode: str = "", session_id: str = "",
) -> Tuple[Dict[str, Any], List[Tuple[str, Dict[str, Any]]]]:
    """Consume a challenge, persisting attempt/expiry state even on failure.

    A wrong or expired attempt must survive so the one-time-use and attempt-cap
    guarantees hold across retries; otherwise each failed try would read a fresh
    zeroed counter.
    """
    try:
        return _consume_challenge(
            doc, challenge_id=challenge_id, code=code, user_uuid=user_uuid,
            purpose=purpose, device_id=device_id, trust_mode=trust_mode,
            session_id=session_id,
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


def _session_confirmation_state(session: Dict[str, Any]) -> str:
    if session.get("device_confirmation_exempt"):
        return "active"
    explicit = str(session.get("device_confirmation_state") or "")
    if explicit == "active":
        return explicit
    if str(session.get("device_trust_status") or "") == STATUS_TRUSTED:
        return "active"
    pending_until = float(session.get("pending_expires_at") or 0)
    if not pending_until:
        pending_until = _epoch_from_iso(session.get("created_at_utc")) + PENDING_SESSION_TTL_SEC
    return STATUS_EXPIRED if pending_until and pending_until <= _now() else STATUS_PENDING


def _activate_session_access(session: Dict[str, Any], *, mode: str) -> None:
    now = _now()
    normal_expiry = float(session.get("normal_expires_at") or 0)
    if normal_expiry <= now:
        normal_expiry = now + account_auth.SESSION_TTL_SEC
    session["expires_at"] = normal_expiry
    session["normal_expires_at"] = normal_expiry
    session["device_confirmation_state"] = "active"
    session["device_trust_mode"] = mode
    session["device_trust_status"] = (
        STATUS_TRUSTED if mode == TRUST_MODE_PERMANENT else STATUS_PENDING
    )
    session["device_confirmed_at_utc"] = account_auth._now_iso()
    session["pending_expires_at"] = 0
    session["pending_expires_at_utc"] = ""


def _caller_cookie_should_persist(
    doc: Dict[str, Any], *, user_id: int, session_id: str,
    device_id: str, trust_mode: str,
) -> bool:
    """Only persist the cookie of the session that just trusted itself.

    An already-active session may approve a different pending Client from the
    Security page. That must never upgrade the approving session's browser
    cookie, especially when that session was granted current-session access.
    """
    if trust_mode != TRUST_MODE_PERMANENT or not str(session_id or "").strip():
        return False
    try:
        session = _owned_session(doc, user_id=user_id, session_id=session_id)
    except SecurityDeviceError:
        return False
    return (
        hmac.compare_digest(
            str(session.get("trusted_device_id") or ""), str(device_id or ""),
        )
        and _session_confirmation_state(session) == "active"
        and str(session.get("device_trust_mode") or "") == TRUST_MODE_PERMANENT
    )


def _apply_device_confirmation(
    doc: Dict[str, Any], *, user_id: int, user_uuid: str,
    device: Dict[str, Any], provider: str, trust_mode: str,
    session_id: str,
) -> Tuple[List[Tuple[str, Dict[str, Any]]], int]:
    """Apply permanent client trust or access for exactly one auth session."""
    mode = _normalize_trust_mode(trust_mode, required=True)
    device_id = str(device.get("device_id") or "")
    events: List[Tuple[str, Dict[str, Any]]] = []
    activated = 0
    if mode == TRUST_MODE_PERMANENT:
        _trust_device(device, provider=provider)
        for session in doc.get("sessions") or []:
            if not isinstance(session, dict) or session.get("revoked"):
                continue
            if int(session.get("user_id") or 0) != int(user_id):
                continue
            if not hmac.compare_digest(
                str(session.get("trusted_device_id") or ""), device_id,
            ):
                continue
            if float(session.get("expires_at") or 0) <= _now():
                continue
            _activate_session_access(session, mode=mode)
            activated += 1
        events.append(("device.approved", {
            "device_id": device_id,
            "provider": provider,
            "trust_mode": mode,
            "activated_sessions": activated,
        }))
        events.extend(_trust_machine_for(doc, user_uuid, device, provider=provider))
        return events, activated

    session = _owned_session(
        doc, user_id=user_id, session_id=session_id,
    )
    if not hmac.compare_digest(
        str(session.get("trusted_device_id") or ""), device_id,
    ):
        raise SecurityDeviceError(
            "Текущая сессия принадлежит другому клиенту.",
            409, code="session_device_mismatch",
        )
    if _session_confirmation_state(session) != STATUS_PENDING:
        raise SecurityDeviceError(
            "Эта сессия уже подтверждена или завершена.",
            409, code="session_not_pending",
        )
    _activate_session_access(session, mode=mode)
    device["last_session_confirmed_at_utc"] = account_auth._now_iso()
    device["last_session_confirmation_provider"] = str(provider or "")
    events.append(("device.session_approved", {
        "device_id": device_id,
        "session_id": session_id,
        "provider": provider,
        "trust_mode": mode,
    }))
    return events, 1


def _live_sessions_for_client(
    doc: Dict[str, Any], *, user_id: int, device_id: str,
) -> List[Dict[str, Any]]:
    now = _now()
    rows = []
    for session in doc.get("sessions") or []:
        if not isinstance(session, dict) or session.get("revoked"):
            continue
        if int(session.get("user_id") or 0) != int(user_id):
            continue
        if not hmac.compare_digest(
            str(session.get("trusted_device_id") or ""), str(device_id or ""),
        ):
            continue
        if float(session.get("expires_at") or 0) <= now:
            continue
        rows.append(session)
    return rows


def _public_session(session: Dict[str, Any], *, current_session_id: str = "") -> Dict[str, Any]:
    session_id = account_auth._session_id(session)
    state = _session_confirmation_state(session)
    return {
        "id": session_id,
        "session_id": session_id,
        "client_id": str(session.get("trusted_device_id") or ""),
        "physical_device_id": str(session.get("physical_device_id") or ""),
        "current": bool(current_session_id) and hmac.compare_digest(session_id, current_session_id),
        "state": state,
        "trust_mode": str(session.get("device_trust_mode") or (
            TRUST_MODE_PERMANENT
            if str(session.get("device_trust_status") or "") == STATUS_TRUSTED else ""
        )),
        "created_at_utc": str(session.get("created_at_utc") or ""),
        "expires_at_utc": _iso_from_epoch(float(session.get("expires_at") or 0)),
        "pending_expires_at_utc": str(session.get("pending_expires_at_utc") or ""),
        "client": str(session.get("client") or ""),
        "audit": {
            "masked_ip": str(session.get("ip") or ""),
            "location": str(session.get("location") or ""),
        },
        "actions": {"end_session": True},
    }


def _effective_client_access(
    device: Dict[str, Any], sessions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    status = str(device.get("status") or STATUS_PENDING)
    if status == STATUS_TRUSTED:
        return {"state": "active", "trust_mode": TRUST_MODE_PERMANENT, "expires_at_utc": ""}
    for session in sessions:
        if (_session_confirmation_state(session) == "active"
                and str(session.get("device_trust_mode") or "") == TRUST_MODE_SESSION):
            return {
                "state": "active",
                "trust_mode": TRUST_MODE_SESSION,
                "expires_at_utc": _iso_from_epoch(float(session.get("expires_at") or 0)),
            }
    if status == STATUS_PENDING:
        return {"state": STATUS_PENDING, "trust_mode": "", "expires_at_utc": ""}
    return {"state": status, "trust_mode": "", "expires_at_utc": ""}


def _normalized_client(
    doc: Dict[str, Any], device: Dict[str, Any], *, user_id: int,
    current_session_id: str, active_ids: frozenset,
) -> Dict[str, Any]:
    public = _public_device(device, active_ids)
    sessions = _live_sessions_for_client(
        doc, user_id=user_id, device_id=public["device_id"],
    )
    session_rows = [
        _public_session(row, current_session_id=current_session_id) for row in sessions
    ]
    session_rows.sort(key=lambda row: row["created_at_utc"], reverse=True)
    os_text = " ".join(filter(None, (public["os_family"], public["os_version"])))
    auto_name = public["client"] or "Web Browser"
    if os_text and os_text.lower() not in auto_name.lower():
        auto_name = f"{auto_name} · {os_text}"
    # A session row is one login of exactly this client, so it must carry the
    # client's current name. The raw session copy keeps the label parsed at
    # login time and would still show the old auto name after a rename.
    client_label = public["display_name"] or public["client"] or "Web Browser"
    for row in session_rows:
        row["client"] = client_label
    return {
        "id": public["device_id"],
        "device_id": public["device_id"],
        "display_name": public["display_name"] or public["client"] or "Web Browser",
        "auto_name": auto_name,
        "kind": "connector" if public["device_type"] == "connector" else "client",
        "device_type": public["device_type"],
        "client": public["client"],
        "os_family": public["os_family"],
        "os_version": public["os_version"],
        "app_version": public["app_version"],
        "status": public["status"],
        "access": _effective_client_access(device, sessions),
        "online": public["online"],
        "first_seen_at_utc": public["first_seen_at_utc"],
        "last_seen_at_utc": public["last_seen_at_utc"],
        "last_auth_at_utc": public["last_auth_at_utc"],
        "physical_device_id": public["physical_device_id"],
        "bound_via": public["bound_via"],
        "audit": {
            "masked_ip": public["last_region"],
            "location": public["location"],
            "last_seen_at": public["last_seen_at_utc"],
        },
        "sessions": session_rows,
        "active_sessions": len(session_rows),
        "actions": {
            "rename": public["status"] in _ACTIVE_STATUSES,
            "revoke": public["status"] in _ACTIVE_STATUSES,
        },
    }


def _normalized_access_catalog(
    doc: Dict[str, Any], user: Dict[str, Any], *, current_session_id: str = "",
) -> Dict[str, Any]:
    uid = int(user.get("user_id") or 0)
    user_uuid = _normalize_uuid(account_auth._user_uuid(user))
    active_ids = _active_device_ids(doc)
    owned = [
        row for row in _devices(doc)
        if isinstance(row, dict)
        and hmac.compare_digest(_normalize_uuid(row.get("user_uuid")), user_uuid)
    ]
    clients = [
        _normalized_client(
            doc, row, user_id=uid, current_session_id=current_session_id,
            active_ids=active_ids,
        ) for row in owned
    ]
    clients_by_machine: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    standalone = []
    for client in clients:
        machine_id = str(client.get("physical_device_id") or "")
        if machine_id:
            clients_by_machine[machine_id].append(client)
        else:
            standalone.append(client)

    machines = []
    for machine in physical_devices._machines(doc):
        if not isinstance(machine, dict):
            continue
        if not hmac.compare_digest(_normalize_uuid(machine.get("user_uuid")), user_uuid):
            continue
        public = physical_devices.public_machine(machine)
        machine_clients = clients_by_machine.get(public["physical_device_id"], [])
        machine_clients.sort(key=lambda row: row["last_seen_at_utc"], reverse=True)
        machines.append({
            "id": public["physical_device_id"],
            "physical_device_id": public["physical_device_id"],
            "display_name": public["display_name"],
            "auto_name": " ".join(filter(None, (public["os_family"], public["os_version"]))) or "Компьютер",
            "device_type": "computer",
            "trust": {
                "status": public["status"],
                "mode": TRUST_MODE_PERMANENT if public["status"] == STATUS_TRUSTED else "",
                "expires_at": None,
            },
            "audit": {
                "masked_ip": public["last_region"],
                "location": str((machine.get("audit_metadata") or {}).get("location") or ""),
                "last_seen_at": public["last_seen_at_utc"],
            },
            "first_seen_at_utc": public["first_seen_at_utc"],
            "last_seen_at_utc": public["last_seen_at_utc"],
            "clients": machine_clients,
            "actions": {
                "rename": public["status"] in physical_devices.ACTIVE_STATUSES,
                "revoke": public["status"] in physical_devices.ACTIVE_STATUSES,
            },
        })
    machines.sort(key=lambda row: row["last_seen_at_utc"], reverse=True)
    standalone.sort(key=lambda row: row["last_seen_at_utc"], reverse=True)
    sessions = [session for client in clients for session in client["sessions"]]
    sessions.sort(key=lambda row: row["created_at_utc"], reverse=True)
    history = []
    for row in reversed(user.get("login_history") or []):
        if not isinstance(row, dict):
            continue
        history.append({
            "at_utc": str(row.get("at") or ""),
            "source": str(row.get("source") or ""),
            "client": str(row.get("device") or ""),
            "masked_ip": str(row.get("ip") or ""),
        })
    return {
        "machines": machines,
        "standalone_clients": standalone,
        "sessions": sessions,
        "login_history": history[:20],
        "grouping_policy": {
            "machine_identity": "hardware_bound_connector",
            "allowed_bindings": list(physical_devices.BINDING_METHODS),
            "ip_or_user_agent_is_identity": False,
            "unbound_clients_are_devices": False,
        },
    }


def _current_session_access(
    doc: Dict[str, Any], user: Dict[str, Any], *, session_id: str,
) -> Dict[str, Any]:
    uid = int(user.get("user_id") or 0)
    session = _owned_session(doc, user_id=uid, session_id=session_id)
    device_id = str(session.get("trusted_device_id") or "")
    device = _owned_device(doc, account_auth._user_uuid(user), device_id)
    public = _public_device(device, _active_device_ids(doc))
    state = _session_confirmation_state(session)
    machine = None
    physical_id = str(device.get("physical_device_id") or "")
    if physical_id:
        found = physical_devices.find_machine(doc, account_auth._user_uuid(user), physical_id)
        if found is not None:
            machine = physical_devices.public_machine(found)
    pending_until = float(session.get("pending_expires_at") or 0)
    return {
        "required": state == STATUS_PENDING,
        "state": state,
        "trust_mode": str(session.get("device_trust_mode") or ""),
        "session_id": account_auth._session_id(session),
        "session_expires_at_utc": _iso_from_epoch(float(session.get("expires_at") or 0)),
        "pending_expires_at_utc": (
            str(session.get("pending_expires_at_utc") or "")
            or (_iso_from_epoch(pending_until) if pending_until else "")
        ),
        "pending_expires_in_sec": max(0, int(pending_until - _now())) if pending_until else 0,
        "client": {
            "id": public["device_id"],
            "display_name": public["display_name"] or public["client"] or "Web Browser",
            "client": public["client"] or "Web Browser",
            "device_type": public["device_type"],
            "os_family": public["os_family"],
            "os_version": public["os_version"],
            "physical_device_id": public["physical_device_id"],
            "bound_via": public["bound_via"],
            "audit": {
                "masked_ip": public["last_region"],
                "location": public["location"],
                "first_seen_at": public["first_seen_at_utc"],
                "last_seen_at": public["last_seen_at_utc"],
            },
        },
        "machine": machine,
        "confirmation_channels": _confirmation_channels(doc, user),
        "policy": {
            "pending_ttl_sec": PENDING_SESSION_TTL_SEC,
            "trust_modes": list(TRUST_MODES),
            "permanent_until_revoke": True,
            "session_only_inherits": False,
        },
    }


def current_session_access(user_id: Any, session_id: str) -> Dict[str, Any]:
    uid = _require_uid(user_id)
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, uid)
        if not user:
            raise SecurityDeviceError("Пользователь не найден.", 404, code="user_not_found")
        return _current_session_access(doc, user, session_id=str(session_id or ""))


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


def account_security(user_id: Any, *, current_session_id: str = "") -> Dict[str, Any]:
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
        machines = physical_devices.list_machines(doc, user_uuid)
        catalog = _normalized_access_catalog(
            doc, user, current_session_id=str(current_session_id or ""),
        )
    devices.sort(key=lambda item: str(item.get("last_seen_at_utc") or ""), reverse=True)
    return {
        "ok": True,
        "identity_model": "uuid",
        "user_uuid": user_uuid,
        "identities": identities,
        "step_up_providers": providers,
        # Three levels, reported separately. ``devices`` are clients (browser
        # profiles and app installations); ``physical_devices`` are the machines
        # some of them are known to run on.
        "devices": devices,
        "physical_devices": machines,
        # Canonical machine -> client -> session projection for the current
        # Security UI. The legacy flat fields above remain during the API
        # compatibility window for older clients.
        "machines": catalog["machines"],
        "standalone_clients": catalog["standalone_clients"],
        "sessions": catalog["sessions"],
        "login_history": catalog["login_history"],
        "grouping_policy": catalog["grouping_policy"],
        "confirmation_channels": _confirmation_channels(doc, user),
        "policy": {
            "device_confirmation_required": True,
            "challenge_ttl_sec": CHALLENGE_TTL_SEC,
            "pending_session_ttl_sec": PENDING_SESSION_TTL_SEC,
            "trust_modes": list(TRUST_MODES),
            "permanent_until_revoke": True,
            "session_only_inherits": False,
            "trust_ttl_sec": None,
            "pairing_ttl_sec": physical_devices.PAIRING_TTL_SEC,
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
    session_id: str = "",
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
        challenge_mode = str((pending or {}).get("trust_mode") or TRUST_MODE_PERMANENT)
        challenge_session = str((pending or {}).get("session_id") or "")
        # A session-bound device challenge must be confirmed by the caller's
        # actual session. Never fill a missing caller id from the challenge
        # itself: doing so would turn possession of the OTP into a bearer token
        # that could be replayed from another authenticated session.
        supplied_session = str(session_id or "")
        challenge, events = _consume_and_persist(
            doc, uid=uid, ip=ip, challenge_id=cid, code=code,
            user_uuid=user_uuid, purpose=purpose,
            trust_mode=challenge_mode, session_id=supplied_session,
        )
        result: Dict[str, Any] = {"ok": True, "purpose": purpose}
        if purpose == PURPOSE_DEVICE_CONFIRM:
            device = _owned_device(doc, user_uuid, str(challenge.get("device_id") or ""))
            provider = str(challenge.get("provider") or "")
            applied, activated = _apply_device_confirmation(
                doc, user_id=uid, user_uuid=user_uuid, device=device,
                provider=provider, trust_mode=challenge_mode,
                session_id=supplied_session,
            )
            events.extend(applied)
            result["device"] = _public_device(device)
            result["trust_mode"] = challenge_mode
            result["activated_sessions"] = activated
            result["session_cookie_persistent"] = _caller_cookie_should_persist(
                doc, user_id=uid, session_id=supplied_session,
                device_id=str(device.get("device_id") or ""),
                trust_mode=challenge_mode,
            )
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
    device["trust_mode"] = TRUST_MODE_PERMANENT
    device["confirmation_provider"] = str(provider or "")
    device["confirmed_at_utc"] = account_auth._now_iso()
    device["expires_at"] = 0
    device["expires_at_utc"] = ""
    device["revoked_at_utc"] = ""


def _clean_display_name(value: Any) -> str:
    name = " ".join(str(value or "").strip().split())
    if not 1 <= len(name) <= 80 or any(ord(ch) < 32 for ch in name):
        raise SecurityDeviceError(
            "Название должно содержать от 1 до 80 символов.",
            400, code="display_name_invalid",
        )
    return name


def rename_device(
    *, user_id: Any, device_id: str, display_name: str, ip: str = "",
) -> Dict[str, Any]:
    uid = _require_uid(user_id)
    name = _clean_display_name(display_name)
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, uid)
        if not user:
            raise SecurityDeviceError("Пользователь не найден.", 404, code="user_not_found")
        device = _owned_device(doc, account_auth._user_uuid(user), device_id)
        if str(device.get("status") or "") not in _ACTIVE_STATUSES:
            raise SecurityDeviceError(
                "Завершённый клиент нельзя переименовать.",
                409, code="client_inactive",
            )
        before = str(device.get("display_name") or "")
        device["display_name"] = name
        device["renamed_at_utc"] = account_auth._now_iso()
        account_auth._write_doc(doc)
        public = _public_device(device, _active_device_ids(doc))
    account_auth._audit(
        "device.renamed", user_id=uid, ip=ip,
        extra={"device_id": public["device_id"], "before": before, "after": name},
    )
    return {"ok": True, "device": public}


def rename_physical_device(
    *, user_id: Any, physical_device_id: str, display_name: str, ip: str = "",
) -> Dict[str, Any]:
    uid = _require_uid(user_id)
    name = _clean_display_name(display_name)
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, uid)
        if not user:
            raise SecurityDeviceError("Пользователь не найден.", 404, code="user_not_found")
        try:
            machine = physical_devices._owned(
                doc, account_auth._user_uuid(user), physical_device_id,
            )
        except physical_devices.PhysicalDeviceError as exc:
            raise _as_device_error(exc) from None
        if str(machine.get("status") or "") not in physical_devices.ACTIVE_STATUSES:
            raise SecurityDeviceError(
                "Завершённое устройство нельзя переименовать.",
                409, code="machine_inactive",
            )
        before = str(machine.get("display_name") or "")
        machine["display_name"] = name
        machine["renamed_at_utc"] = account_auth._now_iso()
        account_auth._write_doc(doc)
        public = physical_devices.public_machine(
            machine,
            clients=physical_devices.clients_on(doc, physical_device_id),
        )
    account_auth._audit(
        "machine.renamed", user_id=uid, ip=ip,
        extra={"physical_device_id": public["physical_device_id"], "before": before, "after": name},
    )
    return {"ok": True, "machine": public}


def _trust_machine_for(
    doc: Dict[str, Any], user_uuid: str, device: Dict[str, Any], *, provider: str,
) -> List[Tuple[str, Dict[str, Any]]]:
    """Confirming a Connector confirms the machine it proves it runs on.

    The Connector is the only client whose credential is bound to hardware, and
    confirming it already required a code delivered over a channel the account
    has verified. That is exactly the evidence a machine needs, so there is no
    separate machine-confirmation ceremony to sit through.

    It does not work the other way round: confirming a browser says nothing
    about any machine, and a trusted machine never confers trust on the clients
    running on it.
    """
    if str(device.get("bound_via") or "") != physical_devices.BOUND_VIA_CONNECTOR_SELF:
        return []
    machine = physical_devices.find_machine(
        doc, user_uuid, str(device.get("physical_device_id") or ""),
    )
    if machine is None or str(machine.get("status") or "") != physical_devices.STATUS_PENDING:
        return []
    physical_devices.trust_machine(machine, provider=provider)
    return [("machine.approved", {
        "physical_device_id": machine["physical_device_id"],
        "provider": provider,
    })]


def approve_device(
    *,
    user_id: Any,
    device_id: str,
    challenge_id: str,
    code: str,
    ip: str = "",
    trust_mode: str = TRUST_MODE_PERMANENT,
    session_id: str = "",
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
        mode = _normalize_trust_mode(trust_mode, required=True)
        challenge, events = _consume_and_persist(
            doc, uid=uid, ip=ip, challenge_id=challenge_id, code=code,
            user_uuid=user_uuid, purpose=PURPOSE_DEVICE_CONFIRM,
            device_id=str(device.get("device_id") or ""),
            trust_mode=mode, session_id=str(session_id or ""),
        )
        provider = str(challenge.get("provider") or "")
        applied, activated = _apply_device_confirmation(
            doc, user_id=uid, user_uuid=user_uuid, device=device,
            provider=provider, trust_mode=mode, session_id=str(session_id or ""),
        )
        events.extend(applied)
        persist_cookie = _caller_cookie_should_persist(
            doc, user_id=uid, session_id=str(session_id or ""),
            device_id=str(device.get("device_id") or ""), trust_mode=mode,
        )
        account_auth._write_doc(doc)
        public = _public_device(device)
    for event, extra in events:
        account_auth._audit(event, user_id=uid, ip=ip, extra=extra)
    return {
        "ok": True,
        "device": public,
        "trust_mode": mode,
        "activated_sessions": activated,
        "session_cookie_persistent": persist_cookie,
    }


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


# --------------------------------------------------------------------------- #
# Machine-level APIs.
#
# Deliberately separate entry points rather than flags on the device ones: the
# blast radius differs by an order of magnitude, and an operator reading an
# audit log should never have to work out which one a single "revoke" meant.
# --------------------------------------------------------------------------- #
def _account(doc: Dict[str, Any], uid: int) -> Tuple[Dict[str, Any], str]:
    user = account_auth._user(doc, uid)
    if not user:
        raise SecurityDeviceError("Пользователь не найден.", 404, code="user_not_found")
    return user, _normalize_uuid(account_auth._user_uuid(user))


def _as_device_error(exc: "physical_devices.PhysicalDeviceError") -> SecurityDeviceError:
    """Machine-level failures leave this module as SecurityDeviceError.

    The HTTP layer maps that one type to a status and an error code; letting
    PhysicalDeviceError escape turned an ordinary 404 into an unhandled 500.
    """
    return SecurityDeviceError(str(exc), exc.status, code=exc.code)


def _require_uid(user_id: Any) -> int:
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise SecurityDeviceError("Требуется вход.", 401, code="auth_required")
    return uid


def list_physical_devices(user_id: Any) -> Dict[str, Any]:
    uid = _require_uid(user_id)
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        _, user_uuid = _account(doc, uid)
        if _expire_stale(doc):
            account_auth._write_doc(doc)
        machines = physical_devices.list_machines(doc, user_uuid)
    return {"ok": True, "physical_devices": machines}


def revoke_physical_device(
    *, user_id: Any, physical_device_id: str, ip: str = "",
) -> Dict[str, Any]:
    """Revoke a machine and everything running on it.

    Unlike ``revoke_device`` this cascades on purpose: the user is saying the
    machine itself is out of their control, so every client bound to it and
    every session those clients hold has to die in the same action. A client
    they had to revoke one at a time is a client they can miss.
    """
    uid = _require_uid(user_id)
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        _, user_uuid = _account(doc, uid)
        try:
            machine = physical_devices._owned(doc, user_uuid, physical_device_id)
        except physical_devices.PhysicalDeviceError as exc:
            raise _as_device_error(exc) from None
        if machine.get("status") == physical_devices.STATUS_REVOKED:
            return {
                "ok": True,
                "physical_device": physical_devices.public_machine(machine),
                "revoked_clients": 0,
                "revoked_sessions": 0,
            }
        counts = physical_devices.revoke_machine(doc, machine, reason="machine_revoked")
        account_auth._write_doc(doc)
        public = physical_devices.public_machine(machine)
    account_auth._audit(
        "machine.revoked", user_id=uid, ip=ip,
        extra={
            "physical_device_id": public["physical_device_id"],
            "clients": counts["clients"],
            "sessions": counts["sessions"],
        },
    )
    return {
        "ok": True,
        "physical_device": public,
        "revoked_clients": counts["clients"],
        "revoked_sessions": counts["sessions"],
    }


def issue_pairing_code(
    *, user_id: Any, device_id: str, ip: str = "",
) -> Dict[str, Any]:
    """A trusted Connector mints a one-time code to pair a browser to its machine.

    ``device_id`` must be the calling Connector's own client record, and it must
    be trusted: an unconfirmed Connector handing out machine membership would
    make its own confirmation pointless.
    """
    uid = _require_uid(user_id)
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user, user_uuid = _account(doc, uid)
        if user.get("status") != "active":
            raise SecurityDeviceError("Аккаунт не активен.", 403, code="account_inactive")
        device = _owned_device(doc, user_uuid, device_id)
        if str(device.get("bound_via") or "") != physical_devices.BOUND_VIA_CONNECTOR_SELF:
            raise SecurityDeviceError(
                "Код привязки выдаёт только Connector этого компьютера.",
                409, code="pairing_requires_connector",
            )
        if device.get("status") != STATUS_TRUSTED:
            raise SecurityDeviceError(
                "Connector не подтверждён.", 409, code="device_not_trusted",
            )
        try:
            machine = physical_devices._owned(
                doc, user_uuid, str(device.get("physical_device_id") or ""),
            )
            code, row = physical_devices.issue_pairing_code(
                doc, user_uuid=user_uuid, machine=machine,
                issuing_client_id=str(device.get("device_id") or ""),
            )
        except physical_devices.PhysicalDeviceError as exc:
            raise _as_device_error(exc) from None
        account_auth._write_doc(doc)
        machine_id = str(machine.get("physical_device_id") or "")
    account_auth._audit(
        "machine.pairing_issued", user_id=uid, ip=ip,
        extra={"physical_device_id": machine_id, "pairing_id": row["pairing_id"]},
    )
    # The code is returned exactly once, to the Connector that asked for it, and
    # only its PBKDF2 hash was stored.
    return {
        "ok": True,
        "code": code,
        "expires_in_sec": physical_devices.PAIRING_TTL_SEC,
        "physical_device_id": machine_id,
    }


def redeem_pairing_code(
    *, user_id: Any, device_id: str, code: str, ip: str = "",
) -> Dict[str, Any]:
    """Bind this browser client to the machine that issued ``code``.

    Membership only. The client's own trust state is untouched: a browser that
    joins a trusted machine is still an unconfirmed client and still has to pass
    device confirmation before it counts as trusted.
    """
    uid = _require_uid(user_id)
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user, user_uuid = _account(doc, uid)
        if user.get("status") != "active":
            raise SecurityDeviceError("Аккаунт не активен.", 403, code="account_inactive")
        device = _owned_device(doc, user_uuid, device_id)
        if device.get("status") not in _ACTIVE_STATUSES:
            raise SecurityDeviceError(
                "Устройство отозвано.", 409, code="device_revoked",
            )
        if str(device.get("physical_device_id") or ""):
            raise SecurityDeviceError(
                "Устройство уже привязано к компьютеру.", 409, code="device_already_bound",
            )
        try:
            machine = physical_devices.redeem_pairing_code(
                doc, user_uuid=user_uuid, code=code, client=device,
            )
        except physical_devices.PhysicalDeviceError as exc:
            # A wrong guess still has to be *recorded*. Raising straight out of
            # here discarded the incremented attempt counter with the unwritten
            # document, so the per-code budget never accumulated and an
            # eight-digit code could be guessed without limit. Only counters
            # changed on this path -- binding happens after the code matches.
            account_auth._write_doc(doc)
            raise _as_device_error(exc) from None
        account_auth._write_doc(doc)
        public = _public_device(device)
        machine_id = str(machine.get("physical_device_id") or "")
    account_auth._audit(
        "machine.client_bound", user_id=uid, ip=ip,
        extra={"physical_device_id": machine_id, "device_id": public["device_id"]},
    )
    return {"ok": True, "device": public, "physical_device_id": machine_id}
