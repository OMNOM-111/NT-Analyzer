"""Bring up a throwaway, TLS-enabled PostgreSQL for the Agent World suite.

`tests/test_agent_world_postgres.py` refuses anything but a disposable loopback
database and checks that the application role is neither SUPERUSER nor
BYPASSRLS, so isolation is proven with runtime-like rights. Three of its cases
open the adapter with `production=True`, which requires TLS — hence the
self-signed certificate below. It exists only for this throwaway cluster.

What this deliberately does not do: register a Windows service, ask for
elevation, change PATH or firewall rules, touch an existing PostgreSQL
installation, or contact any owner, Canary or Production database. Everything
lives under one directory you choose and is removed by `--teardown`.

Passwords are generated per run and written only to `<workdir>/acceptance.env`.
That file is git-ignored and must never be committed; nothing here prints a
secret.

Usage
-----
    # binaries: the official PostgreSQL Windows zip (no installer), extracted so
    # that <workdir>/pgsql/bin/initdb.exe exists.
    python deploy/testing/provision-disposable-agent-world-postgres.py \
        --workdir C:\\path\\to\\scratch\\pgtest
    # then, from NT-Analyzer/, with those variables exported:
    python -c "import json,sys;from app.production_storage.core import MigrationRunner;\
print(json.dumps(MigrationRunner(sys.argv[1]).apply()))" "$ADMIN_URL"
    python -m pytest tests/test_agent_world_postgres.py -q
    python deploy/testing/provision-disposable-agent-world-postgres.py \
        --workdir ... --teardown
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import socket
import string
import subprocess
import sys
from pathlib import Path

ENV_NAME = "acceptance.env"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(28))


def run(args, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


def teardown(workdir: Path) -> int:
    data = workdir / "pgdata"
    if data.exists():
        subprocess.run([str(workdir / "pgsql" / "bin" / "pg_ctl.exe"), "-D", str(data),
                        "-m", "immediate", "-w", "stop"],
                       capture_output=True, text=True, errors="replace")
        shutil.rmtree(data, ignore_errors=True)
    for name in (ENV_NAME, ".superpw", "pg.log"):
        (workdir / name).unlink(missing_ok=True)
    print("torn down:", workdir)
    return 0


def certificate(data: Path) -> bool:
    """Self-signed, loopback-only, short lived. Only this cluster ever sees it."""
    if not shutil.which("openssl"):
        print("openssl not found; the three production=True TLS cases will fail", file=sys.stderr)
        return False
    subprocess.run(["openssl", "req", "-new", "-x509", "-days", "2", "-nodes",
                    "-subj", "/CN=127.0.0.1", "-keyout", str(data / "server.key"),
                    "-out", str(data / "server.crt")],
                   check=True, capture_output=True, text=True, errors="replace",
                   env=dict(os.environ, MSYS_NO_PATHCONV="1"))
    (data / "server.key").chmod(0o600)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", required=True, type=Path)
    parser.add_argument("--teardown", action="store_true")
    args = parser.parse_args()
    workdir: Path = args.workdir.resolve()

    if args.teardown:
        return teardown(workdir)

    binaries = workdir / "pgsql" / "bin"
    if not (binaries / "initdb.exe").is_file():
        print(f"expected the extracted PostgreSQL binaries at {binaries}", file=sys.stderr)
        return 2
    data = workdir / "pgdata"
    if data.exists():
        print("a cluster is already present; run with --teardown first", file=sys.stderr)
        return 2

    superpw, pwfile = password(), workdir / ".superpw"
    pwfile.write_text(superpw, encoding="utf-8")
    run([str(binaries / "initdb.exe"), "-D", str(data), "-U", "pgboot",
         "--pwfile", str(pwfile), "-E", "UTF8", "--locale=C",
         "--auth-local=scram-sha-256", "--auth-host=scram-sha-256"])

    port, tls = free_port(), certificate(data)
    (data / "postgresql.auto.conf").write_text(
        f"listen_addresses = '127.0.0.1'\nport = {port}\n"
        "unix_socket_directories = ''\nfsync = off\nfull_page_writes = off\n"
        "max_connections = 40\n"
        + ("ssl = on\nssl_cert_file = 'server.crt'\nssl_key_file = 'server.key'\n" if tls else ""),
        encoding="utf-8")
    # A detached postgres child may inherit Python's capture pipes on Windows,
    # leaving communicate() waiting forever after pg_ctl has already exited.
    # The server has its own -l log; no pipe needs to survive this launcher.
    subprocess.run([str(binaries / "pg_ctl.exe"), "-D", str(data), "-l", str(workdir / "pg.log"),
                    "-w", "-o", f"-p {port}", "start"], check=True,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=60,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    database = "aw_disposable_" + secrets.token_hex(6)
    admin_pw, app_pw = password(), password()
    import psycopg
    from psycopg import sql

    def psql(dbname: str, statement) -> None:
        # CREATE ROLE cannot use bind parameters. sql.Literal handles quoting
        # in-process without putting either password into a process argv.
        with psycopg.connect(host="127.0.0.1", port=port, user="pgboot", password=superpw,
                dbname=dbname, sslmode="require" if tls else "disable", autocommit=True) as connection:
            connection.execute(statement)

    psql("postgres", sql.SQL("CREATE ROLE aw_test_admin LOGIN CREATEDB PASSWORD {}").format(sql.Literal(admin_pw)))
    # NOBYPASSRLS is the point of the exercise: the suite proves that a
    # workspace-scoped session cannot read another workspace's rows.
    psql("postgres", sql.SQL("CREATE ROLE stratforge_app LOGIN NOSUPERUSER NOCREATEDB NOBYPASSRLS PASSWORD {}").format(sql.Literal(app_pw)))
    psql("postgres", f'CREATE DATABASE "{database}" OWNER aw_test_admin')
    psql("postgres", f'GRANT CONNECT ON DATABASE "{database}" TO stratforge_app')
    psql(database, "GRANT USAGE, CREATE ON SCHEMA public TO aw_test_admin")
    psql(database, "GRANT USAGE ON SCHEMA public TO stratforge_app")
    pwfile.unlink(missing_ok=True)

    suffix = "?sslmode=require" if tls else ""
    (workdir / ENV_NAME).write_text(
        "STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ALLOW=1\n"
        f"STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ADMIN_URL=postgresql://aw_test_admin:{admin_pw}@127.0.0.1:{port}/{database}{suffix}\n"
        f"STRATFORGE_TEST_AGENT_WORLD_POSTGRES_URL=postgresql://stratforge_app:{app_pw}@127.0.0.1:{port}/{database}{suffix}\n"
        "STRATFORGE_ALLOW_INSECURE_LOCAL_POSTGRES=1\n",
        encoding="utf-8")
    print(f"ready: database={database} port={port} tls={'on' if tls else 'off'}")
    print(f"credentials written to {workdir / ENV_NAME} — never print or commit this file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
