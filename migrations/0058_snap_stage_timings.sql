-- 0058_snap_stage_timings.sql
--
-- Where the snap wait actually goes.
--
-- `doubts.latency_ms` has been recording photo-to-answer all along, and it says
-- p95 is 60-110 seconds with a worst case of 272. What it cannot say is WHY.
-- Model calls account for only 28-36s of that, so 30-70 seconds sit somewhere
-- between the model returning and the answer reaching the student, and one
-- total cannot tell you where.
--
-- The stages were never unmeasured. app/snap.py has computed ocr_ms,
-- structure_ms, diagram_ms, options_ms and the solve span since the
-- [SNAP BREAKDOWN] log line was written — it prints them on one line per
-- submission and then throws them away. This stores them.
--
-- ─── One jsonb column, not six ─────────────────────────────────────────────
--
-- Stages come and go as the pipeline changes, and a schema migration per stage
-- is how a breakdown quietly stops being maintained. `timings` holds whatever
-- the pipeline measured; a stage that was not measured is ABSENT rather than
-- zero, because an unmeasured stage must never read as an instant one. That
-- distinction is the whole reason this dashboard says "not recorded" in half a
-- dozen places.
--
-- ─── The streamed path settles up ──────────────────────────────────────────
--
-- Rows are written as each answer lands, which is before the summary carrying
-- diagram/options/solve exists. The insert stores what is known, and one
-- UPDATE after the last answer fills the rest — off the student's path, and
-- wrapped so telemetry can never fail a solved submission.

begin;

alter table public.doubts add column if not exists timings jsonb;

comment on column public.doubts.timings is
  'Stage breakdown in ms: ocr_ms, structure_ms, transcribe_ms, diagram_ms, '
  'options_ms, solve_ms, latency_ms, db_insert_ms. A key is absent when that '
  'stage was not measured — never zero. Written from 2026-09-19; doubts '
  'before then have none.';

-- The reporting below filters on it; without this every percentile is a scan.
create index if not exists doubts_timings_idx
  on public.doubts ((timings is not null), created_at desc)
  where timings is not null;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_snap_latency — where the wait goes, across a window.
--
-- Percentiles per stage, plus the share of the median total each one takes.
-- The shares will not sum to exactly 100%: a median is not additive, and the
-- solve stages run concurrently across questions. They are a guide to where to
-- look, not an accounting identity, and the function says so in its output
-- rather than leaving someone to discover it by adding them up.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_snap_latency(
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
         (((today - (days - 1))::timestamp) at time zone 'Asia/Kolkata') as from_ts
  from p
),
ex as (select h.user_id from public.admin_hidden_users(p_include_internal) h),
d as (
  select t.timings, t.latency_ms, t.solved, t.created_at
  from public.doubts t
  where t.created_at >= (select from_ts from b)
    and not exists (select 1 from ex where ex.user_id = t.user_id)
),
timed as (select * from d where timings is not null),
stage_rows as (
  select s.stage, (timed.timings ->> s.stage)::numeric as ms
  from timed
  cross join lateral (values ('ocr_ms'), ('structure_ms'), ('transcribe_ms'),
                             ('diagram_ms'), ('options_ms'), ('solve_ms'),
                             ('db_insert_ms'), ('latency_ms')) as s(stage)
  where timed.timings ? s.stage
),
by_stage as (
  select stage,
         count(*) as n,
         round(percentile_cont(0.50) within group (order by ms))::int as p50,
         round(percentile_cont(0.95) within group (order by ms))::int as p95,
         max(ms)::int as worst
  from stage_rows group by stage
),
total_p50 as (select p50 from by_stage where stage = 'latency_ms')
select jsonb_build_object(
  'window_days', (select days from b),
  'includes_internal', coalesce(p_include_internal, false),
  'doubts',        (select count(*) from d),
  -- The gap between these two is how much of the window predates the
  -- instrumentation. Without it, "p95 of 40 doubts" looks like the whole story.
  'doubts_timed',  (select count(*) from timed),
  'overall', (
    select jsonb_build_object(
      'n',     count(*),
      'p50',   round(percentile_cont(0.50) within group (order by latency_ms))::int,
      'p95',   round(percentile_cont(0.95) within group (order by latency_ms))::int,
      'worst', max(latency_ms))
    from d where latency_ms is not null
  ),
  'by_stage', (
    select coalesce(jsonb_agg(jsonb_build_object(
             'stage', stage, 'n', n, 'p50', p50, 'p95', p95, 'worst', worst,
             'share_of_median_pct',
               case when (select p50 from total_p50) in (null, 0) then null
                    when stage = 'latency_ms' then null
                    else round(100.0 * p50 / (select p50 from total_p50)) end
           ) order by p50 desc), '[]'::jsonb)
    from by_stage
  ),
  'note', 'shares are of the median total and will not sum to 100 — a median '
          'is not additive and solves run concurrently across questions'
)
$fn$;

revoke all on function public.admin_snap_latency(int, boolean) from public;
revoke all on function public.admin_snap_latency(int, boolean) from anon;
revoke all on function public.admin_snap_latency(int, boolean) from authenticated;
grant execute on function public.admin_snap_latency(int, boolean) to service_role;

commit;

notify pgrst, 'reload schema';

-- ─── Verification, once a doubt has been snapped after this deploys ────────
--
--   select id, timings from public.doubts
--    where timings is not null order by created_at desc limit 3;
--
--   select public.admin_snap_latency(30, true);
--
-- `doubts_timed` will be 0 until then, and the dashboard says so rather than
-- reporting an empty breakdown as a fast one.
