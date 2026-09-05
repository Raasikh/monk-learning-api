# Lesson plan cache key and invalidation

Written **before** the first precompute, deliberately. A cache whose
invalidation rules are decided after it fills is a cache nobody trusts, and the
only safe operation on it becomes "delete everything".

Companion to `migrations/0033_plan_provenance.sql`, which adds the columns this
depends on. That migration is written, **not applied**.

---

## The key

```
(concept_id,
 planner_prompt_hash,     sha256 of the three planner prompt files
 planner_code_sha,        sha256 of app/drona/planner.py
 model_id,                the literal model id passed to the API
 archetype_version,       which classification chose the widget
 chunk_corpus_version)    which book corpus grounded it
```

A plan is **valid** only if every component matches the current value. Any one
differing means regenerate. There is no partial validity and no "close enough".

### Why each component, and what breaks without it

| component | what changes when it moves | why not covered by something else |
|---|---|---|
| `concept_id` | the subject of the plan | — |
| `planner_prompt_hash` | the planner's instructions | `prompt_version` exists but hashes **all** `prompts/*.md`, so it moves when an unrelated prompt moves and stays still when `planner.py` moves. It answers the wrong question. |
| `planner_code_sha` | context assembly, retrieval call, parsing | Prompt and code change independently. A plan can be stale on either. |
| `model_id` | the generator itself | Free-text `source_model` exists but is a label, not the id passed to the API. |
| `archetype_version` | which widget a segment gets | The archetype column is the runtime widget selector. A reclassification changes what the board draws without changing a word of the plan's prose. |
| `chunk_corpus_version` | the grounding | **The reason this is on the list at all.** The corpus was fully replaced on 2026-09-04. Any plan built before that is grounded in text that no longer exists, and nothing in the row would have said so. |

`temperature` and `retrieval_config` are recorded but **not** in the key.
Temperature has been 0.0 at all three call sites since the planner was written;
if it ever changes, that is a code change and `planner_code_sha` moves with it.
Same for `top_k`. They are recorded so the claim is checkable rather than
remembered — which is the distinction this project keeps having to relearn.

---

## `chunk_corpus_version` — how it is computed

Not a timestamp. A timestamp tells you *when*, not *whether it differs*.

```
chunk_corpus_version = sha256(
    sorted( (source_file, chunk_count) for each distinct source_file )
)[:16]
```

Cheap, deterministic, and it moves when and only when the corpus does. Under the
current corpus this is a hash over eight rows — one per master book.

**What it does not catch:** an in-place edit that leaves the chunk count
identical. Accepted deliberately: the ingest replaces whole books, so counts
move. If that ever stops being true, hash the chunk ids instead, which costs a
full scan and is why it is not the default.

Compute it once per precompute run, not per plan.

**Current value, computed 2026-09-05: `b6ae8226a951b903`** over the eight
master books (1817/1257 maths, 1394/1288 physics, 1303/872 biology, 636/737
chemistry = 9,304 chunks).

---

## Invalidation strategy: lazy, with a background sweep

**Recommended, and the tradeoff is real in both directions.**

### Lazy regeneration on next request

On a request for a concept's plan, compute the current key. If the stored plan's
key matches, serve it. If not, regenerate, store, serve.

- **For:** zero wasted generation — a concept nobody teaches is never
  regenerated. Cost tracks actual usage. A prompt fix reaches the next student
  immediately rather than after a batch completes.
- **Against:** the invalidating change moves the cost to a live session. The
  first student after a prompt change pays the full planner latency — measured
  at ~24s for one outline call — inside a class that has already started. That
  is the whole reason precompute exists, undone for that student.

### Batch regeneration on change

Regenerate everything affected the moment a component moves.

- **For:** the latency stays out of live sessions entirely.
- **Against:** a one-line prompt fix costs a full corpus regeneration, most of
  it for concepts nobody will teach this month. It also makes prompt changes
  feel expensive, which quietly discourages fixing prompts — the worst possible
  second-order effect.

### The recommendation

**Lazy as the correctness mechanism; a background sweep as the latency
mechanism.**

The key check is what guarantees correctness — a stale plan can never be served,
whatever the sweep is doing. The sweep exists only to make the lazy path rarely
fire during a class:

1. Any component changes.
2. A background sweep regenerates in priority order: concepts with a scheduled
   session first, then by historical teach frequency, then the tail.
3. Meanwhile every request still checks the key. A concept the sweep has not
   reached yet regenerates lazily and the sweep skips it.

This is one mechanism with a warmer, not two mechanisms that can disagree.

**The sweep must be resumable and idempotent**, for the reason the book ingest
demonstrated: it failed twice mid-run, and only survived because each unit was
independently verifiable and re-runnable. A sweep that must complete or start
over will, eventually, do neither.

---

## What must NOT happen

**No silent fallback to a stale plan.** If regeneration fails, the request fails
or falls through to live generation — it does not quietly serve a plan built on
a corpus that no longer exists. This project has now had five defects of exactly
that shape: a check that passes on absent information (`prompt_version` not
covering the planner; `grounded` always true; `topic_hash` never populated;
`page_start` hardcoded to 1; six docs cited that were never written). A stale
plan served silently would be the sixth.

**No writing a plan without full provenance.** `0033` enforces this with NOT
NULL on three of the columns, so it is a constraint rather than a convention.

**No treating `unknown-pre-0033` as valid.** The 20 existing rows carry that
marker because their real provenance is not recoverable. They must be
regenerated before they are trusted, not grandfathered.

---

## Open question, flagged not answered

`archetype_version` has no value yet. The archetype column was reclassified on
2026-09-04 **against the old corpus**, which was replaced hours later. Those
verdicts were read from chunks that no longer exist.

Before it can be a cache-key component it needs a version identifier and a
re-run against the current corpus. Until then, precomputes should record
`archetype_version = 'unversioned-2026-09-04'` so the rows are at least
identifiable, and the first thing that happens when the classification is
re-run is that they all invalidate — which is the correct outcome.
