-- Phase 6: durable shared-NinjaTrader resource lease and job queue.
--
-- Additive expand-only migration. Creates one new, initially empty table for the
-- shared owner-training NinjaTrader resource lease/queue. Canonical owner key is
-- the Phase 3 ``user_uuid``; ``requested_by_legacy_id`` is carried only so the
-- existing BIGINT row level security scope keeps working during the compatibility
-- window. No destructive contract, no queue mutation, no data removal.

CREATE TABLE IF NOT EXISTS sf_ninjatrader_resource_leases (
  resource_id TEXT NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 200),
  job_id UUID NOT NULL,
  workspace_id TEXT NOT NULL CHECK (length(workspace_id) BETWEEN 1 AND 120),
  requested_by_user_id UUID NOT NULL REFERENCES sf_users(user_uuid) ON DELETE CASCADE,
  requested_by_legacy_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE CASCADE,
  -- Only the hash of the one-time lease token is stored; the raw token is
  -- returned to the worker once and never persisted or logged.
  lease_token_hash TEXT NOT NULL DEFAULT '' CHECK (length(lease_token_hash) <= 128),
  operation_kind TEXT NOT NULL
    CHECK (operation_kind IN ('training', 'backtest', 'compile', 'optimization', 'telemetry_read', 'live')),
  parallel_group TEXT NOT NULL DEFAULT 'exclusive'
    CHECK (parallel_group IN ('exclusive', 'readonly')),
  state TEXT NOT NULL DEFAULT 'queued'
    CHECK (state IN ('queued', 'active', 'released', 'expired', 'cancelled', 'failed')),
  queue_seq BIGINT NOT NULL,
  idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 160),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  acquired_at TIMESTAMPTZ,
  heartbeat_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  released_at TIMESTAMPTZ,
  -- Masked audit metadata only (never account/strategy identity or the token).
  document JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object'),
  PRIMARY KEY (resource_id, job_id)
);

-- At most one active EXCLUSIVE lease per shared resource: the core mutual
-- exclusion for conflicting owner-training jobs.
CREATE UNIQUE INDEX IF NOT EXISTS sf_nt_resource_one_active_exclusive_idx
  ON sf_ninjatrader_resource_leases(resource_id)
  WHERE state = 'active' AND parallel_group = 'exclusive';

-- A retry with the same idempotency key never creates a second live lease.
CREATE UNIQUE INDEX IF NOT EXISTS sf_nt_resource_idempotency_uidx
  ON sf_ninjatrader_resource_leases(resource_id, requested_by_user_id, idempotency_key)
  WHERE state IN ('queued', 'active');

CREATE INDEX IF NOT EXISTS sf_nt_resource_queue_idx
  ON sf_ninjatrader_resource_leases(resource_id, state, queue_seq);
CREATE INDEX IF NOT EXISTS sf_nt_resource_user_idx
  ON sf_ninjatrader_resource_leases(requested_by_user_id, state);
CREATE INDEX IF NOT EXISTS sf_nt_resource_expiry_idx
  ON sf_ninjatrader_resource_leases(state, expires_at)
  WHERE state = 'active';

ALTER TABLE sf_ninjatrader_resource_leases ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_ninjatrader_resource_leases FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_ninjatrader_resource_leases_scope ON sf_ninjatrader_resource_leases;
CREATE POLICY sf_ninjatrader_resource_leases_scope ON sf_ninjatrader_resource_leases
  USING (
    sf_scope_global()
    OR workspace_id = sf_scope_workspace()
    OR requested_by_legacy_id = sf_scope_user()
  )
  WITH CHECK (
    sf_scope_global()
    OR workspace_id = sf_scope_workspace()
    OR requested_by_legacy_id = sf_scope_user()
  );

GRANT SELECT, INSERT, UPDATE, DELETE ON sf_ninjatrader_resource_leases TO stratforge_app;
