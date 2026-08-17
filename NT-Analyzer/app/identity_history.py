"""Append-only identity history.

The current identity lives in ``account_auth``; this module records every state
an identifier has ever held on an account beside it. A change is never an
overwrite: the replacement is added, verified, activated, and only then is the
previous value retired, all in one step so a reader never sees two active
values or none.

The rules that matter are not in Python. ``sf_identity_history`` carries a
partial unique index on ``(provider, normalized_key) WHERE state = 'active'``,
so two accounts cannot hold one live identifier even if both requests pass
their checks before either commits. This module raises before the constraint
has to, so callers get a specific error instead of a violation.
"""
from __future__ import annotations

import hashlib
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import auth_identity

PROVIDERS = ("telegram", "google", "email", "phone")
STATE_PENDING = "pending"
STATE_ACTIVE = "active"
STATE_RETIRED = "retired"
STATE_REVOKED = "revoked"
STATES = (STATE_PENDING, STATE_ACTIVE, STATE_RETIRED, STATE_REVOKED)

_LOCK = threading.RLock()


class IdentityHistoryError(RuntimeError):
    def __init__(self, message: str, status: int = 409, *, code: str = ""):
        super().__init__(message)
        self.status = int(status)
        self.code = str(code or "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_key(provider: str, value: Any) -> str:
    """Canonical comparable form for one provider."""
    provider_id = str(provider or "").strip().lower()
    if provider_id not in PROVIDERS:
        raise IdentityHistoryError("Unsupported identity provider.", 400,
                                   code="provider_invalid")
    if provider_id == "phone":
        return auth_identity.normalize_phone_e164(value)
    if provider_id in {"email", "google"}:
        # Google is keyed by sub, but the address it carries is compared as an
        # address; a bare sub is passed through unchanged.
        raw = str(value or "").strip()
        if "@" in raw:
            return auth_identity.normalize_email(raw)
        return raw
    return auth_identity.normalize_subject("telegram", value)


def key_hash(normalized: str) -> str:
    return hashlib.sha256(str(normalized or "").encode("utf-8")).hexdigest()


def display_value(provider: str, normalized: str) -> str:
    """Masked form. The raw address or number is never rendered."""
    if provider in {"email", "google"} and "@" in normalized:
        return auth_identity.mask_email(normalized)
    if provider == "phone" and len(normalized) > 4:
        return f"+•••{normalized[-4:]}"
    if normalized:
        return f"•{normalized[-4:]}"
    return ""


def _rows(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = doc.get("identity_history")
    if not isinstance(rows, list):
        rows = []
        doc["identity_history"] = rows
    return rows


def active_row(doc: Dict[str, Any], provider: str, normalized: str) -> Optional[Dict[str, Any]]:
    """The live claim on this key, whoever holds it.

    An e-mail address is matched across every provider, not just within one.
    Keying purely on (provider, value) would let a Google account whose address
    is already someone else's verified e-mail be linked as a separate identity
    -- the same person to a reader, two rows to the index -- which is exactly
    the hijack migration 0013 closed for sf_auth_identities and
    ``email_already_verified_elsewhere`` closes at the account layer. The
    canonical history has to agree with both.

    A Google subject that is not an address keeps provider-scoped matching:
    a bare sub means nothing outside Google.
    """
    is_address = "@" in str(normalized or "")
    for row in _rows(doc):
        if not isinstance(row, dict):
            continue
        if row.get("state") != STATE_ACTIVE:
            continue
        if str(row.get("normalized_key") or "") != normalized:
            continue
        if is_address or str(row.get("provider") or "") == provider:
            return row
    return None


def active_for_user(doc: Dict[str, Any], user_uuid: str, provider: str) -> Optional[Dict[str, Any]]:
    for row in _rows(doc):
        if not isinstance(row, dict) or row.get("state") != STATE_ACTIVE:
            continue
        if str(row.get("provider") or "") != provider:
            continue
        if str(row.get("user_uuid") or "") == str(user_uuid):
            return row
    return None


def history_for_user(doc: Dict[str, Any], user_uuid: str) -> List[Dict[str, Any]]:
    """Everything this account has ever held, newest window first."""
    rows = [
        dict(row) for row in _rows(doc)
        if isinstance(row, dict) and str(row.get("user_uuid") or "") == str(user_uuid)
    ]
    rows.sort(key=lambda r: str(r.get("valid_from") or ""), reverse=True)
    return rows


def ever_used_by_other(doc: Dict[str, Any], provider: str, normalized: str,
                       user_uuid: str) -> Optional[Dict[str, Any]]:
    """A past claim on this key by a different account.

    A retired identifier is not free for the taking: reassignment goes through
    an explicit, audited flow rather than happening because someone typed an
    address that used to belong to somebody else.
    """
    for row in _rows(doc):
        if not isinstance(row, dict):
            continue
        if str(row.get("provider") or "") != provider:
            continue
        if str(row.get("normalized_key") or "") != normalized:
            continue
        if str(row.get("user_uuid") or "") != str(user_uuid):
            return row
    return None


def record_change(
    doc: Dict[str, Any],
    *,
    user_uuid: str,
    legacy_user_id: Any,
    provider: str,
    value: Any,
    verified_at_utc: str,
    actor_user_uuid: str = "",
    actor_source: str = "",
    reason: str = "",
    allow_reassignment: bool = False,
) -> Dict[str, Any]:
    """Add, verify, activate the new value and retire the previous one.

    One step, so a reader never observes two active values for a provider or a
    gap where an account has none. Returns the new history row.
    """
    provider_id = str(provider or "").strip().lower()
    if provider_id not in PROVIDERS:
        raise IdentityHistoryError("Unsupported identity provider.", 400,
                                   code="provider_invalid")
    if not verified_at_utc:
        # Nothing becomes active without proof; the database says so too.
        raise IdentityHistoryError("An identity is activated only after verification.",
                                   409, code="verification_required")
    normalized = normalize_key(provider_id, value)
    canonical = str(user_uuid or "")
    if not canonical:
        raise IdentityHistoryError("Identity history requires a user UUID.", 409,
                                   code="user_uuid_required")

    with _LOCK:
        held = active_row(doc, provider_id, normalized)
        if held is not None and str(held.get("user_uuid") or "") != canonical:
            raise IdentityHistoryError(
                "Этот идентификатор уже активен в другом профиле.", 409,
                code="identity_active_elsewhere",
            )
        if held is not None:
            # Already active on this account: nothing changes, and re-recording
            # would create a second active row the index would reject anyway.
            return dict(held)
        prior_other = ever_used_by_other(doc, provider_id, normalized, canonical)
        if prior_other is not None and not allow_reassignment:
            raise IdentityHistoryError(
                "Этот идентификатор ранее принадлежал другому профилю. "
                "Требуется отдельная процедура передачи.", 409,
                code="identity_requires_reassignment",
            )

        now = _now_iso()
        new_row = {
            "history_id": str(uuid.uuid4()),
            "user_uuid": canonical,
            "legacy_user_id": int(legacy_user_id or 0),
            "provider": provider_id,
            "normalized_key": normalized,
            "key_hash": key_hash(normalized),
            "display_value": display_value(provider_id, normalized),
            "state": STATE_ACTIVE,
            "verified_at": str(verified_at_utc),
            "valid_from": now,
            "valid_to": "",
            "replacement_reason": str(reason or "")[:200],
            "replaced_by_history_id": "",
            "actor_user_uuid": str(actor_user_uuid or ""),
            "actor_source": str(actor_source or "")[:60],
        }
        previous = active_for_user(doc, canonical, provider_id)
        if previous is not None:
            previous["state"] = STATE_RETIRED
            previous["valid_to"] = now
            previous["replaced_by_history_id"] = new_row["history_id"]
            if not previous.get("replacement_reason"):
                previous["replacement_reason"] = str(reason or "replaced")[:200]
        _rows(doc).append(new_row)
        return dict(new_row)


def revoke(doc: Dict[str, Any], *, user_uuid: str, provider: str,
           reason: str = "", actor_user_uuid: str = "") -> Optional[Dict[str, Any]]:
    """Close an account's active claim without replacing it."""
    with _LOCK:
        row = active_for_user(doc, str(user_uuid or ""), str(provider or "").strip().lower())
        if row is None:
            return None
        row["state"] = STATE_REVOKED
        row["valid_to"] = _now_iso()
        row["replacement_reason"] = str(reason or "revoked")[:200]
        row["actor_user_uuid"] = str(actor_user_uuid or "")
        return dict(row)


def public_history(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Timeline safe to render. Never the raw identifier."""
    out = []
    for row in rows:
        out.append({
            "provider": row.get("provider"),
            "display_value": row.get("display_value"),
            "state": row.get("state"),
            "verified_at": row.get("verified_at"),
            "valid_from": row.get("valid_from"),
            "valid_to": row.get("valid_to") or "",
            "replacement_reason": row.get("replacement_reason") or "",
            "actor_source": row.get("actor_source") or "",
        })
    return out


def backfill_from_identities(doc: Dict[str, Any]) -> int:
    """Create missing active history rows from verified auth identities.

    Migration 0014 did exactly this for the relational table. The account
    document never received the same backfill, so an account whose identities
    predate the history model rendered as having none at all.

    Idempotent and conservative: a provider that already has any history row
    for this account is skipped entirely. Real history is the record of what
    happened; a row derived after the fact must never compete with it.

    Returns the number of rows added, so the caller can decide whether the
    document needs writing.
    """
    rows = _rows(doc)
    added = 0
    for identity in doc.get("auth_identities") or []:
        if not isinstance(identity, dict):
            continue
        if not identity.get("verified_at_utc") or identity.get("revoked_at_utc"):
            continue
        user_uuid = auth_identity.normalize_user_uuid(identity.get("user_uuid"))
        provider = str(identity.get("provider") or "").strip().lower()
        if not user_uuid or provider not in PROVIDERS:
            continue
        if any(
            isinstance(row, dict)
            and str(row.get("provider") or "") == provider
            and auth_identity.normalize_user_uuid(row.get("user_uuid")) == user_uuid
            for row in rows
        ):
            continue
        raw = identity.get("normalized_email") or identity.get("provider_subject")
        try:
            normalized = normalize_key(provider, raw)
        except Exception:
            continue
        if not normalized:
            continue
        verified = str(identity.get("verified_at_utc") or "")
        rows.append({
            "history_id": "hist_" + hashlib.sha256(
                (user_uuid + "|" + provider + "|" + normalized).encode("utf-8")
            ).hexdigest()[:24],
            "user_uuid": user_uuid,
            "provider": provider,
            "normalized_key": normalized,
            "display_value": display_value(provider, normalized),
            "key_hash": key_hash(normalized),
            "state": STATE_ACTIVE,
            "verified_at": verified,
            # The identity's own link time, not today: a card that showed every
            # identity as created at first render would be lying about the age
            # of the account.
            "valid_from": str(identity.get("linked_at_utc") or verified),
            "valid_to": "",
            "replacement_reason": "",
            "actor_source": "backfill",
        })
        added += 1
    return added
