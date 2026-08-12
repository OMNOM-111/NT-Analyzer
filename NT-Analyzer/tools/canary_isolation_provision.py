#!/usr/bin/env python3
"""Provision a fully isolated Canary contour on a Supervisor-managed host.

Real topology on the current production host: no systemd, a single
supervisord instance manages `api` (Production) / `api-canary` (Canary) /
`worker` / `worker-canary` / `operations` / `operations-canary` /
`telegram` programs. This tool creates the Canary-only PostgreSQL role and
database, a dedicated data/artifact root, and a Canary environment file with
identities that differ from Production on every field checked by
`app.runtime_env.assert_environment_isolation`.

Idempotent by default: refuses to overwrite an existing Canary environment
file unless --force is passed. Never prints a secret value; only paths,
booleans, ids and non-secret runtime fields.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import urllib.parse
from pathlib import Path

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
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


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


def provision_database(args: argparse.Namespace) -> dict[str, str]:
    """Create the Canary migration+app roles and database. Returns DSNs.

    Passwords are generated in-process and only ever written to the
    protected Canary env file (0600); they are never printed or logged.
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

    ca_cert = args.pg_ca_cert
    quoted_migration_pw = urllib.parse.quote(migration_password, safe="")
    quoted_app_pw = urllib.parse.quote(app_password, safe="")
    common = f"@localhost:{port}/{db_name}?sslmode=verify-full&sslrootcert={ca_cert}"
    return {
        "migration_url": f"postgresql://{migration_role}:{quoted_migration_pw}{common}",
        "app_url": f"postgresql://{app_role}:{quoted_app_pw}{common}",
    }


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
        "DEPLOYMENT_ENV=canary",
        f"STRATFORGE_INSTANCE_ID={args.instance_id}",
        # all-in-one: Canary has no separate worker/operations Supervisor
        # program (app.production_workers and app.observability
        # --maintenance are hard-gated to DEPLOYMENT_ENV=production and
        # would only restart-loop). The single api process starts its own
        # in-process worker/telegram/orchestrator loops, exactly like
        # Development, whenever environment != production.
        "STRATFORGE_DEPLOYMENT_ROLE=all-in-one",
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
        f"STRATFORGE_DATABASE_URL={dsn['app_url']}",
        f"STRATFORGE_BACKUP_DATABASE_URL={dsn['migration_url']}",
        f"STRATFORGE_MIGRATION_DATABASE_URL={dsn['migration_url']}",
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
        "# WEBHOOK_SECRET stay unset. This is a known acceptance gap, not a defect.",
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="/home/stratforge/production_data")
    parser.add_argument("--canary-data-root", default=None)
    parser.add_argument("--canary-artifact-root", default=None)
    parser.add_argument("--canary-env-path", default=None)
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
    args = parser.parse_args()

    base = Path(args.base)
    args.canary_data_root = args.canary_data_root or str(base / "canary" / "var")
    args.canary_artifact_root = args.canary_artifact_root or str(base / "canary" / "artifacts")
    args.canary_env_path = args.canary_env_path or str(base / "config" / "canary.env")
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

    env_path = Path(args.canary_env_path)
    if env_path.exists() and not args.force:
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
    if not catalog_path.exists():
        catalog_path.write_text(
            json.dumps({"schema_version": 1, "channel": "beta", "installations": []}, indent=2) + "\n",
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

    print(json.dumps({
        "ok": True,
        "canary_env_path": str(env_path),
        "canary_data_root": args.canary_data_root,
        "canary_artifact_root": args.canary_artifact_root,
        "canary_database_name": args.canary_db_name,
        "canary_app_role": args.canary_app_role,
        "canary_migration_role": args.canary_migration_role,
        "telegram_status": "disabled_pending_owner_bot_provisioning",
        "secrets_redacted": True,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
