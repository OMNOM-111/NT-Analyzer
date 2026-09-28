-- Additive server-only Agent World BYOK and shared-model access.
-- Operator migration after a verified backup. No plaintext credential is stored.
CREATE TABLE sf_aw_credentials (
  environment TEXT NOT NULL CHECK(environment IN ('canary','production')),
  workspace_id TEXT NOT NULL CHECK(workspace_id ~ '^ws_[A-Za-z0-9_-]{8,80}$'),
  owner_uuid UUID NOT NULL,
  account_id UUID NOT NULL,
  nonce BYTEA NOT NULL CHECK(octet_length(nonce)=12),
  ciphertext BYTEA NOT NULL CHECK(octet_length(ciphertext) BETWEEN 24 AND 8192),
  PRIMARY KEY(environment,workspace_id,account_id)
);
ALTER TABLE sf_aw_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_aw_credentials FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_aw_credential_owner ON sf_aw_credentials
  USING(sf_aw_scope_ok(environment,workspace_id) AND owner_uuid=sf_aw_user_uuid())
  WITH CHECK(sf_aw_scope_ok(environment,workspace_id) AND owner_uuid=sf_aw_user_uuid());
REVOKE ALL ON sf_aw_credentials FROM PUBLIC,stratforge_app;
GRANT SELECT,INSERT,DELETE ON sf_aw_credentials TO stratforge_app;

CREATE TABLE sf_aw_model_shares (
  environment TEXT NOT NULL CHECK(environment IN ('canary','production')),
  owner_workspace_id TEXT NOT NULL CHECK(owner_workspace_id ~ '^ws_[A-Za-z0-9_-]{8,80}$'),
  owner_user_uuid UUID NOT NULL,
  model_id UUID NOT NULL,
  label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 80),
  provider TEXT NOT NULL CHECK(length(provider) BETWEEN 1 AND 80),
  model_key TEXT NOT NULL CHECK(length(model_key) BETWEEN 1 AND 120),
  credential_source TEXT NOT NULL CHECK(credential_source='user_supplied'),
  shared BOOLEAN NOT NULL,
  revision BIGINT NOT NULL CHECK(revision>0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(environment,model_id)
);
CREATE INDEX sf_aw_model_shares_active ON sf_aw_model_shares(environment,label,model_id) WHERE shared;
ALTER TABLE sf_aw_model_shares ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_aw_model_shares FORCE ROW LEVEL SECURITY;
-- Only an authenticated, scoped owner may change a share. A live descriptor
-- is readable by any authenticated user; never contains credential/endpoint.
CREATE POLICY sf_aw_share_read ON sf_aw_model_shares FOR SELECT USING (
  current_setting('stratforge.aw_environment',true)=environment
  AND sf_aw_user_uuid() IS NOT NULL
  AND current_setting('stratforge.service_scope',true) IN ('scoped','global')
  AND (shared OR owner_user_uuid=sf_aw_user_uuid()));
CREATE POLICY sf_aw_share_insert ON sf_aw_model_shares FOR INSERT WITH CHECK (
  sf_aw_scope_ok(environment,owner_workspace_id) AND owner_user_uuid=sf_aw_user_uuid());
CREATE POLICY sf_aw_share_update ON sf_aw_model_shares FOR UPDATE
  USING(sf_aw_scope_ok(environment,owner_workspace_id) AND owner_user_uuid=sf_aw_user_uuid())
  WITH CHECK(sf_aw_scope_ok(environment,owner_workspace_id) AND owner_user_uuid=sf_aw_user_uuid());
REVOKE ALL ON sf_aw_model_shares FROM PUBLIC,stratforge_app;
GRANT SELECT,INSERT,UPDATE ON sf_aw_model_shares TO stratforge_app;

CREATE TABLE sf_aw_model_share_events (
  event_id BIGSERIAL PRIMARY KEY,
  environment TEXT NOT NULL CHECK(environment IN ('canary','production')),
  owner_workspace_id TEXT NOT NULL,
  owner_user_uuid UUID NOT NULL,
  model_id UUID NOT NULL,
  shared BOOLEAN NOT NULL,
  at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY(environment,model_id) REFERENCES sf_aw_model_shares(environment,model_id)
);
ALTER TABLE sf_aw_model_share_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_aw_model_share_events FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_aw_share_event_owner ON sf_aw_model_share_events
  USING(sf_aw_scope_ok(environment,owner_workspace_id) AND owner_user_uuid=sf_aw_user_uuid())
  WITH CHECK(sf_aw_scope_ok(environment,owner_workspace_id) AND owner_user_uuid=sf_aw_user_uuid());
REVOKE ALL ON sf_aw_model_share_events FROM PUBLIC,stratforge_app;
GRANT SELECT,INSERT ON sf_aw_model_share_events TO stratforge_app;
GRANT USAGE ON SEQUENCE sf_aw_model_share_events_event_id_seq TO stratforge_app;

CREATE TABLE sf_aw_model_calls (
  environment TEXT NOT NULL CHECK(environment IN ('canary','production')),
  request_id TEXT NOT NULL CHECK(length(request_id) BETWEEN 1 AND 160),
  model_id UUID NOT NULL,
  owner_user_uuid UUID NOT NULL,
  owner_workspace_id TEXT NOT NULL,
  caller_user_uuid UUID NOT NULL,
  caller_workspace_id TEXT NOT NULL,
  caller_name TEXT NOT NULL DEFAULT '',
  task TEXT NOT NULL DEFAULT '', agent TEXT NOT NULL DEFAULT '', purpose TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '', input_tokens BIGINT NOT NULL DEFAULT 0,
  output_tokens BIGINT NOT NULL DEFAULT 0, cost_usd NUMERIC(12,6),
  cost_known BOOLEAN NOT NULL DEFAULT FALSE, at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(environment,request_id),
  FOREIGN KEY(environment,model_id) REFERENCES sf_aw_model_shares(environment,model_id)
);
CREATE INDEX sf_aw_model_calls_owner ON sf_aw_model_calls(environment,owner_user_uuid,at DESC);
CREATE INDEX sf_aw_model_calls_caller ON sf_aw_model_calls(environment,caller_user_uuid,at DESC);
ALTER TABLE sf_aw_model_calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_aw_model_calls FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_aw_call_read ON sf_aw_model_calls FOR SELECT USING (
  current_setting('stratforge.aw_environment',true)=environment AND sf_aw_user_uuid() IS NOT NULL
  AND current_setting('stratforge.service_scope',true) IN ('scoped','global')
  AND (owner_user_uuid=sf_aw_user_uuid() OR caller_user_uuid=sf_aw_user_uuid()));
CREATE POLICY sf_aw_call_insert ON sf_aw_model_calls FOR INSERT WITH CHECK (
  sf_aw_scope_ok(environment,caller_workspace_id) AND caller_user_uuid=sf_aw_user_uuid());
REVOKE ALL ON sf_aw_model_calls FROM PUBLIC,stratforge_app;
GRANT SELECT,INSERT ON sf_aw_model_calls TO stratforge_app;
