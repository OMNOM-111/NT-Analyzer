-- Make the identity invariants hold in the database, not only in Python.
--
-- 0005 gave sf_auth_identities UNIQUE (provider, provider_subject), so one
-- Google sub / Telegram id / e-mail address cannot be the login subject of two
-- accounts. Two holes remained, and both are reachable by a race that passes
-- every application-level check before either transaction commits:
--
--   1. The verified-e-mail index was scoped WHERE provider = 'email', so the
--      same address could be an e-mail identity on one account and the
--      normalized_email of a Google identity on another. That is precisely the
--      silent cross-provider merge the model is supposed to forbid.
--   2. It did not require verified_at, so an unverified row could occupy an
--      address a verified one needs -- or worse, two unverified rows for the
--      same address could both survive and later both be verified.
--
-- Phone had no constraint at all: it lived only inside the user document.
--
-- These are partial unique indexes rather than table constraints because the
-- rule applies to live, verified rows only. A revoked or retired identity must
-- keep its history (see the identity-history work) without blocking anyone.
BEGIN;

-- One verified e-mail address, across every provider that can carry one.
DROP INDEX IF EXISTS sf_auth_identities_verified_email_uidx;
CREATE UNIQUE INDEX IF NOT EXISTS sf_identity_verified_email_uidx
  ON sf_auth_identities(normalized_email)
  WHERE normalized_email IS NOT NULL
    AND normalized_email <> ''
    AND verified_at IS NOT NULL
    AND revoked_at IS NULL;

-- Verified phone numbers are canonical E.164 and belong to one account.
-- The column is added here because the number previously lived only in the
-- user document, where nothing could enforce anything about it.
ALTER TABLE sf_users
  ADD COLUMN IF NOT EXISTS verified_phone_e164 TEXT;

ALTER TABLE sf_users
  DROP CONSTRAINT IF EXISTS sf_users_verified_phone_e164_shape;
ALTER TABLE sf_users
  ADD CONSTRAINT sf_users_verified_phone_e164_shape
  CHECK (verified_phone_e164 IS NULL OR verified_phone_e164 ~ '^\+[1-9][0-9]{6,14}$');

CREATE UNIQUE INDEX IF NOT EXISTS sf_users_verified_phone_uidx
  ON sf_users(verified_phone_e164)
  WHERE verified_phone_e164 IS NOT NULL;

-- Backfill from the document for accounts whose number is already E.164, so
-- the constraint starts from the truth that exists. Anything not already
-- canonical is left NULL rather than guessed at: a wrong normalisation here
-- would silently rewrite someone's identity.
UPDATE sf_users
   SET verified_phone_e164 = document->>'phone'
 WHERE verified_phone_e164 IS NULL
   AND document->>'phone' ~ '^\+[1-9][0-9]{6,14}$'
   AND NOT EXISTS (
     SELECT 1 FROM sf_users other
      WHERE other.user_id <> sf_users.user_id
        AND other.document->>'phone' = sf_users.document->>'phone'
   );

COMMIT;
