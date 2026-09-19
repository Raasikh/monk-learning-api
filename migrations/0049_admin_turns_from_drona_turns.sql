-- 0049_admin_turns_from_drona_turns.sql
--
-- Count turns from `drona_turns`, not from `drona_sessions.turn_count`.
--
-- Measured against live data the day 0048 went in:
--
--   drona_sessions rows              826
--   ...with turn_count > 0             0      <- never incremented, ever
--   drona_turns rows               1,819
--
-- `turn_count` is declared `not null default 0` in 0005 and nothing in the
-- codebase has ever written to it, so the column is a permanent zero. The
-- dashboard duly reported "avg 0.0 turns" across 174 sessions — a number that
-- is not merely wrong but wrong in the most misleading direction available,
-- since 0.0 turns reads as "students open the classroom and never speak"
-- rather than as "this column is dead".
--
-- `drona_turns` is the real record: one row per exchange, written by the tutor
-- path. Two functions from 0048 are replaced to read it. Nothing else in 0048
-- changes, and its grants survive — `create or replace function` keeps the
-- existing ACL, and the verification query at the foot of 0048 will still come
-- back empty. (Re-run it anyway; a one-line check is cheaper than the
-- assumption.)
--
-- Not fixed here: `turn_count` itself. Whether to start writing it, or to drop
-- the column, is a question about the tutor path rather than about analytics,
-- and a migration that reaches into live session state deserves its own change
-- rather than riding along with a dashboard fix.

begin;

-- ───────────────────────────────────────────────────────────────────────────
-- admin_features — identical to 0048 except `drona_avg_turns`.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_features(p_days int default 30)
returns jsonb
language sql
stable
security definer
set search_path = public
as $fn$
with p as (
  select greatest(coalesce(p_days, 30), 1) as days,
         (now() at time zone 'Asia/Kolkata')::date as today
),
b as (
  select days, today,
         (today - (days - 1))::date as from_day,
         (((today - (days - 1))::timestamp) at time zone 'Asia/Kolkata') as from_ts
  from p
),
pa as (
  select (created_at at time zone 'Asia/Kolkata')::date as day,
         user_id, is_correct, gave_up
  from public.practice_attempts where created_at >= (select from_ts from b)
),
ds as (
  select id, (created_at at time zone 'Asia/Kolkata')::date as day,
         user_id, mode, language, phase, cost_usd
  from public.drona_sessions where created_at >= (select from_ts from b)
),
-- Turns per session, counted from the rows that actually exist. A session with
-- no turns still counts as a zero — it is a real outcome (someone opened the
-- classroom and left), and dropping it would inflate the average.
turns_per_session as (
  select ds.id, (select count(*) from public.drona_turns t where t.session_id = ds.id) as n
  from ds
),
dbt as (
  select (created_at at time zone 'Asia/Kolkata')::date as day,
         user_id, solved
  from public.doubts where created_at >= (select from_ts from b)
),
nt as (
  select (created_at at time zone 'Asia/Kolkata')::date as day, user_id
  from public.notes where created_at >= (select from_ts from b)
),
days as (
  select d::date as day
  from generate_series((select from_day from b), (select today from b), interval '1 day') d
)
select jsonb_build_object(
  'window_days', (select days from b),
  'totals', jsonb_build_object(
    'practice_attempts',  (select count(*) from pa),
    'practice_users',     (select count(distinct user_id) from pa),
    'practice_accuracy',  (select round(100.0 * count(*) filter (where is_correct)
                                  / nullif(count(*) filter (where not gave_up), 0), 1) from pa),
    'practice_gave_up_rate', (select round(100.0 * count(*) filter (where gave_up)
                                  / nullif(count(*), 0), 1) from pa),
    'drona_sessions',     (select count(*) from ds),
    'drona_users',        (select count(distinct user_id) from ds),
    'drona_completion_rate', (select round(100.0 * count(*) filter (where phase = 'complete')
                                  / nullif(count(*), 0), 1) from ds),
    'drona_avg_turns',    (select round(coalesce(avg(n), 0)::numeric, 1) from turns_per_session),
    'drona_total_turns',  (select coalesce(sum(n), 0) from turns_per_session),
    'drona_cost_usd',     (select round(coalesce(sum(cost_usd), 0)::numeric, 4) from ds),
    'doubts',             (select count(*) from dbt),
    'doubts_users',       (select count(distinct user_id) from dbt),
    'doubts_solved_rate', (select round(100.0 * count(*) filter (where solved)
                                  / nullif(count(*), 0), 1) from dbt),
    'notes',              (select count(*) from nt),
    'notes_users',        (select count(distinct user_id) from nt)
  ),
  'drona_by_mode',     (select coalesce(jsonb_object_agg(coalesce(mode, 'unknown'), n), '{}'::jsonb)
                        from (select mode, count(*) n from ds group by 1) x),
  'drona_by_language', (select coalesce(jsonb_object_agg(coalesce(language, 'unknown'), n), '{}'::jsonb)
                        from (select language, count(*) n from ds group by 1) x),
  'drona_by_phase',    (select coalesce(jsonb_object_agg(coalesce(phase, 'unknown'), n), '{}'::jsonb)
                        from (select phase, count(*) n from ds group by 1) x),
  'daily', (
    select coalesce(jsonb_agg(jsonb_build_object(
             'day',      d.day,
             'practice', (select count(*) from pa  where pa.day  = d.day),
             'drona',    (select count(*) from ds  where ds.day  = d.day),
             'doubts',   (select count(*) from dbt where dbt.day = d.day),
             'notes',    (select count(*) from nt  where nt.day  = d.day)
           ) order by d.day), '[]'::jsonb)
    from days d
  )
)
$fn$;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_user — `recent_sessions` carried the same dead column.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_user(p_user_id uuid, p_days int default 30)
returns jsonb
language sql
stable
security definer
set search_path = public
as $fn$
with p as (
  select greatest(coalesce(p_days, 30), 1) as days,
         (now() at time zone 'Asia/Kolkata')::date as today
),
b as (
  select days, today,
         (today - (days - 1))::date as from_day,
         (((today - (days - 1))::timestamp) at time zone 'Asia/Kolkata') as from_ts
  from p
),
u as (
  select id, email, created_at, last_sign_in_at
  from auth.users where id = p_user_id
),
days as (
  select d::date as day
  from generate_series((select from_day from b), (select today from b), interval '1 day') d
),
act as (
  select (a.at at time zone 'Asia/Kolkata')::date as day
  from public.admin_activity((select from_ts from b)) a
  where a.user_id = p_user_id
)
select case when not exists (select 1 from u) then null else jsonb_build_object(
  'user_id',         p_user_id,
  'email',           (select email from u),
  'signed_up_at',    (select created_at from u),
  'last_sign_in_at', (select last_sign_in_at from u),
  'profile', (
    select to_jsonb(x) from (
      select display_name, phone, phone_verified, target_exam, enrolled_class, created_at
      from public.profiles where id = p_user_id
    ) x
  ),
  'totals', jsonb_build_object(
    'attempts', (select count(*) from public.practice_attempts where user_id = p_user_id),
    'correct',  (select count(*) from public.practice_attempts where user_id = p_user_id and is_correct),
    'gave_up',  (select count(*) from public.practice_attempts where user_id = p_user_id and gave_up),
    'sessions', (select count(*) from public.drona_sessions where user_id = p_user_id),
    'sessions_completed', (select count(*) from public.drona_sessions
                           where user_id = p_user_id and phase = 'complete'),
    'turns',    (select count(*) from public.drona_turns t
                 where t.session_id in (select id from public.drona_sessions where user_id = p_user_id)),
    'doubts',   (select count(*) from public.doubts where user_id = p_user_id),
    'doubts_solved', (select count(*) from public.doubts where user_id = p_user_id and solved),
    'notes',    (select count(*) from public.notes where user_id = p_user_id),
    'cost_usd', (select round(coalesce(sum(cost_usd), 0)::numeric, 4)
                 from public.llm_calls where user_id = p_user_id),
    'last_active_at', greatest(
      (select max(created_at)   from public.practice_attempts where user_id = p_user_id),
      (select max(last_turn_at) from public.drona_sessions   where user_id = p_user_id),
      (select max(created_at)   from public.doubts           where user_id = p_user_id),
      (select max(created_at)   from public.notes            where user_id = p_user_id)
    )
  ),
  'daily', (
    select coalesce(jsonb_agg(jsonb_build_object(
             'day', d.day,
             'events', (select count(*) from act where act.day = d.day)
           ) order by d.day), '[]'::jsonb)
    from days d
  ),
  'recent_sessions', (
    select coalesce(jsonb_agg(to_jsonb(x) order by x.created_at desc), '[]'::jsonb)
    from (select s.id, s.mode, s.language, s.phase, s.subtopic_key,
                 -- was s.turn_count, which is always 0
                 (select count(*) from public.drona_turns t where t.session_id = s.id) as turn_count,
                 s.cost_usd, s.created_at, s.completed_at
          from public.drona_sessions s where s.user_id = p_user_id
          order by s.created_at desc limit 15) x
  ),
  'recent_doubts', (
    select coalesce(jsonb_agg(to_jsonb(x) order by x.created_at desc), '[]'::jsonb)
    from (select id, chapter, concept, solved, status, question_text, created_at
          from public.doubts where user_id = p_user_id
          order by created_at desc limit 15) x
  ),
  'recent_notes', (
    select coalesce(jsonb_agg(to_jsonb(x) order by x.created_at desc), '[]'::jsonb)
    from (select id, chapter_id, item_count, segments_covered, total_segments, created_at
          from public.notes where user_id = p_user_id
          order by created_at desc limit 15) x
  )
) end
$fn$;

-- drona_turns is now read per session on every features call; without this the
-- count is a sequential scan per row.
create index if not exists drona_turns_session_idx
  on public.drona_turns (session_id);

commit;

-- ─── Verification ──────────────────────────────────────────────────────────
--
--   select public.admin_features(30)->'totals'->>'drona_avg_turns';   -- was 0.0
--   select public.admin_features(30)->'totals'->>'drona_total_turns';
--
-- And confirm 0048's grants survived the replace (must be zero rows):
--
--   select p.proname, a.rolname
--   from pg_proc p cross join lateral aclexplode(p.proacl) acl
--   join pg_roles a on a.oid = acl.grantee
--   where p.proname like 'admin\_%' and a.rolname in ('anon','authenticated');
