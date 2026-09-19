-- 0050_admin_exclude_internal.sql
--
-- Keep founder and test accounts out of the aggregate numbers.
--
-- Why this is not a nice-to-have. Measured the day it was written, over all
-- 29 accounts:
--
--   top 4 accounts    99% of classroom sessions, 100% of doubts
--   other 25 accounts  9 sessions and 1 doubt, between them
--
-- Every engagement figure on the dashboard was therefore a readout of the
-- founders using their own product. Not slightly skewed — almost entirely
-- composed of it. Retention especially: a cohort containing an account that
-- opens the app daily for testing reports retention that no real student
-- produced.
--
-- ─── Shape ─────────────────────────────────────────────────────────────────
--
-- A table, not an env var. Adding a teammate is then one INSERT in the SQL
-- editor rather than a Railway redeploy, the list is inspectable, and each row
-- carries the reason it exists — which is the part you want six months from
-- now when someone asks why the numbers moved.
--
-- Every aggregate function gains `p_include_internal boolean default false`.
-- The default is the honest view; the dashboard has a toggle for the other
-- one, because "did my own test session record properly?" is a real question
-- and a filter with no escape hatch just gets worked around.
--
-- `admin_user()` deliberately does NOT filter. Drilling into a specific
-- account should always show that account, excluded or not — otherwise your
-- own user page renders blank and looks broken.
--
-- ─── Why the drops ─────────────────────────────────────────────────────────
--
-- Adding a defaulted parameter creates an OVERLOAD, it does not replace: both
-- admin_overview(int) and admin_overview(int, boolean) would then exist, and
-- a one-argument call becomes ambiguous — "function is not unique" — which
-- would take the dashboard down rather than fail quietly. So the old
-- signatures are dropped and recreated in one transaction.
--
-- The consequence worth watching: a dropped-and-recreated function is NEW, and
-- a new function grants EXECUTE to PUBLIC by default — in Supabase that means
-- `anon` and `authenticated`, i.e. the key in every student's app bundle. The
-- grant block at the foot is therefore not a formality here the way it was in
-- 0048; without it this migration would silently open all of it up. Run the
-- verification query.

begin;

-- ───────────────────────────────────────────────────────────────────────────
-- The list.
-- ───────────────────────────────────────────────────────────────────────────
create table if not exists public.admin_excluded_users (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  email      text,                     -- denormalised so the list reads without a join
  reason     text not null default '',
  created_at timestamptz not null default now()
);

comment on table public.admin_excluded_users is
  'Accounts kept out of /admin aggregate numbers (founders, test rigs, demo '
  'accounts). Per-user drilldown still shows them. Pass p_include_internal '
  '=> true to any admin_* function to see the unfiltered view.';

-- Content-table posture, per AGENTS.md rule 9: RLS on, zero policies, and
-- reachable only by the service role.
alter table public.admin_excluded_users enable row level security;
revoke all on table public.admin_excluded_users from public;
revoke all on table public.admin_excluded_users from anon;
revoke all on table public.admin_excluded_users from authenticated;
grant all on table public.admin_excluded_users to service_role;


-- ───────────────────────────────────────────────────────────────────────────
-- Old signatures out, so the defaulted parameter can't create an ambiguity.
-- ───────────────────────────────────────────────────────────────────────────
drop function if exists public.admin_activity(timestamptz);
drop function if exists public.admin_overview(int);
drop function if exists public.admin_retention(int);
drop function if exists public.admin_features(int);
drop function if exists public.admin_costs(int);
drop function if exists public.admin_users(text, int, int, text);
drop function if exists public.admin_user(uuid, int);


-- ───────────────────────────────────────────────────────────────────────────
-- admin_activity — still the single definition of "did something".
-- ───────────────────────────────────────────────────────────────────────────
create function public.admin_activity(
  p_from timestamptz,
  p_include_internal boolean default false
)
returns table (user_id uuid, at timestamptz)
language sql
stable
security definer
set search_path = public
as $fn$
  with ex as (
    select x.user_id from public.admin_excluded_users x
    where not coalesce(p_include_internal, false)
  ),
  all_activity as (
    select a.user_id, a.created_at from public.practice_attempts a
      where a.created_at >= p_from and a.user_id is not null
    union all
    select s.user_id, s.created_at from public.drona_sessions s
      where s.created_at >= p_from and s.user_id is not null
    union all
    select d.user_id, d.created_at from public.doubts d
      where d.created_at >= p_from and d.user_id is not null
    union all
    select n.user_id, n.created_at from public.notes n
      where n.created_at >= p_from and n.user_id is not null
  )
  select t.user_id, t.created_at
  from all_activity t
  where not exists (select 1 from ex where ex.user_id = t.user_id)
$fn$;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_overview
-- ───────────────────────────────────────────────────────────────────────────
create function public.admin_overview(
  p_days int default 30,
  p_include_internal boolean default false
)
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
         (((today - (greatest(days, 30) - 1))::timestamp) at time zone 'Asia/Kolkata') as act_from
  from p
),
ex as (
  select x.user_id from public.admin_excluded_users x
  where not coalesce(p_include_internal, false)
),
act as (
  select a.user_id, (a.at at time zone 'Asia/Kolkata')::date as day
  from b, public.admin_activity(b.act_from, p_include_internal) a
),
u as (
  select id, (created_at at time zone 'Asia/Kolkata')::date as day
  from auth.users
  where email is not null
    and not exists (select 1 from ex where ex.user_id = auth.users.id)
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
  'includes_internal', coalesce(p_include_internal, false),
  'excluded_count', (select count(*) from public.admin_excluded_users),
  'totals', jsonb_build_object(
    'users_total',     (select count(*) from u),
    'users_onboarded', (select count(*) from public.profiles pr
                        where not exists (select 1 from ex where ex.user_id = pr.id)),
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
-- admin_retention
-- ───────────────────────────────────────────────────────────────────────────
create function public.admin_retention(
  p_weeks int default 8,
  p_include_internal boolean default false
)
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
ex as (
  select x.user_id from public.admin_excluded_users x
  where not coalesce(p_include_internal, false)
),
cohort as (
  select u.id as user_id,
         u.created_at as signed_up_at,
         date_trunc('week', (u.created_at at time zone 'Asia/Kolkata'))::date as cohort_week
  from auth.users u
  where u.email is not null
    and not exists (select 1 from ex where ex.user_id = u.id)
    and (u.created_at at time zone 'Asia/Kolkata')::date
        >= (select today - (weeks * 7 - 1) from p)
),
act as (
  select a.user_id, a.at
  from (select min(signed_up_at) as m from cohort) s,
       public.admin_activity(s.m, p_include_internal) a
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
-- admin_features  (turns from drona_turns, per 0049)
-- ───────────────────────────────────────────────────────────────────────────
create function public.admin_features(
  p_days int default 30,
  p_include_internal boolean default false
)
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
ex as (
  select x.user_id from public.admin_excluded_users x
  where not coalesce(p_include_internal, false)
),
pa as (
  select (t.created_at at time zone 'Asia/Kolkata')::date as day,
         t.user_id, t.is_correct, t.gave_up
  from public.practice_attempts t
  where t.created_at >= (select from_ts from b)
    and not exists (select 1 from ex where ex.user_id = t.user_id)
),
ds as (
  select t.id, (t.created_at at time zone 'Asia/Kolkata')::date as day,
         t.user_id, t.mode, t.language, t.phase, t.cost_usd
  from public.drona_sessions t
  where t.created_at >= (select from_ts from b)
    and not exists (select 1 from ex where ex.user_id = t.user_id)
),
turns_per_session as (
  select ds.id, (select count(*) from public.drona_turns t where t.session_id = ds.id) as n
  from ds
),
dbt as (
  select (t.created_at at time zone 'Asia/Kolkata')::date as day,
         t.user_id, t.solved
  from public.doubts t
  where t.created_at >= (select from_ts from b)
    and not exists (select 1 from ex where ex.user_id = t.user_id)
),
nt as (
  select (t.created_at at time zone 'Asia/Kolkata')::date as day, t.user_id
  from public.notes t
  where t.created_at >= (select from_ts from b)
    and not exists (select 1 from ex where ex.user_id = t.user_id)
),
days as (
  select d::date as day
  from generate_series((select from_day from b), (select today from b), interval '1 day') d
)
select jsonb_build_object(
  'window_days', (select days from b),
  'includes_internal', coalesce(p_include_internal, false),
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
-- admin_costs
--
-- An excluded account's model calls leave the spend total too. Founder testing
-- is a real bill, but it is not what serving a student costs, and
-- cost_per_active_user is meaningless if the numerator counts one and the
-- denominator the other. Flip the toggle to see the full invoice.
-- ───────────────────────────────────────────────────────────────────────────
create function public.admin_costs(
  p_days int default 30,
  p_include_internal boolean default false
)
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
ex as (
  select x.user_id from public.admin_excluded_users x
  where not coalesce(p_include_internal, false)
),
c as (
  select (t.created_at at time zone 'Asia/Kolkata')::date as day,
         t.model, t.service, t.ok, t.cost_usd, t.latency_ms, t.user_id
  from public.llm_calls t
  where t.created_at >= (select from_ts from b)
    -- A call with no user_id is platform work (ingest, warmers) and stays in
    -- the total: `not exists` over a NULL keeps the row, which is what we want.
    and not exists (select 1 from ex where ex.user_id = t.user_id)
),
days as (
  select d::date as day
  from generate_series((select from_day from b), (select today from b), interval '1 day') d
)
select jsonb_build_object(
  'window_days', (select days from b),
  'includes_internal', coalesce(p_include_internal, false),
  'totals', jsonb_build_object(
    'calls',       (select count(*) from c),
    'failed',      (select count(*) from c where not ok),
    'cost_usd',    (select round(coalesce(sum(cost_usd), 0)::numeric, 4) from c),
    'wasted_usd',  (select round(coalesce(sum(cost_usd) filter (where not ok), 0)::numeric, 4) from c),
    'p95_latency_ms', (select round(percentile_cont(0.95)
                               within group (order by latency_ms))::int
                       from c where latency_ms is not null),
    'cost_per_active_user_usd', (
      select round(
        coalesce((select sum(cost_usd) from c), 0)
        / nullif((select count(distinct a.user_id)
                  from public.admin_activity((select from_ts from b), p_include_internal) a), 0)
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
-- admin_users
--
-- Excluded accounts are HIDDEN from the list by default rather than merely
-- unmarked, so the list agrees with the counters above it. Turn the toggle on
-- and they reappear, flagged — you still need to find your own account to
-- check something, and hunting for it is not a filter, it is an annoyance.
-- ───────────────────────────────────────────────────────────────────────────
create function public.admin_users(
  p_q      text default null,
  p_limit  int  default 50,
  p_offset int  default 0,
  p_sort   text default 'recent',
  p_include_internal boolean default false
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
ex as (
  select x.user_id from public.admin_excluded_users x
  where not coalesce(p_include_internal, false)
),
filtered as (
  select u.id as user_id, u.email, u.created_at as signed_up_at,
         u.last_sign_in_at,
         pr.display_name, pr.target_exam, pr.enrolled_class, pr.phone,
         exists (select 1 from public.admin_excluded_users z where z.user_id = u.id) as internal
  from auth.users u
  left join public.profiles pr on pr.id = u.id
  where u.email is not null
    and not exists (select 1 from ex where ex.user_id = u.id)
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
  'includes_internal', coalesce(p_include_internal, false),
  'rows', (
    select coalesce(jsonb_agg(jsonb_build_object(
      'user_id',        user_id,
      'email',          email,
      'display_name',   display_name,
      'phone',          phone,
      'target_exam',    target_exam,
      'enrolled_class', enrolled_class,
      'onboarded',      display_name is not null,
      'internal',       internal,
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
-- admin_user — NO exclusion. Asking for one account always returns it.
-- ───────────────────────────────────────────────────────────────────────────
create function public.admin_user(p_user_id uuid, p_days int default 30)
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
  -- `true` on purpose: this user's own activity, whether or not they are on
  -- the exclusion list. Filtering here would blank out your own page.
  select (a.at at time zone 'Asia/Kolkata')::date as day
  from public.admin_activity((select from_ts from b), true) a
  where a.user_id = p_user_id
)
select case when not exists (select 1 from u) then null else jsonb_build_object(
  'user_id',         p_user_id,
  'email',           (select email from u),
  'signed_up_at',    (select created_at from u),
  'last_sign_in_at', (select last_sign_in_at from u),
  'internal',        exists (select 1 from public.admin_excluded_users z where z.user_id = p_user_id),
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


-- ───────────────────────────────────────────────────────────────────────────
-- Re-lock. MANDATORY here: these are brand-new functions after the drops, and
-- a new function grants EXECUTE to PUBLIC — which in Supabase hands it to
-- `anon` and `authenticated`, i.e. the key in every student's app bundle.
-- ───────────────────────────────────────────────────────────────────────────
do $grants$
declare
  fn text;
begin
  foreach fn in array array[
    'public.admin_activity(timestamptz,boolean)',
    'public.admin_overview(int,boolean)',
    'public.admin_retention(int,boolean)',
    'public.admin_features(int,boolean)',
    'public.admin_costs(int,boolean)',
    'public.admin_users(text,int,int,text,boolean)',
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

-- PostgREST caches the schema; the drop/create cycle needs it told.
notify pgrst, 'reload schema';

-- ─── Seed the list ─────────────────────────────────────────────────────────
--
-- Run this separately, once per account, with the address filled in. Matching
-- on email rather than a pasted UUID so there is nothing to copy wrong, and
-- `on conflict do nothing` makes it safe to re-run.
--
--   insert into public.admin_excluded_users (user_id, email, reason)
--   select id, email, 'founder'
--   from auth.users where lower(email) = lower('you@example.com')
--   on conflict (user_id) do nothing;
--
-- To see the list:      select email, reason, created_at from public.admin_excluded_users;
-- To put one back:      delete from public.admin_excluded_users where lower(email) = lower('...');
--
-- ─── Verification ──────────────────────────────────────────────────────────
--
--   select public.admin_overview(30)->'totals';              -- students only
--   select public.admin_overview(30, true)->'totals';        -- everyone
--
-- And the one that matters — MUST return zero rows:
--
--   select p.proname, a.rolname
--   from pg_proc p cross join lateral aclexplode(p.proacl) acl
--   join pg_roles a on a.oid = acl.grantee
--   where p.proname like 'admin\_%' and a.rolname in ('anon','authenticated');
