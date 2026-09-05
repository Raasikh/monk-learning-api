-- 0034_chunk_section_and_provenance.sql
--
-- WRITTEN, NOT APPLIED. Apply by hand in the Supabase SQL editor after review.
-- Additive and safe to apply while the corpus is being rebuilt: the ingest
-- writes these columns when they exist and omits them when they do not.
--
-- TWO THINGS, BOTH MEASURED
-- =========================
--
-- 1. section_key -- the fix for the retrieval finding that mattered most.
--
--    Measured 2026-09-05 over 30 concepts through the real RPC path:
--
--      concept OWNS a book section    14 concepts   6.79/8 relevant   top-1 100%
--      concept SHARES one w/ sibling  16 concepts   3.56/8            top-1  44%
--
--    Chapter size is NOT the variable -- r(chunk count, relevance) = +0.048,
--    and the two groups had near-identical chapter sizes (102 vs 105 chunks).
--    Retrieval cannot separate what the source never separated. So the section
--    a chunk came from has to be RECORDED rather than inferred from an
--    embedded heading string.
--
--    It is also what lets the planner be told what a section covers that this
--    concept does NOT, which is the exclusion mechanism for sibling bleed.
--
-- 2. Chunk provenance. chunk_corpus_version in the plan cache key
--    (docs/plan-invalidation.md) is currently derived from (source_file,
--    count) pairs, which cannot tell a PyMuPDF corpus from a Mathpix one --
--    and those differ in every equation. After this migration it can.

begin;

alter table public.pdf_chunks
  -- e.g. 'ch1:section-3-key-procedures-frameworks'. Stable within a book
  -- edition; changes when the book is re-authored, which is correct because
  -- that is a different section.
  add column if not exists section_key text,

  -- The heading text as printed, for prompts and for debugging a bad
  -- section_key without re-reading the PDF.
  add column if not exists section_title text,

  -- 'mathpix' | 'pymupdf'. Not a boolean: there will be a third one day, and
  -- a boolean named is_mathpix would then be a lie rather than a gap.
  add column if not exists extractor text,

  -- sha256 of the ingest script, first 12 hex. Two corpora extracted by the
  -- same service and different chunkers are different corpora.
  add column if not exists ingest_script_sha text,

  add column if not exists ingested_on date;

-- Retrieval filters by chapter first and would filter by section next.
create index if not exists pdf_chunks_section_key_idx
  on public.pdf_chunks (chapter_id, section_key);

commit;

-- ------------------------------------------------------------- verification
-- Every one of these should hold after the Mathpix re-ingest completes.
--
--   -- no chunk should lack a section, and none should claim one it cannot have
--   select count(*) from pdf_chunks where extractor = 'mathpix' and section_key is null;
--
--   -- sections per chapter: a chapter with exactly 1 is a chapter where the
--   -- book never sectioned, and is the population the 44% top-1 rate lives in
--   select chapter_id, count(distinct section_key) as sections
--     from pdf_chunks group by 1 having count(distinct section_key) <= 1;
--
--   -- the corpus must not silently become a mixture of two extractors
--   select extractor, count(*) from pdf_chunks group by 1;
--
-- DELIBERATELY NOT NULL-CONSTRAINED. Unlike 0033's provenance columns, these
-- describe how a row was PRODUCED rather than whether it can be trusted, and
-- the corpus is mid-migration: a NOT NULL here would block the very ingest
-- that populates it. Add the constraint once one extractor owns every row.
