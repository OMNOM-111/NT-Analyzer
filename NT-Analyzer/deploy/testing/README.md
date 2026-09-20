# Isolated PostgreSQL acceptance

This kit runs the StratForge storage acceptance suite against a **throwaway,
non-Production PostgreSQL** instance. It exercises the authoritative-storage
invariants that the local SQLite development store cannot prove:

- the additive migration set applies cleanly `1..N` with a stable checksum and
  no pending migrations (`sf_migration_runs`);
- **row-level security** isolates one workspace from another (a workspace-scoped
  app session can never read another workspace's rows);
- **UUID identity backfill** (`sf_users.user_uuid`, `sf_auth_identities`);
- **release-center tables** (`sf_release_*`, blue-green deploy steps);
- **NinjaTrader resource leases** and the production worker queue;
- document-specification tables (`sf_documents`, `sf_document_revisions`,
  migration `0011`, added in Phase 11).

The acceptance logic already lives in the test suite; this folder only provides
the provisioning, environment, runner and backup/restore tooling around it.

## Status on this checkout

**BLOCKED — EXTERNAL TEST DATABASE REQUIRED.** No PostgreSQL server and no
`STRATFORGE_TEST_POSTGRES_ADMIN_URL` / `STRATFORGE_TEST_POSTGRES_URL` DSNs are
available in this environment, so the PostgreSQL-dependent suite is skipped
(`pytest.mark.skipif`). Everything needed to run it is prepared here; supply an
isolated test database to execute it. `psycopg` 3.x is already installed.

## Roles

Two roles model the production separation of duties:

| DSN env var | Role | Purpose |
| --- | --- | --- |
| `STRATFORGE_TEST_POSTGRES_ADMIN_URL` | `stratforge_test_admin` | owns the schema, applies migrations, truncates between tests |
| `STRATFORGE_TEST_POSTGRES_URL` | `stratforge_app` | unprivileged, `NOBYPASSRLS`; RLS is enforced against it |

`stratforge_app` is deliberately `NOSUPERUSER NOBYPASSRLS` so the isolation
tests are meaningful. Migration `0001` aborts if the `stratforge_app` role is
missing.

## Procedure

1. Provision (once, as a PostgreSQL superuser against a disposable instance):

   ```bash
   STRATFORGE_TEST_ADMIN_PW=... STRATFORGE_TEST_APP_PW=... \
     psql "postgresql://postgres@127.0.0.1:5432/postgres" \
       -v ON_ERROR_STOP=1 -f deploy/testing/provision-test-postgres.sql
   ```

2. Configure DSNs: copy `postgres-acceptance.env.example` to
   `postgres-acceptance.env`, fill in the host/port and the two passwords, then
   `chmod 600 postgres-acceptance.env`.

3. Run the acceptance suite:

   - Linux/macOS: `deploy/testing/run-postgres-acceptance.sh`
   - Windows: `deploy/testing/run-postgres-acceptance.ps1`

   The runner applies migrations (`MigrationRunner(admin_url).apply()`) and then
   runs `test_stage8_postgresql`, `test_production_storage` and
   `test_production_workers`.

4. Optional disaster-recovery drill (backup + restore round-trip):

   ```bash
   deploy/testing/backup-restore-test-postgres.sh
   ```

## Safety

- These DSNs must never point at a Production database — the suite truncates
  every `sf_*` table between tests.
- Production itself hard-rejects the local auth bypass and the test DSNs; this
  kit only targets an isolated acceptance instance.
- No secrets are stored in this folder; `.env.example` contains placeholders.

## Agent World acceptance (migration 0023) — no longer blocked

`tests/test_agent_world_postgres.py` is **69 cases from 27 test functions**.
Exactly one, `test_constructor_does_no_database_io_ddl_or_fallback`, needs no
server, which is why an unconfigured run reports `1 passed, 68 skipped` and a
configured run reports `69 passed`. The suite size never changed.

It uses its own gate, separate from the four Stage 8 suites above:

    STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ALLOW=1
    STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ADMIN_URL=...
    STRATFORGE_TEST_AGENT_WORLD_POSTGRES_URL=...
    STRATFORGE_ALLOW_INSECURE_LOCAL_POSTGRES=1

and refuses any target that is not a disposable `aw_disposable_*` database on
127.0.0.1, checking that the application role is neither SUPERUSER nor
BYPASSRLS. Three cases open the adapter with `production=True`, so the cluster
must serve TLS.

`provision-disposable-agent-world-postgres.py` brings up such a cluster inside a
directory you choose — its own data directory, a free loopback port, a
self-signed certificate for that cluster only, generated passwords written to
`<workdir>/acceptance.env`, and nothing else. It registers no service, needs no
elevation, and changes no PATH, firewall rule or existing PostgreSQL install.
`--teardown` stops it and deletes the data directory and the env file.

Obtain the binaries as the official PostgreSQL Windows **zip archive** (no
installer) and extract it so `<workdir>/pgsql/bin/initdb.exe` exists. Note when
recording evidence: that archive is served without a published checksum or
signature file, and the executables inside it are not Authenticode-signed, so
authenticity rests on the HTTPS origin plus the version and structure you can
verify locally.

Never commit `acceptance.env`, `pgdata/`, `server.key` or `server.crt`.
