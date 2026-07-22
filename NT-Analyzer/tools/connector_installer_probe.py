"""Clean-path install, repair, tamper and rollback probe for Connector Setup."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


TEST_CODE = "2345-6789-ABCD-EFGH"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _run(setup: Path, *args: str) -> tuple[int, dict, str]:
    completed = subprocess.run(
        [str(setup), *args],
        cwd=setup.parent,
        text=True,
        capture_output=True,
        timeout=60,
    )
    text = completed.stdout.strip()
    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError:
        payload = {}
    return completed.returncode, payload, text


def _common(ninja_dir: Path, state_root: Path) -> list[str]:
    return [
        "--ninja-user-dir", str(ninja_dir),
        "--state-root", str(state_root),
        "--server-origin", "https://app.stratforges.com",
        "--channel", "stable",
        "--update-policy", "safe_restart",
        "--skip-uri-registration",
        "--non-interactive",
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="0.4.0-dev.1")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    release_root = root / ".artifacts" / "connector" / "releases" / args.version
    archive = next(release_root.glob("StratForge.Connector-*.zip"), None)
    if archive is None:
        raise SystemExit("release archive is missing; run build_connector_release.py first")

    checks: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="stratforge-installer-probe-") as temp:
        temp_root = Path(temp)
        extracted = temp_root / "extracted release"
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(extracted)
        setup = extracted / "StratForge.Connector.Setup.exe"
        code, verified, output = _run(setup, "--verify")
        checks["archive_self_verify"] = code == 0 and verified.get("ok") is True

        ninja_dir = temp_root / "Alternate Documents" / "NinjaTrader 8"
        custom = ninja_dir / "bin" / "Custom"
        custom.mkdir(parents=True)
        state_root = temp_root / "isolated LocalAppData"
        dll_target = custom / "NTAnalyzerBridge.dll"
        config_target = custom / "NTAnalyzerBridge.config.json"
        dll_target.write_bytes(b"legacy-bridge-before-stratforge")
        config_target.write_text(json.dumps({
            "schema_version": 1,
            "mode": "local_development",
            "project_root": "C:\\legacy\\NT-Analyzer",
            "ninjatrader_user_dir": str(ninja_dir),
        }, indent=2), encoding="utf-8")
        original_dll = _hash(dll_target)
        original_config = _hash(config_target)
        common = _common(ninja_dir, state_root)

        code, rejected, rejected_text = _run(
            setup, "--install", *common, "--enrollment-code", TEST_CODE,
        )
        checks["migration_requires_consent"] = (
            code != 0
            and rejected.get("error_class") == "InvalidOperationException"
            and _hash(dll_target) == original_dll
            and _hash(config_target) == original_config
        )

        code, installed, installed_text = _run(
            setup, "--install", *common, "--enrollment-code", TEST_CODE,
            "--migrate-local",
        )
        if code != 0:
            raise RuntimeError("install failed: " + installed_text[-1000:])
        state_dir = Path(installed["state_dir"])
        config = json.loads(config_target.read_text(encoding="utf-8"))
        payload_dll = extracted / "payload" / "NTAnalyzerBridge.dll"
        bootstrap = state_dir / "bootstrap.dpapi"
        checks["non_default_path_install"] = (
            installed.get("ok") is True
            and Path(installed["ninja_user_dir"]) == ninja_dir
            and _hash(dll_target) == _hash(payload_dll)
        )
        checks["strict_secret_free_config"] = (
            config.get("schema_version") == 3
            and config.get("mode") == "production_connector"
            and "project_root" not in config
            and "enrollment_code" not in config.get("production_connector", {})
            and config["production_connector"].get("enrollment_credential_ref") == "dpapi:bootstrap-v1"
            and TEST_CODE.replace("-", "") not in config_target.read_text(encoding="utf-8")
        )
        checks["dpapi_bootstrap"] = (
            bootstrap.is_file()
            and TEST_CODE.replace("-", "").encode() not in bootstrap.read_bytes()
            and TEST_CODE not in installed_text
        )

        dll_target.write_bytes(b"tampered-installed-dll")
        code, repaired, repaired_text = _run(setup, "--repair", *common)
        checks["repair_restores_payload"] = (
            code == 0 and repaired.get("ok") is True
            and _hash(dll_target) == _hash(payload_dll)
            and bootstrap.is_file()
        )

        tampered_payload = temp_root / "tampered-payload"
        shutil.copytree(extracted, tampered_payload)
        tampered_dll = tampered_payload / "payload" / "NTAnalyzerBridge.dll"
        data = bytearray(tampered_dll.read_bytes())
        data[len(data) // 2] ^= 0x01
        tampered_dll.write_bytes(data)
        code, tampered_result, _ = _run(
            tampered_payload / "StratForge.Connector.Setup.exe", "--verify",
        )
        checks["tampered_payload_rejected"] = (
            code != 0 and tampered_result.get("error_class") == "CryptographicException"
        )

        tampered_manifest = temp_root / "tampered-manifest"
        shutil.copytree(extracted, tampered_manifest)
        manifest_path = tampered_manifest / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = "99.0.0-tampered"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        code, signature_result, _ = _run(
            tampered_manifest / "StratForge.Connector.Setup.exe", "--verify",
        )
        checks["tampered_manifest_rejected"] = (
            code != 0 and signature_result.get("error_class") == "CryptographicException"
        )

        code, diagnostics, _ = _run(setup, "--diagnostics", *common)
        checks["diagnostics_redacted"] = (
            code == 0 and diagnostics.get("ok") is True
            and "enrollment" not in json.dumps(diagnostics).lower()
            and TEST_CODE not in json.dumps(diagnostics)
        )

        code, uninstalled, uninstall_text = _run(setup, "--uninstall", *common)
        checks["uninstall_restores_original"] = (
            code == 0 and uninstalled.get("ok") is True
            and _hash(dll_target) == original_dll
            and _hash(config_target) == original_config
            and (state_dir / "install-record.json").is_file()
            and (state_dir / "installer-journal.jsonl").is_file()
        )

        deep_ninja = temp_root / "Deep Link User" / "NinjaTrader 8"
        (deep_ninja / "bin" / "Custom").mkdir(parents=True)
        deep_state = temp_root / "Deep Link State"
        pairing_uri = "stratforge-connector://enroll?code=" + TEST_CODE
        code, deep_installed, deep_text = _run(
            setup,
            "--install",
            *_common(deep_ninja, deep_state),
            "--pairing-uri", pairing_uri,
        )
        checks["pairing_deep_link"] = (
            code == 0 and deep_installed.get("ok") is True and TEST_CODE not in deep_text
        )
        if code == 0:
            _run(setup, "--uninstall", *_common(deep_ninja, deep_state))

        setup_sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (root / "connector" / "installer").glob("*.cs")
        ).lower()
        checks["no_broker_password_prompt"] = (
            "broker_password" not in setup_sources
            and "broker password" not in setup_sources
        )
        checks["state_preserved_on_uninstall"] = bootstrap.is_file()

    failed = sorted(name for name, value in checks.items() if value is not True)
    report = {
        "ok": not failed,
        "version": args.version,
        "checks": checks,
        "failed": failed,
        "check_count": len(checks),
        "standalone_setup": True,
        "sdk_used_by_setup": False,
    }
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
