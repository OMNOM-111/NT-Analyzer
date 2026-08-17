-- Phase 5: the two operational fields the registry reports but could not store.
--
-- 0016 created sf_environment_registry before the heartbeat carried
-- market_data and connector. The application then began reporting both, the
-- INSERT had no column to put them in, and every row read back showed them
-- empty -- so the compare view rendered "not reported" for two fields that
-- were, in fact, being reported on every beat.
--
-- Found by reading the live registry rather than by a test: the Python side
-- was self-consistent and only the round trip through the real schema showed
-- the loss.
--
-- Expand-only. Existing rows get the empty default, which is the honest value
-- for a beat that predates the column, and the next heartbeat fills them in.

BEGIN;

-- Scope declared for the same reason as 0014-0016: this migration inserts
-- nothing today, but FORCE ROW LEVEL SECURITY applies to the table owner, so
-- any future backfill added here would be refused by the table's own policy
-- with SQLSTATE 42501.
SET LOCAL stratforge.service_scope = 'global';

-- Which side of the owner market-data gateway an environment is on. Two
-- environments both reporting 'hub' would mean two live provider connections,
-- which the single-lease design exists to prevent -- so this is exactly the
-- kind of disagreement the compare view has to be able to show.
ALTER TABLE sf_environment_registry
  ADD COLUMN IF NOT EXISTS market_data TEXT NOT NULL DEFAULT '';
DO $$
BEGIN
  ALTER TABLE sf_environment_registry
    ADD CONSTRAINT sf_environment_registry_market_data_check
    CHECK (market_data IN ('', 'hub', 'consumer', 'disabled'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Whether the Connector control plane answers in that environment.
ALTER TABLE sf_environment_registry
  ADD COLUMN IF NOT EXISTS connector TEXT NOT NULL DEFAULT '';
DO $$
BEGIN
  ALTER TABLE sf_environment_registry
    ADD CONSTRAINT sf_environment_registry_connector_check
    CHECK (connector IN ('', 'ok', 'degraded', 'unavailable'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

COMMIT;
