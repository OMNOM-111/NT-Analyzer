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
