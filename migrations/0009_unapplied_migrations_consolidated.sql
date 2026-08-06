-- Consolidated Unapplied Migrations (0007, 0008, and missing 0005 objects)
-- Run this script in Supabase SQL Editor: https://supabase.com/dashboard/project/tgbknrmnjwiokraddurx/sql/new

-- 1. Missing 0007 Tables: drona_wellbeing_flags & drona_rate_limits
CREATE TABLE IF NOT EXISTS public.drona_wellbeing_flags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES public.drona_sessions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    tier_level INT NOT NULL CHECK (tier_level BETWEEN 1 AND 5),
    trigger_utterance TEXT NOT NULL,
    flagged_reason TEXT NOT NULL,
    action_taken TEXT NOT NULL,
    helpline_info_sent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.drona_rate_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    endpoint TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    request_count INT DEFAULT 1,
    is_blocked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Missing 0008 Telemetry Columns
ALTER TABLE public.drona_sessions ADD COLUMN IF NOT EXISTS mute_duration_sec DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE public.drona_sessions ADD COLUMN IF NOT EXISTS stt_seconds DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE public.drona_sessions ADD COLUMN IF NOT EXISTS tts_characters INT DEFAULT 0;
ALTER TABLE public.drona_sessions ADD COLUMN IF NOT EXISTS reconnect_count INT DEFAULT 0;

ALTER TABLE public.drona_turns ADD COLUMN IF NOT EXISTS tts_failure_count INT DEFAULT 0;

-- 3. Information Schema Verification Query (Run after executing above)
SELECT table_name, column_name 
FROM information_schema.columns
WHERE table_name IN ('drona_sessions', 'drona_turns', 'drona_wellbeing_flags', 'drona_rate_limits')
  AND column_name IN ('mute_duration_sec', 'stt_seconds', 'tts_characters', 'reconnect_count', 'tts_failure_count', 'id')
ORDER BY table_name, column_name;
