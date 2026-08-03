-- Phase 9: Blue-green deployment steps + maintenance windows.
--
-- Additive expand-only migration. Extends the Phase 8 Release Center with the
-- per-stage blue-green deployment step log and maintenance-window records. No
-- destructive contract, no DROP, no data migration. Both tables start empty.
-- Like the rest of the Release Center they are a global administrative control
-- plane, so every table is global-scope only under row level security (never
-- workspace/user readable). No signing key, token, raw credential or absolute
-- host path is ever stored here — only public build identity, slot names, stage
-- status and redacted evidence.

CREATE TABLE IF NOT EXISTS sf_release_deploy_steps (
  step_id UUID PRIMARY KEY,
  deployment_id UUID NOT NULL REFERENCES sf_release_deployments(deployment_id) ON DELETE CASCADE,
  candidate_id UUID NOT NULL REFERENCES sf_release_candidates(candidate_id) ON DELETE CASCADE,
  environment TEXT NOT NULL CHECK (environment IN ('canary', 'production')),
  strategy TEXT NOT NULL DEFAULT 'blue_green_symlink' CHECK (length(strategy) BETWEEN 1 AND 60),
  stage TEXT NOT NULL CHECK (stage IN (
    'prepare_green', 'expand_migrate', 'start_green', 'green_readiness',
    'drain_blue', 'switch_traffic', 'verify_live', 'contract_migrate'
  )),
  ordinal INTEGER NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
  -- 'pass'/'fail' are only ever recorded by a real executor; a dry-run stage is
  -- 'dry_run', a stage that would contact real infrastructure is 'pending', an
  -- incompatible stage is 'blocked', a deferred stage is 'skipped'.
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('dry_run', 'pending', 'blocked', 'skipped', 'pass', 'fail')),
  active_slot TEXT NOT NULL DEFAULT '' CHECK (active_slot IN ('', 'blue', 'green')),
  target_slot TEXT NOT NULL DEFAULT '' CHECK (target_slot IN ('', 'blue', 'green')),
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(evidence) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS sf_maintenance_windows (
  window_id UUID PRIMARY KEY,
  candidate_id UUID REFERENCES sf_release_candidates(candidate_id) ON DELETE CASCADE,
  environment TEXT NOT NULL CHECK (environment IN ('canary', 'production')),
  kind TEXT NOT NULL DEFAULT 'deploy' CHECK (length(kind) BETWEEN 1 AND 40),
  -- A record + interface contract only in this phase; nothing is enforced, so
  -- the window stays 'planned' until a real executor opens/closes it.
  state TEXT NOT NULL DEFAULT 'planned'
    CHECK (state IN ('planned', 'active', 'closed', 'cancelled')),
  reason TEXT NOT NULL DEFAULT '' CHECK (length(reason) <= 200),
  scheduled_for_utc TIMESTAMPTZ,
  opened_at_utc TIMESTAMPTZ,
  closed_at_utc TIMESTAMPTZ,
  document JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS sf_release_deploy_steps_deployment_idx
  ON sf_release_deploy_steps(deployment_id, ordinal);
CREATE INDEX IF NOT EXISTS sf_release_deploy_steps_candidate_idx
  ON sf_release_deploy_steps(candidate_id, stage);
CREATE INDEX IF NOT EXISTS sf_maintenance_windows_candidate_idx
  ON sf_maintenance_windows(candidate_id, state);

-- The Release Center is a global administrative control plane: both tables are
-- readable/writable only under the global service scope, never a workspace or
-- user scope.
ALTER TABLE sf_release_deploy_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_release_deploy_steps FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_release_deploy_steps_global ON sf_release_deploy_steps;
CREATE POLICY sf_release_deploy_steps_global ON sf_release_deploy_steps
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

ALTER TABLE sf_maintenance_windows ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_maintenance_windows FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_maintenance_windows_global ON sf_maintenance_windows;
CREATE POLICY sf_maintenance_windows_global ON sf_maintenance_windows
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());
