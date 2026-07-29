from __future__ import annotations

import argparse
import base64
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
    assert "docs/PRODUCTION_RELEASE_WORKFLOW.md" in selected
    assert "tools/production_preflight.py" in selected
    assert "tools/verify_server_release.py" in selected
    assert "tests/test_server_release.py" not in selected
    assert "bridge/NTAnalyzerBridge.csproj" not in selected
    assert "docs/AGENTS.md" not in selected
    assert "docs/AI_DIALOGUE_CONTRACT.md" not in selected
    assert "data/catalog/instrument_groups.json" in selected
    assert "data/catalog/margins.json" in selected
    assert not any(path.startswith("data/development/") for path in selected)
    assert not any(path.startswith("data/ai_lab/") for path in selected)
    assert "data/portfolio/cells.json" not in selected


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
        version="0.9.0-dev.5", channel="canary", production=False, force=False,
    )
    with pytest.raises(RuntimeError, match="must remain development"):
        build_server_release.build(args)


def test_server_release_verifier_rejects_archive_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("../outside.txt", "no")
    with pytest.raises(RuntimeError, match="unsafe archive member path"):
        verify_server_release.verify(archive)


def _signed_server_archive(tmp_path: Path, *, trust_tier: str = "production") -> tuple[Path, str]:
    payload = b"print('release')\n"
    key = ec.generate_private_key(ec.SECP256R1())
    numbers = key.public_key().public_numbers()
    x = numbers.x.to_bytes(32, "big")
    y = numbers.y.to_bytes(32, "big")
    fingerprint = "SHA256:" + hashlib.sha256(b"\x04" + x + y).hexdigest()
    manifest = {
        "schema_version": 1,
        "product": "StratForge Server",
        "version": "0.9.0",
        "channel": "stable",
        "trust_tier": trust_tier,
        "source_revision": "f" * 40,
        "signing": {
            "algorithm": "ECDSA_P256_SHA256_RAW",
            "public_key_x": base64.urlsafe_b64encode(x).decode().rstrip("="),
            "public_key_y": base64.urlsafe_b64encode(y).decode().rstrip("="),
            "key_fingerprint": fingerprint,
        },
        "files": [{
            "path": "app/server.py",
            "sha256": hashlib.sha256(payload).hexdigest().upper(),
            "size": len(payload),
        }],
    }
    manifest_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    der = key.sign(manifest_bytes, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = base64.urlsafe_b64encode(
        r.to_bytes(32, "big") + s.to_bytes(32, "big"),
    ).decode().rstrip("=")
    archive = tmp_path / "server.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("app/server.py", payload)
        zipped.writestr("manifest.json", manifest_bytes)
        zipped.writestr("manifest.sig", signature)
    return archive, fingerprint


def test_production_server_release_requires_external_key_pin(tmp_path: Path) -> None:
    archive, fingerprint = _signed_server_archive(tmp_path)
    with pytest.raises(RuntimeError, match="requires a trusted key fingerprint"):
        verify_server_release.verify(archive)
    with pytest.raises(RuntimeError, match="is not trusted"):
        verify_server_release.verify(
            archive, expected_key_fingerprint="SHA256:" + "0" * 64,
        )
    verified = verify_server_release.verify(
        archive, expected_key_fingerprint=fingerprint,
    )
    assert verified["ok"] is True
    assert verified["key_fingerprint"] == fingerprint


def test_stable_server_release_cannot_downgrade_its_trust_tier(tmp_path: Path) -> None:
    archive, fingerprint = _signed_server_archive(tmp_path, trust_tier="development")
    with pytest.raises(RuntimeError, match="trust tier and channel"):
        verify_server_release.verify(
            archive, expected_key_fingerprint=fingerprint,
        )
