-- 0041_concept_assets_sha256_required.sql
--
-- WRITTEN, NOT APPLIED. Apply AFTER 0040 and after `ingest_asset.py --execute`
-- has backfilled every row.
--
-- Closes the window 0040 opened. A column that is nullable for ever is a
-- column that is sometimes filled in, and "sometimes" is what makes a cache
-- key untrustworthy: the client cannot tell "this asset has no version" from
-- "nobody backfilled this one".
--
-- THE RENDITION HASH IS CONDITIONALLY REQUIRED, NOT UNCONDITIONALLY.
-- A master at or above 1800 px has no @2x — the widest request the client can
-- make is 900pt at 2x, so one would never be fetched and the ingest does not
-- produce it. NULL there means "this master needs no rendition"; NULL on a
-- narrower master means "the backfill missed one". A plain NOT NULL would
-- conflate them and would refuse a correct row.

begin;

do $$
declare n_master int; n_rend int; same int;
begin
  select count(*) into n_master from public.concept_assets
   where master_sha256 is null;
  if n_master > 0 then
    raise exception
      'REFUSED: % row(s) still have a NULL master_sha256. Run '
      'scripts/ingest_asset.py ingest --execute first; it is idempotent and '
      'backfills from the files it already reads.', n_master;
  end if;

  select count(*) into n_rend from public.concept_assets
   where rendition_2x_sha256 is null and width < 1800;
  if n_rend > 0 then
    raise exception
      'REFUSED: % narrow master(s) have a NULL rendition_2x_sha256. Every '
      'master under 1800px is asked for an @2x by some device, so a missing '
      'hash there is a file the client cannot verify.', n_rend;
  end if;

  -- The backfill that would look right and be wrong: copying the RAW hash.
  -- The two are the same shape, so no CHECK can separate them; only equality
  -- across the whole table can, and it must be zero — the master is the
  -- stripped plate and the raw is the labelled one.
  select count(*) into same from public.concept_assets
   where master_sha256 = labelled_reference_sha256;
  if same > 0 then
    raise exception
      'REFUSED: % row(s) have master_sha256 equal to labelled_reference_sha256. '
      'This is a backfill that read the wrong column.', same;
  end if;

  -- And the same mistake one column over.
  select count(*) into same from public.concept_assets
   where rendition_2x_sha256 = master_sha256;
  if same > 0 then
    raise exception
      'REFUSED: % row(s) have rendition_2x_sha256 equal to master_sha256. A '
      '2x upscale cannot hash the same as what it was upscaled from.', same;
  end if;
end $$;

alter table public.concept_assets
  alter column master_sha256 set not null;

alter table public.concept_assets
  drop constraint if exists concept_assets_rendition_required;

-- NULL is reachable only where no rendition exists. Same shape as 0038's
-- anchor_book rule: the absence means something, and it cannot mean
-- "unfilled".
alter table public.concept_assets
  add constraint concept_assets_rendition_required
    check (
      (width >= 1800 and rendition_2x_sha256 is null)
      or (width < 1800 and rendition_2x_sha256 is not null)
    );

commit;

-- ------------------------------------------------------------- verification
--   select count(*) from concept_assets where master_sha256 is null;  -- 0
--   select count(*) from concept_assets
--    where width < 1800 and rendition_2x_sha256 is null;              -- 0
--
-- PROBE IT, do not trust the apply:
--   insert into concept_assets (asset_slug, master_sha256) values ('probe', null);
--   -- expect: null value in column "master_sha256" violates not-null constraint
