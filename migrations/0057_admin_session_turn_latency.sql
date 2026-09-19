-- 0057_admin_session_turn_latency.sql
--
-- Report the turn timings that tutor.py and scoped_turn.py now write.
--
-- Until today drona_turns.latency_ms and .llm_ms were declared and never
-- written — 0% populated across every turn ever taken — so admin_session()
-- could only report `timed_turns` and say "none". Both writers now fill them:
-- latency_ms is the whole turn (entry to audit insert), llm_ms the model's
-- share of it, so a slow lesson can be attributed rather than just noticed.
--
-- tts_ms stays unwritten and unreported. Synthesis happens in the WS consumer
-- after the turn generator has yielded, so there is no TTS duration in scope
-- at the insert. Reporting a zero for it would make an unmeasured thing look
-- instant, which is the failure this whole run has been unpicking.
--
-- Percentiles ignore nulls by construction, so old untimed turns neither
-- distort the numbers nor block them: a lesson taught before today reports
-- timed_turns = 0 and the panel says so, while one taught after reports real
-- figures from its first turn.

begin;

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
    'timed_turns',    (select count(*) from t where latency_ms is not null),
    'turn_p50_ms',    (select round(percentile_cont(0.50) within group (order by latency_ms))::int
                       from t where latency_ms is not null),
    'turn_p95_ms',    (select round(percentile_cont(0.95) within group (order by latency_ms))::int
                       from t where latency_ms is not null),
    'turn_max_ms',    (select max(latency_ms) from t),
    'llm_p50_ms',     (select round(percentile_cont(0.50) within group (order by llm_ms))::int
                       from t where llm_ms is not null),
    'llm_p95_ms',     (select round(percentile_cont(0.95) within group (order by llm_ms))::int
                       from t where llm_ms is not null)
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
      'llm_ms',         llm_ms,
      'created_at',     created_at
    ) order by turn_index), '[]'::jsonb)
    from t
  )
) end
$fn$;

revoke all on function public.admin_session(uuid) from public;
revoke all on function public.admin_session(uuid) from anon;
revoke all on function public.admin_session(uuid) from authenticated;
grant execute on function public.admin_session(uuid) to service_role;

commit;

notify pgrst, 'reload schema';

-- ─── Verification, once a lesson has been taught after this deploy ─────────
--
--   select id, latency_ms, llm_ms from public.drona_turns
--    where latency_ms is not null order by created_at desc limit 5;
--
--   select public.admin_session('<that session id>')->'totals';
