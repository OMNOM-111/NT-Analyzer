-- StratForge Stage 7: horizontally safe Production workers and shared admission.

ALTER TABLE sf_jobs
  ADD COLUMN worker_class TEXT NOT NULL DEFAULT 'maintenance',
  ADD COLUMN priority SMALLINT NOT NULL DEFAULT 100,
  ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN timeout_sec INTEGER NOT NULL DEFAULT 300,
  ADD COLUMN available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  ADD COLUMN started_at TIMESTAMPTZ,
  ADD COLUMN finished_at TIMESTAMPTZ,
  ADD COLUMN leased_until TIMESTAMPTZ,
  ADD COLUMN lease_owner TEXT,
  ADD COLUMN lease_token UUID,
  ADD COLUMN heartbeat_at TIMESTAMPTZ,
  ADD COLUMN cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN dangerous BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN payload_bytes INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN result_bytes INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN last_error TEXT NOT NULL DEFAULT '';

-- Pre-Stage-7 rows did not carry a renewable lease.  Never pretend that an
-- inherited `running` marker is safe to resume; move it to operator review.
UPDATE sf_jobs
SET status='review',
    last_error='pre-stage7 running row requires explicit review',
    updated_at=clock_timestamp()
WHERE status='running';

ALTER TABLE sf_jobs
  ADD CONSTRAINT sf_jobs_worker_class_check
    CHECK (worker_class ~ '^[a-z][a-z0-9_]{1,39}$'),
  ADD CONSTRAINT sf_jobs_priority_check CHECK (priority BETWEEN 0 AND 1000),
  ADD CONSTRAINT sf_jobs_attempts_check
    CHECK (attempts >= 0 AND max_attempts BETWEEN 1 AND 20 AND attempts <= max_attempts),
  ADD CONSTRAINT sf_jobs_timeout_check CHECK (timeout_sec BETWEEN 1 AND 86400),
  ADD CONSTRAINT sf_jobs_payload_bytes_check CHECK (payload_bytes BETWEEN 0 AND 8388608),
  ADD CONSTRAINT sf_jobs_result_bytes_check CHECK (result_bytes BETWEEN 0 AND 8388608),
  ADD CONSTRAINT sf_jobs_lease_shape_check CHECK (
    (status = 'running' AND lease_owner IS NOT NULL AND lease_token IS NOT NULL
      AND leased_until IS NOT NULL AND started_at IS NOT NULL)
    OR status <> 'running'
  );

CREATE INDEX sf_jobs_worker_claim_idx
  ON sf_jobs(worker_class, status, available_at, priority, created_at)
  WHERE status = 'queued' AND cancel_requested = FALSE;
CREATE INDEX sf_jobs_active_lease_idx
  ON sf_jobs(worker_class, leased_until)
  WHERE status = 'running';
CREATE INDEX sf_jobs_workspace_worker_status_idx
  ON sf_jobs(workspace_id, worker_class, status, created_at);

CREATE TABLE sf_worker_classes (
  worker_class TEXT PRIMARY KEY CHECK (worker_class ~ '^[a-z][a-z0-9_]{1,39}$'),
  max_concurrency INTEGER NOT NULL CHECK (max_concurrency BETWEEN 1 AND 256),
  max_payload_bytes INTEGER NOT NULL CHECK (max_payload_bytes BETWEEN 1024 AND 8388608),
  default_timeout_sec INTEGER NOT NULL CHECK (default_timeout_sec BETWEEN 1 AND 86400),
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  document JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object'),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE sf_workspace_queue_quotas (
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  worker_class TEXT NOT NULL REFERENCES sf_worker_classes(worker_class) ON DELETE RESTRICT,
  max_queued INTEGER NOT NULL CHECK (max_queued BETWEEN 1 AND 10000),
  max_running INTEGER NOT NULL CHECK (max_running BETWEEN 1 AND 100),
  weight INTEGER NOT NULL DEFAULT 1 CHECK (weight BETWEEN 1 AND 100),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (workspace_id, worker_class)
);

CREATE TABLE sf_queue_workspace_state (
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  worker_class TEXT NOT NULL REFERENCES sf_worker_classes(worker_class) ON DELETE CASCADE,
  last_claimed_at TIMESTAMPTZ,
  served_count BIGINT NOT NULL DEFAULT 0 CHECK (served_count >= 0),
  PRIMARY KEY (workspace_id, worker_class)
);

CREATE TABLE sf_job_attempts (
  job_id TEXT NOT NULL REFERENCES sf_jobs(job_id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  attempt INTEGER NOT NULL CHECK (attempt BETWEEN 1 AND 20),
  worker_id TEXT NOT NULL CHECK (length(worker_id) BETWEEN 1 AND 160),
  lease_token UUID NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  finished_at TIMESTAMPTZ,
  outcome TEXT NOT NULL DEFAULT 'running'
    CHECK (outcome IN ('running','completed','retry','failed','dead_letter','cancelled','lease_expired','deadline_expired')),
  error_class TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (job_id, attempt),
  UNIQUE (lease_token)
);

CREATE INDEX sf_job_attempts_workspace_time_idx
  ON sf_job_attempts(workspace_id, started_at DESC);

CREATE TABLE sf_rate_limit_buckets (
  subject_hash TEXT NOT NULL CHECK (subject_hash ~ '^[0-9a-f]{64}$'),
  action_class TEXT NOT NULL CHECK (action_class ~ '^[a-z][a-z0-9_.:-]{1,79}$'),
  window_started_at TIMESTAMPTZ NOT NULL,
  request_count INTEGER NOT NULL CHECK (request_count BETWEEN 1 AND 10000000),
  expires_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (subject_hash, action_class, window_started_at)
);

CREATE INDEX sf_rate_limit_expiry_idx ON sf_rate_limit_buckets(expires_at);

CREATE TABLE sf_idempotency_keys (
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  operation TEXT NOT NULL CHECK (operation ~ '^[a-z][a-z0-9_.:-]{1,99}$'),
  key_hash TEXT NOT NULL CHECK (key_hash ~ '^[0-9a-f]{64}$'),
  request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  state TEXT NOT NULL CHECK (state IN ('reserved','completed','failed')),
  response JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(response) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  expires_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (workspace_id, operation, key_hash)
);

CREATE INDEX sf_idempotency_expiry_idx ON sf_idempotency_keys(expires_at);

ALTER TABLE sf_worker_classes ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_worker_classes FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_worker_classes_read ON sf_worker_classes
  FOR SELECT USING (TRUE);
CREATE POLICY sf_worker_classes_global_write ON sf_worker_classes
  FOR ALL USING (sf_scope_global()) WITH CHECK (sf_scope_global());

ALTER TABLE sf_workspace_queue_quotas ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_workspace_queue_quotas FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_workspace_queue_quotas_scope ON sf_workspace_queue_quotas
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_queue_workspace_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_queue_workspace_state FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_queue_workspace_state_scope ON sf_queue_workspace_state
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_job_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_job_attempts FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_job_attempts_scope ON sf_job_attempts
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_rate_limit_buckets ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_rate_limit_buckets FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_rate_limit_buckets_global ON sf_rate_limit_buckets
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

ALTER TABLE sf_idempotency_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_idempotency_keys FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_idempotency_keys_scope ON sf_idempotency_keys
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

GRANT SELECT, INSERT, UPDATE, DELETE ON
  sf_worker_classes, sf_workspace_queue_quotas, sf_queue_workspace_state,
  sf_job_attempts, sf_rate_limit_buckets, sf_idempotency_keys
TO stratforge_app;
