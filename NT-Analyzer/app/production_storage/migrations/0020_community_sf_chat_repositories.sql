-- Authoritative documents for Community social state and human SF Chat.
-- Application-level access checks remain the narrow public contract; the
-- PostgreSQL document rows are available only to the isolated global service
-- scope and never fall back to local JSON in Canary or Production.

BEGIN;

SET LOCAL stratforge.service_scope = 'global';

ALTER TABLE sf_repository_documents
  DROP CONSTRAINT IF EXISTS sf_repository_documents_repository_check;

ALTER TABLE sf_repository_documents
  ADD CONSTRAINT sf_repository_documents_repository_check
  CHECK (repository IN (
    'auth', 'workspaces', 'entitlements', 'connectors', 'releases', 'doc_specs',
    'community', 'sf_chat'
  ));

COMMIT;
