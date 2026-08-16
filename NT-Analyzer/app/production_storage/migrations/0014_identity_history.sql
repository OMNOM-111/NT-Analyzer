-- Append-only identity history.
--
-- Until now an identity change overwrote a field: the previous e-mail, phone
-- or provider link simply stopped existing. That loses exactly the record a
-- security review needs -- "what address was on this account in June, and who
-- changed it" -- and it also makes a stolen-then-changed identifier
-- indistinguishable from one that was never there.
--
-- The current identity stays where it is (sf_auth_identities, sf_users). This
-- table is the history beside it: every state an identifier has ever held on
-- an account, never updated in place except to close its validity window.
--
-- Reassignment is deliberately hard. A key that has ever been active on one
-- account cannot quietly become active on another: the partial unique index
-- below stops two live claims, and application policy requires an explicit,
-- audited reassignment to move a retired key. An identifier changing hands
-- silently is how account takeover looks from the database.
BEGIN;

CREATE TABLE IF NOT EXISTS sf_identity_history (
  history_id UUID PRIMARY KEY,
  -- SET NULL rather than CASCADE: deleting an account must not erase the
  -- record that it once held an identifier, which is what an audit reads.
  user_uuid UUID REFERENCES sf_users(user_uuid) ON DELETE SET NULL,
  legacy_user_id BIGINT,
  provider TEXT NOT NULL
    CHECK (provider IN ('telegram', 'google', 'email', 'phone')),
  -- Canonical comparable form: E.164, folded address, provider subject.
  normalized_key TEXT NOT NULL CHECK (length(normalized_key) BETWEEN 1 AND 320),
  -- Lets a lookup avoid reading the plaintext where that is preferable.
  key_hash TEXT NOT NULL CHECK (key_hash ~ '^[0-9a-f]{64}$'),
  -- Masked, safe to render. Never the raw value for phone/e-mail.
  display_value TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL CHECK (state IN ('pending', 'active', 'retired', 'revoked')),
  verified_at TIMESTAMPTZ,
  valid_from TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  valid_to TIMESTAMPTZ,
  replacement_reason TEXT NOT NULL DEFAULT '',
  replaced_by_history_id UUID REFERENCES sf_identity_history(history_id),
  actor_user_uuid UUID,
  actor_source TEXT NOT NULL DEFAULT '',
  document JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(document) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  -- An open window means active or pending; a closed one means it ended.
  CHECK ((state IN ('active', 'pending')) = (valid_to IS NULL)),
  -- Nothing is "active" without proof.
  CHECK (state <> 'active' OR verified_at IS NOT NULL)
);

-- One live claim on a key, globally. This is what makes a race unable to give
-- the same address or number to two accounts, and what forces a deliberate
-- reassignment rather than a silent handover.
CREATE UNIQUE INDEX IF NOT EXISTS sf_identity_history_active_key_uidx
  ON sf_identity_history(provider, normalized_key)
  WHERE state = 'active';

-- Providers that may hold only one active value per account. Telegram and
-- Google are one-per-account too, but are keyed by subject rather than a
-- user-editable value, so the same rule reads naturally for all four.
CREATE UNIQUE INDEX IF NOT EXISTS sf_identity_history_one_active_per_user_uidx
  ON sf_identity_history(user_uuid, provider)
  WHERE state = 'active' AND user_uuid IS NOT NULL;

CREATE INDEX IF NOT EXISTS sf_identity_history_user_idx
  ON sf_identity_history(user_uuid, provider, valid_from DESC);
CREATE INDEX IF NOT EXISTS sf_identity_history_key_hash_idx
  ON sf_identity_history(key_hash);

ALTER TABLE sf_identity_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_identity_history FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sf_identity_history_scope ON sf_identity_history;
CREATE POLICY sf_identity_history_scope ON sf_identity_history
  USING (sf_scope_global() OR legacy_user_id = sf_scope_user())
  WITH CHECK (sf_scope_global());

-- Backfill: every identity that exists today becomes its own first history
-- row, so the timeline does not begin empty for accounts that predate it.
INSERT INTO sf_identity_history(
  history_id, user_uuid, legacy_user_id, provider, normalized_key, key_hash,
  display_value, state, verified_at, valid_from, valid_to, actor_source, document
)
SELECT
  sf_identity_uuid_v1('history:' || i.provider || ':' || i.provider_subject),
  i.user_uuid,
  i.legacy_user_id,
  i.provider,
  COALESCE(NULLIF(i.normalized_email, ''), i.provider_subject),
  encode(sha256(convert_to(
    COALESCE(NULLIF(i.normalized_email, ''), i.provider_subject), 'UTF8')), 'hex'),
  CASE
    WHEN i.provider IN ('email', 'google')
      THEN regexp_replace(COALESCE(NULLIF(i.normalized_email, ''), i.provider_subject),
                          '^(.).*(@.*)$', '\1•••\2')
    ELSE '•' || right(i.provider_subject, 4)
  END,
  CASE WHEN i.revoked_at IS NOT NULL THEN 'revoked'
       WHEN i.verified_at IS NOT NULL THEN 'active'
       ELSE 'pending' END,
  i.verified_at,
  COALESCE(i.linked_at, clock_timestamp()),
  -- A closed window is required for anything not active/pending, so it is set
  -- here rather than repaired afterwards: the CHECK would reject the insert.
  CASE WHEN i.revoked_at IS NOT NULL THEN i.revoked_at ELSE NULL END,
  'migration_0014_backfill',
  jsonb_build_object('backfilled', true, 'identity_id', i.identity_id)
FROM sf_auth_identities i
WHERE NOT EXISTS (
  SELECT 1 FROM sf_identity_history h
   WHERE h.provider = i.provider
     AND h.normalized_key = COALESCE(NULLIF(i.normalized_email, ''), i.provider_subject)
)
ON CONFLICT DO NOTHING;

COMMIT;
