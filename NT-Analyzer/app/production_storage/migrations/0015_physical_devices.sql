-- Phase 5: separate the physical machine from the clients running on it.
--
-- Until now sf_trusted_devices was a single flat level that meant "a browser
-- profile" for the web app and "an installation" for the Connector. Those are
-- not the same kind of thing: three browser profiles on one workstation are
-- three independent credentials but one machine, and the security question
-- "revoke that laptop" could not be expressed at all.
--
-- The model is now Physical device -> client -> session:
--
--   sf_physical_devices   one real machine, identified only by a hardware-bound
--                         credential the Windows Connector holds.
--   sf_trusted_devices    one browser profile or one app installation, now
--                         optionally bound to a machine. Unchanged otherwise.
--   sf_auth_sessions      unchanged; a session still references its client.
--
-- A machine is never inferred. User-Agent, IP, hostname and account name are
-- identical across every user of a deployment and change on their own, so
-- joining clients by them both split one machine into many and merged
-- different people's machines into one. The only way a client joins a machine
-- is an explicit binding attested by an already-trusted Connector on that
-- machine.
--
-- Expand-only. sf_trusted_devices gains a nullable column and keeps every
-- existing row, id, status, timestamp and audit reference: a client that
-- belongs to no known machine is a normal, fully functional state, which is
-- exactly what every pre-existing row becomes.

BEGIN;

-- FORCE ROW LEVEL SECURITY covers the table owner too, so the backfill at the
-- bottom is checked against this migration's own policy. Without a declared
-- scope the WITH CHECK is false and the migration is refused by its own rules
-- (SQLSTATE 42501). SET LOCAL, so it lasts exactly this transaction and grants
-- the runtime role nothing. Same reasoning as 0014.
SET LOCAL stratforge.service_scope = 'global';

CREATE TABLE IF NOT EXISTS sf_physical_devices (
  physical_device_id UUID PRIMARY KEY,
  user_uuid UUID NOT NULL REFERENCES sf_users(user_uuid) ON DELETE CASCADE,
  legacy_user_id BIGINT NOT NULL REFERENCES sf_users(user_id) ON DELETE CASCADE,
  -- Digest of the Connector's hardware-bound credential, folded with the
  -- account UUID. Never the credential itself, never a fingerprint assembled
  -- from request headers.
  machine_key_hash TEXT NOT NULL CHECK (length(machine_key_hash) BETWEEN 16 AND 128),
  display_name TEXT NOT NULL DEFAULT '' CHECK (length(display_name) <= 160),
  os_family TEXT NOT NULL DEFAULT '' CHECK (length(os_family) <= 40),
  os_version TEXT NOT NULL DEFAULT '' CHECK (length(os_version) <= 40),
  -- A machine carries its own trust level, independent of its clients: a
  -- trusted laptop can still be running an unconfirmed new browser profile,
  -- and revoking the laptop must not depend on which browser noticed first.
  status TEXT NOT NULL
    CHECK (status IN ('pending', 'trusted', 'revoked', 'expired')),
  confirmation_provider TEXT NOT NULL DEFAULT ''
    CHECK (confirmation_provider IN ('', 'telegram', 'email', 'google')),
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  last_seen_at TIMESTAMPTZ,
  confirmed_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  -- Masked, coarse audit metadata only. Never identity.
  audit_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(audit_metadata) = 'object'),
  CHECK ((status = 'revoked') = (revoked_at IS NOT NULL)),
  CHECK (status <> 'trusted' OR confirmed_at IS NOT NULL)
);

-- One machine credential maps to at most one live machine record per account.
-- Revoked and expired rows are excluded so a rejected machine can never be
-- silently resurrected by presenting the same credential again.
CREATE UNIQUE INDEX IF NOT EXISTS sf_physical_devices_active_key_uidx
  ON sf_physical_devices(user_uuid, machine_key_hash)
  WHERE status IN ('pending', 'trusted');
CREATE INDEX IF NOT EXISTS sf_physical_devices_user_status_idx
  ON sf_physical_devices(user_uuid, status, last_seen_at DESC);

-- ON DELETE SET NULL, not CASCADE: deleting a machine record must not delete
-- the security history of the browser profiles that ran on it. The client
-- survives, unbound, with its whole timeline intact.
ALTER TABLE sf_trusted_devices
  ADD COLUMN IF NOT EXISTS physical_device_id UUID
    REFERENCES sf_physical_devices(physical_device_id) ON DELETE SET NULL;

-- How the binding was established, so an operator can tell an attested pairing
-- from the Connector's own self-registration. There is no third way to get a
-- non-empty value here.
ALTER TABLE sf_trusted_devices
  ADD COLUMN IF NOT EXISTS bound_via TEXT NOT NULL DEFAULT '';
DO $$
BEGIN
  ALTER TABLE sf_trusted_devices
    ADD CONSTRAINT sf_trusted_devices_bound_via_check
    CHECK (bound_via IN ('', 'connector_self', 'attested_pairing'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TABLE sf_trusted_devices
    ADD CONSTRAINT sf_trusted_devices_binding_origin_check
    CHECK ((physical_device_id IS NULL) = (bound_via = ''));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS sf_trusted_devices_physical_idx
  ON sf_trusted_devices(physical_device_id)
  WHERE physical_device_id IS NOT NULL;

ALTER TABLE sf_physical_devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_physical_devices FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_physical_devices_scope ON sf_physical_devices;
CREATE POLICY sf_physical_devices_scope ON sf_physical_devices
  USING (sf_scope_global() OR legacy_user_id = sf_scope_user())
  WITH CHECK (sf_scope_global() OR legacy_user_id = sf_scope_user());

GRANT SELECT, INSERT, UPDATE, DELETE ON sf_physical_devices TO stratforge_app;

-- Backfill: every existing Connector client already carries a stable
-- installation id, which is exactly the hardware-bound credential this model
-- is built on. Each becomes a machine, and the client that produced it is
-- bound to it as 'connector_self'.
--
-- The machine inherits the client's real timeline rather than starting today,
-- so a Connector trusted six months ago does not appear as a machine first
-- seen at migration time. Browser clients are deliberately left unbound: there
-- is no evidence of which machine they ran on, and inventing one is the exact
-- guess this model exists to remove.
INSERT INTO sf_physical_devices(
  physical_device_id, user_uuid, legacy_user_id, machine_key_hash, display_name,
  os_family, os_version, status, confirmation_provider,
  first_seen_at, last_seen_at, confirmed_at, revoked_at, expires_at, audit_metadata
)
SELECT
  gen_random_uuid(),
  d.user_uuid,
  d.legacy_user_id,
  -- Built-in sha256(bytea), so this needs no pgcrypto and no extension
  -- privilege. The separator is '|' rather than a NUL because PostgreSQL text
  -- cannot carry a NUL byte; the UUID between the separators is fixed-length,
  -- so the encoding stays unambiguous. app/physical_devices.py computes this
  -- byte for byte -- if the two ever diverge, a Connector already known here
  -- would register as a second machine.
  encode(sha256(convert_to('machine-key/v1|' || d.user_uuid::text || '|'
                           || d.connector_installation_id, 'UTF8')), 'hex'),
  COALESCE(NULLIF(d.display_name, ''), 'NinjaTrader Connector'),
  d.os_family,
  d.os_version,
  d.status,
  d.confirmation_provider,
  d.first_seen_at,
  d.last_seen_at,
  d.confirmed_at,
  d.revoked_at,
  d.expires_at,
  d.audit_metadata
FROM sf_trusted_devices d
WHERE d.device_type = 'connector'
  AND d.connector_installation_id <> ''
  AND d.physical_device_id IS NULL
  -- One row per (account, machine credential): if the same installation was
  -- registered twice, the newest active record wins and the older one is bound
  -- to the same machine below.
  AND d.device_id = (
    SELECT e.device_id FROM sf_trusted_devices e
    WHERE e.user_uuid = d.user_uuid
      AND e.connector_installation_id = d.connector_installation_id
      AND e.device_type = 'connector'
    ORDER BY (e.status IN ('pending', 'trusted')) DESC,
             e.last_seen_at DESC NULLS LAST, e.first_seen_at DESC
    LIMIT 1
  );

UPDATE sf_trusted_devices d
SET physical_device_id = p.physical_device_id,
    bound_via = 'connector_self'
FROM sf_physical_devices p
WHERE d.physical_device_id IS NULL
  AND d.device_type = 'connector'
  AND d.connector_installation_id <> ''
  AND p.user_uuid = d.user_uuid
  AND p.machine_key_hash = encode(sha256(convert_to(
        'machine-key/v1|' || d.user_uuid::text || '|'
        || d.connector_installation_id, 'UTF8')), 'hex');

COMMIT;
