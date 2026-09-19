-- 0056_admin_user_cost_and_latency.sql
--
-- Everything one student costs, and how slow it was for them, on their page.
--
-- ─── What can honestly be shown, and what cannot ───────────────────────────
--
-- Measured against production before writing a line of this:
--
--   LLM   llm_calls    82,900 rows, 1,221 with a user_id  ->   1% attributable
--                      latency_ms 100% populated
--   TTS   drona_turns  1,821 rows, rumik_chars/requests  -> 100% attributable
--                      (joined to the user through drona_sessions)
--   STT   Sarvam / Deepgram                              ->   NOT RECORDED AT ALL
--   Snap  doubts.latency_ms 92%, transcribe_ms 96%       ->  end-to-end, per doubt
--   Class drona_turns.latency_ms / tts_ms / llm_ms       ->   0%, three dead columns
--
-- So this function reports three different kinds of thing and must not let
-- them look alike:
--
--   * numbers that are complete       (TTS, snap latency)
--   * numbers that are a SAMPLE       (LLM cost — 1% of calls carry a user)
--   * numbers that do not exist       (STT, classroom turn latency)
--
-- The third kind is the dangerous one. A per-user cost panel that silently
-- omits speech-to-text reads as "this student cost $0.04", and someone will
-- multiply it by ten thousand. So `stt` is present in the output with
-- `recorded: false` and a reason, and the LLM block carries the count of calls
-- that could be attributed alongside the cost, so a small number is visibly
-- small-because-unattributed rather than small-because-cheap.
--
-- Fixing the LLM 1% is a code change, not a query: user_id has to be threaded
-- at the call sites. The snap path was done; the planner is deliberately
-- unattributed (a lesson is authored once for everyone); the classroom tutor
-- already passes it. What remains unattributed is mostly content authoring,
-- which is exactly the spend that does NOT belong to a student.
--
-- ─── Money ─────────────────────────────────────────────────────────────────
--
-- All USD, converted from vendor currency at admin_settings.inr_per_usd (95).
-- The rate travels in the response so a figure can be traced to its assumption.

begin;

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
  select id, email, created_at, last_sign_in_at, banned_until
  from auth.users where id = p_user_id
),
days as (
  select d::date as day
  from generate_series((select from_day from b), (select today from b), interval '1 day') d
),
act as (
  select (a.at at time zone 'Asia/Kolkata')::date as day
  from public.admin_activity((select from_ts from b), true) a
  where a.user_id = p_user_id
),
fx as (
  select coalesce((select value from public.admin_settings where key = 'inr_per_usd'), 95)
         as inr_per_usd
),
rumik as (
  select case when vp.price_per_1m_units is null then null
              when vp.currency = 'INR'
                then round(vp.price_per_1m_units / (select inr_per_usd from fx), 6)
              else vp.price_per_1m_units end as rate_usd
  from public.vendor_prices vp where vp.vendor = 'rumik'
),
-- Lifetime, not windowed: "what has this student cost us" is the question the
-- page is for, and a 30-day slice of it invites the wrong comparison against
-- the lifetime counters sitting beside it.
llm as (
  select l.service, l.model, l.ok, l.cost_usd, l.latency_ms,
         l.input_tokens, l.output_tokens
  from public.llm_calls l where l.user_id = p_user_id
),
sess as (select id from public.drona_sessions where user_id = p_user_id),
tts as (
  select coalesce(sum(t.rumik_requests), 0)::bigint    as reqs,
         coalesce(sum(t.rumik_chars), 0)::bigint       as chars,
         coalesce(sum(t.tts_failure_count), 0)::bigint as fails,
         coalesce(sum(t.input_tokens), 0)::bigint      as in_tok,
         coalesce(sum(t.output_tokens), 0)::bigint     as out_tok
  from public.drona_turns t where t.session_id in (select id from sess)
),
dbt as (
  select latency_ms, transcribe_ms, solved
  from public.doubts where user_id = p_user_id
)
select case when not exists (select 1 from u) then null else jsonb_build_object(
  'user_id',         p_user_id,
  'email',           (select email from u),
  'signed_up_at',    (select created_at from u),
  'last_sign_in_at', (select last_sign_in_at from u),
  'internal',        exists (select 1 from public.admin_excluded_users z where z.user_id = p_user_id),
  'deleted',         exists (select 1 from public.admin_deleted_users  z where z.user_id = p_user_id),
  'banned_until',    (select banned_until from u),
  'deletion', (
    select to_jsonb(x) from (
      select reason, deleted_by, deleted_at
      from public.admin_deleted_users where user_id = p_user_id) x
  ),
  'profile', (
    select to_jsonb(x) from (
      select display_name, phone, phone_verified, target_exam, enrolled_class, created_at
      from public.profiles where id = p_user_id) x
  ),

  -- ── Everything this student cost, by vendor class ──────────────────────
  'costs', jsonb_build_object(
    'inr_per_usd', (select inr_per_usd from fx),
    'llm', jsonb_build_object(
      'calls',         (select count(*) from llm),
      'failed',        (select count(*) from llm where not ok),
      'cost_usd',      (select round(coalesce(sum(cost_usd), 0)::numeric, 6) from llm),
      'input_tokens',  (select coalesce(sum(input_tokens), 0) from llm),
      'output_tokens', (select coalesce(sum(output_tokens), 0) from llm),
      -- Say so on the data, not in a doc: only ~1% of llm_calls carry a
      -- user_id, so this is a floor on what the student cost, not the figure.
      'attribution',   'only calls that recorded a user_id appear here; '
                       'content authoring is unattributed by design',
      'by_service', (
        select coalesce(jsonb_agg(jsonb_build_object(
                 'service', service, 'calls', n, 'cost_usd', cost,
                 'p95_latency_ms', p95) order by cost desc nulls last), '[]'::jsonb)
        from (select service, count(*) n,
                     round(coalesce(sum(cost_usd), 0)::numeric, 6) cost,
                     round(percentile_cont(0.95) within group (order by latency_ms))::int p95
              from llm group by service) x
      ),
      'by_model', (
        select coalesce(jsonb_agg(jsonb_build_object(
                 'model', model, 'calls', n, 'cost_usd', cost) order by cost desc nulls last), '[]'::jsonb)
        from (select model, count(*) n,
                     round(coalesce(sum(cost_usd), 0)::numeric, 6) cost
              from llm group by model) x
      )
    ),
    'tts', jsonb_build_object(
      'vendor',           'rumik',
      'requests',         (select reqs  from tts),
      'characters',       (select chars from tts),
      'failures',         (select fails from tts),
      'price_per_1m_usd', (select rate_usd from rumik),
      'cost_usd', (select case when (select rate_usd from rumik) is null then null
                          else round(((select chars from tts)::numeric / 1000000)
                                     * (select rate_usd from rumik), 6) end),
      'coverage', 'classroom turns only; ask-a-follow-up also speaks and is not counted'
    ),
    -- Present precisely so its absence is visible. A per-user cost panel that
    -- silently drops speech-to-text reads as a complete figure and is not one.
    'stt', jsonb_build_object(
      'recorded', false,
      'vendors',  jsonb_build_array('sarvam', 'deepgram'),
      'note',     'no table, column or counter records STT usage anywhere — '
                  'this cannot be reported until the call sites record it'
    ),
    'total_usd', (
      select case when (select rate_usd from rumik) is null then null
             else round((select coalesce(sum(cost_usd), 0) from llm)
                        + ((select chars from tts)::numeric / 1000000)
                          * (select rate_usd from rumik), 6) end
    ),
    'total_is_partial', true
  ),

  -- ── How slow it was for them ───────────────────────────────────────────
  'latency', jsonb_build_object(
    'llm_call_ms', (
      select jsonb_build_object(
        'n',   count(*),
        'p50', round(percentile_cont(0.50) within group (order by latency_ms))::int,
        'p95', round(percentile_cont(0.95) within group (order by latency_ms))::int,
        'max', max(latency_ms))
      from llm where latency_ms is not null
    ),
    -- End to end, from photo to answer. The number the student actually felt.
    'doubt_solve_ms', (
      select jsonb_build_object(
        'n',   count(*),
        'p50', round(percentile_cont(0.50) within group (order by latency_ms))::int,
        'p95', round(percentile_cont(0.95) within group (order by latency_ms))::int,
        'max', max(latency_ms))
      from dbt where latency_ms is not null
    ),
    'doubt_transcribe_ms', (
      select jsonb_build_object(
        'n',   count(*),
        'p50', round(percentile_cont(0.50) within group (order by transcribe_ms))::int,
        'p95', round(percentile_cont(0.95) within group (order by transcribe_ms))::int,
        'max', max(transcribe_ms))
      from dbt where transcribe_ms is not null
    ),
    'classroom_turn_ms', jsonb_build_object(
      'recorded', false,
      'note', 'drona_turns declares latency_ms, tts_ms and llm_ms and all three '
              'are unwritten across every turn ever taken'
    )
  ),

  'totals', jsonb_build_object(
    'attempts', (select count(*) from public.practice_attempts where user_id = p_user_id),
    'correct',  (select count(*) from public.practice_attempts where user_id = p_user_id and is_correct),
    'gave_up',  (select count(*) from public.practice_attempts where user_id = p_user_id and gave_up),
    'sessions', (select count(*) from sess),
    'sessions_completed', (select count(*) from public.drona_sessions
                           where user_id = p_user_id and phase = 'complete'),
    'turns',    (select count(*) from public.drona_turns t where t.session_id in (select id from sess)),
    'doubts',   (select count(*) from dbt),
    'doubts_solved', (select count(*) from dbt where solved),
    'notes',    (select count(*) from public.notes where user_id = p_user_id),
    'cost_usd', (select round(coalesce(sum(cost_usd), 0)::numeric, 4) from llm),
    'input_tokens',  (select coalesce(sum(input_tokens), 0) from llm)
                     + (select in_tok from tts),
    'output_tokens', (select coalesce(sum(output_tokens), 0) from llm)
                     + (select out_tok from tts),
    'last_active_at', greatest(
      (select max(created_at)   from public.practice_attempts where user_id = p_user_id),
      (select max(last_turn_at) from public.drona_sessions   where user_id = p_user_id),
      (select max(created_at)   from public.doubts           where user_id = p_user_id),
      (select max(created_at)   from public.notes            where user_id = p_user_id)
    )
  ),
  'daily', (
    select coalesce(jsonb_agg(jsonb_build_object(
             'day', d.day, 'events', coalesce(a.n, 0)) order by d.day), '[]'::jsonb)
    from days d
    left join (select day, count(*) n from act group by day) a on a.day = d.day
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
    from (select id, chapter, concept, solved, status, question_text,
                 latency_ms, transcribe_ms, created_at
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

revoke all on function public.admin_user(uuid, int) from public;
revoke all on function public.admin_user(uuid, int) from anon;
revoke all on function public.admin_user(uuid, int) from authenticated;
grant execute on function public.admin_user(uuid, int) to service_role;

commit;

notify pgrst, 'reload schema';

-- ─── Verification ──────────────────────────────────────────────────────────
--
--   select public.admin_user((select user_id from public.drona_sessions limit 1))->'costs';
--   select public.admin_user((select user_id from public.doubts
--                             where latency_ms is not null limit 1))->'latency';
--
-- `costs.stt.recorded` must be false and `costs.total_is_partial` true — both
-- are there so the panel cannot present a partial figure as a complete one.
