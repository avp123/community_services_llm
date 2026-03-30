-- Conversation display title (first-message summary) and denormalized tool usage per chat.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS stats_tool_calls_total INTEGER;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS stats_tool_calls_by_name JSONB;
