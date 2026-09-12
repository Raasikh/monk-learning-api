-- The question as the student photographed it, kept so the app can show them
-- their own page instead of a transcription of it.
--
-- One R2 object key, or NULL. NULL is normal and must stay readable: a page
-- whose question numbers could not be located gives no span to cut, R2 may not
-- be configured, and every doubt saved before this migration has none. The
-- screen falls back to the transcription in all three cases.
--
-- Why an image at all, when the transcription is already stored: the
-- transcription is what the SOLVER needs, and it is not what the student
-- should have to read back. Mathpix spells a drawn structure as
-- `<smiles>C1CCNC1`, renders gamma inconsistently at screen resolution, and a
-- question it half-read arrives looking mangled in a way a student cannot
-- distinguish from a question that IS mangled. Their own photograph has none
-- of those failure modes.
--
-- The transcription is NOT replaced by this. Library search matches on it,
-- follow-ups use it as context, and the solver is still handed it rather than
-- the picture — see MODEL_SOLVE_VISION in app/snap.py, which adds the figure
-- alongside the text and never in place of it.
alter table doubts
  add column if not exists question_image text;

comment on column doubts.question_image is
  'R2 object key for the cropped photo of this question. NULL when no span '
  'could be cut or the bucket is not configured; the client falls back to the '
  'transcription. Served only as a short-lived signed URL, never as a key.';

-- RETENTION: these objects are meant to live 360 days and then go.
--
-- Deliberately NOT expressed here. Postgres holds the key, R2 holds the bytes,
-- and deleting the row would orphan the object rather than remove it — so the
-- lifetime belongs to the bucket, as an R2 lifecycle rule on the `doubts/`
-- prefix. Putting a 360-day trigger in this file would read as if the deletion
-- were handled when nothing would actually be freed.
--
-- Set it once on the bucket, e.g.:
--   wrangler r2 bucket lifecycle add <bucket> \
--     --prefix doubts/ --expire-days 360
--
-- Until that rule exists these objects are kept indefinitely. That is a cost
-- question rather than a correctness one: a deleted object simply sends the
-- screen back to the transcription, which is what it showed before.
