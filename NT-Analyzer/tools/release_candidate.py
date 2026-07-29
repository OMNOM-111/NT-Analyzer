"""Build and verify one immutable StratForge release candidate.

The command never deploys, promotes, overwrites, or force-rebuilds an artifact.
Canary and Production promotion must reference the hashes emitted here.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import build_connector_release, build_server_release, verify_server_release


ROOT = Path(__file__).resolve().parent.parent


def _run(command: list[str]) -> str:
    completed = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True,
    )
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


def _git_state() -> tuple[str, bool]:
    revision = _run(["git", "rev-parse", "HEAD"]).strip()
    dirty = bool(_run(["git", "status", "--porcelain"]).strip())
    return revision, dirty


def _identity() -> dict[str, Any]:
    value = json.loads((ROOT / "VERSION.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("VERSION.json must contain an object")
    return value


def _has_prerelease(version: str) -> bool:
    match = build_server_release._SEMVER.fullmatch(version)
    if not match:
        raise RuntimeError(f"invalid semantic version: {version}")
    return bool(match.group(4))


def _validate_versions(
    identity: dict[str, Any],
    *,
    production: bool,
    connector_version: str,
    server_only: bool,
) -> str:
    server_version = str(identity.get("version") or "").strip()
    server_prerelease = _has_prerelease(server_version)
    if production:
        if server_only:
            raise RuntimeError("Production candidate must include Server and Connector")
        if str(identity.get("channel") or "") != "stable":
            raise RuntimeError("Production candidate requires VERSION.json channel=stable")
        if str(identity.get("status") or "") not in {"release_candidate", "ready"}:
            raise RuntimeError(
                "Production candidate requires VERSION.json status=release_candidate or ready"
            )
        if server_prerelease:
            raise RuntimeError("Production candidate requires a stable Server SemVer")
        if _has_prerelease(connector_version):
            raise RuntimeError("Production candidate requires a stable Connector SemVer")
    else:
        if str(identity.get("channel") or "") != "development":
            raise RuntimeError("Development candidate requires VERSION.json channel=development")
        if str(identity.get("status") or "") != "in_development":
            raise RuntimeError(
                "Development candidate requires VERSION.json status=in_development"
            )
        if not server_prerelease:
            raise RuntimeError("Development candidate requires a prerelease Server SemVer")
        if not server_only and not _has_prerelease(connector_version):
            raise RuntimeError("Development candidate requires a prerelease Connector SemVer")
    return server_version


def _load_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"release output is incomplete or invalid: {path}") from exc
    if not isinstance(value, dict) or value.get("ok") is not True:
        raise RuntimeError(f"release report is not successful: {path}")
    return value


def _validate_report(
    report: dict[str, Any],
    *,
    product: str,
    version: str,
    channel: str,
    trust_tier: str,
    revision: str,
    expected_key_fingerprint: str = "",
) -> None:
    expected = {
        "version": version,
        "channel": channel,
        "trust_tier": trust_tier,
        "source_revision": revision,
    }
    for name, value in expected.items():
        if str(report.get(name) or "") != value:
            raise RuntimeError(
                f"existing {product} artifact has unexpected {name}; "
                "the version is burned and must not be rebuilt"
            )
    expected_fingerprint = str(expected_key_fingerprint or "").strip()
    if expected_fingerprint and not hmac.compare_digest(
        str(report.get("key_fingerprint") or "").lower(),
        expected_fingerprint.lower(),
    ):
        raise RuntimeError(
            f"existing {product} artifact is not signed by the trusted Production key; "
            "the version is burned and must not be rebuilt"
        )


def _server_candidate(
    *, version: str, production: bool, revision: str, trusted_fingerprint: str = "",
) -> dict[str, Any]:
    channel = "stable" if production else "development"
    trust_tier = "production" if production else "development"
    root = ROOT / ".artifacts" / "server" / "releases" / version
    report_path = root / "build-report.json"
    if root.exists():
        report = _load_report(report_path)
    else:
        report = build_server_release.build(argparse.Namespace(
            version=version,
            channel=channel,
            production=production,
            force=False,
        ))
    _validate_report(
        report,
        product="Server",
        version=version,
        channel=channel,
        trust_tier=trust_tier,
        revision=revision,
        expected_key_fingerprint=trusted_fingerprint,
    )
    archive = root / f"StratForge.Server-{version}-{channel}.zip"
    if _sha256(archive) != str(report.get("archive_sha256") or "").upper():
        raise RuntimeError("Server archive hash differs from its build report")
    fingerprint = trusted_fingerprint or str(report.get("key_fingerprint") or "")
    verified = verify_server_release.verify(
        archive,
        expected_key_fingerprint=fingerprint,
    )
    if verified.get("ok") is not True:
        raise RuntimeError("Server archive verification failed")
    return report


def _connector_candidate(
    *, version: str, production: bool, revision: str, trusted_fingerprint: str = "",
) -> dict[str, Any]:
    channel = "stable" if production else "canary"
    trust_tier = "production" if production else "development"
    root = ROOT / ".artifacts" / "connector" / "releases" / version
    report_path = root / "build-report.json"
    if root.exists():
        report = _load_report(report_path)
    else:
        report = build_connector_release.build(argparse.Namespace(
            version=version,
            channel=channel,
            production=production,
            force=False,
        ))
    _validate_report(
        report,
        product="Connector",
        version=version,
        channel=channel,
        trust_tier=trust_tier,
        revision=revision,
        expected_key_fingerprint=trusted_fingerprint,
    )
    archive = root / f"StratForge.Connector-{version}-{channel}.zip"
    if _sha256(archive) != str(report.get("archive_sha256") or "").upper():
        raise RuntimeError("Connector archive hash differs from its build report")
    bundle = root / "bundle"
    verify = subprocess.run(
        [str(bundle / "StratForge.Connector.Setup.exe"), "--verify"],
        cwd=bundle,
        text=True,
        capture_output=True,
    )
    if verify.returncode:
        raise RuntimeError("Connector Setup self-verification failed")
    if production:
        build_connector_release._authenticode_verify([
            bundle / "StratForge.Connector.Setup.exe",
            bundle / "StratForge.Connector.Updater.exe",
            bundle / "payload" / "NTAnalyzerBridge.dll",
        ])
    return report


def build_candidate(args: argparse.Namespace) -> dict[str, Any]:
    revision, dirty = _git_state()
    if dirty:
        raise RuntimeError("Release candidate requires a clean Git worktree")
    identity = _identity()
    connector_version = str(args.connector_version or "").strip()
    if not args.server_only and not connector_version:
        raise RuntimeError("--connector-version is required unless --server-only is used")
    server_version = _validate_versions(
        identity,
        production=bool(args.production),
        connector_version=connector_version,
        server_only=bool(args.server_only),
    )

    trusted_fingerprint = ""
    if args.production:
        # Validate all external material before either immutable artifact is built.
        server_key, _ = build_server_release._load_signing_key(ROOT, True)
        connector_key, _ = build_connector_release._load_signing_key(ROOT, True)
        trusted_fingerprint = build_server_release._public_signing(server_key)[
            "key_fingerprint"
        ]
        connector_fingerprint = build_connector_release._public_values(connector_key)[2]
        if not hmac.compare_digest(
            trusted_fingerprint.lower(), connector_fingerprint.lower(),
        ):
            raise RuntimeError("Server and Connector Production signing keys differ")
        build_connector_release._authenticode_timestamp_url()

    connector = None
    if not args.server_only:
        connector = _connector_candidate(
            version=connector_version,
            production=bool(args.production),
            revision=revision,
            trusted_fingerprint=trusted_fingerprint,
        )
    server = _server_candidate(
        version=server_version,
        production=bool(args.production),
        revision=revision,
        trusted_fingerprint=trusted_fingerprint,
    )

    candidate = {
        "schema_version": 1,
        "ok": True,
        "mode": "production" if args.production else "development",
        "source_revision": revision,
        "server": server,
        "connector": connector,
        "immutable": True,
        "rebuild_for_promotion_forbidden": True,
        "live_trading_allowed": False,
        "real_payments_allowed": False,
    }
    suffix = connector_version if connector_version else "server-only"
    target = (
        ROOT / ".artifacts" / "release-candidates"
        / f"{server_version}--{suffix}" / "release-candidate.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(candidate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    candidate["candidate_report"] = str(target)
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--connector-version", default="")
    parser.add_argument("--server-only", action="store_true")
    args = parser.parse_args()
    try:
        result = build_candidate(args)
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "error_class": type(exc).__name__,
            "error": str(exc)[:1000],
        }, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
