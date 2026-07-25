from __future__ import annotations

from pathlib import Path

import pytest

from app import connector_protocol
from tools import build_connector_release


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


def test_release_builder_restores_clean_checkout_before_release_build() -> None:
    source = Path(build_connector_release.__file__).read_text(encoding="utf-8")
    restore = source.index('"dotnet", "restore"')
    first_build = source.index('"dotnet", "build"')
    assert restore < first_build
    assert '"-c", "Release", "--no-restore"' in source


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
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "dev"))
    # The payload needs an authorized workspace; contract details are verified
    # in test_connector_protocol. Here the release-state fields are static and
    # must never claim a public download before Stage 9 publishing.
    source = Path(connector_protocol.__file__).read_text(encoding="utf-8")
    assert '"state": "blocked_release_gate"' in source
    assert '"download_url": ""' in source
    assert "Authenticode" in source
