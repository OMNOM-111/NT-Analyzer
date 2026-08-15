-- Give the identity UUID foreign keys an explicit ON DELETE rule.
--
-- 0005 added every sf_identity_*_user_uuid_fk with no delete action, so each
-- one defaulted to NO ACTION. That blocks deleting an account on every table
-- carrying a user_uuid -- including sf_audit_events, whose legacy user_id
-- column has said ON DELETE SET NULL since 0001. The result was that no
-- non-owner account could be removed at all: the foreign key violation aborts
-- the transaction, the whole document write rolls back, and a user "deleted"
-- in the UI silently stayed.
--
-- NOT VALID did not help and was never going to: it only skips validating rows
-- that already exist, it never relaxes enforcement of new deletes.
--
-- Each constraint below is dropped and recreated with the same rule its legacy
-- user_id counterpart already has:
--
--   CASCADE   the row belongs to the account and goes with it
--   SET NULL  the row is history and must outlive the account, unlinked
--   RESTRICT  the row must be handed over deliberately (workspaces)
--
-- Recreated NOT VALID so an existing database is not forced into a full table
-- scan during deploy; enforcement of new writes is immediate either way, which
-- is the part that matters here.
DO $$
DECLARE
  spec RECORD;
  constraint_name TEXT;
BEGIN
  FOR spec IN
    SELECT * FROM (VALUES
      -- owned by the account: remove with it
      ('sf_auth_challenges',           'user_uuid',              'CASCADE'),
      ('sf_auth_sessions',             'user_uuid',              'CASCADE'),
      ('sf_workspace_memberships',     'user_uuid',              'CASCADE'),
      ('sf_active_workspaces',         'user_uuid',              'CASCADE'),
      ('sf_connections',               'user_uuid',              'CASCADE'),
      ('sf_entitlements',              'user_uuid',              'CASCADE'),
      ('sf_connector_installations',   'user_uuid',              'CASCADE'),
      ('sf_jobs',                      'user_uuid',              'CASCADE'),
      ('sf_commands',                  'user_uuid',              'CASCADE'),
      ('sf_artifacts',                 'user_uuid',              'CASCADE'),
      ('sf_ai_reservations',           'user_uuid',              'CASCADE'),
      ('sf_ai_usage_events',           'user_uuid',              'CASCADE'),
      -- history: outlives the account, unlinked from it
      ('sf_audit_events',              'user_uuid',              'SET NULL'),
      ('sf_operational_events',        'user_uuid',              'SET NULL')
    ) AS t(table_name, column_name, delete_rule)
  LOOP
    IF to_regclass(spec.table_name) IS NULL THEN
      CONTINUE;
    END IF;
    constraint_name := 'sf_identity_' || spec.table_name || '_user_uuid_fk';
    EXECUTE format('ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I',
                   spec.table_name, constraint_name);
    -- SET NULL needs a nullable column; 0005 backfilled these, so a NOT NULL
    -- left over from an earlier shape would make the rule unusable.
    IF spec.delete_rule = 'SET NULL' THEN
      EXECUTE format('ALTER TABLE %I ALTER COLUMN %I DROP NOT NULL',
                     spec.table_name, spec.column_name);
    END IF;
    EXECUTE format(
      'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (%I) '
      'REFERENCES sf_users(user_uuid) ON DELETE %s NOT VALID',
      spec.table_name, constraint_name, spec.column_name, spec.delete_rule
    );
  END LOOP;

  -- Named separately: these carry their own column names.
  IF to_regclass('sf_workspaces') IS NOT NULL THEN
    ALTER TABLE sf_workspaces
      DROP CONSTRAINT IF EXISTS sf_identity_sf_workspaces_owner_user_uuid_fk;
    -- RESTRICT, matching owner_user_id: a workspace is handed over or removed
    -- deliberately, never silently dropped with its owner.
    ALTER TABLE sf_workspaces
      ADD CONSTRAINT sf_identity_sf_workspaces_owner_user_uuid_fk
      FOREIGN KEY (owner_user_uuid) REFERENCES sf_users(user_uuid)
      ON DELETE RESTRICT NOT VALID;
  END IF;

  IF to_regclass('sf_migration_runs') IS NOT NULL THEN
    ALTER TABLE sf_migration_runs
      DROP CONSTRAINT IF EXISTS sf_identity_sf_migration_runs_owner_user_uuid_fk;
    ALTER TABLE sf_migration_runs ALTER COLUMN owner_user_uuid DROP NOT NULL;
    ALTER TABLE sf_migration_runs
      ADD CONSTRAINT sf_identity_sf_migration_runs_owner_user_uuid_fk
      FOREIGN KEY (owner_user_uuid) REFERENCES sf_users(user_uuid)
      ON DELETE SET NULL NOT VALID;
  END IF;

  IF to_regclass('sf_market_data_subscriptions') IS NOT NULL THEN
    ALTER TABLE sf_market_data_subscriptions
      DROP CONSTRAINT IF EXISTS sf_identity_sf_market_data_requested_user_uuid_fk;
    ALTER TABLE sf_market_data_subscriptions
      ADD CONSTRAINT sf_identity_sf_market_data_requested_user_uuid_fk
      FOREIGN KEY (requested_by_user_uuid) REFERENCES sf_users(user_uuid)
      ON DELETE CASCADE NOT VALID;
  END IF;

  IF to_regclass('sf_ninjatrader_resource_leases') IS NOT NULL THEN
    ALTER TABLE sf_ninjatrader_resource_leases
      DROP CONSTRAINT IF EXISTS sf_ninjatrader_resource_leases_requested_by_user_id_fkey;
    ALTER TABLE sf_ninjatrader_resource_leases
      ADD CONSTRAINT sf_ninjatrader_resource_leases_requested_by_user_id_fkey
      FOREIGN KEY (requested_by_user_id) REFERENCES sf_users(user_uuid)
      ON DELETE CASCADE;
  END IF;
END $$;
