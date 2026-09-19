-- 0048_admin_analytics.sql
--
-- The read side of the founders' dashboard (/admin).
--
-- Every number the dashboard shows is computed HERE, in Postgres, not in
-- Python. Two reasons, both learned from app/routers/progress.py:
--
--  1. PostgREST caps a response at 1000 rows and reports no error when it
--     truncates (see the note in app/db.py). Counting DAU by pulling
--     practice_attempts into the API and len()-ing it is wrong the day the
--     table passes a thousand rows, and wrong SILENTLY.
--  2. One RPC round trip per panel instead of a dozen .table() calls. The API
--     has a single uvicorn worker (railway.toml) — a dashboard that fans out
--     twenty Supabase reads is twenty ~325ms blocking hops competing with
--     live classroom audio.
--
-- ─── Who may call these ────────────────────────────────────────────────────
-- SECURITY DEFINER, because they read auth.users and cross every student's
-- rows — exactly what RLS exists to prevent. So EXECUTE is revoked from
-- `anon` and `authenticated` and granted ONLY to `service_role`. A student's
-- publishable key cannot reach them even by guessing the name: the mobile app
-- holds the anon key, the FastAPI process holds the secret key, and only the
-- latter is allowed in. The admin allowlist is enforced a second time above
-- this, in app/routers/admin.py — this grant is the floor, not the gate.
--
-- ─── Two definitions worth arguing with ────────────────────────────────────
--
-- DAYS ARE IST. Every bucket boundary is Asia/Kolkata, not UTC. A student
-- practising at 11pm in Delhi is 17:30 UTC — under UTC bucketing half of your
-- evening peak lands on "yesterday" and DAU looks flat when it isn't.
--
-- A USER IS auth.users, NOT profiles. `profiles` only gets a row when
-- onboarding COMPLETES (lib/profile.ts upserts it at the end), so counting
-- signups from profiles silently hides everyone who verified their email and
-- then bailed — the single most important number a pre-launch product has.
-- auth.users is the spine; profiles is joined for the display fields.
-- `email is not null` excludes the anonymous sessions every pre-email-auth
-- install was handed (see the anon branch in lib/auth.ts).

begin;

-- ───────────────────────────────────────────────────────────────────────────
-- Indexes. Every function below filters or maxes on created_at.
-- ───────────────────────────────────────────────────────────────────────────
create index if not exists practice_attempts_created_idx
  on public.practice_attempts (created_at desc);
create index if not exists drona_sessions_created_idx
  on public.drona_sessions (created_at desc);
create index if not exists doubts_created_idx
  on public.doubts (created_at desc);
create index if not exists notes_created_idx
  on public.notes (created_at desc);


-- ───────────────────────────────────────────────────────────────────────────
-- admin_activity — the one definition of "this user did something".
--
-- Four tables, because there is no events table yet and these are what the
-- product actually records: a practice answer, a classroom session, a snapped
-- doubt, a saved note. Anything that counts as "active" anywhere in this
-- dashboard counts as active HERE, so DAU, retention and the per-user
-- "last seen" column can never quietly disagree about what activity means.
--
-- Add a fifth source here and every panel picks it up at once.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_activity(p_from timestamptz)
returns table (user_id uuid, at timestamptz)
language sql
stable
security definer
set search_path = public
as $fn$
  select user_id, created_at from public.practice_attempts
    where created_at >= p_from and user_id is not null
  union all
  select user_id, created_at from public.drona_sessions
    where created_at >= p_from and user_id is not null
  union all
  select user_id, created_at from public.doubts
    where created_at >= p_from and user_id is not null
  union all
  select user_id, created_at from public.notes
    where created_at >= p_from and user_id is not null
$fn$;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_overview — headline counters + the signups/active daily series.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_overview(p_days int default 30)
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
         -- WAU and MAU are fixed 7/30-day windows regardless of the chart's
         -- range, so activity is read over whichever span is longer. Without
         -- this, asking for a 7-day chart would report MAU as a 7-day count.
         (((today - (greatest(days, 30) - 1))::timestamp) at time zone 'Asia/Kolkata') as act_from
  from p
),
act as (
  select a.user_id, (a.at at time zone 'Asia/Kolkata')::date as day
  from b, public.admin_activity(b.act_from) a
),
u as (
  select id, (created_at at time zone 'Asia/Kolkata')::date as day
  from auth.users
  where email is not null
),
days as (
  select d::date as day
  from generate_series((select from_day from b), (select today from b), interval '1 day') d
),
series as (
  select d.day,
         (select count(*) from u where u.day = d.day) as signups,
         (select count(distinct a.user_id) from act a where a.day = d.day) as active
  from days d
)
select jsonb_build_object(
  'window_days',  (select days from b),
  'from_day',     (select from_day from b),
  'to_day',       (select today from b),
  'generated_at', now(),
  'totals', jsonb_build_object(
    -- signed up (email verified) vs. actually finished onboarding. The gap
    -- between these two is the onboarding funnel, and it is the only funnel
    -- measurable without client-side event tracking.
    'users_total',     (select count(*) from u),
    'users_onboarded', (select count(*) from public.profiles),
    'users_new',       (select count(*) from u where u.day >= (select from_day from b)),
    'dau',             (select count(distinct a.user_id) from act a where a.day  = (select today from b)),
    'wau',             (select count(distinct a.user_id) from act a where a.day >  (select today from b) - 7),
    'mau',             (select count(distinct a.user_id) from act a where a.day >  (select today from b) - 30)
  ),
  'daily', (
    select coalesce(jsonb_agg(
             jsonb_build_object('day', day, 'signups', signups, 'active', active)
             order by day), '[]'::jsonb)
    from series
  )
)
$fn$;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_retention — weekly signup cohorts, D1 / D7 / D30.
--
-- Retention is WINDOWED, not exact-day: D7 means "came back on any day in
-- days 7-13 after signing up", not "came back on day 7 precisely". With a
-- handful of users a day, exact-day retention is mostly zeroes and tells you
-- nothing; the window is the standard fix.
--
-- `eligible` is reported alongside `returned` for each milestone and the
-- dashboard divides by it, never by cohort size. A cohort that signed up
-- yesterday CANNOT have 7-day retention yet — dividing by its full size
-- would print a fake collapse in the most recent (and most interesting)
-- column of the chart.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_retention(p_weeks int default 8)
returns jsonb
language sql
stable
security definer
set search_path = public
as $fn$
with p as (
  select greatest(coalesce(p_weeks, 8), 1) as weeks,
         (now() at time zone 'Asia/Kolkata')::date as today
),
cohort as (
  select u.id as user_id,
         u.created_at as signed_up_at,
         date_trunc('week', (u.created_at at time zone 'Asia/Kolkata'))::date as cohort_week
  from auth.users u
  where u.email is not null
    and (u.created_at at time zone 'Asia/Kolkata')::date
        >= (select today - (weeks * 7 - 1) from p)
),
act as (
  select a.user_id, a.at
  from (select min(signed_up_at) as m from cohort) s,
       public.admin_activity(s.m) a
),
flags as (
  select c.cohort_week,
         c.user_id,
         coalesce(bool_or(a.at >= c.signed_up_at + interval '1 day'
                      and a.at <  c.signed_up_at + interval '2 days'),  false) as d1,
         coalesce(bool_or(a.at >= c.signed_up_at + interval '7 days'
                      and a.at <  c.signed_up_at + interval '14 days'), false) as d7,
         coalesce(bool_or(a.at >= c.signed_up_at + interval '30 days'
                      and a.at <  c.signed_up_at + interval '37 days'), false) as d30,
         (now() >= c.signed_up_at + interval '2 days')  as elig_d1,
         (now() >= c.signed_up_at + interval '14 days') as elig_d7,
         (now() >= c.signed_up_at + interval '37 days') as elig_d30
  from cohort c
  left join act a on a.user_id = c.user_id
  group by c.cohort_week, c.user_id, c.signed_up_at
),
rolled as (
  select cohort_week,
         count(*) as size,
         jsonb_build_object(
           'eligible', count(*) filter (where elig_d1),
           'returned', count(*) filter (where elig_d1 and d1)) as d1,
         jsonb_build_object(
           'eligible', count(*) filter (where elig_d7),
           'returned', count(*) filter (where elig_d7 and d7)) as d7,
         jsonb_build_object(
           'eligible', count(*) filter (where elig_d30),
           'returned', count(*) filter (where elig_d30 and d30)) as d30
  from flags
  group by cohort_week
)
select coalesce(
  jsonb_agg(jsonb_build_object(
    'cohort_week', cohort_week, 'size', size,
    'd1', d1, 'd7', d7, 'd30', d30
  ) order by cohort_week), '[]'::jsonb)
from rolled
$fn$;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_features — what people actually use, and how well it works.
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
  select (created_at at time zone 'Asia/Kolkata')::date as day,
         user_id, mode, language, phase, turn_count, cost_usd
  from public.drona_sessions where created_at >= (select from_ts from b)
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
    -- Accuracy excludes gave-up attempts on purpose: 0043 added `gave_up`
    -- precisely because a student who tapped "show me" was otherwise
    -- indistinguishable from one who answered and missed.
    'practice_accuracy',  (select round(100.0 * count(*) filter (where is_correct)
                                  / nullif(count(*) filter (where not gave_up), 0), 1) from pa),
    'practice_gave_up_rate', (select round(100.0 * count(*) filter (where gave_up)
                                  / nullif(count(*), 0), 1) from pa),
    'drona_sessions',     (select count(*) from ds),
    'drona_users',        (select count(distinct user_id) from ds),
    'drona_completion_rate', (select round(100.0 * count(*) filter (where phase = 'complete')
                                  / nullif(count(*), 0), 1) from ds),
    'drona_avg_turns',    (select round(coalesce(avg(turn_count), 0)::numeric, 1) from ds),
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
-- admin_costs — what the LLMs are costing, from llm_calls (0018).
--
-- `ok = false` rows billed but had their result discarded. They are counted
-- in the spend and reported separately as `wasted_usd`: that number is pure
-- loss, and it is the one line here that can be acted on the same afternoon.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_costs(p_days int default 30)
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
c as (
  select (created_at at time zone 'Asia/Kolkata')::date as day,
         model, service, ok, cost_usd, latency_ms, user_id
  from public.llm_calls where created_at >= (select from_ts from b)
),
days as (
  select d::date as day
  from generate_series((select from_day from b), (select today from b), interval '1 day') d
)
select jsonb_build_object(
  'window_days', (select days from b),
  'totals', jsonb_build_object(
    'calls',       (select count(*) from c),
    'failed',      (select count(*) from c where not ok),
    'cost_usd',    (select round(coalesce(sum(cost_usd), 0)::numeric, 4) from c),
    'wasted_usd',  (select round(coalesce(sum(cost_usd) filter (where not ok), 0)::numeric, 4) from c),
    'p95_latency_ms', (select round(percentile_cont(0.95)
                               within group (order by latency_ms))::int
                       from c where latency_ms is not null),
    -- Cost per active user is the unit economic that matters before revenue
    -- exists: it is what one engaged student costs to serve for the window.
    'cost_per_active_user_usd', (
      select round(
        coalesce((select sum(cost_usd) from c), 0)
        / nullif((select count(distinct a.user_id)
                  from public.admin_activity((select from_ts from b)) a), 0)
      , 4)
    )
  ),
  'by_service', (select coalesce(jsonb_agg(jsonb_build_object(
                    'service', service, 'calls', n, 'cost_usd', cost) order by cost desc), '[]'::jsonb)
                 from (select service, count(*) n,
                              round(coalesce(sum(cost_usd), 0)::numeric, 4) cost
                       from c group by 1) x),
  'by_model',   (select coalesce(jsonb_agg(jsonb_build_object(
                    'model', model, 'calls', n, 'cost_usd', cost) order by cost desc), '[]'::jsonb)
                 from (select model, count(*) n,
                              round(coalesce(sum(cost_usd), 0)::numeric, 4) cost
                       from c group by 1) x),
  'daily', (
    select coalesce(jsonb_agg(jsonb_build_object(
             'day', d.day,
             'calls',    (select count(*) from c where c.day = d.day),
             'cost_usd', (select round(coalesce(sum(cost_usd), 0)::numeric, 4)
                          from c where c.day = d.day)
           ) order by d.day), '[]'::jsonb)
    from days d
  )
)
$fn$;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_users — the searchable user list.
--
-- Paginated by row_number rather than LIMIT/OFFSET so the total and the page
-- come back from one pass, and so p_sort can pick an ordering without the
-- caller ever interpolating a column name into SQL.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_users(
  p_q      text default null,
  p_limit  int  default 50,
  p_offset int  default 0,
  p_sort   text default 'recent'
)
returns jsonb
language sql
stable
security definer
set search_path = public
as $fn$
with args as (
  select nullif(trim(coalesce(p_q, '')), '')        as q,
         least(greatest(coalesce(p_limit, 50), 1), 200) as lim,
         greatest(coalesce(p_offset, 0), 0)         as off,
         coalesce(p_sort, 'recent')                 as sort
),
filtered as (
  select u.id as user_id, u.email, u.created_at as signed_up_at,
         u.last_sign_in_at,
         pr.display_name, pr.target_exam, pr.enrolled_class, pr.phone
  from auth.users u
  left join public.profiles pr on pr.id = u.id
  where u.email is not null
    and (
      (select q from args) is null
      or u.email                          ilike '%' || (select q from args) || '%'
      or coalesce(pr.display_name, '')    ilike '%' || (select q from args) || '%'
      or coalesce(pr.phone, '')           ilike '%' || (select q from args) || '%'
      or u.id::text                        =           (select q from args)
    )
),
stats as (
  select f.*,
    (select count(*) from public.practice_attempts a
       where a.user_id = f.user_id)                            as attempts,
    (select count(*) from public.practice_attempts a
       where a.user_id = f.user_id and a.is_correct)           as correct,
    (select count(*) from public.drona_sessions s
       where s.user_id = f.user_id)                            as sessions,
    (select count(*) from public.doubts d
       where d.user_id = f.user_id)                            as doubts,
    (select count(*) from public.notes n
       where n.user_id = f.user_id)                            as notes,
    (select round(coalesce(sum(l.cost_usd), 0)::numeric, 4)
       from public.llm_calls l where l.user_id = f.user_id)     as cost_usd,
    -- greatest() skips NULLs in Postgres, so a user who has only ever
    -- snapped a doubt still gets a last-seen.
    greatest(
      (select max(a.created_at)  from public.practice_attempts a where a.user_id = f.user_id),
      (select max(s.last_turn_at) from public.drona_sessions   s where s.user_id = f.user_id),
      (select max(d.created_at)  from public.doubts            d where d.user_id = f.user_id),
      (select max(n.created_at)  from public.notes             n where n.user_id = f.user_id)
    )                                                           as last_active_at
  from filtered f
),
ranked as (
  select s.*, row_number() over (
    order by
      case when (select sort from args) = 'attempts' then s.attempts       end desc nulls last,
      case when (select sort from args) = 'cost'     then s.cost_usd       end desc nulls last,
      case when (select sort from args) = 'active'   then s.last_active_at end desc nulls last,
      s.signed_up_at desc
  ) as rn
  from stats s
)
select jsonb_build_object(
  'total',  (select count(*) from filtered),
  'limit',  (select lim from args),
  'offset', (select off from args),
  'sort',   (select sort from args),
  'rows', (
    select coalesce(jsonb_agg(jsonb_build_object(
      'user_id',        user_id,
      'email',          email,
      'display_name',   display_name,
      'phone',          phone,
      'target_exam',    target_exam,
      'enrolled_class', enrolled_class,
      'onboarded',      display_name is not null,
      'signed_up_at',   signed_up_at,
      'last_sign_in_at', last_sign_in_at,
      'last_active_at', last_active_at,
      'attempts',       attempts,
      'accuracy',       round(100.0 * correct / nullif(attempts, 0), 1),
      'sessions',       sessions,
      'doubts',         doubts,
      'notes',          notes,
      'cost_usd',       cost_usd
    ) order by rn), '[]'::jsonb)
    from ranked
    where rn >  (select off from args)
      and rn <= (select off from args) + (select lim from args)
  )
)
$fn$;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_user — one student, in full.
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
    from (select id, mode, language, phase, subtopic_key, turn_count,
                 cost_usd, created_at, completed_at
          from public.drona_sessions where user_id = p_user_id
          order by created_at desc limit 15) x
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


-- ───────────────────────────────────────────────────────────────────────────
-- Lock every one of them to the service role.
--
-- `public` is revoked first because a freshly created function grants EXECUTE
-- to PUBLIC by default — which in Supabase means `anon` and `authenticated`
-- inherit it, i.e. the key sitting in every student's app bundle.
-- ───────────────────────────────────────────────────────────────────────────
do $grants$
declare
  fn text;
begin
  foreach fn in array array[
    'public.admin_activity(timestamptz)',
    'public.admin_overview(int)',
    'public.admin_retention(int)',
    'public.admin_features(int)',
    'public.admin_costs(int)',
    'public.admin_users(text,int,int,text)',
    'public.admin_user(uuid,int)'
  ] loop
    execute format('revoke all on function %s from public', fn);
    execute format('revoke all on function %s from anon', fn);
    execute format('revoke all on function %s from authenticated', fn);
    execute format('grant execute on function %s to service_role', fn);
  end loop;
end
$grants$;

commit;

-- ─── Verification (run after applying) ─────────────────────────────────────
--
--   select public.admin_overview(30);
--   select public.admin_features(30);
--   select public.admin_retention(8);
--   select public.admin_costs(30);
--   select public.admin_users(null, 10, 0, 'recent');
--
-- And confirm the lock actually took — this must return zero rows:
--
--   select p.proname, a.rolname
--   from pg_proc p
--   cross join lateral aclexplode(p.proacl) acl
--   join pg_roles a on a.oid = acl.grantee
--   where p.proname like 'admin\_%' and a.rolname in ('anon','authenticated');
