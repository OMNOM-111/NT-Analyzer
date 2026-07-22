#!/usr/bin/env python3
"""Fail-closed operator CLI for StratForge Production storage."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.production_storage import (
    MigrationRunner,
    apply_owner_plan,
    build_owner_plan,
    load_development_source,
    owner_plan_summary,
)
from app.production_storage.backup import create_backup, restore_backup, verify_backup
from app.production_storage.artifacts import FileArtifactStore
from app.production_storage.core import (
    PostgresClient,
    Scope,
    StorageConstraintError,
    StorageError,
)


_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,100}$")


def _url_from_environment(name: str) -> str:
    if not _ENV_NAME_RE.fullmatch(str(name or "")):
        raise ValueError("Invalid database URL environment-variable name.")
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise ValueError(f"Required database URL environment variable is empty: {name}.")
    return value


def _pg_bin(value: str) -> Path:
    raw = str(value or os.environ.get("STRATFORGE_PG_BIN") or "").strip()
    if not raw:
        raise ValueError("PostgreSQL binary directory is required via --pg-bin or STRATFORGE_PG_BIN.")
    return Path(raw)


def _artifact_root(value: str) -> Path:
    raw = str(value or os.environ.get("STRATFORGE_ARTIFACT_ROOT") or "").strip()
    if not raw:
        raise ValueError("Artifact root is required via --artifact-root or STRATFORGE_ARTIFACT_ROOT.")
    return Path(raw)


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str))


def _schema(args: argparse.Namespace) -> int:
    url = _url_from_environment(args.url_env)
    runner = MigrationRunner(url, production=not args.allow_local_test)
    plan = runner.plan()
    if not args.apply:
        _print({**plan, "dry_run": True})
        return 0
    if args.confirm_migration_set_sha256 != plan["migration_set_sha256"]:
        raise ValueError("Migration-set checksum confirmation mismatch.")
    _print({**runner.apply(), "dry_run": False})
    return 0


def _owner(args: argparse.Namespace) -> int:
    documents, ledgers = load_development_source(args.workspace_id)
    plan = build_owner_plan(
        documents,
        ledgers,
        owner_user_id=args.owner_user_id,
        categories=args.include,
        workspace_ids=args.workspace_id,
        installation_ids=args.installation_id,
    )
    summary = owner_plan_summary(plan)
    if not args.apply:
        _print(summary)
        return 0
    url = _url_from_environment(args.url_env)
    client = PostgresClient(url, production=not args.allow_local_test)
    _print(apply_owner_plan(client, plan, confirm_sha256=args.confirm_sha256))
    return 0


def _backup(args: argparse.Namespace) -> int:
    _print(create_backup(
        database_url=_url_from_environment(args.url_env),
        artifact_root=_artifact_root(args.artifact_root),
        output_dir=Path(args.output_dir),
        pg_bin=_pg_bin(args.pg_bin),
        quiesced=bool(args.confirm_quiesced),
    ))
    return 0


def _verify(args: argparse.Namespace) -> int:
    _print(verify_backup(backup_dir=Path(args.backup_dir), pg_bin=_pg_bin(args.pg_bin)))
    return 0


def _restore(args: argparse.Namespace) -> int:
    _print(restore_backup(
        backup_dir=Path(args.backup_dir),
        target_database_url=_url_from_environment(args.url_env),
        target_artifact_root=Path(args.artifact_target),
        confirm_dump_sha256=args.confirm_dump_sha256,
        confirm_target_database=args.confirm_target_database,
        pg_bin=_pg_bin(args.pg_bin),
    ))
    return 0


def _retention(args: argparse.Namespace) -> int:
    url = _url_from_environment(args.url_env)
    production = not args.allow_local_test
    client = PostgresClient(url, production=production)
    store = FileArtifactStore(client, production=production)
    current = None
    if args.at_utc:
        try:
            current = datetime.fromisoformat(args.at_utc.replace("Z", "+00:00"))
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            current = current.astimezone(timezone.utc)
        except ValueError as exc:
            raise ValueError("--at-utc must be an ISO-8601 timestamp.") from exc
    scope = Scope(workspace_id=args.workspace_id)
    plan = store.retention_plan(scope=scope, now=current)
    summary = {
        "dry_run": True,
        "workspace_id": plan["workspace_id"],
        "count": plan["count"],
        "size_bytes": plan["size_bytes"],
        "plan_sha256": plan["plan_sha256"],
    }
    if not args.apply:
        _print(summary)
        return 0
    result = store.quarantine_expired(
        plan, scope=scope, confirm_sha256=args.confirm_sha256,
    )
    _print({**summary, **result, "dry_run": False})
    return 0


def _quota(args: argparse.Namespace) -> int:
    client = PostgresClient(
        _url_from_environment(args.url_env), production=not args.allow_local_test,
    )
    scope = Scope(workspace_id=args.workspace_id)
    with client.transaction(scope) as conn:
        used = int(conn.execute(
            """SELECT COALESCE(SUM(size_bytes),0) AS used FROM sf_artifacts
               WHERE workspace_id=%s AND status='active'""",
            (args.workspace_id,),
        ).fetchone()["used"])
        if args.set_bytes is not None:
            quota = int(args.set_bytes)
            if args.confirm_workspace_id != args.workspace_id:
                raise StorageConstraintError("Quota workspace confirmation mismatch.")
            if quota < 1024 * 1024 or quota > 10 * 1024**4:
                raise StorageConstraintError("Workspace quota is outside the schema limits.")
            if quota < used:
                raise StorageConstraintError("Workspace quota cannot be lower than active usage.")
            conn.execute(
                """INSERT INTO sf_storage_quotas(workspace_id,quota_bytes,updated_at)
                   VALUES(%s,%s,clock_timestamp())
                   ON CONFLICT(workspace_id) DO UPDATE SET quota_bytes=EXCLUDED.quota_bytes,
                     updated_at=clock_timestamp()""",
                (args.workspace_id, quota),
            )
        row = conn.execute(
            "SELECT quota_bytes FROM sf_storage_quotas WHERE workspace_id=%s",
            (args.workspace_id,),
        ).fetchone()
    _print({
        "ok": True,
        "workspace_id": args.workspace_id,
        "quota_bytes": int(row["quota_bytes"]) if row else None,
        "active_usage_bytes": used,
        "explicit_override": bool(row),
    })
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)

    schema = commands.add_parser("schema", help="Plan or apply immutable SQL migrations.")
    schema.add_argument("--url-env", default="STRATFORGE_MIGRATION_DATABASE_URL")
    schema.add_argument("--apply", action="store_true")
    schema.add_argument("--confirm-migration-set-sha256", default="")
    schema.add_argument("--allow-local-test", action="store_true")
    schema.set_defaults(handler=_schema)

    owner = commands.add_parser("owner", help="Plan or apply explicitly selected owner data.")
    owner.add_argument("--owner-user-id", type=int, required=True)
    owner.add_argument("--include", action="append", required=True, choices=sorted({
        "auth", "workspaces", "entitlements", "connectors", "ledgers",
    }))
    owner.add_argument("--workspace-id", action="append", default=[])
    owner.add_argument("--installation-id", action="append", default=[])
    owner.add_argument("--url-env", default="STRATFORGE_DATABASE_URL")
    owner.add_argument("--apply", action="store_true")
    owner.add_argument("--confirm-sha256", default="")
    owner.add_argument("--allow-local-test", action="store_true")
    owner.set_defaults(handler=_owner)

    backup = commands.add_parser("backup", help="Create a verified DB plus artifact backup.")
    backup.add_argument("--url-env", default="STRATFORGE_BACKUP_DATABASE_URL")
    backup.add_argument("--artifact-root", default="")
    backup.add_argument("--output-dir", required=True)
    backup.add_argument("--pg-bin", default="")
    backup.add_argument("--confirm-quiesced", action="store_true")
    backup.set_defaults(handler=_backup)

    verify = commands.add_parser("verify-backup", help="Verify dump and every artifact checksum.")
    verify.add_argument("--backup-dir", required=True)
    verify.add_argument("--pg-bin", default="")
    verify.set_defaults(handler=_verify)

    restore = commands.add_parser("restore", help="Restore only into an empty isolated target.")
    restore.add_argument("--url-env", default="STRATFORGE_RESTORE_DATABASE_URL")
    restore.add_argument("--backup-dir", required=True)
    restore.add_argument("--artifact-target", required=True)
    restore.add_argument("--confirm-dump-sha256", required=True)
    restore.add_argument("--confirm-target-database", required=True)
    restore.add_argument("--pg-bin", default="")
    restore.set_defaults(handler=_restore)

    retention = commands.add_parser("retention", help="Plan or quarantine expired artifacts.")
    retention.add_argument("--url-env", default="STRATFORGE_DATABASE_URL")
    retention.add_argument("--workspace-id", required=True)
    retention.add_argument("--at-utc", default="")
    retention.add_argument("--apply", action="store_true")
    retention.add_argument("--confirm-sha256", default="")
    retention.add_argument("--allow-local-test", action="store_true")
    retention.set_defaults(handler=_retention)

    quota = commands.add_parser("quota", help="Read or explicitly set a workspace artifact quota.")
    quota.add_argument("--url-env", default="STRATFORGE_DATABASE_URL")
    quota.add_argument("--workspace-id", required=True)
    quota.add_argument("--set-bytes", type=int)
    quota.add_argument("--confirm-workspace-id", default="")
    quota.add_argument("--allow-local-test", action="store_true")
    quota.set_defaults(handler=_quota)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (StorageError, ValueError, OSError) as exc:
        print(json.dumps({
            "ok": False,
            "code": getattr(exc, "code", "operator_error"),
            "error": str(exc),
        }, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
