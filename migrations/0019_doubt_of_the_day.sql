-- ============================================================================
-- 0019_doubt_of_the_day.sql — the curated "doubt of the day" pool
-- ============================================================================
-- The dashboard card previously pulled a row out of `questions` by
-- day-of-year, which served an ordinary practice question, identical for every
-- student in the country, with no regard for whether they sit JEE or NEET.
-- This table holds the hand-curated pool instead (seeded from
-- dronav1project/apps_and_demos/Doubt_Of_The_Day/dotd_all.json by
-- scripts/seed_doubt_of_the_day.py): short, deliberately curiosity-shaped
-- doubts, each carrying its own verified answer and explanation.
--
-- `subject_ordinal` is what makes the daily pick cheap. Rows are numbered
-- 1..N *within* each subject at seed time, so the app can address one exact
-- row with an indexed two-column lookup instead of counting the table and
-- paging into it by offset. The per-student rotation walks those ordinals
-- with a stride coprime to N, which visits every doubt in a subject before
-- repeating any of them (see monk-learning-web/src/lib/dotd.ts).
--
-- `exam_tracks` deliberately does NOT copy the source JSON's `_exam_track`
-- field. That field tags all 250 physics and all 250 chemistry rows "JEE"
-- purely because of where they were authored — filtering a NEET student on it
-- would serve them biology and nothing else. Physics and chemistry doubts at
-- this level are syllabus-neutral, so they are tagged for both tracks and the
-- subject mix is decided by the app, not by the row.

begin;

create table if not exists doubt_of_the_day (
  id             uuid primary key default gen_random_uuid(),
  subject        text not null check (subject in ('physics', 'chemistry', 'mathematics', 'biology')),
  subject_ordinal integer not null,
  chapter        text,
  concept        text,
  question_text  text not null,
  answer         text not null,
  explanation    text not null,
  difficulty     text,
  exam_tracks    text[] not null default '{JEE,NEET}',
  active         boolean not null default true,
  created_at     timestamptz not null default now()
);

-- The daily pick's only lookup: (subject, subject_ordinal) -> one row. It is
-- also the seed script's upsert target, which is why it is a plain two-column
-- unique index and not an expression index over question_text: PostgREST can
-- only name real columns in `on_conflict`.
create unique index if not exists doubt_of_the_day_subject_ordinal_idx
  on doubt_of_the_day (subject, subject_ordinal);

alter table doubt_of_the_day enable row level security;

-- Shared content, same as concepts/chapter_aliases: any signed-in student
-- reads the pool. Writes happen only through the service-role seed script.
do $$
begin
  if not exists (
    select 1 from pg_policies
    where tablename = 'doubt_of_the_day' and policyname = 'doubt_of_the_day_read_all'
  ) then
    create policy doubt_of_the_day_read_all
      on doubt_of_the_day for select to authenticated using (active);
  end if;
end $$;

-- A fourth drona_sessions mode: the quick chat launched from the card. Like
-- practice_explain it is disposable and question-scoped, so it carries its own
-- snapshot column rather than reading the doubt row live at turn time.
alter table drona_sessions
  add column if not exists doubt_id uuid references doubt_of_the_day(id) on delete set null,
  add column if not exists doubt_seed jsonb;

-- Same lookup-don't-assume dance as 0015: the CHECK was re-created there with
-- an explicit name, but re-deriving it keeps this correct either way.
do $$
declare
  cname text;
begin
  select conname into cname
  from pg_constraint
  where conrelid = 'drona_sessions'::regclass
    and contype = 'c'
    and pg_get_constraintdef(oid) like '%mode%';

  if cname is not null then
    execute format('alter table drona_sessions drop constraint %I', cname);
  end if;

  alter table drona_sessions
    add constraint drona_sessions_mode_check
    check (mode in ('chapter', 'free_text', 'practice_explain', 'doubt_of_day'));
end $$;

commit;
