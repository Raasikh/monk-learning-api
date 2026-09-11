-- 0042_drona_turns_turn_failed.sql
--
-- WRITTEN, NOT APPLIED. Apply by hand in the Supabase SQL editor after review.
--
-- THE FAILED TURNS ARE NOT MISSING A FLAG. THEY ARE MISSING.
-- ==========================================================
-- app/drona/tutor.py has written this since the turn_failed flag was added:
--
--     if turn_failed:
--         turn_data["turn_failed"] = True
--     try:
--         supabase.table("drona_turns").insert([turn_data]).execute()
--     except Exception as db_ins_err:
--         logger.warning(f"Insert into drona_turns warning: {db_ins_err}")
--
-- The column does not exist. PostgREST does not ignore an unknown column — it
-- REJECTS THE WHOLE REQUEST with PGRST204, verified against production on
-- 2026-09-11:
--
--     probe insert REJECTED: {'message': "Could not find the 'turn_failed'
--     column of 'drona_turns' in the schema cache", 'code': 'PGRST204'}
--
-- and the key is set ONLY when the turn failed. So the effect is not "failed
-- turns are recorded without a flag". It is:
--
--     EVERY FAILED TURN IS ABSENT FROM drona_turns ENTIRELY.
--
-- Successful turns insert fine, because they never carry the key. The audit
-- table therefore contains a perfectly clean record of turns that worked and
-- no trace of any that did not — and because the insert is wrapped in a
-- try/except that logs at WARNING, nothing ever surfaced it.
--
-- WHY THIS IS WORSE THAN A MISSING COLUMN.
-- Any failure rate computed over this table reads 0%, by construction, no
-- matter how badly the product is failing. On 2026-09-10 every teaching turn
-- in production failed for hours (DeepSeek renamed the model id it echoes;
-- see tests/drona/test_model_echo.py). drona_turns recorded none of it. An
-- instrument that fails closed in the exact shape of the thing it measures is
-- worse than no instrument — the same defect, in the same words, that
-- scripts/measure_widget_routing.py's assert_every_turn_ran docstring already
-- describes for the routing harness.
--
-- NOT NULL WITH A DEFAULT, NOT NULLABLE.
-- Nullable would make three states out of two: true, false, and "written by a
-- build that predates this column". Every existing row is a turn that
-- inserted successfully, which by the logic above means a turn that did not
-- fail — so false is not a guess, it is what those rows mean. Backfilling
-- them to false and refusing null keeps the column a straight answer to "did
-- this turn fail".
--
-- THE WRITER NEEDS NO CHANGE, AND MUST NOT GET ONE.
-- It is tempting to have tutor.py always send turn_failed so the value is
-- explicit. Do not: sending the key is exactly what fails today, and a writer
-- that always sends it would have made EVERY turn — not just failed ones —
-- vanish from the table while this column was missing. The conditional write
-- is what limited the damage. It is correct as it stands once the column
-- exists.

begin;

alter table public.drona_turns
  add column if not exists turn_failed boolean not null default false;

comment on column public.drona_turns.turn_failed is
  'True when the turn''s LLM call failed and the student got a fallback '
  'apology instead of a taught turn. Written only on failure by '
  'app/drona/tutor.py; the default supplies false for every healthy turn. '
  'Added 0042 after the column''s absence was found to be rejecting the '
  'entire insert (PGRST204), so failed turns were absent from this table '
  'rather than merely unflagged.';

commit;

-- ------------------------------------------------------------- verification
--   -- 1. the column exists and refuses null
--   select column_name, data_type, is_nullable, column_default
--     from information_schema.columns
--    where table_name = 'drona_turns' and column_name = 'turn_failed';
--   -- expect: boolean | NO | false
--
--   -- 2. every pre-existing row reads false, and none read null
--   select turn_failed, count(*) from public.drona_turns group by 1;
--
--   -- 3. the insert that was rejected now succeeds — run a real failing turn
--   --    (or the probe below) and confirm a row appears:
--   --      insert into public.drona_turns
--   --        (session_id, turn_index, segment_index, phase_in, turn_failed)
--   --      values (<a real session_id>, 999, 1, 'teaching', true);
--   select count(*) from public.drona_turns where turn_failed;
--
-- AFTER APPLYING: the first failed turn in production should now appear here.
-- If `select count(*) where turn_failed` stays at 0 across a known outage,
-- the write path is broken somewhere else and this migration did not fix it.
