-- ============================================================================
-- 0005_drona.sql — Learn with Drona v1
-- ============================================================================

begin;

create extension if not exists vector;

-- 1. Master PDF chunks for grounded retrieval
create table if not exists pdf_chunks (
  id            uuid primary key default gen_random_uuid(),
  chapter_id    uuid references chapters(id) on delete cascade,
  subject       text not null,
  class_level   smallint not null,
  source_file   text not null,
  page_start    smallint,
  page_end      smallint,
  chunk_index   integer not null,
  content       text not null,
  embedding     vector(1536) not null,
  created_at    timestamptz not null default now()
);
create index if not exists pdf_chunks_chapter_idx on pdf_chunks (chapter_id);
create unique index if not exists pdf_chunks_dedupe_idx
  on pdf_chunks (source_file, chunk_index);

-- 2. Subtopic index
create table if not exists subtopic_index (
  id               uuid primary key default gen_random_uuid(),
  chapter_id       uuid not null references chapters(id) on delete cascade,
  subtopic         text not null,
  subtopic_key     text not null,
  section_count    smallint not null default 0,
  grounding_status text not null default 'grounded' check (grounding_status in ('grounded','sections_only','unavailable')),
  unique (chapter_id, subtopic_key)
);

-- 3. Cached lesson plans
create table if not exists lesson_plans (
  id             uuid primary key default gen_random_uuid(),
  chapter_id     uuid references chapters(id) on delete set null,
  subtopic_key   text,
  topic_hash     text,
  plan_json      jsonb not null,
  grounded       boolean not null,
  segment_count  smallint not null,
  source_model   text not null,
  prompt_version text not null,
  reviewed_by    text,
  created_at     timestamptz not null default now()
);
create unique index if not exists lesson_plans_subtopic_idx
  on lesson_plans (chapter_id, subtopic_key)
  where subtopic_key is not null;
create unique index if not exists lesson_plans_topic_hash_idx
  on lesson_plans (topic_hash)
  where topic_hash is not null;

-- 4. Sessions
create table if not exists drona_sessions (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users(id) on delete cascade,
  mode           text not null check (mode in ('chapter','free_text')),
  chapter_id     uuid references chapters(id) on delete set null,
  subtopic_key   text,
  language       text not null check (language in ('english','hinglish')),
  plan_id        uuid references lesson_plans(id) on delete set null,
  phase          text not null check (phase in
                   ('scoping','teaching','awaiting_answer','wrapup','complete','abandoned')),
  current_segment smallint not null default 1,
  attempts_on_current_question smallint not null default 0,
  history_summary text[] not null default '{}',
  grounded       boolean not null default true,
  top1_similarity numeric(5,4),          -- top1 similarity score on free-text session
  mute_duration_sec integer not null default 0, -- accumulated student mute duration in seconds
  prompt_version text not null,
  turn_count     smallint not null default 0,
  cost_usd       numeric(10,6) not null default 0,
  created_at     timestamptz not null default now(),
  last_turn_at   timestamptz not null default now(),
  completed_at   timestamptz
);
create index if not exists drona_sessions_user_idx on drona_sessions (user_id);

-- 5. Turn log
create table if not exists drona_turns (
  id             uuid primary key default gen_random_uuid(),
  session_id     uuid not null references drona_sessions(id) on delete cascade,
  turn_index     smallint not null,
  segment_index  smallint not null,
  phase_in       text not null,
  utterance      text,
  is_interruption boolean not null default false,
  raw_response   jsonb not null,
  grade          text check (grade in ('correct','partial','incorrect')),
  filter_tier2_violation boolean not null default false,
  latency_ms     integer,
  input_tokens   integer,
  cache_hit_tokens integer,
  output_tokens  integer,
  created_at     timestamptz not null default now()
);
create index if not exists drona_turns_session_idx on drona_turns (session_id);

-- 6. Misconceptions
create table if not exists student_misconceptions (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users(id) on delete cascade,
  session_id     uuid not null references drona_sessions(id) on delete cascade,
  chapter_id     uuid references chapters(id) on delete set null,
  subtopic_key   text,
  tag_raw        text not null,
  tag_canonical  text,
  was_seeded     boolean not null,
  created_at     timestamptz not null default now()
);
create index if not exists student_misconceptions_user_chapter_idx
  on student_misconceptions (user_id, chapter_id);

-- 7. RLS Configuration
alter table pdf_chunks    enable row level security;
alter table lesson_plans  enable row level security;

alter table subtopic_index enable row level security;
drop policy if exists subtopic_index_public_read on subtopic_index;
create policy subtopic_index_public_read
  on subtopic_index for select using (true);

alter table drona_sessions enable row level security;
drop policy if exists drona_sessions_owner_read on drona_sessions;
create policy drona_sessions_owner_read
  on drona_sessions for select using (auth.uid() = user_id);

alter table drona_turns enable row level security;
drop policy if exists drona_turns_owner_read on drona_turns;
create policy drona_turns_owner_read
  on drona_turns for select
  using (
    exists (
      select 1 from drona_sessions s
      where s.id = drona_turns.session_id and s.user_id = auth.uid()
    )
  );

alter table student_misconceptions enable row level security;
drop policy if exists student_misconceptions_owner_read on student_misconceptions;
create policy student_misconceptions_owner_read
  on student_misconceptions for select using (auth.uid() = user_id);

commit;
