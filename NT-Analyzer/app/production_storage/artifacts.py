"""Opaque, quota-bound file artifact store backed by PostgreSQL metadata."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .core import (
    PostgresClient,
    Scope,
    StorageConfigurationError,
    StorageConstraintError,
    StorageError,
    _jsonb,
    get_client,
)


_LOGICAL_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
DEFAULT_QUOTA_BYTES = 10 * 1024 * 1024 * 1024
DEFAULT_MAX_ARTIFACT_BYTES = 512 * 1024 * 1024


def _root(*, production: bool = False) -> Path:
    raw = str(os.environ.get("STRATFORGE_ARTIFACT_ROOT") or "").strip()
    if not raw:
        raise StorageConfigurationError("STRATFORGE_ARTIFACT_ROOT is required.")
    path = Path(raw).expanduser()
    if production and not path.is_absolute():
        raise StorageConfigurationError("Production artifact root must be absolute.")
    resolved = path.resolve()
    if resolved == resolved.anchor or resolved == Path(resolved.anchor):
        raise StorageConfigurationError("Artifact root cannot be a filesystem root.")
    return resolved


def _logical_name(value: str) -> str:
    raw = Path(str(value or "artifact.bin").replace("\\", "/")).name
    safe = _LOGICAL_NAME_RE.sub("-", raw).strip(".-") or "artifact.bin"
    return safe[:160]


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class FileArtifactStore:
    def __init__(self, client: Optional[PostgresClient] = None, *, production: bool = False) -> None:
        self.client = client or get_client(production=production)
        self.root = _root(production=production)
        self.quota_bytes = max(
            1024 * 1024,
            int(os.environ.get("STRATFORGE_DEFAULT_WORKSPACE_QUOTA_BYTES", DEFAULT_QUOTA_BYTES)),
        )
        self.max_artifact_bytes = max(
            1,
            int(os.environ.get("STRATFORGE_MAX_ARTIFACT_BYTES", DEFAULT_MAX_ARTIFACT_BYTES)),
        )

    def _path(self, object_key: str) -> Path:
        relative = Path(str(object_key or ""))
        if relative.is_absolute() or ".." in relative.parts or ":" in str(relative):
            raise StorageConstraintError("Unsafe artifact object key.")
        target = (self.root / relative).resolve()
        if not _inside(target, self.root):
            raise StorageConstraintError("Artifact object key escaped the storage root.")
        return target

    def put_bytes(
        self,
        data: bytes,
        *,
        scope: Scope,
        logical_name: str = "artifact.bin",
        media_type: str = "application/octet-stream",
        retention_days: Optional[int] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not scope.workspace_id or scope.user_id <= 0:
            raise StorageConstraintError("Artifact writes require user and workspace scope.")
        payload = bytes(data)
        if len(payload) > self.max_artifact_bytes:
            raise StorageConstraintError("Artifact exceeds the configured per-file limit.")
        artifact_id = f"art_{uuid.uuid4().hex}"
        name = _logical_name(logical_name)
        now = datetime.now(timezone.utc)
        retention_until = None
        if retention_days is not None:
            try:
                retention_until = now + timedelta(
                    days=max(1, min(3650, int(retention_days)))
                )
            except (TypeError, ValueError, OverflowError) as exc:
                raise StorageConstraintError("Artifact retention_days is invalid.") from exc
        object_key = (
            f"{scope.workspace_id}/{now:%Y/%m}/{artifact_id}/{name}"
        )
        target = self._path(object_key)
        digest = hashlib.sha256(payload).hexdigest()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target)
            with self.client.transaction(scope) as conn:
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    (scope.workspace_id,),
                )
                quota_row = conn.execute(
                    "SELECT quota_bytes FROM sf_storage_quotas WHERE workspace_id=%s",
                    (scope.workspace_id,),
                ).fetchone()
                quota = int(quota_row["quota_bytes"]) if quota_row else self.quota_bytes
                used = conn.execute(
                    """SELECT COALESCE(SUM(size_bytes),0) AS used
                       FROM sf_artifacts WHERE workspace_id=%s AND status='active'""",
                    (scope.workspace_id,),
                ).fetchone()
                if int(used["used"]) + len(payload) > quota:
                    raise StorageConstraintError("Workspace artifact quota exceeded.")
                conn.execute(
                    """
                    INSERT INTO sf_artifacts(artifact_id,workspace_id,user_id,object_key,
                      logical_name,media_type,sha256,size_bytes,retention_until,document)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        artifact_id, scope.workspace_id, scope.user_id, object_key,
                        name, str(media_type or "application/octet-stream")[:160],
                        digest, len(payload),
                        retention_until,
                        _jsonb(dict(metadata or {})),
                    ),
                )
        except Exception:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return {
            "artifact_id": artifact_id,
            "workspace_id": scope.workspace_id,
            "logical_name": name,
            "media_type": str(media_type or "application/octet-stream")[:160],
            "sha256": digest,
            "size_bytes": len(payload),
            "retention_until": retention_until.isoformat() if retention_until else "",
        }

    def read_bytes(self, artifact_id: str, *, scope: Scope) -> bytes:
        with self.client.transaction(scope, read_only=True) as conn:
            row = conn.execute(
                """SELECT object_key,sha256,size_bytes FROM sf_artifacts
                   WHERE artifact_id=%s AND status='active'""",
                (str(artifact_id),),
            ).fetchone()
        if not row:
            raise FileNotFoundError("Artifact not found in this workspace.")
        path = self._path(str(row["object_key"]))
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise StorageError("Artifact payload is unavailable.") from exc
        if len(data) != int(row["size_bytes"]) or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise StorageError("Artifact payload checksum mismatch.")
        return data

    def retention_plan(self, *, scope: Scope, now: Optional[datetime] = None) -> Dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        with self.client.transaction(scope, read_only=True) as conn:
            rows = conn.execute(
                """SELECT artifact_id,object_key,sha256,size_bytes,retention_until
                   FROM sf_artifacts WHERE status='active' AND retention_until IS NOT NULL
                     AND retention_until <= %s ORDER BY artifact_id""",
                (current,),
            ).fetchall()
        items = [dict(row) for row in rows]
        digest_rows = [
            {"artifact_id": row["artifact_id"], "sha256": row["sha256"],
             "size_bytes": int(row["size_bytes"])}
            for row in items
        ]
        return {
            "dry_run": True,
            "workspace_id": scope.workspace_id,
            "count": len(items),
            "size_bytes": sum(int(row["size_bytes"]) for row in items),
            "plan_sha256": hashlib.sha256(
                json_bytes(digest_rows)
            ).hexdigest(),
            "items": items,
        }

    def quarantine_expired(self, plan: Mapping[str, Any], *, scope: Scope,
                           confirm_sha256: str) -> Dict[str, Any]:
        if os.environ.get("STRATFORGE_RETENTION_EXECUTION_ALLOWED") != "1":
            raise StorageConstraintError("Retention execution is disabled.")
        if str(plan.get("workspace_id") or "") != scope.workspace_id:
            raise StorageConstraintError("Retention plan workspace mismatch.")
        if str(plan.get("plan_sha256") or "") != str(confirm_sha256 or ""):
            raise StorageConstraintError("Retention plan confirmation checksum mismatch.")
        items = list(plan.get("items") or [])
        digest_rows = [
            {
                "artifact_id": str(row.get("artifact_id") or ""),
                "sha256": str(row.get("sha256") or ""),
                "size_bytes": int(row.get("size_bytes") or 0),
            }
            for row in items if isinstance(row, Mapping)
        ]
        if hashlib.sha256(json_bytes(digest_rows)).hexdigest() != str(plan.get("plan_sha256") or ""):
            raise StorageConstraintError("Retention plan contents do not match its checksum.")
        quarantined: list[str] = []
        moved: list[tuple[Path, Path]] = []
        trash_root = (self.root / ".trash" / scope.workspace_id).resolve()
        if not _inside(trash_root, self.root):
            raise StorageConstraintError("Unsafe artifact trash root.")
        try:
            with self.client.transaction(scope) as conn:
                prepared = []
                for item in items:
                    if not isinstance(item, Mapping):
                        raise StorageConstraintError("Retention plan item is invalid.")
                    artifact_id = str(item.get("artifact_id") or "")
                    row = conn.execute(
                        """SELECT object_key,sha256,size_bytes,retention_until FROM sf_artifacts
                           WHERE artifact_id=%s AND status='active' FOR UPDATE""",
                        (artifact_id,),
                    ).fetchone()
                    if (
                        not row
                        or str(row["sha256"]) != str(item.get("sha256") or "")
                        or int(row["size_bytes"]) != int(item.get("size_bytes") or 0)
                        or str(row["retention_until"]) != str(item.get("retention_until"))
                    ):
                        raise StorageConstraintError("Retention artifact changed after dry-run.")
                    source = self._path(str(row["object_key"]))
                    target = (trash_root / artifact_id / source.name).resolve()
                    if not _inside(target, trash_root) or target.exists():
                        raise StorageConstraintError("Unsafe or occupied quarantine target.")
                    prepared.append((artifact_id, source, target))
                for artifact_id, source, target in prepared:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        os.replace(source, target)
                    except OSError:
                        shutil.move(str(source), str(target))
                    moved.append((source, target))
                    conn.execute(
                        """UPDATE sf_artifacts SET status='quarantined',deleted_at=clock_timestamp(),
                           updated_at=clock_timestamp() WHERE artifact_id=%s""",
                        (artifact_id,),
                    )
                    quarantined.append(artifact_id)
        except Exception as exc:
            rollback_failed = False
            for source, target in reversed(moved):
                try:
                    source.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() and not source.exists():
                        os.replace(target, source)
                except OSError:
                    rollback_failed = True
            if rollback_failed:
                raise StorageError(
                    "Artifact quarantine failed and filesystem rollback was incomplete."
                ) from exc
            raise
        return {"ok": True, "quarantined": quarantined, "recoverable": True}


def json_bytes(value: Any) -> bytes:
    import json
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def object_storage_readiness() -> Dict[str, Any]:
    try:
        root = _root(production=False)
        if not root.is_dir():
            return {"ok": False, "code": "object_storage_root_missing"}
        if not os.access(str(root), os.R_OK | os.W_OK | os.X_OK):
            return {"ok": False, "code": "object_storage_not_writable"}
        free = shutil.disk_usage(root).free
        floor = int(os.environ.get("STRATFORGE_ARTIFACT_MIN_FREE_BYTES", 1024 * 1024 * 1024))
        if free < floor:
            return {"ok": False, "code": "object_storage_space_low"}
        return {"ok": True, "code": "ok"}
    except (StorageError, OSError, ValueError):
        return {"ok": False, "code": "object_storage_unavailable"}
