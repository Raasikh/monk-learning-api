-- 0051_admin_cost_kinds.sql
--
-- Split LLM spend by what the money was FOR, and stop dividing all of it by
-- the number of active students.
--
-- The number this fixes: `cost_per_active_user_usd` read $1.38. It was total
-- spend over active users, and total spend is mostly not spent on students.
-- Measured over the 30 days this was written, of $30.40:
--
--   $21.14  lesson authoring + an offline QA script
--   $ 9.26  actually serving students
--
-- $11.51 of that authoring is `segment` — and there are 290 rows in
-- `lesson_plans`, each authored ONCE and then replayed to every student who
-- ever takes that lesson. It is a library being built, not a cost of service.
-- $10.24 more is `gate_*`, which `scripts/quality_gate.py` emits when a human
-- runs it from a terminal; there is no user anywhere near it.
--
-- Dividing either by "active users this month" produces a unit economic that
-- gets WORSE the more lessons you author and BETTER the fewer students you
-- have. It is not a slightly-off number, it is a number pointing the wrong way.
--
-- ─── Three kinds ───────────────────────────────────────────────────────────
--
--   student   scales with usage. The real marginal cost of one more student.
--   content   authored once, amortised across everyone. Capital, not COGS.
--   pipeline  offline scripts a human runs. Neither of the above.
--
-- A table rather than a CASE expression, because service names are added by
-- whoever adds a feature and a hardcoded list rots silently.
--
-- ─── The default for an unknown service ────────────────────────────────────
--
-- `unclassified` — never `student`. A new service quietly defaulting into the
-- student bucket would inflate the one figure this migration exists to make
-- honest, and would do it invisibly. Unclassified spend is reported as its own
-- bucket and the dashboard names the offending services in a banner, so the
-- failure mode is a visible nag rather than a wrong headline.

begin;

create table if not exists public.llm_service_kinds (
  service text primary key,
  kind    text not null check (kind in ('student', 'content', 'pipeline')),
  note    text not null default ''
);

comment on table public.llm_service_kinds is
  'What each llm_calls.service spends money ON. student = scales per user; '
  'content = authored once and reused; pipeline = offline scripts. Anything '
  'missing here shows on /admin as "unclassified" until it is added.';

alter table public.llm_service_kinds enable row level security;
revoke all on table public.llm_service_kinds from public;
revoke all on table public.llm_service_kinds from anon;
revoke all on table public.llm_service_kinds from authenticated;
grant all on table public.llm_service_kinds to service_role;

-- Every service name `llm_calls` has ever recorded (16, verified against
-- 82,881 rows), plus the ones app/drona/usage.py and 0018 document but that
-- have not fired yet.
insert into public.llm_service_kinds (service, kind, note) values
  ('tutor',                  'student',  'live classroom turn'),
  ('scoped_turn',            'student',  'live classroom turn, scoped'),
  ('scoping',                'student',  'deciding what a student asked for'),
  ('practice_explain',       'student',  'explaining a practice answer'),
  ('doubt_practice_explain', 'student',  'explaining a snapped doubt'),
  ('snap_solve',             'student',  'solving a snapped doubt'),
  ('snap_transcribe',        'student',  'reading the photo'),
  ('snap_diagram',           'student',  'describing a figure in the photo'),
  ('snap_options',           'student',  'describing option figures'),
  ('snap_match',             'student',  'matching an answer to options'),
  ('snap_stepcheck',         'student',  'checking solution steps'),
  ('segment',                'content',  'authoring one lesson segment; cached in lesson_plans'),
  ('outline',                'content',  'authoring a lesson outline; cached in lesson_plans'),
  ('widget_payload',         'content',  'authoring a board widget for a segment'),
  ('planner',                'content',  'lesson planning'),
  ('gate',                   'pipeline', 'scripts/quality_gate.py'),
  ('gate_write_sol',         'pipeline', 'scripts/quality_gate.py'),
  ('gate_check_sol',         'pipeline', 'scripts/quality_gate.py'),
  ('gate_blind',             'pipeline', 'scripts/quality_gate.py'),
  ('gate_blind_dispute',     'pipeline', 'scripts/quality_gate.py'),
  ('gate_defend',            'pipeline', 'scripts/quality_gate.py')
on conflict (service) do nothing;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_costs — same signature, so 0050's grants survive the replace.
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
ex as (
  select x.user_id from public.admin_excluded_users x
  where not coalesce(p_include_internal, false)
),
c as (
  select (t.created_at at time zone 'Asia/Kolkata')::date as day,
         t.model, t.service, t.ok, t.cost_usd, t.latency_ms, t.user_id,
         -- Unknown services land here, never in 'student'.
         coalesce(k.kind, 'unclassified') as kind
  from public.llm_calls t
  left join public.llm_service_kinds k on k.service = t.service
  where t.created_at >= (select from_ts from b)
    and not exists (select 1 from ex where ex.user_id = t.user_id)
),
days as (
  select d::date as day
  from generate_series((select from_day from b), (select today from b), interval '1 day') d
),
kind_totals as (
  select kind, count(*) as calls, round(coalesce(sum(cost_usd), 0)::numeric, 4) as cost
  from c group by kind
),
actives as (
  select count(distinct a.user_id) as n
  from public.admin_activity((select from_ts from b), p_include_internal) a
),
student_cost as (
  select coalesce(sum(cost_usd), 0) as v from c where kind = 'student'
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
    -- coalesce OUTSIDE the subquery. Inside, it never fires: a bucket with no
    -- rows yields no row at all, so the scalar subquery is NULL and the tile
    -- renders "—" rather than "$0.00" — and any sum touching it goes NULL too.
    'student_cost_usd',      coalesce((select cost from kind_totals where kind = 'student'), 0),
    'content_cost_usd',      coalesce((select cost from kind_totals where kind = 'content'), 0),
    'pipeline_cost_usd',     coalesce((select cost from kind_totals where kind = 'pipeline'), 0),
    'unclassified_cost_usd', coalesce((select cost from kind_totals where kind = 'unclassified'), 0),
    'active_users', (select n from actives),
    -- STUDENT SPEND ONLY. This is the marginal cost of one more student, and
    -- it is the only division here that means anything. Content authoring and
    -- the offline pipeline do not belong in a per-user figure: they would make
    -- it rise as the lesson library grows and fall as students leave.
    'cost_per_active_user_usd', (
      select round(coalesce(
        (select v from student_cost) / nullif((select n from actives), 0), 0)::numeric, 4)
    )
  ),
  'by_kind', (
    select coalesce(jsonb_agg(jsonb_build_object(
             'kind', kind, 'calls', calls, 'cost_usd', cost
           ) order by cost desc), '[]'::jsonb)
    from kind_totals
  ),
  -- Named, so an unclassified service is something you FIX rather than
  -- something you stop noticing.
  'unclassified_services', (
    select coalesce(jsonb_agg(distinct service), '[]'::jsonb)
    from c where kind = 'unclassified'
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
             'day', d.day,
             'calls',        (select count(*) from c where c.day = d.day),
             'cost_usd',     (select round(coalesce(sum(cost_usd), 0)::numeric, 4)
                              from c where c.day = d.day),
             'student',      (select round(coalesce(sum(cost_usd), 0)::numeric, 4)
                              from c where c.day = d.day and kind = 'student'),
             'content',      (select round(coalesce(sum(cost_usd), 0)::numeric, 4)
                              from c where c.day = d.day and kind = 'content'),
             'pipeline',     (select round(coalesce(sum(cost_usd), 0)::numeric, 4)
                              from c where c.day = d.day and kind = 'pipeline'),
             'unclassified', (select round(coalesce(sum(cost_usd), 0)::numeric, 4)
                              from c where c.day = d.day and kind = 'unclassified')
           ) order by d.day), '[]'::jsonb)
    from days d
  )
)
$fn$;

-- Same signature as 0050, so the existing ACL carries over. Re-asserted anyway
-- — it costs nothing and the one time it matters is the time someone changed
-- the signature without noticing.
revoke all on function public.admin_costs(int, boolean) from public;
revoke all on function public.admin_costs(int, boolean) from anon;
revoke all on function public.admin_costs(int, boolean) from authenticated;
grant execute on function public.admin_costs(int, boolean) to service_role;

commit;

notify pgrst, 'reload schema';

-- ─── Verification ──────────────────────────────────────────────────────────
--
--   select public.admin_costs(30)->'totals';
--   select public.admin_costs(30)->'by_kind';
--   select public.admin_costs(30)->'unclassified_services';   -- should be []
--
-- To classify a new service later:
--   insert into public.llm_service_kinds (service, kind, note)
--   values ('my_new_service', 'student', 'what it does');
--
-- And the usual (must return zero rows):
--   select p.proname, a.rolname
--   from pg_proc p cross join lateral aclexplode(p.proacl) acl
--   join pg_roles a on a.oid = acl.grantee
--   where p.proname like 'admin\_%' and a.rolname in ('anon','authenticated');
