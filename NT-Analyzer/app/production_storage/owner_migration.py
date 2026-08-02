"""Explicit, checksum-confirmed migration of selected owner data.

This module intentionally does not support a blanket "copy local data" mode.
Only the owner identity, named workspaces, named data categories and named
Connector installations selected by the operator can enter a plan.  Ephemeral
credentials and client filesystem paths are stripped before the plan is
hashed, reviewed and applied atomically.
"""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Sequence

from .core import (
    DocumentRepository,
    PostgresClient,
    Scope,
    StorageConflictError,
    StorageConstraintError,
    _canonical,
    _int,
    _jsonb,
)


PLAN_SCHEMA_VERSION = 1
ALLOWED_CATEGORIES = frozenset({
    "auth", "workspaces", "entitlements", "connectors", "ledgers",
})
_REPOSITORY_ORDER = ("auth", "workspaces", "entitlements", "connectors")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_SECRET_NAMES = frozenset({
    "access_token", "authorization", "challenge", "challenge_code", "code",
    "code_hash", "cookie", "credential", "credentials", "csrf",
    "csrf_token", "enrollment_code", "password", "private_key", "refresh_token",
    "secret", "session_token", "token",
})
_PATH_NAMES = frozenset({
    "config_file", "data_root", "file_path", "ninjatrader_user_dir", "path",
    "project_root", "runtime_data_dir", "runtime_dir", "source_path",
})
_DROP = object()


def _clean_ids(values: Iterable[Any], *, label: str) -> list[str]:
    rows = sorted({str(value or "").strip() for value in values if str(value or "").strip()})
    if any(len(value) > 160 for value in rows):
        raise StorageConstraintError(f"{label} contains an overlong identifier.")
    return rows


def _is_secret_key(key: str) -> bool:
    lowered = key.strip().lower()
    return (
        lowered in _SECRET_NAMES
        or lowered.endswith("_password")
        or lowered.endswith("_secret")
        or lowered.endswith("_token")
        or "private_key" in lowered
        or "challenge" in lowered
        or lowered.endswith("_nonce")
    )


def _is_path_key(key: str) -> bool:
    lowered = key.strip().lower()
    return (
        lowered in _PATH_NAMES
        or lowered.endswith("_path")
        or lowered.endswith("_root")
        or lowered.endswith("_directory")
    )


def _looks_like_absolute_path(value: str) -> bool:
    text = str(value or "").strip()
    return bool(
        text.startswith(("/", "\\\\"))
        or _WINDOWS_ABSOLUTE_RE.match(text)
    )


def _sanitize(value: Any, redactions: MutableMapping[str, int], *, depth: int = 0) -> Any:
    if depth > 20:
        raise StorageConstraintError("Owner migration source nesting is too deep.")
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if _is_secret_key(key):
                redactions["credentials"] = redactions.get("credentials", 0) + 1
                continue
            if _is_path_key(key):
                redactions["paths"] = redactions.get("paths", 0) + 1
                continue
            clean = _sanitize(raw_value, redactions, depth=depth + 1)
            if clean is not _DROP:
                result[key] = clean
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            clean = _sanitize(item, redactions, depth=depth + 1)
            if clean is not _DROP:
                result.append(clean)
        return result
    if isinstance(value, str) and _looks_like_absolute_path(value):
        redactions["paths"] = redactions.get("paths", 0) + 1
        return _DROP
    if value is None or isinstance(value, (str, int, float, bool)):
        return copy.deepcopy(value)
    return str(value)


def _rows(document: Mapping[str, Any], name: str) -> list[Dict[str, Any]]:
    return [copy.deepcopy(dict(row)) for row in document.get(name, []) if isinstance(row, Mapping)]


def _find_one(rows: Sequence[Mapping[str, Any]], key: str, value: Any, *, label: str) -> Dict[str, Any]:
    matches = [dict(row) for row in rows if str(row.get(key) or "") == str(value)]
    if len(matches) != 1:
        raise StorageConstraintError(f"Selected {label} was not found exactly once in Development.")
    return matches[0]


def _plan_hash(plan: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key != "plan_sha256"}
    return hashlib.sha256(_canonical(payload)).hexdigest()


def build_owner_plan(
    source_documents: Mapping[str, Mapping[str, Any]],
    source_ledgers: Mapping[str, Mapping[str, Any]],
    *,
    owner_user_id: int,
    categories: Iterable[str],
    workspace_ids: Iterable[str] = (),
    installation_ids: Iterable[str] = (),
) -> Dict[str, Any]:
    """Build an in-memory plan; callers must never persist it without protection."""
    owner_id = int(owner_user_id)
    if owner_id <= 0:
        raise StorageConstraintError("A positive owner_user_id is required.")
    selected_categories = sorted({str(value or "").strip().lower() for value in categories})
    unknown = set(selected_categories) - ALLOWED_CATEGORIES
    if unknown or not selected_categories:
        raise StorageConstraintError("Owner migration categories are missing or unsupported.")
    selected_workspaces = _clean_ids(workspace_ids, label="workspace_ids")
    selected_installations = _clean_ids(installation_ids, label="installation_ids")
    if set(selected_categories) - {"auth"} and "auth" not in selected_categories:
        raise StorageConstraintError("Every relational owner migration must explicitly include auth.")
    if set(selected_categories) & {"workspaces", "entitlements", "connectors", "ledgers"}:
        if "workspaces" not in selected_categories or not selected_workspaces:
            raise StorageConstraintError("Selected workspace data requires explicit workspaces and workspace_ids.")
    if selected_installations and "connectors" not in selected_categories:
        raise StorageConstraintError("installation_ids require the connectors category.")
    if "connectors" in selected_categories and not selected_installations:
        raise StorageConstraintError("Connector migration requires explicit installation_ids.")

    redactions: Dict[str, int] = {"credentials": 0, "paths": 0, "ephemeral_records": 0}
    raw_selection: Dict[str, Any] = {}
    documents: Dict[str, Dict[str, Any]] = {}

    auth_source = source_documents.get("auth") or {}
    owner = _find_one(_rows(auth_source, "users"), "user_id", owner_id, label="owner user")
    if not bool(owner.get("is_owner")) and str(owner.get("role") or "").lower() != "owner":
        raise StorageConstraintError("Selected user is not marked as the Development owner.")
    raw_selection["owner"] = owner
    if "auth" in selected_categories:
        clean_owner = _sanitize(owner, redactions)
        clean_owner["user_id"] = owner_id
        clean_owner["is_owner"] = True
        documents["auth"] = {
            "version": int(auth_source.get("version") or 2),
            "users": [clean_owner],
            "challenges": [],
            "sessions": [],
        }
        redactions["ephemeral_records"] += len(_rows(auth_source, "challenges"))
        redactions["ephemeral_records"] += len(_rows(auth_source, "sessions"))

    workspace_source = source_documents.get("workspaces") or {}
    selected_workspace_rows: list[Dict[str, Any]] = []
    selected_memberships: list[Dict[str, Any]] = []
    if "workspaces" in selected_categories:
        all_workspaces = _rows(workspace_source, "workspaces")
        all_memberships = _rows(workspace_source, "memberships")
        for workspace_id in selected_workspaces:
            row = _find_one(all_workspaces, "workspace_id", workspace_id, label="workspace")
            if _int(row.get("owner_user_id")) != owner_id:
                raise StorageConstraintError("A selected workspace is not owned by the selected owner.")
            selected_workspace_rows.append(_sanitize(row, redactions))
            memberships = [
                member for member in all_memberships
                if str(member.get("workspace_id") or "") == workspace_id
                and _int(member.get("user_id")) == owner_id
                and str(member.get("role") or "").lower() == "owner"
            ]
            if len(memberships) != 1:
                raise StorageConstraintError("Selected workspace lacks one exact owner membership.")
            selected_memberships.append(_sanitize(memberships[0], redactions))
        raw_selection["workspaces"] = selected_workspace_rows
        active_source = dict(workspace_source.get("active_workspaces") or {})
        active = str(active_source.get(str(owner_id)) or "")
        documents["workspaces"] = {
            "version": int(workspace_source.get("version") or 1),
            "workspaces": selected_workspace_rows,
            "memberships": selected_memberships,
            "active_workspaces": {str(owner_id): active} if active in selected_workspaces else {},
            "connections": [],
            "pairings": [],
        }
        redactions["ephemeral_records"] += len(_rows(workspace_source, "connections"))
        redactions["ephemeral_records"] += len(_rows(workspace_source, "pairings"))

    entitlement_source = source_documents.get("entitlements") or {}
    if "entitlements" in selected_categories:
        selected_entitlements = [
            row for row in _rows(entitlement_source, "entitlements")
            if _int(row.get("user_id")) == owner_id
            and str(row.get("workspace_id") or "") in selected_workspaces
        ]
        raw_selection["entitlements"] = selected_entitlements
        documents["entitlements"] = {
            "version": int(entitlement_source.get("version") or 1),
            "vouchers": [],
            "entitlements": [_sanitize(row, redactions) for row in selected_entitlements],
            "plan_overrides": {},
            "payment_config": {},
            "paypal": {},
            "payment_requests": [],
        }
        for key in ("vouchers", "payment_requests"):
            redactions["ephemeral_records"] += len(_rows(entitlement_source, key))

    connector_source = source_documents.get("connectors") or {}
    if "connectors" in selected_categories:
        all_installations = _rows(connector_source, "installations")
        installations = []
        for installation_id in selected_installations:
            row = _find_one(
                all_installations, "installation_id", installation_id,
                label="Connector installation",
            )
            if _int(row.get("user_id") or row.get("enrolled_by_user_id")) != owner_id:
                raise StorageConstraintError("Selected Connector installation belongs to another user.")
            if str(row.get("workspace_id") or "") not in selected_workspaces:
                raise StorageConstraintError("Selected Connector installation is outside selected workspaces.")
            clean = _sanitize(row, redactions)
            clean["status"] = "offline"
            if isinstance(clean.get("public_key"), Mapping):
                clean["public_key"] = {
                    key: value for key, value in dict(clean["public_key"]).items()
                    if key in {"kty", "crv", "x", "y", "n", "e", "use", "kid", "alg"}
                }
            for key in ("last_heartbeat_utc", "last_seen_utc", "online_at_utc"):
                clean.pop(key, None)
            installations.append(clean)
        raw_selection["installations"] = installations
        documents["connectors"] = {
            "schema_version": int(connector_source.get("schema_version") or 1),
            "enrollments": [],
            "installations": installations,
            "sessions": [],
            "commands": [],
            "results": [],
        }
        for key in ("enrollments", "sessions", "commands", "results"):
            redactions["ephemeral_records"] += len(_rows(connector_source, key))

    ledgers: Dict[str, Dict[str, Any]] = {}
    if "ledgers" in selected_categories:
        for workspace_id in selected_workspaces:
            ledger = source_ledgers.get(workspace_id)
            if not isinstance(ledger, Mapping):
                raise StorageConstraintError("Selected workspace ledger is unavailable.")
            raw_selection.setdefault("ledgers", {})[workspace_id] = dict(ledger)
            ledgers[workspace_id] = _sanitize(ledger, redactions)

    source_sha256 = hashlib.sha256(_canonical(raw_selection)).hexdigest()
    counts = {
        "users": len(documents.get("auth", {}).get("users", [])),
        "workspaces": len(documents.get("workspaces", {}).get("workspaces", [])),
        "memberships": len(documents.get("workspaces", {}).get("memberships", [])),
        "entitlements": len(documents.get("entitlements", {}).get("entitlements", [])),
        "installations": len(documents.get("connectors", {}).get("installations", [])),
        "ledgers": len(ledgers),
    }
    plan: Dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "owner_user_id": owner_id,
        "selection": {
            "categories": selected_categories,
            "workspace_ids": selected_workspaces,
            "installation_ids": selected_installations,
        },
        "source_sha256": source_sha256,
        "documents": documents,
        "ledgers": ledgers,
        "counts": counts,
        "redactions": redactions,
    }
    if len(_canonical(plan)) > 16 * 1024 * 1024:
        raise StorageConstraintError("Selected owner migration plan exceeds 16 MiB.")
    plan["plan_sha256"] = _plan_hash(plan)
    return plan


def owner_plan_summary(plan: Mapping[str, Any]) -> Dict[str, Any]:
    if int(plan.get("schema_version") or 0) != PLAN_SCHEMA_VERSION:
        raise StorageConstraintError("Unsupported owner migration plan schema.")
    expected = _plan_hash(plan)
    if str(plan.get("plan_sha256") or "") != expected:
        raise StorageConflictError("Owner migration plan checksum is invalid.")
    return {
        "dry_run": True,
        "owner_user_id": int(plan.get("owner_user_id") or 0),
        "selection": copy.deepcopy(dict(plan.get("selection") or {})),
        "counts": copy.deepcopy(dict(plan.get("counts") or {})),
        "redactions": copy.deepcopy(dict(plan.get("redactions") or {})),
        "source_sha256": str(plan.get("source_sha256") or ""),
        "plan_sha256": expected,
    }


def _merge_rows(
    existing: Sequence[Mapping[str, Any]], incoming: Sequence[Mapping[str, Any]],
    *, keys: Sequence[str], label: str,
) -> list[Dict[str, Any]]:
    result = [copy.deepcopy(dict(row)) for row in existing if isinstance(row, Mapping)]
    index = {tuple(str(row.get(key) or "") for key in keys): row for row in result}
    for raw in incoming:
        row = copy.deepcopy(dict(raw))
        identity = tuple(str(row.get(key) or "") for key in keys)
        if not all(identity):
            raise StorageConstraintError(f"Incoming {label} identity is incomplete.")
        prior = index.get(identity)
        if prior is not None:
            if _canonical(prior) != _canonical(row):
                raise StorageConflictError(f"Target already contains different {label} data.")
            continue
        result.append(row)
        index[identity] = row
    return result


def _merge_document(repository: str, existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> Dict[str, Any]:
    target = copy.deepcopy(dict(existing))
    if repository == "auth":
        target.setdefault("version", incoming.get("version", 2))
        target.setdefault("challenges", [])
        target.setdefault("sessions", [])
        target["users"] = _merge_rows(
            target.get("users", []), incoming.get("users", []),
            keys=("user_id",), label="owner user",
        )
    elif repository == "workspaces":
        target.setdefault("version", incoming.get("version", 1))
        target.setdefault("connections", [])
        target.setdefault("pairings", [])
        target["workspaces"] = _merge_rows(
            target.get("workspaces", []), incoming.get("workspaces", []),
            keys=("workspace_id",), label="workspace",
        )
        target["memberships"] = _merge_rows(
            target.get("memberships", []), incoming.get("memberships", []),
            keys=("workspace_id", "user_id"), label="workspace membership",
        )
        active = dict(target.get("active_workspaces") or {})
        for user_id, workspace_id in dict(incoming.get("active_workspaces") or {}).items():
            if str(user_id) in active and str(active[str(user_id)]) != str(workspace_id):
                raise StorageConflictError("Target owner active workspace differs from the migration plan.")
            active[str(user_id)] = str(workspace_id)
        target["active_workspaces"] = active
    elif repository == "entitlements":
        target.setdefault("version", incoming.get("version", 1))
        for key, empty in (
            ("vouchers", []), ("plan_overrides", {}), ("payment_config", {}),
            ("paypal", {}), ("payment_requests", []),
        ):
            target.setdefault(key, copy.deepcopy(empty))
        target["entitlements"] = _merge_rows(
            target.get("entitlements", []), incoming.get("entitlements", []),
            keys=("entitlement_id",), label="entitlement",
        )
    elif repository == "connectors":
        target.setdefault("schema_version", incoming.get("schema_version", 1))
        for key in ("enrollments", "sessions", "commands", "results"):
            target.setdefault(key, [])
        target["installations"] = _merge_rows(
            target.get("installations", []), incoming.get("installations", []),
            keys=("installation_id",), label="Connector installation",
        )
    else:
        raise StorageConstraintError("Unsupported owner migration repository.")
    return target


def apply_owner_plan(
    client: PostgresClient,
    plan: Mapping[str, Any],
    *,
    confirm_sha256: str,
) -> Dict[str, Any]:
    summary = owner_plan_summary(plan)
    if str(confirm_sha256 or "") != summary["plan_sha256"]:
        raise StorageConstraintError("Owner migration confirmation checksum mismatch.")
    documents = dict(plan.get("documents") or {})
    ledgers = dict(plan.get("ledgers") or {})
    owner_id = int(plan.get("owner_user_id") or 0)
    migration_run_id = f"owner_{summary['plan_sha256'][:32]}"
    document_revisions: Dict[str, int] = {}
    ledger_revisions: Dict[str, int] = {}
    repository = DocumentRepository(client)
    with client.transaction(Scope.global_service_scope()) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(7838146202602)")
        prior = conn.execute(
            "SELECT status FROM sf_migration_runs WHERE plan_sha256=%s",
            (summary["plan_sha256"],),
        ).fetchone()
        if prior:
            if str(prior["status"]) != "applied":
                raise StorageConflictError("Owner migration plan has a non-applied prior run.")
            return {**summary, "dry_run": False, "applied": False, "already_applied": True}

        for name in _REPOSITORY_ORDER:
            incoming = documents.get(name)
            if not isinstance(incoming, Mapping):
                continue
            row = conn.execute(
                "SELECT revision,document FROM sf_repository_documents WHERE repository=%s FOR UPDATE",
                (name,),
            ).fetchone()
            current_revision = int(row["revision"]) if row else 0
            current_document = dict(row["document"]) if row else {}
            merged = _merge_document(name, current_document, incoming)
            if row and _canonical(current_document) == _canonical(merged):
                document_revisions[name] = current_revision
                continue
            revision = current_revision + 1
            conn.execute(
                """
                INSERT INTO sf_repository_documents(repository,revision,document,updated_at)
                VALUES(%s,%s,%s,clock_timestamp())
                ON CONFLICT(repository) DO UPDATE SET revision=EXCLUDED.revision,
                  document=EXCLUDED.document,updated_at=clock_timestamp()
                """,
                (name, revision, _jsonb(merged)),
            )
            repository._sync_mirrors(conn, name, merged)
            document_revisions[name] = revision

        for workspace_id in sorted(ledgers):
            document = ledgers[workspace_id]
            if not isinstance(document, Mapping):
                raise StorageConstraintError("Owner migration ledger is invalid.")
            row = conn.execute(
                "SELECT revision,document FROM sf_workspace_ledgers WHERE workspace_id=%s FOR UPDATE",
                (workspace_id,),
            ).fetchone()
            if row:
                if _canonical(dict(row["document"])) != _canonical(dict(document)):
                    raise StorageConflictError("Target already contains a different workspace ledger.")
                ledger_revisions[workspace_id] = int(row["revision"])
                continue
            conn.execute(
                "INSERT INTO sf_workspace_ledgers(workspace_id,revision,document) VALUES(%s,1,%s)",
                (workspace_id, _jsonb(dict(document))),
            )
            ledger_revisions[workspace_id] = 1

        selection = dict(plan.get("selection") or {})
        selection_rows = [f"category:{value}" for value in selection.get("categories", [])]
        selection_rows.extend(f"workspace:{value}" for value in selection.get("workspace_ids", []))
        selection_rows.extend(f"installation:{value}" for value in selection.get("installation_ids", []))
        conn.execute(
            """
            INSERT INTO sf_migration_runs(migration_run_id,owner_user_id,selection,plan_sha256,
              source_sha256,status,counts,applied_at)
            VALUES(%s,%s,%s,%s,%s,'applied',%s,clock_timestamp())
            """,
            (
                migration_run_id, owner_id, _jsonb(selection_rows), summary["plan_sha256"],
                summary["source_sha256"], _jsonb(summary["counts"]),
            ),
        )
    return {
        **summary,
        "dry_run": False,
        "applied": True,
        "already_applied": False,
        "document_revisions": document_revisions,
        "ledger_revisions": ledger_revisions,
    }


def load_development_source(workspace_ids: Iterable[str]) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Read local DPAPI/files only under an explicit Development profile."""
    from .. import account_auth, connector_protocol, runtime_env, subscriptions, workspaces

    if not runtime_env.environment_explicit() or not runtime_env.is_development():
        raise StorageConstraintError(
            "Owner migration source must be read under explicit STRATFORGE_ENV=development."
        )
    documents = {
        "auth": account_auth._read_doc(),
        "workspaces": workspaces._read_doc(),
        "entitlements": subscriptions._read_doc(),
        "connectors": connector_protocol._read_doc(),
    }
    ledgers = {str(workspace_id): workspaces._read_ledger(str(workspace_id)) for workspace_id in workspace_ids}
    return documents, ledgers
