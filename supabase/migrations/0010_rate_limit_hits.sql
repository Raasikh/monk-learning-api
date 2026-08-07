-- Migration 0010: Add rate_limit_hits tracking column to drona_sessions
ALTER TABLE drona_sessions ADD COLUMN IF NOT EXISTS rate_limit_hits SMALLINT DEFAULT 0;
