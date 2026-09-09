-- 0040_concept_assets_master_sha256.sql
--
-- WRITTEN, NOT APPLIED. Apply by hand in the Supabase SQL editor after review.
--
-- THE MASTER'S OWN HASH, WHICH THIS TABLE HAS NEVER HAD.
-- =====================================================
-- `labelled_reference_sha256` is the RAW file's hash — the labelled reference
-- kept for provenance and never uploaded. The master, which is the object a
-- board actually fetches, has had no hash recorded anywhere in the database
-- since 0035.
--
-- That absence has already caused one defect and now blocks a feature:
--
--   * the ingest's content-hash skip compared `existing["sha256"]` to the
--     row's — both `None`, always equal — so it would have skipped every row
--     for ever. It was rewritten to compare R2's ETag instead, which works but
--     asks the network a question the row should have been able to answer.
--
--   * the client caches downloaded art under `<asset_slug>.<sha256[:12]>.png`
--     so that new art for an existing slug invalidates the old file. Without a
--     hash in the row there is no version to key on, and `bytes` is not one:
--     two different plates can be the same length.
--
-- NULLABLE ON PURPOSE, FOR ONE MIGRATION ONLY. The 113 existing rows have no
-- value and this file cannot compute one — the bytes live in R2, not in
-- Postgres. So: add it nullable here, let `ingest_asset.py` backfill every row
-- on its next `--execute` (it is idempotent and already reads the file), then
-- apply 0041, which refuses to run while any row is still NULL and then makes
-- it NOT NULL. A column that is nullable for ever is a column that is
-- sometimes filled in, which is the state `syllabus_gap` documents the cost of.

begin;

alter table public.concept_assets
  add column if not exists sha256 text;

comment on column public.concept_assets.sha256 is
  'SHA-256 of the MASTER object at r2_key, lowercase hex. Distinct from '
  'labelled_reference_sha256, which hashes the raw labelled plate that is '
  'recorded for provenance and never uploaded.';

alter table public.concept_assets
  drop constraint if exists concept_assets_sha256_shape;

-- Shape, not presence: NULL is admitted until 0041, but a value that is
-- present must be a real hash. "unknown", "" and a truncated paste are the
-- three things that would otherwise arrive here and each would silently
-- become a cache key.
alter table public.concept_assets
  add constraint concept_assets_sha256_shape
    check (sha256 is null or sha256 ~ '^[0-9a-f]{64}$');

commit;

-- ------------------------------------------------------------- verification
--   select count(*) filter (where sha256 is null) as unbackfilled,
--          count(*) as rows
--     from concept_assets;
--   -- expect unbackfilled = rows before the ingest re-run, 0 after it
--
-- WHAT IS STILL REFUSED, and must stay refused:
--   sha256 'unknown'                     not hex
--   sha256 ''                            not hex
--   sha256 '410118D439C4158F...'         uppercase; one canonical form only
--   sha256 <the labelled_reference one>  not refused here and cannot be —
--     they are the same shape. 0041's verification query is what catches a
--     backfill that copied the wrong column, by comparing the two.
