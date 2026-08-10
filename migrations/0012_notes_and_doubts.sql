-- ============================================================================
-- 0012_notes_and_doubts.sql — Notes, Snap It Out, My Doubts
--
-- NUMBERING: the Snap directive calls this `0011_doubts.sql`. 0011 is already
-- taken in this repo by 0011_drona_tutor_voice.sql, so this lands as 0012.
--
-- LIVE STATE THIS WAS WRITTEN AGAINST (verified, not assumed):
--   notes          EXISTS, 0 rows — id, user_id, subject, chapter, concept,
--                  content, created_at  (already matches the web pages)
--   doubts         EXISTS, 0 rows — id, user_id, image_url, transcribed_question,
--                  question_latex, subject, chapter_name, answer_json, solved,
--                  created_at  (old stub, does NOT match the web pages)
--   doubt_reports  ABSENT
--
-- `create table if not exists` would silently do NOTHING against those stubs and
-- leave every new column missing — the exact failure mode AGENTS.md Rule 9
-- exists to catch (0007 and 0008 were both reported applied and were not). So
-- every table is reconciled column by column.
--
-- COLUMN CONTRACT: the web pages read Supabase directly, so their names win —
-- subject / chapter / concept / content / question_text / explanation / solved.
-- The structured columns (board_items, steps, answer, key_idea) sit alongside
-- them so nothing is lost; FastAPI writes both the flat text and the structure.
--
-- IMAGES live in Cloudflare R2. The row stores the object KEY
-- (`doubts/{user_id}/{submission_id}.jpg`), never a public URL — a student's
-- photographed homework must not be publicly addressable. `image_url` is
-- therefore dropped.
--
-- RLS: owner-read only, and it is REQUIRED — the /notes and /doubts pages query
-- Supabase from the browser under the student's own session. There are NO
-- insert/update/delete policies: FastAPI holds the service role key and does
-- every write (AGENTS.md Rule 9).
--
-- This file is re-runnable. The destructive step refuses to run if the table
-- has rows, rather than reshaping data.
-- ============================================================================

begin;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. notes — a Drona session's board, kept by the student.
--
--    The existing columns already match the web pages, so nothing is renamed
--    or dropped here. `content` is the readable board the note page renders;
--    `board_items` keeps the same board as structured events so it can be
--    re-rendered through the live session's board components.
-- ─────────────────────────────────────────────────────────────────────────────
alter table notes add column if not exists session_id         uuid;
alter table notes add column if not exists chapter_id         uuid;
alter table notes add column if not exists board_items        jsonb not null default '[]'::jsonb;
alter table notes add column if not exists segments_covered   smallint not null default 0;
alter table notes add column if not exists total_segments     smallint not null default 0;
alter table notes add column if not exists item_count         smallint not null default 0;
alter table notes add column if not exists session_started_at timestamptz;

do $$
begin
  if not exists (
    select 1 from information_schema.table_constraints
    where table_schema = 'public' and constraint_name = 'notes_session_id_fkey'
  ) then
    alter table notes
      add constraint notes_session_id_fkey
      foreign key (session_id) references drona_sessions(id) on delete set null;
  end if;

  if not exists (
    select 1 from information_schema.table_constraints
    where table_schema = 'public' and constraint_name = 'notes_chapter_id_fkey'
  ) then
    alter table notes
      add constraint notes_chapter_id_fkey
      foreign key (chapter_id) references chapters(id) on delete set null;
  end if;
end $$;

-- One note per session: saving the same class twice refreshes it rather than
-- filling the shelf with duplicates.
create unique index if not exists notes_session_idx
  on notes (session_id) where session_id is not null;
create index if not exists notes_user_created_idx
  on notes (user_id, created_at desc);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. doubts — one transcribed question and its solution.
--
--    One row per QUESTION, not per photo: a submission may hold up to 2
--    questions, which share a submission_id and an image_key.
--
--    Step 2a reshapes the old stub. It is guarded: if the table ever has rows
--    AND still carries the legacy columns, it raises instead of destroying
--    data. Once migrated, re-running this file is a no-op.
-- ─────────────────────────────────────────────────────────────────────────────
do $$
declare
  row_count bigint;
  has_legacy boolean;
begin
  select count(*) into row_count from doubts;

  select exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'doubts'
      and column_name in ('image_url', 'transcribed_question', 'question_latex',
                          'answer_json', 'chapter_name')
  ) into has_legacy;

  if has_legacy and row_count > 0 then
    raise exception
      'doubts has % row(s) and still carries the legacy stub columns. Refusing '
      'to reshape it. Migrate the data by hand, then re-run this migration.',
      row_count;
  end if;

  -- Clean 1:1 renames, so the intent is visible rather than add-then-drop.
  if has_legacy
     and exists (select 1 from information_schema.columns
                 where table_schema='public' and table_name='doubts'
                   and column_name='chapter_name')
     and not exists (select 1 from information_schema.columns
                     where table_schema='public' and table_name='doubts'
                       and column_name='chapter') then
    alter table doubts rename column chapter_name to chapter;
  end if;

  if has_legacy
     and exists (select 1 from information_schema.columns
                 where table_schema='public' and table_name='doubts'
                   and column_name='transcribed_question')
     and not exists (select 1 from information_schema.columns
                     where table_schema='public' and table_name='doubts'
                       and column_name='question_text') then
    alter table doubts rename column transcribed_question to question_text;
  end if;

  -- Superseded. image_url in particular must go: we store the key, not a URL.
  alter table doubts drop column if exists image_url;
  alter table doubts drop column if exists question_latex;
  alter table doubts drop column if exists answer_json;
  alter table doubts drop column if exists chapter_name;
  alter table doubts drop column if exists transcribed_question;
end $$;

-- 2b. The columns the web pages read.
alter table doubts add column if not exists chapter           text;
alter table doubts add column if not exists concept           text;
alter table doubts add column if not exists question_text     text;
alter table doubts add column if not exists explanation       text;
alter table doubts add column if not exists solved            boolean not null default false;

-- 2c. The columns the pipeline needs.
alter table doubts add column if not exists submission_id     uuid;
alter table doubts add column if not exists question_index    smallint not null default 1;
alter table doubts add column if not exists image_key         text;
alter table doubts add column if not exists legible           boolean not null default true;
alter table doubts add column if not exists legibility_note   text;
alter table doubts add column if not exists answer            text;
alter table doubts add column if not exists steps             jsonb not null default '[]'::jsonb;
alter table doubts add column if not exists key_idea          text;
alter table doubts add column if not exists status            text not null default 'solved';
alter table doubts add column if not exists failure_reason    text;
alter table doubts add column if not exists transcriber_model text;
alter table doubts add column if not exists solver_model      text;
alter table doubts add column if not exists transcribe_ms     integer;
alter table doubts add column if not exists latency_ms        integer;

-- `solved` is the boolean the list page renders; `status` carries the three-way
-- outcome. FastAPI writes both, and this keeps them from disagreeing.
alter table doubts drop constraint if exists doubts_status_check;
alter table doubts add constraint doubts_status_check
  check (status in ('solved', 'failed', 'illegible'));

alter table doubts drop constraint if exists doubts_solved_matches_status;
alter table doubts add constraint doubts_solved_matches_status
  check (solved = (status = 'solved'));

create index if not exists doubts_user_created_idx
  on doubts (user_id, created_at desc);
create index if not exists doubts_submission_idx
  on doubts (submission_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. doubt_reports — "Report a mistake". Read-only for now; it exists so wrong
--    answers are countable rather than invisible.
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists doubt_reports (
  id         uuid primary key default gen_random_uuid(),
  doubt_id   uuid not null references doubts(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  comment    text,
  created_at timestamptz not null default now()
);

create index if not exists doubt_reports_doubt_idx on doubt_reports (doubt_id);
create index if not exists doubt_reports_user_idx  on doubt_reports (user_id);
-- One standing report per student per doubt; re-reporting updates the comment
-- rather than inflating the count.
create unique index if not exists doubt_reports_unique_idx
  on doubt_reports (doubt_id, user_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. RLS — owner-read only. No write policies: FastAPI writes.
--    Without these SELECT policies the web pages return zero rows.
-- ─────────────────────────────────────────────────────────────────────────────
alter table notes enable row level security;
drop policy if exists notes_owner_read on notes;
create policy notes_owner_read
  on notes for select using (auth.uid() = user_id);

alter table doubts enable row level security;
drop policy if exists doubts_owner_read on doubts;
create policy doubts_owner_read
  on doubts for select using (auth.uid() = user_id);

alter table doubt_reports enable row level security;
drop policy if exists doubt_reports_owner_read on doubt_reports;
create policy doubt_reports_owner_read
  on doubt_reports for select using (auth.uid() = user_id);

commit;

-- ============================================================================
-- VERIFY (Rule 9 — the migration file is not evidence; the catalog is):
--
--   select table_name, column_name, data_type
--   from information_schema.columns
--   where table_schema = 'public'
--     and table_name in ('notes', 'doubts', 'doubt_reports')
--   order by table_name, ordinal_position;
--
--   select tablename, policyname, cmd
--   from pg_policies
--   where tablename in ('notes', 'doubts', 'doubt_reports');
--
-- Or from the repo:  python scratch/apply_0012_notes_and_doubts.py
-- ============================================================================
