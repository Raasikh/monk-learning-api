-- 0043_practice_attempts_gave_up.sql
--
-- WRITTEN, NOT APPLIED. Apply by hand in the Supabase SQL editor after review.
--
-- "I DON'T KNOW" AND "GOT IT WRONG" ARE CURRENTLY THE SAME ROW.
-- =============================================================
-- The Practice screen dropped its Skip button and replaced it with an explicit
-- "I don't know", which submits with no chosen option. app/routers/practice.py
-- grades that exactly as it grades a wrong answer, because it is one by every
-- test it applies:
--
--     if req.chosen_option and correct_option:
--         is_correct = req.chosen_option.strip().lower() == ...
--
-- with no chosen_option, is_correct stays False. So the attempt lands in
-- practice_attempts indistinguishable from a student who answered and missed.
--
-- That is defensible for concept mastery — they did not know it either way —
-- and WRONG for everything else being built on this table.
--
-- WHY IT MATTERS MOST FOR PACE.
-- The pace card on Progress ("avg time per question", per subject) is meant to
-- answer "how long does this student take to SOLVE one". Giving up takes a few
-- seconds; solving takes minutes. Leave the two mixed and the median is pulled
-- down hardest in exactly the subjects students give up on most, so the card
-- would report that the hardest subject is the fastest. The query needs to be
-- able to say `and gave_up = false`, and today it cannot.
--
-- It also blocks the softer thing the client wants to do: notice five
-- consecutive give-ups in one chapter and offer a lesson. Five wrong answers
-- and five give-ups are different students and only one of them is stuck.
--
-- NOT NULL WITH A DEFAULT, NOT NULLABLE.
-- Nullable would make three states out of two: true, false, and "written
-- before this column existed". Every existing row was written when the only
-- way to submit was to choose an answer — Skip wrote nothing at all — so false
-- is not a guess about those rows, it is what they mean.
--
-- THE WRITER MUST SEND IT ALWAYS, UNLIKE 0042.
-- 0042 documents a column whose writer sent the key only in the failure case,
-- which is what limited the damage while the column was missing. This one is
-- the opposite: practice.py sends `gave_up` on every insert. That is safe only
-- once this migration has been applied, because PostgREST rejects the whole
-- insert on an unknown column (PGRST204) rather than ignoring it — so applying
-- this BEFORE deploying the matching app change is required, not preferred.
-- Deploy in that order or every practice answer will fail to record.

begin;

alter table public.practice_attempts
  add column if not exists gave_up boolean not null default false;

comment on column public.practice_attempts.gave_up is
  'True when the student pressed "I don''t know" instead of answering. Such an '
  'attempt is still graded incorrect and still spaces the question the same '
  'way, but it must be excluded from any timing statistic: giving up is fast '
  'and solving is slow, so mixing them makes the hardest subject look like the '
  'quickest. Added 0043 with the Skip button''s removal.';

-- The pace query is "this user's first attempts at questions they actually
-- tried, by subject" — so it filters on exactly these three, every time.
create index if not exists practice_attempts_user_genuine_idx
  on public.practice_attempts (user_id, gave_up, created_at desc);

commit;

-- ------------------------------------------------------------- verification
--   -- 1. the column exists, refuses null, defaults false
--   select column_name, data_type, is_nullable, column_default
--     from information_schema.columns
--    where table_name = 'practice_attempts' and column_name = 'gave_up';
--   -- expect: boolean | NO | false
--
--   -- 2. every pre-existing row reads false, and none read null
--   select gave_up, count(*) from public.practice_attempts group by 1;
--   -- expect: a single row, false = <all of them>
--
--   -- 3. after deploying the app change, a real "I don't know" lands as true
--   select gave_up, is_correct, created_at
--     from public.practice_attempts
--    order by created_at desc limit 5;
--   -- expect: the give-up reads gave_up = true, is_correct = false
--
-- IF STEP 3 SHOWS NO true ROWS after a give-up, the client is not sending the
-- flag — check that app/practice.tsx passes `gave_up` and that the request
-- model in app/routers/practice.py has not dropped it.
