"""Bind the canonical Production owner to one preselected workspace.

The tool never accepts a raw Telegram id or workspace id on the command line.
Both identities come from the protected Production environment; destructive
intent is confirmed with SHA-256 digests that are safe to retain in evidence.
All repository documents and their normalized mirrors are updated in one
PostgreSQL transaction and the operation is idempotent.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, Mapping, Tuple

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import runtime_env, storage_router
from app.production_storage import DocumentRepository, Scope, get_client


class OwnerBootstrapError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _short(value: Any) -> str:
    return _digest(value)[:12]


def _identity_from_environment() -> Tuple[int, str]:
    raw_owner = str(os.environ.get("NTA_TELEGRAM_CHAT_ID") or "").strip()
    workspace_id = str(
        os.environ.get("STRATFORGE_OWNER_WORKSPACE_ID") or ""
    ).strip()
    if not re.fullmatch(r"[1-9][0-9]{0,19}", raw_owner):
        raise OwnerBootstrapError("Configured canonical owner identity is invalid.")
    if not re.fullmatch(r"ws_[A-Za-z0-9_-]{8,80}", workspace_id):
        raise OwnerBootstrapError("Configured canonical owner workspace is invalid.")
    return int(raw_owner), workspace_id


def reconcile_documents(
    auth: Mapping[str, Any],
    workspace_registry: Mapping[str, Any],
    connectors: Mapping[str, Any],
    *,
    owner_id: int,
    workspace_id: str,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """Return repaired copies plus a secret-safe reconciliation summary."""
    docs: Dict[str, Dict[str, Any]] = {
        "auth": copy.deepcopy(dict(auth)),
        "workspaces": copy.deepcopy(dict(workspace_registry)),
        "connectors": copy.deepcopy(dict(connectors)),
    }
    for name, fields in {
        "auth": ("users", "challenges", "sessions"),
        "workspaces": (
            "workspaces", "memberships", "connections", "pairings",
        ),
        "connectors": (
            "enrollments", "installations", "sessions", "commands", "results",
        ),
    }.items():
        for field in fields:
            if not isinstance(docs[name].get(field), list):
                docs[name][field] = []
    if not isinstance(docs["workspaces"].get("active_workspaces"), dict):
        docs["workspaces"]["active_workspaces"] = {}

    now = _now_iso()
    changes = {"auth": 0, "workspaces": 0, "connectors": 0}
    users = docs["auth"]["users"]
    configured = next(
        (row for row in users if int(row.get("user_id") or 0) == owner_id), None,
    )
    foreign_owners = [
        row for row in users
        if (
            bool(row.get("is_owner"))
            or str(row.get("role") or "").strip().lower() == "owner"
        )
        and int(row.get("user_id") or 0) != owner_id
    ]
    if foreign_owners:
        raise OwnerBootstrapError(
            "A foreign owner identity exists; automatic reassignment is forbidden."
        )
    if configured is None:
        configured = {
            "user_id": owner_id,
            "username": "",
            "first_name": "",
            "last_name": "",
            "email": "",
            "phone": "",
            "phone_hash": "",
            "role": "owner",
            "status": "active",
            "is_owner": True,
            "created_at_utc": now,
            "approved_at_utc": now,
            "revoked_at_utc": "",
        }
        users.append(configured)
        changes["auth"] += 1
    expected_owner = {
        "role": "owner", "status": "active", "is_owner": True,
        "revoked_at_utc": "",
    }
    if any(configured.get(key) != value for key, value in expected_owner.items()):
        configured.update(expected_owner)
        configured["updated_at_utc"] = now
        changes["auth"] += 1

    workspaces = docs["workspaces"]["workspaces"]
    target = next(
        (row for row in workspaces if str(row.get("workspace_id") or "") == workspace_id),
        None,
    )
    if target is None:
        raise OwnerBootstrapError(
            "Configured owner workspace does not exist; implicit selection is forbidden."
        )
    if str(target.get("status") or "active") != "active":
        raise OwnerBootstrapError("Configured owner workspace is not active.")
    collisions = [
        row for row in workspaces
        if str(row.get("workspace_id") or "") != workspace_id
        and int(row.get("owner_user_id") or 0) == owner_id
        and str(row.get("status") or "active") == "active"
    ]
    if collisions:
        raise OwnerBootstrapError(
            "Canonical owner already owns another active workspace."
        )
    if int(target.get("owner_user_id") or 0) != owner_id:
        target["owner_user_id"] = owner_id
        changes["workspaces"] += 1
    if not target.get("canonical_owner_workspace"):
        target["canonical_owner_workspace"] = True
        target["owner_bootstrapped_at_utc"] = now
        target["updated_at_utc"] = now
        changes["workspaces"] += 1

    memberships = docs["workspaces"]["memberships"]
    owner_membership = next(
        (
            row for row in memberships
            if str(row.get("workspace_id") or "") == workspace_id
            and int(row.get("user_id") or 0) == owner_id
        ),
        None,
    )
    if owner_membership is None:
        owner_membership = {
            "workspace_id": workspace_id,
            "user_id": owner_id,
            "role": "owner",
            "created_by_user_id": owner_id,
            "created_at_utc": now,
            "revoked_at_utc": "",
        }
        memberships.append(owner_membership)
        changes["workspaces"] += 1
    elif (
        str(owner_membership.get("role") or "") != "owner"
        or bool(owner_membership.get("revoked_at_utc"))
    ):
        owner_membership.update(
            {"role": "owner", "revoked_at_utc": "", "updated_at_utc": now}
        )
        changes["workspaces"] += 1

    for row in memberships:
        row_workspace = str(row.get("workspace_id") or "")
        row_user = int(row.get("user_id") or 0)
        if (
            row_workspace == workspace_id
            and row_user != owner_id
            and str(row.get("role") or "") == "owner"
            and not row.get("revoked_at_utc")
        ):
            row["role"] = "viewer"
            row["updated_at_utc"] = now
            changes["workspaces"] += 1
        if (
            row_user == owner_id
            and row_workspace != workspace_id
            and str(row.get("role") or "") == "owner"
            and not row.get("revoked_at_utc")
        ):
            row["revoked_at_utc"] = now
            row["updated_at_utc"] = now
            changes["workspaces"] += 1

    active = docs["workspaces"]["active_workspaces"]
    if str(active.get(str(owner_id)) or "") != workspace_id:
        active[str(owner_id)] = workspace_id
        changes["workspaces"] += 1

    target_installations = [
        row for row in docs["connectors"]["installations"]
        if str(row.get("workspace_id") or "") == workspace_id
    ]
    online_installations = [
        row for row in target_installations if str(row.get("status") or "") == "online"
    ]
    if len(online_installations) != 1:
        raise OwnerBootstrapError(
            "Canonical owner workspace must have exactly one online Connector."
        )
    for row in target_installations:
        if int(row.get("enrolled_by_user_id") or row.get("user_id") or 0) != owner_id:
            row["enrolled_by_user_id"] = owner_id
            if "user_id" in row:
                row["user_id"] = owner_id
            row["owner_rebound_at_utc"] = now
            changes["connectors"] += 1
    for row in docs["connectors"]["enrollments"]:
        if (
            str(row.get("workspace_id") or "") == workspace_id
            and int(row.get("created_by_user_id") or 0) != owner_id
        ):
            row["created_by_user_id"] = owner_id
            changes["connectors"] += 1

    active_owner_memberships = [
        row for row in memberships
        if int(row.get("user_id") or 0) == owner_id
        and str(row.get("role") or "") == "owner"
        and not row.get("revoked_at_utc")
    ]
    summary = {
        "owner_hash": _short(owner_id),
        "workspace_hash": _short(workspace_id),
        "changes": changes,
        "owner_users": sum(
            1 for row in users
            if int(row.get("user_id") or 0) == owner_id
            and bool(row.get("is_owner"))
            and str(row.get("status") or "") == "active"
        ),
        "owner_workspaces": sum(
            1 for row in workspaces
            if str(row.get("workspace_id") or "") == workspace_id
            and int(row.get("owner_user_id") or 0) == owner_id
            and str(row.get("status") or "") == "active"
        ),
        "owner_memberships": len(active_owner_memberships),
        "online_connectors": len(online_installations),
        "connector_installations": len(target_installations),
        "idempotent": not any(changes.values()),
    }
    if (
        summary["owner_users"] != 1
        or summary["owner_workspaces"] != 1
        or summary["owner_memberships"] != 1
    ):
        raise OwnerBootstrapError("Canonical owner invariants were not established.")
    return docs, summary


def run(*, apply: bool, confirm_owner_sha256: str = "",
        confirm_workspace_sha256: str = "") -> Dict[str, Any]:
    config = runtime_env.assert_startup_safe()
    if config.environment != runtime_env.PRODUCTION:
        raise OwnerBootstrapError("Owner bootstrap is Production-only.")
    storage_router.assert_production_storage_safe()
    owner_id, workspace_id = _identity_from_environment()
    if apply:
        if not (
            hashlib.sha256(str(owner_id).encode("utf-8")).hexdigest()
            == str(confirm_owner_sha256 or "").lower()
            and hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()
            == str(confirm_workspace_sha256 or "").lower()
        ):
            raise OwnerBootstrapError("Hashed owner/workspace confirmation mismatch.")

    client = get_client(production=True)
    repository = DocumentRepository(client)
    scope = Scope.global_service_scope()
    with client.transaction(scope, read_only=not apply) as conn:
        rows = conn.execute(
            """
            SELECT repository, revision, document
            FROM sf_repository_documents
            WHERE repository IN ('auth','workspaces','connectors')
            ORDER BY repository
            """ + (" FOR UPDATE" if apply else "")
        ).fetchall()
        current = {str(row["repository"]): dict(row["document"]) for row in rows}
        revisions = {str(row["repository"]): int(row["revision"]) for row in rows}
        if set(current) != {"auth", "workspaces", "connectors"}:
            raise OwnerBootstrapError("Required Production repositories are missing.")
        repaired, summary = reconcile_documents(
            current["auth"], current["workspaces"], current["connectors"],
            owner_id=owner_id, workspace_id=workspace_id,
        )
        if apply:
            from psycopg.types.json import Jsonb

            for name in ("auth", "workspaces", "connectors"):
                if not summary["changes"][name]:
                    continue
                conn.execute(
                    """
                    UPDATE sf_repository_documents
                    SET revision=%s, document=%s, updated_at=clock_timestamp()
                    WHERE repository=%s AND revision=%s
                    """,
                    (revisions[name] + 1, Jsonb(repaired[name]), name, revisions[name]),
                )
                repository._sync_mirrors(conn, name, repaired[name])  # noqa: SLF001
            summary["applied"] = True
        else:
            summary["applied"] = False
    summary["ok"] = True
    summary["secrets_redacted"] = True
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-owner-sha256", default="")
    parser.add_argument("--confirm-workspace-sha256", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run(
            apply=bool(args.apply),
            confirm_owner_sha256=args.confirm_owner_sha256,
            confirm_workspace_sha256=args.confirm_workspace_sha256,
        )
    except Exception as exc:  # output class only; never echo identities/DSN
        print(json.dumps({
            "ok": False,
            "error": exc.__class__.__name__,
            "secrets_redacted": True,
        }, sort_keys=True, separators=(",", ":")))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
