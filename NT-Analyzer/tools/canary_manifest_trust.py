#!/usr/bin/env python3
"""Verify a signed StratForge server release manifest against a pinned key.

`tools/canary_blue_green_promote.sh` shells out to this module (as a plain
script, not a package import, so it works regardless of the ops-tooling
checkout layout) to get the *only* trustworthy source of the version/git
SHA/build ID/artifact SHA it deploys. It intentionally never trusts the
public key embedded in the manifest itself for the actual cryptographic
verification: only a pinned, host-local trusted-key file (public material
only, never a secret) is used. The manifest's own declared key/fingerprint is
compared only as an early, human-readable mismatch diagnostic -- verification
below always uses the pinned key, so a forged manifest key can never
substitute for it.

The trusted-key file is plain JSON, safe to store world-readable (it is
public key material, not a secret):

    {
      "algorithm": "ECDSA_P256_SHA256_RAW",
      "public_key_x": "<base64url>",
      "public_key_y": "<base64url>",
      "key_fingerprint": "SHA256:<hex>"
    }

It must be provisioned on the host out-of-band (e.g. exported once from the
production signing key right after it is generated, and copied to a
protected config path) before the first promotion that relies on it.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature


class ManifestTrustError(RuntimeError):
    pass


def _b64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded)


def load_trusted_key(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise ManifestTrustError(f"trusted signing key file missing: {path}")
    try:
        trusted = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestTrustError("trusted signing key file is unreadable") from exc
    if not isinstance(trusted, dict) or trusted.get("algorithm") != "ECDSA_P256_SHA256_RAW":
        raise ManifestTrustError("trusted signing key file has an unexpected algorithm")
    for field in ("public_key_x", "public_key_y", "key_fingerprint"):
        if not str(trusted.get(field) or "").strip():
            raise ManifestTrustError(f"trusted signing key file is missing {field}")
    try:
        x = int.from_bytes(_b64url_decode(trusted["public_key_x"]), "big")
        y = int.from_bytes(_b64url_decode(trusted["public_key_y"]), "big")
    except (ValueError, TypeError) as exc:
        raise ManifestTrustError("trusted signing key file has invalid key material") from exc
    encoded_point = b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")
    recomputed_fp = "SHA256:" + hashlib.sha256(encoded_point).hexdigest()
    if recomputed_fp != trusted["key_fingerprint"]:
        raise ManifestTrustError(
            "trusted signing key file fingerprint does not match its own key material"
        )
    return {"x": x, "y": y, "key_fingerprint": trusted["key_fingerprint"]}


def verify_release(
    release_dir: Path, trusted_key_path: Path, *, required_environment: str = "canary",
) -> Dict[str, Any]:
    """Verify the release's manifest signature against the pinned key.

    Returns a dict with the manifest-derived, now-trusted build identity
    (version/channel/build_id/git_commit_sha/build_timestamp_utc plus a
    locally recomputed artifact_sha256 = sha256(manifest.json bytes)).
    Raises :class:`ManifestTrustError` on any mismatch/failure -- the caller
    must treat that as a hard refusal, never a warning.
    """
    manifest_path = release_dir / "manifest.json"
    signature_path = release_dir / "manifest.sig"
    if not manifest_path.is_file():
        raise ManifestTrustError("manifest.json is missing from the release directory")
    if not signature_path.is_file():
        raise ManifestTrustError("manifest.sig is missing from the release directory")

    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestTrustError("manifest.json is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise ManifestTrustError("manifest.json must be a JSON object")
    if manifest.get("trust_tier") != "production":
        raise ManifestTrustError(
            "manifest trust_tier is not 'production': " + str(manifest.get("trust_tier"))
        )
    signing = manifest.get("signing")
    if not isinstance(signing, dict) or signing.get("algorithm") != "ECDSA_P256_SHA256_RAW":
        raise ManifestTrustError("manifest signing block has an unexpected algorithm")

    trusted = load_trusted_key(trusted_key_path)
    if signing.get("key_fingerprint") != trusted["key_fingerprint"]:
        raise ManifestTrustError(
            "manifest key_fingerprint does not match the pinned trusted production key"
        )

    try:
        signature = _b64url_decode(signature_path.read_text(encoding="ascii").strip())
    except (OSError, UnicodeError, ValueError) as exc:
        raise ManifestTrustError("manifest.sig is not valid base64url") from exc
    if len(signature) != 64:
        raise ManifestTrustError("manifest.sig has an unexpected length")

    public_key = ec.EllipticCurvePublicNumbers(
        trusted["x"], trusted["y"], ec.SECP256R1(),
    ).public_key()
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    try:
        public_key.verify(
            encode_dss_signature(r, s), manifest_bytes, ec.ECDSA(hashes.SHA256()),
        )
    except Exception as exc:
        raise ManifestTrustError("manifest signature verification failed") from exc

    if bool(manifest.get("dirty")):
        raise ManifestTrustError("manifest reports a dirty build")
    deployable = manifest.get("deployable_environments")
    if not isinstance(deployable, list) or required_environment not in deployable:
        raise ManifestTrustError(
            f"manifest does not declare {required_environment!r} as a deployable environment"
        )

    identity = {
        "version": str(manifest.get("version") or ""),
        "channel": str(manifest.get("channel") or ""),
        "build_id": str(manifest.get("build_id") or ""),
        "git_commit_sha": str(manifest.get("git_commit_sha") or ""),
        "build_timestamp_utc": str(manifest.get("build_timestamp_utc") or ""),
    }
    if not all(identity.values()):
        raise ManifestTrustError("manifest is missing required build-identity fields")
    identity["artifact_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    identity["key_fingerprint"] = str(signing["key_fingerprint"])
    identity["manifest_signature_verified"] = True
    return identity


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_dir", type=Path)
    parser.add_argument("trusted_key_path", type=Path)
    parser.add_argument("--required-environment", default="canary")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        identity = verify_release(
            args.release_dir, args.trusted_key_path,
            required_environment=args.required_environment,
        )
    except ManifestTrustError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **identity}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
