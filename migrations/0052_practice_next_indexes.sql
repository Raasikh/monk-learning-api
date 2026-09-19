-- 0052 — indexes for /practice/next, the tap behind every practice question.
--
-- WHY: measured against production on 2026-09-19, /practice/next was answering
-- in 1.8s warm and 4.8s cold. A student re-entering Practice waited 7-8s and a
-- subject toggle 4-5s, because both are one uncached call to this endpoint.
--
-- No migration in this repo has ever created an index on `questions`, so the
-- table has had nothing but its primary key while the bank grew to 15,408 rows.
-- Both statements below are additive: no column, constraint, policy or row is
-- touched, and dropping either one restores the previous behaviour exactly.
--
-- Deliberately NOT `CONCURRENTLY`. Concurrent builds cannot run inside a
-- transaction block, which is how the Supabase SQL editor submits a script, and
-- at these row counts a plain build takes a fraction of a second. CREATE INDEX
-- holds a SHARE lock — it blocks writes for that moment, not reads.

-- ── questions: the candidate scan ───────────────────────────────────────────
--
-- The predicate mirrors the endpoint's servable filter exactly, because a
-- partial index is only used when its predicate matches the query's:
--
--     subject = $1
--     and needs_manual is null
--     and (source is null or source <> 'extracted_master_content')
--
-- `subject` was being matched with ILIKE, which cannot use a btree index at
-- all; app/routers/practice.py now uses `=`, verified safe against production —
-- all 15,408 rows store the lowercase vocabulary app/exam_scope.py documents,
-- with zero exceptions and zero NULLs.
--
-- `chapter_id` is second in the key so the same index serves a focused session
-- (`req.chapter_id`) as well as a whole-subject one.
create index if not exists questions_servable_subject_chapter_idx
  on questions (subject, chapter_id)
  where needs_manual is null
    and (source is null or source <> 'extracted_master_content');

-- ── practice_attempts: the spacing window ───────────────────────────────────
--
-- Every call reads this student's most recent page of attempts to work out the
-- 21-attempt repeat spacing and the day's tally:
--
--     where user_id = $1 order by created_at desc limit 1000
--
-- Without an index that is a scan plus a sort of every attempt the student has
-- ever made, and it gets slower the more they practise — the opposite of what
-- it should do. `created_at desc` is in the key so the ordering is read
-- straight off the index and no sort is needed.
create index if not exists practice_attempts_user_recent_idx
  on practice_attempts (user_id, created_at desc);

-- WHAT THIS DOES NOT FIX, so it is not mistaken for done:
--
-- The candidate fetch is still truncated. There are 2,628-3,092 servable rows
-- per subject and PostgREST caps a response at 1000 without reporting it, so
-- selection sees roughly a third of the bank. An index makes that page cheap to
-- find; it does not make the page complete. Fixing it properly means selecting
-- the question IN the database rather than fetching candidates to choose from
-- in Python — which has to reproduce the exam, class and discipline rules that
-- app/routers/practice.py documents with the production incidents they exist to
-- prevent (131 class-12 maths questions leaking into a class-11 filter), so it
-- wants writing deliberately rather than alongside an index.
