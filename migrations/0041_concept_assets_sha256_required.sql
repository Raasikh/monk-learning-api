-- 0041_concept_assets_sha256_required.sql
--
-- WRITTEN, NOT APPLIED. Apply AFTER 0040 and after `ingest_asset.py --execute`
-- has backfilled every row.
--
-- Closes the window 0040 opened. A column that is nullable for ever is a
-- column that is sometimes filled in, and "sometimes" is exactly what makes a
-- cache key untrustworthy: the client cannot tell "this asset has no version"
-- from "nobody backfilled this one".

begin;

do $$
declare n int; same int;
begin
  select count(*) into n from public.concept_assets where sha256 is null;
  if n > 0 then
    raise exception
      'REFUSED: % row(s) still have a NULL sha256. Run '
      'scripts/ingest_asset.py ingest --execute first; it is idempotent and '
      'backfills every row from the file it already reads.', n;
  end if;

  -- The backfill that would look right and be wrong: copying the RAW hash.
  -- The two are the same shape, so no CHECK can separate them; only equality
  -- across the whole table can, and it must be zero for every row where the
  -- master and the raw genuinely differ (which is all of them — the master is
  -- the stripped plate).
  select count(*) into same from public.concept_assets
   where sha256 = labelled_reference_sha256;
  if same > 0 then
    raise exception
      'REFUSED: % row(s) have sha256 equal to labelled_reference_sha256. The '
      'master is the stripped plate and the raw is the labelled one; they '
      'cannot hash the same. This is a backfill that read the wrong column.',
      same;
  end if;
end $$;

alter table public.concept_assets
  alter column sha256 set not null;

commit;

-- ------------------------------------------------------------- verification
--   select count(*) from concept_assets where sha256 is null;  -- 0, enforced
