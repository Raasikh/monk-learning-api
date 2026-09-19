-- 0054_admin_voice_and_transcripts.sql
--
-- Two things the database already knew and nothing ever showed.
--
-- ─── 1. Rumik ──────────────────────────────────────────────────────────────
--
-- The Costs tab reads `llm_calls`, and only the LLM paths write there. Rumik,
-- Sarvam, Deepgram and Mathpix have never recorded a row, so the dashboard has
-- been reporting the model bill as though it were the whole bill.
--
-- For Rumik that turns out to be a display problem, not an instrumentation
-- one: `drona_turns.rumik_chars` and `.rumik_requests` are 100% populated and
-- have been all along — 2,927 requests and 513,791 characters as of today.
-- TTS bills per character, so the spend is computable from rows that already
-- exist.
--
-- The rate is Rumik's published one for Silk MULBERRY — Rs 0.50 per 1,000
-- characters — and mulberry is what the code actually calls, in both the
-- classroom and the follow-up path. It is seeded here rather than guessed.
--
-- It is seeded in RUPEES, with the currency stored beside it. Rumik bills in
-- INR and the model vendors bill in USD, so there is no honest single total
-- without an exchange rate, and an exchange rate written into a migration is a
-- number that drifts silently from the day it lands. The dashboard therefore
-- reports models in dollars and voice in rupees, side by side, and leaves
-- `grand_total_usd` null. That is less tidy than one figure and it is the only
-- version of it that stays true.
--
-- Any vendor left with a NULL price shows usage and says "price not set" —
-- app/drona/usage.py's rule, that an unpriced unit records NULL and never
-- zero, because a guessed price is a confident wrong number.
--
-- A table rather than an env var, deliberately: changing a price should not
-- need a redeploy, and the value belongs next to the rows it multiplies.
--
-- Only the classroom is covered. Ask-a-follow-up also speaks through Rumik and
-- counts nothing — there is no per-turn row to count. That needs writes on a
-- live path and is not in this migration.
--
-- ─── 2. Transcripts ────────────────────────────────────────────────────────
--
-- Every classroom turn already stores what the student said (`utterance`, 99%
-- populated) and what the tutor replied (`raw_response.speech`, 100%). 1,821
-- turns of real lesson transcript, never once looked at.
--
-- `raw_response` is declared jsonb but holds a jsonb STRING, because the
-- writers pass `json.dumps(parsed_json)` into it — so the column contains a
-- quoted blob of JSON rather than an object, and `->>'speech'` on it returns
-- NULL rather than erroring. That silent-null is exactly why this needed
-- checking against real rows instead of the schema; `admin_jsonb` below
-- unwraps either shape.

begin;

-- ───────────────────────────────────────────────────────────────────────────
-- Prices for the things that are not token-billed.
-- ───────────────────────────────────────────────────────────────────────────
create table if not exists public.vendor_prices (
  vendor             text primary key,
  unit               text not null,
  price_per_1m_units numeric(12, 4),         -- NULL = unpriced, never 0
  -- Rumik bills in RUPEES; DeepSeek and OpenAI bill in dollars. Folding one
  -- into the other needs an FX rate, and an FX rate baked into a migration is
  -- a number that goes quietly wrong from the day it is written. So the
  -- currency travels with the price and the dashboard reports each in its own,
  -- rather than inventing a combined total nobody can check.
  currency           text not null default 'USD' check (currency in ('USD', 'INR')),
  note               text not null default ''
);

comment on table public.vendor_prices is
  'Per-unit prices for vendors that do not bill by token. NULL price means '
  'unpriced: /admin shows the usage and says the price is not set, rather '
  'than reporting a guess as money.';

alter table public.vendor_prices enable row level security;
revoke all on table public.vendor_prices from public;
revoke all on table public.vendor_prices from anon;
revoke all on table public.vendor_prices from authenticated;
grant all on table public.vendor_prices to service_role;

-- Rumik Silk MULBERRY, which is what the code actually calls: RUMIK_MODEL is
-- "mulberry" in both app/drona/voice_proxy.py (classroom) and
-- app/followup_voice.py (follow-ups), and acquire_lease() defaults to it.
-- Published rate: Rs 0.50 per 1,000 characters => Rs 500 per 1M.
-- The other tier, Muga, is Rs 0.99/1k; if the model ever changes, change this.
insert into public.vendor_prices (vendor, unit, price_per_1m_units, currency, note) values
  ('rumik',    'characters', 500.0000, 'INR',
     'Silk Mulberry, Rs 0.50/1k chars. Counted from drona_turns.rumik_chars. Classroom only.'),
  ('sarvam',   'seconds',    null, 'INR', 'STT. Usage is not counted anywhere yet.'),
  ('deepgram', 'seconds',    null, 'USD', 'STT. Usage is not counted anywhere yet.'),
  ('mathpix',  'requests',   null, 'USD', 'OCR. Usage is not counted anywhere yet.')
on conflict (vendor) do nothing;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_jsonb — read a column that may hold an object or a stringified one.
--
-- plpgsql rather than SQL so a row that is neither yields NULL instead of
-- taking the whole transcript query down with it. One malformed turn out of
-- 1,821 should cost you that turn, not the lesson.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_jsonb(p jsonb)
returns jsonb
language plpgsql
immutable
as $fn$
begin
  if p is null then return null; end if;
  if jsonb_typeof(p) = 'object' then return p; end if;
  if jsonb_typeof(p) = 'string' then
    begin
      return (p #>> '{}')::jsonb;
    exception when others then
      return null;
    end;
  end if;
  return null;
end
$fn$;


-- ───────────────────────────────────────────────────────────────────────────
-- admin_costs — unchanged arithmetic, plus a voice block.
--
-- The LLM buckets and `cost_usd` keep meaning exactly what they did, so the
-- "buckets sum to total" check still holds. Voice is reported alongside with
-- its own total, and `grand_total_usd` adds the two only when Rumik is priced
-- — adding an unpriced zero would quietly understate the bill.
--
-- Signature unchanged, so 0050/0051's grants survive the replace.
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
-- Voice comes from the classroom turn rows, which is the only place TTS usage
-- has ever been counted. Joined through the session to reach a user_id, so the
-- same exclusion applies as everywhere else.
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
rumik_price as (
  select price_per_1m_units as rate, currency
  from public.vendor_prices where vendor = 'rumik'
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
student_cost as (select coalesce(sum(cost_usd), 0) as v from c where kind = 'student'),
voice_total as (
  select coalesce(sum(chars), 0)::bigint as chars,
         coalesce(sum(reqs), 0)::bigint  as reqs,
         coalesce(sum(fails), 0)::bigint as fails,
         case when (select rate from rumik_price) is null then null
              else round((coalesce(sum(chars), 0)::numeric / 1000000)
                         * (select rate from rumik_price), 4) end as cost
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
    -- NULL unless voice is priced IN DOLLARS. Rumik bills in rupees today, so
    -- this stays null and the dashboard shows the two totals side by side in
    -- their own currencies. Adding them would require an exchange rate, and a
    -- hardcoded one is a number that is wrong by a little more every month.
    'grand_total_usd', (
      select case
        when (select cost from voice_total) is null then null
        when (select currency from rumik_price) <> 'USD' then null
        else round((select coalesce(sum(cost_usd), 0) from c)
                   + (select cost from voice_total), 4) end
    )
  ),
  'voice', jsonb_build_object(
    'vendor',        'rumik',
    'unit',          'characters',
    'requests',      (select reqs  from voice_total),
    'characters',    (select chars from voice_total),
    'failures',      (select fails from voice_total),
    'price_per_1m',  (select rate from rumik_price),
    'currency',      (select currency from rumik_price),
    'cost',          (select cost  from voice_total),
    'priced',        (select rate from rumik_price) is not null,
    -- Only the classroom is counted. Say so on the face of the data rather
    -- than in a doc nobody opens.
    'covers',        'classroom turns only — ask-a-follow-up also uses Rumik and is not counted',
    'daily', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'day', d.day,
               'characters', (select coalesce(sum(chars), 0) from v where v.day = d.day),
               'requests',   (select coalesce(sum(reqs), 0)  from v where v.day = d.day)
             ) order by d.day), '[]'::jsonb)
      from days d
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


-- ───────────────────────────────────────────────────────────────────────────
-- admin_session — one lesson, turn by turn.
--
-- No exclusion filter: you asked for this session, you get this session, the
-- same way admin_user() always returns the account you named.
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.admin_session(p_session_id uuid)
returns jsonb
language sql
stable
security definer
set search_path = public
as $fn$
with s as (
  select * from public.drona_sessions where id = p_session_id
),
t as (
  select tr.*, public.admin_jsonb(tr.raw_response) as rr
  from public.drona_turns tr
  where tr.session_id = p_session_id
)
select case when not exists (select 1 from s) then null else jsonb_build_object(
  'session', (
    select jsonb_build_object(
      'id', s.id, 'user_id', s.user_id, 'mode', s.mode, 'language', s.language,
      'phase', s.phase, 'subtopic_key', s.subtopic_key, 'chapter_id', s.chapter_id,
      'grounded', s.grounded, 'cost_usd', s.cost_usd,
      'created_at', s.created_at, 'last_turn_at', s.last_turn_at,
      'completed_at', s.completed_at,
      'email', (select u.email from auth.users u where u.id = s.user_id),
      'display_name', (select pr.display_name from public.profiles pr where pr.id = s.user_id)
    ) from s
  ),
  'totals', jsonb_build_object(
    'turns',          (select count(*) from t),
    'graded',         (select count(*) from t where grade is not null),
    'correct',        (select count(*) from t where grade = 'correct'),
    'interruptions',  (select count(*) from t where is_interruption),
    'failed_turns',   (select count(*) from t where coalesce(turn_failed, false)),
    'rumik_requests', (select coalesce(sum(rumik_requests), 0) from t),
    'rumik_chars',    (select coalesce(sum(rumik_chars), 0) from t),
    'tts_failures',   (select coalesce(sum(tts_failure_count), 0) from t),
    'input_tokens',   (select coalesce(sum(input_tokens), 0) from t),
    'output_tokens',  (select coalesce(sum(output_tokens), 0) from t),
    -- Reported so the dashboard can say "not recorded" rather than "0ms",
    -- which is what a coalesce here would have made it say. These three
    -- columns are declared on drona_turns and have never been written.
    'timed_turns',    (select count(*) from t where latency_ms is not null
                                                 or tts_ms is not null
                                                 or llm_ms is not null)
  ),
  'turns', (
    select coalesce(jsonb_agg(jsonb_build_object(
      'turn_index',     turn_index,
      'segment_index',  segment_index,
      'phase_in',       phase_in,
      'student',        utterance,
      'tutor',          rr ->> 'speech',
      'grade',          coalesce(grade, rr ->> 'grade'),
      'mistake_tag',    rr ->> 'mistake_tag',
      'offtopic_tier',  rr ->> 'offtopic_tier',
      'question_type',  rr ->> 'question_type',
      'board_events',   coalesce(board_event_count, 0),
      'is_interruption', is_interruption,
      'turn_failed',    coalesce(turn_failed, false),
      'rumik_chars',    coalesce(rumik_chars, 0),
      'input_tokens',   input_tokens,
      'output_tokens',  output_tokens,
      'latency_ms',     latency_ms,
      'created_at',     created_at
    ) order by turn_index), '[]'::jsonb)
    from t
  )
) end
$fn$;


-- ───────────────────────────────────────────────────────────────────────────
-- Lock the new functions. admin_jsonb and admin_session are NEW, and a new
-- function grants EXECUTE to PUBLIC by default.
--
-- admin_session matters more than most: it returns verbatim transcripts of
-- what children said out loud in a lesson. That must not be reachable with the
-- key compiled into every copy of the app.
-- ───────────────────────────────────────────────────────────────────────────
do $grants$
declare fn text;
begin
  foreach fn in array array[
    'public.admin_jsonb(jsonb)',
    'public.admin_session(uuid)',
    'public.admin_costs(int,boolean)'
  ] loop
    execute format('revoke all on function %s from public', fn);
    execute format('revoke all on function %s from anon', fn);
    execute format('revoke all on function %s from authenticated', fn);
    execute format('grant execute on function %s to service_role', fn);
  end loop;
end
$grants$;

commit;

notify pgrst, 'reload schema';

-- ─── Changing the Rumik price ──────────────────────────────────────────────
--
-- Seeded above at Rs 500/1M (Silk Mulberry). If you move tier or the rate
-- changes, one UPDATE is the whole job — no redeploy:
--
--   update public.vendor_prices
--      set price_per_1m_units = <rate>, currency = 'INR'
--    where vendor = 'rumik';
--
-- Then:  select public.admin_costs(30)->'voice';
--
-- ─── Verification ──────────────────────────────────────────────────────────
--
--   select public.admin_costs(30)->'voice';
--   select public.admin_session((select id from public.drona_sessions
--                                where (select count(*) from public.drona_turns t
--                                       where t.session_id = drona_sessions.id) > 2
--                                limit 1))->'turns'->0;
--
-- And the usual — MUST return zero rows:
--
--   select p.proname, a.rolname
--   from pg_proc p cross join lateral aclexplode(p.proacl) acl
--   join pg_roles a on a.oid = acl.grantee
--   where p.proname like 'admin\_%' and a.rolname in ('anon','authenticated');
