-- Prevent late update_conversation calls from recreating a hard-deleted conversation_id.
CREATE TABLE IF NOT EXISTS conversation_deletions (
    id TEXT PRIMARY KEY,
    deleted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
