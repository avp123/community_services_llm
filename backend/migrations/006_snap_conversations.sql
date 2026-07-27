-- SNAP chat history: separate from the caseworker/service-user `conversations` table
-- since SNAP conversations belong to the logged-in user directly (no service_user_id),
-- and are scoped by mode ('expert' = caseworker, 'simple' = applicant).

CREATE TABLE IF NOT EXISTS snap_conversations (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    mode TEXT NOT NULL,
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_snap_conversations_username_mode
    ON snap_conversations (username, mode, updated_at DESC);

CREATE TABLE IF NOT EXISTS snap_messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES snap_conversations (id) ON DELETE CASCADE,
    sender TEXT NOT NULL,
    text TEXT NOT NULL,
    sources JSONB,
    flags JSONB,
    questions JSONB,
    resource JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_snap_messages_conversation_id
    ON snap_messages (conversation_id, created_at);
