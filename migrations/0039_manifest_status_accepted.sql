-- 0039_manifest_status_accepted.sql
--
-- WRITTEN, NOT APPLIED. Apply by hand in the Supabase SQL editor after review.
--
-- ONE WORD. THE ONE THE PIPELINE ACTUALLY USES.
-- =============================================
-- 0035 pinned `manifest_status = 'approved'`. Nothing has ever written that
-- value. The manifest column is spelled `accepted`:
--
--     status
--     ------
--     accepted    112 rows
--     svg-queue     1 row   (deliberately not ingested; see KNOWN_SKIP_STATUSES)
--
-- so --execute uploaded 105 masters and 105 renditions and then failed all 105
-- database writes with 23514 against this constraint. `approved` was a word
-- chosen while writing 0035, before any manifest with real statuses existed.
-- It is not a second gate, a legacy value, or a different meaning: it is the
-- same state under a name the generator does not use.
--
-- WHY THIS IS A NARROWING, NOT A WEAKENING.
-- The obvious fix is `in ('approved', 'accepted')`, and it is the wrong one.
-- Read what 0035 says this column is for:
--
--     "Recorded so a later change to what counts as approved is detectable,
--      and so a row cannot exist that was admitted under some other status."
--
-- Two admitted words for one state is exactly what defeats that. A row saying
-- `approved` and a row saying `accepted` would be indistinguishable in meaning
-- and distinguishable in text, and nobody reading the table later could tell
-- whether the difference meant anything. The allowlist stays at ONE member; a
-- third value is refused exactly as before, and the property 0035 wanted still
-- holds.
--
-- The value being dropped has zero rows — `select count(*) from
-- concept_assets` was 0 when this was written, and this migration asserts it
-- rather than trusting the note. If that assertion fires, STOP: a row admitted
-- under 'approved' exists, this is no longer a rename, and it needs a decision
-- rather than a migration.

begin;

do $$
declare n int;
begin
  select count(*) into n from public.concept_assets
   where manifest_status = 'approved';
  if n > 0 then
    raise exception
      'REFUSED: % row(s) were admitted under manifest_status=''approved''. '
      'This migration assumed none existed. Do not drop the value they were '
      'admitted under — decide what those rows mean first.', n;
  end if;
end $$;

alter table public.concept_assets
  drop constraint if exists concept_assets_manifest_status;

alter table public.concept_assets
  add constraint concept_assets_manifest_status
    check (manifest_status = 'accepted');

commit;

-- ------------------------------------------------------------- verification
--   -- every row names the gate it came through, and it is the one word
--   select manifest_status, count(*) from concept_assets group by 1;
--
-- WHAT IS STILL REFUSED, and must stay refused:
--   manifest_status 'svg-queue'   queued for a tier-3 SVG, not ingested art
--   manifest_status 'approved'    a word no manifest writes; see above
--   manifest_status 'pending'     admitted under no gate at all
--   manifest_status ''            the placeholder denylist catches it first
