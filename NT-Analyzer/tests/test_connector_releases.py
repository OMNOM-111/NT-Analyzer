from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import connector_releases


def _catalog(path: Path, *, canary: list[str] | None = None) -> Path:
    release = {
        "archive_url": "https://releases.stratforges.com/connector.zip",
        "archive_sha256": "A" * 64,
        "manifest_sha256": "B" * 64,
        "protocol_version": "1.0",
        "minimum_version": "0.4.0",
        "blocked_versions": ["0.4.0"],
        "major_approved": False,
        "health_timeout_sec": 900,
        "published_at_utc": "2026-07-21T00:00:00Z",
    }
    doc = {
        "schema_version": 1,
        "channels": {
            "stable": {**release, "version": "0.4.2"},
            "canary": {
                **release,
                "version": "0.4.3",
                "archive_url": "https://releases.stratforges.com/connector-canary.zip",
            },
        },
        "canary_installation_ids": canary or [],
    }
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_release_catalog_selects_stable_and_explicit_canary(
    monkeypatch, tmp_path: Path,
) -> None:
    canary_id = "inst_canary_device_0001"
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv(
        "STRATFORGE_CONNECTOR_RELEASE_CATALOG",
        str(_catalog(tmp_path / "catalog.json", canary=[canary_id])),
    )
    stable = connector_releases.resolve_update({
        "installation_id": "inst_stable_device_0001",
        "connector_version": "0.4.1",
        "protocol_version": "1.0",
    })
    canary = connector_releases.resolve_update({
        "installation_id": canary_id,
        "connector_version": "0.4.1",
        "protocol_version": "1.0",
    })
    assert stable["state"] == "update_available"
    assert stable["channel"] == "stable"
    assert stable["offer"]["version"] == "0.4.2"
    assert canary["channel"] == "canary"
    assert canary["offer"]["version"] == "0.4.3"


def test_revoked_version_and_missing_production_catalog_fail_closed(
    monkeypatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv(
        "STRATFORGE_CONNECTOR_RELEASE_CATALOG",
        str(_catalog(tmp_path / "catalog.json")),
    )
    blocked = connector_releases.resolve_update({
        "installation_id": "inst_blocked_device_0001",
        "connector_version": "0.4.0",
        "protocol_version": "1.0",
    })
    assert blocked["state"] == "blocked"
    assert blocked["reason"] == "version_revoked"
    assert blocked["offer"]["archive_url"].startswith("https://")

    monkeypatch.setenv("STRATFORGE_ENV", "production")
    monkeypatch.delenv("STRATFORGE_CONNECTOR_RELEASE_CATALOG")
    missing = connector_releases.resolve_update({
        "installation_id": "inst_blocked_device_0001",
        "connector_version": "0.4.1",
        "protocol_version": "1.0",
    })
    assert missing == {
        "state": "blocked",
        "reason": "release_catalog_unconfigured",
        "channel": "",
        "offer": {},
    }


def test_release_catalog_rejects_non_https_and_unknown_fields(
    monkeypatch, tmp_path: Path,
) -> None:
    path = _catalog(tmp_path / "catalog.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["channels"]["stable"]["archive_url"] = "http://unsafe.example/release.zip"
    doc["channels"]["stable"]["unexpected"] = True
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_CONNECTOR_RELEASE_CATALOG", str(path))
    status = connector_releases.readiness_status()
    assert status["ok"] is False
    assert status["state"] == "invalid"


def test_semver_prerelease_precedence_is_numeric_and_strict() -> None:
    dev_two = connector_releases._semver("0.4.1-dev.2", "version")
    dev_ten = connector_releases._semver("0.4.1-dev.10", "version")
    release = connector_releases._semver("0.4.1", "version")

    assert connector_releases._compare(dev_ten, dev_two) > 0
    assert connector_releases._compare(release, dev_ten) > 0
    with pytest.raises(connector_releases.ConnectorReleaseError):
        connector_releases._semver("0.4.1-dev.01", "version")
    with pytest.raises(connector_releases.ConnectorReleaseError):
        connector_releases._semver("0.4.1-dev..2", "version")
