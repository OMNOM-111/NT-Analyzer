"""Stable identities for sources, content versions and logical fragments."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from uuid import UUID, uuid5

from .states import ContractError


SOURCE_NAMESPACE = UUID("3463c17b-f2cf-5592-9475-ea4c16c262c8")
VERSION_NAMESPACE = UUID("6132e374-88f6-5bd9-ab1a-cddb83225918")


def content_sha256(content: bytes) -> str:
    if type(content) is not bytes:
        raise ContractError("source_content_required")
    return hashlib.sha256(content).hexdigest()


def new_source_id(seed: str) -> UUID:
    """Allocate a stable first-ingest id from a private opaque seed.

    Production callers use a random idempotency key; deterministic seeds make
    offline migration and retry safe.  The locator is deliberately not the id,
    so a rename never changes identity.
    """
    if not isinstance(seed, str) or not 8 <= len(seed) <= 512:
        raise ContractError("source_seed_invalid")
    return uuid5(SOURCE_NAMESPACE, seed)


def source_version_id(content: bytes) -> UUID:
    """Content-addressed identity shared by byte-identical source versions."""
    return uuid5(VERSION_NAMESPACE, content_sha256(content))


def normalize_anchor(anchor: str) -> str:
    if not isinstance(anchor, str):
        raise ContractError("fragment_anchor_invalid")
    value = unicodedata.normalize("NFKC", anchor).strip().casefold()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"[^\w .:/-]", "", value, flags=re.UNICODE).strip(" .:/-")
    if not value or len(value) > 500:
        raise ContractError("fragment_anchor_invalid")
    return value


def fragment_id(source_id: UUID, anchor: str) -> UUID:
    if not isinstance(source_id, UUID) or source_id.int == 0:
        raise ContractError("invalid_uuid")
    return uuid5(source_id, "fragment:" + normalize_anchor(anchor))
