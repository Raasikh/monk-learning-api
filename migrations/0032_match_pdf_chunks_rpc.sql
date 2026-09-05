-- 0032_match_pdf_chunks_rpc.sql
--
-- ============================================================================
-- RETRACTED 2026-09-04. DO NOT APPLY AS WRITTEN.
-- ============================================================================
--
-- This migration was written on a false premise. I probed for the RPC with the
-- parameter name `chapter_id_filter`; app/drona/retrieval.py actually calls it
-- with `filter_chapter_id`. PostgREST resolves overloads by argument NAME, so
-- my probe reported "Could not find the function" for a function that exists
-- and works. Everything downstream of that -- "the fallback IS the production
-- path", the 1088ms and 3164ms figures, "PRE-INGEST BLOCKER" -- was wrong.
--
-- WHAT IS ACTUALLY TRUE, measured 2026-09-04 after the master-book ingest:
--
--   baseline round-trip (trivial query)              324 ms   <- network floor
--   RPC, largest chapter (233 chunks), match_count=1 321 ms
--   RPC, largest chapter (233 chunks), match_count=12 361 ms
--   RPC, smallest chapter (34 chunks), match_count=12 318 ms
--
-- The vector search is FREE. 233 chunks vs 34 chunks costs 43ms. Latency is
-- network round-trip plus payload size (match_count=50 costs 892ms because it
-- returns 50 chunks of content text, not because the search is slow).
--
-- So an HNSW index would buy approximately nothing, and on a query already
-- filtered to one chapter's ~80 rows the planner would likely not use it.
-- The 1088/3164 ms numbers were measurements of the FALLBACK, which production
-- does not take.
--
-- THE ONE THING STILL WORTH DOING, and it is not urgent:
-- the live function's return type omits page_start and page_end. Those were
-- meaningless before (every row was page 1) and are meaningful now (1,200
-- distinct values, pages 6-1211). Adding them would let Drona cite a page.
-- That requires DROP + CREATE, which is a real risk to a working production
-- function, so do it WITH an app change that uses them -- not speculatively.
-- The DROP-and-recreate form is kept below for that day.
--
-- Original (wrong) rationale follows, kept so the error is legible.
-- ============================================================================
--
--
-- PRE-INGEST BLOCKER. Apply WITH the 1,000-page book ingest, not before, not after.
--
-- WHY THIS IS URGENT RATHER THAN TIDY
--
-- app/drona/retrieval.py already calls an RPC named match_pdf_chunks and falls
-- back, silently, to fetching EVERY chunk in the chapter (embeddings included)
-- and cosining them in Python. That RPC has never existed in this database, so
-- the fallback IS the production path on every live turn.
--
-- Measured 2026-09-04 against the largest chapter today
-- (mathematics 12, Three Dimensional Geometry, 104 chunks):
--
--     fetch (network + JSON)   1062 ms      <- the cost is the transfer
--     cosine (in-process)        26 ms
--     TOTAL per retrieval      1088 ms      2.24 MB transferred
--
-- The bottleneck is shipping 1536-dimension embeddings over the wire as JSON
-- text, about 21 KB per chunk. It scales linearly with chunks-per-chapter:
--
--     1000 chunks/chapter   ~10.5 s    21.5 MB   per live turn
--     3000 chunks/chapter   ~31.4 s    64.6 MB   per live turn
--     5000 chunks/chapter   ~52.3 s   107.6 MB   per live turn
--
-- Today's chapters median 47 chunks, so the fallback is survivable. The
-- 1,000-page books take chapters to several thousand. Without this migration
-- the first-run wait gets WORSE the day the content gets BETTER, which is the
-- kind of regression that looks like a mystery in production.
--
-- This function returns top_k rows and does NOT return the embedding column,
-- so the wire payload stops scaling with chapter size altogether.

-- ---------------------------------------------------------------- extension
-- Guarded: applying this file as-is will FAIL on the existing function with
-- "cannot change return type of existing function". That is intentional --
-- see the retraction above. To adopt the page-number version deliberately,
-- uncomment the drop.
-- drop function if exists public.match_pdf_chunks(vector, uuid, integer);

create extension if not exists vector;

-- ------------------------------------------------------------------- index
-- pdf_chunks.embedding is already public.vector(1536) — verified against the
-- PostgREST schema — so this is an index, not a type change.
--
-- HNSW over IVFFlat, deliberately:
--   * IVFFlat needs its lists tuned to row count AND needs REINDEXing as the
--     table grows. Ingest changes the row count by orders of magnitude, which
--     is exactly the case IVFFlat handles worst.
--   * HNSW builds without knowing the final size and does not need retuning.
--   * HNSW costs more to build and more memory. That is the right trade for a
--     read-heavy table written once per ingest.
--
-- vector_cosine_ops matches retrieval.py's cosine similarity. Using l2 here
-- while the code computes cosine would silently return the wrong neighbours,
-- so the operator class and the query operator (<=>) must agree.
create index if not exists pdf_chunks_embedding_hnsw
  on public.pdf_chunks
  using hnsw (embedding vector_cosine_ops);

-- Chapter filter runs before the vector scan on a small result set.
create index if not exists pdf_chunks_chapter_id_idx
  on public.pdf_chunks (chapter_id);

-- ---------------------------------------------------------------------- rpc
-- Signature matches what app/drona/retrieval.py ALREADY calls, exactly:
--   supabase.rpc("match_pdf_chunks", {
--       "query_embedding": ..., "filter_chapter_id": ..., "match_count": ...
--   })
-- The parameter names are part of the contract — PostgREST resolves the
-- overload by argument NAME, so renaming any of them re-breaks the call and
-- sends production back to the fallback without any error being raised.
--
-- The returned column set matches the fallback's select list so the two paths
-- are interchangeable to the caller, MINUS `embedding`, which is the entire
-- point.
create or replace function public.match_pdf_chunks(
  query_embedding   vector(1536),
  filter_chapter_id uuid,
  match_count       int default 12
)
returns table (
  id           uuid,
  chapter_id   uuid,
  content      text,
  source_file  text,
  chunk_index  int,
  page_start   smallint,
  page_end     smallint,
  similarity   float
)
language sql
stable
parallel safe
as $$
  select
    c.id,
    c.chapter_id,
    c.content,
    c.source_file,
    c.chunk_index,
    c.page_start,
    c.page_end,
    -- <=> is cosine DISTANCE; similarity is 1 - distance, matching the
    -- cosine_similarity() the fallback computes in Python.
    1 - (c.embedding <=> query_embedding) as similarity
  from public.pdf_chunks c
  where c.chapter_id = filter_chapter_id
    and c.embedding is not null
  order by c.embedding <=> query_embedding
  limit greatest(1, least(match_count, 100));
$$;

comment on function public.match_pdf_chunks is
  'Top-k pdf_chunks for a chapter by cosine similarity. Returns no embedding column, so the wire payload does not scale with chapter size. Param NAMES are a contract with app/drona/retrieval.py.';

-- --------------------------------------------------------------- verification
-- After applying, confirm the RPC is actually being taken. retrieval.py logs
-- "[VECTOR RPC MATCH]" on success and "[VECTOR RPC FALLBACK]" otherwise, and
-- the fallback path raises NO error — so absence of errors is not evidence.
-- Grep the logs for VECTOR RPC MATCH before believing this landed.
