"""Phase 5: personal NinjaTrader security.

Connecting a personal NinjaTrader and other critical account/NT actions require
two independent factors — a confirmed Telegram identity and a verified email —
plus a fresh step-up confirmation. A safely linked Google verified email may act
as the email factor; Telegram remains a mandatory, independent second channel.

Step-up reuses the Phase 4 security-challenge machinery: a confirmed ``step_up``
challenge becomes a single-use grant bound to (user UUID, action, deployment
environment). A named critical action consumes exactly one matching grant. Grants
cannot be replayed, reused for another action, moved across environments, or used
by another account. Owners are exempt; a Development test-auth helper issues a
grant without a real code so owner/developer tests are never hard-blocked.
"""
from __future__ import annotations

import hmac
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import account_auth, auth_identity, runtime_env, security_devices


# Critical actions that require a personal-NT step-up grant.
ACTION_PAIRING = "pairing"
ACTION_CONNECTOR_REVOKE = "connector_revoke"
ACTION_DEFAULT_ACCOUNT = "default_account"
ACTION_TRADING_CAPABILITY = "trading_capability"
ACTION_RECOVERY = "recovery"
ACTION_UNLINK_METHOD = "unlink_method"
CRITICAL_ACTIONS = (
    ACTION_PAIRING,
    ACTION_CONNECTOR_REVOKE,
    ACTION_DEFAULT_ACCOUNT,
    ACTION_TRADING_CAPABILITY,
    ACTION_RECOVERY,
    ACTION_UNLINK_METHOD,
)

# Actions that additionally require both personal-NT factors to be present
# before they may proceed. Access-reducing actions (revoke, unlink) require only
# a step-up so a user who lost a factor can still lock things down.
FACTOR_REQUIRED_ACTIONS = frozenset({
    ACTION_PAIRING,
    ACTION_DEFAULT_ACCOUNT,
    ACTION_TRADING_CAPABILITY,
})

# A confirmed step-up grant is valid for this long after the challenge was
# consumed, then it can no longer authorize an action.
STEP_UP_GRANT_TTL_SEC = 10 * 60


class PersonalNtSecurityError(RuntimeError):
    def __init__(
        self, message: str, status: int = 403, *, code: str = "",
        onboarding: Optional[Dict[str, Any]] = None, action: str = "",
    ):
        super().__init__(message)
        self.status = int(status)
        self.code = str(code or "")
        self.onboarding = onboarding
        self.action = str(action or "")


def _normalize_uuid(value: Any) -> str:
    return auth_identity.normalize_user_uuid(value)


def _current_environment() -> str:
    try:
        return runtime_env.deployment_environment()
    except Exception:
        return "development"


def _iso_to_epoch(value: Any) -> float:
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


# --------------------------------------------------------------------------- #
# Factor predicates.
# --------------------------------------------------------------------------- #
def has_confirmed_telegram(doc: Dict[str, Any], user: Dict[str, Any]) -> bool:
    """A confirmed Telegram identity is bound to this account."""
    return account_auth._telegram_subject_for_user(doc, user) > 0


def verified_email_factor(doc: Dict[str, Any], user: Dict[str, Any]) -> Tuple[bool, str]:
    """Whether the account has a verified email factor and which provider proves it.

    A verified email login identity satisfies it directly. A safely linked Google
    account with a verified email also satisfies the email factor (but never the
    independent Telegram factor).
    """
    for row in account_auth._identities_for_user(doc, user):
        provider = str(row.get("provider") or "")
        if provider == "email" and row.get("verified_at_utc"):
            return True, "email"
        if provider == "google" and row.get("verified_at_utc"):
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            verified_email = str(metadata.get("email") or user.get("google_email") or "").strip()
            if "@" in verified_email:
                return True, "google"
    return False, ""


def email_factor_ok(doc: Dict[str, Any], user: Dict[str, Any]) -> bool:
    return verified_email_factor(doc, user)[0]


# --------------------------------------------------------------------------- #
# Security posture / onboarding.
# --------------------------------------------------------------------------- #
def _posture(doc: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
    is_owner = bool(user.get("is_owner"))
    telegram_ok = is_owner or has_confirmed_telegram(doc, user)
    email_ok, via = (True, "owner") if is_owner else verified_email_factor(doc, user)
    missing: List[str] = []
    onboarding: List[Dict[str, str]] = []
    if not telegram_ok:
        missing.append("telegram")
        onboarding.append({
            "factor": "telegram",
            "title": "Подтвердите Telegram",
            "message": "Привяжите и подтвердите Telegram — это обязательный независимый фактор для личного NinjaTrader.",
        })
    if not email_ok:
        missing.append("email")
        onboarding.append({
            "factor": "email",
            "title": "Подтвердите e-mail",
            "message": "Подтвердите e-mail по одноразовому коду или привяжите Google с подтверждённым e-mail. Это не SMS.",
        })
    return {
        "ok": True,
        "is_owner": is_owner,
        "factors": {"telegram": telegram_ok, "email": email_ok},
        "email_factor_via": via,
        "ready": telegram_ok and email_ok,
        "missing": missing,
        "onboarding": onboarding,
        "critical_actions": list(CRITICAL_ACTIONS),
        "step_up_grant_ttl_sec": STEP_UP_GRANT_TTL_SEC,
        "policy": "owner_exempt" if is_owner else "personal_nt_factors",
    }


def security_posture(user_id: Any) -> Dict[str, Any]:
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise PersonalNtSecurityError("Требуется вход.", 401, code="auth_required")
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, uid)
        if not user:
            raise PersonalNtSecurityError("Пользователь не найден.", 404, code="user_not_found")
        return _posture(doc, user)


# --------------------------------------------------------------------------- #
# Step-up: begin / consume grant.
# --------------------------------------------------------------------------- #
def _validate_action(action: Any) -> str:
    action_id = str(action or "").strip().lower()
    if action_id not in CRITICAL_ACTIONS:
        raise PersonalNtSecurityError("Недопустимое действие step-up.", 400, code="action_invalid")
    return action_id


def begin_step_up(
    user_id: Any, *, action: str, provider: str = "", ip: str = "", user_agent: str = "",
) -> Dict[str, Any]:
    """Start a step-up challenge for a named critical action."""
    action_id = _validate_action(action)
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise PersonalNtSecurityError("Требуется вход.", 401, code="auth_required")
    # Factor gate first so the user is guided through onboarding before a code.
    if action_id in FACTOR_REQUIRED_ACTIONS:
        require_ready(uid)
    try:
        out = security_devices.create_challenge(
            user_id=uid, purpose=security_devices.PURPOSE_STEP_UP,
            action=action_id, provider=provider, ip=ip, user_agent=user_agent,
        )
    except security_devices.SecurityDeviceError as exc:
        raise PersonalNtSecurityError(str(exc), exc.status, code=exc.code) from None
    out["action"] = action_id
    return out


def _find_grant(
    doc: Dict[str, Any], *, user_uuid: str, action: str, environment: str,
    challenge_id: str = "",
) -> Optional[Dict[str, Any]]:
    now = time.time()
    for row in reversed(doc.get("security_challenges") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("purpose") or "") != security_devices.PURPOSE_STEP_UP:
            continue
        if str(row.get("status") or "") != "consumed":
            continue
        if str(row.get("action") or "") != action:
            continue
        if row.get("step_up_used_at"):
            continue
        if not hmac.compare_digest(_normalize_uuid(row.get("user_uuid")), user_uuid):
            continue
        if str(row.get("environment") or "") != environment:
            continue
        if challenge_id and not hmac.compare_digest(str(row.get("challenge_id") or ""), challenge_id):
            continue
        consumed_epoch = _iso_to_epoch(row.get("consumed_at_utc"))
        if consumed_epoch and now > consumed_epoch + STEP_UP_GRANT_TTL_SEC:
            continue
        return row
    return None


def _reload_user(uid: int) -> Optional[Dict[str, Any]]:
    with account_auth._LOCK:
        stored = account_auth._user(account_auth._read_doc(), uid)
        return dict(stored) if stored is not None else None


# --------------------------------------------------------------------------- #
# Enforcement.
# --------------------------------------------------------------------------- #
def require_ready(user_id: Any) -> Dict[str, Any]:
    """Raise unless both personal-NT factors are present. Owner is exempt."""
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise PersonalNtSecurityError("Требуется вход.", 401, code="auth_required")
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, uid)
        if not user or user.get("status") != "active":
            raise PersonalNtSecurityError("Аккаунт не активен.", 403, code="account_inactive")
        posture = _posture(doc, user)
    if not posture["ready"]:
        raise PersonalNtSecurityError(
            "Для личного NinjaTrader нужны подтверждённые Telegram и e-mail.",
            403, code="personal_nt_onboarding_required", onboarding=posture,
        )
    return posture


def require_step_up(
    user_id: Any, *, action: str, challenge_id: str = "", ip: str = "",
) -> Dict[str, Any]:
    """Consume a single step-up grant for ``action``. Owner is exempt.

    Reloads the account from the encrypted store so a forged public payload
    cannot fake owner status or identity.
    """
    action_id = _validate_action(action)
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise PersonalNtSecurityError("Требуется вход.", 401, code="auth_required")
    environment = _current_environment()
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, uid)
        if not user or user.get("status") != "active":
            raise PersonalNtSecurityError("Аккаунт не активен.", 403, code="account_inactive")
        if user.get("is_owner"):
            return {"ok": True, "action": action_id, "owner_exempt": True}
        user_uuid = _normalize_uuid(account_auth._user_uuid(user))
        if not user_uuid:
            raise PersonalNtSecurityError("Профиль без UUID identity.", 409, code="identity_missing")
        grant = _find_grant(
            doc, user_uuid=user_uuid, action=action_id, environment=environment,
            challenge_id=str(challenge_id or ""),
        )
        if grant is None:
            raise PersonalNtSecurityError(
                "Требуется подтверждение действия (step-up).",
                403, code="step_up_required", action=action_id,
            )
        grant["step_up_used_at"] = account_auth._now_iso()
        account_auth._write_doc(doc)
        used_challenge = str(grant.get("challenge_id") or "")
    account_auth._audit(
        "security.step_up_consumed", user_id=uid, ip=ip,
        extra={"action": action_id, "challenge_id": used_challenge, "environment": environment},
    )
    return {"ok": True, "action": action_id, "challenge_id": used_challenge}


def require_ready_and_step_up(
    user_id: Any, *, action: str, challenge_id: str = "", ip: str = "",
) -> Dict[str, Any]:
    action_id = _validate_action(action)
    if action_id in FACTOR_REQUIRED_ACTIONS:
        require_ready(user_id)
    return require_step_up(user_id, action=action_id, challenge_id=challenge_id, ip=ip)


def grant_step_up_staging(user_id: Any, *, action: str) -> Dict[str, Any]:
    """Development test-auth helper: issue a consumed step-up grant.

    Lets owner/developer automated tests exercise critical actions without a real
    out-of-band code. Refuses outside the explicit Development test-auth gate.
    """
    runtime_env.require_test_auth()
    action_id = _validate_action(action)
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise PersonalNtSecurityError("Требуется вход.", 401, code="auth_required")
    environment = _current_environment()
    now_iso = account_auth._now_iso()
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, uid)
        if not user:
            raise PersonalNtSecurityError("Пользователь не найден.", 404, code="user_not_found")
        user_uuid = _normalize_uuid(account_auth._user_uuid(user))
        rows = doc.get("security_challenges")
        if not isinstance(rows, list):
            rows = []
            doc["security_challenges"] = rows
        challenge_id = "stg_" + account_auth.secrets.token_urlsafe(16)
        rows.append({
            "challenge_id": challenge_id,
            "user_uuid": user_uuid,
            "legacy_user_id": uid,
            "device_id": "",
            "purpose": security_devices.PURPOSE_STEP_UP,
            "provider": "staging",
            "action": action_id,
            "environment": environment,
            "code_salt": "",
            "code_hash": "",
            "status": "consumed",
            "attempts": 0,
            "max_attempts": security_devices.CHALLENGE_MAX_ATTEMPTS,
            "created_at_utc": now_iso,
            "consumed_at_utc": now_iso,
            "expires_at": time.time() + STEP_UP_GRANT_TTL_SEC,
            "staging": True,
        })
        account_auth._write_doc(doc)
    return {"ok": True, "action": action_id, "challenge_id": challenge_id, "staging": True}
