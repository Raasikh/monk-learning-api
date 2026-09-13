# Directive: materialise the non-figure question pool

**Read this whole document first.** It is self-contained — it does not assume you
remember previous sessions. Every number below was measured independently against the
files on disk and the live database, not taken from a prior report.

This directive changes priority. The diagram work is not abandoned, but it moves to
second place, and §6 explains why.

---

## 1. The situation

`monk-learning-api` serves JEE/NEET practice questions from a Supabase `questions` table
(**15,408 rows live**, 80 with diagrams). A long effort extracted *diagram questions* into
a raw staging layer. That effort is largely complete and its current state is:

- 4,232 rows, 668 with vision-verified figures, 119 with 2-of-2 solver-verified keys
- **`servable_now: 0`**
- binding constraints: metadata (903 rows), solutions (562), and client-side support for
  image-carried options that does not exist yet

Meanwhile, the same extraction wrote **full paper artifacts** to `data/nta_raw/papers/*.json`
— every question from every scraped paper, not just the ones with figures. That pool was
never materialised because materialisation required a figure.

**It contains a large, clean, already-keyed set of ordinary questions that need no figure
attribution work at all.** Attribution is the problem that has consumed this project;
these rows sidestep it entirely.

---

## 2. The pool, measured

```
paper artifact files                          :    797
total questions in them                       : 16,504
  with 4+ non-empty options                   : 11,303
  with a usable A–D embedded key              :  9,325
  with Symbol-font PUA corruption             :     39   ← text quality is clean

CLEAN (4 options + usable key + ≥20 chars + no PUA)
                                              :  7,035
  minus 1,387 internal duplicates             :  5,648 distinct
  minus 535 already in the live table (7.6%)  :  5,414 NET NEW
```

**5,414 net-new questions against a 15,408-row live bank — a ~35% expansion.**

Health signals:

- **Key spread A 26.6% / B 26.7% / C 24.8% / D 21.9%** — a plausible answer key. (This
  matters: an earlier extraction bug produced 90% "B" keys, and distribution was how it
  was caught.)
- `question_type`: 6,851 `single_correct`, 184 unset
- 344 papers represented
- Only 39 rows corpus-wide carry PUA mojibake

Known defects already visible in the pool — these are the **same classes already solved**
for the diagram corpus, so reuse the existing scripts rather than writing new ones:

| defect | rows | existing fix |
|---|---:|---|
| answer/solution text leaked into an option value | **677** | truncate at leak marker, `scripts/repair_directive4_pass1.py` |
| an option longer than 300 chars | 533 | same — usually a parse that swallowed the next block |
| `subject` unset | **4,138 (59%)** | classification pass |

---

## 3. The work

### 3.1 Materialise without the figure requirement

Re-materialise from `data/nta_raw/papers/*.json` into a new raw file (suggest
`data/nta_raw/nonfigure_questions.jsonl`) applying the clean filter in §2. **Do not touch
the existing diagram JSONL files.**

Every row carries `needs_manual: "pending_gate"` and full provenance: source paper id,
qno, page, PDF URL, source tier.

**These rows have no figure and must never be given one.** The figure-attachment logic
exists for diagram rows only. A non-figure question with a figure attached is the exact
defect that cost this project weeks.

### 3.2 Apply the deterministic repairs that already exist

Run the existing repair passes over the new file — the option-leak truncation, the
>300-char option check, the duplicate-option sweep, the minus-sign/fraction-bar scan.
These are solved problems; do not re-derive them.

Then enforce the eligibility rule already implemented in
`scripts/enforce_pending_gate_eligibility.py`: **a row may only hold
`needs_manual='pending_gate'` if it could in principle pass `is_quality_question()`** —
4 non-empty options, or numerical with a `correct_value`. Anything else gets a specific
quarantine reason. Otherwise `pending_gate` becomes a bucket of rows that look in-play
and are not.

### 3.3 Deduplicate — internally and against the live bank

1,387 internal duplicates and 535 rows already live. Dedupe by normalised text
fingerprint (strip LaTeX, punctuation, lowercase). For live matches set
`needs_manual: "duplicate_of_servable:<existing_id>"`. **Never modify or delete the
existing live row.**

### 3.4 Verify the keys — this is the gating step

The embedded keys are **mirror-printed and unverified**. Two independent audits of the
equivalent keys in the diagram corpus measured **89% accuracy**. At that rate, expect
**roughly 600 wrong keys** among 5,414.

A wrong key tells a student they are right when they are wrong, and corrupts their
mastery score on the way through. It is worse than a missing question.

Use the pipeline you have already proven: **two independent blind solves** per question,
solvers seeing stem and options but never the key, **promote only on 2-of-2 agreement that
also matches the stated key**, everything else `key_disputed`. No third-call tie-breaks.

**Seed known-good controls unlabelled into every batch and report control recovery
separately from the headline rate.** A key-agreement number without a control rate cannot
be interpreted — it cannot distinguish "the keys are good" from "the solver is weak". Your
last run's 16/16 control recovery is what made its ~4% wrong-key harvest believable.

5,414 questions × 2 solves is a large run. Batch it, report per batch, and state plainly
if you cap or sample rather than covering everything.

### 3.5 Attach metadata

The current binding constraint on the diagram corpus is metadata, and it will bind here
too. Each row needs:

- `chapter_name` + `chapter_id` — **must match an existing row in the live `chapters`
  table.** Never invent a chapter name; that table is read by 15+ call sites across
  practice selection and the live tutor, so a new or renamed chapter has blast radius
  beyond this task. If a question maps to no existing chapter, quarantine it.
- `concept` — must exist in the live `concepts` taxonomy, or the row contributes nothing
  to mastery scoring
- `difficulty` 1–3
- `subject` — 4,138 rows have none
- `solution` as `{"steps": [...]}` and `explanations` as `{"en": "..."}`

---

## 4. Target schema

| column | requirement |
|---|---|
| `question_text` | ≥20 chars, no mojibake, no answer or solution text embedded |
| `options` | `{"A":…,"B":…,"C":…,"D":…}`, 4 non-empty |
| `question_type` | `single_correct` \| `numerical` \| `match_the_following` |
| `correct_option` | `A`–`D` when not numerical |
| `correct_value` | required when `numerical`; `options` must then be **null** |
| `solution` | `{"steps":[…]}` |
| `chapter_name` / `chapter_id` | must match live `chapters` |
| `concept` | must exist in live `concepts` |
| `difficulty` | 1–3 |
| `diagram` | **null for every row in this pool** |
| `needs_manual` | null = servable; any string quarantines |

A `numerical` row with 4 options and a letter key renders with **no options at all** in
the client. That defect already had to be repaired 52 times in production. If a row has
A–D options and a letter answer it is `single_correct`, never `numerical`.

Output conventions the client parses: `$…$` / `$$…$$` math, mhchem `\ce{}` for chemistry,
real markdown tables with separator rows, options keyed `A`–`D` regardless of whether the
source printed `(1)`–`(4)` — **grading compares the option key, not its display text.**

---

## 5. Standing rules

- **Never write to the `questions` table.** Raw layer only, everything `pending_gate`
  until a human approves.
- **Never modify the `chapters` table.**
- **Never fabricate.** Garbled stem, unreadable option, uncertain key → `needs_manual`
  with a specific reason. A quarantined row costs nothing; a fabricated one poisons a
  student's practice.
- **Never attach a figure to a row in this pool.**
- **Preserve provenance** on every row.
- Take backups before any destructive pass, as you did with
  `backups/*_directive4_*.jsonl`.

---

## 6. Why this comes first, and what happens to the diagram work

The diagram corpus needs the same metadata and solution work this pool needs. The
difference is what else it needs:

| | non-figure pool | diagram corpus |
|---|---:|---:|
| net-new questions | **5,414** | 668 |
| figure attribution required | none | done, ~3% residual error, same-subject blind spot measured at 0/6 |
| client support needed | none | image-carried options not yet supported |
| currently servable | 0 | 0 |

Both are at zero today. One is eight times larger and carries none of the risk.

**The diagram rows are not cancelled.** They become the second tranche: once the metadata
and key pipelines are running on the larger pool, the same passes apply to the 668. Keep
their current state intact.

---

## 7. Reporting

- **A cumulative funnel, gate by gate**, so the binding constraint stays visible:
  `raw → text≥20 → question_type → options → dedupe → key → key_verified → metadata → solution → servable`.
  A total without per-gate attribution hides which single field is costing thousands of
  rows — that is how a missing `question_type` blocked 8,637 rows unnoticed for six rounds.
- **Key accuracy with control recovery stated separately.**
- **Per-class counts before and after** for every repair.
- **Anything capped, sampled, or skipped.** Silent truncation reads as full coverage.
- **Build controls into your own gates.** Every audit run on this project so far has found
  something a prior report marked closed, and in each case the check had been run by the
  process that made the change. Seeded controls — known-good rows in a key pass, scrambled
  pairs in a vision gate — cost almost nothing and turn a gate's self-report into a
  measurement. Your last round's 6/12 three-way control result is exactly the right
  instinct: a blind spot measured and disclosed rather than smoothed over.
