-- ============================================================================
-- 0011_drona_tutor_voice.sql — student-selectable tutor persona
-- ============================================================================
-- Adds the per-session tutor voice choice. 'female' -> Rumik preset "Ira",
-- display name "Veda". 'male' -> Rumik preset "Lucas", display name "Drona".
-- Default 'female' preserves the behaviour that was previously hardcoded in
-- app/drona/tutor.py and app/drona/live_session_ws.py.

ALTER TABLE drona_sessions
  ADD COLUMN IF NOT EXISTS tutor_voice TEXT NOT NULL DEFAULT 'female';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'drona_sessions_tutor_voice_check'
  ) THEN
    ALTER TABLE drona_sessions
      ADD CONSTRAINT drona_sessions_tutor_voice_check
      CHECK (tutor_voice IN ('male', 'female'));
  END IF;
END $$;

-- Verification (run after applying):
-- SELECT column_name, data_type, column_default, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'drona_sessions' AND column_name = 'tutor_voice';
