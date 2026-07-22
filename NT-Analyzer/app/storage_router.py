"""Environment router between local DPAPI/files and Production PostgreSQL."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Mapping
from urllib.parse import unquote, urlparse

from . import runtime_env
from .production_storage import (
    AuditRepository,
    DocumentRepository,
    Scope,
    StorageConfigurationError,
    StorageError,
    WorkspaceRepository,
    database_readiness,
    get_client,
)
from .production_storage.artifacts import object_storage_readiness


def production_enabled() -> bool:
    return runtime_env.is_production() and runtime_env.environment_explicit()


def _mode() -> str:
    return str(os.environ.get("STRATFORGE_STORAGE_MODE") or "").strip().lower()


def _documents() -> DocumentRepository:
    if not production_enabled():
        raise StorageConfigurationError("Production document router used in Development.")
    if _mode() != "postgresql":
        raise StorageConfigurationError("Production storage mode must be postgresql.")
    return DocumentRepository(get_client(production=True))


def read_document(repository: str, default: Mapping[str, Any]) -> Dict[str, Any]:
    return _documents().read(repository, default)


def write_document(repository: str, document: Mapping[str, Any]) -> int:
    return _documents().write(repository, document)


def read_workspace_ledger(workspace_id: str, default: Mapping[str, Any]) -> Dict[str, Any]:
    scope = Scope(workspace_id=str(workspace_id))
    return WorkspaceRepository(get_client(production=True)).get_ledger(
        scope=scope, default=default,
    )


def write_workspace_ledger(workspace_id: str, document: Mapping[str, Any]) -> int:
    scope = Scope(workspace_id=str(workspace_id))
    return WorkspaceRepository(get_client(production=True)).put_ledger(
        document, scope=scope,
    )


def append_audit(source: str, event: str, values: Mapping[str, Any]) -> str:
    workspace_id = str(values.get("workspace_id") or "")
    try:
        user_id = int(values.get("user_id") or values.get("owner_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    if workspace_id or user_id:
        scope = Scope(user_id=max(0, user_id), workspace_id=workspace_id)
    else:
        scope = Scope.global_service_scope()
    return AuditRepository(get_client(production=True)).append(
        event, dict(values), source=source, scope=scope,
    )


def storage_status() -> Dict[str, Any]:
    if not production_enabled():
        return {"available": True, "backend": "local", "authoritative": False}
    database = database_readiness()
    objects = object_storage_readiness()
    return {
        "available": bool(database.get("ok") and objects.get("ok")),
        "backend": "postgresql+file-object-store",
        "authoritative": True,
        "database_code": database.get("code"),
        "object_storage_code": objects.get("code"),
    }


def assert_production_storage_safe() -> None:
    if not production_enabled():
        return
    if _mode() != "postgresql":
        raise StorageConfigurationError(
            "STRATFORGE_STORAGE_MODE=postgresql is mandatory in Production."
        )
    database_url = str(os.environ.get("STRATFORGE_DATABASE_URL") or "").strip()
    parsed = urlparse(database_url)
    username = unquote(parsed.username or "")
    database_name = (parsed.path or "").strip("/")
    if username != "stratforge_app":
        raise StorageConfigurationError(
            "Production runtime must use the non-superuser stratforge_app database role."
        )
    if not database_name or database_name.lower() in {"postgres", "template0", "template1"}:
        raise StorageConfigurationError("Production requires a dedicated application database.")
    artifact_raw = str(os.environ.get("STRATFORGE_ARTIFACT_ROOT") or "").strip()
    if not artifact_raw:
        raise StorageConfigurationError("STRATFORGE_ARTIFACT_ROOT is required in Production.")
    artifact_root = Path(artifact_raw).expanduser().resolve()
    data_root = runtime_env.data_root().resolve()
    source_root = Path(__file__).resolve().parents[1]
    for forbidden in (data_root, source_root):
        try:
            artifact_root.relative_to(forbidden)
        except ValueError:
            continue
        raise StorageConfigurationError(
            "Production artifact root must be isolated from source and runtime data roots."
        )
    # Parse and validate the runtime DSN now, but keep temporary database or
    # storage outages as readiness failures.  The HTTP process remains alive so
    # orchestration can observe it; every authoritative request still fails
    # closed because repositories never fall back to local files.
    get_client(production=True)
