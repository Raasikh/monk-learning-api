# Pre-ingest checklist

> **STATUS 2026-09-04: the ingest has HAPPENED.** All eight master books are in
> (9,304 chunks, 106 chapters, legacy corpus fully replaced). Item 1 is now
> OVERDUE rather than pending — measured at 3,164 ms per live turn, up from
> 1,088 ms before the ingest. Items 2 and 3 are DONE.

Things that must be true **before** the 1,000-page books are ingested, because
each one is cheap now and expensive or impossible afterwards.

> This file was CREATED on 2026-09-04, not appended to. It was referenced as an
> existing checklist; it did not exist in any of the three repos. That is the
> same shape as the six docs `lib/widgets/CLAUDE.md` cited and never had, so it
> is written down here rather than assumed again.

Every item below is **measured**, with the measurement recorded. Nothing on this
list is a hunch.

---

## 1. `match_pdf_chunks` RPC + HNSW index — OVERDUE, APPLY NOW

**Re-measured after the ingest**, largest chapter (mathematics 11 Trigonometry,
233 chunks): **3,164 ms and 5.0 MB per live turn**, against 1,088 ms / 2.24 MB
before. The corpus got better and retrieval got 3x slower, exactly as predicted.
This is no longer a forecast — it is the current production latency.

Applying requires a direct Postgres connection. The repo has PostgREST
credentials only, which cannot run DDL, so this must be applied by hand in the
Supabase SQL editor.

**Migration:** `migrations/0032_match_pdf_chunks_rpc.sql` — written, **not applied**.
Apply it *with* the ingest.

`app/drona/retrieval.py` calls an RPC named `match_pdf_chunks` and, when it is
absent, falls back to fetching **every chunk in the chapter including its
1536-dimension embedding** and cosining them in Python. That RPC has never
existed in this database, so **the fallback is the production path on every
live turn**, and it raises no error while doing it.

Measured 2026-09-04, largest chapter today (mathematics 12, Three Dimensional
Geometry, 104 chunks):

| | |
|---|---|
| fetch (network + JSON) | **1062 ms** |
| cosine (in-process) | 26 ms |
| **total per retrieval** | **1088 ms** |
| payload transferred | **2.24 MB** |

The cost is the transfer, not the arithmetic — roughly 21 KB per chunk, and it
scales linearly with chunks per chapter:

| chunks/chapter | per live turn | payload |
|---|---|---|
| 47 (today's median) | ~0.5 s | ~1.0 MB |
| 1 000 | ~10.5 s | 21.5 MB |
| 3 000 | ~31.4 s | 64.6 MB |
| 5 000 | ~52.3 s | 107.6 MB |

**The first-run wait gets worse the day the content gets better.** That is the
kind of regression that reads as a mystery in production.

**Verify after applying:** `retrieval.py` logs `[VECTOR RPC MATCH]` on success
and `[VECTOR RPC FALLBACK]` otherwise. The fallback raises no error, so absence
of errors is not evidence. Grep for `VECTOR RPC MATCH`.

---

## 2. `page_start` / `page_end` — FIXED 2026-09-04

**RESOLVED.** After the master-book ingest: **1,200 distinct `page_start`
values, spanning pages 6 to 1211.** Real page spans, taken from the PDF outline.

The original defect, for the record:
**all 5 266 rows had `page_start = page_end = 1`.**
100% non-null, 100% information-free. `scripts/ingest_pdf_chunks.py:209-210`
hardcodes both to `1`.

A `NOT NULL` constraint passes on this data. A completeness check passes. The
column is a constant, so any feature built on it — citation, "see page N",
jumping to source, narrowing retrieval to a page range — silently returns page
1 for everything.

This is the same failure shape as `prompt_version`, `grounded`, `topic_hash`
and the phantom docs: **a field that looks populated and asserts nothing.**
Fix it in the ingest script before the books land, because backfilling real
page numbers for 5 266 existing rows means re-running extraction anyway — and
after ingest that is a much larger number.

**Check that would have caught it, and should be in CI:**
`select count(distinct page_start) from pdf_chunks;` — if that is 1 across a
whole corpus, the column is decorative.

---

## 3. Chapters with no chunks — RESOLVED except one, by design

**Now 106 of 107.** `chemistry 11 ch8` (General Organic Chemistry) gained 39
chunks, which unblocks the 11 concepts marked `build_class=review`,
`reason=no_chunks` — they can now be reclassified from content.

The one remaining is `mathematics 11 ch0: Basic Mathematics`, which has **no
corresponding chapter in any book** and had no chunks before either, so nothing
was lost. It needs either book content or removal from `chapters`.

Original measurement:
**105 of 107 chapters have chunks.** The two that do not
include **chemistry 11 ch8** (Organic Chemistry: Some Basic Principles and
Techniques), which alone accounts for 11 concepts that could not be
reclassified from content and are marked `build_class=review`,
`reason=no_chunks` in `content/concept-archetypes.csv`.

Confirm all 107 have chunks post-ingest, and re-run the reclassification for
any chapter that gains them.

---

## The general rule these share

Each item is a check that **passes on absent information**: an RPC whose
absence triggers a silent fallback, a column whose constant value satisfies
every null check, a chapter whose emptiness looks like a concept simply not
matching. Prefer assertions that fail loudly on missing data over assertions
that succeed on a placeholder.


---

## 4. Index and constraint discovery — a lesson from this ingest

The ingest failed twice before succeeding, both times on schema the PostgREST
schema does not expose:

1. `chunk_index` is NOT NULL. Caught by reading the OpenAPI `required` list.
2. `pdf_chunks_dedupe_idx` is **UNIQUE(source_file, chunk_index)**. NOT visible
   in the OpenAPI schema at all — indexes are not part of it. It encodes an
   assumption from the legacy corpus, that `source_file` identifies a chapter.
   The master books are one file per BOOK, so a per-chapter `chunk_index`
   collided the moment chapter 2 started counting from zero.

**Before any future bulk write, enumerate indexes and constraints, not just
columns.** `select indexname, indexdef from pg_indexes where tablename = '...'`
and the equivalent for constraints. A column-level check is not a schema check.

Also: never pipe a migration or ingest through `tail`. The first failure
reported exit code 0 because the shell returned `tail`'s status while Python had
crashed. Redirect to a file and check the real exit code.
