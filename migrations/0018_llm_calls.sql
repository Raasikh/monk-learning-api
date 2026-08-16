-- Every model call, recorded where it can be queried.
--
-- Written 2026-08-15 after $8.86 of deepseek-v4-pro (10,937 requests,
-- 15,087,263 tokens) could not be attributed to anything in the database.
-- drona_sessions.cost_usd existed but was never written; drona_turns captured
-- tokens for tutor turns only, so the planner - the single most expensive path,
-- 7-10 Pro calls per plan with 2-attempt retries - left no trace at all. The
-- only record of that spend was DeepSeek's own dashboard.
--
-- Tokens are the ground truth here and are always recorded. cost_usd is
-- DERIVED, and is null when prices are not configured (see app/drona/usage.py)
-- rather than defaulting to 0, so "we don't know" stays distinguishable from
-- "it was free" - the exact ambiguity that made drona_sessions.cost_usd = 0.0000
-- useless during the investigation.
create table if not exists llm_calls (
  id               uuid primary key default gen_random_uuid(),

  -- what was called
  model            text not null,
  service          text not null,          -- planner | segment | outline | tutor | scoping | practice_explain | snap_solve | ...
  ok               boolean not null,       -- false = the call billed but its result was discarded
  attempt          smallint not null default 1,

  -- what it cost
  input_tokens     integer,
  cache_hit_tokens integer,
  output_tokens    integer,
  cost_usd         numeric(12,6),          -- null when prices are unconfigured; never guessed
  latency_ms       integer,

  -- what it belonged to. All nullable: a call that fails before a plan or
  -- session row exists must still be recorded, because those are precisely the
  -- calls that were invisible before.
  session_id       uuid references drona_sessions(id) on delete set null,
  plan_id          uuid references lesson_plans(id) on delete set null,
  chapter_id       uuid references chapters(id) on delete set null,
  subtopic_key     text,
  user_id          uuid references auth.users(id) on delete set null,

  error            text,
  created_at       timestamptz not null default now()
);

create index if not exists llm_calls_created_idx on llm_calls (created_at desc);
create index if not exists llm_calls_model_created_idx on llm_calls (model, created_at desc);
create index if not exists llm_calls_service_idx on llm_calls (service, created_at desc);
create index if not exists llm_calls_session_idx on llm_calls (session_id);
