-- StratForge authoritative Production storage, schema version 1.
-- The deployment bootstrap must create a non-superuser LOGIN role named
-- stratforge_app before this migration is applied by the migration role.

DO $stratforge$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'stratforge_app') THEN
    RAISE EXCEPTION 'required database role stratforge_app does not exist';
  END IF;
END
$stratforge$;

CREATE TABLE IF NOT EXISTS sf_repository_documents (
  repository TEXT PRIMARY KEY CHECK (repository IN ('auth','workspaces','entitlements','connectors')),
  revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS sf_users (
  user_id BIGINT PRIMARY KEY CHECK (user_id > 0),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('pending','active','blocked','revoked','deleted')),
  is_owner BOOLEAN NOT NULL DEFAULT FALSE,
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE UNIQUE INDEX IF NOT EXISTS sf_one_owner_idx ON sf_users(is_owner) WHERE is_owner;

CREATE TABLE IF NOT EXISTS sf_auth_challenges (
  challenge_id TEXT PRIMARY KEY CHECK (length(challenge_id) BETWEEN 8 AND 160),
  user_id BIGINT REFERENCES sf_users(user_id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ,
  consumed BOOLEAN NOT NULL DEFAULT FALSE,
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS sf_auth_sessions (
  session_id TEXT PRIMARY KEY CHECK (length(session_id) BETWEEN 8 AND 160),
  user_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  revoked BOOLEAN NOT NULL DEFAULT FALSE,
  expires_at TIMESTAMPTZ,
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS sf_auth_sessions_user_active_idx
  ON sf_auth_sessions(user_id, revoked, expires_at);

CREATE TABLE IF NOT EXISTS sf_workspaces (
  workspace_id TEXT PRIMARY KEY CHECK (workspace_id ~ '^ws_[A-Za-z0-9_-]{8,80}$'),
  owner_user_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE RESTRICT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','archived','deleted')),
  kind TEXT NOT NULL DEFAULT 'personal' CHECK (length(kind) BETWEEN 1 AND 64),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS sf_workspace_memberships (
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  user_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('owner','admin','operator','viewer','developer')),
  revoked_at TIMESTAMPTZ,
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (workspace_id, user_id)
);

CREATE INDEX IF NOT EXISTS sf_workspace_memberships_user_idx
  ON sf_workspace_memberships(user_id, revoked_at);

CREATE TABLE IF NOT EXISTS sf_active_workspaces (
  user_id BIGINT PRIMARY KEY REFERENCES sf_users(user_id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS sf_workspace_ledgers (
  workspace_id TEXT PRIMARY KEY REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS sf_connections (
  connection_id TEXT PRIMARY KEY CHECK (length(connection_id) BETWEEN 6 AND 160),
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  user_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','online','offline','revoked','failed')),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS sf_connections_workspace_idx
  ON sf_connections(workspace_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS sf_entitlements (
  entitlement_id TEXT PRIMARY KEY CHECK (length(entitlement_id) BETWEEN 3 AND 160),
  user_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE CASCADE,
  workspace_id TEXT REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  plan_id TEXT NOT NULL CHECK (length(plan_id) BETWEEN 1 AND 80),
  status TEXT NOT NULL CHECK (status IN ('promo_grant','trial','active','pending','expired','revoked','cancelled')),
  expires_at TIMESTAMPTZ,
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS sf_entitlements_user_idx
  ON sf_entitlements(user_id, status, expires_at);
CREATE INDEX IF NOT EXISTS sf_entitlements_workspace_idx
  ON sf_entitlements(workspace_id, status) WHERE workspace_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS sf_connector_installations (
  installation_id TEXT PRIMARY KEY CHECK (length(installation_id) BETWEEN 6 AND 160),
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  user_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('pending','online','offline','revoked','blocked','failed')),
  public_key_fingerprint TEXT NOT NULL CHECK (length(public_key_fingerprint) BETWEEN 16 AND 160),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS sf_connector_installations_workspace_idx
  ON sf_connector_installations(workspace_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS sf_connector_sessions (
  session_id TEXT PRIMARY KEY CHECK (length(session_id) BETWEEN 8 AND 160),
  installation_id TEXT NOT NULL REFERENCES sf_connector_installations(installation_id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS sf_jobs (
  job_id TEXT PRIMARY KEY CHECK (length(job_id) BETWEEN 6 AND 160),
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  user_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE RESTRICT,
  kind TEXT NOT NULL CHECK (length(kind) BETWEEN 1 AND 80),
  status TEXT NOT NULL CHECK (status IN ('queued','running','completed','failed','cancelled','dead_letter','review')),
  idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 160),
  revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (workspace_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS sf_jobs_workspace_status_idx
  ON sf_jobs(workspace_id, status, created_at);

CREATE TABLE IF NOT EXISTS sf_commands (
  command_id TEXT PRIMARY KEY CHECK (length(command_id) BETWEEN 6 AND 160),
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  installation_id TEXT REFERENCES sf_connector_installations(installation_id) ON DELETE RESTRICT,
  user_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE RESTRICT,
  command_type TEXT NOT NULL CHECK (length(command_type) BETWEEN 1 AND 100),
  status TEXT NOT NULL CHECK (status IN ('queued','leased','completed','failed','rejected','expired','cancelled','review')),
  dangerous BOOLEAN NOT NULL DEFAULT FALSE,
  idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 160),
  revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (workspace_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS sf_commands_delivery_idx
  ON sf_commands(workspace_id, installation_id, status, created_at);

CREATE TABLE IF NOT EXISTS sf_audit_events (
  audit_id BIGSERIAL PRIMARY KEY,
  event_id TEXT NOT NULL UNIQUE CHECK (length(event_id) BETWEEN 8 AND 160),
  workspace_id TEXT REFERENCES sf_workspaces(workspace_id) ON DELETE SET NULL,
  user_id BIGINT REFERENCES sf_users(user_id) ON DELETE SET NULL,
  source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 100),
  event_type TEXT NOT NULL CHECK (length(event_type) BETWEEN 1 AND 120),
  payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  retention_until TIMESTAMPTZ NOT NULL DEFAULT (clock_timestamp() + INTERVAL '730 days')
);

CREATE INDEX IF NOT EXISTS sf_audit_events_workspace_time_idx
  ON sf_audit_events(workspace_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS sf_audit_events_retention_idx
  ON sf_audit_events(retention_until);

CREATE TABLE IF NOT EXISTS sf_storage_quotas (
  workspace_id TEXT PRIMARY KEY REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  quota_bytes BIGINT NOT NULL CHECK (quota_bytes BETWEEN 1048576 AND 10995116277760),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS sf_artifacts (
  artifact_id TEXT PRIMARY KEY CHECK (artifact_id ~ '^art_[0-9a-f]{32}$'),
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  user_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE RESTRICT,
  object_key TEXT NOT NULL UNIQUE,
  logical_name TEXT NOT NULL CHECK (length(logical_name) BETWEEN 1 AND 160),
  media_type TEXT NOT NULL CHECK (length(media_type) BETWEEN 1 AND 160),
  sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes BIGINT NOT NULL CHECK (size_bytes BETWEEN 0 AND 10737418240),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','quarantined','deleted')),
  retention_until TIMESTAMPTZ,
  document JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  deleted_at TIMESTAMPTZ,
  CHECK (object_key ~ '^[A-Za-z0-9._/-]+$'),
  CHECK (left(object_key, 1) <> '/'),
  CHECK (position(':' in object_key) = 0),
  CHECK (position('..' in object_key) = 0),
  CHECK (split_part(object_key, '/', 1) = workspace_id)
);

CREATE INDEX IF NOT EXISTS sf_artifacts_workspace_status_idx
  ON sf_artifacts(workspace_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS sf_artifacts_retention_idx
  ON sf_artifacts(retention_until) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS sf_migration_runs (
  migration_run_id TEXT PRIMARY KEY CHECK (length(migration_run_id) BETWEEN 8 AND 160),
  owner_user_id BIGINT NOT NULL CHECK (owner_user_id > 0),
  selection JSONB NOT NULL CHECK (jsonb_typeof(selection) = 'array'),
  plan_sha256 TEXT NOT NULL CHECK (plan_sha256 ~ '^[0-9a-f]{64}$'),
  source_sha256 TEXT NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
  status TEXT NOT NULL CHECK (status IN ('planned','applied','failed','rolled_back')),
  counts JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(counts) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  applied_at TIMESTAMPTZ
);

CREATE OR REPLACE FUNCTION sf_scope_global() RETURNS BOOLEAN
LANGUAGE sql STABLE AS $$
  SELECT current_setting('stratforge.service_scope', true) = 'global'
$$;

CREATE OR REPLACE FUNCTION sf_scope_user() RETURNS BIGINT
LANGUAGE sql STABLE AS $$
  SELECT CASE
    WHEN current_setting('stratforge.user_id', true) ~ '^[1-9][0-9]*$'
      THEN current_setting('stratforge.user_id', true)::BIGINT
    ELSE NULL
  END
$$;

CREATE OR REPLACE FUNCTION sf_scope_workspace() RETURNS TEXT
LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('stratforge.workspace_id', true), '')
$$;

REVOKE ALL ON FUNCTION sf_scope_global() FROM PUBLIC;
REVOKE ALL ON FUNCTION sf_scope_user() FROM PUBLIC;
REVOKE ALL ON FUNCTION sf_scope_workspace() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sf_scope_global(), sf_scope_user(), sf_scope_workspace() TO stratforge_app;

ALTER TABLE sf_repository_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_repository_documents FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_repository_documents_global ON sf_repository_documents
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

ALTER TABLE sf_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_users FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_users_scope ON sf_users
  USING (sf_scope_global() OR user_id = sf_scope_user())
  WITH CHECK (sf_scope_global() OR user_id = sf_scope_user());

ALTER TABLE sf_auth_challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_auth_challenges FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_auth_challenges_scope ON sf_auth_challenges
  USING (sf_scope_global() OR user_id = sf_scope_user())
  WITH CHECK (sf_scope_global() OR user_id = sf_scope_user());

ALTER TABLE sf_auth_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_auth_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_auth_sessions_scope ON sf_auth_sessions
  USING (sf_scope_global() OR user_id = sf_scope_user())
  WITH CHECK (sf_scope_global() OR user_id = sf_scope_user());

ALTER TABLE sf_workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_workspaces FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_workspaces_scope ON sf_workspaces
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_workspace_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_workspace_memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_workspace_memberships_scope ON sf_workspace_memberships
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace() OR user_id = sf_scope_user())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_active_workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_active_workspaces FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_active_workspaces_scope ON sf_active_workspaces
  USING (sf_scope_global() OR user_id = sf_scope_user())
  WITH CHECK (sf_scope_global() OR user_id = sf_scope_user());

ALTER TABLE sf_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_connections FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_connections_scope ON sf_connections
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_workspace_ledgers ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_workspace_ledgers FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_workspace_ledgers_scope ON sf_workspace_ledgers
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_entitlements ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_entitlements FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_entitlements_scope ON sf_entitlements
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace() OR user_id = sf_scope_user())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace() OR user_id = sf_scope_user());

ALTER TABLE sf_connector_installations ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_connector_installations FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_connector_installations_scope ON sf_connector_installations
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_connector_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_connector_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_connector_sessions_scope ON sf_connector_sessions
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_jobs_scope ON sf_jobs
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_commands FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_commands_scope ON sf_commands
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_audit_events FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_audit_events_scope ON sf_audit_events
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace() OR user_id = sf_scope_user())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace() OR user_id = sf_scope_user());

ALTER TABLE sf_storage_quotas ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_storage_quotas FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_storage_quotas_scope ON sf_storage_quotas
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_artifacts FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_artifacts_scope ON sf_artifacts
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_migration_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_migration_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_migration_runs_global ON sf_migration_runs
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

GRANT SELECT ON sf_schema_migrations TO stratforge_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON
  sf_repository_documents, sf_users, sf_auth_challenges, sf_auth_sessions,
  sf_workspaces, sf_workspace_memberships, sf_active_workspaces, sf_workspace_ledgers, sf_connections,
  sf_entitlements, sf_connector_installations, sf_connector_sessions,
  sf_jobs, sf_commands, sf_audit_events, sf_storage_quotas, sf_artifacts,
  sf_migration_runs
TO stratforge_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO stratforge_app;
