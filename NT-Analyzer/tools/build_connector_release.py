"""Build one verified StratForge Connector release bundle."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.parse
import zipfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import secure_store


_SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_DEV_KEY_MAGIC = b"STRATFORGE-DEV-RELEASE-KEY-DPAPI-1\n"


def _run(command: list[str], *, cwd: Path) -> None:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if completed.returncode:
        detail = (completed.stdout + "\n" + completed.stderr)[-4000:]
        raise RuntimeError(f"command failed ({command[0]}): {detail}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _load_development_key(root: Path) -> ec.EllipticCurvePrivateKey:
    if not secure_store.available():
        raise RuntimeError("Windows DPAPI is required for the development release key")
    path = root / ".artifacts" / "connector" / "signing" / "development-key.dpapi"
    if path.is_file():
        raw = path.read_bytes()
        if not raw.startswith(_DEV_KEY_MAGIC):
            raise RuntimeError("development release key has an unknown format")
        der = secure_store._unprotect(base64.b64decode(raw[len(_DEV_KEY_MAGIC):]))
        key = serialization.load_der_private_key(der, password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise RuntimeError("development release key is not EC")
        return key
    key = ec.generate_private_key(ec.SECP256R1())
    der = key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(_DEV_KEY_MAGIC + base64.b64encode(secure_store._protect(der)))
    os.replace(temporary, path)
    return key


def _load_signing_key(root: Path, production: bool) -> tuple[ec.EllipticCurvePrivateKey, str]:
    if not production:
        return _load_development_key(root), "development"
    key_path = Path(os.environ.get("STRATFORGE_RELEASE_SIGNING_KEY_PEM") or "")
    if not key_path.is_file():
        raise RuntimeError("Production release requires STRATFORGE_RELEASE_SIGNING_KEY_PEM")
    password = os.environ.get("STRATFORGE_RELEASE_SIGNING_KEY_PASSWORD")
    key = serialization.load_pem_private_key(
        key_path.read_bytes(), password=password.encode() if password else None,
    )
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise RuntimeError("Production release key must be ECDSA P-256")
    if not os.environ.get("STRATFORGE_AUTHENTICODE_THUMBPRINT"):
        raise RuntimeError("Production release requires STRATFORGE_AUTHENTICODE_THUMBPRINT")
    if not re.fullmatch(
        r"[0-9A-Fa-f]{40}", os.environ["STRATFORGE_AUTHENTICODE_THUMBPRINT"].strip(),
    ):
        raise RuntimeError("STRATFORGE_AUTHENTICODE_THUMBPRINT must be a SHA-1 thumbprint")
    if shutil.which("signtool") is None:
        raise RuntimeError("Production release requires signtool on PATH")
    return key, "production"


def _public_values(key: ec.EllipticCurvePrivateKey) -> tuple[str, str, str]:
    numbers = key.public_key().public_numbers()
    x = numbers.x.to_bytes(32, "big")
    y = numbers.y.to_bytes(32, "big")
    fingerprint = "SHA256:" + hashlib.sha256(b"\x04" + x + y).hexdigest()
    return _b64url(x), _b64url(y), fingerprint


def _write_trust_source(path: Path, x: str, y: str, fingerprint: str, tier: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "namespace StratForge.Connector.Setup\n"
        "{\n"
        "    internal static class ReleaseTrust\n"
        "    {\n"
        f'        internal const string PublicKeyX = "{x}";\n'
        f'        internal const string PublicKeyY = "{y}";\n'
        f'        internal const string KeyFingerprint = "{fingerprint}";\n'
        f'        internal const string TrustTier = "{tier}";\n'
        "    }\n"
        "}\n",
        encoding="utf-8",
    )


def _authenticode_timestamp_url() -> str:
    timestamp = str(os.environ.get("STRATFORGE_AUTHENTICODE_TIMESTAMP_URL") or "").strip()
    parsed_timestamp = urllib.parse.urlsplit(timestamp)
    if parsed_timestamp.scheme not in {"http", "https"} or not parsed_timestamp.netloc:
        raise RuntimeError(
            "Production release requires an explicit trusted Authenticode timestamp URL"
        )
    return timestamp


def _authenticode_sign(files: list[Path]) -> None:
    thumbprint = os.environ["STRATFORGE_AUTHENTICODE_THUMBPRINT"]
    timestamp = _authenticode_timestamp_url()
    for path in files:
        _run([
            "signtool", "sign", "/sha1", thumbprint, "/fd", "SHA256",
            "/tr", timestamp, "/td", "SHA256", str(path),
        ], cwd=path.parent)


def _authenticode_verify(files: list[Path]) -> None:
    for path in files:
        _run([
            "signtool", "verify", "/pa", "/all", "/tw", str(path),
        ], cwd=path.parent)


def _git_state(root: Path) -> tuple[str, bool]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, text=True, capture_output=True, check=True,
    ).stdout.strip() != ""
    return revision, dirty


def build(args: argparse.Namespace) -> dict:
    root = Path(__file__).resolve().parent.parent
    match = _SEMVER.fullmatch(args.version)
    prerelease = (match.group(4) or "") if match else ""
    if not match or any(
        item.isdigit() and len(item) > 1 and item.startswith("0")
        for item in prerelease.split(".") if item
    ):
        raise RuntimeError("--version must be semantic versioning")
    if args.channel not in {"stable", "canary"}:
        raise RuntimeError("--channel must be stable or canary")
    revision, dirty = _git_state(root)
    if args.production and dirty:
        raise RuntimeError("Production release requires a clean Git worktree")
    key, trust_tier = _load_signing_key(root, args.production)
    x, y, fingerprint = _public_values(key)
    release_root = root / ".artifacts" / "connector" / "releases" / args.version
    if release_root.exists():
        if not args.force:
            raise RuntimeError(f"release output already exists: {release_root}")
        expected_parent = (root / ".artifacts" / "connector" / "releases").resolve()
        if release_root.resolve().parent != expected_parent:
            raise RuntimeError("refusing to replace release output outside the artifact root")
        shutil.rmtree(release_root)
    bundle = release_root / "bundle"
    payload = bundle / "payload"
    payload.mkdir(parents=True)
    trust_source = release_root / "build" / "GeneratedReleaseTrust.cs"
    _write_trust_source(trust_source, x, y, fingerprint, trust_tier)
    major, minor, patch = match.group(1), match.group(2), match.group(3)
    assembly_version = f"{major}.{minor}.{patch}.0"

    bridge_project = root / "bridge" / "NTAnalyzerBridge.csproj"
    setup_project = root / "connector" / "installer" / "StratForge.Connector.Setup.csproj"
    updater_project = root / "connector" / "updater" / "StratForge.Connector.Updater.csproj"
    # A release must build from a genuinely clean checkout, where obj/ and the
    # net48 reference-assembly package cache have not been primed by an earlier
    # developer build. Restore explicitly, then keep every compilation locked
    # to that resolved graph with --no-restore.
    for project in (bridge_project, setup_project, updater_project):
        _run(["dotnet", "restore", str(project), "--nologo"], cwd=root)

    _run([
        "dotnet", "build", str(bridge_project),
        "-c", "Release", "--no-restore",
        f"-p:Version={args.version}",
        f"-p:AssemblyVersion={assembly_version}",
        f"-p:FileVersion={assembly_version}",
    ], cwd=root)
    _run([
        "dotnet", "build", str(setup_project),
        "-c", "Release", "--no-restore",
        f"-p:Version={args.version}",
        f"-p:AssemblyVersion={assembly_version}",
        f"-p:FileVersion={assembly_version}",
        f"-p:ReleaseTrustSource={trust_source}",
    ], cwd=root)
    _run([
        "dotnet", "build", str(updater_project),
        "-c", "Release", "--no-restore",
        f"-p:Version={args.version}",
        f"-p:AssemblyVersion={assembly_version}",
        f"-p:FileVersion={assembly_version}",
        f"-p:ReleaseTrustSource={trust_source}",
    ], cwd=root)

    bridge_dll = root / "bridge" / "bin" / "Release" / "NTAnalyzerBridge.dll"
    setup_dir = root / "connector" / "installer" / "bin" / "Release"
    updater_dir = root / "connector" / "updater" / "bin" / "Release"
    shutil.copy2(bridge_dll, payload / "NTAnalyzerBridge.dll")
    shutil.copy2(setup_dir / "StratForge.Connector.Setup.exe", bundle / "StratForge.Connector.Setup.exe")
    shutil.copy2(
        updater_dir / "StratForge.Connector.Updater.exe",
        bundle / "StratForge.Connector.Updater.exe",
    )
    shutil.copy2(setup_dir / "Newtonsoft.Json.dll", bundle / "Newtonsoft.Json.dll")
    shutil.copy2(root / "connector" / "COMPATIBILITY.md", bundle / "COMPATIBILITY.md")
    (bundle / "INSTALL.cmd").write_text(
        '@echo off\r\n"%~dp0StratForge.Connector.Setup.exe"\r\n', encoding="ascii",
    )
    (payload / "NTAnalyzerBridge.config.default.json").write_text(json.dumps({
        "schema_version": 3,
        "mode": "production_connector",
        "ninjatrader_user_dir": "<detected by installer>",
        "runtime_data_dir": "<DPAPI state>/spool",
        "production_connector": {
            "enabled": True,
            "server_origin": "https://app.stratforges.com",
            "protocol_version": "1.0",
            "connector_version": args.version,
            "enrollment_credential_ref": "dpapi:bootstrap-v1",
            "state_dir": "<DPAPI state>",
            "heartbeat_interval_ms": 15000,
            "command_poll_seconds": 15,
            "release_channel": args.channel,
            "update_policy": "safe_restart",
        },
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    signed_files = [
        bundle / "StratForge.Connector.Setup.exe",
        bundle / "StratForge.Connector.Updater.exe",
        payload / "NTAnalyzerBridge.dll",
    ]
    if args.production:
        _authenticode_sign(signed_files)
        _authenticode_verify(signed_files)

    files = []
    for path in sorted(bundle.rglob("*")):
        if not path.is_file() or path.name in {"manifest.json", "manifest.sig"}:
            continue
        files.append({
            "path": path.relative_to(bundle).as_posix(),
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        })
    built_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    manifest = {
        "schema_version": 1,
        "product": "StratForge Connector",
        "version": args.version,
        "channel": args.channel,
        "trust_tier": trust_tier,
        "source_revision": revision + ("-dirty" if dirty else ""),
        "built_at_utc": built_at,
        "protocol_version": "1.0",
        "config_schema_version": 3,
        "migration_version": 1,
        "compatibility": {
            "windows": ["10-22H2", "11"],
            "ninjatrader": "8.1.x-x64",
            "dotnet_framework": "4.8",
            "macos_supported": False,
        },
        "rollback": {
            "last_known_good_required": True,
            "preserve_config": True,
            "preserve_device_key": True,
            "max_automatic_rollbacks": 1,
        },
        "signing": {
            "algorithm": "ECDSA_P256_SHA256_RAW",
            "key_fingerprint": fingerprint,
            "authenticode_required": bool(args.production),
        },
        "files": files,
    }
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    (bundle / "manifest.json").write_bytes(manifest_bytes)
    der_signature = key.sign(manifest_bytes, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    (bundle / "manifest.sig").write_text(_b64url(signature), encoding="ascii")

    verify = subprocess.run(
        [str(bundle / "StratForge.Connector.Setup.exe"), "--verify"],
        cwd=bundle, text=True, capture_output=True,
    )
    if verify.returncode:
        raise RuntimeError("built Setup rejected its own signed release: " + verify.stdout[-1000:])
    verify_result = json.loads(verify.stdout)
    archive = release_root / f"StratForge.Connector-{args.version}-{args.channel}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                zipped.write(path, path.relative_to(bundle).as_posix())
    archive_hash = _sha256(archive)
    (archive.with_suffix(archive.suffix + ".sha256")).write_text(
        f"{archive_hash}  {archive.name}\n", encoding="ascii",
    )
    report = {
        "ok": True,
        "version": args.version,
        "channel": args.channel,
        "trust_tier": trust_tier,
        "source_revision": manifest["source_revision"],
        "manifest_sha256": _sha256(bundle / "manifest.json"),
        "key_fingerprint": fingerprint,
        "archive_sha256": archive_hash,
        "archive": str(archive),
        "bundle": str(bundle),
        "setup_self_verify": bool(verify_result.get("ok")),
        "authenticode": bool(args.production),
        "authenticode_verified": bool(args.production),
        "authenticode_timestamp_verified": bool(args.production),
        "file_count": len(files),
    }
    (release_root / "build-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=("stable", "canary"), default="stable")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        report = build(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error_class": type(exc).__name__, "error": str(exc)[:1000]}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
