"""Build one verified, source-revision-bound StratForge server release."""
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
import zipfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import build_connector_release


ROOT = Path(__file__).resolve().parent.parent
_SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_INCLUDED_TREES = ("app", "ai_lab", "data", "deploy", "docs/governance")
_INCLUDED_FILES = (
    "README.md",
    "README-RUN-MODES.md",
    "VERSION.json",
    "requirements.txt",
    "docs/strategies/AI_STRATEGY_LAB_QUALITY.md",
    "docs/strategies/AI_STRATEGY_LAB_RUN_CONTROLS.md",
    "docs/operations/CONNECTOR_INSTALL_GUIDE.md",
    "docs/architecture/CONNECTOR_PROTOCOL_V1.md",
    "docs/operations/MARKET_DATA_PRODUCTION_RUNBOOK.md",
    "docs/operations/PRODUCTION_DEPLOYMENT_RUNBOOK.md",
    "docs/operations/PRODUCTION_OPERATIONS_RUNBOOK.md",
    "docs/operations/PRODUCTION_STORAGE_RUNBOOK.md",
    "docs/operations/PRODUCTION_TELEGRAM_RUNBOOK.md",
    "docs/operations/PRODUCTION_WORKER_RUNBOOK.md",
    "docs/strategies/risk-profile.md",
    "tools/production_preflight.py",
    "tools/production_storage_cli.py",
    "tools/canary_blue_green_promote.sh",
    "tools/production_blue_green_promote.sh",
    "tools/production_blue_green_rollback.sh",
    "tools/canary_isolation_provision.py",
    "tools/canary_manifest_trust.py",
    "tools/release_static_scan.py",
    "tools/verify_server_release.py",
)
_EXCLUDED_FILES = {"docs/agents/AGENTS.md", "docs/AI_DIALOGUE_CONTRACT.md"}


def _run(command: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if completed.returncode:
        detail = (completed.stdout + "\n" + completed.stderr)[-4000:]
        raise RuntimeError(f"command failed ({command[0]}): {detail}")
    return completed.stdout


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _git_state(root: Path) -> tuple[str, bool]:
    revision = _run(["git", "rev-parse", "HEAD"], cwd=root).strip()
    dirty = bool(_run(["git", "status", "--porcelain"], cwd=root).strip())
    return revision, dirty


def _selected_files(root: Path) -> list[Path]:
    pathspecs = [*_INCLUDED_TREES, *_INCLUDED_FILES]
    raw = subprocess.check_output(
        ["git", "ls-files", "-z", "--", *pathspecs], cwd=root,
    ).decode("utf-8", errors="surrogateescape")
    selected: list[Path] = []
    for value in sorted(item for item in raw.split("\0") if item):
        relative = Path(value)
        normalized = relative.as_posix()
        if normalized in _EXCLUDED_FILES:
            continue
        source = root / relative
        if source.is_symlink():
            raise RuntimeError(f"release source symlinks are forbidden: {normalized}")
        if not source.is_file():
            raise RuntimeError(f"tracked release source is missing: {normalized}")
        selected.append(relative)
    required = {
        "app/server.py",
        "app/production_workers.py",
        "app/production_telegram.py",
        "app/observability.py",
        "deploy/production/stratforge.service",
        "deploy/production/stratforge-worker.service",
        "deploy/production/stratforge-telegram.service",
        "deploy/production/stratforge-operations.timer",
        "tools/production_preflight.py",
        "tools/canary_blue_green_promote.sh",
        "tools/production_blue_green_promote.sh",
        "tools/production_blue_green_rollback.sh",
        "tools/canary_manifest_trust.py",
        "requirements.txt",
        "VERSION.json",
    }
    present = {path.as_posix() for path in selected}
    missing = sorted(required - present)
    if missing:
        raise RuntimeError("incomplete server release selection: " + ", ".join(missing))
    return selected


def _load_signing_key(
    root: Path, production: bool,
) -> tuple[ec.EllipticCurvePrivateKey, str]:
    if not production:
        return build_connector_release._load_development_key(root), "development"
    raw_path = str(os.environ.get("STRATFORGE_RELEASE_SIGNING_KEY_PEM") or "").strip()
    key_path = Path(raw_path).expanduser() if raw_path else Path()
    if not raw_path or not key_path.is_file():
        raise RuntimeError("Production release requires STRATFORGE_RELEASE_SIGNING_KEY_PEM")
    password = os.environ.get("STRATFORGE_RELEASE_SIGNING_KEY_PASSWORD")
    key = serialization.load_pem_private_key(
        key_path.read_bytes(), password=password.encode() if password else None,
    )
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
        key.curve, ec.SECP256R1,
    ):
        raise RuntimeError("Production release key must be ECDSA P-256")
    return key, "production"


def _public_signing(key: ec.EllipticCurvePrivateKey) -> dict[str, str]:
    numbers = key.public_key().public_numbers()
    encoded = (
        b"\x04"
        + numbers.x.to_bytes(32, "big")
        + numbers.y.to_bytes(32, "big")
    )
    return {
        "algorithm": "ECDSA_P256_SHA256_RAW",
        "public_key_x": _b64url(numbers.x.to_bytes(32, "big")),
        "public_key_y": _b64url(numbers.y.to_bytes(32, "big")),
        "key_fingerprint": "SHA256:" + hashlib.sha256(encoded).hexdigest(),
    }


def _verify_signature(
    key: ec.EllipticCurvePrivateKey, manifest_bytes: bytes, signature: bytes,
) -> None:
    if len(signature) != 64:
        raise RuntimeError("manifest signature has an invalid length")
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    key.public_key().verify(
        encode_dss_signature(r, s), manifest_bytes, ec.ECDSA(hashes.SHA256()),
    )


def build(args: argparse.Namespace) -> dict[str, object]:
    match = _SEMVER.fullmatch(args.version)
    prerelease = (match.group(4) or "") if match else ""
    if not match or any(
        item.isdigit() and len(item) > 1 and item.startswith("0")
        for item in prerelease.split(".") if item
    ):
        raise RuntimeError("--version must be semantic versioning")
    if args.production and args.channel not in {"beta", "stable"}:
        raise RuntimeError("Production-trust server release must be beta or stable")
    if not args.production and args.channel != "dev":
        raise RuntimeError("development-trust server release must remain dev")

    identity = json.loads((ROOT / "VERSION.json").read_text(encoding="utf-8"))
    if str(identity.get("version") or "") != args.version:
        raise RuntimeError("--version must match VERSION.json")
    if str(identity.get("channel") or "") != args.channel:
        raise RuntimeError("--channel must match VERSION.json")
    revision, dirty = _git_state(ROOT)
    if dirty:
        raise RuntimeError("Server release requires a clean Git worktree")
    key, trust_tier = _load_signing_key(ROOT, args.production)
    release_root = ROOT / ".artifacts" / "server" / "releases" / args.version
    if release_root.exists():
        if not args.force:
            raise RuntimeError(f"release output already exists: {release_root}")
        expected_parent = (ROOT / ".artifacts" / "server" / "releases").resolve()
        if release_root.resolve().parent != expected_parent:
            raise RuntimeError("refusing to replace release output outside the artifact root")
        shutil.rmtree(release_root)
    bundle = release_root / "bundle"
    bundle.mkdir(parents=True)

    selected = _selected_files(ROOT)
    for relative in selected:
        destination = bundle / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)

    files = []
    for path in sorted(bundle.rglob("*")):
        if path.is_file():
            files.append({
                "path": path.relative_to(bundle).as_posix(),
                "sha256": _sha256(path),
                "size": path.stat().st_size,
            })
    migrations = [
        {
            "name": path.name,
            "sha256": _sha256(path),
        }
        for path in sorted((bundle / "app" / "production_storage" / "migrations").glob("*.sql"))
    ]
    built_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    build_id = f"sf-{args.version}-{revision[:12]}-{built_at.replace(':', '').replace('-', '')}"
    deployable_environments = (
        ["canary", "production"] if args.production else ["development"]
    )
    manifest = {
        "schema_version": 1,
        "product": "StratForge Server",
        "version": args.version,
        "channel": args.channel,
        "app_version": args.version,
        "release_channel": args.channel,
        "build_id": build_id,
        "git_commit_sha": revision,
        "build_timestamp_utc": built_at,
        "dirty": False,
        "deployable_environments": deployable_environments,
        "trust_tier": trust_tier,
        "source_revision": revision,
        "built_at_utc": built_at,
        "python": ">=3.11,<3.14",
        "database_migrations": migrations,
        "rollback": {
            "immutable_release_required": True,
            "previous_symlink_required": True,
            "database_restore_isolated_only": True,
            "persistent_state_outside_release": True,
        },
        "signing": _public_signing(key),
        "files": files,
    }
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    manifest_path = bundle / "manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    der = key.sign(manifest_bytes, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    signature_path = bundle / "manifest.sig"
    signature_path.write_text(_b64url(signature), encoding="ascii")
    _verify_signature(key, manifest_path.read_bytes(), signature)

    _run([sys.executable, "tools/release_static_scan.py"], cwd=bundle)
    archive = release_root / f"StratForge.Server-{args.version}-{args.channel}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                zipped.write(path, path.relative_to(bundle).as_posix())
    archive_hash = _sha256(archive)
    verified = json.loads(_run([
        sys.executable, "tools/verify_server_release.py", str(archive),
    ], cwd=ROOT))
    if not verified.get("ok"):
        raise RuntimeError("server release archive self-verification failed")
    archive.with_suffix(archive.suffix + ".sha256").write_text(
        f"{archive_hash}  {archive.name}\n", encoding="ascii",
    )
    report = {
        "ok": True,
        "version": args.version,
        "channel": args.channel,
        "app_version": args.version,
        "release_channel": args.channel,
        "build_id": build_id,
        "git_commit_sha": revision,
        "build_timestamp_utc": built_at,
        "dirty": False,
        "deployable_environments": deployable_environments,
        "trust_tier": trust_tier,
        "source_revision": revision,
        "manifest_sha256": _sha256(manifest_path),
        "archive_sha256": archive_hash,
        "archive": str(archive),
        "bundle": str(bundle),
        "signature_verified": True,
        "archive_self_verified": True,
        "static_scan": True,
        "file_count": len(files),
        "migration_count": len(migrations),
    }
    (release_root / "build-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--channel", choices=("dev", "beta", "stable"), default="dev",
    )
    parser.add_argument(
        "--production", action="store_true",
        help="sign for immutable Canary-to-Production promotion",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        report = build(args)
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "error_class": type(exc).__name__,
            "error": str(exc)[:1000],
        }))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
