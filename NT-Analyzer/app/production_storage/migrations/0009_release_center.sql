-- Phase 8: Release Center — immutable artifact promotion control plane.
--
-- Additive expand-only migration. Creates new, initially empty tables for the
-- release candidate/artifact state machine, Canary/Production deployment records,
-- checks, approvals, rollbacks, notifications and an append-only event log. No
-- destructive contract, no DROP, no data migration. The Release Center is a
-- global administrative control plane, so every table is global-scope only under
-- row level security (never workspace/user readable). Signing keys, tokens and
-- raw credentials are never stored here — only public build identity, checksums,
-- signature status and redacted evidence.

CREATE TABLE IF NOT EXISTS sf_release_artifacts (
  artifact_id UUID PRIMARY KEY,
  app_version TEXT NOT NULL CHECK (length(app_version) BETWEEN 1 AND 80),
  release_channel TEXT NOT NULL CHECK (release_channel IN ('dev', 'beta', 'stable')),
  build_id TEXT NOT NULL CHECK (length(build_id) BETWEEN 1 AND 200),
  git_commit_sha TEXT NOT NULL CHECK (length(git_commit_sha) BETWEEN 7 AND 64),
  artifact_sha256 TEXT NOT NULL CHECK (length(artifact_sha256) BETWEEN 32 AND 128),
  manifest_sha256 TEXT NOT NULL CHECK (length(manifest_sha256) BETWEEN 32 AND 128),
  signature_algorithm TEXT NOT NULL DEFAULT '' CHECK (length(signature_algorithm) <= 64),
  signature_status TEXT NOT NULL DEFAULT 'unverified'
    CHECK (signature_status IN ('unverified', 'verified', 'invalid', 'missing')),
  trust_tier TEXT NOT NULL DEFAULT 'development'
    CHECK (trust_tier IN ('development', 'production')),
  built_at_utc TIMESTAMPTZ,
  dirty BOOLEAN NOT NULL DEFAULT FALSE,
  -- A storage reference/URI only; never a credentialed URL.
  storage_uri TEXT NOT NULL DEFAULT '' CHECK (length(storage_uri) <= 500),
  file_count INTEGER NOT NULL DEFAULT 0 CHECK (file_count >= 0),
  migration_count INTEGER NOT NULL DEFAULT 0 CHECK (migration_count >= 0),
  -- Immutable once built: a second build for the same candidate must never
  -- overwrite the frozen artifact identity.
  immutable BOOLEAN NOT NULL DEFAULT TRUE,
  document JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  -- The exact-artifact identity fingerprint used to gate Production promotion.
  CONSTRAINT sf_release_artifacts_identity_unique
    UNIQUE (artifact_sha256, manifest_sha256, git_commit_sha, build_id)
);

CREATE TABLE IF NOT EXISTS sf_release_candidates (
  candidate_id UUID PRIMARY KEY,
  app_version TEXT NOT NULL CHECK (length(app_version) BETWEEN 1 AND 80),
  release_channel TEXT NOT NULL CHECK (release_channel IN ('dev', 'beta', 'stable')),
  git_commit_sha TEXT NOT NULL CHECK (length(git_commit_sha) BETWEEN 7 AND 64),
  state TEXT NOT NULL DEFAULT 'draft'
    CHECK (state IN (
      'draft', 'building', 'built', 'signed',
      'canary_deploying', 'canary_checking', 'canary_passed',
      'approved_for_production', 'production_scheduled',
      'production_deploying', 'production_live',
      'build_failed', 'canary_failed', 'production_failed',
      'rolled_back', 'superseded', 'cancelled'
    )),
  artifact_id UUID REFERENCES sf_release_artifacts(artifact_id) ON DELETE SET NULL,
  created_by_user_id UUID REFERENCES sf_users(user_uuid) ON DELETE SET NULL,
  created_by_legacy_id BIGINT NOT NULL DEFAULT 0,
  failure_reason TEXT NOT NULL DEFAULT '' CHECK (length(failure_reason) <= 500),
  document JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS sf_release_deployments (
  deployment_id UUID PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES sf_release_candidates(candidate_id) ON DELETE CASCADE,
  artifact_id UUID NOT NULL REFERENCES sf_release_artifacts(artifact_id) ON DELETE RESTRICT,
  environment TEXT NOT NULL CHECK (environment IN ('canary', 'production')),
  state TEXT NOT NULL DEFAULT 'requested'
    CHECK (state IN ('requested', 'deploying', 'live', 'failed', 'rolled_back', 'superseded')),
  adapter TEXT NOT NULL DEFAULT 'dry_run' CHECK (length(adapter) BETWEEN 1 AND 60),
  -- The exact-artifact fingerprint captured at deployment time so a later
  -- Production promotion can be proven to reference the same artifact.
  artifact_sha256 TEXT NOT NULL CHECK (length(artifact_sha256) BETWEEN 32 AND 128),
  manifest_sha256 TEXT NOT NULL CHECK (length(manifest_sha256) BETWEEN 32 AND 128),
  git_commit_sha TEXT NOT NULL CHECK (length(git_commit_sha) BETWEEN 7 AND 64),
  build_id TEXT NOT NULL CHECK (length(build_id) BETWEEN 1 AND 200),
  requested_by_user_id UUID REFERENCES sf_users(user_uuid) ON DELETE SET NULL,
  requested_by_legacy_id BIGINT NOT NULL DEFAULT 0,
  scheduled_for_utc TIMESTAMPTZ,
  failure_reason TEXT NOT NULL DEFAULT '' CHECK (length(failure_reason) <= 500),
  idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 160),
  document JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- A retry with the same idempotency key never creates a second live deployment
-- request for the same candidate/environment.
CREATE UNIQUE INDEX IF NOT EXISTS sf_release_deployments_idempotency_uidx
  ON sf_release_deployments(candidate_id, environment, idempotency_key);
-- At most one non-terminal deployment per candidate/environment prevents a
-- double deployment race.
CREATE UNIQUE INDEX IF NOT EXISTS sf_release_deployments_one_active_idx
  ON sf_release_deployments(candidate_id, environment)
  WHERE state IN ('requested', 'deploying', 'live');

CREATE TABLE IF NOT EXISTS sf_release_checks (
  check_id UUID PRIMARY KEY,
  deployment_id UUID NOT NULL REFERENCES sf_release_deployments(deployment_id) ON DELETE CASCADE,
  candidate_id UUID NOT NULL REFERENCES sf_release_candidates(candidate_id) ON DELETE CASCADE,
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
  result TEXT NOT NULL DEFAULT 'pending'
    CHECK (result IN ('pass', 'fail', 'pending', 'blocked')),
  recorded_by_user_id UUID REFERENCES sf_users(user_uuid) ON DELETE SET NULL,
  recorded_by_legacy_id BIGINT NOT NULL DEFAULT 0,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(evidence) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS sf_release_approvals (
  approval_id UUID PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES sf_release_candidates(candidate_id) ON DELETE CASCADE,
  artifact_id UUID NOT NULL REFERENCES sf_release_artifacts(artifact_id) ON DELETE RESTRICT,
  environment TEXT NOT NULL DEFAULT 'production' CHECK (environment IN ('production')),
  -- The exact-artifact fingerprint the approval is bound to; a Production
  -- promotion must match every field or the approval is not usable.
  artifact_sha256 TEXT NOT NULL CHECK (length(artifact_sha256) BETWEEN 32 AND 128),
  manifest_sha256 TEXT NOT NULL CHECK (length(manifest_sha256) BETWEEN 32 AND 128),
  git_commit_sha TEXT NOT NULL CHECK (length(git_commit_sha) BETWEEN 7 AND 64),
  build_id TEXT NOT NULL CHECK (length(build_id) BETWEEN 1 AND 200),
  approved_by_user_id UUID REFERENCES sf_users(user_uuid) ON DELETE SET NULL,
  approved_by_legacy_id BIGINT NOT NULL DEFAULT 0,
  step_up_challenge_id TEXT NOT NULL DEFAULT '' CHECK (length(step_up_challenge_id) <= 120),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'consumed', 'revoked', 'stale')),
  idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 160),
  document JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE UNIQUE INDEX IF NOT EXISTS sf_release_approvals_idempotency_uidx
  ON sf_release_approvals(candidate_id, idempotency_key);

CREATE TABLE IF NOT EXISTS sf_release_rollbacks (
  rollback_id UUID PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES sf_release_candidates(candidate_id) ON DELETE CASCADE,
  from_artifact_id UUID REFERENCES sf_release_artifacts(artifact_id) ON DELETE SET NULL,
  to_artifact_id UUID NOT NULL REFERENCES sf_release_artifacts(artifact_id) ON DELETE RESTRICT,
  environment TEXT NOT NULL DEFAULT 'production' CHECK (environment IN ('production')),
  requested_by_user_id UUID REFERENCES sf_users(user_uuid) ON DELETE SET NULL,
  requested_by_legacy_id BIGINT NOT NULL DEFAULT 0,
  reason TEXT NOT NULL DEFAULT '' CHECK (length(reason) <= 500),
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(evidence) = 'object'),
  idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 160),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE UNIQUE INDEX IF NOT EXISTS sf_release_rollbacks_idempotency_uidx
  ON sf_release_rollbacks(candidate_id, idempotency_key);

CREATE TABLE IF NOT EXISTS sf_release_notifications (
  notification_id UUID PRIMARY KEY,
  candidate_id UUID REFERENCES sf_release_candidates(candidate_id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN (
    'scheduled_update', 'warn_5m', 'warn_60s', 'deploy_started',
    'deploy_successful', 'deploy_failed', 'rollback', 'reload_available'
  )),
  environment TEXT NOT NULL DEFAULT 'production' CHECK (environment IN ('canary', 'production')),
  channel TEXT NOT NULL DEFAULT 'interface' CHECK (length(channel) BETWEEN 1 AND 40),
  -- The notification is only ever a durable record + interface contract in this
  -- phase; no real Telegram/banner is sent, so delivery stays 'recorded'.
  delivery TEXT NOT NULL DEFAULT 'recorded'
    CHECK (delivery IN ('recorded', 'queued', 'sent', 'suppressed')),
  scheduled_for_utc TIMESTAMPTZ,
  document JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS sf_release_events (
  event_id UUID PRIMARY KEY,
  candidate_id UUID REFERENCES sf_release_candidates(candidate_id) ON DELETE CASCADE,
  event_type TEXT NOT NULL CHECK (length(event_type) BETWEEN 1 AND 120),
  from_state TEXT NOT NULL DEFAULT '' CHECK (length(from_state) <= 60),
  to_state TEXT NOT NULL DEFAULT '' CHECK (length(to_state) <= 60),
  actor_user_id UUID REFERENCES sf_users(user_uuid) ON DELETE SET NULL,
  actor_legacy_id BIGINT NOT NULL DEFAULT 0,
  idempotency_key TEXT NOT NULL DEFAULT '' CHECK (length(idempotency_key) <= 160),
  -- Redacted evidence only: never a signing key, token, secret or raw path.
  document JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS sf_release_candidates_state_idx
  ON sf_release_candidates(state, updated_at);
CREATE INDEX IF NOT EXISTS sf_release_deployments_candidate_idx
  ON sf_release_deployments(candidate_id, environment, state);
CREATE INDEX IF NOT EXISTS sf_release_checks_deployment_idx
  ON sf_release_checks(deployment_id, result);
CREATE INDEX IF NOT EXISTS sf_release_events_candidate_idx
  ON sf_release_events(candidate_id, created_at);

-- The Release Center is a global administrative control plane: every table is
-- readable/writable only under the global service scope, never a workspace or
-- user scope.
ALTER TABLE sf_release_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_release_artifacts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_release_artifacts_global ON sf_release_artifacts;
CREATE POLICY sf_release_artifacts_global ON sf_release_artifacts
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

ALTER TABLE sf_release_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_release_candidates FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_release_candidates_global ON sf_release_candidates;
CREATE POLICY sf_release_candidates_global ON sf_release_candidates
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

ALTER TABLE sf_release_deployments ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_release_deployments FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_release_deployments_global ON sf_release_deployments;
CREATE POLICY sf_release_deployments_global ON sf_release_deployments
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

ALTER TABLE sf_release_checks ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_release_checks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_release_checks_global ON sf_release_checks;
CREATE POLICY sf_release_checks_global ON sf_release_checks
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

ALTER TABLE sf_release_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_release_approvals FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_release_approvals_global ON sf_release_approvals;
CREATE POLICY sf_release_approvals_global ON sf_release_approvals
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

ALTER TABLE sf_release_rollbacks ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_release_rollbacks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_release_rollbacks_global ON sf_release_rollbacks;
CREATE POLICY sf_release_rollbacks_global ON sf_release_rollbacks
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

ALTER TABLE sf_release_notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_release_notifications FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_release_notifications_global ON sf_release_notifications;
CREATE POLICY sf_release_notifications_global ON sf_release_notifications
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

ALTER TABLE sf_release_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_release_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_release_events_global ON sf_release_events;
CREATE POLICY sf_release_events_global ON sf_release_events
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

GRANT SELECT, INSERT, UPDATE, DELETE ON sf_release_artifacts TO stratforge_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON sf_release_candidates TO stratforge_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON sf_release_deployments TO stratforge_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON sf_release_checks TO stratforge_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON sf_release_approvals TO stratforge_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON sf_release_rollbacks TO stratforge_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON sf_release_notifications TO stratforge_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON sf_release_events TO stratforge_app;
