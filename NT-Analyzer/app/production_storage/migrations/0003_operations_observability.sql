-- StratForge Stage 8: single Telegram consumer, AI budgets, remote market data
-- and durable operational observability. All secrets remain outside PostgreSQL.

CREATE TABLE sf_service_leases (
  lease_name TEXT PRIMARY KEY CHECK (lease_name ~ '^[a-z][a-z0-9_.:-]{2,99}$'),
  owner_id TEXT NOT NULL CHECK (length(owner_id) BETWEEN 3 AND 160),
  lease_token UUID NOT NULL,
  leased_until TIMESTAMPTZ NOT NULL,
  heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  document JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object')
);

CREATE INDEX sf_service_leases_expiry_idx ON sf_service_leases(leased_until);

CREATE TABLE sf_service_heartbeats (
  service_role TEXT NOT NULL CHECK (service_role ~ '^[a-z][a-z0-9_.:-]{1,79}$'),
  instance_id TEXT NOT NULL CHECK (length(instance_id) BETWEEN 3 AND 160),
  status TEXT NOT NULL CHECK (status IN ('starting','healthy','degraded','stopping','failed')),
  started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  document JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object'),
  PRIMARY KEY (service_role, instance_id)
);

CREATE INDEX sf_service_heartbeats_role_time_idx
  ON sf_service_heartbeats(service_role, heartbeat_at DESC);

CREATE TABLE sf_telegram_updates (
  update_key TEXT PRIMARY KEY CHECK (update_key ~ '^tgu_[0-9a-f]{32}$'),
  bot_identity_hash TEXT NOT NULL CHECK (bot_identity_hash ~ '^[0-9a-f]{64}$'),
  update_id BIGINT NOT NULL CHECK (update_id > 0),
  conversation_key TEXT NOT NULL CHECK (length(conversation_key) BETWEEN 1 AND 200),
  transport TEXT NOT NULL CHECK (transport IN ('webhook','poll','recovery')),
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued','running','completed','dead_letter')),
  attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 100),
  available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  lease_owner TEXT,
  lease_token UUID,
  leased_until TIMESTAMPTZ,
  last_error TEXT NOT NULL DEFAULT '' CHECK (length(last_error) <= 1000),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  received_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  finished_at TIMESTAMPTZ,
  retention_until TIMESTAMPTZ NOT NULL DEFAULT (clock_timestamp() + INTERVAL '30 days'),
  UNIQUE (bot_identity_hash, update_id),
  CHECK ((status = 'running') = (lease_token IS NOT NULL))
);

CREATE INDEX sf_telegram_updates_claim_idx
  ON sf_telegram_updates(status, available_at, update_id);
CREATE INDEX sf_telegram_updates_retention_idx
  ON sf_telegram_updates(retention_until) WHERE status IN ('completed','dead_letter');

CREATE TABLE sf_telegram_outbox (
  outbox_id TEXT PRIMARY KEY CHECK (outbox_id ~ '^tgo_[0-9a-f]{32}$'),
  bot_identity_hash TEXT NOT NULL CHECK (bot_identity_hash ~ '^[0-9a-f]{64}$'),
  dedupe_hash TEXT NOT NULL CHECK (dedupe_hash ~ '^[0-9a-f]{64}$'),
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued','sending','sent','dead_letter')),
  attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 100),
  available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  lease_owner TEXT,
  lease_token UUID,
  leased_until TIMESTAMPTZ,
  last_error TEXT NOT NULL DEFAULT '' CHECK (length(last_error) <= 1000),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  sent_at TIMESTAMPTZ,
  retention_until TIMESTAMPTZ NOT NULL DEFAULT (clock_timestamp() + INTERVAL '30 days'),
  UNIQUE (bot_identity_hash, dedupe_hash),
  CHECK ((status = 'sending') = (lease_token IS NOT NULL))
);

CREATE INDEX sf_telegram_outbox_claim_idx
  ON sf_telegram_outbox(status, available_at, created_at);
CREATE INDEX sf_telegram_outbox_retention_idx
  ON sf_telegram_outbox(retention_until) WHERE status IN ('sent','dead_letter');

CREATE TABLE sf_telegram_bot_state (
  bot_identity_hash TEXT PRIMARY KEY CHECK (bot_identity_hash ~ '^[0-9a-f]{64}$'),
  poll_offset BIGINT NOT NULL DEFAULT 0 CHECK (poll_offset >= 0),
  webhook_configured BOOLEAN NOT NULL DEFAULT FALSE,
  document JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object'),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE sf_ai_workspace_budgets (
  workspace_id TEXT PRIMARY KEY REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  daily_limit_usd NUMERIC(14,6) NOT NULL DEFAULT 5.0 CHECK (daily_limit_usd BETWEEN 0 AND 10000),
  monthly_limit_usd NUMERIC(14,6) NOT NULL DEFAULT 20.0 CHECK (monthly_limit_usd BETWEEN 0 AND 100000),
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Existing workspaces receive a conservative enabled budget during cutover;
-- future workspaces receive the same row atomically with their creation.
INSERT INTO sf_ai_workspace_budgets(workspace_id)
SELECT workspace_id FROM sf_workspaces
ON CONFLICT(workspace_id) DO NOTHING;

CREATE OR REPLACE FUNCTION sf_seed_ai_workspace_budget()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO sf_ai_workspace_budgets(workspace_id)
  VALUES(NEW.workspace_id)
  ON CONFLICT(workspace_id) DO NOTHING;
  RETURN NEW;
END;
$$;

CREATE TRIGGER sf_workspaces_seed_ai_budget
AFTER INSERT ON sf_workspaces
FOR EACH ROW EXECUTE FUNCTION sf_seed_ai_workspace_budget();

CREATE TABLE sf_ai_reservations (
  reservation_id TEXT PRIMARY KEY CHECK (reservation_id ~ '^air_[0-9a-f]{32}$'),
  request_id TEXT NOT NULL UNIQUE CHECK (length(request_id) BETWEEN 8 AND 160),
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  user_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE RESTRICT,
  provider TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 80),
  model TEXT NOT NULL CHECK (length(model) BETWEEN 1 AND 160),
  role TEXT NOT NULL CHECK (length(role) BETWEEN 1 AND 80),
  estimated_cost_usd NUMERIC(14,8) NOT NULL CHECK (estimated_cost_usd BETWEEN 0 AND 10000),
  prompt_sha256 TEXT NOT NULL CHECK (prompt_sha256 ~ '^[0-9a-f]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX sf_ai_reservations_workspace_expiry_idx
  ON sf_ai_reservations(workspace_id, expires_at);

CREATE TABLE sf_ai_usage_events (
  request_id TEXT PRIMARY KEY CHECK (length(request_id) BETWEEN 8 AND 160),
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  user_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE RESTRICT,
  provider TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 80),
  model TEXT NOT NULL CHECK (length(model) BETWEEN 1 AND 160),
  role TEXT NOT NULL CHECK (length(role) BETWEEN 1 AND 80),
  purpose TEXT NOT NULL CHECK (length(purpose) BETWEEN 1 AND 120),
  status TEXT NOT NULL CHECK (status IN ('success','error','blocked','cache_hit')),
  input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
  output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
  cost_usd NUMERIC(14,8) NOT NULL DEFAULT 0 CHECK (cost_usd BETWEEN 0 AND 10000),
  prompt_sha256 TEXT NOT NULL CHECK (prompt_sha256 ~ '^[0-9a-f]{64}$'),
  document JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object'),
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  retention_until TIMESTAMPTZ NOT NULL DEFAULT (clock_timestamp() + INTERVAL '400 days')
);

CREATE INDEX sf_ai_usage_workspace_time_idx
  ON sf_ai_usage_events(workspace_id, occurred_at DESC);
CREATE INDEX sf_ai_usage_retention_idx ON sf_ai_usage_events(retention_until);

CREATE TABLE sf_market_data_subscriptions (
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  installation_id TEXT NOT NULL REFERENCES sf_connector_installations(installation_id) ON DELETE CASCADE,
  requested_by_user_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE RESTRICT,
  exact_contract TEXT NOT NULL CHECK (exact_contract ~ '^[A-Za-z0-9._ -]{1,40}$'),
  timeframe TEXT NOT NULL CHECK (
    timeframe ~ '^(?:[1-9]|[1-9][0-9]|1[0-9]{2}|2[0-3][0-9]|240)m$'
    OR timeframe ~ '^(?:[1-9]|1[0-9]|2[0-4])h$'
    OR timeframe = '1D'
  ),
  max_bars INTEGER NOT NULL DEFAULT 1500 CHECK (max_bars BETWEEN 100 AND 10000),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','deleted')),
  requested_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  expires_at TIMESTAMPTZ NOT NULL DEFAULT (clock_timestamp() + INTERVAL '5 minutes'),
  document JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object'),
  PRIMARY KEY (workspace_id, installation_id, exact_contract, timeframe)
);

CREATE INDEX sf_market_data_subscriptions_connector_idx
  ON sf_market_data_subscriptions(installation_id, status, expires_at);

CREATE TABLE sf_market_data_snapshots (
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  installation_id TEXT NOT NULL REFERENCES sf_connector_installations(installation_id) ON DELETE CASCADE,
  exact_contract TEXT NOT NULL CHECK (exact_contract ~ '^[A-Za-z0-9._ -]{1,40}$'),
  timeframe TEXT NOT NULL CHECK (
    timeframe ~ '^(?:[1-9]|[1-9][0-9]|1[0-9]{2}|2[0-3][0-9]|240)m$'
    OR timeframe ~ '^(?:[1-9]|1[0-9]|2[0-4])h$'
    OR timeframe = '1D'
  ),
  source_sequence BIGINT NOT NULL CHECK (source_sequence > 0),
  source_signature TEXT NOT NULL CHECK (source_signature ~ '^[0-9a-f]{64}$'),
  payload_sha256 TEXT NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
  observed_at TIMESTAMPTZ NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  stale_after TIMESTAMPTZ NOT NULL,
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  PRIMARY KEY (workspace_id, installation_id, exact_contract, timeframe)
);

CREATE INDEX sf_market_data_snapshots_workspace_time_idx
  ON sf_market_data_snapshots(workspace_id, received_at DESC);
CREATE INDEX sf_market_data_snapshots_stale_idx ON sf_market_data_snapshots(stale_after);

CREATE TABLE sf_market_data_ingest_batches (
  batch_id TEXT PRIMARY KEY CHECK (batch_id ~ '^mdb_[0-9a-f]{32}$'),
  workspace_id TEXT NOT NULL REFERENCES sf_workspaces(workspace_id) ON DELETE CASCADE,
  installation_id TEXT NOT NULL REFERENCES sf_connector_installations(installation_id) ON DELETE CASCADE,
  source_sequence BIGINT NOT NULL CHECK (source_sequence > 0),
  payload_sha256 TEXT NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
  item_count INTEGER NOT NULL CHECK (item_count BETWEEN 1 AND 64),
  received_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  retention_until TIMESTAMPTZ NOT NULL DEFAULT (clock_timestamp() + INTERVAL '7 days'),
  UNIQUE (installation_id, source_sequence)
);

CREATE INDEX sf_market_data_ingest_retention_idx
  ON sf_market_data_ingest_batches(retention_until);

CREATE TABLE sf_operational_events (
  event_id TEXT PRIMARY KEY CHECK (event_id ~ '^ope_[0-9a-f]{32}$'),
  workspace_id TEXT REFERENCES sf_workspaces(workspace_id) ON DELETE SET NULL,
  user_id BIGINT REFERENCES sf_users(user_id) ON DELETE SET NULL,
  component TEXT NOT NULL CHECK (length(component) BETWEEN 1 AND 80),
  event_type TEXT NOT NULL CHECK (length(event_type) BETWEEN 1 AND 120),
  severity TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved')),
  fingerprint TEXT NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
  payload JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  retention_until TIMESTAMPTZ NOT NULL DEFAULT (clock_timestamp() + INTERVAL '730 days')
);

CREATE UNIQUE INDEX sf_operational_events_open_fingerprint_idx
  ON sf_operational_events(fingerprint) WHERE status = 'open';
CREATE INDEX sf_operational_events_status_time_idx
  ON sf_operational_events(status, severity, occurred_at DESC);
CREATE INDEX sf_operational_events_retention_idx ON sf_operational_events(retention_until);

-- Tenant identity is enforced by relational constraints as well as RLS.  A
-- globally valid user or Connector installation must never be attachable to a
-- different workspace merely because both identifiers exist independently.
ALTER TABLE sf_connector_installations
  ADD CONSTRAINT sf_connector_installations_workspace_installation_uniq
  UNIQUE (workspace_id, installation_id);

ALTER TABLE sf_connector_installations
  ADD CONSTRAINT sf_connector_installations_workspace_user_fk
  FOREIGN KEY (workspace_id, user_id)
  REFERENCES sf_workspace_memberships(workspace_id, user_id);

ALTER TABLE sf_connector_sessions
  ADD CONSTRAINT sf_connector_sessions_workspace_installation_fk
  FOREIGN KEY (workspace_id, installation_id)
  REFERENCES sf_connector_installations(workspace_id, installation_id)
  ON DELETE CASCADE;

ALTER TABLE sf_connections
  ADD CONSTRAINT sf_connections_workspace_user_fk
  FOREIGN KEY (workspace_id, user_id)
  REFERENCES sf_workspace_memberships(workspace_id, user_id);

ALTER TABLE sf_jobs
  ADD CONSTRAINT sf_jobs_workspace_user_fk
  FOREIGN KEY (workspace_id, user_id)
  REFERENCES sf_workspace_memberships(workspace_id, user_id);

ALTER TABLE sf_jobs
  ADD CONSTRAINT sf_jobs_workspace_job_uniq UNIQUE (workspace_id, job_id);

ALTER TABLE sf_job_attempts
  ADD CONSTRAINT sf_job_attempts_workspace_job_fk
  FOREIGN KEY (workspace_id, job_id)
  REFERENCES sf_jobs(workspace_id, job_id)
  ON DELETE CASCADE;

ALTER TABLE sf_commands
  ADD CONSTRAINT sf_commands_workspace_user_fk
  FOREIGN KEY (workspace_id, user_id)
  REFERENCES sf_workspace_memberships(workspace_id, user_id);

ALTER TABLE sf_ai_reservations
  ADD CONSTRAINT sf_ai_reservations_workspace_user_fk
  FOREIGN KEY (workspace_id, user_id)
  REFERENCES sf_workspace_memberships(workspace_id, user_id);

ALTER TABLE sf_ai_usage_events
  ADD CONSTRAINT sf_ai_usage_events_workspace_user_fk
  FOREIGN KEY (workspace_id, user_id)
  REFERENCES sf_workspace_memberships(workspace_id, user_id);

ALTER TABLE sf_market_data_subscriptions
  ADD CONSTRAINT sf_market_data_subscriptions_workspace_user_fk
  FOREIGN KEY (workspace_id, requested_by_user_id)
  REFERENCES sf_workspace_memberships(workspace_id, user_id);

ALTER TABLE sf_market_data_subscriptions
  ADD CONSTRAINT sf_market_data_subscriptions_workspace_installation_fk
  FOREIGN KEY (workspace_id, installation_id)
  REFERENCES sf_connector_installations(workspace_id, installation_id)
  ON DELETE CASCADE;

ALTER TABLE sf_market_data_snapshots
  ADD CONSTRAINT sf_market_data_snapshots_workspace_installation_fk
  FOREIGN KEY (workspace_id, installation_id)
  REFERENCES sf_connector_installations(workspace_id, installation_id)
  ON DELETE CASCADE;

ALTER TABLE sf_market_data_ingest_batches
  ADD CONSTRAINT sf_market_data_batches_workspace_installation_fk
  FOREIGN KEY (workspace_id, installation_id)
  REFERENCES sf_connector_installations(workspace_id, installation_id)
  ON DELETE CASCADE;

ALTER TABLE sf_operational_events
  ADD CONSTRAINT sf_operational_events_workspace_user_fk
  FOREIGN KEY (workspace_id, user_id)
  REFERENCES sf_workspace_memberships(workspace_id, user_id);

ALTER TABLE sf_service_leases ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_service_leases FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_service_leases_global ON sf_service_leases
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

ALTER TABLE sf_service_heartbeats ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_service_heartbeats FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_service_heartbeats_global ON sf_service_heartbeats
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

ALTER TABLE sf_telegram_updates ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_telegram_updates FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_telegram_updates_global ON sf_telegram_updates
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

ALTER TABLE sf_telegram_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_telegram_outbox FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_telegram_outbox_global ON sf_telegram_outbox
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

ALTER TABLE sf_telegram_bot_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_telegram_bot_state FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_telegram_bot_state_global ON sf_telegram_bot_state
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

ALTER TABLE sf_ai_workspace_budgets ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_ai_workspace_budgets FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_ai_workspace_budgets_scope ON sf_ai_workspace_budgets
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_ai_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_ai_reservations FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_ai_reservations_scope ON sf_ai_reservations
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_ai_usage_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_ai_usage_events FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_ai_usage_events_scope ON sf_ai_usage_events
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_market_data_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_market_data_subscriptions FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_market_data_subscriptions_scope ON sf_market_data_subscriptions
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_market_data_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_market_data_snapshots FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_market_data_snapshots_scope ON sf_market_data_snapshots
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_market_data_ingest_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_market_data_ingest_batches FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_market_data_ingest_batches_scope ON sf_market_data_ingest_batches
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace());

ALTER TABLE sf_operational_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_operational_events FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_operational_events_scope ON sf_operational_events
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace() OR user_id = sf_scope_user())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace() OR user_id = sf_scope_user());

GRANT SELECT, INSERT, UPDATE, DELETE ON
  sf_service_leases, sf_service_heartbeats, sf_telegram_updates,
  sf_telegram_outbox, sf_telegram_bot_state, sf_ai_workspace_budgets, sf_ai_reservations,
  sf_ai_usage_events, sf_market_data_subscriptions, sf_market_data_snapshots,
  sf_market_data_ingest_batches, sf_operational_events
TO stratforge_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO stratforge_app;
