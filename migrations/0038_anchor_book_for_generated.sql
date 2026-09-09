-- 0038_anchor_book_for_generated.sql
--
-- WRITTEN, NOT APPLIED. Apply by hand after review, together with 0037.
--
-- THE PROBLEM
-- ===========
-- `anchor_book` is NOT NULL with a placeholder denylist, and its own comment in
-- 0035 says what it is for: "the public-domain plate this was derived from.
-- Kept SEPARATE from licence: the generated plate is a new work, and a
-- derivative of a PD work is not automatically PD."
--
-- drona-illustrations-v1 has no such plate. Its 112 masters were generated to
-- our own prompts from our own work order; nothing was opened, referenced or
-- traced. The manifest therefore has no `anchor_book` column, and there is no
-- honest value to put in one.
--
-- WHAT NOT TO DO, AND WHY
-- =======================
-- The obvious fix is for the ingest to write a constant — 'generated, no anchor
-- plate' — for all 112 rows. That is exactly the shape 0035's own refusal
-- message warns about: "There is no default for this field, deliberately: a
-- default is what turned page_start into 5,266 rows that all said '1' and meant
-- nothing." A constant supplied by the tool to satisfy a checker is not
-- provenance; it is a checker being satisfied.
--
-- The other obvious fix is to drop the NOT NULL. That WEAKENS the constraint
-- for every row, including the third-party derived art it was written for,
-- where a missing anchor is a real gap and must stay refused.
--
-- WHAT THIS DOES INSTEAD
-- ======================
-- Makes the requirement CONDITIONAL on the thing that decides whether an anchor
-- can exist. Third-party art must still name its anchor. First-party generated
-- art may leave it NULL — and NULL here is a positive statement, because the
-- CHECK makes it reachable ONLY for `licence = 'generated-free'`. A NULL in
-- this column now means "this asset was generated, so there is no anchor
-- plate", and it cannot mean "nobody filled it in": a third-party row with a
-- NULL anchor is still refused by the same constraint.
--
-- Requires 0037 (which admits `generated-free`) to have been applied first.

begin;

alter table public.concept_assets
  alter column anchor_book drop not null;

-- Guarded so this file is safe to apply twice. Without it a re-run fails with
-- 42710 "constraint already exists", which reads like a broken migration and is
-- really just a second apply. 0037 guarded its adds; this one did not.
alter table public.concept_assets
  drop constraint if exists concept_assets_anchor_book_required;

alter table public.concept_assets
  add constraint concept_assets_anchor_book_required
    check (
      -- Generated in-house: no anchor plate exists, and NULL says so.
      (licence = 'generated-free' and anchor_book is null)
      -- Anything third-party: the anchor is required, and the placeholder
      -- denylist in 0035 still applies to whatever is written there.
      or (licence <> 'generated-free' and anchor_book is not null)
    );

commit;

-- ------------------------------------------------------------- verification
--   -- generated rows carry no anchor; third-party rows all carry one
--   select licence, count(*) filter (where anchor_book is null) as no_anchor,
--          count(*) as rows
--     from concept_assets group by 1;
--
-- WHAT IS STILL REFUSED, and must stay refused:
--   a PD-old-70 row with anchor_book NULL      -- a real gap on derived art
--   a generated-free row with anchor_book set  -- claims an anchor it never had
--
-- The second is deliberate and is the half that makes NULL mean something. If
-- a future batch IS generated from a reference plate, it is not
-- `generated-free`: it is a derivative, it names its anchor, and it takes the
-- licence its anchor allows.
