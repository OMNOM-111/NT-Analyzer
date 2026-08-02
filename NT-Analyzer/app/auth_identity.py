"""Provider-neutral identity primitives for StratForge accounts.

The account repository owns persistence and authorization.  This module keeps
provider subject normalization, UUID generation and public masking small and
deterministic so Telegram, Google and email flows use one identity contract.
Provider subjects are never session tokens and must never be used as the
canonical internal user identifier.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict


PROVIDERS = ("telegram", "google", "email", "test")
LOGIN_PROVIDERS = ("telegram", "google", "email")
_IDENTITY_NAMESPACE = uuid.UUID("f44c14d3-74df-4f4a-bb5b-71f86f522865")


class IdentityError(ValueError):
    pass


def normalize_provider(value: Any) -> str:
    provider = str(value or "").strip().lower()
    if provider not in PROVIDERS:
        raise IdentityError("Unsupported authentication provider.")
    return provider


def normalize_subject(provider: Any, value: Any) -> str:
    provider_id = normalize_provider(provider)
    subject = str(value or "").strip()
    if provider_id == "telegram":
        if not re.fullmatch(r"[1-9][0-9]{0,19}", subject):
            raise IdentityError("Telegram provider subject must be a positive numeric id.")
    elif provider_id == "email":
        subject = subject.casefold()
        if len(subject) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", subject):
            raise IdentityError("Email provider subject is invalid.")
    else:
        if not 1 <= len(subject) <= 255 or any(ord(ch) < 32 for ch in subject):
            raise IdentityError("Provider subject is invalid.")
    return subject


def new_user_uuid() -> str:
    return str(uuid.uuid4())


def normalize_user_uuid(value: Any) -> str:
    raw = str(value or "").strip()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        return ""
    return str(parsed)


def deterministic_identity_id(provider: Any, subject: Any) -> str:
    provider_id = normalize_provider(provider)
    normalized = normalize_subject(provider_id, subject)
    return str(uuid.uuid5(_IDENTITY_NAMESPACE, f"{provider_id}\0{normalized}"))


def mask_email(value: Any) -> str:
    raw = str(value or "").strip().casefold()
    if "@" not in raw:
        return ""
    local, domain = raw.rsplit("@", 1)
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'•' * max(2, min(6, len(local) - len(visible)))}@{domain}"


def public_identity(identity: Dict[str, Any], *, user: Dict[str, Any] | None = None) -> Dict[str, Any]:
    provider = normalize_provider(identity.get("provider"))
    subject = normalize_subject(provider, identity.get("provider_subject"))
    metadata = identity.get("metadata") if isinstance(identity.get("metadata"), dict) else {}
    label = ""
    if provider == "telegram":
        username = str((user or {}).get("username") or "").strip().lstrip("@")
        label = f"@{username}" if username else f"Telegram •{subject[-4:]}"
    elif provider in {"email", "google"}:
        label = mask_email(metadata.get("email") or (user or {}).get("google_email") or subject)
    else:
        label = "Development test identity"
    return {
        "identity_id": str(identity.get("identity_id") or ""),
        "provider": provider,
        "label": label,
        "verified": bool(identity.get("verified_at_utc")),
        "linked_at_utc": str(identity.get("linked_at_utc") or ""),
        "last_used_at_utc": str(identity.get("last_used_at_utc") or ""),
    }
