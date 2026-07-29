from __future__ import annotations

import argparse

import pytest

from tools import release_candidate


def test_development_candidate_requires_prerelease_versions() -> None:
    identity = {
        "version": "0.9.0-dev.13",
        "channel": "development",
        "status": "in_development",
    }
    assert release_candidate._validate_versions(
        identity,
        production=False,
        connector_version="0.4.2-dev.14",
        server_only=False,
    ) == "0.9.0-dev.13"
    with pytest.raises(RuntimeError, match="prerelease Connector"):
        release_candidate._validate_versions(
            identity,
            production=False,
            connector_version="0.4.2",
            server_only=False,
        )


def test_production_candidate_requires_stable_identity_and_both_artifacts() -> None:
    identity = {
        "version": "0.9.0",
        "channel": "stable",
        "status": "release_candidate",
    }
    assert release_candidate._validate_versions(
        identity,
        production=True,
        connector_version="0.4.2",
        server_only=False,
    ) == "0.9.0"
    with pytest.raises(RuntimeError, match="Server and Connector"):
        release_candidate._validate_versions(
            identity,
            production=True,
            connector_version="",
            server_only=True,
        )


def test_existing_artifact_cannot_be_rebound_to_another_commit() -> None:
    report = {
        "version": "0.9.0",
        "channel": "stable",
        "trust_tier": "production",
        "source_revision": "a" * 40,
    }
    with pytest.raises(RuntimeError, match="version is burned"):
        release_candidate._validate_report(
            report,
            product="Server",
            version="0.9.0",
            channel="stable",
            trust_tier="production",
            revision="b" * 40,
        )


def test_existing_production_artifact_must_match_external_signing_key() -> None:
    report = {
        "version": "0.9.0",
        "channel": "stable",
        "trust_tier": "production",
        "source_revision": "a" * 40,
        "key_fingerprint": "SHA256:" + "1" * 64,
    }
    with pytest.raises(RuntimeError, match="trusted Production key"):
        release_candidate._validate_report(
            report,
            product="Server",
            version="0.9.0",
            channel="stable",
            trust_tier="production",
            revision="a" * 40,
            expected_key_fingerprint="SHA256:" + "2" * 64,
        )


def test_candidate_refuses_dirty_worktree_before_build(monkeypatch) -> None:
    monkeypatch.setattr(release_candidate, "_git_state", lambda: ("f" * 40, True))
    with pytest.raises(RuntimeError, match="clean Git worktree"):
        release_candidate.build_candidate(argparse.Namespace(
            production=False,
            connector_version="",
            server_only=True,
        ))
