"""Verify a StratForge server release ZIP before extraction or deployment."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature


MAX_FILES = 10000
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")
_BUILD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")


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


def verify(path: Path) -> dict[str, object]:
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
        channel = str(manifest.get("release_channel") or "")
        if channel not in {"dev", "beta", "stable"} or manifest.get("channel") != channel:
            raise RuntimeError("release channel contract is invalid")
        version = str(manifest.get("app_version") or "")
        if not version or manifest.get("version") != version:
            raise RuntimeError("release version contract is invalid")
        revision = str(manifest.get("git_commit_sha") or "")
        if not _GIT_SHA_RE.fullmatch(revision) or manifest.get("source_revision") != revision:
            raise RuntimeError("release Git identity is invalid")
        build_id = str(manifest.get("build_id") or "")
        if not _BUILD_ID_RE.fullmatch(build_id):
            raise RuntimeError("release build id is invalid")
        timestamp = str(manifest.get("build_timestamp_utc") or "")
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError("release build timestamp is invalid") from exc
        if (
            parsed_timestamp.tzinfo is None
            or parsed_timestamp.utcoffset().total_seconds() != 0
            or not timestamp.endswith("Z")
            or manifest.get("built_at_utc") != timestamp
        ):
            raise RuntimeError("release build timestamp is invalid")
        if manifest.get("dirty") is not False:
            raise RuntimeError("release artifact must be clean")
        environments = manifest.get("deployable_environments")
        expected_environments = (
            ["development"] if channel == "dev" else ["canary", "production"]
        )
        if environments != expected_environments or "environment" in manifest:
            raise RuntimeError("release deployment environment contract is invalid")

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
            raw_size = row.get("size")
            if not isinstance(raw_size, int) or isinstance(raw_size, bool) or raw_size < 0:
                raise RuntimeError(f"payload size metadata is invalid: {name}")
            expected_size = raw_size
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
        "channel": str(manifest.get("release_channel") or manifest.get("channel") or ""),
        "build_id": str(manifest.get("build_id") or ""),
        "git_commit_sha": str(
            manifest.get("git_commit_sha") or manifest.get("source_revision") or ""
        ),
        "build_timestamp_utc": str(
            manifest.get("build_timestamp_utc") or manifest.get("built_at_utc") or ""
        ),
        "dirty": bool(manifest.get("dirty")),
        "trust_tier": str(manifest.get("trust_tier") or ""),
        "source_revision": str(manifest.get("source_revision") or ""),
        "file_count": len(expected),
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest().upper(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.archive)
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
