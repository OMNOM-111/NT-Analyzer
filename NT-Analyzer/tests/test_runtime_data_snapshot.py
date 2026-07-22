from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tools import runtime_data_snapshot as snapshot


def _sample_tree(root: Path) -> None:
    (root / "audit").mkdir(parents=True)
    (root / "audit" / "events.jsonl").write_text(
        '{"event":"one"}\n', encoding="utf-8"
    )
    db_path = root / "durable" / "state.sqlite3"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO items(value) VALUES ('kept')")
        db.commit()
        # Make the fixture itself quiescent before asking the snapshot tool for
        # a zero-second settle window. Windows may otherwise finish the final
        # WAL checkpoint after this helper returns.
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.execute("PRAGMA journal_mode=DELETE")


def test_backup_verify_restore_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _sample_tree(source)
    backup = tmp_path / "snapshot"

    manifest = snapshot.create_snapshot(source, backup, settle_seconds=0)
    verified = snapshot.verify_snapshot(backup)
    restored = tmp_path / "restored"
    result = snapshot.restore_snapshot(backup, restored)

    assert manifest["consistency"] == "quiesced-full-tree"
    assert manifest["data_sha256"] == verified["data_sha256"]
    assert result["data_sha256"] == manifest["data_sha256"]
    assert (restored / "audit" / "events.jsonl").read_text(encoding="utf-8") == (
        '{"event":"one"}\n'
    )
    with sqlite3.connect(restored / "durable" / "state.sqlite3") as db:
        assert db.execute("SELECT value FROM items").fetchone()[0] == "kept"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_verify_rejects_tampered_payload(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _sample_tree(source)
    backup = tmp_path / "snapshot"
    snapshot.create_snapshot(source, backup, settle_seconds=0)
    (backup / "data" / "audit" / "events.jsonl").write_text(
        "tampered\n", encoding="utf-8"
    )

    with pytest.raises(snapshot.SnapshotError, match="size mismatch|checksum mismatch"):
        snapshot.verify_snapshot(backup)


def test_verify_rejects_tampered_manifest(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _sample_tree(source)
    backup = tmp_path / "snapshot"
    snapshot.create_snapshot(source, backup, settle_seconds=0)
    manifest_path = backup / snapshot.MANIFEST_NAME
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    doc["file_count"] = 999
    manifest_path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(snapshot.SnapshotError, match="manifest checksum"):
        snapshot.verify_snapshot(backup)


def test_restore_requires_empty_isolated_target(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _sample_tree(source)
    backup = tmp_path / "snapshot"
    snapshot.create_snapshot(source, backup, settle_seconds=0)
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(snapshot.SnapshotError, match="not empty"):
        snapshot.restore_snapshot(backup, target)
    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_backup_rejects_nested_destination_and_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text("x", encoding="utf-8")
    with pytest.raises(snapshot.SnapshotError, match="contain"):
        snapshot.create_snapshot(source, source / "backup", settle_seconds=0)


def test_aggregate_checksum_is_path_sensitive() -> None:
    digest = hashlib.sha256(b"same").hexdigest()
    first = [{"path": "a", "size_bytes": 4, "sha256": digest, "kind": "file"}]
    second = [{"path": "b", "size_bytes": 4, "sha256": digest, "kind": "file"}]
    assert snapshot._data_digest(first) != snapshot._data_digest(second)
