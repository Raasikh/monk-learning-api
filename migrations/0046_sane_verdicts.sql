-- 0046 — SANE verdicts as columns on `chapters`.
--
-- NOT APPLIED BY CLAUDE. Raasikh runs this. Until it is applied, the hold-back
-- gate reads content/sane-verdicts.json, which carries the same values and the
-- confirmation line that authorised them.
--
-- WHY THE BAR LIVES IN CODE AND THE VERDICT LIVES HERE
-- ====================================================
-- A verdict is a human judgement about one chapter and changes when a person
-- re-reviews it. The 85% bar is a policy that applies to every chapter at
-- once. Storing the bar per row would let two chapters disagree about what
-- "passing" means, which is the sort of drift that gets discovered by a blank
-- board in a live class.
--
-- NULL IS NOT A PASS, AND THAT IS ENFORCED BY THE READER, NOT BY A DEFAULT.
-- There is deliberately NO default on `sane_percent`. A chapter nobody has
-- reviewed must read as UNMEASURED and be held back, exactly like a failing
-- score. A default of 0 would work today and would be indistinguishable from a
-- real measured 0 tomorrow; a default of 100 would be the check-that-passes-
-- on-absent-information defect this project keeps finding, written into the
-- schema where nothing could see it.
--
-- `sane_verdict_by` is NOT NULL-checked against `sane_percent`: a score with
-- nobody's name on it is an assertion no one made.

begin;

alter table public.chapters
  add column if not exists sane_percent    numeric(5,2),
  add column if not exists sane_rows       integer,
  add column if not exists sane_y          integer,
  add column if not exists sane_n          integer,
  add column if not exists sane_verdict_by text,
  add column if not exists sane_verdict_at timestamptz,
  add column if not exists sane_source     text;

alter table public.chapters
  drop constraint if exists chapters_sane_range;
alter table public.chapters
  add constraint chapters_sane_range
    check (sane_percent is null
           or (sane_percent >= 0 and sane_percent <= 100));

-- A score must carry the name of whoever gave it, and the counts it came from.
alter table public.chapters
  drop constraint if exists chapters_sane_attributed;
alter table public.chapters
  add constraint chapters_sane_attributed
    check (sane_percent is null
           or (sane_verdict_by is not null
               and sane_verdict_at is not null
               and sane_source     is not null
               and sane_rows       is not null
               and sane_y          is not null
               and sane_n          is not null));

-- The counts must agree with each other. A y+n that does not equal rows means
-- one of the three was typed rather than measured.
alter table public.chapters
  drop constraint if exists chapters_sane_counts_agree;
alter table public.chapters
  add constraint chapters_sane_counts_agree
    check (sane_percent is null or (sane_y + sane_n = sane_rows));

comment on column public.chapters.sane_percent is
  'Share of measured segments a reviewer judged sane. NULL = unmeasured, which the hold-back treats exactly like a failing score. Never defaulted.';
comment on column public.chapters.sane_source is
  'Where the verdict came from, e.g. scripts/sane_proposals.md — so a number can always be traced to the sheet it was read off.';

commit;

-- Backfill, from content/sane-verdicts.json, adopted on this confirmation:
--   "confirmed: adopt scripts/sane_proposals.md as SANE verdicts for the
--    chapters it covers, verdict_by raasikh; precompute all chapters with
--    hold-back below 85%"
--
-- update public.chapters set
--   sane_percent = 75.0, sane_rows = 40, sane_y = 30, sane_n = 10,
--   sane_verdict_by = 'raasikh', sane_verdict_at = '2026-09-14',
--   sane_source = 'scripts/sane_proposals.md'
--  where subject='physics' and class_level=12 and name='Electric Charges and Fields';
--
-- update public.chapters set
--   sane_percent = 43.7, sane_rows = 71, sane_y = 31, sane_n = 40,
--   sane_verdict_by = 'raasikh', sane_verdict_at = '2026-09-14',
--   sane_source = 'scripts/sane_proposals.md'
--  where subject='mathematics' and class_level=12 and name='Application of Integrals';
--
-- update public.chapters set
--   sane_percent = 83.2, sane_rows = 113, sane_y = 94, sane_n = 19,
--   sane_verdict_by = 'raasikh', sane_verdict_at = '2026-09-14',
--   sane_source = 'scripts/sane_proposals.md'
--  where subject='chemistry' and class_level=12 and name='Aldehydes, Ketones & Carboxylic Acids';
--
-- update public.chapters set
--   sane_percent = 75.7, sane_rows = 70, sane_y = 53, sane_n = 17,
--   sane_verdict_by = 'raasikh', sane_verdict_at = '2026-09-14',
--   sane_source = 'scripts/sane_proposals.md'
--  where subject='biology' and class_level=12 and name='Ecosystem';
--
-- Every other chapter stays NULL, which is UNMEASURED, which is held back.
