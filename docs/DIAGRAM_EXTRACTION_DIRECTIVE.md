# Directive: diagram-question extraction to production standard

You have already extracted 16,211 raw diagram questions into `data/nta_raw/*.jsonl`.
An independent audit of that output found the **diagram/OCR layer is good** and the
**text/answer/metadata layer is not shippable**. This directive tells you exactly
what to fix, what the target schema is, and how you must *prove* the work is correct.

Read all of it before changing anything.

---

## 0. What is already good — do not regress it

Measured across all 16,211 rows:

- 13,028 diagram assets, **0 unresolvable paths**, all with `sha256`, width, height, mime.
- Median crop 211×137 px — correctly-scoped diagram regions, not full-page dumps.
- Mathpix status `ok` on 12,974/12,974 attempted, median confidence 0.9796.
- Provenance is complete: source page, PDF URL, source tier, exam, year, paper_id.

**Keep the Mathpix + bbox-crop approach exactly as it is.** It is the strongest part
of the pipeline. Everything below is about the text extracted *around* the diagram.

Two known blemishes to fix while you are in there:

- 2,616 rows have OCR confidence < 0.90 (minimum observed: 0.0000). **Do not use this as
  an exclusion filter.** Mathpix's `confidence_rate` is an estimated fraction of elements
  recognized, and it correlates poorly with whether the text is actually usable — 146 of
  the 222 rows scoring exactly 0.0 carry substantial, clean OCR text. Treat low confidence
  as a weak signal for prioritising review, never as grounds for dropping a row. (Note:
  `app/mathpix.py` does gate on `MIN_CONFIDENCE_RATE = 0.90`, but that governs whether a
  *live doubt photo* is worth solving from — a different decision from whether an already-
  extracted corpus row is worth keeping. `confidence: null` means not measured, and the
  code deliberately treats that as usable.)
- 348 crops are smaller than 60×40 px. A crop that small is almost certainly a stray
  rule, a subscript, or punctuation — not a figure. Re-check or drop them.

---

## 1. The bugs you must fix, with the evidence

### 1.1 The letter-format answer-key parser is producing garbage — HIGHEST PRIORITY

Answer keys in your output split into two extraction paths. Their letter distributions:

| raw format | n | A | B | C | D | verdict |
|---|---|---|---|---|---|---|
| numeric (`"2"` → B) | 844 | 25% | 29% | 22% | 24% | plausible |
| letter (`"B"` → B) | 696 | 4% | **90%** | 2% | 2% | **broken** |

A real answer key is approximately uniform. A path emitting 90% "B" is not reading the
answer — it is matching something else on the page (most likely a literal "B" from
option text, a booklet code, a section header, or a bold marker) and calling it the key.

**That is 629 questions that would be marked wrong for every student who answers them
correctly.** This is the single most damaging defect in the corpus.

Independent corroboration: 13 groups of duplicate question text carry *contradicting*
keys across copies (e.g. the same capacitor question keyed both `B` and `D`). A correct
extractor cannot disagree with itself on identical input.

**ROOT CAUSE — confirmed and reproduced (2026-09-11).** The bug is in
`EMBEDDED_ANSWER_VALUE_RE`, `scripts/extract_nta_papers.py:1086`:

```python
r"(?i)\b(?:Official\s+Ans(?:\.|\s+by\s+NTA)?|Answer|Ans)"
r"\s*(?:[.:\)]|\()\s*\(?\s*([A-Da-d]|[1-4])\s*\)?"
```

On the line `Official Ans. by NTA (2)` the optional group's alternation tries `\.` first
and consumes the period, so ` by NTA` is never consumed; the value capture then matches
**the `b` of the word "by"**. Verified output:

```
'Official Ans. by NTA (2)'  -> captured='b'   matched='Official Ans. b'
'Official Ans by NTA (3)'   -> captured='3'   (no period, so it works)
'Allen Ans. (2)'            -> captured='2'   (the healthy numeric path)
```

Because it only misfires when a period follows "Ans", it corrupted a subset rather than
everything — which is exactly why the structural lint never caught it.

**These 696 rows are repairable, not droppable.** The true key `(2)` is printed on the
same line, immediately after the text the regex stopped on. Fix the alternation order
(try the longest alternative first, or make the group possessive/atomic), re-extract the
affected mirror papers, and prove the distribution flattens (§4).

### 1.2 Options parsing fails on 74% of rows

11,957 of 16,211 rows have fewer than 4 non-empty options. The live API's quality
filter (`is_quality_question`) hard-rejects any `single_correct` row with under 4
options, so these are unservable regardless of anything else.

This is the difference between ~700 usable questions and ~10,000. It is where the
volume actually is. Most of these are MathonGo chapter PDFs and scanned NEET booklets
where options are laid out in 2×2 grids or split across a column break — the text
extractor is reading them as prose or dropping them.

Treat multi-column and grid option layouts as a first-class case, not an edge case.

### 1.3 One question split across rows — merge, never deduplicate on `(paper_id, qno)`

> **This section was rewritten on 2026-09-11 and contradicts an earlier draft.** That
> draft said "`(source_file, paper_id, qno)` must be unique — enforce it at write time."
> **That instruction was wrong and would have destroyed data. Do not follow it.**
> If you already have the earlier version, this section supersedes it entirely.

2,103 groups of rows share a `(paper_id, qno)`. They are **not** all duplicates, and
the three patterns need three different actions:

| pattern | groups | rows | correct action |
|---|---:|---:|---|
| same question, multiple diagram regions | 779 | 2,542 excess | **merge** into one row with a multi-element `diagram` array |
| different questions sharing a qno | 1,324 | 6,083 | **keep all** — not duplicates |
| identical page + bbox re-processing | 0 | 0 | — does not occur |

Two things follow.

**The pipeline is not re-processing pages.** Zero groups share a page and bbox. The
apparent "internal duplication" is one question whose figure was detected as several
regions, emitted once per region. Those rows must be **merged into a single row carrying
every region in its `diagram` array** — dropping the extras would silently discard
figures the question depends on.

**`qno` is not unique within a source.** Chapter-wise books (MathonGo, SelfStudys)
restart numbering per chapter, so "Q2" on pages 52, 133 and 142 are three *different*
questions. A uniqueness constraint on `(paper_id, qno)` would fuse 1,324 groups of
distinct questions — 6,083 rows of real content destroyed.

So the merge key is the **question-text fingerprint**, never `(paper_id, qno)`. Merge
only same-text groups, and merge them into multi-region rows rather than discarding
copies.

Separately, a text-similarity pass over the whole corpus (Jaccard ≥ 0.75) finds 1,911
near-duplicate groups covering 7,526 rows, of which ~329 span two different source
files — genuine cross-source overlap, handled by §1.4.

### 1.4 Cross-source merges must pick the better copy, not the first one

When the same question appears from two sources, they are not interchangeable:

- **ExamSIDE copies** are cleaner text but **strip embedded numeric values** — one
  resistance question kept `150.4 Ω / 240 Ω` in the PDF-pipeline copy and had them
  genericized away in the ExamSIDE copy. For numerical questions the ExamSIDE copy is
  *wrong*, not merely redundant.
- **PDF-pipeline copies** are more complete but noisier (stray option fragments bleeding
  into the stem, Symbol-font mojibake).
- **NEET booklet copies** occasionally truncate at page boundaries — one cationic-detergent
  question had a stem cut off mid-option-list in one copy and complete in another.

So dedupe is **not** "keep first, drop rest." Rank candidates by completeness:
numeric values preserved > full stem > option count > OCR confidence. Keep the best,
record the discarded IDs in a `merged_from` field so the decision is auditable.

---

### 1.5 Dedupe against the live bank — DEFERRED, do not do this now

For the record, not for this pass: **875 rows in the current corpus are near-duplicates
(Jaccard ≥ 0.75 on normalised text) of questions already live in the `questions` table.**
They must be quarantined as `needs_manual: "duplicate_of_servable:<existing_id>"` rather
than inserted, or students get the same question twice and the Monk Score's repeat-attempt
detection misses it because the row IDs differ.

**This is a gate-time step and it is cheap — do not spend effort on it during extraction.**
Deduplication is a fast pass over finished rows. Your job in this pass is to make the rows
themselves correct and complete. Get the text, the answers, and the diagrams right; the
duplicate sweep happens once, afterwards, against the finished set.

### 1.6 Question-text fidelity — the defects nobody has measured yet

Everything above concerns keys and duplicates. This section concerns whether the stem is
*readable by a student at all*. A question with a correct key and an unreadable stem is
still unservable. Measured across the current 16,211 rows:

| defect | rows | what it looks like |
|---|---:|---|
| **char-fragmented stem** | **482** | a matrix/integral exploded into one character per line |
| **Symbol-font PUA mojibake** | **847** | `10` where the source reads `10 Ω` |
| publisher header in stem | 1,130 | `"Probability Chapter-wise Question Bank JEE Main 2025 April MathonGo ..."` |
| **answer stamp inside stem** | **135** | `"... Q2. (2) ..."` — this leaks the answer to the student |
| solution page filed as a question | 37 | stem is worked solutions; `options: None` |
| stem ends with next question's number | 350 | trailing `"... 181."` |
| raw pipes needing table structure | 886 | `\|` delimiters with no row/separator structure |
| control characters | 20 | stray `\x00`–`\x1f` |

All of these are confined to `diagram_questions.jsonl` — the PDF pipeline.

#### The fragmentation + mojibake pair is one root cause, and it is fixable

These two defects co-occur, and they are the same bug. Example (real row, truncated):

```
'Let   0 and \n3\nA\n2\n\n\n\n\n\n\n ...'
```

That was a 2×2 matrix with Greek entries. The PDF stores it as *positioned glyphs in a
Symbol-family font*; the extractor read the **embedded text layer** and linearised those
glyphs top-to-bottom, destroying the 2D structure and leaving every character as an
unmapped private-use codepoint. No regex can rebuild a matrix from that — the geometry
is gone.

**The fix is not to repair these strings. It is to never produce them.** Mathpix already
handles these pages correctly — it is the same OCR that gives you a 0.98 median confidence
and clean diagram crops. The pipeline simply trusted the text layer instead of calling it.

So: **treat the text layer as untrusted, and fall back to Mathpix OCR whenever the
extracted stem shows either symptom** —

- any codepoint in `U+F000`–`U+F0FF` (Symbol-font PUA), or
- ≥40% of non-empty lines being 1–2 characters long.

Re-OCR that question's page region and use the Mathpix result. Do not attempt a PUA
substitution table as the primary fix: ``→Ω, ``→α, ``→β, ``→π,
``→Δ, ``→≠, ``→=, ``→−, ``→→ will recover *individual
characters*, but the 482 fragmented rows also lost their layout, so character-level
repair yields a readable alphabet in an unreadable order. Use the substitution table only
for rows that are otherwise well-formed prose.

#### Stem hygiene

Strip before writing `question_text`:

- publisher/marketing headers (`"Chapter-wise Question Bank"`, `"MathonGo"`, site names)
- the trailing question number of the *following* question
- any `Qn. (k)` answer stamp — and if a stamp is present, capture it as an embedded
  answer candidate rather than discarding it, but **never leave it in the stem**
- control characters

If after stripping the stem is a worked solution rather than a question (37 known rows),
do not emit it as a question at all.

#### Output formatting the client actually parses

The web client renders stems through a parser that has specific expectations. Match them:

- **Math** in `$...$` (inline) or `$$...$$` (display). Chemistry uses mhchem `\ce{...}`.
- **Tables** (match-the-following, data tables) as real markdown: one row per line, a
  `|---|---|` separator after the header. A whole table condensed onto one line renders
  as raw pipes — that defect had to be repaired by hand in production.
- **A pipe inside math is not a cell boundary.** `\left| x \right|` must stay in one cell.
- **Options keyed `A`/`B`/`C`/`D`** in the options dict, regardless of whether the source
  printed `(1)`–`(4)`. Grading compares the option *key*, not its display text.

## 2. Target schema — what a production row must contain

This is the live `questions` table in Supabase. A row is servable only when it can fill
these. Match the types exactly.

| column | type | requirement |
|---|---|---|
| `question_text` | text | ≥20 chars, no mojibake, no stray option fragments |
| `options` | jsonb | `{"A": "...", "B": "...", "C": "...", "D": "..."}` — 4 non-empty for `single_correct` |
| `question_type` | text | `single_correct` \| `numerical` \| `match_the_following` |
| `correct_option` | text | `A`/`B`/`C`/`D` — required when type is not `numerical` |
| `correct_value` | numeric | required when type **is** `numerical`; `options` must then be null |
| `solution` | jsonb | `{"steps": ["Step 1: ...", "Step 2: ..."]}` |
| `explanations` | jsonb | `{"en": "..."}` |
| `subject` | text | lowercase: `physics` \| `chemistry` \| `mathematics` \| `biology` |
| `chapter_name` | text | **must exactly match an existing row in the `chapters` table** |
| `chapter_id` | uuid | FK to `chapters`; authoritative for class-level filtering |
| `concept` | text | required — feeds Monk Score concept mastery |
| `sub_concept` | text | optional but preferred |
| `difficulty` | int | 1–3 |
| `target_exams` | jsonb array | e.g. `["JEE Main"]`, `["NEET"]` |
| `reference_exam` | text | e.g. `JEE Main` |
| `reference_year` | int | e.g. `2024` |
| `diagram` | jsonb array | see §3 |
| `source_pdf` / `answer_source` | text | provenance |
| `needs_manual` | text | **null = servable.** Any non-null string quarantines the row. |

### Critical type rule

A row typed `numerical` with 4 options and a letter key **renders with no options at
all** in the client. 52 rows had exactly this defect in production and had to be
retyped. If a row has A–D options and a letter answer, it is `single_correct` —
never `numerical`.

### Metadata you are currently not producing at all

Of the 2,096 structurally-clean rows in your current output:

- `chapter`: **0 / 2,096**
- `concept`: **0 / 2,096**
- `difficulty`: **0 / 2,096**
- `solution`: **28 / 2,096**

These are not optional decoration. `concept` and `difficulty` drive the Monk Score
scoring pipeline; `chapter_id` drives both practice question selection *and* the live
tutor's topic router; `solution.steps` is what the student sees after answering.
A row without them is not a question, it is a fragment.

`chapter_name` must match the existing `chapters` table exactly — do not invent chapter
names. If a question does not map to an existing chapter, set `needs_manual` and stop.

---

## 3. Diagram contract — the transformation you have not done

Your rows carry local asset paths. Production serves from Cloudflare R2. The live
`questions.diagram` column is a **JSON array**:

```json
[{
  "url":    "https://pub-1a2e70cb254c42069ccd8c7c9772de82.r2.dev/questions/v2/physics/<paper>/p0003/q14/00-<hash>.jpg",
  "r2_key": "questions/v2/physics/<paper>/p0003/q14/00-<hash>.jpg",
  "form":   "cdn_crop",
  "page":   3,
  "region": {"x": 1142, "y": 402, "w": 699, "h": 404}
}]
```

Mapping from your current shape:

- `diagram_asset.path` → upload to R2 → `url` + `r2_key`
- `diagram_bbox` `[x1, y1, x2, y2]` → `region` `{x, y, w: x2-x1, h: y2-y1}`
- `page` → `page`
- `form` is always `"cdn_crop"`

Assets live in R2, **never in git**. `data/nta_raw/diagram_assets/` is now gitignored;
do not remove that entry or commit binaries.

---

## 4. How you must prove the work — non-negotiable

Do not report "done", "0 errors", or "validation passed" without the numbers below.
The previous run reported "0 OCR errors" while shipping a 90%-"B" answer key, because
the lint only checked structural integrity and never checked whether values were
*plausible*. Integrity checks are necessary and not sufficient.

Every run must emit a report containing:

1. **Answer-key distribution, split by extraction path.** Each of A/B/C/D must land
   between 15% and 35%. Any path outside that band is broken — say so and quarantine
   that path's rows rather than shipping them.
2. **Self-consistency:** count duplicate-text groups whose copies disagree on the key.
   Target is 0. Report the actual number.
3. **Multi-region merges (§1.3):** how many same-text groups you merged, and how many
   `diagram` arrays now carry more than one region. Do **not** report `(paper_id, qno)`
   uniqueness — that is not a defect, and treating it as one destroys data.
4. **Funnel with a number at every stage**, e.g.
   `raw → text≥20 → options≥4 → asset resolves → key present → key verified → metadata complete → servable`.
   Report the count dropped at each stage and *why*.
5. **Asset integrity:** paths resolving, crops under 60×40, OCR confidence
   distribution (min/p05/median) and the count below 0.90.
6. **Text fidelity (§1.6)** — counts for each defect class, before and after your pass:
   rows containing `U+F000`–`U+F0FF`, rows with ≥40% single/double-char lines, rows with a
   publisher header, rows with an `Qn. (k)` answer stamp still in the stem, rows with
   control characters. **Target is 0 for every class.** These are the checks that would
   have caught the 482 unreadable stems, which passed every existing integrity lint
   because the file was present, the reference resolved, and the text was non-empty.
7. **Anything you capped, sampled, or truncated.** If you processed the top-N of
   something, say what was left out. Silent truncation reads as full coverage.

### Answer keys specifically

Keys sourced from coaching mirrors are `embedded_unverified` — that is a claim, not a
fact. Before any row is marked servable, its key must be confirmed by an independent
route: an official NTA key PDF join, or two independent blind solves that agree.
Single-source key claims measured a 41–67% false-positive rate on this corpus. A wrong
key is worse than a missing question, because the student is told they are wrong when
they are right.

---

## 5. Standing rules

- **Never fabricate.** If a stem is garbled, an option is unreadable, or a key is
  uncertain, set `needs_manual` with a specific reason string and move on. Do not
  reconstruct plausible-sounding text. Do not guess a key. A quarantined row costs
  nothing; a fabricated one poisons a student's practice and their mastery score.
- **Do not write to the `questions` table.** Everything stays in the raw layer with
  `needs_manual: "pending_gate"` until the checks in §4 pass and a human approves.
- **Do not modify the `chapters` table.** It is read by 15+ call sites across practice
  selection and the live tutor; a new or renamed chapter has blast radius beyond this task.
- **Preserve provenance on every row.** source page, PDF URL, source tier, paper_id,
  qno, page, and — for merged duplicates — the `merged_from` IDs.

---

## 6. Order of work

1. **Fix `EMBEDDED_ANSWER_VALUE_RE` and re-extract the affected mirror papers** (§1.1).
   Root cause is confirmed; the true keys are present in the source. Prove the per-path
   distribution flattens into the 15–35% band.
2. **Re-OCR the untrusted text layer** (§1.6) — every row with Symbol-font PUA codepoints
   or ≥40% single-character lines goes back through Mathpix. ~1,300 rows, and it converts
   them from unreadable to servable using OCR you have already proven works. Then apply
   stem hygiene (headers, trailing qnos, answer stamps) across the corpus.
3. **Merge the 779 same-text multi-region groups** into multi-element `diagram` rows
   (§1.3). Use the text fingerprint. Do **not** apply a `(paper_id, qno)` constraint.
4. **OCR-mine Question IDs from the 31 eSaral 2022 papers, then join to the official NTA
   key PDFs** (§4). This is the only route to `official_verified` keys at any scale —
   roughly 930 questions. Higher value than raw volume, because unverified keys cannot ship.
5. **Fix options parsing** (§1.2) — per-source, starting with the ExamSIDE `<img alt>`
   extraction and the MathonGo generic-parser failure (162/175 files). This is where the
   volume is: potentially 10,000+ rows rather than ~700.
6. **Attach chapter / concept / difficulty / solution** (§2), matching the live `chapters`
   and `concepts` tables exactly.
7. **Upload assets to R2 and emit the `diagram` array** (§3).

Deduplication is deliberately **not** in this list — see §1.5. It is a cheap pass over
finished rows and happens after all of the above.

Report after each step with the §4 numbers. Do not batch all seven and report at the end.

## 7. A note on citing this codebase

When you attribute a claim to our code, quote it exactly and give `file:line`. In the
previous round, one answer stated that `app/mathpix.py` documents the confidence score as
not separating "good from bad at all." That sentence is not in the file. The underlying
point was correct and well-supported by your own data, so the conclusion stood — but a
fabricated citation is indistinguishable from a real one until someone checks, and it
costs us the ability to trust the citations that *are* real. Paraphrase openly, or quote
exactly. Never present a paraphrase as a quotation.
