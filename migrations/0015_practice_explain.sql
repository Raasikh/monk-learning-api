-- ============================================================================
-- 0015_practice_explain.sql — "Talk to the teacher" from a Practice question
-- ============================================================================
-- Adds a third drona_sessions mode: a disposable, question-scoped session
-- seeded from a just-answered practice question instead of an authored
-- lesson_plans row. question_id is kept as a real column for joins/analytics;
-- practice_seed snapshots the full question context (stem, options, the
-- student's answer, the correct answer, the solution) at session-creation
-- time, matching the existing lesson_plans.plan_json snapshot pattern so a
-- turn's prompt is reproducible without depending on the live questions row.

begin;

alter table drona_sessions
  add column if not exists question_id uuid,
  add column if not exists practice_seed jsonb;

-- 0005_drona.sql defined `mode`'s CHECK inline with no explicit name, so
-- Postgres auto-named it. Look the name up rather than assuming it, so this
-- migration is correct even if that assumption is wrong.
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
    check (mode in ('chapter', 'free_text', 'practice_explain'));
end $$;

commit;
