-- ============================================================================
-- 0007_drona_voice.sql — Learn with Drona v1 / Phase 2 (Voice)
-- ============================================================================

begin;

alter table drona_sessions
  add column if not exists mute_duration_sec integer not null default 0,
  add column if not exists stt_seconds numeric(10,2) not null default 0,
  add column if not exists tts_characters integer not null default 0,
  add column if not exists reconnect_count smallint not null default 0;

alter table drona_turns
  add column if not exists offtopic_tier smallint
    check (offtopic_tier between 1 and 5),
  add column if not exists playback_cutoff_point text,
  add column if not exists stt_confidence numeric(4,3);

create table if not exists drona_wellbeing_flags (
  id         uuid primary key default gen_random_uuid(),
  session_id uuid not null references drona_sessions(id) on delete cascade,
  turn_id    uuid not null references drona_turns(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  tier       text not null check (tier in ('distress','explicit_self_harm')),
  utterance  text not null,
  reviewed   boolean not null default false,
  created_at timestamptz not null default now()
);

alter table drona_wellbeing_flags enable row level security;
-- Zero policies. Server-only. Never client-readable, including by the student
-- who triggered it.

alter table profiles
  add column if not exists drona_language text not null default 'hinglish'
  check (drona_language in ('english','hinglish'));

commit;
