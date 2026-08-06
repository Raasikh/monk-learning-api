-- Migration 0008: Add Drona Telemetry Columns
-- Adds missing telemetry columns to drona_sessions and drona_turns

ALTER TABLE drona_sessions ADD COLUMN IF NOT EXISTS mute_duration_sec DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE drona_sessions ADD COLUMN IF NOT EXISTS stt_seconds DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE drona_sessions ADD COLUMN IF NOT EXISTS tts_characters INT DEFAULT 0;
ALTER TABLE drona_sessions ADD COLUMN IF NOT EXISTS reconnect_count INT DEFAULT 0;

ALTER TABLE drona_turns ADD COLUMN IF NOT EXISTS tts_failure_count INT DEFAULT 0;
