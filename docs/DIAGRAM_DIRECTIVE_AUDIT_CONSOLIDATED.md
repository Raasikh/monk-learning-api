# Directive: diagram-question corpus — state of play and remaining work

**Read this whole document before touching anything.** It is written to be self-contained:
a previous session did the work described in §2 and that session is gone, so nothing here
assumes you remember it. All numbers were measured independently against the files on
disk, not taken from prior reports.

---

## 1. What this project is

`monk-learning-api` serves JEE/NEET practice questions to students from a Supabase
`questions` table. A long-running effort scraped **diagram questions** — questions with an
accompanying figure — from public exam papers and coaching mirrors, to expand the bank.

The extraction lives in a **raw staging layer**, not in the live database:

| file | rows |
|---|---:|
| `data/nta_raw/diagram_questions.jsonl` | 995 |
| `data/nta_raw/examside_diagram_questions.jsonl` | 2,627 |
| `data/nta_raw/examside_diagram_questions_jee_advanced.jsonl` | 576 |
| `data/nta_raw/neet_mathongo_questions.jsonl` | 34 |
| **total** | **4,232** |

Image crops live in `data/nta_raw/diagram_assets/` (~1.4 GB, gitignored — they belong in
R2, never in git). `data/nta_raw/diagram_candidates.jsonl` (21,591 rows) is the
pre-materialisation candidate pool.

**The live `questions` table is untouched and must stay that way.** Verified just now:
15,408 rows, 80 with diagrams, zero rows with `needs_manual='pending_gate'`. Nothing from
this corpus has ever been inserted. **Do not insert anything.** Everything stays raw until
a human approves it.

### The production schema you are eventually targeting

| column | requirement |
|---|---|
| `question_text` | ≥20 chars, no mojibake, no answer or solution text embedded |
| `options` | `{"A":…,"B":…,"C":…,"D":…}`, 4 non-empty for `single_correct` |
| `question_type` | `single_correct` \| `numerical` \| `match_the_following` |
| `correct_option` | `A`–`D` when not numerical |
| `correct_value` | required when `numerical`; `options` must then be null |
| `solution` | `{"steps":[…]}` |
| `chapter_name` / `chapter_id` | **must match an existing row in the live `chapters` table** — never invent one |
| `concept` | must exist in the live `concepts` taxonomy, or the row scores nothing |
| `difficulty` | 1–3 |
| `diagram` | JSON array, see §6 |
| `needs_manual` | **null = servable.** Any non-null string quarantines the row. |

A `numerical` row with 4 options and a letter key renders with **no options at all** in
the client. That defect already had to be repaired 52 times in production. If a row has
A–D options and a letter answer it is `single_correct`, never `numerical`.

---

## 2. What has already been fixed — do not redo this

Six rounds of work are already done. Re-running them wastes effort and risks regression.

- **Answer-key regex.** `EMBEDDED_ANSWER_VALUE_RE` in `scripts/extract_nta_papers.py`
  used to match the `b` of "by" in `Official Ans. by NTA (2)`, producing 90% "B" keys.
  Fixed; distributions are now uniform.
- **Text fidelity.** Symbol-font PUA mojibake, character-fragmented stems, publisher
  watermarks, answer stamps in stems — all cleared to near zero.
- **Options contamination.** 383 option values had `Official Ans` / `Sol.` text and full
  worked solutions printed inside them; truncated at the leak marker. **Incomplete — see
  §4.4.**
- **Figure attribution.** This was the big one. Figures used to be paired to questions by
  *page co-location*: the extractor found figure regions on a page, found questions on the
  page, and paired them off. ~80% were attached to the wrong question — a billiard-ball
  collision question carried a resistor network, a definite integral carried a
  coordinate-geometry figure. Rebuilt to bind figures by question-span geometry with a
  no-fallback rule, then vision-gated. **Confirmed working — see §3.1.**
- **`has_stem_figure`** was hardcoded `True` on 11,577 of 11,579 rows, giving false
  assurance while testing nothing. Removed from `diagram_questions.jsonl`. **Still present
  on the other three files — see §4.6.**

Current figure state: **702 rows carry a figure**, of which **668** passed the vision gate.

---

## 3. Two independent audits were just run. Here are the results.

Both were run blind by separate agents, forbidden from reading anything under `data/`
(the repository contains the answers and labels they were asked to reproduce), with
controls seeded unlabelled.

### 3.1 Vision audit of figure attribution — the fix holds

40 probes: 30 pairs the gate passed, plus **10 deliberately scrambled pairs** (a stem
given a figure donated from a different paper), shuffled together.

| | result |
|---|---:|
| Scrambled pairs caught | **10 / 10** |
| Judge false-accept rate | **0%** |
| Passed pairs confirmed | **29 / 30** |
| Genuine false-accepts found | **1** |

The 10/10 on negative controls is what makes the rest trustworthy — a judge that waves
through scrambled pairs tells you nothing about the pairs it approves.

**Measured false-accept ≈ 3.3%.** Applied to 668 rows: **~22 still carrying a wrong
figure.** Attribution went from ~80% wrong to ~3–5% wrong. That is a real fix.

### 3.2 Key verification — 89%

53 rows: 45 unverified mirror keys, 8 `official_verified` controls, seeded unlabelled.

| | result |
|---|---:|
| Controls recovered | **8 / 8 (100%)** |
| Unverified keys agreeing | **33 / 37 (89%)** |
| Disagreements | **4** |
| UNSURE — unanswerable as extracted | **8 / 45 (18%)** |

Controls come from the NTA key-PDF join, independent of the row text, so 8/8 establishes
solver competence and makes 89% a real measurement.

**Applied to the 359 unverified rows: ~39 wrong keys** (95% CI ≈ 11–78). 89% is not a
shippable key accuracy — a wrong key tells a student they are wrong when they are right,
and corrupts their mastery score on the way through.

---

## 4. Defects to fix, in priority order

### 4.1 HIGHEST — option-figure questions cannot be represented at all

Six of 53 sampled rows (~11%) are questions where **the options themselves are images** —
"which graph shows…", "which structure is the product…". They need all four option figures
to be answerable. The current model assigns exactly one figure per question.

| qid | finding |
|---|---|
| `68e1698cbcd1a474` | all four option texts identical (`"time No. of atoms"`); one of four graphs attached, and it is the wrong one |
| `96bab29185707cc2` | options A and B byte-identical; the ortho/para difference exists **only** in the un-attached figures |
| `7839c0f0842139e6` | only the option-C figure attached; option text alone cannot be solved |
| `8fe8b1b446111219` | options are `'-'`, `','`, `'and'`; one graph attached, inconsistent with the stem |
| `172b936c79baa660` | one of four option circuits attached; options are OCR fragments (`'D4 R'`, `'D2 R 5V'`) |
| `95381c0c61187508` | figure (a) attached, figure (b) missing — the stem's comparison is impossible |

The one-figure-per-row rule is exactly what fixed stem attribution, so **this is a missing
case, not a regression to undo.**

**Build a distinct `option_figures` concept**, separate from the stem figure. A row has
either (a) a stem figure, (b) a complete A–D set of option figures, or (c) neither.
**A partial set is never servable** — quarantine `option_figures_incomplete` rather than
shipping one of four. Detect the class by the signature already in the data: near-identical
or empty option texts on a question with multiple sibling crops on the same page.

Report the corpus-wide count. Given 6 of 53, expect several hundred.

### 4.2 The ~39 wrong keys

Four disagreements were found:

| qid | solver | stated | assessment |
|---|---|---|---|
| `c56280cf2b2328c4` | A (high) | B | **Genuine key error.** Hydrazine has no carbon, so Na fusion cannot form NaCN and no Prussian blue forms. |
| `96bab29185707cc2` | B (high) | A | options byte-identical — ungradeable regardless (§4.1) |
| `541bc57d1bbab008` | A (low) | C | figure ambiguous; read as NOR, three options are simultaneously correct |
| `d1cae47c6b12d3a6` | C (low) | B | stem truncated mid-sentence, resistance value missing |

Only the first is a clean key dispute; the others are symptoms of defective rows.

**Either** extend blind-solve verification across all 359 unverified rows (two independent
solves, promote only on agreement *and* match with the stated key, everything else
`key_disputed`), **or** quarantine the unverified set and ship only `official_verified`
keys. Do not ship 89%.

### 4.3 A second vision false-accept, and the signature to gate on

`e4e321569cfbab8c` — *"Figure shows isoprene (excess) + HBr, but every option is an
indole/amino-ketone."* Found by a key solver, not a vision judge.

The other: `2adb27384034555f` — stem reads *"Consider the given chemical reaction:
KMnO₄–H₂SO₄, Heat → Product A"*, attached figure is chlorobenzene + NaOH → phenol (the Dow
process). That stem contains **no substrate at all**, so it is unanswerable without the
correct figure.

Both share a signature: **right subject, right question *type*, wrong content.** A
reaction-scheme question given *a* reaction scheme. The gate appears to accept on
type-match. Re-run it instructing that a scheme must match the stem's stated **reagents**,
not merely be a scheme. Prioritise rows whose stem references a figure but carries none of
the needed content — those are the highest-risk rows in the corpus.

### 4.4 Options cleanup is incomplete

- `d570e455a7c28553` — **answer choices still merged into option D.** The truncation pass
  missed this row.
- `d5a4fd28bfb6360c` — options A and C character-for-character identical
- `e76314c461c43677` — **options belong to a different question**: stem asks for
  2,3-dibromo-1-phenylpentane, every option is a chloro-cycloalkane
- `8fe8b1b446111219` — options are `'-'`, `','`, `'and'`, with an unrelated
  equivalent-resistance question appended to option D
- `5db841df3ce2ef2e`, `e6556da76375fdd8`, `7839c0f0842139e6` — **OCR dropped minus signs
  and fraction bars.** `'0 V 33V'` is really 0V and −3V; `'34V 33V'` is −4V and −3V.

That last class deserves its own scan: a lost minus sign changes the answer without
looking broken.

### 4.5 Truncated and corrupted stems

`d1cae47c6b12d3a6` (cut mid-sentence), `fd77921934f2641f` (force and displacement vectors
absent), `7aaf1bf18a249d8f` (stem is OCR garbage `'n ¾¾® 2 2 3'`, options are reagents not
products). Quarantine; do not reconstruct.

### 4.6 Three of four source files were never re-attributed

`has_stem_figure` is reported removed. It is still present on **3,237 rows**: 2,627 in
`examside_diagram_questions.jsonl`, 576 in `examside_diagram_questions_jee_advanced.jsonl`,
34 in `neet_mathongo_questions.jsonl`. **Only `diagram_questions.jsonl` was re-attributed.**

ExamSIDE figures come from the question's own HTML detail page rather than page geometry,
so attribution is probably better there by construction — but "probably" is what the last
six rounds disproved. Run the same vision gate over their figure rows, report the pass
rate, and remove `has_stem_figure` everywhere.

### 4.7 Smaller items

- `7831666e00f64a2f` — stem says *"in the figure shown"*, **no image attached**, and the
  row is unquarantined. The `stem_reference_absent` quarantine is not catching everything.
- `100383e3ca6fb082` is an exact duplicate of `68afe0ae57644d5b`; both present, both keyed C.
- `7b493d842c687bd9` — the printed source figure has **its axis labels swapped**
  (vertical reads `P (in cc)`, horizontal `V (in kPa)`). Correctly attributed and still
  wrong. Worth its own flag class.

---

## 5. Deferred — do not spend effort here

- **Deduplication against the live bank.** 875 rows of this corpus duplicate questions
  already live. Real, but it is a cheap pass over finished rows and happens last.
- **The ~7,359 non-figure questions.** `diagram_questions.jsonl` went 8,354 → 995 when
  rows without figures stopped being materialised. Those are legitimate JEE/NEET questions
  that simply need no diagram, and as practice content they are worth more than the 668
  diagram rows. **Confirm whether they survive in `diagram_candidates.jsonl` and are
  recoverable, then surface that as a decision — do not act on it.**

---

## 6. The R2 diagram contract, for when rows are finally ready

Production serves figures from Cloudflare R2. `questions.diagram` is a JSON array:

```json
[{
  "url":    "https://pub-1a2e70cb254c42069ccd8c7c9772de82.r2.dev/questions/v2/physics/<paper>/p0018/q121/00-<hash>.jpg",
  "r2_key": "questions/v2/physics/<paper>/p0018/q121/00-<hash>.jpg",
  "form":   "cdn_crop",
  "page":   18,
  "region": { "x": 377, "y": 624, "w": 409, "h": 267 }
}]
```

Map `diagram_asset.path` → upload → `url` + `r2_key`; `diagram_bbox [x1,y1,x2,y2]` →
`region {x, y, w: x2−x1, h: y2−y1}`. `form` is always `"cdn_crop"`.

The uploader previously had a lost-update race — it loaded the file, uploaded for an hour,
then wrote back rows the pipeline had since rewritten. Reportedly fixed with
merge-on-write-back; verify before any large run.

Client rendering expects: `$…$` / `$$…$$` math, mhchem `\ce{}` for chemistry, real
markdown tables with separator rows, and options keyed `A`–`D` regardless of whether the
source printed `(1)`–`(4)` — grading compares the option **key**, not its display text.

---

## 7. Standing rules

- **Never fabricate.** Garbled stem, unreadable option, uncertain key → set `needs_manual`
  with a specific reason and move on. A quarantined row costs nothing; a fabricated one
  poisons a student's practice and their mastery score.
- **Never write to the `questions` table.** Raw layer only, `needs_manual: pending_gate`.
- **Never modify the `chapters` table.** It is read by 15+ call sites across practice
  selection and the live tutor; a new or renamed chapter has blast radius beyond this task.
- **Never attach a figure as a fallback.** "This question has no figure" is a correct and
  common outcome — only ~1,722 of the original 11,579 stems referenced a figure at all.
- **Preserve provenance** on every row: source page, PDF URL, source tier, paper_id, qno,
  page, and `merged_from` for merged duplicates.

---

## 8. Reporting requirements

Report after each item, not batched at the end.

- **Corpus-wide count of option-figure questions**, and how many have a complete A–D set.
- **Key accuracy with the control-recovery rate stated separately.** A key-agreement
  number without a control rate cannot be interpreted — it cannot distinguish "the keys
  are good" from "the solver is weak".
- **Per-class counts for every §4 item, before and after.**
- **A cumulative funnel, gate by gate**, so the binding constraint is visible:
  `raw → text≥20 → question_type → options → figure → metadata → solution → key → verified`.
  A total without per-gate attribution hides which single field is costing thousands of
  rows — that is how a missing `question_type` blocked 8,637 rows unnoticed for six rounds.
- **Anything capped, sampled, or skipped.** Silent truncation reads as full coverage.

### One process note

Each audit above found something a prior report had marked closed — the options leak
(§4.4), the `stem_reference_absent` quarantine (§4.7), the vision gate's false-accept rate
(§4.3), `has_stem_figure` removal (§4.6). In every case the check had been run by the same
process that made the change.

The checks that caught these were blind, externally run, and carried controls. **Build
controls into your own gates.** A vision gate with 10 deliberately scrambled pairs mixed
in measures its own false-accept rate honestly and costs almost nothing. A key pass with
known-good rows seeded in tells you whether the solver is competent before you trust its
disagreements. Without controls, a gate reports its intent rather than its behaviour.
