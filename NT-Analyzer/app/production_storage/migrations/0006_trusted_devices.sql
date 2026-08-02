-- Phase 4: trusted devices and step-up security challenges.
--
-- Additive expand-only migration. It creates two new, initially empty tables
-- and never rewrites, drops or contracts Phase 1-3 schema. The canonical key is
-- the Phase 3 ``user_uuid``; ``legacy_user_id`` is carried only so the existing
-- BIGINT-based row level security scope keeps working during the compatibility
-- window. No destructive contract is performed here.

CREATE TABLE IF NOT EXISTS sf_trusted_devices (
  device_id UUID PRIMARY KEY,
  user_uuid UUID NOT NULL REFERENCES sf_users(user_uuid) ON DELETE CASCADE,
  legacy_user_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE CASCADE,
  -- Server-side correlation digest only. Never a full device fingerprint and
  -- never a client-supplied identifier.
  fingerprint TEXT NOT NULL CHECK (length(fingerprint) BETWEEN 1 AND 128),
  device_type TEXT NOT NULL
    CHECK (device_type IN ('phone', 'tablet', 'desktop', 'browser', 'connector')),
  display_name TEXT NOT NULL DEFAULT '' CHECK (length(display_name) <= 160),
  os_family TEXT NOT NULL DEFAULT '' CHECK (length(os_family) <= 40),
  os_version TEXT NOT NULL DEFAULT '' CHECK (length(os_version) <= 40),
  client TEXT NOT NULL DEFAULT '' CHECK (length(client) <= 80),
  app_version TEXT NOT NULL DEFAULT '' CHECK (length(app_version) <= 80),
  connector_installation_id TEXT NOT NULL DEFAULT '' CHECK (length(connector_installation_id) <= 128),
  status TEXT NOT NULL
    CHECK (status IN ('pending', 'trusted', 'revoked', 'expired')),
  confirmation_provider TEXT NOT NULL DEFAULT ''
    CHECK (confirmation_provider IN ('', 'telegram', 'email', 'google')),
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  last_seen_at TIMESTAMPTZ,
  last_auth_at TIMESTAMPTZ,
  confirmed_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  -- IP/region live here only, masked, as retained audit metadata. Never used as
  -- device identity and never the sole proof of a device.
  audit_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(audit_metadata) = 'object')
);

CREATE INDEX IF NOT EXISTS sf_trusted_devices_user_status_idx
  ON sf_trusted_devices(user_uuid, status, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS sf_trusted_devices_legacy_user_idx
  ON sf_trusted_devices(legacy_user_id, status);
-- Correlate a session's server-side fingerprint to at most one active device
-- per account. Revoked/expired records are excluded so a rejected device can
-- never be silently reused.
CREATE UNIQUE INDEX IF NOT EXISTS sf_trusted_devices_active_fingerprint_uidx
  ON sf_trusted_devices(user_uuid, fingerprint)
  WHERE status IN ('pending', 'trusted');

CREATE TABLE IF NOT EXISTS sf_security_challenges (
  challenge_id TEXT PRIMARY KEY CHECK (length(challenge_id) BETWEEN 8 AND 128),
  user_uuid UUID NOT NULL REFERENCES sf_users(user_uuid) ON DELETE CASCADE,
  legacy_user_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE CASCADE,
  device_id UUID REFERENCES sf_trusted_devices(device_id) ON DELETE CASCADE,
  purpose TEXT NOT NULL
    CHECK (purpose IN ('device_confirm', 'step_up', 'revoke')),
  provider TEXT NOT NULL
    CHECK (provider IN ('telegram', 'email', 'google')),
  -- The challenge is bound to the deployment environment it was issued in and
  -- cannot be replayed across environments.
  environment TEXT NOT NULL
    CHECK (environment IN ('development', 'canary', 'production')),
  -- Only a salted PBKDF2 hash of the one-time code is stored; the code itself
  -- is never persisted.
  code_hash TEXT NOT NULL CHECK (length(code_hash) BETWEEN 1 AND 256),
  code_salt TEXT NOT NULL CHECK (length(code_salt) BETWEEN 1 AND 128),
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'consumed', 'failed', 'expired')),
  attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 20),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  expires_at TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS sf_security_challenges_user_status_idx
  ON sf_security_challenges(user_uuid, status, expires_at DESC);
CREATE INDEX IF NOT EXISTS sf_security_challenges_device_idx
  ON sf_security_challenges(device_id)
  WHERE device_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS sf_security_challenges_expiry_idx
  ON sf_security_challenges(expires_at);

ALTER TABLE sf_trusted_devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_trusted_devices FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_trusted_devices_scope ON sf_trusted_devices;
CREATE POLICY sf_trusted_devices_scope ON sf_trusted_devices
  USING (sf_scope_global() OR legacy_user_id = sf_scope_user())
  WITH CHECK (sf_scope_global() OR legacy_user_id = sf_scope_user());

ALTER TABLE sf_security_challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_security_challenges FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_security_challenges_scope ON sf_security_challenges;
CREATE POLICY sf_security_challenges_scope ON sf_security_challenges
  USING (sf_scope_global() OR legacy_user_id = sf_scope_user())
  WITH CHECK (sf_scope_global() OR legacy_user_id = sf_scope_user());

GRANT SELECT, INSERT, UPDATE, DELETE ON sf_trusted_devices TO stratforge_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON sf_security_challenges TO stratforge_app;
