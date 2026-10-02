-- beta.107: account deletion receipts and anonymized metering retention.
-- The application performs the scoped, ordered erasure. No generic CASCADE is
-- added for user-private domain records, and no RLS bypass is introduced.

BEGIN;
SET LOCAL stratforge.service_scope = 'global';

CREATE TABLE sf_deleted_accounts (
  user_uuid UUID PRIMARY KEY,
  legacy_user_id BIGINT NOT NULL UNIQUE,
  identifier_fingerprint TEXT NOT NULL CHECK(identifier_fingerprint ~ '^[0-9a-f]{64}$'),
  created_at_utc TIMESTAMPTZ,
  deleted_at_utc TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  reason TEXT NOT NULL CHECK(reason IN ('self_requested','owner_requested')),
  account_type TEXT NOT NULL DEFAULT 'real' CHECK(account_type='real'),
  security_flags JSONB NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(security_flags)='object')
);
ALTER TABLE sf_deleted_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_deleted_accounts FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_deleted_accounts_service ON sf_deleted_accounts
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());
REVOKE ALL ON sf_deleted_accounts FROM PUBLIC,stratforge_app;
GRANT SELECT,INSERT ON sf_deleted_accounts TO stratforge_app;

-- Files remain an isolated object payload layer; only PostgreSQL metadata
-- authorizes their deletion. A crash after commit leaves a retryable cleanup
-- entry rather than an untracked private file or a guessed recursive purge.
CREATE TABLE sf_account_erasure_objects (
  user_uuid UUID NOT NULL REFERENCES sf_deleted_accounts(user_uuid),
  category TEXT NOT NULL CHECK(category IN (
    'artifact','sf_chat','community','avatar','tenant','orchestrator_scope')),
  object_key TEXT NOT NULL CHECK(length(object_key) BETWEEN 1 AND 500),
  sha256 TEXT CHECK(sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'),
  completed_at TIMESTAMPTZ,
  PRIMARY KEY(user_uuid,category,object_key)
);
ALTER TABLE sf_account_erasure_objects ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_account_erasure_objects FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_account_erasure_objects_service ON sf_account_erasure_objects
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());
REVOKE ALL ON sf_account_erasure_objects FROM PUBLIC,stratforge_app;
GRANT SELECT,INSERT,UPDATE(completed_at) ON sf_account_erasure_objects TO stratforge_app;

-- Metering totals outlive a private account/workspace. Remove live FK targets
-- and private JSON content during the erasure transaction, not via cascade.
ALTER TABLE sf_ai_usage_events
  DROP CONSTRAINT sf_ai_usage_events_workspace_user_fk,
  DROP CONSTRAINT sf_ai_usage_events_user_id_fkey,
  DROP CONSTRAINT sf_ai_usage_events_workspace_id_fkey,
  DROP CONSTRAINT sf_identity_sf_ai_usage_events_user_uuid_fk;
ALTER TABLE sf_ai_usage_events
  ALTER COLUMN user_id DROP NOT NULL,
  ALTER COLUMN workspace_id DROP NOT NULL,
  ADD COLUMN deleted_user_fingerprint TEXT
    CHECK(deleted_user_fingerprint IS NULL OR deleted_user_fingerprint ~ '^[0-9a-f]{64}$');
ALTER TABLE sf_ai_usage_events
  ADD CONSTRAINT sf_ai_usage_events_user_id_fkey
    FOREIGN KEY(user_id) REFERENCES sf_users(user_id) ON DELETE SET NULL,
  ADD CONSTRAINT sf_ai_usage_events_workspace_id_fkey
    FOREIGN KEY(workspace_id) REFERENCES sf_workspaces(workspace_id) ON DELETE SET NULL,
  ADD CONSTRAINT sf_identity_sf_ai_usage_events_user_uuid_fk
    FOREIGN KEY(user_uuid) REFERENCES sf_users(user_uuid) ON DELETE SET NULL;

-- Identity history is retained, but a deleted identity must no longer be
-- active or pending. The existing global RLS policy still controls the row.
GRANT SELECT(user_uuid,state),UPDATE(state,valid_to,replacement_reason)
  ON sf_identity_history TO stratforge_app;

-- Scoped erasure may remove only the authenticated owner's Agent World data.
CREATE POLICY sf_aw_record_delete ON sf_aw_records FOR DELETE
  USING(sf_aw_scope_ok(environment,workspace_id) AND owner_uuid=sf_aw_user_uuid());
CREATE POLICY sf_aw_revision_delete ON sf_aw_revisions FOR DELETE
  USING(sf_aw_scope_ok(environment,workspace_id) AND owner_uuid=sf_aw_user_uuid());
CREATE POLICY sf_aw_artifact_delete ON sf_aw_artifacts FOR DELETE
  USING(sf_aw_scope_ok(environment,workspace_id) AND owner_uuid=sf_aw_user_uuid());
GRANT DELETE ON sf_aw_records,sf_aw_revisions,sf_aw_artifacts,
  sf_aw_events,sf_aw_outbox,sf_aw_mutations,sf_aw_inbox TO stratforge_app;

-- Preserve historical calls but remove a departed caller's display name.
CREATE POLICY sf_aw_call_anonymize ON sf_aw_model_calls FOR UPDATE
  USING(sf_aw_scope_ok(environment,caller_workspace_id)
    AND caller_user_uuid=sf_aw_user_uuid())
  WITH CHECK(sf_aw_scope_ok(environment,caller_workspace_id)
    AND caller_user_uuid=sf_aw_user_uuid());
GRANT UPDATE(caller_name) ON sf_aw_model_calls TO stratforge_app;

COMMIT;
