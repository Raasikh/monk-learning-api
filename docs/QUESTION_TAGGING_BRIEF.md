# Tagging practice questions to Progress concepts

Written 2026-08-23, after migrations 0022–0027 reshaped the concept taxonomy.
Hand this to the session doing the tagging.

## Why this matters

`progress_scoring.apply_answer_scoring` resolves a question's concepts, then
upserts `concept_mastery`. A question with no link scores **nothing** when
answered — the student's Monk Score does not move. This is the only mechanism
that connects practice to mastery.

## The one thing to get right

There are two "concept" fields on questions and **only one drives scoring**:

| field | what it is | used for scoring? |
|---|---|---|
| `questions.concept` | free text — `"General"`, `"VSEPR & Lone Pairs"` | **NO.** 0 of its 4,989 values match a concept key. |
| `question_concepts` | join table `(question_id, concept_id, role)` | **YES.** This is the one. |

Writing to `questions.concept` accomplishes nothing. The insert shape:

```sql
INSERT INTO question_concepts (question_id, concept_id, role)
VALUES ('<question uuid>', '<concept uuid>', 'primary');
```

`role` is `'primary'` (full mastery gain/loss) or `'secondary'` (×0.35, from
`progress_config.secondary_concept_weight`). All 7,285 existing links are
`primary`, one concept per question. Multi-concept tagging works but has never
been exercised in production — prefer one primary link unless a question
genuinely spans two concepts.

## Scope: two jobs, not one

### Job 1 — the 419 questions with no link at all

```
274  have a chapter_name   → scope to that chapter's ~11 concepts, then pick
145  have NEITHER chapter_name nor concept → question text only
       chemistry 72 · physics 42 · biology 31
 21  carry a free-text concept hint
```

The 145 are the hard ones: no subject scoping, no hint, classification from the
stem alone against 1,153 concepts. **Return low confidence rather than guess.**
A wrong `concept_id` is worse than a missing link — it silently moves the wrong
mastery number, and unlike a missing link, nothing flags it.

### Job 2 — re-check 1,792 links that predate today's concepts

Every existing link was written 2026-08-15 or 2026-08-18. Migrations 0025–0027
added 27 concepts after that, so questions in those chapters were tagged to the
nearest thing that existed at the time. Chapters that gained a concept, by
volume of already-tagged questions:

```
156  chem11 Chemical Bonding            + Metallic Bonding and the Electron Sea Model
134  chem12 d-and-f-Block Elements      + Ionisation Enthalpy Trends in the Transition Series
113  phys11 Rotational Motion           + Angular Impulse and Collisions with Rigid Bodies
109  chem11 Thermodynamics              + Enthalpies of Phase Transition, Atomisation, ...
 97  phys11 Mech. Properties of Fluids  + Turbulent Flow, Critical Velocity and Reynolds Number
 96  chem12 Chemical Kinetics           + Homogeneous and Heterogeneous Catalysis
 92  phys11 Laws of Motion              + Non-Inertial Frames and Pseudo Forces
 90  chem11 General Organic Chemistry   + Diastereomers, Meso Compounds and Two Stereocentres
 77  math11 Complex Numbers             + 3 quadratic concepts (see below)
 77  math11 Conic Sections              + Relative Position of Two Circles and Common Tangents
 74  phys11 Thermal Properties          + Blackbody Radiation and Wien's Displacement Law
 70  chem11 Hydrocarbons                + Polymerisation of Alkenes and Alkynes
 68  biol11 Plant Growth & Development  + Seed Germination and Conditions for Growth
 64  biol12 Evolution                   + Types of Natural Selection
 ... 11 more chapters, 1 new concept each
```

**Complex Numbers is the highest-value one.** The chapter gained three concepts
covering real-coefficient quadratic theory — nature of roots and the
discriminant, relations between roots and coefficients, formation of equations
and the common-root condition. That material had NO concept before today, so
every quadratic question in the bank is currently tagged to something else.

Do NOT bulk re-tag. Re-examine only questions whose stem plainly matches a new
concept, and leave a correct existing link alone.

## Shortcut: concept_aliases is already populated

`concept_aliases` holds 865 rows mapping free-text question tags onto the
taxonomy (`alias`, `source='question_tag'`, `concept_id`), e.g. `"AC Circuits"`,
`"RLC Circuit"` and `"LCR Circuits"` all → one concept. **4,902 questions carry
a free-text tag matching an existing alias.** Consume that mapping rather than
re-deriving it.

## Constraints

- **`concept_id` must be an ACTIVE concept.** Migrations 0022–0024 retired 18
  and remapped 48 links off them. A link to a retired concept now logs a
  warning and scores nothing, by design.
- **The chapter matters, and it is ambiguous.** `questions.chapter_id` is
  populated on only 191 of 7,704 rows, so matching goes through
  `chapter_name` — ~98% populated but NOT unique across classes. "Probability",
  "Relations and Functions" and "Thermodynamics" each exist in two places.
  Match on `(chapter_name, subject, class_level)`, never name alone.
- **Class 11 and Class 12 were just split along the NCERT boundary.**
  Conditional probability, Bayes and random variables now live ONLY in Class
  12; sample space and the addition theorem ONLY in Class 11. Same for
  Relations and Functions. A question tagged to the wrong class is now a real
  error where in August it was harmless duplication.

## Verifying the work

```sql
-- 1. No link may point at a retired concept. Must return 0.
SELECT count(*) FROM question_concepts qc
  JOIN concepts c ON c.id = qc.concept_id WHERE c.active = false;

-- 2. Coverage. Was 7,285 of 7,704 before this work.
SELECT count(DISTINCT question_id) FROM question_concepts;

-- 3. A question's concept must belong to the chapter the question is in.
--    Any row here is a cross-chapter mistag.
SELECT q.id, q.chapter_name, ch.name AS concept_chapter, c.name
  FROM question_concepts qc
  JOIN questions q ON q.id = qc.question_id
  JOIN concepts c  ON c.id = qc.concept_id
  JOIN chapters ch ON ch.id = c.chapter_id
 WHERE q.chapter_name IS NOT NULL
   AND lower(trim(q.chapter_name)) <> lower(trim(ch.name))
 LIMIT 50;
```

Query 3 is the one that catches real damage. Run it before and after — the
count should not grow.

## Do not

- Do not write to `questions.concept`. It scores nothing.
- Do not drop `questions.concept`. It is the display fallback in
  `resolve_display_concept` for questions with no link, and it is the input
  `concept_aliases` was built from. Drop it only after coverage hits 100%.
- Do not delete existing links to "start clean". 7,285 of them are correct.
