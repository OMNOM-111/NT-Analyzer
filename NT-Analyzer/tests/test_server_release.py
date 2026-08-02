from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from tools import build_server_release
from tools import verify_server_release


def test_server_release_selection_is_runtime_bounded() -> None:
    selected = {
        path.as_posix() for path in build_server_release._selected_files(
            Path(__file__).resolve().parent.parent,
        )
    }
    assert "app/server.py" in selected
    assert "app/production_telegram.py" in selected
    assert "deploy/production/stratforge-operations.timer" in selected
    assert "docs/PRODUCTION_DEPLOYMENT_RUNBOOK.md" in selected
    assert "tools/production_preflight.py" in selected
    assert "tools/verify_server_release.py" in selected
    assert "tests/test_server_release.py" not in selected
    assert "bridge/NTAnalyzerBridge.csproj" not in selected
    assert "docs/AGENTS.md" not in selected
    assert "docs/AI_DIALOGUE_CONTRACT.md" not in selected


def test_server_production_release_cannot_use_development_key(
    monkeypatch, tmp_path: Path,
) -> None:
    monkeypatch.delenv("STRATFORGE_RELEASE_SIGNING_KEY_PEM", raising=False)
    monkeypatch.delenv("STRATFORGE_RELEASE_SIGNING_KEY_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="STRATFORGE_RELEASE_SIGNING_KEY_PEM"):
        build_server_release._load_signing_key(tmp_path, True)


def test_server_release_channel_cannot_be_mislabeled(monkeypatch) -> None:
    monkeypatch.setattr(
        build_server_release,
        "_git_state",
        lambda root: ("f" * 40, False),
    )
    args = argparse.Namespace(
        version="0.10.0-dev.1", channel="beta", production=False, force=False,
    )
    with pytest.raises(RuntimeError, match="must remain dev"):
        build_server_release.build(args)


def test_server_release_manifest_is_environment_portable() -> None:
    source = Path(build_server_release.__file__).read_text(encoding="utf-8")

    assert '"release_channel": args.channel' in source
    assert '"deployable_environments": deployable_environments' in source
    assert '["canary", "production"]' in source
    assert '"git_commit_sha": revision' in source
    assert '"build_id": build_id' in source
    assert '"dirty": False' in source
    assert '"environment": "production" if args.production' not in source


def test_server_release_verifier_rejects_archive_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("../outside.txt", "no")
    with pytest.raises(RuntimeError, match="unsafe archive member path"):
        verify_server_release.verify(archive)


def test_server_release_verifier_accepts_zero_byte_tracked_payload(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "zero-byte.zip"
    key = ec.generate_private_key(ec.SECP256R1())
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z",
    )
    revision = "a" * 40
    manifest = {
        "schema_version": 1,
        "product": "StratForge Server",
        "version": "0.10.0-dev.1",
        "channel": "dev",
        "app_version": "0.10.0-dev.1",
        "release_channel": "dev",
        "build_id": "sf-zero-byte-test",
        "git_commit_sha": revision,
        "source_revision": revision,
        "build_timestamp_utc": timestamp,
        "built_at_utc": timestamp,
        "dirty": False,
        "deployable_environments": ["development"],
        "trust_tier": "development",
        "signing": build_server_release._public_signing(key),
        "files": [{
            "path": "data/empty.jsonl",
            "sha256": hashlib.sha256(b"").hexdigest().upper(),
            "size": 0,
        }],
    }
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    der = key.sign(manifest_bytes, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = build_server_release._b64url(
        r.to_bytes(32, "big") + s.to_bytes(32, "big"),
    )
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("data/empty.jsonl", b"")
        zipped.writestr("manifest.json", manifest_bytes)
        zipped.writestr("manifest.sig", signature)

    result = verify_server_release.verify(archive)

    assert result["ok"] is True
    assert result["file_count"] == 1
    assert result["build_id"] == "sf-zero-byte-test"
