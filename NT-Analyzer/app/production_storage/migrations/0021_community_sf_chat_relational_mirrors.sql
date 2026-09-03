-- Constrained relational mirrors for the authoritative Community and SF Chat
-- documents. This is expand-only: the compatibility documents remain the
-- source of truth, so application rollback never requires destructive SQL.

BEGIN;

SET LOCAL stratforge.service_scope = 'global';

CREATE TABLE IF NOT EXISTS sf_community_profiles (
  profile_id TEXT PRIMARY KEY CHECK (length(profile_id) BETWEEN 8 AND 96),
  user_id BIGINT NOT NULL,
  user_uuid UUID,
  username TEXT NOT NULL CHECK (length(username) BETWEEN 3 AND 30),
  visibility TEXT NOT NULL CHECK (visibility IN ('network','followers')),
  message_policy TEXT NOT NULL CHECK (message_policy IN ('everyone','following','nobody')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  CONSTRAINT sf_community_profiles_user_fk FOREIGN KEY(user_id)
    REFERENCES sf_users(user_id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX IF NOT EXISTS sf_community_profiles_user_idx
  ON sf_community_profiles(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS sf_community_profiles_uuid_idx
  ON sf_community_profiles(user_uuid) WHERE user_uuid IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS sf_community_profiles_username_idx
  ON sf_community_profiles(lower(username));

CREATE TABLE IF NOT EXISTS sf_community_posts (
  post_id TEXT PRIMARY KEY CHECK (length(post_id) BETWEEN 8 AND 96),
  author_profile_id TEXT NOT NULL,
  workspace_id TEXT,
  visibility TEXT NOT NULL CHECK (visibility IN ('network','followers')),
  kind TEXT NOT NULL CHECK (kind IN ('text','image','object')),
  object_source_type TEXT,
  object_source_id TEXT,
  attestation_sha256 TEXT CHECK (
    attestation_sha256 IS NULL OR attestation_sha256 ~ '^[0-9a-f]{64}$'
  ),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  deleted_at TIMESTAMPTZ,
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  CONSTRAINT sf_community_posts_author_fk FOREIGN KEY(author_profile_id)
    REFERENCES sf_community_profiles(profile_id) ON DELETE RESTRICT,
  CONSTRAINT sf_community_posts_workspace_fk FOREIGN KEY(workspace_id)
    REFERENCES sf_workspaces(workspace_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS sf_community_posts_feed_idx
  ON sf_community_posts(created_at DESC, post_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS sf_community_posts_author_idx
  ON sf_community_posts(author_profile_id, created_at DESC);
CREATE INDEX IF NOT EXISTS sf_community_posts_object_idx
  ON sf_community_posts(object_source_type, object_source_id)
  WHERE object_source_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS sf_community_posts_document_gin_idx
  ON sf_community_posts USING GIN(document jsonb_path_ops);

CREATE TABLE IF NOT EXISTS sf_community_comments (
  comment_id TEXT PRIMARY KEY CHECK (length(comment_id) BETWEEN 8 AND 96),
  post_id TEXT NOT NULL,
  author_profile_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  deleted_at TIMESTAMPTZ,
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  CONSTRAINT sf_community_comments_post_fk FOREIGN KEY(post_id)
    REFERENCES sf_community_posts(post_id) ON DELETE CASCADE,
  CONSTRAINT sf_community_comments_author_fk FOREIGN KEY(author_profile_id)
    REFERENCES sf_community_profiles(profile_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS sf_community_comments_post_idx
  ON sf_community_comments(post_id, created_at) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS sf_community_follows (
  follow_id TEXT PRIMARY KEY,
  follower_profile_id TEXT NOT NULL,
  target_profile_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  CONSTRAINT sf_community_follows_follower_fk FOREIGN KEY(follower_profile_id)
    REFERENCES sf_community_profiles(profile_id) ON DELETE CASCADE,
  CONSTRAINT sf_community_follows_target_fk FOREIGN KEY(target_profile_id)
    REFERENCES sf_community_profiles(profile_id) ON DELETE CASCADE,
  CONSTRAINT sf_community_follows_not_self CHECK (follower_profile_id <> target_profile_id),
  CONSTRAINT sf_community_follows_unique UNIQUE(follower_profile_id,target_profile_id)
);
CREATE INDEX IF NOT EXISTS sf_community_follows_target_idx
  ON sf_community_follows(target_profile_id, created_at DESC);

CREATE TABLE IF NOT EXISTS sf_community_blocks (
  block_id TEXT PRIMARY KEY,
  blocker_profile_id TEXT NOT NULL,
  target_profile_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  CONSTRAINT sf_community_blocks_blocker_fk FOREIGN KEY(blocker_profile_id)
    REFERENCES sf_community_profiles(profile_id) ON DELETE CASCADE,
  CONSTRAINT sf_community_blocks_target_fk FOREIGN KEY(target_profile_id)
    REFERENCES sf_community_profiles(profile_id) ON DELETE CASCADE,
  CONSTRAINT sf_community_blocks_not_self CHECK (blocker_profile_id <> target_profile_id),
  CONSTRAINT sf_community_blocks_unique UNIQUE(blocker_profile_id,target_profile_id)
);
CREATE INDEX IF NOT EXISTS sf_community_blocks_target_idx
  ON sf_community_blocks(target_profile_id);

CREATE TABLE IF NOT EXISTS sf_community_reactions (
  reaction_id TEXT PRIMARY KEY,
  post_id TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  reaction TEXT NOT NULL CHECK (reaction IN ('support','insightful','fire')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  CONSTRAINT sf_community_reactions_post_fk FOREIGN KEY(post_id)
    REFERENCES sf_community_posts(post_id) ON DELETE CASCADE,
  CONSTRAINT sf_community_reactions_profile_fk FOREIGN KEY(profile_id)
    REFERENCES sf_community_profiles(profile_id) ON DELETE CASCADE,
  CONSTRAINT sf_community_reactions_unique UNIQUE(post_id,profile_id)
);

CREATE TABLE IF NOT EXISTS sf_community_bookmarks (
  bookmark_id TEXT PRIMARY KEY,
  post_id TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  CONSTRAINT sf_community_bookmarks_post_fk FOREIGN KEY(post_id)
    REFERENCES sf_community_posts(post_id) ON DELETE CASCADE,
  CONSTRAINT sf_community_bookmarks_profile_fk FOREIGN KEY(profile_id)
    REFERENCES sf_community_profiles(profile_id) ON DELETE CASCADE,
  CONSTRAINT sf_community_bookmarks_unique UNIQUE(post_id,profile_id)
);
CREATE INDEX IF NOT EXISTS sf_community_bookmarks_profile_idx
  ON sf_community_bookmarks(profile_id, created_at DESC);

CREATE TABLE IF NOT EXISTS sf_community_moderation_reports (
  report_id TEXT PRIMARY KEY CHECK (length(report_id) BETWEEN 8 AND 96),
  reporter_profile_id TEXT NOT NULL,
  target_type TEXT NOT NULL CHECK (target_type IN ('post','profile','comment')),
  target_id TEXT NOT NULL CHECK (length(target_id) BETWEEN 1 AND 100),
  status TEXT NOT NULL CHECK (status IN ('open','resolved','dismissed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  resolved_at TIMESTAMPTZ,
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  CONSTRAINT sf_community_reports_profile_fk FOREIGN KEY(reporter_profile_id)
    REFERENCES sf_community_profiles(profile_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS sf_community_reports_queue_idx
  ON sf_community_moderation_reports(status, created_at DESC);

CREATE TABLE IF NOT EXISTS sf_chat_conversations (
  conversation_id TEXT PRIMARY KEY CHECK (length(conversation_id) BETWEEN 8 AND 96),
  conversation_type TEXT NOT NULL CHECK (conversation_type = 'human'),
  last_seq BIGINT NOT NULL DEFAULT 0 CHECK (last_seq >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object')
);
CREATE INDEX IF NOT EXISTS sf_chat_conversations_updated_idx
  ON sf_chat_conversations(updated_at DESC);

CREATE TABLE IF NOT EXISTS sf_chat_participants (
  participant_id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  joined_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  CONSTRAINT sf_chat_participants_conversation_fk FOREIGN KEY(conversation_id)
    REFERENCES sf_chat_conversations(conversation_id) ON DELETE CASCADE,
  CONSTRAINT sf_chat_participants_profile_fk FOREIGN KEY(profile_id)
    REFERENCES sf_community_profiles(profile_id) ON DELETE RESTRICT,
  CONSTRAINT sf_chat_participants_unique UNIQUE(conversation_id,profile_id)
);
CREATE INDEX IF NOT EXISTS sf_chat_participants_profile_idx
  ON sf_chat_participants(profile_id, conversation_id);

CREATE TABLE IF NOT EXISTS sf_chat_messages (
  message_id TEXT PRIMARY KEY CHECK (length(message_id) BETWEEN 8 AND 96),
  conversation_id TEXT NOT NULL,
  seq BIGINT NOT NULL CHECK (seq > 0),
  sender_profile_id TEXT NOT NULL,
  idempotency_key_hash TEXT CHECK (
    idempotency_key_hash IS NULL OR idempotency_key_hash ~ '^[0-9a-f]{64}$'
  ),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  deleted_at TIMESTAMPTZ,
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  CONSTRAINT sf_chat_messages_conversation_fk FOREIGN KEY(conversation_id)
    REFERENCES sf_chat_conversations(conversation_id) ON DELETE CASCADE,
  CONSTRAINT sf_chat_messages_sender_fk FOREIGN KEY(sender_profile_id)
    REFERENCES sf_community_profiles(profile_id) ON DELETE RESTRICT,
  CONSTRAINT sf_chat_messages_seq_unique UNIQUE(conversation_id,seq)
);
CREATE UNIQUE INDEX IF NOT EXISTS sf_chat_messages_idempotency_idx
  ON sf_chat_messages(conversation_id,sender_profile_id,idempotency_key_hash)
  WHERE idempotency_key_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS sf_chat_messages_conversation_idx
  ON sf_chat_messages(conversation_id, seq DESC) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS sf_chat_reads (
  read_id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  last_read_seq BIGINT NOT NULL DEFAULT 0 CHECK (last_read_seq >= 0),
  read_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
  CONSTRAINT sf_chat_reads_conversation_fk FOREIGN KEY(conversation_id)
    REFERENCES sf_chat_conversations(conversation_id) ON DELETE CASCADE,
  CONSTRAINT sf_chat_reads_profile_fk FOREIGN KEY(profile_id)
    REFERENCES sf_community_profiles(profile_id) ON DELETE RESTRICT,
  CONSTRAINT sf_chat_reads_unique UNIQUE(conversation_id,profile_id)
);

ALTER TABLE sf_community_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_community_profiles FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_community_profiles_service ON sf_community_profiles
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());
ALTER TABLE sf_community_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_community_posts FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_community_posts_service ON sf_community_posts
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());
ALTER TABLE sf_community_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_community_comments FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_community_comments_service ON sf_community_comments
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());
ALTER TABLE sf_community_follows ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_community_follows FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_community_follows_service ON sf_community_follows
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());
ALTER TABLE sf_community_blocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_community_blocks FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_community_blocks_service ON sf_community_blocks
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());
ALTER TABLE sf_community_reactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_community_reactions FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_community_reactions_service ON sf_community_reactions
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());
ALTER TABLE sf_community_bookmarks ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_community_bookmarks FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_community_bookmarks_service ON sf_community_bookmarks
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());
ALTER TABLE sf_community_moderation_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_community_moderation_reports FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_community_reports_service ON sf_community_moderation_reports
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());
ALTER TABLE sf_chat_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_chat_conversations FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_chat_conversations_service ON sf_chat_conversations
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());
ALTER TABLE sf_chat_participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_chat_participants FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_chat_participants_service ON sf_chat_participants
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());
ALTER TABLE sf_chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_chat_messages FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_chat_messages_service ON sf_chat_messages
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());
ALTER TABLE sf_chat_reads ENABLE ROW LEVEL SECURITY;
ALTER TABLE sf_chat_reads FORCE ROW LEVEL SECURITY;
CREATE POLICY sf_chat_reads_service ON sf_chat_reads
  USING (sf_scope_global()) WITH CHECK (sf_scope_global());

GRANT SELECT, INSERT, UPDATE, DELETE ON
  sf_community_profiles, sf_community_posts, sf_community_comments,
  sf_community_follows, sf_community_blocks, sf_community_reactions,
  sf_community_bookmarks, sf_community_moderation_reports,
  sf_chat_conversations, sf_chat_participants, sf_chat_messages, sf_chat_reads
TO stratforge_app;

COMMIT;
