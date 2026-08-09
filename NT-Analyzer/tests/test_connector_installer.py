from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from app import connector_protocol
from tools import build_connector_release
from tools import release_static_scan


def test_production_release_signing_cannot_fall_back_to_development(
    monkeypatch, tmp_path: Path,
) -> None:
    monkeypatch.delenv("STRATFORGE_RELEASE_SIGNING_KEY_PEM", raising=False)
    monkeypatch.delenv("STRATFORGE_RELEASE_SIGNING_KEY_PASSWORD", raising=False)
    monkeypatch.delenv("STRATFORGE_AUTHENTICODE_THUMBPRINT", raising=False)
    with pytest.raises(RuntimeError, match="STRATFORGE_RELEASE_SIGNING_KEY_PEM"):
        build_connector_release._load_signing_key(tmp_path, True)


def test_installer_is_standalone_strict_and_transactional() -> None:
    root = Path(__file__).resolve().parent.parent
    project = (root / "connector" / "installer" / "StratForge.Connector.Setup.csproj").read_text(
        encoding="utf-8",
    )
    engine = (root / "connector" / "installer" / "InstallerEngine.cs").read_text(
        encoding="utf-8",
    )
    verifier = (root / "connector" / "installer" / "ReleaseManifestVerifier.cs").read_text(
        encoding="utf-8",
    )
    assert "net48" in project
    assert "dotnet" not in engine.lower()
    assert "RestoreOperationBackup" in engine
    assert "DataProtectionScope.CurrentUser" in engine
    assert "RetryIo" in engine
    assert "NinjaTrader started while Connector files were being changed" in engine
    assert 'connector.Remove("enrollment_code")' in engine
    assert '["enrollment_code"] =' not in engine
    assert "VerifyData" in verifier
    assert "unsafe file path" in verifier
    assert "payload hash mismatch" in verifier
    assert "absent from manifest" in verifier
    assert "Path.GetFullPath(release.Root)" in engine
    assert "string.Equals" in engine
    client = (root / "bridge" / "src" / "Connector" / "ConnectorClient.cs").read_text(encoding="utf-8")
    assert 'File.Exists(Path.Combine(_stateDir, "bootstrap.dpapi"))' in client
    assert '_state.Revoked = false;' in client


def test_release_builder_restores_clean_checkout_before_release_build() -> None:
    source = Path(build_connector_release.__file__).read_text(encoding="utf-8")
    restore = source.index('"dotnet", "restore"')
    first_build = source.index('"dotnet", "build"')
    assert restore < first_build
    assert '"-c", "Release", "--no-restore"' in source


def test_release_static_scan_supports_extracted_archive(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "app" / "server.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('release')\n", encoding="utf-8")
    ignored = tmp_path / ".artifacts" / "secret.py"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("generated\n", encoding="utf-8")
    cached = tmp_path / "app" / "__pycache__" / "cached.py"
    cached.parent.mkdir(parents=True)
    cached.write_text("generated\n", encoding="utf-8")

    monkeypatch.setattr(release_static_scan, "ROOT", tmp_path)
    monkeypatch.setattr(
        release_static_scan.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 128, b"", b"not a repo"),
    )
    found = {path.resolve() for path in release_static_scan._tracked_files()}
    assert source.resolve() in found
    assert ignored.resolve() not in found
    assert cached.resolve() not in found


def test_external_updater_has_safe_restart_health_and_one_shot_rollback() -> None:
    root = Path(__file__).resolve().parent.parent
    project = (root / "connector" / "updater" / "StratForge.Connector.Updater.csproj").read_text(
        encoding="utf-8",
    )
    engine = (root / "connector" / "updater" / "UpdaterEngine.cs").read_text(
        encoding="utf-8",
    )
    launcher = (root / "bridge" / "src" / "Connector" / "ConnectorUpdaterLauncher.cs").read_text(
        encoding="utf-8",
    )
    assert "net48" in project
    assert "WaitForNinjaTraderClosed" in engine
    assert "CreateLastKnownGood" in engine
    assert "rollback_attempted" in engine
    assert "Update archive symlinks are forbidden" in engine
    assert "RecordHealth" in launcher
    assert "ProcessWindowStyle.Hidden" in launcher


def test_setup_payload_reports_real_release_gate(monkeypatch, tmp_path: Path) -> None:
    release = {
        "version": "1.2.3",
        "archive_url": "https://downloads.stratforges.com/connector/1.2.3.zip",
        "archive_sha256": "A" * 64,
        "manifest_sha256": "B" * 64,
    }
    monkeypatch.setattr(
        connector_protocol,
        "list_installations",
        lambda *_args, **_kwargs: {"ok": True, "workspace": {}, "connections": []},
    )
    monkeypatch.setattr(
        connector_protocol.connector_releases,
        "load_catalog",
        lambda: {"channels": {"stable": release, "canary": release}},
    )
    monkeypatch.setattr(
        connector_protocol.runtime_env,
        "deployment_config",
        lambda: SimpleNamespace(public_origin="https://app.stratforges.com"),
    )

    payload = connector_protocol.setup_payload(42)

    assert payload["installer"]["state"] == "available"
    assert payload["installer"]["download_url"] == release["archive_url"]
    assert payload["installer"]["requires_user_consent"] is True
    assert payload["installer"]["browser_silent_install"] is False
    assert payload["installer"]["requires_authenticode"] is True
    assert payload["updater"]["state"] == "release_catalog_ready"


def test_setup_payload_is_blocked_without_published_catalog(monkeypatch) -> None:
    monkeypatch.setattr(
        connector_protocol,
        "list_installations",
        lambda *_args, **_kwargs: {"ok": True, "workspace": {}, "connections": []},
    )
    monkeypatch.setattr(connector_protocol.connector_releases, "load_catalog", lambda: None)
    monkeypatch.setattr(
        connector_protocol.runtime_env,
        "deployment_config",
        lambda: SimpleNamespace(public_origin="https://app.stratforges.com"),
    )
    payload = connector_protocol.setup_payload(42)
    assert payload["installer"]["state"] == "blocked_release_catalog_unconfigured"
    assert payload["installer"]["download_url"] == ""


def test_aurora_connector_download_has_explicit_consent_gate() -> None:
    source = (
        Path(__file__).resolve().parent.parent
        / "app" / "static" / "aurora" / "assets" / "ui.js"
    ).read_text(encoding="utf-8")
    assert "data-nt-installer-url" in source
    assert "Согласиться и скачать Connector" in source
    assert "Скачать подписанный StratForge Connector?" in source
    assert "link.click()" in source
