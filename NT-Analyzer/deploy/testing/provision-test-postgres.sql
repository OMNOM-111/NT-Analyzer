-- StratForge — isolated PostgreSQL acceptance: provisioning.
--
-- Run this ONCE as a PostgreSQL superuser (e.g. `postgres`) against a
-- throwaway, NON-PRODUCTION PostgreSQL instance. It creates an isolated
-- acceptance database and the two roles the StratForge storage layer expects:
--
--   * a migration/admin role that OWNS the schema and applies migrations
--     (STRATFORGE_TEST_POSTGRES_ADMIN_URL), and
--   * the unprivileged application role `stratforge_app`, which row-level
--     security is enforced against (STRATFORGE_TEST_POSTGRES_URL).
--
-- The application role is NOSUPERUSER / NOBYPASSRLS on purpose: the acceptance
-- suite proves that a workspace-scoped session cannot read another workspace's
-- rows. Replace the two placeholder passwords before running. This file
-- contains no secret values and must never point at a Production database.

\set admin_pw `echo "${STRATFORGE_TEST_ADMIN_PW:-change-me-admin}"`
\set app_pw   `echo "${STRATFORGE_TEST_APP_PW:-change-me-app}"`

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'stratforge_test_admin') THEN
    CREATE ROLE stratforge_test_admin LOGIN CREATEDB;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'stratforge_app') THEN
    -- NOBYPASSRLS is critical: the app role must obey row level security.
    CREATE ROLE stratforge_app LOGIN NOSUPERUSER NOCREATEDB NOBYPASSRLS;
  END IF;
END
$$;

ALTER ROLE stratforge_test_admin PASSWORD :'admin_pw';
ALTER ROLE stratforge_app        PASSWORD :'app_pw';

-- Fresh, isolated acceptance database owned by the migration role.
DROP DATABASE IF EXISTS stratforge_acceptance;
CREATE DATABASE stratforge_acceptance OWNER stratforge_test_admin;

\connect stratforge_acceptance

-- The app role needs schema visibility; migrations grant per-table DML.
GRANT USAGE ON SCHEMA public TO stratforge_app;
ALTER DEFAULT PRIVILEGES FOR ROLE stratforge_test_admin IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO stratforge_app;
