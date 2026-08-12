#!/usr/bin/env python3
"""Provision a fully isolated Canary contour on a Supervisor-managed host.

Real topology on the current production host: no systemd, a single
supervisord instance manages `api` (Production) / `api-canary` (Canary) /
`worker` / `worker-canary` / `operations` / `operations-canary` / `telegram`
programs. This tool creates the Canary-only PostgreSQL role and database, a
dedicated data/artifact root, and a Canary environment file with identities
that differ from Production on every field checked by
`app.runtime_env.assert_environment_isolation`.

Every mutation is preceded by a fail-closed pre-validation
(`_preflight_collision_guard`) that reads the real Production reference
identities *before* issuing any `CREATE`/`ALTER ROLE`/`CREATE DATABASE`
statement and refuses to run if the requested Canary identity collides with
(or would override) a Production one. This tool never creates, alters or
drops `stratforge_app`, Production's database, or any object owned by them.

The SQL migration files under `app/production_storage/migrations/` hardcode
`GRANT ... TO stratforge_app` (Production's own role) because they run
unmodified against Production and Canary alike to keep their checksums
stable. Applying them to the Canary database therefore also grants
Production's role access to Canary's own tables/sequences/functions -- a
real cross-environment privilege leak. `--lockdown-privileges` is the
mandatory follow-up step, run once immediately after migrations are applied
to the Canary database: inside one transaction it revokes every privilege
`stratforge_app` (or the configured Production app role) and `PUBLIC` hold
on Canary's schema/objects/database, and (re)grants the Canary app role
(plus default privileges for future migration-created objects) explicitly.
It is idempotent and safe to re-run after every future migration.

Idempotent by default: refuses to overwrite an existing Canary environment
file unless --force is passed. Never prints a secret value; only paths,
booleans, ids and non-secret runtime fields.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

_SAFE_PRODUCTION_KEYS = (
    "STRATFORGE_DATABASE_ID",
    "STRATFORGE_QUEUE_ID",
    "STRATFORGE_OBJECT_STORAGE_ID",
    "STRATFORGE_TELEGRAM_BOT_ID",
    "STRATFORGE_COOKIE_NAMESPACE",
    "STRATFORGE_SIGNING_KEY_ID",
    "STRATFORGE_LOG_NAMESPACE",
    "STRATFORGE_INSTANCE_ID",
    "STRATFORGE_PUBLIC_ORIGIN",
    "STRATFORGE_ALLOWED_HOSTS",
    "STRATFORGE_DATA_ROOT",
)

# Third-party market-data/AI provider credentials are vendor subscriptions,
# not per-environment identity. They are intentionally shared with
# Production; the isolation guard never compares them.
_SHARED_PROVIDER_KEYS = (
    "NTA_DATABENTO_API_KEY",
    "NTA_DEEPSEEK_API_KEY",
    "NTA_DXFEED_TOKEN",
    "NTA_GEMINI_API_KEY",
    "NTA_OPENAI_API_KEY",
    "NTA_TOPSTEPX_API_KEY",
    "NTA_TOPSTEPX_USERNAME",
)

# Known Production/superuser role and database names. A requested Canary
# identity matching any of these is always rejected, even if the real
# Production reference file cannot be read for some reason.
_RESERVED_ROLE_NAMES = {"postgres", "stratforge_app", "stratforge_migration"}
_RESERVED_DB_NAMES = {"postgres", "template0", "template1"}
_PG_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class ProvisionGuardError(RuntimeError):
    """Raised by the pre-validation guard; no Postgres mutation has occurred yet."""


def _quote_env_value(value: str) -> str:
    """Single-quote a value for safe `set -a; . file; set +a` sourcing.

    Without quoting, unquoted `&`, `?`, `;` etc. inside a DSN are
    reinterpreted by the shell (e.g. `&` backgrounds the assignment),
    silently truncating the value.
    """
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _quote_env_lines(content: str) -> str:
    out = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key, _, value = line.partition("=")
        out.append(f"{key}={_quote_env_value(value)}")
    return "\n".join(out) + "\n"


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _parse_dsn_identity(url: str) -> tuple[str, str]:
    """Return (username, database_name) from a PostgreSQL DSN. No secrets."""
    if not url:
        return "", ""
    parsed = urllib.parse.urlsplit(url)
    username = urllib.parse.unquote(parsed.username or "")
    database = (parsed.path or "").strip("/")
    return username, database


def _pg_identifier(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not _PG_IDENTIFIER_RE.fullmatch(text):
        raise ProvisionGuardError(
            f"{label} must be a lowercase PostgreSQL identifier (a-z, 0-9, underscore)."
        )
    return text


def _run_psql(socket_dir: str, port: int, database: str, sql: str) -> str:
    result = subprocess.run(
        [
            "sudo", "-n", "-u", "postgres", "psql",
            "-h", socket_dir, "-p", str(port), "-d", database,
            "-v", "ON_ERROR_STOP=1", "-Atq", "-c", sql,
        ],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _run_psql_script(socket_dir: str, port: int, database: str, script: str) -> None:
    """Run a multi-statement SQL script as one explicit transaction.

    Uses a temp file + `psql -f` (rather than `-c`) so `ON_ERROR_STOP=1`
    reliably aborts the whole script -- including the surrounding
    `BEGIN`/`COMMIT` -- on the first failing statement.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sql", delete=False, encoding="utf-8",
    ) as handle:
        handle.write("BEGIN;\n" + script.strip() + "\nCOMMIT;\n")
        script_path = handle.name
    try:
        # The script is executed as the postgres OS user. The lockdown SQL
        # contains only role/object names, never DSNs or passwords, so a
        # short-lived world-readable temp file is safer than making the
        # postgres user fail to read a 0600 file owned by the caller.
        os.chmod(script_path, 0o644)
        subprocess.run(
            [
                "sudo", "-n", "-u", "postgres", "psql",
                "-h", socket_dir, "-p", str(port), "-d", database,
                "-v", "ON_ERROR_STOP=1", "-Atq", "-f", script_path,
            ],
            check=True, capture_output=True, text=True,
        )
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def _role_exists(socket_dir: str, port: int, role: str) -> bool:
    out = _run_psql(
        socket_dir, port, "postgres",
        f"SELECT 1 FROM pg_roles WHERE rolname = '{role}'",
    )
    return out.strip() == "1"


def _database_exists(socket_dir: str, port: int, name: str) -> bool:
    out = _run_psql(
        socket_dir, port, "postgres",
        f"SELECT 1 FROM pg_database WHERE datname = '{name}'",
    )
    return out.strip() == "1"


def _preflight_collision_guard(args: argparse.Namespace, production_env: dict[str, str]) -> None:
    """Fail closed before any CREATE/ALTER ROLE/DATABASE statement.

    Reads only the real Production reference identity (never a secret) and
    refuses to proceed if the requested Canary role/database/instance/data
    root would collide with, or could be mistaken for, Production's own.
    """
    prod_role, prod_db = _parse_dsn_identity(production_env.get("STRATFORGE_DATABASE_URL", ""))
    requested_roles = {}
    for field in ("canary_app_role", "canary_migration_role"):
        value = _pg_identifier(getattr(args, field, ""), field)
        setattr(args, field, value)
        requested_roles[field] = value
    for field, value in requested_roles.items():
        lowered = value.lower()
        if lowered in _RESERVED_ROLE_NAMES:
            raise ProvisionGuardError(f"{field} '{value}' is a reserved Production/superuser role name")
        if prod_role and lowered == prod_role.strip().lower():
            raise ProvisionGuardError(f"{field} '{value}' collides with the Production app role")
    if args.canary_app_role.lower() == args.canary_migration_role.lower():
        raise ProvisionGuardError("canary_app_role and canary_migration_role must differ")

    args.canary_db_name = _pg_identifier(args.canary_db_name, "canary_db_name")
    db_lowered = args.canary_db_name.lower()
    if db_lowered in _RESERVED_DB_NAMES:
        raise ProvisionGuardError(f"canary_db_name '{args.canary_db_name}' is a reserved database name")
    if prod_db and db_lowered == prod_db.strip().lower():
        raise ProvisionGuardError(f"canary_db_name '{args.canary_db_name}' collides with the Production database")

    prod_instance = production_env.get("STRATFORGE_INSTANCE_ID", "").strip()
    if prod_instance and args.instance_id.strip().lower() == prod_instance.lower():
        raise ProvisionGuardError(f"instance_id '{args.instance_id}' collides with the Production instance id")

    prod_data_root = production_env.get("STRATFORGE_DATA_ROOT", "").strip()
    if prod_data_root:
        try:
            prod_resolved = Path(prod_data_root).resolve()
            for label, raw in (
                ("canary_data_root", args.canary_data_root),
                ("canary_artifact_root", args.canary_artifact_root),
            ):
                candidate = Path(raw).resolve()
                if candidate == prod_resolved or _is_within(candidate, prod_resolved) or _is_within(prod_resolved, candidate):
                    raise ProvisionGuardError(f"{label} '{raw}' collides with the Production data root")
        except (OSError, ValueError):
            pass


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def provision_database(args: argparse.Namespace) -> dict[str, str]:
    """Create the Canary migration+app roles and database. Returns DSNs.

    Passwords are generated in-process and only ever written to the
    protected Canary env files (0600); they are never printed or logged.
    Grants issued here cover the baseline schema/default-privilege surface
    only; the migrations themselves additionally (and unavoidably) grant
    Production's `stratforge_app` role access to whatever tables they
    create -- `--lockdown-privileges` must run immediately after migrations
    to revoke that and make the Canary role's access exclusive.
    """
    socket_dir, port = args.pg_socket, args.pg_port
    migration_role = args.canary_migration_role
    app_role = args.canary_app_role
    db_name = args.canary_db_name

    migration_password = secrets.token_urlsafe(36)
    app_password = secrets.token_urlsafe(36)

    if not _role_exists(socket_dir, port, migration_role):
        _run_psql(
            socket_dir, port, "postgres",
            f"CREATE ROLE {migration_role} LOGIN PASSWORD '{migration_password}'",
        )
    else:
        _run_psql(
            socket_dir, port, "postgres",
            f"ALTER ROLE {migration_role} PASSWORD '{migration_password}'",
        )
    if not _role_exists(socket_dir, port, app_role):
        _run_psql(
            socket_dir, port, "postgres",
            f"CREATE ROLE {app_role} LOGIN PASSWORD '{app_password}'",
        )
    else:
        _run_psql(
            socket_dir, port, "postgres",
            f"ALTER ROLE {app_role} PASSWORD '{app_password}'",
        )

    if not _database_exists(socket_dir, port, db_name):
        _run_psql(
            socket_dir, port, "postgres",
            f"CREATE DATABASE {db_name} OWNER {migration_role}",
        )

    _run_psql(socket_dir, port, db_name, f"GRANT CONNECT ON DATABASE {db_name} TO {app_role}")
    _run_psql(socket_dir, port, db_name, f"GRANT USAGE ON SCHEMA public TO {app_role}")
    _run_psql(
        socket_dir, port, db_name,
        f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {app_role}",
    )
    _run_psql(
        socket_dir, port, db_name,
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {migration_role} IN SCHEMA public "
        f"GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO {app_role}",
    )
    _run_psql(
        socket_dir, port, db_name,
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {migration_role} IN SCHEMA public "
        f"GRANT USAGE,SELECT ON SEQUENCES TO {app_role}",
    )
    _run_psql(
        socket_dir, port, db_name,
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {migration_role} IN SCHEMA public "
        f"GRANT EXECUTE ON FUNCTIONS TO {app_role}",
    )

    ca_cert = args.pg_ca_cert
    quoted_migration_pw = urllib.parse.quote(migration_password, safe="")
    quoted_app_pw = urllib.parse.quote(app_password, safe="")
    common = f"@localhost:{port}/{db_name}?sslmode=verify-full&sslrootcert={ca_cert}"
    return {
        "migration_url": f"postgresql://{migration_role}:{quoted_migration_pw}{common}",
        "app_url": f"postgresql://{app_role}:{quoted_app_pw}{common}",
    }


def lockdown_privileges_sql(args: argparse.Namespace, production_app_role: str) -> str:
    """Return the idempotent post-migration privilege-lockdown SQL script.

    Pure/testable: builds and returns the SQL text without touching
    Postgres, so tests can assert its exact shape (which roles are revoked
    from, which role is granted to) without a live database.
    """
    app_role = args.canary_app_role
    migration_role = args.canary_migration_role
    statements = [
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {production_app_role}",
        f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {production_app_role}",
        f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM {production_app_role}",
        f"REVOKE ALL ON SCHEMA public FROM {production_app_role}",
        "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC",
        "REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC",
        "REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {migration_role} IN SCHEMA public "
        f"REVOKE ALL ON TABLES FROM {production_app_role}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {migration_role} IN SCHEMA public "
        f"REVOKE ALL ON SEQUENCES FROM {production_app_role}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {migration_role} IN SCHEMA public "
        f"REVOKE ALL ON FUNCTIONS FROM {production_app_role}",
        f"GRANT USAGE ON SCHEMA public TO {app_role}",
        f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {app_role}",
        f"GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {app_role}",
        f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO {app_role}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {migration_role} IN SCHEMA public "
        f"GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO {app_role}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {migration_role} IN SCHEMA public "
        f"GRANT USAGE,SELECT ON SEQUENCES TO {app_role}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {migration_role} IN SCHEMA public "
        f"GRANT EXECUTE ON FUNCTIONS TO {app_role}",
    ]
    return ";\n".join(statements) + ";"


def lockdown_privileges(args: argparse.Namespace, production_env: dict[str, str]) -> dict[str, object]:
    """Revoke Production/PUBLIC access to the Canary database, grant Canary.

    Must run once, immediately after every `production_storage_cli.py schema
    --apply` against the Canary database. Idempotent: safe to re-run.
    """
    _preflight_collision_guard(args, production_env)
    prod_role, _ = _parse_dsn_identity(production_env.get("STRATFORGE_DATABASE_URL", ""))
    production_app_role = _pg_identifier(prod_role or "stratforge_app", "production_app_role")
    if production_app_role.strip().lower() == args.canary_app_role.strip().lower():
        raise ProvisionGuardError("refusing to lock down: Production app role equals Canary app role")
    script = lockdown_privileges_sql(args, production_app_role)
    _run_psql_script(args.pg_socket, args.pg_port, args.canary_db_name, script)
    _run_psql(
        args.pg_socket, args.pg_port, "postgres",
        f"REVOKE CONNECT ON DATABASE {args.canary_db_name} FROM {production_app_role}",
    )
    _run_psql(
        args.pg_socket, args.pg_port, "postgres",
        f"REVOKE CONNECT ON DATABASE {args.canary_db_name} FROM PUBLIC",
    )
    return {
        "ok": True,
        "schema_version": 1,
        "canary_database_name": args.canary_db_name,
        "canary_app_role": args.canary_app_role,
        "revoked_from": [production_app_role, "PUBLIC"],
        "granted_to": args.canary_app_role,
    }


def write_lockdown_marker(path: Path, result: Mapping[str, object]) -> None:
    """Write the secret-free marker required by Canary promotion."""
    marker = {
        "schema_version": 1,
        "ok": bool(result.get("ok")),
        "canary_database_name": str(result.get("canary_database_name") or ""),
        "canary_app_role": str(result.get("canary_app_role") or ""),
        "revoked_from": list(result.get("revoked_from") or []),
        "granted_to": str(result.get("granted_to") or ""),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    if not marker["ok"] or not marker["canary_database_name"] or not marker["canary_app_role"]:
        raise ProvisionGuardError("refusing to write incomplete privilege-lockdown marker")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)
    os.chmod(path, 0o600)


def default_connector_catalog() -> dict[str, object]:
    """A schema-valid, disabled Connector release catalog.

    Matches `app.connector_releases.load_catalog`'s real, strict schema
    exactly (schema_version=1, channels.stable/canary, each with the full
    required field set). Placeholder version/hashes/URL clearly mark that no
    real Connector distribution has been provisioned for Canary yet; the
    loader accepts the document and Connector stays intentionally unusable
    (0 canary installations, an unreachable archive URL) rather than
    unreadable/invalid.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    placeholder_hash = "0" * 64

    def _channel() -> dict[str, object]:
        return {
            "version": "0.0.1",
            "archive_url": "https://canary.stratforges.com/connector/not-provisioned",
            "archive_sha256": placeholder_hash,
            "manifest_sha256": placeholder_hash,
            "protocol_version": "1.0",
            "minimum_version": "0.0.1",
            "blocked_versions": [],
            "major_approved": False,
            "health_timeout_sec": 900,
            "published_at_utc": now,
        }

    return {
        "schema_version": 1,
        "channels": {"stable": _channel(), "canary": _channel()},
        "canary_installation_ids": [],
    }


def _connector_catalog_needs_refresh(path: Path) -> bool:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return True
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return True
    channels = raw.get("channels")
    if not isinstance(channels, dict) or set(channels) != {"stable", "canary"}:
        return True
    required = {
        "version", "archive_url", "archive_sha256", "manifest_sha256",
        "protocol_version", "minimum_version", "blocked_versions",
        "major_approved", "health_timeout_sec", "published_at_utc",
    }
    for value in channels.values():
        if not isinstance(value, dict) or set(value) != required:
            return True
    return False


def build_canary_env(args: argparse.Namespace, dsn: dict[str, str], signing_key: str) -> str:
    production = _read_env_file(Path(args.production_env_path))
    reference_lines = []
    for key in _SAFE_PRODUCTION_KEYS:
        value = production.get(key, "")
        reference_lines.append(f"STRATFORGE_PRODUCTION_{key[len('STRATFORGE_'):]}={value}")
    shared_provider_lines = [
        f"{key}={production[key]}" for key in _SHARED_PROVIDER_KEYS if key in production
    ]

    lines = [
        "# Generated by tools/canary_isolation_provision.py. Contains real secrets;",
        "# mode 0600, owner stratforge only. Never commit to Git.",
        "#",
        "# API-runtime env ONLY: this file intentionally does NOT contain the",
        "# migration/backup owner DSN (STRATFORGE_MIGRATION_DATABASE_URL /",
        "# STRATFORGE_BACKUP_DATABASE_URL). Those live in the separate",
        "# canary-maintenance.env (mode 0600), sourced only by",
        "# tools/production_storage_cli.py schema/backup/restore invocations,",
        "# never by the long-running api Supervisor program.",
        "DEPLOYMENT_ENV=canary",
        f"STRATFORGE_INSTANCE_ID={args.instance_id}",
        # API runtime only. worker-canary and operations-canary override this
        # to `worker` in their own launchers; the long-running HTTP process
        # must never carry migration/backup-owner DSNs or consume the queue.
        "STRATFORGE_DEPLOYMENT_ROLE=api",
        f"STRATFORGE_CONFIG_PROFILE={args.config_profile}",
        "STRATFORGE_REGION=primary",
        "STRATFORGE_BIND_HOST=127.0.0.1",
        "STRATFORGE_ALLOWED_HOSTS=canary.stratforges.com",
        "STRATFORGE_PUBLIC_ORIGIN=https://canary.stratforges.com",
        "STRATFORGE_EDGE_MODE=cloudflare-tunnel",
        "STRATFORGE_TRUSTED_PROXY_IPS=127.0.0.1,::1",
        # STRATFORGE_DATA_ROOT is intentionally NOT set here: it is the
        # Production data-root variable name, read unconditionally by
        # app.runtime_env.data_root()'s cross-environment collision matrix
        # regardless of which environment is actually running. Setting it
        # to the Canary path here would make Canary collide with itself
        # ("Data root canary совпадает с production или вложен в него").
        # Only the Canary-specific variable is set.
        f"STRATFORGE_CANARY_DATA_ROOT={args.canary_data_root}",
        "STRATFORGE_DATABASE_ID=postgres-canary",
        "STRATFORGE_QUEUE_ID=canary-jobs",
        "STRATFORGE_OBJECT_STORAGE_ID=canary-artifacts",
        "STRATFORGE_TELEGRAM_BOT_ID=canary-telegram-disabled-pending-owner-bot",
        "STRATFORGE_COOKIE_NAMESPACE=sf-canary",
        "STRATFORGE_SIGNING_KEY_ID=canary-key-v1",
        # Runtime application signing secret checked by
        # storage_router.signing_key_readiness(); independently generated
        # per environment, never shared with Production, never printed.
        f"STRATFORGE_SIGNING_KEY={signing_key}",
        "STRATFORGE_LOG_NAMESPACE=canary",
        "STRATFORGE_READINESS_MIN_FREE_MB=2048",
        "STRATFORGE_API_MAX_INFLIGHT=24",
        "STRATFORGE_API_BACKLOG=96",
        "STRATFORGE_API_MAX_BODY_BYTES=1048576",
        "STRATFORGE_WORKER_POLL_MS=250",
        "STRATFORGE_WORKER_SHUTDOWN_GRACE_SEC=60",
        f"STRATFORGE_CONNECTOR_RELEASE_CATALOG={args.connector_catalog_path}",
        "STRATFORGE_STORAGE_MODE=postgresql",
        # The Canary app role's name, explicitly declared so
        # storage_router.assert_production_storage_safe() checks the real
        # Canary identity rather than assuming Production's stratforge_app.
        f"STRATFORGE_DATABASE_APP_ROLE={args.canary_app_role}",
        f"STRATFORGE_DATABASE_URL={dsn['app_url']}",
        f"STRATFORGE_ARTIFACT_ROOT={args.canary_artifact_root}",
        "STRATFORGE_DEFAULT_WORKSPACE_QUOTA_BYTES=5368709120",
        "STRATFORGE_MAX_ARTIFACT_BYTES=268435456",
        "STRATFORGE_ARTIFACT_MIN_FREE_BYTES=2147483648",
        "STRATFORGE_DATABASE_CONNECT_TIMEOUT_SEC=5",
        "STRATFORGE_LIVE_TRADING_ALLOWED=0",
        "STRATFORGE_REAL_PAYMENTS_ALLOWED=0",
        "",
        "# Telegram intentionally left disabled (fail-closed): no separate Canary",
        "# bot identity has been provisioned yet. NTA_TELEGRAM_BOT_TOKEN/CHAT_ID/",
        "# WEBHOOK_SECRET stay unset. This is a known, disclosed acceptance gap:",
        "# app.server.py deliberately does not register the telegram_consumer",
        "# readiness probe while no token is configured (see",
        "# deploy/canary/README.md), so this is not a defect to hide or fabricate",
        "# a PASS for.",
        "",
        "# Shared third-party market-data/AI provider credentials (not an identity",
        "# boundary; the isolation guard never compares these).",
        *shared_provider_lines,
        "",
        "# Production reference identifiers (no secrets) for the fail-closed",
        "# isolation guard (app.runtime_env.assert_environment_isolation).",
        *reference_lines,
        "",
    ]
    return "\n".join(lines) + "\n"


def build_canary_maintenance_env(args: argparse.Namespace, dsn: dict[str, str]) -> str:
    """Maintenance-only env: migration/backup owner DSN, mode 0600.

    Sourced only by ad-hoc `tools/production_storage_cli.py schema|backup|
    restore` invocations, never by the long-running api Supervisor program,
    so the least-privilege app DSN is the only database credential an
    HTTP-request-handling process can ever read from its own environment.
    """
    lines = [
        "# Generated by tools/canary_isolation_provision.py. Contains real secrets;",
        "# mode 0600, owner stratforge only. Never commit to Git. Never source",
        "# this file from the api Supervisor program's environment -- only from",
        "# a manually invoked maintenance/migration/backup command.",
        "DEPLOYMENT_ENV=canary",
        f"STRATFORGE_INSTANCE_ID={args.instance_id}",
        f"STRATFORGE_MIGRATION_DATABASE_URL={dsn['migration_url']}",
        f"STRATFORGE_BACKUP_DATABASE_URL={dsn['migration_url']}",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="/home/stratforge/production_data")
    parser.add_argument("--canary-data-root", default=None)
    parser.add_argument("--canary-artifact-root", default=None)
    parser.add_argument("--canary-env-path", default=None)
    parser.add_argument("--canary-maintenance-env-path", default=None)
    parser.add_argument("--lockdown-marker-path", default=None)
    parser.add_argument("--production-env-path", default=None)
    parser.add_argument("--connector-catalog-path", default=None)
    parser.add_argument("--pg-socket", default=None)
    parser.add_argument("--pg-port", type=int, default=5432)
    parser.add_argument("--pg-ca-cert", default=None)
    parser.add_argument("--canary-db-name", default="stratforge_canary")
    parser.add_argument("--canary-app-role", default="stratforge_canary_app")
    parser.add_argument("--canary-migration-role", default="stratforge_canary_migration")
    parser.add_argument("--instance-id", default="stratforge-canary-01")
    parser.add_argument("--config-profile", default="production-canary")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--lockdown-privileges", action="store_true",
        help=(
            "Run ONLY the post-migration privilege lockdown against an "
            "already-provisioned Canary database (revoke Production app "
            "role + PUBLIC, grant the Canary app role). Run this once, "
            "immediately after every `production_storage_cli.py schema "
            "--apply` against the Canary database. Idempotent."
        ),
    )
    args = parser.parse_args()

    base = Path(args.base)
    args.canary_data_root = args.canary_data_root or str(base / "canary" / "var")
    args.canary_artifact_root = args.canary_artifact_root or str(base / "canary" / "artifacts")
    args.canary_env_path = args.canary_env_path or str(base / "config" / "canary.env")
    args.canary_maintenance_env_path = (
        args.canary_maintenance_env_path or str(base / "config" / "canary-maintenance.env")
    )
    args.lockdown_marker_path = (
        args.lockdown_marker_path or str(base / "config" / "canary-privilege-lockdown.ok.json")
    )
    # NOTE: on the real host, `config/production.env` is a historical name
    # for the *Canary*-facing process (port 18765, canary.stratforges.com);
    # the real Production identity (app.stratforges.com, port 18767) lives
    # in `config/production-app.env`. Always source the isolation-guard
    # reference values from the real Production file.
    args.production_env_path = args.production_env_path or str(base / "config" / "production-app.env")
    args.connector_catalog_path = args.connector_catalog_path or str(
        base / "config" / "connector-releases-canary.json",
    )
    args.pg_socket = args.pg_socket or str(base / "run" / "postgresql")
    args.pg_ca_cert = args.pg_ca_cert or str(base / "config" / "postgresql-ca.crt")

    production_env = _read_env_file(Path(args.production_env_path))

    if args.lockdown_privileges:
        try:
            result = lockdown_privileges(args, production_env)
            write_lockdown_marker(Path(args.lockdown_marker_path), result)
        except ProvisionGuardError as exc:
            print(json.dumps({"ok": False, "reason": str(exc)}, indent=2, sort_keys=True))
            return 1
        result["lockdown_marker_path"] = str(args.lockdown_marker_path)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    try:
        _preflight_collision_guard(args, production_env)
    except ProvisionGuardError as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}, indent=2, sort_keys=True))
        return 1

    env_path = Path(args.canary_env_path)
    maintenance_env_path = Path(args.canary_maintenance_env_path)
    if (env_path.exists() or maintenance_env_path.exists()) and not args.force:
        print(json.dumps({
            "ok": False,
            "reason": "canary_env_already_exists",
            "path": str(env_path),
        }, indent=2))
        return 1

    for directory in (args.canary_data_root, args.canary_artifact_root):
        Path(directory).mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)

    catalog_path = Path(args.connector_catalog_path)
    if not catalog_path.exists() or (args.force and _connector_catalog_needs_refresh(catalog_path)):
        catalog_path.write_text(
            json.dumps(default_connector_catalog(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(catalog_path, 0o600)

    dsn = provision_database(args)
    signing_key = secrets.token_urlsafe(48)

    content = _quote_env_lines(build_canary_env(args, dsn, signing_key))
    tmp_path = env_path.with_suffix(".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, env_path)
    os.chmod(env_path, 0o600)

    maintenance_content = _quote_env_lines(build_canary_maintenance_env(args, dsn))
    maintenance_tmp_path = maintenance_env_path.with_suffix(".tmp")
    maintenance_tmp_path.write_text(maintenance_content, encoding="utf-8")
    os.chmod(maintenance_tmp_path, 0o600)
    os.replace(maintenance_tmp_path, maintenance_env_path)
    os.chmod(maintenance_env_path, 0o600)

    print(json.dumps({
        "ok": True,
        "canary_env_path": str(env_path),
        "canary_maintenance_env_path": str(maintenance_env_path),
        "canary_data_root": args.canary_data_root,
        "canary_artifact_root": args.canary_artifact_root,
        "canary_database_name": args.canary_db_name,
        "canary_app_role": args.canary_app_role,
        "canary_migration_role": args.canary_migration_role,
        "telegram_status": "disabled_pending_owner_bot_provisioning",
        "privilege_lockdown_pending": True,
        "privilege_lockdown_note": (
            "Run --lockdown-privileges immediately after applying migrations "
            "to this database, before serving real traffic."
        ),
        "secrets_redacted": True,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
