"""Verified PostgreSQL plus artifact-store backup and isolated restore."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse

from .core import StorageConfigurationError, StorageConstraintError, StorageError, _canonical


BACKUP_FORMAT_VERSION = 1
_RESTORE_ROLE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class BackupError(StorageError):
    code = "backup_error"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_root(path: Path, *, label: str, must_exist: bool) -> Path:
    value = Path(path).expanduser()
    if not value.is_absolute():
        raise StorageConfigurationError(f"{label} must be an absolute path.")
    resolved = value.resolve()
    if resolved == Path(resolved.anchor):
        raise StorageConfigurationError(f"{label} cannot be a filesystem root.")
    if must_exist and (not resolved.is_dir() or resolved.is_symlink()):
        raise StorageConfigurationError(f"{label} must be an existing non-symlink directory.")
    return resolved


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _database_identity(url: str) -> Dict[str, Any]:
    parsed = urlparse(str(url or ""))
    name = (parsed.path or "").strip("/")
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not name:
        raise StorageConfigurationError("Backup database URL must identify a PostgreSQL database.")
    if name.lower() in {"postgres", "template0", "template1"}:
        raise StorageConfigurationError("Backup/restore requires a dedicated application database.")
    return {
        "host": parsed.hostname,
        "port": int(parsed.port or 5432),
        "database": name,
        "sslmode": str(dict(
            pair.split("=", 1) if "=" in pair else (pair, "")
            for pair in (parsed.query or "").split("&") if pair
        ).get("sslmode") or ""),
    }


def _subprocess_connection(url: str) -> tuple[str, Dict[str, str]]:
    try:
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        values = conninfo_to_dict(str(url or ""))
    except Exception as exc:
        raise StorageConfigurationError("PostgreSQL connection settings are invalid.") from exc
    password = str(values.pop("password", "") or "")
    environment = dict(os.environ)
    if password:
        environment["PGPASSWORD"] = password
    return make_conninfo(**values), environment


def _tool(pg_bin: Path, name: str) -> Path:
    root = _safe_root(Path(pg_bin), label="PostgreSQL binary directory", must_exist=True)
    candidates = [root / name, root / f"{name}.exe"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise StorageConfigurationError(f"Required PostgreSQL tool is missing: {name}.")


def _run(command: list[str], *, environment: Optional[Mapping[str, str]] = None) -> str:
    try:
        result = subprocess.run(
            command,
            env=dict(environment or os.environ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60 * 60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BackupError("PostgreSQL backup tool could not be executed.") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        safe_detail = detail[-1][:300] if detail else "unknown error"
        raise BackupError(f"PostgreSQL backup tool failed: {safe_detail}")
    return result.stdout.strip()


def _database_manifest(url: str) -> Dict[str, Any]:
    try:
        import psycopg
        from psycopg import sql
        with psycopg.connect(url, autocommit=True, row_factory=psycopg.rows.dict_row) as conn:
            tables = [
                str(row["tablename"])
                for row in conn.execute(
                    """SELECT tablename FROM pg_tables
                       WHERE schemaname='public' AND tablename LIKE 'sf\\_%' ESCAPE '\\'
                       ORDER BY tablename"""
                ).fetchall()
            ]
            counts: Dict[str, int] = {}
            for table in tables:
                row = conn.execute(
                    sql.SQL("SELECT count(*) AS count FROM {}").format(sql.Identifier(table))
                ).fetchone()
                counts[table] = int(row["count"])
            migrations = [dict(row) for row in conn.execute(
                """SELECT version,name,checksum,applied_at
                   FROM sf_schema_migrations ORDER BY version"""
            ).fetchall()] if "sf_schema_migrations" in tables else []
            for row in migrations:
                row["applied_at"] = row["applied_at"].isoformat() if row.get("applied_at") else ""
            server = conn.execute(
                "SELECT current_database() AS database, current_setting('server_version_num') AS version"
            ).fetchone()
    except Exception as exc:
        raise BackupError("PostgreSQL backup preflight failed.") from exc
    return {
        "database": str(server["database"]),
        "server_version_num": str(server["version"]),
        "migrations": migrations,
        "table_counts": counts,
    }


def _scan_source(root: Path) -> Dict[str, tuple[int, int]]:
    rows: Dict[str, tuple[int, int]] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise BackupError("Artifact storage contains a symlink; backup stopped.")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        stat = path.stat()
        rows[relative] = (int(stat.st_size), int(stat.st_mtime_ns))
    return rows


def _copy_artifacts(source: Path, target: Path) -> Dict[str, Any]:
    before = _scan_source(source)
    target.mkdir(parents=True, exist_ok=False)
    files = []
    for relative, (size, _) in before.items():
        src = source / Path(relative)
        dst = target / Path(relative)
        if not _inside(dst, target):
            raise BackupError("Artifact relative path escaped the backup target.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        source_sha = _sha256_file(src)
        target_sha = _sha256_file(dst)
        if source_sha != target_sha or dst.stat().st_size != size:
            raise BackupError("Artifact changed or was corrupted during backup.")
        files.append({"path": relative, "size_bytes": size, "sha256": source_sha})
    if _scan_source(source) != before:
        raise BackupError("Artifact storage changed during the quiesced backup window.")
    return {
        "file_count": len(files),
        "size_bytes": sum(row["size_bytes"] for row in files),
        "aggregate_sha256": hashlib.sha256(_canonical(files)).hexdigest(),
        "files": files,
    }


def _write_manifest(root: Path, manifest: Mapping[str, Any]) -> None:
    payload = json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True, default=str,
    ).encode("utf-8") + b"\n"
    manifest_path = root / "manifest.json"
    with manifest_path.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    digest = hashlib.sha256(payload).hexdigest()
    with (root / "manifest.sha256").open("w", encoding="ascii", newline="\n") as stream:
        stream.write(f"{digest}  manifest.json\n")
        stream.flush()
        os.fsync(stream.fileno())


def create_backup(
    *,
    database_url: str,
    artifact_root: Path,
    output_dir: Path,
    pg_bin: Path,
    quiesced: bool,
) -> Dict[str, Any]:
    if not quiesced:
        raise StorageConstraintError(
            "A combined backup requires an explicitly quiesced write window."
        )
    database_identity = _database_identity(database_url)
    source = _safe_root(Path(artifact_root), label="Artifact root", must_exist=True)
    output = _safe_root(Path(output_dir), label="Backup output", must_exist=False)
    if output.exists():
        raise StorageConstraintError("Backup output must not already exist.")
    if _inside(output, source) or _inside(source, output):
        raise StorageConstraintError("Backup output and artifact root must be isolated.")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.partial-{uuid.uuid4().hex}"
    if temporary.exists():
        raise BackupError("Temporary backup target unexpectedly exists.")
    pg_dump = _tool(pg_bin, "pg_dump")
    pg_restore = _tool(pg_bin, "pg_restore")
    connection, environment = _subprocess_connection(database_url)
    temporary.mkdir()
    try:
        dump_path = temporary / "database.dump"
        _run([
            str(pg_dump), "--format=custom", "--compress=6", "--no-owner",
            f"--file={dump_path}", f"--dbname={connection}",
        ], environment=environment)
        with dump_path.open("r+b") as stream:
            os.fsync(stream.fileno())
        _run([str(pg_restore), "--list", str(dump_path)], environment=environment)
        database = _database_manifest(database_url)
        objects = _copy_artifacts(source, temporary / "objects")
        dump_sha = _sha256_file(dump_path)
        version = _run([str(pg_dump), "--version"], environment=environment)
        manifest = {
            "format_version": BACKUP_FORMAT_VERSION,
            "backup_id": f"sfbackup_{uuid.uuid4().hex}",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "consistency": "operator-confirmed-quiesced",
            "database_identity": database_identity,
            "database": database,
            "dump": {
                "file": "database.dump",
                "size_bytes": dump_path.stat().st_size,
                "sha256": dump_sha,
                "pg_dump_version": version,
            },
            "objects": objects,
        }
        _write_manifest(temporary, manifest)
        temporary.rename(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        "ok": True,
        "backup_id": manifest["backup_id"],
        "backup_dir": str(output),
        "dump_sha256": manifest["dump"]["sha256"],
        "dump_size_bytes": manifest["dump"]["size_bytes"],
        "object_file_count": manifest["objects"]["file_count"],
        "object_size_bytes": manifest["objects"]["size_bytes"],
        "object_aggregate_sha256": manifest["objects"]["aggregate_sha256"],
        "table_counts": manifest["database"]["table_counts"],
    }


def _load_manifest(root: Path) -> Dict[str, Any]:
    manifest_path = root / "manifest.json"
    checksum_path = root / "manifest.sha256"
    try:
        payload = manifest_path.read_bytes()
        expected = checksum_path.read_text(encoding="ascii").strip().split()[0]
    except (OSError, IndexError) as exc:
        raise BackupError("Backup manifest or its checksum is missing.") from exc
    if hashlib.sha256(payload).hexdigest() != expected:
        raise BackupError("Backup manifest checksum mismatch.")
    try:
        manifest = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError("Backup manifest is invalid.") from exc
    if int(manifest.get("format_version") or 0) != BACKUP_FORMAT_VERSION:
        raise BackupError("Unsupported backup format version.")
    return manifest


def verify_backup(*, backup_dir: Path, pg_bin: Path) -> Dict[str, Any]:
    root = _safe_root(Path(backup_dir), label="Backup directory", must_exist=True)
    manifest = _load_manifest(root)
    dump = root / str(manifest.get("dump", {}).get("file") or "")
    if not dump.is_file():
        raise BackupError("PostgreSQL dump is missing.")
    if dump.stat().st_size != int(manifest["dump"]["size_bytes"]):
        raise BackupError("PostgreSQL dump size mismatch.")
    if _sha256_file(dump) != str(manifest["dump"]["sha256"]):
        raise BackupError("PostgreSQL dump checksum mismatch.")
    pg_restore = _tool(pg_bin, "pg_restore")
    _run([str(pg_restore), "--list", str(dump)])
    object_root = root / "objects"
    declared = list(manifest.get("objects", {}).get("files") or [])
    if len(declared) != int(manifest.get("objects", {}).get("file_count") or 0):
        raise BackupError("Artifact backup declared file count mismatch.")
    if sum(int(row.get("size_bytes") or 0) for row in declared) != int(
        manifest.get("objects", {}).get("size_bytes") or 0
    ):
        raise BackupError("Artifact backup declared size mismatch.")
    actual_paths = set(_scan_source(object_root)) if object_root.is_dir() else set()
    declared_paths = {str(row.get("path") or "") for row in declared}
    if actual_paths != declared_paths:
        raise BackupError("Artifact backup file set mismatch.")
    for row in declared:
        path = object_root / Path(str(row["path"]))
        if not _inside(path, object_root):
            raise BackupError("Artifact backup path escaped its root.")
        if path.stat().st_size != int(row["size_bytes"]) or _sha256_file(path) != row["sha256"]:
            raise BackupError("Artifact backup checksum mismatch.")
    if hashlib.sha256(_canonical(declared)).hexdigest() != manifest["objects"]["aggregate_sha256"]:
        raise BackupError("Artifact aggregate checksum mismatch.")
    return {
        "ok": True,
        "backup_id": str(manifest["backup_id"]),
        "dump_sha256": str(manifest["dump"]["sha256"]),
        "dump_size_bytes": int(manifest["dump"]["size_bytes"]),
        "object_file_count": int(manifest["objects"]["file_count"]),
        "object_size_bytes": int(manifest["objects"]["size_bytes"]),
        "object_aggregate_sha256": str(manifest["objects"]["aggregate_sha256"]),
        "table_counts": dict(manifest["database"]["table_counts"]),
    }


def _assert_empty_database(url: str, *, confirmed_name: str) -> None:
    identity = _database_identity(url)
    if identity["database"] != str(confirmed_name or ""):
        raise StorageConstraintError("Restore target database confirmation does not match.")
    try:
        import psycopg
        with psycopg.connect(url, autocommit=True) as conn:
            rows = conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
            ).fetchall()
    except Exception as exc:
        raise BackupError("Restore target database preflight failed.") from exc
    if rows:
        raise StorageConstraintError("Restore target database must contain no public tables.")


def _assert_verification_database(
    target_database_url: str,
    verification_database_url: str,
    *,
    confirmed_name: str,
) -> None:
    """Require the read-only verifier to inspect the exact restore target.

    Production restore identities intentionally do not bypass forced RLS.  A
    separate backup/read-only identity may therefore verify post-restore table
    counts, but it must not be possible to point that identity at a different
    database or server and obtain a false green result.
    """
    target = _database_identity(target_database_url)
    verifier = _database_identity(verification_database_url)
    expected = str(confirmed_name or "")
    if target["database"] != expected or verifier["database"] != expected:
        raise StorageConstraintError(
            "Restore verification database confirmation does not match."
        )
    if any(target[key] != verifier[key] for key in ("host", "port", "database")):
        raise StorageConstraintError(
            "Restore verification identity must target the same PostgreSQL database."
        )


def _restore_artifacts(source: Path, target: Path, manifest: Mapping[str, Any]) -> None:
    if target.exists():
        raise StorageConstraintError("Restore artifact target must not already exist.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.partial-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        for row in manifest.get("files", []):
            relative = Path(str(row["path"]))
            src = source / relative
            dst = temporary / relative
            if not _inside(src, source) or not _inside(dst, temporary):
                raise BackupError("Unsafe artifact restore path.")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            if dst.stat().st_size != int(row["size_bytes"]) or _sha256_file(dst) != row["sha256"]:
                raise BackupError("Artifact restore checksum mismatch.")
        temporary.rename(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def restore_backup(
    *,
    backup_dir: Path,
    target_database_url: str,
    target_artifact_root: Path,
    confirm_dump_sha256: str,
    confirm_target_database: str,
    pg_bin: Path,
    verification_database_url: str | None = None,
    restore_execution_role: str = "",
) -> Dict[str, Any]:
    execution_role = str(restore_execution_role or "").strip()
    if execution_role and not _RESTORE_ROLE.fullmatch(execution_role):
        raise StorageConfigurationError("Restore execution role is invalid.")
    verified = verify_backup(backup_dir=backup_dir, pg_bin=pg_bin)
    if str(confirm_dump_sha256 or "") != verified["dump_sha256"]:
        raise StorageConstraintError("Restore dump checksum confirmation mismatch.")
    _assert_empty_database(target_database_url, confirmed_name=confirm_target_database)
    verifier_url = str(verification_database_url or target_database_url)
    _assert_verification_database(
        target_database_url,
        verifier_url,
        confirmed_name=confirm_target_database,
    )
    root = _safe_root(Path(backup_dir), label="Backup directory", must_exist=True)
    target = _safe_root(Path(target_artifact_root), label="Restore artifact target", must_exist=False)
    if target.exists():
        raise StorageConstraintError("Restore artifact target must not already exist.")
    if _inside(target, root) or _inside(root, target):
        raise StorageConstraintError("Restore artifact target and backup must be isolated.")
    manifest = _load_manifest(root)
    pg_restore = _tool(pg_bin, "pg_restore")
    connection, environment = _subprocess_connection(target_database_url)
    restore_command = [
        str(pg_restore), "--exit-on-error", "--no-owner",
    ]
    if execution_role:
        # The login restore identity has SET=TRUE but INHERIT=FALSE membership.
        # Explicit SET ROLE keeps ordinary Production access unavailable while
        # allowing owner/default-ACL statements to replay in the isolated DB.
        restore_command.append(f"--role={execution_role}")
    restore_command.extend([
        f"--dbname={connection}", str(root / manifest["dump"]["file"]),
    ])
    _run(restore_command, environment=environment)
    restored_database = _database_manifest(verifier_url)
    if restored_database["table_counts"] != manifest["database"]["table_counts"]:
        raise BackupError("Restored PostgreSQL table counts differ from the backup manifest.")
    if restored_database["migrations"] != manifest["database"]["migrations"]:
        raise BackupError("Restored PostgreSQL migration ledger differs from the backup manifest.")
    _restore_artifacts(root / "objects", target, manifest["objects"])
    restored_scan = _scan_source(target)
    if len(restored_scan) != int(manifest["objects"]["file_count"]):
        raise BackupError("Restored artifact file count differs from the backup manifest.")
    return {
        "ok": True,
        "backup_id": str(manifest["backup_id"]),
        "target_database": str(confirm_target_database),
        "restore_execution_role": execution_role,
        "dump_sha256": verified["dump_sha256"],
        "table_counts": restored_database["table_counts"],
        "object_file_count": len(restored_scan),
        "object_aggregate_sha256": str(manifest["objects"]["aggregate_sha256"]),
    }
