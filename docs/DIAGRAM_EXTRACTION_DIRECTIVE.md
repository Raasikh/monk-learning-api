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

- 2,616 rows have OCR confidence < 0.90 (minimum observed: 0.0000). Do not treat those
  rows' text as trustworthy — see §4 on flagging.
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

Fix the letter path. Then prove it (§4).

### 1.2 Options parsing fails on 74% of rows

11,957 of 16,211 rows have fewer than 4 non-empty options. The live API's quality
filter (`is_quality_question`) hard-rejects any `single_correct` row with under 4
options, so these are unservable regardless of anything else.

This is the difference between ~700 usable questions and ~10,000. It is where the
volume actually is. Most of these are MathonGo chapter PDFs and scanned NEET booklets
where options are laid out in 2×2 grids or split across a column break — the text
extractor is reading them as prose or dropping them.

Treat multi-column and grid option layouts as a first-class case, not an edge case.

### 1.3 The pipeline emits the same question multiple times

1,911 duplicate groups exist within the corpus, covering 7,526 rows — **5,615 excess
rows**. Breaking that down by cause:

| cause | groups | excess rows |
|---|---|---|
| **one source file re-emitting the same `paper_id` + `qno`** | 1,280 | **2,995** |
| genuine cross-source overlap (two sites, same paper) | 329 | ~2,300 |
| same file, different paper/qno, near-identical text | 302 | ~300 |

All 2,995 internal-repeat rows come from `diagram_questions.jsonl`. This is a bug in
your PDF pass, not source overlap — the same PDF page is being processed more than
once, or one question spanning two detected regions is emitted once per region.

`(source_file, paper_id, qno)` must be unique. Enforce it at write time.

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
3. **Uniqueness:** count violations of `(source_file, paper_id, qno)`. Target 0.
4. **Funnel with a number at every stage**, e.g.
   `raw → text≥20 → options≥4 → asset resolves → key present → key verified → metadata complete → servable`.
   Report the count dropped at each stage and *why*.
5. **Asset integrity:** paths resolving, crops under 60×40, OCR confidence
   distribution (min/p05/median) and the count below 0.90.
6. **Anything you capped, sampled, or truncated.** If you processed the top-N of
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

1. **Fix the letter-format key parser** (§1.1). Self-contained, and it is the
   difference between ~840 and ~1,540 usable keys. Prove it with a flat distribution.
2. **Fix options parsing for multi-column/grid layouts** (§1.2). This is where the
   volume is — potentially 10,000+ rows rather than 700.
3. **Enforce `(source_file, paper_id, qno)` uniqueness and completeness-ranked
   dedupe** (§1.3, §1.4).
4. **Attach chapter / concept / difficulty / solution** (§2), matching `chapters` exactly.
5. **Verify keys independently** (§4).
6. **Upload assets to R2 and emit the `diagram` array** (§3).

Report after each step with the §4 numbers. Do not batch all six and report at the end.
