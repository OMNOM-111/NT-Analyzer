-- Phase 11: workspace / strategy document specification revisions.
--
-- Additive expand-only migration. Creates the document-specification tables that
-- back the workspace/strategy specification revision module: a document with a
-- scope (global / governance / workspace / strategy / changelog) and an
-- append-only chain of immutable revisions (draft -> review -> approved ->
-- published -> superseded). No destructive contract, no DROP, no data migration.
-- Both tables start empty.
--
-- Scope safety: global/governance/changelog documents are readable/writable only
-- under the global service scope (owner / docs.manage_global). Workspace and
-- strategy documents are scoped to their workspace, so a workspace or strategy
-- revision can never read or mutate global governance or safety limits (those
-- live in the governance store, a separate control plane). No secret, token or
-- credential is stored here.

CREATE TABLE IF NOT EXISTS sf_documents (
  document_id UUID PRIMARY KEY,
  scope_type TEXT NOT NULL
    CHECK (scope_type IN ('global', 'governance', 'workspace', 'strategy', 'changelog')),
  workspace_id TEXT NOT NULL DEFAULT '',
  strategy_id TEXT NOT NULL DEFAULT '',
  slug TEXT NOT NULL CHECK (length(slug) BETWEEN 1 AND 160),
  title TEXT NOT NULL DEFAULT '' CHECK (length(title) <= 200),
  owner_user_id UUID REFERENCES sf_users(user_uuid) ON DELETE SET NULL,
  owner_legacy_id BIGINT NOT NULL DEFAULT 0,
  current_revision_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  -- A workspace/strategy scope must carry a workspace; a global/governance/
  -- changelog scope must not. This keeps global docs out of any workspace scope.
  CONSTRAINT sf_documents_scope_workspace_ck CHECK (
    (scope_type IN ('workspace', 'strategy') AND length(workspace_id) > 0)
    OR (scope_type IN ('global', 'governance', 'changelog') AND length(workspace_id) = 0)
  )
);

-- One document per (scope, workspace, slug); the same slug can exist in a
-- different workspace without collision.
CREATE UNIQUE INDEX IF NOT EXISTS sf_documents_scope_slug_uidx
  ON sf_documents(scope_type, workspace_id, slug);

CREATE TABLE IF NOT EXISTS sf_document_revisions (
  revision_id UUID PRIMARY KEY,
  document_id UUID NOT NULL REFERENCES sf_documents(document_id) ON DELETE CASCADE,
  revision INTEGER NOT NULL CHECK (revision >= 1),
  author_user_id UUID REFERENCES sf_users(user_uuid) ON DELETE SET NULL,
  author_legacy_id BIGINT NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'review', 'approved', 'published', 'superseded')),
  -- Revision content is opaque document JSON (title/body/params); never secrets.
  content JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(content) = 'object'),
  reason TEXT NOT NULL DEFAULT '' CHECK (length(reason) <= 500),
  supersedes_revision_id UUID,
  reverted_from_revision INTEGER,
  approved_by_legacy_id BIGINT NOT NULL DEFAULT 0,
  published_by_legacy_id BIGINT NOT NULL DEFAULT 0,
  release_build_id TEXT NOT NULL DEFAULT '' CHECK (length(release_build_id) <= 200),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  approved_at_utc TIMESTAMPTZ,
  published_at_utc TIMESTAMPTZ,
  CONSTRAINT sf_document_revisions_unique UNIQUE (document_id, revision)
);

CREATE INDEX IF NOT EXISTS sf_document_revisions_document_idx
  ON sf_document_revisions(document_id, revision);
CREATE INDEX IF NOT EXISTS sf_documents_workspace_idx
  ON sf_documents(scope_type, workspace_id);

-- Row level security. Global/governance/changelog documents are only visible
-- under the global service scope; workspace/strategy documents are visible to
-- their workspace (or the global scope). A workspace member therefore can never
-- read or write a global/governance document, and never another workspace's docs.
ALTER TABLE sf_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_documents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_documents_scope ON sf_documents;
CREATE POLICY sf_documents_scope ON sf_documents
  USING (
    sf_scope_global()
    OR (scope_type IN ('workspace', 'strategy') AND workspace_id = sf_scope_workspace())
  )
  WITH CHECK (
    sf_scope_global()
    OR (scope_type IN ('workspace', 'strategy') AND workspace_id = sf_scope_workspace())
  );

ALTER TABLE sf_document_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_document_revisions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_document_revisions_scope ON sf_document_revisions;
CREATE POLICY sf_document_revisions_scope ON sf_document_revisions
  USING (
    sf_scope_global()
    OR EXISTS (
      SELECT 1 FROM sf_documents d
      WHERE d.document_id = sf_document_revisions.document_id
        AND d.scope_type IN ('workspace', 'strategy')
        AND d.workspace_id = sf_scope_workspace()
    )
  )
  WITH CHECK (
    sf_scope_global()
    OR EXISTS (
      SELECT 1 FROM sf_documents d
      WHERE d.document_id = sf_document_revisions.document_id
        AND d.scope_type IN ('workspace', 'strategy')
        AND d.workspace_id = sf_scope_workspace()
    )
  );

-- The application role owns no tables; grant it scoped DML (RLS still applies).
GRANT SELECT, INSERT, UPDATE, DELETE ON sf_documents TO stratforge_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON sf_document_revisions TO stratforge_app;
