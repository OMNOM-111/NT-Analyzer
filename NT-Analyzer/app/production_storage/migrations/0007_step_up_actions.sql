-- Phase 5: personal NinjaTrader step-up action binding.
--
-- Additive expand-only migration on the Phase 4 sf_security_challenges table.
-- A confirmed step_up challenge becomes a single-use grant for a named critical
-- action; ``action`` binds the intent and ``step_up_used_at`` marks the grant as
-- spent so it cannot be replayed. No destructive contract is performed.

ALTER TABLE sf_security_challenges
  ADD COLUMN IF NOT EXISTS action TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS step_up_used_at TIMESTAMPTZ;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'sf_security_challenges_action_length'
  ) THEN
    ALTER TABLE sf_security_challenges
      ADD CONSTRAINT sf_security_challenges_action_length
      CHECK (length(action) <= 40);
  END IF;
END $$;

-- Locate an unspent step-up grant for a given account + action quickly.
CREATE INDEX IF NOT EXISTS sf_security_challenges_step_up_action_idx
  ON sf_security_challenges(user_uuid, action, status)
  WHERE purpose = 'step_up' AND action <> '' AND step_up_used_at IS NULL;
