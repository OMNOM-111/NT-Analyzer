from __future__ import annotations

from pathlib import Path
import hashlib

import pytest

from app.production_storage import backup as backup_mod
from app.production_storage.backup import (
    BackupError,
    _assert_verification_database,
    _subprocess_connection,
    _write_manifest,
    create_backup,
    restore_backup,
    verify_backup,
)
from app.production_storage.core import (
    StorageConfigurationError,
    StorageConstraintError,
    _canonical,
)


def test_subprocess_connection_removes_password_from_process_arguments() -> None:
    connection, environment = _subprocess_connection(
        "postgresql://user:p%40ss@db.example:5432/stratforge?sslmode=verify-full"
    )
    assert "p@ss" not in connection
    assert "p%40ss" not in connection
    assert environment["PGPASSWORD"] == "p@ss"
    assert "sslmode=verify-full" in connection


def test_combined_backup_requires_explicit_quiesced_window(tmp_path: Path) -> None:
    with pytest.raises(StorageConstraintError, match="quiesced"):
        create_backup(
            database_url="postgresql://app@127.0.0.1/test",
            artifact_root=tmp_path / "objects",
            output_dir=tmp_path / "backup",
            pg_bin=tmp_path / "bin",
            quiesced=False,
        )


def _fixture_backup(tmp_path: Path):
    root = tmp_path / "backup"
    objects = root / "objects"
    pg_bin = tmp_path / "bin"
    objects.mkdir(parents=True)
    pg_bin.mkdir()
    (pg_bin / "pg_restore.exe").write_bytes(b"test tool")
    dump = root / "database.dump"
    dump.write_bytes(b"verified pg dump")
    payload = b"verified artifact"
    artifact = objects / "ws_owner_TEST0001" / "artifact.bin"
    artifact.parent.mkdir()
    artifact.write_bytes(payload)
    files = [{
        "path": "ws_owner_TEST0001/artifact.bin",
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }]
    manifest = {
        "format_version": 1,
        "backup_id": "sfbackup_test",
        "database": {"table_counts": {}, "migrations": []},
        "dump": {
            "file": "database.dump",
            "size_bytes": dump.stat().st_size,
            "sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
        },
        "objects": {
            "file_count": 1,
            "size_bytes": len(payload),
            "aggregate_sha256": hashlib.sha256(_canonical(files)).hexdigest(),
            "files": files,
        },
    }
    _write_manifest(root, manifest)
    return root, pg_bin, artifact


def test_backup_verification_detects_payload_tampering(tmp_path: Path, monkeypatch) -> None:
    root, pg_bin, artifact = _fixture_backup(tmp_path)
    monkeypatch.setattr(backup_mod, "_run", lambda *args, **kwargs: "")
    assert verify_backup(backup_dir=root, pg_bin=pg_bin)["ok"] is True
    artifact.write_bytes(b"tampered")
    with pytest.raises(BackupError, match="checksum"):
        verify_backup(backup_dir=root, pg_bin=pg_bin)


def test_backup_verification_detects_manifest_tampering(tmp_path: Path, monkeypatch) -> None:
    root, pg_bin, _ = _fixture_backup(tmp_path)
    monkeypatch.setattr(backup_mod, "_run", lambda *args, **kwargs: "")
    manifest = root / "manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b" ")
    with pytest.raises(BackupError, match="manifest checksum"):
        verify_backup(backup_dir=root, pg_bin=pg_bin)


def test_restore_verification_identity_must_target_exact_database() -> None:
    target = "postgresql://restore@db.internal:5432/restore_drill?sslmode=verify-full"
    verifier = "postgresql://backup@db.internal:5432/restore_drill?sslmode=verify-full"
    _assert_verification_database(
        target, verifier, confirmed_name="restore_drill",
    )
    with pytest.raises(StorageConstraintError, match="same PostgreSQL database"):
        _assert_verification_database(
            target,
            "postgresql://backup@other.internal:5432/restore_drill?sslmode=verify-full",
            confirmed_name="restore_drill",
        )
    with pytest.raises(StorageConstraintError, match="confirmation"):
        _assert_verification_database(
            target,
            "postgresql://backup@db.internal:5432/other_drill?sslmode=verify-full",
            confirmed_name="restore_drill",
        )


def test_restore_uses_separate_read_only_verification_identity(
    tmp_path: Path, monkeypatch,
) -> None:
    root, pg_bin, _ = _fixture_backup(tmp_path)
    target_url = "postgresql://restore@db.internal:5432/restore_drill?sslmode=verify-full"
    verifier_url = "postgresql://backup@db.internal:5432/restore_drill?sslmode=verify-full"
    observed: list[str] = []
    commands: list[list[str]] = []
    monkeypatch.setattr(
        backup_mod, "_run",
        lambda command, **kwargs: commands.append(command) or "",
    )
    monkeypatch.setattr(backup_mod, "_assert_empty_database", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        backup_mod,
        "_database_manifest",
        lambda url: observed.append(url) or {"table_counts": {}, "migrations": []},
    )

    result = restore_backup(
        backup_dir=root,
        target_database_url=target_url,
        verification_database_url=verifier_url,
        target_artifact_root=tmp_path / "restored-objects",
        confirm_dump_sha256=hashlib.sha256(b"verified pg dump").hexdigest(),
        confirm_target_database="restore_drill",
        pg_bin=pg_bin,
        restore_execution_role="stratforge_migration",
    )

    assert result["ok"] is True
    assert result["restore_execution_role"] == "stratforge_migration"
    assert observed == [verifier_url]
    assert "--role=stratforge_migration" in commands[-1]
    assert (tmp_path / "restored-objects/ws_owner_TEST0001/artifact.bin").read_bytes() == b"verified artifact"


def test_restore_rejects_unsafe_execution_role_before_io(tmp_path: Path) -> None:
    with pytest.raises(StorageConfigurationError, match="execution role"):
        restore_backup(
            backup_dir=tmp_path / "missing-backup",
            target_database_url="postgresql://restore@db.internal/restore_drill",
            verification_database_url="postgresql://backup@db.internal/restore_drill",
            target_artifact_root=tmp_path / "objects",
            confirm_dump_sha256="0" * 64,
            confirm_target_database="restore_drill",
            pg_bin=tmp_path / "bin",
            restore_execution_role="stratforge_migration --no-acl",
        )
