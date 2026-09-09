-- 0040_concept_assets_master_sha256.sql
--
-- WRITTEN, NOT APPLIED. Apply by hand in the Supabase SQL editor after review.
--
-- THE HASHES OF THE FILES A BOARD ACTUALLY FETCHES.
-- =================================================
-- `labelled_reference_sha256` is the RAW plate's hash — the labelled reference
-- kept for provenance and never uploaded. Neither object a board fetches has
-- had a hash recorded anywhere in this database since 0035: not the master,
-- and not the @2x rendition derived from it.
--
-- That absence has already caused one defect and now blocks a feature:
--
--   * the ingest's content-hash skip compared `existing["sha256"]` to the
--     row's — both `None`, always equal — so it would have skipped every row
--     for ever. It was rewritten to compare R2's ETag instead, which works but
--     asks the network a question the row should have been able to answer.
--
--   * the client caches downloaded art under `<asset_slug>.<sha256[:12]>.png`
--     and verifies the bytes against the recorded hash. Without one there is
--     no version to key on and no way to tell a truncated file from a
--     DIFFERENT file of the same length. `bytes` cannot do either job.
--
-- NAMED `master_sha256`, NOT `sha256`. Three hashes now live on this row and
-- two of them are 64 hex characters of the same shape; a column called plain
-- `sha256` beside `labelled_reference_sha256` invites exactly the confusion
-- 0041 has to write a query to catch.
--
-- `rendition_2x_sha256` IS NULL FOR A WIDE MASTER, AND THAT IS A STATEMENT.
-- `make_rendition` produces nothing at or above 1800 px, because the widest
-- request the client can make is 900pt at 2x — so a master that wide is never
-- asked for a rendition and none exists to hash. The CHECK below makes NULL
-- reachable ONLY in that case, the same way 0038 made a NULL `anchor_book`
-- mean "generated, so there is no anchor plate" rather than "nobody filled it
-- in". A narrow master with a NULL rendition hash is still refused.
--
-- Both are nullable HERE and only here: this file cannot compute them, since
-- the bytes live in R2. The ingest backfills every row on its next
-- `--execute` (idempotent, and it already reads both files). 0041 then closes
-- the window.

begin;

alter table public.concept_assets
  add column if not exists master_sha256 text;

alter table public.concept_assets
  add column if not exists rendition_2x_sha256 text;

comment on column public.concept_assets.master_sha256 is
  'SHA-256 of the MASTER object at r2_key, lowercase hex. Distinct from '
  'labelled_reference_sha256, which hashes the raw labelled plate that is '
  'recorded for provenance and never uploaded.';

comment on column public.concept_assets.rendition_2x_sha256 is
  'SHA-256 of the @2x rendition beside r2_key. NULL when width >= 1800, '
  'because no rendition is produced for a master that wide — see 0040.';

alter table public.concept_assets
  drop constraint if exists concept_assets_master_sha256_shape;
alter table public.concept_assets
  drop constraint if exists concept_assets_rendition_sha256_shape;

-- Shape, not presence: NULL is admitted until 0041, but a value that is
-- present must be a real hash. 'unknown', '' and a truncated paste are the
-- three things that would otherwise arrive here, and each would silently
-- become a cache key and a verification target.
alter table public.concept_assets
  add constraint concept_assets_master_sha256_shape
    check (master_sha256 is null or master_sha256 ~ '^[0-9a-f]{64}$');

alter table public.concept_assets
  add constraint concept_assets_rendition_sha256_shape
    check (rendition_2x_sha256 is null or rendition_2x_sha256 ~ '^[0-9a-f]{64}$');

commit;

-- ------------------------------------------------------------- verification
--   select count(*) filter (where master_sha256 is null)       as no_master,
--          count(*) filter (where rendition_2x_sha256 is null) as no_rendition,
--          count(*) filter (where width >= 1800)               as wide,
--          count(*)                                            as rows
--     from concept_assets;
--   -- before the ingest re-run: no_master = rows
--   -- after:  no_master = 0, and no_rendition = wide (currently 1, the frog
--   --         heart at 1800x1240)
--
-- WHAT IS STILL REFUSED, and must stay refused:
--   master_sha256 'unknown' / '' / uppercase hex     not the canonical shape
--   master_sha256 = labelled_reference_sha256        NOT refused here and
--     cannot be: they are the same shape, and only equality across the whole
--     table separates them. 0041 is what catches that backfill.
