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


# Domains close enough to a common one that a typo is the likely explanation.
# Used only to *suggest*; the address the user typed is never rewritten.
_COMMON_EMAIL_DOMAINS = (
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "yahoo.com", "icloud.com", "proton.me", "protonmail.com", "yandex.ru",
    "mail.ru", "stratforges.com",
)


def _one_typo_apart(a: str, b: str) -> bool:
    """One substitution, insertion, deletion or adjacent transposition.

    Transposition matters most in practice -- gmial/gmail is the commonest
    address typo there is, and it is two substitutions, so plain edit distance
    would miss it.
    """
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        if len(diff) == 1:
            return True
        if len(diff) == 2:
            i, j = diff
            return j == i + 1 and a[i] == b[j] and a[j] == b[i]
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    return any(shorter == longer[:i] + longer[i + 1:] for i in range(len(longer)))


def email_domain_suggestion(value: Any) -> str:
    """A likely intended domain for an obvious typo, or "".

    Returned for the user to confirm. The address is never silently corrected:
    an e-mail is an identity, and quietly changing one would hand the account
    to a different mailbox than the person typed.
    """
    text = str(value or "").strip().casefold()
    if text.count("@") != 1:
        return ""
    local, _, domain = text.partition("@")
    if not local or not domain or domain in _COMMON_EMAIL_DOMAINS:
        return ""
    for candidate in _COMMON_EMAIL_DOMAINS:
        if _one_typo_apart(domain, candidate):
            return f"{local}@{candidate}"
    return ""


def normalize_email(value: Any) -> str:
    """Canonical form of an e-mail address, or raise.

    Rejects control characters and Unicode direction marks outright: those are
    invisible in a UI and are exactly how one address is made to look like
    another. Case is folded because mailbox routing is case-insensitive in
    practice, but nothing else about the local part is rewritten -- stripping
    dots or plus tags would merge addresses their owners consider distinct.
    """
    raw = str(value or "").strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise IdentityError("Email contains control characters.")
    if any(ch in raw for ch in "​‌‍⁦⁧⁨⁩‪‫‬‭‮﻿"):
        raise IdentityError("Email contains invisible or direction-control characters.")
    email = raw.casefold()
    if not 3 <= len(email) <= 254:
        raise IdentityError("Email length is invalid.")
    if email.count("@") != 1:
        raise IdentityError("Email must contain exactly one @.")
    local, _, domain = email.partition("@")
    if not local or not domain:
        raise IdentityError("Email is invalid.")
    if len(local) > 64:
        raise IdentityError("Email local part is too long.")
    if ".." in email:
        raise IdentityError("Email domain is invalid.")
    if not re.fullmatch(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+", local):
        raise IdentityError("Email local part has invalid characters.")
    labels = domain.split(".")
    if len(labels) < 2 or any(
        not re.fullmatch(r"[a-z0-9-]{1,63}", part) or part.startswith("-") or part.endswith("-")
        for part in labels
    ):
        raise IdentityError("Email domain is invalid.")
    if len(labels[-1]) < 2 or not labels[-1].isalpha():
        raise IdentityError("Email top-level domain is invalid.")
    return email


def normalize_phone_e164(value: Any) -> str:
    """Canonical E.164, or raise. Digits alone are not an identity."""
    raw = str(value or "").strip().replace(" ", "").replace("-", "")
    raw = raw.replace("(", "").replace(")", "")
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if not raw.startswith("+"):
        raw = "+" + raw
    if not re.fullmatch(r"\+[1-9][0-9]{6,14}", raw):
        raise IdentityError("Phone must be a valid E.164 number.")
    return raw


def normalize_subject(provider: Any, value: Any) -> str:
    provider_id = normalize_provider(provider)
    subject = str(value or "").strip()
    if provider_id == "telegram":
        if not re.fullmatch(r"[1-9][0-9]{0,19}", subject):
            raise IdentityError("Telegram provider subject must be a positive numeric id.")
    elif provider_id == "email":
        subject = normalize_email(subject)
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
