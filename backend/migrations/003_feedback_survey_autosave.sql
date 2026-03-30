-- Session survey feedback with per-answer autosave (one row per conversation+username).

CREATE TABLE IF NOT EXISTS conversation_feedback (
    id BIGSERIAL PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    q1 INTEGER,
    q2 INTEGER,
    q3 INTEGER,
    q4 INTEGER,
    q5 INTEGER,
    feedback_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Back-compat: if table already exists with older shape, add new columns.
ALTER TABLE conversation_feedback ADD COLUMN IF NOT EXISTS username TEXT;
ALTER TABLE conversation_feedback ADD COLUMN IF NOT EXISTS q1 INTEGER;
ALTER TABLE conversation_feedback ADD COLUMN IF NOT EXISTS q2 INTEGER;
ALTER TABLE conversation_feedback ADD COLUMN IF NOT EXISTS q3 INTEGER;
ALTER TABLE conversation_feedback ADD COLUMN IF NOT EXISTS q4 INTEGER;
ALTER TABLE conversation_feedback ADD COLUMN IF NOT EXISTS q5 INTEGER;
ALTER TABLE conversation_feedback ADD COLUMN IF NOT EXISTS feedback_text TEXT;
ALTER TABLE conversation_feedback ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE conversation_feedback ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Backfill username from conversations where missing.
UPDATE conversation_feedback cf
SET username = c.username
FROM conversations c
WHERE cf.conversation_id = c.id
  AND (cf.username IS NULL OR BTRIM(cf.username) = '');

-- Dedupe legacy rows so we can enforce one row per conversation+username.
WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY conversation_id, username
            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
        ) AS rn
    FROM conversation_feedback
    WHERE username IS NOT NULL AND BTRIM(username) <> ''
)
DELETE FROM conversation_feedback cf
USING ranked r
WHERE cf.id = r.id
  AND r.rn > 1;

-- Ensure one autosave row per conversation/user.
CREATE UNIQUE INDEX IF NOT EXISTS ux_conversation_feedback_conversation_user
ON conversation_feedback(conversation_id, username);

-- Optional hard bounds for survey responses.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'conversation_feedback_q1_range'
    ) THEN
        ALTER TABLE conversation_feedback
            ADD CONSTRAINT conversation_feedback_q1_range CHECK (q1 IS NULL OR (q1 >= 1 AND q1 <= 5));
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'conversation_feedback_q2_range'
    ) THEN
        ALTER TABLE conversation_feedback
            ADD CONSTRAINT conversation_feedback_q2_range CHECK (q2 IS NULL OR (q2 >= 1 AND q2 <= 5));
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'conversation_feedback_q3_range'
    ) THEN
        ALTER TABLE conversation_feedback
            ADD CONSTRAINT conversation_feedback_q3_range CHECK (q3 IS NULL OR (q3 >= 1 AND q3 <= 5));
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'conversation_feedback_q4_range'
    ) THEN
        ALTER TABLE conversation_feedback
            ADD CONSTRAINT conversation_feedback_q4_range CHECK (q4 IS NULL OR (q4 >= 1 AND q4 <= 5));
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'conversation_feedback_q5_range'
    ) THEN
        ALTER TABLE conversation_feedback
            ADD CONSTRAINT conversation_feedback_q5_range CHECK (q5 IS NULL OR (q5 >= 1 AND q5 <= 5));
    END IF;
END
$$;
