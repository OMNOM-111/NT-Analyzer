-- Migration 0001 already owns sf_audit_events.  This migration extends that
-- authoritative table rather than relying on CREATE TABLE IF NOT EXISTS,
-- which would silently leave the Stage 8 audit columns absent.
ALTER TABLE sf_audit_events
  ADD COLUMN IF NOT EXISTS actor TEXT,
  ADD COLUMN IF NOT EXISTS action TEXT,
  ADD COLUMN IF NOT EXISTS resource_type TEXT,
  ADD COLUMN IF NOT EXISTS resource_id TEXT,
  ADD COLUMN IF NOT EXISTS outcome TEXT,
  ADD COLUMN IF NOT EXISTS ip_hash TEXT,
  ADD COLUMN IF NOT EXISTS document JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE sf_audit_events
SET actor = COALESCE(NULLIF(actor, ''), NULLIF(source, ''), 'system'),
    action = COALESCE(
      NULLIF(action, ''),
      LEFT(CONCAT_WS('.', NULLIF(source, ''), NULLIF(event_type, '')), 120),
      'legacy_event'
    ),
    resource_type = COALESCE(NULLIF(resource_type, ''), 'legacy_event'),
    resource_id = COALESCE(resource_id, ''),
    outcome = CASE
      WHEN outcome IN ('success', 'denied', 'error') THEN outcome
      ELSE 'success'
    END,
    ip_hash = COALESCE(ip_hash, ''),
    document = CASE
      WHEN document = '{}'::jsonb THEN COALESCE(payload, '{}'::jsonb)
      ELSE document
    END
WHERE actor IS NULL OR actor = ''
   OR action IS NULL OR action = ''
   OR resource_type IS NULL OR resource_type = ''
   OR resource_id IS NULL
   OR outcome IS NULL
   OR ip_hash IS NULL;

ALTER TABLE sf_audit_events
  ALTER COLUMN actor SET NOT NULL,
  ALTER COLUMN action SET NOT NULL,
  ALTER COLUMN resource_type SET NOT NULL,
  ALTER COLUMN resource_id SET DEFAULT '',
  ALTER COLUMN resource_id SET NOT NULL,
  ALTER COLUMN outcome SET DEFAULT 'success',
  ALTER COLUMN outcome SET NOT NULL,
  ALTER COLUMN ip_hash SET DEFAULT '',
  ALTER COLUMN ip_hash SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'sf_audit_events_actor_length'
  ) THEN
    ALTER TABLE sf_audit_events ADD CONSTRAINT sf_audit_events_actor_length
      CHECK (length(actor) BETWEEN 1 AND 160);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'sf_audit_events_action_length'
  ) THEN
    ALTER TABLE sf_audit_events ADD CONSTRAINT sf_audit_events_action_length
      CHECK (length(action) BETWEEN 1 AND 120);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'sf_audit_events_resource_type_length'
  ) THEN
    ALTER TABLE sf_audit_events ADD CONSTRAINT sf_audit_events_resource_type_length
      CHECK (length(resource_type) BETWEEN 1 AND 80);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'sf_audit_events_resource_id_length'
  ) THEN
    ALTER TABLE sf_audit_events ADD CONSTRAINT sf_audit_events_resource_id_length
      CHECK (length(resource_id) <= 200);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'sf_audit_events_outcome_values'
  ) THEN
    ALTER TABLE sf_audit_events ADD CONSTRAINT sf_audit_events_outcome_values
      CHECK (outcome IN ('success', 'denied', 'error'));
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'sf_audit_events_ip_hash_length'
  ) THEN
    ALTER TABLE sf_audit_events ADD CONSTRAINT sf_audit_events_ip_hash_length
      CHECK (length(ip_hash) <= 64);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS sf_audit_events_actor_time_idx
  ON sf_audit_events(actor, occurred_at DESC);
CREATE INDEX IF NOT EXISTS sf_audit_events_retention_idx
  ON sf_audit_events(retention_until);

ALTER TABLE sf_audit_events
  ADD CONSTRAINT sf_audit_events_workspace_user_fk
  FOREIGN KEY (workspace_id, user_id)
  REFERENCES sf_workspace_memberships(workspace_id, user_id);

ALTER TABLE sf_audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_audit_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_audit_events_scope ON sf_audit_events;
CREATE POLICY sf_audit_events_scope ON sf_audit_events
  USING (sf_scope_global() OR workspace_id = sf_scope_workspace() OR user_id = sf_scope_user())
  WITH CHECK (sf_scope_global() OR workspace_id = sf_scope_workspace() OR user_id = sf_scope_user());

GRANT SELECT, INSERT, UPDATE, DELETE ON sf_audit_events TO stratforge_app;
