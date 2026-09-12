-- Additive Agent World repository. Applying this migration is an explicit
-- operator action; neither the repository constructor nor Local starts it.
-- These are domain revisions/events, NOT a second worker queue or permission
-- authority. Existing sf_jobs/resource leases and authenticated admission stay
-- authoritative. Memory grants below are a revocable, derived visibility index.

CREATE FUNCTION sf_aw_user_uuid() RETURNS UUID LANGUAGE sql STABLE
SET search_path = pg_catalog AS $$
  SELECT CASE WHEN current_setting('stratforge.aw_user_uuid', true)
    ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    AND current_setting('stratforge.aw_user_uuid', true) <> '00000000-0000-0000-0000-000000000000'
    THEN current_setting('stratforge.aw_user_uuid', true)::uuid ELSE NULL END
$$;

CREATE FUNCTION sf_aw_scope_ok(row_environment TEXT, row_workspace TEXT) RETURNS BOOLEAN
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $$
  SELECT COALESCE(current_setting('stratforge.service_scope', true) = 'scoped'
    AND public.sf_aw_user_uuid() IS NOT NULL
    AND current_setting('stratforge.aw_environment', true) IN ('development','canary','production')
    AND row_environment = current_setting('stratforge.aw_environment', true)
    AND row_workspace = current_setting('stratforge.workspace_id', true), FALSE)
$$;

CREATE FUNCTION sf_aw_memory_read_id() RETURNS UUID LANGUAGE sql STABLE
SET search_path = pg_catalog AS $$
  SELECT CASE WHEN current_setting('stratforge.aw_memory_read_id', true)
    ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    THEN current_setting('stratforge.aw_memory_read_id', true)::uuid ELSE NULL END
$$;

CREATE TABLE sf_aw_meta (
  environment TEXT NOT NULL CHECK(environment IN ('development','canary','production')),
  workspace_id TEXT NOT NULL CHECK(workspace_id ~ '^ws_[A-Za-z0-9_-]{8,80}$'),
  schema_version INTEGER NOT NULL DEFAULT 1 CHECK(schema_version = 1),
  cursor_key BYTEA NOT NULL CHECK(octet_length(cursor_key) = 32),
  revision_watermark BIGINT NOT NULL DEFAULT 0 CHECK(revision_watermark >= 0),
  PRIMARY KEY(environment,workspace_id)
);

CREATE TABLE sf_aw_revisions (
  seq BIGSERIAL PRIMARY KEY,
  environment TEXT NOT NULL CHECK(environment IN ('development','canary','production')),
  workspace_id TEXT NOT NULL CHECK(workspace_id ~ '^ws_[A-Za-z0-9_-]{8,80}$'),
  kind TEXT NOT NULL CHECK(kind ~ '^[a-z_]{1,40}$'),
  entity_id UUID NOT NULL, revision BIGINT NOT NULL CHECK(revision > 0),
  owner_uuid UUID NOT NULL, visibility TEXT NOT NULL CHECK(visibility IN ('private','workspace')),
  payload TEXT NOT NULL CHECK(octet_length(payload) BETWEEN 2 AND 262144),
  CHECK(((payload::jsonb)->>'kind' = kind) IS TRUE),
  CHECK(((payload::jsonb)#>>'{header,scope,environment}' = environment) IS TRUE),
  CHECK(((payload::jsonb)#>>'{header,scope,workspace_id}' = workspace_id) IS TRUE),
  CHECK(((payload::jsonb)#>>'{header,entity_id}' = entity_id::text) IS TRUE),
  CHECK(((payload::jsonb)#>>'{header,owner_user_uuid}' = owner_uuid::text) IS TRUE),
  CHECK((((payload::jsonb)#>>'{header,revision}')::bigint = revision) IS TRUE),
  UNIQUE(environment,workspace_id,kind,entity_id,revision),
  UNIQUE(environment,workspace_id,kind,entity_id,revision,owner_uuid,visibility,seq)
);

CREATE TABLE sf_aw_records (
  environment TEXT NOT NULL, workspace_id TEXT NOT NULL, kind TEXT NOT NULL,
  entity_id UUID NOT NULL, revision BIGINT NOT NULL, seq BIGINT NOT NULL,
  owner_uuid UUID NOT NULL, visibility TEXT NOT NULL,
  PRIMARY KEY(environment,workspace_id,kind,entity_id),
  FOREIGN KEY(environment,workspace_id,kind,entity_id,revision,owner_uuid,visibility,seq)
    REFERENCES sf_aw_revisions(environment,workspace_id,kind,entity_id,revision,owner_uuid,visibility,seq)
);

CREATE TABLE sf_aw_events (
  seq BIGSERIAL PRIMARY KEY, event_id UUID NOT NULL,
  environment TEXT NOT NULL, workspace_id TEXT NOT NULL, user_uuid UUID NOT NULL,
  kind TEXT NOT NULL, entity_id UUID NOT NULL, revision BIGINT NOT NULL,
  payload TEXT NOT NULL CHECK(octet_length(payload) BETWEEN 2 AND 262144),
  UNIQUE(environment,workspace_id,event_id),
  UNIQUE(environment,workspace_id,event_id,user_uuid),
  FOREIGN KEY(environment,workspace_id,kind,entity_id,revision)
    REFERENCES sf_aw_revisions(environment,workspace_id,kind,entity_id,revision)
);

CREATE TABLE sf_aw_outbox (
  environment TEXT NOT NULL, workspace_id TEXT NOT NULL, user_uuid UUID NOT NULL, event_id UUID NOT NULL,
  PRIMARY KEY(environment,workspace_id,event_id),
  FOREIGN KEY(environment,workspace_id,event_id,user_uuid)
    REFERENCES sf_aw_events(environment,workspace_id,event_id,user_uuid)
);

CREATE TABLE sf_aw_mutations (
  environment TEXT NOT NULL, workspace_id TEXT NOT NULL, operation TEXT NOT NULL CHECK(length(operation) BETWEEN 1 AND 100),
  key_hash TEXT NOT NULL CHECK(key_hash ~ '^[0-9a-f]{64}$'),
  request_hash TEXT NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'), user_uuid UUID NOT NULL,
  kind TEXT NOT NULL, entity_id UUID NOT NULL, revision BIGINT NOT NULL, event_id UUID NOT NULL,
  PRIMARY KEY(environment,workspace_id,operation,key_hash),
  FOREIGN KEY(environment,workspace_id,kind,entity_id,revision)
    REFERENCES sf_aw_revisions(environment,workspace_id,kind,entity_id,revision),
  FOREIGN KEY(environment,workspace_id,event_id,user_uuid)
    REFERENCES sf_aw_events(environment,workspace_id,event_id,user_uuid)
);

CREATE TABLE sf_aw_inbox (
  environment TEXT NOT NULL, workspace_id TEXT NOT NULL, user_uuid UUID NOT NULL,
  consumer TEXT NOT NULL CHECK(length(consumer) BETWEEN 1 AND 100), event_id UUID NOT NULL,
  PRIMARY KEY(environment,workspace_id,consumer,event_id),
  FOREIGN KEY(environment,workspace_id,event_id,user_uuid)
    REFERENCES sf_aw_events(environment,workspace_id,event_id,user_uuid)
);

CREATE TABLE sf_aw_artifacts (
  environment TEXT NOT NULL CHECK(environment IN ('development','canary','production')),
  workspace_id TEXT NOT NULL CHECK(workspace_id ~ '^ws_[A-Za-z0-9_-]{8,80}$'),
  owner_uuid UUID NOT NULL, artifact_id UUID NOT NULL,
  sha256 TEXT NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
  media_type TEXT NOT NULL CHECK(media_type IN ('application/json','image/png','image/svg+xml')),
  content BYTEA NOT NULL CHECK(octet_length(content) BETWEEN 1 AND 262144),
  PRIMARY KEY(environment,workspace_id,artifact_id),
  UNIQUE(environment,workspace_id,artifact_id,owner_uuid,sha256)
);

-- Rebuildable index only. No public grant mutation API; a transaction derives
-- it from the exact active workspace Memory + original source and verification.
CREATE TABLE sf_aw_memory_grants (
  environment TEXT NOT NULL, workspace_id TEXT NOT NULL, owner_uuid UUID NOT NULL,
  memory_id UUID NOT NULL, memory_revision BIGINT NOT NULL CHECK(memory_revision > 0),
  content_id UUID NOT NULL, content_sha256 TEXT NOT NULL,
  proof_id UUID NOT NULL, proof_sha256 TEXT NOT NULL,
  retention_until TIMESTAMPTZ NOT NULL, valid BOOLEAN NOT NULL DEFAULT FALSE,
  purpose TEXT NOT NULL DEFAULT 'workspace_memory_publication' CHECK(purpose = 'workspace_memory_publication'),
  PRIMARY KEY(environment,workspace_id,memory_id),
  FOREIGN KEY(environment,workspace_id,content_id,owner_uuid,content_sha256)
    REFERENCES sf_aw_artifacts(environment,workspace_id,artifact_id,owner_uuid,sha256),
  FOREIGN KEY(environment,workspace_id,proof_id,owner_uuid,proof_sha256)
    REFERENCES sf_aw_artifacts(environment,workspace_id,artifact_id,owner_uuid,sha256)
);

CREATE TABLE sf_aw_memory_grant_anchors (
  environment TEXT NOT NULL, workspace_id TEXT NOT NULL, owner_uuid UUID NOT NULL,
  memory_id UUID NOT NULL, kind TEXT NOT NULL, entity_id UUID NOT NULL, revision BIGINT NOT NULL,
  PRIMARY KEY(environment,workspace_id,memory_id,kind,entity_id),
  FOREIGN KEY(environment,workspace_id,memory_id)
    REFERENCES sf_aw_memory_grants(environment,workspace_id,memory_id) ON DELETE CASCADE,
  FOREIGN KEY(environment,workspace_id,kind,entity_id,revision)
    REFERENCES sf_aw_revisions(environment,workspace_id,kind,entity_id,revision)
);

CREATE INDEX sf_aw_revision_scope ON sf_aw_revisions(environment,workspace_id,kind,entity_id,seq);
CREATE INDEX sf_aw_event_scope ON sf_aw_events(environment,workspace_id,user_uuid,seq);
CREATE INDEX sf_aw_grant_source ON sf_aw_memory_grant_anchors(environment,workspace_id,kind,entity_id);

-- Defense in depth: even a writer that misses the application refresh cannot
-- leave a valid grant behind after changing an anchored source. The ordinary
-- scoped app transaction may rebuild it only after fresh source verification.
CREATE FUNCTION sf_aw_invalidate_memory_grants() RETURNS TRIGGER LANGUAGE plpgsql
SET search_path = pg_catalog, public AS $$
BEGIN
  UPDATE public.sf_aw_memory_grants g SET valid = FALSE
    WHERE g.environment = NEW.environment AND g.workspace_id = NEW.workspace_id
      AND EXISTS (SELECT 1 FROM public.sf_aw_memory_grant_anchors a
        WHERE a.environment=g.environment AND a.workspace_id=g.workspace_id AND a.memory_id=g.memory_id
          AND a.kind=NEW.kind AND a.entity_id=NEW.entity_id);
  RETURN NEW;
END $$;
CREATE TRIGGER sf_aw_record_invalidates_grants AFTER UPDATE ON sf_aw_records
  FOR EACH ROW EXECUTE FUNCTION sf_aw_invalidate_memory_grants();

DO $aw$
DECLARE relation TEXT;
BEGIN
  FOREACH relation IN ARRAY ARRAY['meta','records','revisions','events','outbox','mutations','inbox','artifacts','memory_grants','memory_grant_anchors'] LOOP
    EXECUTE format('ALTER TABLE public.sf_aw_%I ENABLE ROW LEVEL SECURITY', relation);
    EXECUTE format('ALTER TABLE public.sf_aw_%I FORCE ROW LEVEL SECURITY', relation);
    EXECUTE format('REVOKE ALL ON public.sf_aw_%I FROM PUBLIC, stratforge_app', relation);
  END LOOP;
END $aw$;

CREATE POLICY sf_aw_meta_scope ON sf_aw_meta
  USING(sf_aw_scope_ok(environment,workspace_id)) WITH CHECK(sf_aw_scope_ok(environment,workspace_id));
CREATE POLICY sf_aw_record_read ON sf_aw_records FOR SELECT
  USING(sf_aw_scope_ok(environment,workspace_id) AND (owner_uuid=sf_aw_user_uuid() OR visibility='workspace'));
CREATE POLICY sf_aw_record_insert ON sf_aw_records FOR INSERT
  WITH CHECK(sf_aw_scope_ok(environment,workspace_id) AND owner_uuid=sf_aw_user_uuid());
CREATE POLICY sf_aw_record_update ON sf_aw_records FOR UPDATE
  USING(sf_aw_scope_ok(environment,workspace_id) AND owner_uuid=sf_aw_user_uuid())
  WITH CHECK(sf_aw_scope_ok(environment,workspace_id) AND owner_uuid=sf_aw_user_uuid());
CREATE POLICY sf_aw_revision_read ON sf_aw_revisions FOR SELECT
  USING(sf_aw_scope_ok(environment,workspace_id) AND (owner_uuid=sf_aw_user_uuid() OR
    (visibility='workspace' AND EXISTS (SELECT 1 FROM sf_aw_records r WHERE r.environment=sf_aw_revisions.environment
      AND r.workspace_id=sf_aw_revisions.workspace_id AND r.kind=sf_aw_revisions.kind AND r.entity_id=sf_aw_revisions.entity_id))));
CREATE POLICY sf_aw_revision_insert ON sf_aw_revisions FOR INSERT
  WITH CHECK(sf_aw_scope_ok(environment,workspace_id) AND owner_uuid=sf_aw_user_uuid());

DO $aw$
DECLARE relation TEXT;
BEGIN
  FOREACH relation IN ARRAY ARRAY['events','outbox','mutations','inbox'] LOOP
    EXECUTE format('CREATE POLICY sf_aw_owned ON public.sf_aw_%I USING(public.sf_aw_scope_ok(environment,workspace_id) AND user_uuid=public.sf_aw_user_uuid()) WITH CHECK(public.sf_aw_scope_ok(environment,workspace_id) AND user_uuid=public.sf_aw_user_uuid())', relation);
  END LOOP;
END $aw$;

CREATE POLICY sf_aw_grant_read ON sf_aw_memory_grants FOR SELECT
  USING(sf_aw_scope_ok(environment,workspace_id) AND (owner_uuid=sf_aw_user_uuid() OR
    (memory_id=sf_aw_memory_read_id() AND valid AND retention_until>clock_timestamp())));
CREATE POLICY sf_aw_grant_write ON sf_aw_memory_grants FOR ALL
  USING(sf_aw_scope_ok(environment,workspace_id) AND owner_uuid=sf_aw_user_uuid())
  WITH CHECK(sf_aw_scope_ok(environment,workspace_id) AND owner_uuid=sf_aw_user_uuid());
CREATE POLICY sf_aw_anchor_owned ON sf_aw_memory_grant_anchors
  USING(sf_aw_scope_ok(environment,workspace_id) AND owner_uuid=sf_aw_user_uuid())
  WITH CHECK(sf_aw_scope_ok(environment,workspace_id) AND owner_uuid=sf_aw_user_uuid());
CREATE POLICY sf_aw_artifact_read ON sf_aw_artifacts FOR SELECT
  USING(sf_aw_scope_ok(environment,workspace_id) AND (owner_uuid=sf_aw_user_uuid() OR EXISTS (
    SELECT 1 FROM sf_aw_memory_grants g WHERE g.environment=sf_aw_artifacts.environment
      AND g.workspace_id=sf_aw_artifacts.workspace_id AND g.owner_uuid=sf_aw_artifacts.owner_uuid
      AND g.memory_id=sf_aw_memory_read_id() AND g.valid AND g.retention_until>clock_timestamp()
      AND ((g.content_id=artifact_id AND g.content_sha256=sha256) OR (g.proof_id=artifact_id AND g.proof_sha256=sha256)))));
CREATE POLICY sf_aw_artifact_insert ON sf_aw_artifacts FOR INSERT
  WITH CHECK(sf_aw_scope_ok(environment,workspace_id) AND owner_uuid=sf_aw_user_uuid());

GRANT SELECT,INSERT ON sf_aw_meta,sf_aw_revisions,sf_aw_events,sf_aw_outbox,sf_aw_mutations,sf_aw_inbox,sf_aw_artifacts TO stratforge_app;
GRANT UPDATE(revision_watermark) ON sf_aw_meta TO stratforge_app;
GRANT SELECT,INSERT,UPDATE ON sf_aw_records TO stratforge_app;
GRANT SELECT,INSERT,UPDATE,DELETE ON sf_aw_memory_grants,sf_aw_memory_grant_anchors TO stratforge_app;
GRANT USAGE ON SEQUENCE sf_aw_revisions_seq_seq,sf_aw_events_seq_seq TO stratforge_app;
REVOKE ALL ON FUNCTION sf_aw_user_uuid(),sf_aw_scope_ok(TEXT,TEXT),sf_aw_memory_read_id(),sf_aw_invalidate_memory_grants() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sf_aw_user_uuid(),sf_aw_scope_ok(TEXT,TEXT),sf_aw_memory_read_id() TO stratforge_app;
