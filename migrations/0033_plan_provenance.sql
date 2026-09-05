-- 0033_plan_provenance.sql
--
-- WRITTEN, NOT APPLIED. Apply by hand in the Supabase SQL editor after review;
-- this repo holds PostgREST credentials only, which cannot run DDL.
--
-- WHY, AND WHY BEFORE ANY PRECOMPUTE
-- ==================================
-- Precomputing lesson plans without provenance is the prompt_version mistake
-- repeated at scale: rows nobody can trace back to the prompt, code, model or
-- corpus that produced them. Today 20 rows are hard to explain; after a
-- corpus-wide precompute it would be 1,154.
--
-- What lesson_plans records today, and why it is not enough:
--
--   prompt_version   populated (6 distinct values over 20 rows) but it is a
--                    sha over ALL prompts/*.md. It changes when an unrelated
--                    prompt changes, and does NOT change when planner.py or
--                    the model changes. It cannot answer "was this plan built
--                    by the current planner".
--   source_model     populated, free text.
--   topic_hash       NULL in 20 of 20 rows. A column that has never held a
--                    value. Resolved below.
--   (absent)         temperature, retrieval config, corpus version.
--
-- THE CACHE KEY this supports, specified in docs/plan-invalidation.md:
--   (concept_id, planner_prompt_hash, planner_code_sha, model_id,
--    archetype_version, chunk_corpus_version)
-- Any component changing means the plan is stale.

begin;

-- ---------------------------------------------------------------- provenance
alter table public.lesson_plans
  -- sha256 of prompts/planner.md + planner_outline.md + planner_segment.md,
  -- concatenated in sorted filename order, first 16 hex chars. THESE THREE
  -- FILES ONLY -- the point is a hash that moves when the planner's own
  -- instructions move and stays still otherwise. Current value: 67c77472bcd8ae0a
  add column if not exists planner_prompt_hash text,

  -- sha256 of app/drona/planner.py, first 16 hex chars. Separate from the
  -- prompt hash because prompt and code change independently and a plan can
  -- be stale on either. Current value: 300ef519df030e97
  add column if not exists planner_code_sha text,

  -- Exact model identifier, e.g. 'deepseek-v4-pro'. source_model already
  -- exists and is free text; this is the one the cache key reads, so it must
  -- be the literal id passed to the API, not a label.
  add column if not exists model_id text,

  -- Sampling temperature. planner.py passes 0.0 at all three call sites
  -- (lines 203, 375, 487). Recorded because a future change to it changes
  -- every plan's reproducibility, and because "we always used 0" is the kind
  -- of claim that should be checkable rather than remembered.
  add column if not exists temperature real,

  -- Retrieval configuration as it was at generation time. jsonb rather than
  -- columns because this is the part most likely to grow. Shape:
  --   {"top_k": 12, "embedding_model": "text-embedding-3-small",
  --    "rpc": "match_pdf_chunks"}
  add column if not exists retrieval_config jsonb,

  -- Which corpus the plan was grounded in. The books WILL be revised, and a
  -- plan built on superseded chunks must be able to say so. See
  -- docs/plan-invalidation.md for how this is computed.
  add column if not exists chunk_corpus_version text,

  -- Which archetype classification chose the widget for each segment.
  add column if not exists archetype_version text;

-- ---------------------------------------------------------------- topic_hash
-- RESOLVED BY DROPPING, not by populating.
--
-- It is NULL in 20 of 20 rows, so nothing depends on its value. Its intended
-- meaning is also now served better by the cache key above: it was a single
-- opaque hash standing in for "the inputs that produced this plan", and that
-- is exactly what the six named columns express, individually and legibly.
-- Keeping it would leave a column that is either permanently NULL or a second, weaker
-- answer to a question already answered.
--
-- A column nobody populates is worse than no column: it passes every
-- completeness check while asserting nothing. That is the same failure as
-- page_start being hardcoded to 1 across all 5,266 rows.
alter table public.lesson_plans drop column if exists topic_hash;

-- ------------------------------------------------------------------ backfill
-- The 20 existing rows were generated before any of this was recorded, so
-- their real provenance is NOT recoverable. They are marked as such rather
-- than being given plausible-looking values -- a wrong provenance is worse
-- than an absent one, because it invites trust.
update public.lesson_plans
   set planner_prompt_hash = coalesce(planner_prompt_hash, 'unknown-pre-0033'),
       planner_code_sha    = coalesce(planner_code_sha,    'unknown-pre-0033'),
       model_id            = coalesce(model_id, nullif(source_model, '')),
       chunk_corpus_version= coalesce(chunk_corpus_version, 'unknown-pre-0033')
 where planner_prompt_hash is null;

-- --------------------------------------------------------------- constraints
-- NOT NULL is applied AFTER the backfill so it cannot fail on existing rows,
-- and it is the point of the migration: a plan with no provenance must be
-- impossible to insert, not merely discouraged.
alter table public.lesson_plans
  alter column planner_prompt_hash set not null,
  alter column planner_code_sha    set not null,
  alter column chunk_corpus_version set not null;

-- The cache lookup. Not unique: several plans may legitimately share a key
-- during a regeneration sweep, and uniqueness would turn a race into an error.
create index if not exists lesson_plans_cache_key_idx
  on public.lesson_plans
  (subtopic_key, planner_prompt_hash, planner_code_sha, model_id, chunk_corpus_version);

commit;

-- ------------------------------------------------------------- verification
-- Run after applying. Every one of these should return zero rows.
--
--   select count(*) from lesson_plans where planner_prompt_hash = 'unknown-pre-0033'
--     and created_at > now() - interval '1 hour';   -- new rows must be traceable
--
--   select column_name from information_schema.columns
--    where table_name='lesson_plans' and column_name='topic_hash';  -- must be gone
--
-- And confirm the writer populates them: generate ONE plan and check that
-- planner_prompt_hash equals the sha of the three planner prompt files. If the
-- writer was not updated, this migration silently fills every new row with the
-- backfill default and we are back where we started.
