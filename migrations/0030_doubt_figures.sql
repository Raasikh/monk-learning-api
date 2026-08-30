-- 0030_doubt_figures.sql
--
-- The figures a question was PRINTED with, kept so a student can see them.
--
-- Snap discards the photo after OCR: the transcript is the record, and a
-- second copy of the whole page costs storage for no benefit. That holds right
-- up until the question says "as shown in the figure" — a beaker with two
-- liquids, a stress-strain graph, two current-carrying wires — at which point
-- the transcript is a question the student cannot answer, referring to a
-- picture they cannot see.
--
-- Option figures needed no column: an option is a jsonb object and carries its
-- own key. A figure belonging to the QUESTION has no option to ride on, which
-- is what this column is for. Keys only — the objects live in R2 and are
-- handed to a client as short-lived signed URLs, never as keys.

alter table doubts
  add column if not exists figures jsonb not null default '[]'::jsonb;

comment on column doubts.figures is
  'R2 keys for the figures this question was printed with, in reading order. '
  'Served as signed URLs; deleted with the row.';
