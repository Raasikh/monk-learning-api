-- ============================================================================
-- 0013_doubts_nullable_and_rls.sql — two corrections to 0012 / schema_v2
--
-- Both were found by testing the live database, not by reading the files.
-- ============================================================================

begin;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. doubts.question_text must be NULLABLE.
--
--    0012 renamed the stub's `transcribed_question` to `question_text`, which
--    silently carried its NOT NULL over. That blocks the honest-failure path:
--    a photo the transcriber cannot read is stored with status='illegible' and
--    NO question_text. Measured against the live table:
--
--      insert illegible doubt -> 400
--      23502 null value in column "question_text" violates not-null constraint
--
--    Without this, an unreadable photo cannot be recorded at all, and the only
--    remaining options are to fabricate a question or drop the row — exactly
--    what AGENTS.md Rule 4 forbids.
-- ─────────────────────────────────────────────────────────────────────────────
alter table doubts alter column question_text drop not null;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Remove client-side write access to notes and doubts.
--
--    supabase/schema_v2.sql (web repo) created insert/update/delete policies on
--    both tables. Verified against production with the ANON key and a real
--    student JWT — all six succeeded:
--
--      notes  INSERT 201 | UPDATE 200 | DELETE 200
--      doubts INSERT 201 | UPDATE 200 | DELETE 200
--
--    That contradicts AGENTS.md Rule 9 ("no insert/update policies — FastAPI
--    writes only"). Rows are still owner-scoped, so this is not a cross-user
--    leak: a student can only forge or edit their OWN rows. It still matters —
--    `doubts` is the record of what Drona actually answered, and if a student
--    can rewrite `explanation` or flip `solved`, that record (and the mistake
--    reports built on it) stops being evidence of anything.
--
--    Safe to drop: the web pages only SELECT from notes and doubts. Client
--    writes go to plan_items and profiles, which keep their policies untouched.
--    Deletes are covered by DELETE /notes/{id} and DELETE /doubts/{id}, which
--    also clean up the R2 object — something a direct client delete cannot do,
--    and which would otherwise orphan the image.
-- ─────────────────────────────────────────────────────────────────────────────
drop policy if exists "notes_insert_own" on public.notes;
drop policy if exists "notes_update_own" on public.notes;
drop policy if exists "notes_delete_own" on public.notes;

drop policy if exists "doubts_insert_own" on public.doubts;
drop policy if exists "doubts_update_own" on public.doubts;
drop policy if exists "doubts_delete_own" on public.doubts;

-- The read policies stay. schema_v2 named them *_select_own and 0012 added
-- *_owner_read; both are owner-scoped SELECT, so either is correct. Keeping
-- one of each is harmless (PostgreSQL ORs permissive policies together), but
-- one name per table is clearer.
drop policy if exists "notes_select_own" on public.notes;
drop policy if exists "doubts_select_own" on public.doubts;

commit;

-- ============================================================================
-- VERIFY
--   select tablename, policyname, cmd from pg_policies
--   where tablename in ('notes','doubts','doubt_reports','plan_items','profiles')
--   order by tablename, cmd;
--
--   -- expect exactly one SELECT policy on notes/doubts, and nothing else:
--   --   notes  | notes_owner_read  | SELECT
--   --   doubts | doubts_owner_read | SELECT
--   -- plan_items and profiles keep their full policy sets.
--
--   select column_name, is_nullable from information_schema.columns
--   where table_name = 'doubts' and column_name = 'question_text';
--   -- expect: question_text | YES
-- ============================================================================
