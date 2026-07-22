"""Fail-closed release policy for the Windows NinjaTrader Connector.

The release catalog is operator-owned configuration.  It contains no private
signing material: every downloadable package still has to pass the embedded
P-256 release trust check in Setup/Updater before any installed file changes.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, Mapping, Tuple
import urllib.parse

from . import runtime_env


_SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_HEX64 = re.compile(r"^[0-9A-Fa-f]{64}$")
_CHANNELS = {"stable", "canary"}


class ConnectorReleaseError(RuntimeError):
    pass


def _catalog_path() -> Path | None:
    raw = str(os.environ.get("STRATFORGE_CONNECTOR_RELEASE_CATALOG") or "").strip()
    return Path(raw).expanduser().resolve() if raw else None


def _semver(value: Any, field: str) -> Tuple[int, int, int, str]:
    text = str(value or "").strip()
    match = _SEMVER.fullmatch(text)
    if not match:
        raise ConnectorReleaseError(f"{field} must be semantic versioning")
    prerelease = match.group(4) or ""
    if any(
        item.isdigit() and len(item) > 1 and item.startswith("0")
        for item in prerelease.split(".") if item
    ):
        raise ConnectorReleaseError(f"{field} must be semantic versioning")
    return int(match.group(1)), int(match.group(2)), int(match.group(3)), prerelease


def _compare(left: Tuple[int, int, int, str], right: Tuple[int, int, int, str]) -> int:
    if left[:3] != right[:3]:
        return -1 if left[:3] < right[:3] else 1
    # A release is newer than its prerelease. Prerelease identifiers follow
    # SemVer 2.0 precedence: numeric identifiers compare numerically, numeric
    # identifiers sort before text, and a longer equal prefix sorts later.
    if left[3] == right[3]:
        return 0
    if not left[3]:
        return 1
    if not right[3]:
        return -1
    left_parts = left[3].split(".")
    right_parts = right[3].split(".")
    for left_item, right_item in zip(left_parts, right_parts):
        if left_item == right_item:
            continue
        left_numeric = left_item.isdigit()
        right_numeric = right_item.isdigit()
        if left_numeric and right_numeric:
            return -1 if int(left_item) < int(right_item) else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_item < right_item else 1
    if len(left_parts) == len(right_parts):
        return 0
    return -1 if len(left_parts) < len(right_parts) else 1


def _https_url(value: Any, field: str) -> str:
    text = str(value or "").strip()
    parsed = urllib.parse.urlsplit(text)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ConnectorReleaseError(f"{field} must be an HTTPS URL without credentials/fragment")
    return text


def _release(raw: Any, channel: str) -> Dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ConnectorReleaseError(f"channels.{channel} must be an object")
    allowed = {
        "version", "archive_url", "archive_sha256", "manifest_sha256",
        "protocol_version", "minimum_version", "blocked_versions",
        "major_approved", "health_timeout_sec", "published_at_utc",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ConnectorReleaseError(
            f"channels.{channel} contains unknown fields: {', '.join(sorted(unknown))}"
        )
    version = str(raw.get("version") or "").strip()
    minimum = str(raw.get("minimum_version") or version).strip()
    _semver(version, f"channels.{channel}.version")
    _semver(minimum, f"channels.{channel}.minimum_version")
    archive_hash = str(raw.get("archive_sha256") or "").strip().upper()
    manifest_hash = str(raw.get("manifest_sha256") or "").strip().upper()
    if not _HEX64.fullmatch(archive_hash) or not _HEX64.fullmatch(manifest_hash):
        raise ConnectorReleaseError(f"channels.{channel} release hashes must be SHA-256")
    blocked = []
    for item in raw.get("blocked_versions") or []:
        value = str(item or "").strip()
        _semver(value, f"channels.{channel}.blocked_versions")
        if value not in blocked:
            blocked.append(value)
    health_timeout = int(raw.get("health_timeout_sec") or 900)
    if health_timeout < 300 or health_timeout > 3600:
        raise ConnectorReleaseError(f"channels.{channel}.health_timeout_sec must be 300..3600")
    published = str(raw.get("published_at_utc") or "").strip()
    if published:
        try:
            parsed = datetime.fromisoformat(published.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timezone required")
        except (TypeError, ValueError):
            raise ConnectorReleaseError(
                f"channels.{channel}.published_at_utc must be ISO-8601 with timezone"
            ) from None
    protocol = str(raw.get("protocol_version") or "").strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+", protocol):
        raise ConnectorReleaseError(f"channels.{channel}.protocol_version is invalid")
    return {
        "version": version,
        "archive_url": _https_url(raw.get("archive_url"), f"channels.{channel}.archive_url"),
        "archive_sha256": archive_hash,
        "manifest_sha256": manifest_hash,
        "protocol_version": protocol,
        "minimum_version": minimum,
        "blocked_versions": blocked,
        "major_approved": bool(raw.get("major_approved")),
        "health_timeout_sec": health_timeout,
        "published_at_utc": published,
    }


def load_catalog() -> Dict[str, Any] | None:
    path = _catalog_path()
    if path is None:
        return None
    if not path.is_file():
        raise ConnectorReleaseError("configured Connector release catalog does not exist")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConnectorReleaseError("Connector release catalog is unreadable") from exc
    if not isinstance(raw, Mapping):
        raise ConnectorReleaseError("Connector release catalog must be an object")
    allowed = {"schema_version", "channels", "canary_installation_ids"}
    unknown = set(raw) - allowed
    if unknown or int(raw.get("schema_version") or 0) != 1:
        raise ConnectorReleaseError("Connector release catalog schema is unsupported")
    channels_raw = raw.get("channels")
    if not isinstance(channels_raw, Mapping) or set(channels_raw) != _CHANNELS:
        raise ConnectorReleaseError("Connector release catalog requires stable and canary channels")
    canary = []
    for item in raw.get("canary_installation_ids") or []:
        value = str(item or "").strip()
        if not re.fullmatch(r"inst_[A-Za-z0-9_-]{8,128}", value):
            raise ConnectorReleaseError("canary installation id is invalid")
        if value not in canary:
            canary.append(value)
    return {
        "schema_version": 1,
        "channels": {name: _release(channels_raw[name], name) for name in sorted(_CHANNELS)},
        "canary_installation_ids": canary,
    }


def resolve_update(installation: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a public, secret-free update decision for one installation."""
    try:
        catalog = load_catalog()
    except ConnectorReleaseError as exc:
        return {
            "state": "blocked", "reason": "release_catalog_invalid",
            "channel": "", "offer": {}, "detail": str(exc)[:240],
        }
    if catalog is None:
        return {
            "state": "blocked" if runtime_env.is_production() else "compatible",
            "reason": "release_catalog_unconfigured",
            "channel": "", "offer": {},
        }
    installation_id = str(installation.get("installation_id") or "")
    channel = (
        "canary" if installation_id in set(catalog["canary_installation_ids"])
        else "stable"
    )
    release = catalog["channels"][channel]
    current_text = str(installation.get("connector_version") or "").strip()
    protocol = str(installation.get("protocol_version") or "1.0").strip()
    try:
        current = _semver(current_text, "connector_version")
    except ConnectorReleaseError:
        return {
            "state": "blocked", "reason": "invalid_connector_version",
            "channel": channel, "offer": _offer(release, channel, "manual"),
        }
    target = _semver(release["version"], "release.version")
    minimum = _semver(release["minimum_version"], "release.minimum_version")
    major_change = target[0] != current[0]
    policy = "manual" if major_change else "safe_restart"
    offer = _offer(release, channel, policy)
    if protocol != release["protocol_version"]:
        return {
            "state": "blocked", "reason": "protocol_incompatible",
            "channel": channel, "offer": offer,
        }
    if current_text in set(release["blocked_versions"]):
        return {
            "state": "blocked", "reason": "version_revoked",
            "channel": channel, "offer": offer,
        }
    if _compare(current, minimum) < 0:
        return {
            "state": "blocked", "reason": "below_minimum_version",
            "channel": channel, "offer": offer,
        }
    if _compare(current, target) < 0:
        if major_change and not release["major_approved"]:
            return {
                "state": "blocked", "reason": "major_approval_required",
                "channel": channel, "offer": offer,
            }
        return {
            "state": "update_available", "reason": "newer_release",
            "channel": channel, "offer": offer,
        }
    return {
        "state": "compatible", "reason": "current_or_newer",
        "channel": channel, "offer": {},
    }


def _offer(release: Mapping[str, Any], channel: str, policy: str) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "version": release["version"],
        "channel": channel,
        "archive_url": release["archive_url"],
        "archive_sha256": release["archive_sha256"],
        "manifest_sha256": release["manifest_sha256"],
        "protocol_version": release["protocol_version"],
        "apply_policy": policy,
        "major_approved": bool(release["major_approved"]),
        "health_timeout_sec": int(release["health_timeout_sec"]),
        "published_at_utc": release["published_at_utc"],
    }


def readiness_status() -> Dict[str, Any]:
    try:
        catalog = load_catalog()
    except ConnectorReleaseError as exc:
        return {"ok": False, "state": "invalid", "error": str(exc)[:240]}
    if catalog is None:
        return {
            "ok": not runtime_env.is_production(),
            "state": "unconfigured",
            "channels": [],
        }
    return {
        "ok": True,
        "state": "ready",
        "channels": sorted(catalog["channels"]),
        "canary_count": len(catalog["canary_installation_ids"]),
        "versions": {
            name: catalog["channels"][name]["version"]
            for name in sorted(catalog["channels"])
        },
    }
