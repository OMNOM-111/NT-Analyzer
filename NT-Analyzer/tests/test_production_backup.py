from __future__ import annotations

from pathlib import Path
import hashlib

import pytest

from app.production_storage import backup as backup_mod
from app.production_storage.backup import (
    BackupError,
    _subprocess_connection,
    _write_manifest,
    create_backup,
    verify_backup,
)
from app.production_storage.core import StorageConstraintError, _canonical


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
        "database": {"table_counts": {}},
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
