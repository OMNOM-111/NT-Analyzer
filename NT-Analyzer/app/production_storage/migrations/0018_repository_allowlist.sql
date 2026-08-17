-- Realign the repository allowlist with the code that uses it.
--
-- sf_repository_documents has permitted exactly four repository names since
-- 0001. Python's REPOSITORIES set grew two more -- 'releases' (release_center)
-- and 'doc_specs' (doc_specs) -- and no migration ever widened the CHECK. The
-- two have been a single contract in name only ever since.
--
-- It has not failed yet because the only code that writes those two documents
-- takes its PostgreSQL branch under `is_production()`, and both are in practice
-- driven from LOCAL, which uses the encrypted local store instead. The moment
-- either is written from the Production process -- a document specification
-- edited in the Production UI, a release action taken there -- the INSERT
-- violates the CHECK, the whole document write is rolled back, and the caller
-- sees an opaque 503.
--
-- Widening a CHECK cannot invalidate an existing row: every value already
-- stored satisfied the narrower rule and still satisfies the wider one.

BEGIN;

SET LOCAL stratforge.service_scope = 'global';

ALTER TABLE sf_repository_documents
  DROP CONSTRAINT IF EXISTS sf_repository_documents_repository_check;

-- Kept as an explicit allowlist rather than dropped entirely: the column is a
-- primary key that application code chooses the value of, and an open text
-- column would let a typo create a silent second document that reads back
-- empty rather than failing.
ALTER TABLE sf_repository_documents
  ADD CONSTRAINT sf_repository_documents_repository_check
  CHECK (repository IN (
    'auth', 'workspaces', 'entitlements', 'connectors', 'releases', 'doc_specs'
  ));

COMMIT;
