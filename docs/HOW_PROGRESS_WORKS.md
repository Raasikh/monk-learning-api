# How Progress works

Everything the Monk Score is built from, bottom to top. Written 2026-08-23,
against the live code and the live `progress_config` row.

---

## The one-paragraph version

A student answers a practice question. That question is linked to one or more
**concepts**. The answer moves that concept's **mastery** (0–100). A chapter's
mastery is the average of its concepts. A subject's score is the
**mark-weighted** average of its chapters — so a 10-mark chapter counts twenty
times a 0.5-mark one. The Monk Score is the mark-weighted average of the
subjects, on a 0–1000 scale.

**If a question is not linked to a concept, answering it changes nothing.**
That link is the whole loop.

---

## The chain

```
     one answered question
              │
              ▼
   ┌──────────────────────┐
   │  CONCEPT mastery     │   0–100 per (student, concept)
   │  concept_mastery     │   moved only by answering a linked question
   └──────────┬───────────┘
              │  mean of the chapter's concepts
              ▼
   ┌──────────────────────┐
   │  CHAPTER mastery     │   0–100
   └──────────┬───────────┘
              │  weighted by chapter_exam_weights.avg_marks
              ▼
   ┌──────────────────────┐
   │  SUBJECT score       │   0–1000
   └──────────┬───────────┘
              │  weighted by marks per subject in the paper
              ▼
   ┌──────────────────────┐
   │  MONK SCORE          │   0–1000, ratcheted, capped by flags
   └──────────────────────┘
```

Each arrow is a weighted average. Nothing else happens in between.

---

## Layer 1 — Concept mastery

One row per `(student, concept)` in `concept_mastery`. Absence of a row means
*not started*, not zero — the distinction matters, because a chapter with no
attempts shows `not_started` rather than a discouraging `0% needs revision`.

### A correct answer

```
gain    = 14 × difficulty × (100 − current) / 100 × role × mode
mastery = min(100, current + gain)
```

Two things are doing the work here:

- **`(100 − current) / 100`** — diminishing returns. Each correct answer closes
  a fixed *fraction* of the remaining gap, so mastery approaches 100 and never
  reaches it by grinding. From zero, on medium primary practice questions:
  `0 → 14 → 26 → 36.4 → 45.3 → 53 …`
- **`difficulty`** — an easy question is worth less evidence than a hard one:

  | band | multiplier |
  |---|---|
  | easy | 0.70 |
  | medium | 1.00 |
  | hard | 1.40 |
  | pyq_hard | 1.60 |

`role` is `1.0` for a primary concept link and `0.35` for a secondary one.
`mode` is `1.15` in mock-test mode — exam conditions are worth more evidence
than casual practice.

### A wrong answer

```
mastery = max(0, current − 5 × (current / 100) × role)
```

Losses are **proportional to what you currently claim**. At 20% mastery a
mistake costs 1 point; at 90% it costs 4.5. Being wrong about something you
supposedly knew is stronger evidence than being wrong about something you
never learned.

Note the asymmetry: gains scale with difficulty, losses don't. Getting a hard
question wrong costs the same as getting an easy one wrong.

### The four states

| state | rule |
|---|---|
| **strong** | mastery ≥ 80 |
| **improving** | mastery ≥ 45 |
| **needs_revision** | below 45, and at least one attempt |
| **not_started** | no attempts |

---

## Layer 2 — Chapter mastery

```
chapter mastery = mean(mastery of every concept in the chapter)
```

A plain average — concepts are **not** individually weighted inside a chapter.

**This average is why a wrong concept in a chapter is so damaging.** A concept
that does not belong there can never be attempted, so it contributes a
permanent zero that no amount of study can lift. Class 12 Relations and
Functions once read **38%** for a student who had genuinely mastered all five
of its real concepts, because eight Class 11 duplicates were still being
averaged in. Migrations 0022–0024 removed 18 such concepts.

The chapter's displayed **chip** is not simply its mastery:

- any flagged concept in it → `needs_revision`, regardless of the average
- no attempts anywhere in it → `not_started`
- otherwise → the state its average mastery falls into

---

## Layer 3 — Subject score

```
subject score = 10 × Σ(chapter mastery × chapter weight)
                    ─────────────────────────────────────
                          Σ(chapter weight)
```

on a **0–1000** scale (hence the ×10).

The weight is `chapter_exam_weights.avg_marks` — how many marks that chapter is
typically worth in the real paper, researched per subject **per exam**, because
JEE and NEET weight physics and chemistry very differently.

```
Conic Sections            jee   10.6      Molecular Basis of Inheritance  neet  21.5
Complex Numbers           jee    7.4      Animal Kingdom                  neet  18.5
Basic Mathematics         jee    0.5      The Living World                neet   2.5
```

Every subject's weights sum to the marks it is actually worth: 100 for each JEE
subject, 180 for NEET physics and chemistry, 360 for NEET biology.

Before these were populated every chapter defaulted to weight `1.0`, which made
mastering the single logarithms concept in Basic Mathematics move the
Mathematics score exactly as much as mastering all 14 concepts in Complex
Numbers. Flat weighting was off by up to **7×**.

**Two kinds of chapter are excluded entirely** — they are not listed and not
scored:

- a chapter whose concepts are all tagged for a different exam (Linear
  Programming, tagged `board`, is on neither JEE nor NEET)
- a chapter whose concepts are all retired

A chapter with **no concepts at all** is different: it still appears, marked
`curated: false`, so an unauthored chapter can still be opened. It is excluded
from recommendations but *is* still averaged into the subject score at 0.

---

## Layer 4 — The Monk Score

```
raw     = Σ(subject score × subject marks) / Σ(subject marks)
ceiling = 1000 − 18 × (number of flagged concepts)
display = min( max(raw, every past raw), ceiling )
```

Subject marks come from the paper: JEE is 100/100/100, NEET is 360 biology /
180 physics / 180 chemistry — so **biology is half the NEET Monk Score**,
exactly as it is half the NEET paper.

### The score is a ratchet

`display` uses the **running maximum** of every score the student has ever had,
not today's raw value. A bad week cannot pull the number down. This is
deliberate and it is the least obvious behaviour in the whole system:

- raw score drops after some wrong answers → **display does not move**
- the only thing that can lower `display` is the **flag ceiling**

So the number a student sees answers "how much have you ever proven?", not "how
sharp are you today". `raw` is returned alongside `display` if you need the
honest current value.

---

## What moves the score, and what doesn't

**Moves it**

- answering a practice question that is linked to a concept
- a mock test — 1.15× the evidence of ordinary practice
- harder questions — up to 1.6× for a hard PYQ

**Does not move it**

- answering a question with **no** `question_concepts` link — silently scores
  nothing
- a question linked to a **retired** concept — skipped, with a warning in the
  logs
- a Drona lesson on its own. Lessons and practice share the concept taxonomy,
  which is what lets them describe the same mastery, but only a graded answer
  writes `concept_mastery`.
- time passing (see below)

---

## Built vs not built

Two features are in the schema and the read path but have **no writer**. The
read side works, so they look implemented from the outside.

### Flagging — read only

`concept_mastery.flag_state` is read in four places: the chapter chip, the
`clear_flag` recommendation, the ceiling penalty, and Drona's student context.
**Nothing in the codebase ever sets it to `pending` or `flagged`.** All live
rows are `none`, so today:

- the ceiling is always a flat 1000
- no chapter is ever forced to `needs_revision` by a flag
- the `clear_flag` recommendation never appears

### Spaced revision and decay — partly written, never read

`apply_answer_scoring` sets `next_retest_at` when a concept first reaches
strong, using a half-life of 21 / 45 / 90 days. But:

- **nothing reads `next_retest_at` back** to surface a re-test
- **nothing decays mastery over time** — `half_life_days` is stored and never
  applied
- **`proven_count` is never incremented**, so the half-life never escalates
  past the first value of 21 days

So mastery today is permanent once earned. A concept mastered in January still
reads 100 in December without a single revision.

Neither gap breaks anything that currently runs — but if you ever wonder why a
student's score never decays, or why no revision flags appear, this is why.

---

## Where every number lives

| table | holds | written by |
|---|---|---|
| `concepts` | the taxonomy — 1,154 active across 107 chapters | migrations |
| `question_concepts` | question → concept links, `(question_id, concept_id, role)` | tagging |
| `concept_mastery` | per-student mastery, one row per concept touched | `apply_answer_scoring` |
| `chapter_exam_weights` | marks per chapter per exam | migration 0028 |
| `progress_config` | every constant below | manual |
| `progress_snapshots` | daily score history, powers the ratchet and the weekly delta | snapshot job |

Reads go through `progress_user_bundle` — one Postgres function instead of five
PostgREST round trips, which took the endpoint from ~4.6s to ~340ms.

**The taxonomy tables are cached for 600 seconds** (`TAXONOMY_CACHE_TTL_S`).
After changing concepts or weights, production keeps serving the old values for
up to 10 minutes unless you redeploy.

---

## Config reference

Every number above is a row in `progress_config`, not a constant in the code.

| key | value | what it does |
|---|---|---|
| `g_base` | 14 | base gain on a correct answer |
| `l_base` | 5 | base loss on a wrong answer |
| `difficulty_multipliers` | 0.7 / 1.0 / 1.4 / 1.6 | easy / medium / hard / pyq_hard |
| `secondary_concept_weight` | 0.35 | a secondary concept link's share |
| `mock_multiplier` | 1.15 | exam-conditions premium |
| `strong_threshold` | 80 | mastery at which a concept counts as mastered |
| `improving_threshold` | 45 | boundary between improving and needs_revision |
| `half_lives_days` | 21 / 45 / 90 | spaced-revision intervals (not yet applied) |
| `flag_ceiling_penalty` | 18 | score ceiling lost per flagged concept |
| `flag_decay_threshold` | 65 | intended flag trigger (no writer yet) |
| `subject_marks` | JEE 100×3 · NEET 360/180/180 | subject weighting in the Monk Score |

---

## If the score looks wrong, check these in order

1. **Is the question linked?**
   `SELECT count(*) FROM question_concepts WHERE question_id = '<id>';`
   Zero means answering it does nothing. This is the most common cause.
2. **Is the linked concept active?**
   A retired concept is skipped and logs `[SCORING] question … is linked to N
   retired concept(s)`.
3. **Does the concept sit in the chapter you expect?**
   A cross-chapter mistag moves the wrong chapter's number. Query 3 in
   `QUESTION_TAGGING_BRIEF.md` finds these.
4. **Is the chapter on the student's exam?**
   Concepts carry an `exams` tag. A JEE-only concept contributes nothing to a
   NEET student's score.
5. **Are you looking at `display` or `raw`?**
   `display` is ratcheted to the student's historical best and will not fall.
