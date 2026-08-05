-- Interview attempt schema aligned with InterviewStack's actual hierarchy:
-- challenge -> round -> focus topic -> repeatable attempt.
--
-- The numeric primary key and exact timestamps distinguish attempts even when
-- every descriptive label and the calendar date are identical.
-- focus_topic stores the primary/launch topic shown in interview history. The
-- score itself belongs to the round attempt; InterviewStack may summarize the
-- same score under several focus-topic cards within that round.

CREATE TABLE IF NOT EXISTS interview_attempts (
    id BIGSERIAL PRIMARY KEY,
    attempted_date DATE NOT NULL,
    attempt_source VARCHAR(30) NOT NULL DEFAULT 'manual',
    external_attempt_id VARCHAR(100),
    source_url VARCHAR(1000),
    challenge_id VARCHAR(36),
    challenge_title VARCHAR(300),
    round_number SMALLINT,
    round_name VARCHAR(250),
    focus_topic VARCHAR(250),
    question_bank_topic_slug VARCHAR(200),
    attempt_number INTEGER,
    company VARCHAR(150),
    role VARCHAR(150),
    level VARCHAR(100),
    topic VARCHAR(200) NOT NULL,
    score NUMERIC(5, 2),
    status VARCHAR(20) NOT NULL DEFAULT 'complete',
    notes TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_attempt_source CHECK (
        attempt_source IN ('manual', 'casual', 'challenge', 'question_bank')
    ),
    CONSTRAINT valid_attempt_status CHECK (
        status IN ('incomplete', 'complete', 'invalidated')
    ),
    CONSTRAINT valid_score CHECK (
        score IS NULL OR (score >= 0 AND score <= 100)
    ),
    CONSTRAINT positive_attempt_number CHECK (
        attempt_number IS NULL OR attempt_number > 0
    ),
    CONSTRAINT positive_round_number CHECK (
        round_number IS NULL OR round_number > 0
    ),
    CONSTRAINT valid_completion_time CHECK (
        completed_at IS NULL OR completed_at >= started_at
    )
);

-- Upgrade the original nine-column tutorial table without deleting its rows.
ALTER TABLE interview_attempts
    ADD COLUMN IF NOT EXISTS attempt_source VARCHAR(30) NOT NULL DEFAULT 'manual',
    ADD COLUMN IF NOT EXISTS external_attempt_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS source_url VARCHAR(1000),
    ADD COLUMN IF NOT EXISTS challenge_id VARCHAR(36),
    ADD COLUMN IF NOT EXISTS challenge_title VARCHAR(300),
    ADD COLUMN IF NOT EXISTS round_number SMALLINT,
    ADD COLUMN IF NOT EXISTS round_name VARCHAR(250),
    ADD COLUMN IF NOT EXISTS focus_topic VARCHAR(250),
    ADD COLUMN IF NOT EXISTS question_bank_topic_slug VARCHAR(200),
    ADD COLUMN IF NOT EXISTS attempt_number INTEGER,
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'complete',
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

UPDATE interview_attempts
SET started_at = COALESCE(
    started_at,
    created_at,
    attempted_date::timestamp AT TIME ZONE 'UTC'
)
WHERE started_at IS NULL;

ALTER TABLE interview_attempts
    ALTER COLUMN score DROP NOT NULL,
    ALTER COLUMN started_at SET DEFAULT NOW(),
    ALTER COLUMN started_at SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'interview_attempts'::regclass
          AND conname = 'valid_attempt_source'
    ) THEN
        ALTER TABLE interview_attempts
            ADD CONSTRAINT valid_attempt_source CHECK (
                attempt_source IN (
                    'manual', 'casual', 'challenge', 'question_bank'
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'interview_attempts'::regclass
          AND conname = 'valid_attempt_status'
    ) THEN
        ALTER TABLE interview_attempts
            ADD CONSTRAINT valid_attempt_status CHECK (
                status IN ('incomplete', 'complete', 'invalidated')
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'interview_attempts'::regclass
          AND conname = 'positive_attempt_number'
    ) THEN
        ALTER TABLE interview_attempts
            ADD CONSTRAINT positive_attempt_number CHECK (
                attempt_number IS NULL OR attempt_number > 0
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'interview_attempts'::regclass
          AND conname = 'positive_round_number'
    ) THEN
        ALTER TABLE interview_attempts
            ADD CONSTRAINT positive_round_number CHECK (
                round_number IS NULL OR round_number > 0
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'interview_attempts'::regclass
          AND conname = 'valid_completion_time'
    ) THEN
        ALTER TABLE interview_attempts
            ADD CONSTRAINT valid_completion_time CHECK (
                completed_at IS NULL OR completed_at >= started_at
            );
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS ux_attempts_external_id
    ON interview_attempts(external_attempt_id)
    WHERE external_attempt_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_challenge_attempt_sequence
    ON interview_attempts(
        challenge_id,
        round_number,
        focus_topic,
        attempt_number
    )
    WHERE attempt_source = 'challenge'
      AND challenge_id IS NOT NULL
      AND round_number IS NOT NULL
      AND focus_topic IS NOT NULL
      AND attempt_number IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_attempts_started_at
    ON interview_attempts(started_at);

CREATE INDEX IF NOT EXISTS idx_attempts_challenge_round
    ON interview_attempts(challenge_id, round_number, started_at);

CREATE INDEX IF NOT EXISTS idx_attempts_topic_date
    ON interview_attempts(topic, attempted_date);
