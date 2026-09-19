-- 0055_admin_costs_daily_one_pass.sql
--
-- Two things: a timeout fix, and one exchange rate so everything reads in USD.
--
-- admin_costs() timed out on any range past 30 days. Measured against
-- production the day this was written:
--
--     7d   200  0.4s
--    30d   200  1.4s
--    90d   TIMEOUT (57014, statement timeout)
--   365d   TIMEOUT
--
-- The dashboard's range selector offers 90 days and a year, so two of its four
-- options returned a 500. admin_overview() and admin_features() answered in
-- under half a second across every range, which is what made the cause
-- findable: it is not "the database is slow", it is one query shape meeting
-- one big table.
--
-- ─── The shape ─────────────────────────────────────────────────────────────
--
-- The daily series, written in 0048 and copied forward through 0051 and 0054,
-- asked a correlated subquery PER DAY PER MEASURE:
--
--     'daily', (select jsonb_agg(jsonb_build_object(
--        'calls',    (select count(*) from c where c.day = d.day),
--        'cost_usd', (select sum(...) from c where c.day = d.day),
--        'student',  (select sum(...) from c where c.day = d.day and kind = ...),
--        ... four more
--      )) from days d)
--
-- That is O(days x rows). Over 90 days and six measures it re-scans the CTE
-- ~540 times. `c` holds llm_calls for the window — 82,881 rows all-time,
-- ~25,000 in a month — so the work grows as the product does.
--
-- The same shape is in admin_features(), where it has never been slow because
-- practice_attempts, drona_sessions, doubts and notes are small. It is a
-- latent copy of the same bug: fast today, timing out at whatever row count
-- arrives first. Both are rewritten here.
--
-- ─── The fix ───────────────────────────────────────────────────────────────
--
-- Aggregate once, grouped by day, then LEFT JOIN the calendar. One pass over
-- the rows instead of one per cell. Nothing about the output changes — same
-- keys, same values, same zeroes on days with no activity, which is what the
-- left join and the coalesces preserve.
--
-- Signatures are unchanged, so 0050/0051's grants carry through the replace.

begin;

-- ───────────────────────────────────────────────────────────────────────────
-- One exchange rate, in one place.
--
-- 0054 refused to combine rupees and dollars because a rate hardcoded in a
-- migration goes quietly wrong. That reasoning holds; the answer is not to
-- avoid the conversion but to put the rate somewhere visible and editable, so
-- it is a number someone owns rather than one buried in a function body.
--
-- Set to 95 by decision, not by lookup — it is a planning rate, and when the
-- real one drifts this is a one-line UPDATE with no redeploy:
--
--   update public.admin_settings set value = 88 where key = 'inr_per_usd';
--
-- Every figure the dashboard reports as money is USD at this rate. The rate
-- itself is returned alongside, so a number can always be traced back to the
-- assumption that produced it.
-- ───────────────────────────────────────────────────────────────────────────
create table if not exists public.admin_settings (
  key   text primary key,
  value numeric(14, 4) not null,
  note  text not null default ''
);

alter table public.admin_settings enable row level security;
revoke all on table public.admin_settings from public;
revoke all on table public.admin_settings from anon;
revoke all on table public.admin_settings from authenticated;
grant all on table public.admin_settings to service_role;

insert into public.admin_settings (key, value, note) values
  ('inr_per_usd', 95.0000,
   'Planning rate for converting INR-billed vendors (Rumik) into the USD totals.')
on conflict (key) do nothing;

-- ───────────────────────────────────────────────────────────────────────────
-- admin_costs
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_costs(
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
ex as (select h.user_id from public.admin_hidden_users(p_include_internal) h),
c as (
  select (t.created_at at time zone 'Asia/Kolkata')::date as day,
         t.model, t.service, t.ok, t.cost_usd, t.latency_ms, t.user_id,
         coalesce(k.kind, 'unclassified') as kind
  from public.llm_calls t
  left join public.llm_service_kinds k on k.service = t.service
  where t.created_at >= (select from_ts from b)
    and not exists (select 1 from ex where ex.user_id = t.user_id)
),
v as (
  select (t.created_at at time zone 'Asia/Kolkata')::date as day,
         coalesce(t.rumik_requests, 0) as reqs,
         coalesce(t.rumik_chars, 0)    as chars,
         coalesce(t.tts_failure_count, 0) as fails
  from public.drona_turns t
  join public.drona_sessions s on s.id = t.session_id
  where t.created_at >= (select from_ts from b)
    and not exists (select 1 from ex where ex.user_id = s.user_id)
),
fx as (
  select coalesce((select value from public.admin_settings where key = 'inr_per_usd'), 95)
         as inr_per_usd
),
rumik_price as (
  select vp.price_per_1m_units as rate,
         vp.currency,
         -- Everything downstream is USD. An INR rate is divided by the one
         -- configured FX rate; a USD rate passes through untouched.
         case when vp.price_per_1m_units is null then null
              when vp.currency = 'INR'
                then round(vp.price_per_1m_units / (select inr_per_usd from fx), 6)
              else vp.price_per_1m_units end as rate_usd
  from public.vendor_prices vp where vp.vendor = 'rumik'
),
days as (
  select d::date as day
  from generate_series((select from_day from b), (select today from b), interval '1 day') d
),
-- One pass. This is the whole fix.
daily_llm as (
  select day,
         count(*) as calls,
         round(coalesce(sum(cost_usd), 0)::numeric, 4) as cost,
         round(coalesce(sum(cost_usd) filter (where kind = 'student'), 0)::numeric, 4)      as student,
         round(coalesce(sum(cost_usd) filter (where kind = 'content'), 0)::numeric, 4)      as content,
         round(coalesce(sum(cost_usd) filter (where kind = 'pipeline'), 0)::numeric, 4)     as pipeline,
         round(coalesce(sum(cost_usd) filter (where kind = 'unclassified'), 0)::numeric, 4) as unclassified
  from c group by day
),
daily_voice as (
  select day, coalesce(sum(chars), 0) as chars, coalesce(sum(reqs), 0) as reqs
  from v group by day
),
kind_totals as (
  select kind, count(*) as calls, round(coalesce(sum(cost_usd), 0)::numeric, 4) as cost
  from c group by kind
),
actives as (
  select count(distinct a.user_id) as n
  from public.admin_activity((select from_ts from b), p_include_internal) a
),
student_cost as (select coalesce(sum(cost_usd), 0) as v from c where kind = 'student'),
voice_total as (
  select coalesce(sum(chars), 0)::bigint as chars,
         coalesce(sum(reqs), 0)::bigint  as reqs,
         coalesce(sum(fails), 0)::bigint as fails,
         case when (select rate_usd from rumik_price) is null then null
              else round((coalesce(sum(chars), 0)::numeric / 1000000)
                         * (select rate_usd from rumik_price), 4) end as cost_usd,
         case when (select rate from rumik_price) is null then null
              else round((coalesce(sum(chars), 0)::numeric / 1000000)
                         * (select rate from rumik_price), 4) end as cost_native
  from v
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
    'student_cost_usd',      coalesce((select cost from kind_totals where kind = 'student'), 0),
    'content_cost_usd',      coalesce((select cost from kind_totals where kind = 'content'), 0),
    'pipeline_cost_usd',     coalesce((select cost from kind_totals where kind = 'pipeline'), 0),
    'unclassified_cost_usd', coalesce((select cost from kind_totals where kind = 'unclassified'), 0),
    'active_users', (select n from actives),
    'cost_per_active_user_usd', (
      select round(coalesce(
        (select v from student_cost) / nullif((select n from actives), 0), 0)::numeric, 4)
    ),
    -- Models + voice, both in USD. Null only while voice is unpriced —
    -- treating an unpriced vendor as free is still the one thing this must
    -- never do.
    'grand_total_usd', (
      select case when (select cost_usd from voice_total) is null then null
             else round((select coalesce(sum(cost_usd), 0) from c)
                        + (select cost_usd from voice_total), 4) end
    ),
    'inr_per_usd', (select inr_per_usd from fx)
  ),
  'voice', jsonb_build_object(
    'vendor',        'rumik',
    'unit',          'characters',
    'requests',      (select reqs  from voice_total),
    'characters',    (select chars from voice_total),
    'failures',      (select fails from voice_total),
    'price_per_1m',       (select rate from rumik_price),
    'currency',           (select currency from rumik_price),
    'price_per_1m_usd',   (select rate_usd from rumik_price),
    'cost_native',        (select cost_native from voice_total),
    'cost_usd',           (select cost_usd from voice_total),
    'inr_per_usd',        (select inr_per_usd from fx),
    'priced',             (select rate from rumik_price) is not null,
    'covers',        'classroom turns only — ask-a-follow-up also uses Rumik and is not counted',
    'daily', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'day',        d.day,
               'characters', coalesce(dv.chars, 0),
               'requests',   coalesce(dv.reqs, 0)
             ) order by d.day), '[]'::jsonb)
      from days d left join daily_voice dv on dv.day = d.day
    )
  ),
  'by_kind', (
    select coalesce(jsonb_agg(jsonb_build_object(
             'kind', kind, 'calls', calls, 'cost_usd', cost) order by cost desc), '[]'::jsonb)
    from kind_totals
  ),
  'unclassified_services', (
    select coalesce(jsonb_agg(distinct service), '[]'::jsonb) from c where kind = 'unclassified'
  ),
  'by_service', (select coalesce(jsonb_agg(jsonb_build_object(
                    'service', service, 'kind', kind, 'calls', n, 'cost_usd', cost)
                    order by cost desc), '[]'::jsonb)
                 from (select service, min(kind) as kind, count(*) n,
                              round(coalesce(sum(cost_usd), 0)::numeric, 4) cost
                       from c group by service) x),
  'by_model',   (select coalesce(jsonb_agg(jsonb_build_object(
                    'model', model, 'calls', n, 'cost_usd', cost) order by cost desc), '[]'::jsonb)
                 from (select model, count(*) n,
                              round(coalesce(sum(cost_usd), 0)::numeric, 4) cost
                       from c group by model) x),
  'daily', (
    select coalesce(jsonb_agg(jsonb_build_object(
             'day',          d.day,
             'calls',        coalesce(dl.calls, 0),
             'cost_usd',     coalesce(dl.cost, 0),
             'student',      coalesce(dl.student, 0),
             'content',      coalesce(dl.content, 0),
             'pipeline',     coalesce(dl.pipeline, 0),
             'unclassified', coalesce(dl.unclassified, 0)
           ) order by d.day), '[]'::jsonb)
    from days d left join daily_llm dl on dl.day = d.day
  )
)
$fn$;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_features — same shape, not yet slow. Fixed before it is.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_features(
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
ex as (select h.user_id from public.admin_hidden_users(p_include_internal) h),
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
  select (t.created_at at time zone 'Asia/Kolkata')::date as day, t.user_id, t.solved
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
),
d_pa  as (select day, count(*) n from pa  group by day),
d_ds  as (select day, count(*) n from ds  group by day),
d_dbt as (select day, count(*) n from dbt group by day),
d_nt  as (select day, count(*) n from nt  group by day)
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
             'practice', coalesce(a.n, 0),
             'drona',    coalesce(s.n, 0),
             'doubts',   coalesce(o.n, 0),
             'notes',    coalesce(t.n, 0)
           ) order by d.day), '[]'::jsonb)
    from days d
    left join d_pa  a on a.day = d.day
    left join d_ds  s on s.day = d.day
    left join d_dbt o on o.day = d.day
    left join d_nt  t on t.day = d.day
  )
)
$fn$;

-- Signatures unchanged, so the ACLs survived. Re-asserted because the one time
-- it matters is the time someone assumed it.
do $grants$
declare fn text;
begin
  foreach fn in array array['public.admin_costs(int,boolean)',
                            'public.admin_features(int,boolean)'] loop
    execute format('revoke all on function %s from public', fn);
    execute format('revoke all on function %s from anon', fn);
    execute format('revoke all on function %s from authenticated', fn);
    execute format('grant execute on function %s to service_role', fn);
  end loop;
end
$grants$;

commit;

notify pgrst, 'reload schema';

-- ─── Verification ──────────────────────────────────────────────────────────
--
-- Both of these must now return in well under the statement timeout, and the
-- 90-day one is the case that used to fail:
--
--   \timing on
--   select jsonb_array_length(public.admin_costs(90, true)->'daily');    -- 90
--   select jsonb_array_length(public.admin_costs(365, true)->'daily');   -- 365
--   select jsonb_array_length(public.admin_features(365, true)->'daily');
--
-- And the values must be unchanged at a range that always worked:
--
--   select public.admin_costs(30, true)->'totals';
