"""Verify a StratForge server release ZIP before extraction or deployment."""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature


MAX_FILES = 10000
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024


def _b64url_decode(value: str) -> bytes:
    text = str(value or "").strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _safe_member_name(name: str) -> str:
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        raise RuntimeError("unsafe archive member path")
    path = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError("unsafe archive member path")
    if path.parts and ":" in path.parts[0]:
        raise RuntimeError("unsafe archive member path")
    return path.as_posix()


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    if info.file_size > MAX_MEMBER_BYTES:
        raise RuntimeError(f"archive member exceeds size limit: {info.filename}")
    with archive.open(info, "r") as handle:
        data = handle.read(MAX_MEMBER_BYTES + 1)
    if len(data) != info.file_size or len(data) > MAX_MEMBER_BYTES:
        raise RuntimeError(f"archive member size mismatch: {info.filename}")
    return data


def verify(
    path: Path,
    *,
    expected_key_fingerprint: str = "",
) -> dict[str, object]:
    archive_path = path.expanduser().resolve()
    if not archive_path.is_file():
        raise RuntimeError("release archive does not exist")
    with zipfile.ZipFile(archive_path, "r") as archive:
        infos = [item for item in archive.infolist() if not item.is_dir()]
        if not infos or len(infos) > MAX_FILES:
            raise RuntimeError("release archive has an invalid file count")
        if sum(item.file_size for item in infos) > MAX_TOTAL_BYTES:
            raise RuntimeError("release archive exceeds total size limit")

        by_name: dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            name = _safe_member_name(info.filename)
            if name in by_name:
                raise RuntimeError(f"duplicate archive member: {name}")
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if unix_mode and stat.S_ISLNK(unix_mode):
                raise RuntimeError(f"archive symlinks are forbidden: {name}")
            if info.flag_bits & 0x1:
                raise RuntimeError(f"encrypted archive members are forbidden: {name}")
            by_name[name] = info

        if "manifest.json" not in by_name or "manifest.sig" not in by_name:
            raise RuntimeError("release manifest or signature is missing")
        manifest_bytes = _read_member(archive, by_name["manifest.json"])
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("release manifest is invalid") from exc
        if manifest.get("schema_version") != 1 or manifest.get("product") != "StratForge Server":
            raise RuntimeError("release manifest contract is invalid")

        rows = manifest.get("files")
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("release manifest file list is invalid")
        expected: dict[str, dict[str, object]] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError("release manifest file row is invalid")
            name = _safe_member_name(str(row.get("path") or ""))
            if name in {"manifest.json", "manifest.sig"} or name in expected:
                raise RuntimeError(f"duplicate manifest file: {name}")
            expected[name] = row
        actual_payload = set(by_name) - {"manifest.json", "manifest.sig"}
        if actual_payload != set(expected):
            raise RuntimeError("archive payload does not exactly match manifest")

        for name, row in expected.items():
            info = by_name[name]
            expected_size = int(row.get("size") or -1)
            expected_hash = str(row.get("sha256") or "").upper()
            if info.file_size != expected_size:
                raise RuntimeError(f"payload size mismatch: {name}")
            payload = _read_member(archive, info)
            if hashlib.sha256(payload).hexdigest().upper() != expected_hash:
                raise RuntimeError(f"payload hash mismatch: {name}")

        signing = manifest.get("signing")
        if not isinstance(signing, dict) or signing.get("algorithm") != "ECDSA_P256_SHA256_RAW":
            raise RuntimeError("release signing contract is invalid")
        x = _b64url_decode(str(signing.get("public_key_x") or ""))
        y = _b64url_decode(str(signing.get("public_key_y") or ""))
        signature = _b64url_decode(
            _read_member(archive, by_name["manifest.sig"]).decode("ascii"),
        )
        if len(x) != 32 or len(y) != 32 or len(signature) != 64:
            raise RuntimeError("release signing material has an invalid length")
        actual_fingerprint = "SHA256:" + hashlib.sha256(b"\x04" + x + y).hexdigest()
        manifest_fingerprint = str(signing.get("key_fingerprint") or "")
        if not manifest_fingerprint or not hmac.compare_digest(
            actual_fingerprint.lower(), manifest_fingerprint.lower(),
        ):
            raise RuntimeError("release signing key fingerprint is invalid")
        expected_fingerprint_pin = str(expected_key_fingerprint or "").strip()
        trust_tier = str(manifest.get("trust_tier") or "")
        channel = str(manifest.get("channel") or "")
        if (trust_tier, channel) not in {
            ("development", "development"),
            ("production", "canary"),
            ("production", "stable"),
        }:
            raise RuntimeError("release trust tier and channel are inconsistent")
        if trust_tier == "production" and not expected_fingerprint_pin:
            raise RuntimeError(
                "Production release verification requires a trusted key fingerprint"
            )
        if expected_fingerprint_pin and not hmac.compare_digest(
            actual_fingerprint.lower(), expected_fingerprint_pin.lower(),
        ):
            raise RuntimeError("release signing key fingerprint is not trusted")
        public_key = ec.EllipticCurvePublicNumbers(
            int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1(),
        ).public_key()
        r = int.from_bytes(signature[:32], "big")
        s = int.from_bytes(signature[32:], "big")
        try:
            public_key.verify(
                encode_dss_signature(r, s), manifest_bytes, ec.ECDSA(hashes.SHA256()),
            )
        except Exception as exc:
            raise RuntimeError("release manifest signature is invalid") from exc

    return {
        "ok": True,
        "archive": str(archive_path),
        "version": str(manifest.get("version") or ""),
        "channel": str(manifest.get("channel") or ""),
        "trust_tier": str(manifest.get("trust_tier") or ""),
        "source_revision": str(manifest.get("source_revision") or ""),
        "key_fingerprint": actual_fingerprint,
        "file_count": len(expected),
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest().upper(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--expected-key-fingerprint", default="")
    args = parser.parse_args()
    try:
        result = verify(
            args.archive,
            expected_key_fingerprint=args.expected_key_fingerprint,
        )
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "error_class": type(exc).__name__,
            "error": str(exc)[:1000],
        }))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
