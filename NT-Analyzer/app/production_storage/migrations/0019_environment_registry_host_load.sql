-- Host load the registry reports but could not store.
--
-- The release panel shows CPU, RAM and disk for each environment, and the only
-- honest source is the environment measuring itself and publishing it on its
-- heartbeat. The application now does that; without a column the value would
-- be dropped on the round trip and every server environment would render
-- "нет данных" while faithfully reporting the figures on every beat.
--
-- Exactly the failure 0017 documents for market_data and connector: the Python
-- side self-consistent, and only the trip through the real schema losing it.
--
-- Expand-only. Existing rows get the empty object, which is the honest value
-- for a beat that predates the column, and the next heartbeat fills it in.

BEGIN;

-- Declared for the same reason as 0014-0017: nothing is inserted here, but
-- FORCE ROW LEVEL SECURITY applies to the table owner, so a future backfill
-- added to this file would be refused by the table's own policy.
SET LOCAL stratforge.service_scope = 'global';

-- Percentages only, as measured by that environment: cpu_percent,
-- memory_percent, disk_percent and the reading's source. A key is absent when
-- the environment could not measure it, which is why this is a document rather
-- than three numeric columns -- absent and zero must stay distinguishable.
ALTER TABLE sf_environment_registry
  ADD COLUMN IF NOT EXISTS host JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
  ALTER TABLE sf_environment_registry
    ADD CONSTRAINT sf_environment_registry_host_check
    CHECK (jsonb_typeof(host) = 'object');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

COMMIT;
