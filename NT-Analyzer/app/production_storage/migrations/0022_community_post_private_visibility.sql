-- Community posts gain a "private" visibility: the post stays on its author's
-- own wall and never reaches Recommendation, search or another member's view.
-- Expand-only: the existing 'network' and 'followers' rows remain valid and no
-- data is rewritten. Profile visibility is deliberately untouched -- a profile
-- is either on the network or limited to followers, and has no private state.
ALTER TABLE sf_community_posts
  DROP CONSTRAINT IF EXISTS sf_community_posts_visibility_check;

ALTER TABLE sf_community_posts
  ADD CONSTRAINT sf_community_posts_visibility_check
  CHECK (visibility IN ('network','followers','private'));
