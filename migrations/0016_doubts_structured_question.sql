-- ============================================================================
-- 0016_doubts_structured_question.sql — store the stem and options separately
--
-- `question_text` has always held stem+options concatenated as one string
-- (question.get("text") in app/routers/doubts.py), because that is what the
-- structuring pass produces for display. The doubt detail page rendered that
-- single blob as one paragraph — stem and four options run together with no
-- structure, which is the "jumbled up" rendering reported against a real page
-- (Q36, waves and organ pipes).
--
-- The pipeline has ALWAYS carried the stem and options separately internally
-- (question["stem"], question["options"] — see app/snap.py, used to decide
-- what the solver is shown). They were simply never persisted. This adds two
-- columns so the frontend can render "Q: <stem>" then a clean options list,
-- instead of one run-on paragraph.
--
-- `question_text` is kept, unchanged, for backward compatibility with search
-- (ilike over question_text) and as the single-string fallback for any doubt
-- solved before this migration, where stem/options will be null.
-- ============================================================================

begin;

alter table doubts add column if not exists stem     text;
alter table doubts add column if not exists options  jsonb not null default '[]'::jsonb;

commit;

-- ============================================================================
-- VERIFY
--   select column_name, data_type from information_schema.columns
--   where table_name = 'doubts' and column_name in ('stem', 'options');
-- ============================================================================
