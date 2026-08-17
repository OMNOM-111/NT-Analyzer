-- Phase 5: environment registry.
--
-- The Environment Switcher could only describe an environment by reaching out
-- and asking it, right now, over HTTP. That gave two bad answers:
--
--   * LOCAL is behind NAT. A server-side probe can never reach a development
--     machine, so LOCAL was permanently "unknown" even while it was running.
--   * An environment that is merely unreachable at this instant reported
--     "unknown" for everything -- version, commit, artifact -- discarding
--     facts that were true a minute ago and are still the best information
--     available.
--
-- So environments publish instead of being polled: each one pushes an
-- authenticated heartbeat carrying its own runtime identity, and this table
-- keeps the last one. Reachability then becomes a property derived from
-- last_seen_at, separate from the metadata, and an offline environment shows
-- its last-known build with an explicit "as of" rather than a row of dashes.
--
-- Global operational state, not user-owned: the policy is sf_scope_global()
-- only, matching the release-center tables in 0009.

BEGIN;

-- This migration inserts nothing, so it would apply without a declared scope --
-- 0006 has the same policy shape and proved that. The scope is declared anyway
-- because the moment anyone adds a backfill here, FORCE ROW LEVEL SECURITY
-- applies to the table owner too and the migration is refused by its own policy
-- with SQLSTATE 42501, which is exactly how 0014 failed. SET LOCAL, so it lasts
-- this transaction only and grants the runtime role nothing.
SET LOCAL stratforge.service_scope = 'global';

CREATE TABLE IF NOT EXISTS sf_environment_registry (
  -- One row per environment. 'development' is the owner's LOCAL machine.
  environment TEXT PRIMARY KEY
    CHECK (environment IN ('development', 'canary', 'production')),

  -- Last-known runtime identity, as self-reported by that environment. These
  -- are retained when it goes quiet: that is the entire point of the table.
  app_version TEXT NOT NULL DEFAULT '' CHECK (length(app_version) <= 64),
  git_commit_sha TEXT NOT NULL DEFAULT '' CHECK (length(git_commit_sha) <= 64),
  build_id TEXT NOT NULL DEFAULT '' CHECK (length(build_id) <= 128),
  artifact_sha256 TEXT NOT NULL DEFAULT ''
    CHECK (artifact_sha256 = '' OR artifact_sha256 ~ '^[0-9a-fA-F]{64}$'),
  release_channel TEXT NOT NULL DEFAULT '' CHECK (length(release_channel) <= 32),
  schema_version INTEGER NOT NULL DEFAULT 0 CHECK (schema_version >= 0),
  readiness TEXT NOT NULL DEFAULT ''
    CHECK (readiness IN ('', 'ready', 'degraded', 'not_ready')),

  -- Reachability lives here, derived from time, never mixed into the metadata
  -- above. first_seen_at answers "has this environment ever reported", which is
  -- a different question from "is it up now".
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  heartbeat_count BIGINT NOT NULL DEFAULT 0 CHECK (heartbeat_count >= 0),

  -- Free-form, size-capped extras the switcher renders verbatim. Never a place
  -- for secrets: everything written here is shown to any operator who can read
  -- the switcher.
  details JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(details) = 'object' AND pg_column_size(details) <= 4096),

  CHECK (last_seen_at >= first_seen_at)
);

CREATE INDEX IF NOT EXISTS sf_environment_registry_seen_idx
  ON sf_environment_registry(last_seen_at DESC);

ALTER TABLE sf_environment_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_environment_registry FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_environment_registry_global ON sf_environment_registry;
CREATE POLICY sf_environment_registry_global ON sf_environment_registry
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

GRANT SELECT, INSERT, UPDATE, DELETE ON sf_environment_registry TO stratforge_app;

COMMIT;
