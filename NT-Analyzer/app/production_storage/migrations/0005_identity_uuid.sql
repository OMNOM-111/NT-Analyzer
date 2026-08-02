-- Phase 3: UUID identity expand/backfill only.
-- BIGINT keys remain authoritative compatibility references until a separately
-- approved contract phase with backup and isolated restore evidence.

-- This deterministic mapping is used only when an older row has no canonical
-- UUID yet. New application writes supply their already-created UUID directly.
CREATE OR REPLACE FUNCTION sf_identity_uuid_v1(identity_key TEXT)
RETURNS UUID
LANGUAGE SQL
IMMUTABLE
STRICT
PARALLEL SAFE
AS $$
  SELECT (
    substr(md5('stratforge/identity/v1/' || identity_key), 1, 8) || '-' ||
    substr(md5('stratforge/identity/v1/' || identity_key), 9, 4) || '-' ||
    substr(md5('stratforge/identity/v1/' || identity_key), 13, 4) || '-' ||
    substr(md5('stratforge/identity/v1/' || identity_key), 17, 4) || '-' ||
    substr(md5('stratforge/identity/v1/' || identity_key), 21, 12)
  )::uuid
$$;

ALTER TABLE sf_users ADD COLUMN IF NOT EXISTS user_uuid UUID;

UPDATE sf_users
SET user_uuid = sf_identity_uuid_v1('user:' || user_id::text)
WHERE user_uuid IS NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'sf_users_user_uuid_uniq'
  ) THEN
    ALTER TABLE sf_users
      ADD CONSTRAINT sf_users_user_uuid_uniq UNIQUE (user_uuid);
  END IF;
END $$;

CREATE OR REPLACE FUNCTION sf_identity_assign_user_uuid()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.user_uuid IS NULL THEN
    NEW.user_uuid := sf_identity_uuid_v1('user:' || NEW.user_id::text);
  END IF;
  RETURN NEW;
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'sf_users_identity_uuid_dual_write'
  ) THEN
    CREATE TRIGGER sf_users_identity_uuid_dual_write
      BEFORE INSERT OR UPDATE ON sf_users
      FOR EACH ROW EXECUTE FUNCTION sf_identity_assign_user_uuid();
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS sf_auth_identities (
  identity_id UUID PRIMARY KEY,
  user_uuid UUID NOT NULL REFERENCES sf_users(user_uuid) ON DELETE RESTRICT,
  legacy_user_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE RESTRICT,
  provider TEXT NOT NULL CHECK (provider IN ('telegram', 'google', 'email')),
  provider_subject TEXT NOT NULL CHECK (length(provider_subject) BETWEEN 1 AND 255),
  normalized_email TEXT,
  verified_at TIMESTAMPTZ,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  last_used_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  document JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object'),
  UNIQUE (provider, provider_subject)
);

CREATE INDEX IF NOT EXISTS sf_auth_identities_user_uuid_idx
  ON sf_auth_identities(user_uuid, provider);

CREATE UNIQUE INDEX IF NOT EXISTS sf_auth_identities_verified_email_uidx
  ON sf_auth_identities(normalized_email)
  WHERE provider = 'email' AND revoked_at IS NULL AND normalized_email IS NOT NULL;

-- Existing Telegram users keep their legacy account/session/workspace keys and
-- gain a provider mapping. Existing profile email is deliberately not promoted
-- to a login identity: an email login requires an independent OTP proof.
INSERT INTO sf_auth_identities(
  identity_id, user_uuid, legacy_user_id, provider, provider_subject,
  verified_at, linked_at, document
)
SELECT
  sf_identity_uuid_v1('telegram:' || COALESCE(NULLIF(u.document->>'telegram_user_id', ''), u.user_id::text)),
  u.user_uuid,
  u.user_id,
  'telegram',
  COALESCE(NULLIF(u.document->>'telegram_user_id', ''), u.user_id::text),
  COALESCE(u.created_at, clock_timestamp()),
  COALESCE(u.created_at, clock_timestamp()),
  jsonb_build_object('source', 'phase3_backfill')
FROM sf_users AS u
WHERE u.user_uuid IS NOT NULL
  AND COALESCE(NULLIF(u.document->>'telegram_user_id', ''), u.user_id::text) ~ '^[1-9][0-9]{0,19}$'
ON CONFLICT (provider, provider_subject) DO UPDATE SET
  legacy_user_id = EXCLUDED.legacy_user_id,
  last_used_at = sf_auth_identities.last_used_at
WHERE sf_auth_identities.user_uuid = EXCLUDED.user_uuid;

-- A previously linked Google subject is preserved as a separate provider
-- identity. Conflicts with a different UUID are not merged by this migration.
INSERT INTO sf_auth_identities(
  identity_id, user_uuid, legacy_user_id, provider, provider_subject,
  normalized_email, verified_at, linked_at, document
)
SELECT
  sf_identity_uuid_v1('google:' || NULLIF(u.document->>'google_sub', '')),
  u.user_uuid,
  u.user_id,
  'google',
  NULLIF(u.document->>'google_sub', ''),
  NULLIF(lower(u.document->>'google_email'), ''),
  COALESCE(u.updated_at, u.created_at, clock_timestamp()),
  COALESCE(u.updated_at, u.created_at, clock_timestamp()),
  jsonb_build_object('source', 'phase3_google_backfill')
FROM sf_users AS u
WHERE u.user_uuid IS NOT NULL
  AND NULLIF(u.document->>'google_sub', '') IS NOT NULL
ON CONFLICT (provider, provider_subject) DO UPDATE SET
  legacy_user_id = EXCLUDED.legacy_user_id,
  last_used_at = sf_auth_identities.last_used_at
WHERE sf_auth_identities.user_uuid = EXCLUDED.user_uuid;

ALTER TABLE sf_auth_challenges ADD COLUMN IF NOT EXISTS user_uuid UUID;
ALTER TABLE sf_auth_sessions ADD COLUMN IF NOT EXISTS user_uuid UUID;
ALTER TABLE sf_workspaces ADD COLUMN IF NOT EXISTS owner_user_uuid UUID;
ALTER TABLE sf_workspace_memberships ADD COLUMN IF NOT EXISTS user_uuid UUID;
ALTER TABLE sf_active_workspaces ADD COLUMN IF NOT EXISTS user_uuid UUID;
ALTER TABLE sf_connections ADD COLUMN IF NOT EXISTS user_uuid UUID;
ALTER TABLE sf_entitlements ADD COLUMN IF NOT EXISTS user_uuid UUID;
ALTER TABLE sf_connector_installations ADD COLUMN IF NOT EXISTS user_uuid UUID;
ALTER TABLE sf_jobs ADD COLUMN IF NOT EXISTS user_uuid UUID;
ALTER TABLE sf_commands ADD COLUMN IF NOT EXISTS user_uuid UUID;
ALTER TABLE sf_audit_events ADD COLUMN IF NOT EXISTS user_uuid UUID;
ALTER TABLE sf_artifacts ADD COLUMN IF NOT EXISTS user_uuid UUID;
ALTER TABLE sf_migration_runs ADD COLUMN IF NOT EXISTS owner_user_uuid UUID;
ALTER TABLE sf_ai_reservations ADD COLUMN IF NOT EXISTS user_uuid UUID;
ALTER TABLE sf_ai_usage_events ADD COLUMN IF NOT EXISTS user_uuid UUID;
ALTER TABLE sf_market_data_subscriptions ADD COLUMN IF NOT EXISTS requested_by_user_uuid UUID;
ALTER TABLE sf_operational_events ADD COLUMN IF NOT EXISTS user_uuid UUID;

UPDATE sf_auth_challenges AS target SET user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.user_uuid IS NULL AND target.user_id = users.user_id;
UPDATE sf_auth_sessions AS target SET user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.user_uuid IS NULL AND target.user_id = users.user_id;
UPDATE sf_workspaces AS target SET owner_user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.owner_user_uuid IS NULL AND target.owner_user_id = users.user_id;
UPDATE sf_workspace_memberships AS target SET user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.user_uuid IS NULL AND target.user_id = users.user_id;
UPDATE sf_active_workspaces AS target SET user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.user_uuid IS NULL AND target.user_id = users.user_id;
UPDATE sf_connections AS target SET user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.user_uuid IS NULL AND target.user_id = users.user_id;
UPDATE sf_entitlements AS target SET user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.user_uuid IS NULL AND target.user_id = users.user_id;
UPDATE sf_connector_installations AS target SET user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.user_uuid IS NULL AND target.user_id = users.user_id;
UPDATE sf_jobs AS target SET user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.user_uuid IS NULL AND target.user_id = users.user_id;
UPDATE sf_commands AS target SET user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.user_uuid IS NULL AND target.user_id = users.user_id;
UPDATE sf_audit_events AS target SET user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.user_uuid IS NULL AND target.user_id = users.user_id;
UPDATE sf_artifacts AS target SET user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.user_uuid IS NULL AND target.user_id = users.user_id;
UPDATE sf_migration_runs AS target SET owner_user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.owner_user_uuid IS NULL AND target.owner_user_id = users.user_id;
UPDATE sf_ai_reservations AS target SET user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.user_uuid IS NULL AND target.user_id = users.user_id;
UPDATE sf_ai_usage_events AS target SET user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.user_uuid IS NULL AND target.user_id = users.user_id;
UPDATE sf_market_data_subscriptions AS target SET requested_by_user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.requested_by_user_uuid IS NULL AND target.requested_by_user_id = users.user_id;
UPDATE sf_operational_events AS target SET user_uuid = users.user_uuid
FROM sf_users AS users
WHERE target.user_uuid IS NULL AND target.user_id = users.user_id;

CREATE OR REPLACE FUNCTION sf_identity_fill_user_uuid()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.user_id IS NOT NULL THEN
    SELECT user_uuid INTO NEW.user_uuid FROM sf_users WHERE user_id = NEW.user_id;
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION sf_identity_fill_owner_user_uuid()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.owner_user_id IS NOT NULL THEN
    SELECT user_uuid INTO NEW.owner_user_uuid
    FROM sf_users WHERE user_id = NEW.owner_user_id;
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION sf_identity_fill_requested_user_uuid()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.requested_by_user_id IS NOT NULL THEN
    SELECT user_uuid INTO NEW.requested_by_user_uuid
    FROM sf_users WHERE user_id = NEW.requested_by_user_id;
  END IF;
  RETURN NEW;
END;
$$;

DO $$
DECLARE
  table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'sf_auth_challenges', 'sf_auth_sessions', 'sf_workspace_memberships',
    'sf_active_workspaces', 'sf_connections', 'sf_entitlements',
    'sf_connector_installations', 'sf_jobs', 'sf_commands',
    'sf_audit_events', 'sf_artifacts', 'sf_ai_reservations',
    'sf_ai_usage_events', 'sf_operational_events'
  ] LOOP
    IF NOT EXISTS (
      SELECT 1 FROM pg_trigger
      WHERE tgname = 'sf_identity_dual_write_' || table_name
    ) THEN
      EXECUTE format(
        'CREATE TRIGGER %I BEFORE INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION sf_identity_fill_user_uuid()',
        'sf_identity_dual_write_' || table_name,
        table_name
      );
    END IF;
  END LOOP;
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'sf_identity_dual_write_sf_workspaces'
  ) THEN
    CREATE TRIGGER sf_identity_dual_write_sf_workspaces
      BEFORE INSERT OR UPDATE ON sf_workspaces
      FOR EACH ROW EXECUTE FUNCTION sf_identity_fill_owner_user_uuid();
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'sf_identity_dual_write_sf_migration_runs'
  ) THEN
    CREATE TRIGGER sf_identity_dual_write_sf_migration_runs
      BEFORE INSERT OR UPDATE ON sf_migration_runs
      FOR EACH ROW EXECUTE FUNCTION sf_identity_fill_owner_user_uuid();
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'sf_identity_dual_write_sf_market_data_subscriptions'
  ) THEN
    CREATE TRIGGER sf_identity_dual_write_sf_market_data_subscriptions
      BEFORE INSERT OR UPDATE ON sf_market_data_subscriptions
      FOR EACH ROW EXECUTE FUNCTION sf_identity_fill_requested_user_uuid();
  END IF;
END $$;

DO $$
DECLARE
  table_name TEXT;
  constraint_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'sf_auth_challenges', 'sf_auth_sessions', 'sf_workspace_memberships',
    'sf_active_workspaces', 'sf_connections', 'sf_entitlements',
    'sf_connector_installations', 'sf_jobs', 'sf_commands',
    'sf_audit_events', 'sf_artifacts', 'sf_ai_reservations',
    'sf_ai_usage_events', 'sf_operational_events'
  ] LOOP
    constraint_name := 'sf_identity_' || table_name || '_user_uuid_fk';
    IF NOT EXISTS (
      SELECT 1 FROM pg_constraint WHERE conname = constraint_name
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (user_uuid) REFERENCES sf_users(user_uuid) NOT VALID',
        table_name,
        constraint_name
      );
    END IF;
  END LOOP;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'sf_identity_sf_workspaces_owner_user_uuid_fk'
  ) THEN
    ALTER TABLE sf_workspaces
      ADD CONSTRAINT sf_identity_sf_workspaces_owner_user_uuid_fk
      FOREIGN KEY (owner_user_uuid) REFERENCES sf_users(user_uuid) NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'sf_identity_sf_migration_runs_owner_user_uuid_fk'
  ) THEN
    ALTER TABLE sf_migration_runs
      ADD CONSTRAINT sf_identity_sf_migration_runs_owner_user_uuid_fk
      FOREIGN KEY (owner_user_uuid) REFERENCES sf_users(user_uuid) NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'sf_identity_sf_market_data_requested_user_uuid_fk'
  ) THEN
    ALTER TABLE sf_market_data_subscriptions
      ADD CONSTRAINT sf_identity_sf_market_data_requested_user_uuid_fk
      FOREIGN KEY (requested_by_user_uuid) REFERENCES sf_users(user_uuid) NOT VALID;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS sf_auth_sessions_user_uuid_active_idx
  ON sf_auth_sessions(user_uuid, revoked, expires_at)
  WHERE user_uuid IS NOT NULL;
CREATE INDEX IF NOT EXISTS sf_workspace_memberships_user_uuid_idx
  ON sf_workspace_memberships(user_uuid, revoked_at)
  WHERE user_uuid IS NOT NULL;
CREATE INDEX IF NOT EXISTS sf_connector_installations_user_uuid_idx
  ON sf_connector_installations(user_uuid, status, updated_at DESC)
  WHERE user_uuid IS NOT NULL;
CREATE INDEX IF NOT EXISTS sf_audit_events_user_uuid_time_idx
  ON sf_audit_events(user_uuid, occurred_at DESC)
  WHERE user_uuid IS NOT NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON sf_auth_identities TO stratforge_app;