"""Create, verify, and restore deterministic StratForge runtime-data snapshots.

The backup command is deliberately fail-closed.  By default it requires the
source tree to remain unchanged from the preflight scan through the final scan;
operators should quiesce application writers before running it.  SQLite files
are copied through SQLite's online-backup API so WAL content is consolidated
into one verified database file.  A restore is only allowed into an empty,
isolated target and is staged before an atomic rename.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


FORMAT_VERSION = 1
MANIFEST_NAME = "snapshot-manifest.json"
MANIFEST_HASH_NAME = "snapshot-manifest.sha256"
SQLITE_SUFFIXES = frozenset({".sqlite", ".sqlite3", ".db"})
SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


class SnapshotError(RuntimeError):
    """A safe snapshot operation could not be completed."""


@dataclass(frozen=True)
class FileState:
    size: int
    mtime_ns: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _resolved(path: Path | str) -> Path:
    return Path(path).expanduser().resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_roots(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise SnapshotError(f"Source data root does not exist: {source}")
    if source == destination:
        raise SnapshotError("Snapshot destination cannot equal the source root.")
    if _is_relative_to(destination, source) or _is_relative_to(source, destination):
        raise SnapshotError("Source and destination must not contain one another.")
    if destination.exists() and any(destination.iterdir()):
        raise SnapshotError(f"Snapshot destination is not empty: {destination}")


def _relative_files(root: Path) -> list[Path]:
    rows: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise SnapshotError(f"Symlinks are forbidden in runtime data: {path}")
        if path.is_file():
            rows.append(path.relative_to(root))
    return sorted(rows, key=lambda value: value.as_posix())


def _is_sqlite_sidecar(relative: Path, sqlite_files: set[str]) -> bool:
    text = relative.as_posix()
    for suffix in SQLITE_SIDECAR_SUFFIXES:
        if text.endswith(suffix) and text[: -len(suffix)] in sqlite_files:
            return True
    return False


def _without_sqlite_sidecars(
    state: dict[str, FileState], sqlite_files: set[str]
) -> dict[str, FileState]:
    return {
        name: value
        for name, value in state.items()
        if not _is_sqlite_sidecar(Path(name), sqlite_files)
    }


def scan_state(root: Path) -> dict[str, FileState]:
    state: dict[str, FileState] = {}
    for relative in _relative_files(root):
        stat = (root / relative).stat()
        state[relative.as_posix()] = FileState(
            size=int(stat.st_size), mtime_ns=int(stat.st_mtime_ns)
        )
    return state


def _state_digest(state: dict[str, FileState]) -> str:
    digest = hashlib.sha256()
    for name, item in sorted(state.items()):
        digest.update(f"{name}\0{item.size}\0{item.mtime_ns}\n".encode("utf-8"))
    return digest.hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_stable(source: Path, destination: Path, expected: FileState) -> None:
    before = source.stat()
    if (before.st_size, before.st_mtime_ns) != (expected.size, expected.mtime_ns):
        raise SnapshotError(f"Source changed before copy: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, destination.open("xb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())
    after = source.stat()
    if (after.st_size, after.st_mtime_ns) != (expected.size, expected.mtime_ns):
        raise SnapshotError(f"Source changed during copy: {source}")
    shutil.copystat(source, destination, follow_symlinks=False)


def _backup_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{source.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(source_uri, uri=True, timeout=30.0) as source_db:
            with sqlite3.connect(
                str(destination), timeout=30.0, isolation_level=None
            ) as target_db:
                source_db.backup(target_db, pages=1024, sleep=0.01)
                # The source may use WAL.  A portable snapshot must contain one
                # self-sufficient database file and verification must not
                # depend on transient sidecars.
                target_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                target_db.execute("PRAGMA journal_mode=DELETE")
                row = target_db.execute("PRAGMA integrity_check").fetchone()
                if not row or str(row[0]).lower() != "ok":
                    raise SnapshotError(
                        f"SQLite integrity_check failed for {source.name}: {row!r}"
                    )
    except sqlite3.Error as exc:
        raise SnapshotError(f"SQLite backup failed for {source}: {exc}") from exc


def _entry(relative: Path, path: Path, *, kind: str) -> dict[str, Any]:
    return {
        "path": relative.as_posix(),
        "size_bytes": int(path.stat().st_size),
        "sha256": _hash_file(path),
        "kind": kind,
    }


def _data_digest(entries: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in sorted(entries, key=lambda value: str(value["path"])):
        digest.update(
            (
                f"{row['path']}\0{row['size_bytes']}\0{row['sha256']}\0"
                f"{row['kind']}\n"
            ).encode("utf-8")
        )
    return digest.hexdigest()


def create_snapshot(
    source: Path | str,
    destination: Path | str,
    *,
    settle_seconds: float = 1.0,
    require_quiescent: bool = True,
) -> dict[str, Any]:
    source_root = _resolved(source)
    destination_root = _resolved(destination)
    _validate_roots(source_root, destination_root)

    preflight = scan_state(source_root)
    # Closing the final Windows SQLite connection can finish its WAL checkpoint
    # immediately after the caller returns.  A zero-second test window therefore
    # gets a few bounded 10 ms convergence probes.  The normal operator default
    # remains one strict full settle interval and still fails on any writer.
    attempts = 5 if float(settle_seconds) <= 0 else 1
    settled = preflight
    preflight_stable = not require_quiescent
    for _ in range(attempts):
        time.sleep(float(settle_seconds) if settle_seconds > 0 else 0.01)
        settled = scan_state(source_root)
        preflight_sqlite = {
            name
            for name in set(preflight) | set(settled)
            if Path(name).suffix.lower() in SQLITE_SUFFIXES
        }
        if _without_sqlite_sidecars(
            settled, preflight_sqlite
        ) == _without_sqlite_sidecars(preflight, preflight_sqlite):
            preflight_stable = True
            break
        preflight = settled
    if require_quiescent and not preflight_stable:
        raise SnapshotError("Source data changed during the quiescence preflight.")

    destination_root.mkdir(parents=True, exist_ok=True)
    payload_root = destination_root / "data"
    payload_root.mkdir(parents=True, exist_ok=False)
    sqlite_files = {
        name for name in settled if Path(name).suffix.lower() in SQLITE_SUFFIXES
    }
    entries: list[dict[str, Any]] = []
    try:
        for name, state in sorted(settled.items()):
            relative = Path(name)
            if _is_sqlite_sidecar(relative, sqlite_files):
                continue
            source_path = source_root / relative
            target_path = payload_root / relative
            if name in sqlite_files:
                _backup_sqlite(source_path, target_path)
                kind = "sqlite-online-backup"
            else:
                _copy_stable(source_path, target_path, state)
                kind = "file"
            entries.append(_entry(relative, target_path, kind=kind))

        final_state = scan_state(source_root)
        # Reading a WAL database through SQLite's backup API may legitimately
        # touch its shared-memory sidecar.  Those sidecars are never payload:
        # the consolidated database is integrity-checked above.  Every durable
        # file, including the main SQLite file, remains under strict full-tree
        # change detection.
        if require_quiescent and _without_sqlite_sidecars(
            final_state, sqlite_files
        ) != _without_sqlite_sidecars(settled, sqlite_files):
            raise SnapshotError("Source data changed while the snapshot was copied.")

        manifest: dict[str, Any] = {
            "format": "stratforge-runtime-data-snapshot",
            "format_version": FORMAT_VERSION,
            "snapshot_id": str(uuid.uuid4()),
            "created_at_utc": _utc_now(),
            "source_root": str(source_root),
            "consistency": (
                "quiesced-full-tree" if require_quiescent else "per-file-stable"
            ),
            "source_state_sha256": _state_digest(final_state),
            "data_sha256": _data_digest(entries),
            "file_count": len(entries),
            "size_bytes": sum(int(row["size_bytes"]) for row in entries),
            "sqlite_count": sum(
                1 for row in entries if row["kind"] == "sqlite-online-backup"
            ),
            "entries": entries,
        }
        manifest_path = destination_root / MANIFEST_NAME
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (destination_root / MANIFEST_HASH_NAME).write_text(
            f"{_hash_file(manifest_path)}  {MANIFEST_NAME}\n", encoding="ascii"
        )
        verify_snapshot(destination_root)
        return manifest
    except Exception:
        shutil.rmtree(destination_root, ignore_errors=True)
        raise


def _load_manifest(snapshot_root: Path) -> dict[str, Any]:
    manifest_path = snapshot_root / MANIFEST_NAME
    hash_path = snapshot_root / MANIFEST_HASH_NAME
    if not manifest_path.is_file() or not hash_path.is_file():
        raise SnapshotError("Snapshot manifest or manifest hash is missing.")
    expected = hash_path.read_text(encoding="ascii").split()[0].lower()
    actual = _hash_file(manifest_path)
    if expected != actual:
        raise SnapshotError("Snapshot manifest checksum mismatch.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SnapshotError(f"Snapshot manifest is invalid: {exc}") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != "stratforge-runtime-data-snapshot"
        or manifest.get("format_version") != FORMAT_VERSION
        or not isinstance(manifest.get("entries"), list)
    ):
        raise SnapshotError("Unsupported snapshot manifest format.")
    return manifest


def verify_snapshot(snapshot: Path | str) -> dict[str, Any]:
    root = _resolved(snapshot)
    manifest = _load_manifest(root)
    payload_root = root / "data"
    expected_names: set[str] = set()
    verified: list[dict[str, Any]] = []
    for raw in manifest["entries"]:
        if not isinstance(raw, dict):
            raise SnapshotError("Invalid snapshot entry.")
        name = str(raw.get("path") or "")
        relative = Path(name)
        if (
            not name
            or relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != name
        ):
            raise SnapshotError(f"Unsafe snapshot entry path: {name!r}")
        if name in expected_names:
            raise SnapshotError(f"Duplicate snapshot entry: {name}")
        expected_names.add(name)
        path = payload_root / relative
        if path.is_symlink() or not path.is_file():
            raise SnapshotError(f"Snapshot file is missing or unsafe: {name}")
        if int(path.stat().st_size) != int(raw.get("size_bytes", -1)):
            raise SnapshotError(f"Snapshot file size mismatch: {name}")
        digest = _hash_file(path)
        if digest != str(raw.get("sha256") or "").lower():
            raise SnapshotError(f"Snapshot file checksum mismatch: {name}")
        kind = str(raw.get("kind") or "")
        if kind == "sqlite-online-backup":
            try:
                with sqlite3.connect(
                    f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True
                ) as db:
                    row = db.execute("PRAGMA integrity_check").fetchone()
            except sqlite3.Error as exc:
                raise SnapshotError(f"Restored SQLite check failed: {name}: {exc}") from exc
            if not row or str(row[0]).lower() != "ok":
                raise SnapshotError(f"Restored SQLite is corrupt: {name}")
        verified.append(
            {
                "path": name,
                "size_bytes": int(raw["size_bytes"]),
                "sha256": digest,
                "kind": kind,
            }
        )

    actual_names = {path.as_posix() for path in _relative_files(payload_root)}
    if actual_names != expected_names:
        extra = sorted(actual_names - expected_names)
        missing = sorted(expected_names - actual_names)
        raise SnapshotError(f"Snapshot file set mismatch; extra={extra}, missing={missing}")
    if _data_digest(verified) != str(manifest.get("data_sha256") or "").lower():
        raise SnapshotError("Snapshot aggregate data checksum mismatch.")
    if len(verified) != int(manifest.get("file_count", -1)):
        raise SnapshotError("Snapshot file count mismatch.")
    if sum(row["size_bytes"] for row in verified) != int(
        manifest.get("size_bytes", -1)
    ):
        raise SnapshotError("Snapshot byte count mismatch.")
    return manifest


def restore_snapshot(snapshot: Path | str, target: Path | str) -> dict[str, Any]:
    snapshot_root = _resolved(snapshot)
    target_root = _resolved(target)
    if target_root == snapshot_root or _is_relative_to(target_root, snapshot_root):
        raise SnapshotError("Restore target must be isolated from the snapshot.")
    if target_root.exists() and any(target_root.iterdir()):
        raise SnapshotError(f"Restore target is not empty: {target_root}")
    manifest = verify_snapshot(snapshot_root)
    target_root.parent.mkdir(parents=True, exist_ok=True)
    if target_root.exists():
        target_root.rmdir()
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target_root.name}.restore-", dir=target_root.parent)
    )
    try:
        for row in manifest["entries"]:
            relative = Path(str(row["path"]))
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(snapshot_root / "data" / relative, destination)
        restored_state = scan_state(staging)
        if len(restored_state) != int(manifest["file_count"]):
            raise SnapshotError("Restored file count differs from the manifest.")
        for row in manifest["entries"]:
            path = staging / Path(str(row["path"]))
            if _hash_file(path) != str(row["sha256"]):
                raise SnapshotError(f"Restored file checksum mismatch: {row['path']}")
        os.replace(staging, target_root)
        return {
            "snapshot_id": manifest["snapshot_id"],
            "target": str(target_root),
            "file_count": manifest["file_count"],
            "size_bytes": manifest["size_bytes"],
            "data_sha256": manifest["data_sha256"],
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup", help="Create a verified snapshot")
    backup.add_argument("--source", required=True, type=Path)
    backup.add_argument("--destination", required=True, type=Path)
    backup.add_argument("--settle-seconds", type=float, default=1.0)
    backup.add_argument(
        "--allow-live",
        action="store_true",
        help="Allow tree-level changes; only per-file stability is guaranteed",
    )
    verify = sub.add_parser("verify", help="Verify an existing snapshot")
    verify.add_argument("--snapshot", required=True, type=Path)
    restore = sub.add_parser("restore", help="Restore into an empty target")
    restore.add_argument("--snapshot", required=True, type=Path)
    restore.add_argument("--target", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "backup":
            result = create_snapshot(
                args.source,
                args.destination,
                settle_seconds=max(0.0, args.settle_seconds),
                require_quiescent=not args.allow_live,
            )
        elif args.command == "verify":
            result = verify_snapshot(args.snapshot)
        else:
            result = restore_snapshot(args.snapshot, args.target)
    except SnapshotError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    # Keep machine-readable console evidence compact.  Per-file checksums stay
    # in the signed-by-hash manifest and are intentionally not echoed into
    # terminal logs where they obscure the operational result.
    summary_keys = (
        "snapshot_id", "created_at_utc", "consistency", "file_count",
        "size_bytes", "sqlite_count", "data_sha256", "source_state_sha256",
        "target",
    )
    summary = {key: result[key] for key in summary_keys if key in result}
    print(json.dumps({"ok": True, **summary}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
