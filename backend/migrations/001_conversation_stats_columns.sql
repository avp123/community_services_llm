-- Optional: denormalized stats on conversations, refreshed after each save in update_conversation.
-- Requires table owner / admin. Safe to run multiple times.

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS stats_message_count INTEGER;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS stats_user_messages INTEGER;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS stats_assistant_messages INTEGER;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS stats_total_chars BIGINT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS stats_user_chars BIGINT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS stats_assistant_chars BIGINT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS stats_first_message_at TIMESTAMPTZ;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS stats_last_message_at TIMESTAMPTZ;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS stats_updated_at TIMESTAMPTZ;
