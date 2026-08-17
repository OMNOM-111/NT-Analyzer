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
    EnvironmentRegistryRepository,
    Scope,
    StorageConfigurationError,
    StorageError,
    WorkspaceRepository,
    database_readiness,
    get_client,
)
from .production_storage.artifacts import object_storage_readiness


def production_enabled() -> bool:
    """True when storage routing must be authoritative against PostgreSQL.

    Applies to Production *and* Canary: both declare a real, isolated
    PostgreSQL identity and must never silently fall back to local
    files/DPAPI just because they are not literally Production.
    """
    return runtime_env.is_server_environment() and runtime_env.environment_explicit()


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


def document_repository_readiness(repository: str) -> Dict[str, Any]:
    """Secret-free ping used by HTTP readiness; never loads the JSON document."""
    try:
        return _documents().ping(repository)
    except StorageError:
        return {"ok": False, "code": "repository_unavailable"}


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


def applied_schema_version() -> int:
    """Highest applied migration version.

    ``database_readiness`` deliberately reports only ok/not-ok, so it cannot
    answer this; the environment registry needs the number itself to compare
    schema state across environments.
    """
    client = get_client(production=True)
    with client.transaction(Scope.global_service_scope(), read_only=True) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(version),0) AS version FROM sf_schema_migrations"
        ).fetchone()
    return int(row["version"]) if row else 0


def record_environment_heartbeat(heartbeat: Mapping[str, Any]) -> Dict[str, Any]:
    return EnvironmentRegistryRepository(get_client(production=True)).record(
        heartbeat, scope=Scope.global_service_scope(),
    )


def read_environment_registry() -> list:
    return EnvironmentRegistryRepository(get_client(production=True)).all(
        scope=Scope.global_service_scope(),
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


def _expected_app_db_role() -> str:
    """Return the non-superuser app role this environment's runtime must use.

    Production and Canary each own a distinct, dedicated role
    (``stratforge_app`` / ``stratforge_canary_app``) so neither environment's
    runtime DSN can be mistaken for, or collide with, the other's. An explicit
    override is honoured for operator-controlled renames, but the safe
    per-environment default requires no configuration.
    """
    configured = str(os.environ.get("STRATFORGE_DATABASE_APP_ROLE") or "").strip()
    if configured:
        return configured
    return "stratforge_canary_app" if runtime_env.is_canary() else "stratforge_app"


def assert_production_storage_safe() -> None:
    """Fail-closed storage safety gate, shared by Production and Canary.

    The name is retained for compatibility with existing callers/tests; the
    checks it enforces (postgresql mode, dedicated non-superuser role,
    dedicated database, isolated artifact root) apply to both server
    environments via :func:`production_enabled`.
    """
    if not production_enabled():
        return
    if _mode() != "postgresql":
        raise StorageConfigurationError(
            "STRATFORGE_STORAGE_MODE=postgresql is mandatory in Production/Canary."
        )
    database_url = str(os.environ.get("STRATFORGE_DATABASE_URL") or "").strip()
    parsed = urlparse(database_url)
    username = unquote(parsed.username or "")
    database_name = (parsed.path or "").strip("/")
    expected_role = _expected_app_db_role()
    if username != expected_role:
        raise StorageConfigurationError(
            f"Runtime must use the non-superuser {expected_role} database role."
        )
    if not database_name or database_name.lower() in {"postgres", "template0", "template1"}:
        raise StorageConfigurationError("Production/Canary requires a dedicated application database.")
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


def signing_key_readiness() -> Dict[str, Any]:
    """Check whether the Production signing key is configured.

    The actual key value is never included in the readiness payload.
    """
    key = str(os.environ.get("STRATFORGE_SIGNING_KEY") or "").strip()
    if len(key) >= 32:
        return {"ok": True, "code": "ok"}
    return {"ok": False, "code": "signing_key_missing_or_short"}
