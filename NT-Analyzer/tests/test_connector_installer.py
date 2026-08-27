from __future__ import annotations

from pathlib import Path
import subprocess

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
    assert "ServerOriginExplicit" in engine
    assert 'string.Equals(uri.Host, "127.0.0.1"' in engine
    assert 'string.Equals(uri.Host, "localhost"' in engine
    assert "options.ServerOriginExplicit" in engine
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
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "dev"))
    # The payload needs an authorized workspace; contract details are verified
    # in test_connector_protocol. Here the release-state fields are static and
    # must never claim a public download before Stage 9 publishing.
    source = Path(connector_protocol.__file__).read_text(encoding="utf-8")
    assert '"state": "blocked_release_gate"' in source
    assert '"download_url": ""' in source
    assert "Authenticode" in source


def test_installing_against_a_local_backend_keeps_the_owner_runtime_directory() -> None:
    """A reinstall on a Development machine must not repoint the AddOn.

    LOCAL has no Connector transport to itself: the backend and the AddOn share
    one owner runtime directory, and they must share the same one or neither
    sees the other. A reinstall that hardcoded the installation spool pointed a
    working local AddOn away from the directory the backend reads, and LOCAL
    then showed NinjaTrader inactive with no accounts -- on a machine where
    NinjaTrader was running and the accounts were still on disk.
    """
    root = Path(__file__).resolve().parent.parent
    engine = (root / "connector" / "installer" / "InstallerEngine.cs").read_text(
        encoding="utf-8",
    )
    # The runtime directory is decided, not assumed.
    assert '["runtime_data_dir"] = ResolveRuntimeDataDir(' in engine
    assert '["runtime_data_dir"] = Path.Combine(stateDir, "spool")' not in engine
    # And it is decided by which backend this installation talks to.
    assert "private static bool IsLocalBackend(" in engine
    assert '"127.0.0.1"' in engine and '"localhost"' in engine
    assert "if (!IsLocalBackend(connector[\"server_origin\"]))" in engine
    assert "return spool;" in engine
    # An operator can state the directory outright.
    assert "options.RuntimeDataDir" in engine
    program = (root / "connector" / "installer" / "Program.cs").read_text(encoding="utf-8")
    assert '"--runtime-data-dir"' in program


def test_a_local_install_never_inherits_a_runtime_directory_inside_the_state_dir() -> None:
    """Carrying the previous value forward is right, unless the previous value
    is the spool a wrong install left behind -- which would make the fix
    inherit the bug."""
    root = Path(__file__).resolve().parent.parent
    engine = (root / "connector" / "installer" / "InstallerEngine.cs").read_text(
        encoding="utf-8",
    )
    assert "!IsInside(previous, stateDir)" in engine


def test_a_server_installation_still_uses_the_signed_spool_transport() -> None:
    """The Development rule must not reach the machines the protocol exists for."""
    root = Path(__file__).resolve().parent.parent
    engine = (root / "connector" / "installer" / "InstallerEngine.cs").read_text(
        encoding="utf-8",
    )
    resolver = engine[engine.index("private static string ResolveRuntimeDataDir"):]
    resolver = resolver[: resolver.index("private static bool IsInside")]
    assert 'string spool = Path.Combine(stateDir, "spool");' in resolver
    assert resolver.index("if (!IsLocalBackend") < resolver.index("options.RuntimeDataDir")
