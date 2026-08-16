# Extraction Quality Spec — what "done" means for a question row

Send this whole file to any session extracting questions. It encodes everything
the 2026-08-15 full-bank audit found: measured error rates, the exact failure
modes, and the verification gate every new row must pass BEFORE it is servable
(`needs_manual = NULL`). The audit quarantined 867 of 3,510 servable rows —
1 in 4 — and every failure mode below was found in production, not imagined.

## Why this exists (measured, not hypothetical)

- **4.3%** of MCQ answer keys were wrong (blind re-solve + adversarial defence).
- **11.6%** of numerical keys were wrong — 2.7× worse, because with no options
  there is nothing for a bad extraction to collide with.
- **16%** of stems were PDF-scramble-corrupted.
- **~740** stored solutions were dishonest: they derived a different answer than
  the key, or rationalized their way to it ("consider the possibility of
  additional constraints… confirming that Option A is indeed correct").
- The tutor (Drona) treats `solution` as verified ground truth and reads it
  aloud. A dishonest solution does not just mis-grade — it *teaches the error*.

## Row contract (`questions` table)

| Field | Requirement |
|---|---|
| `question_text` | The stem ONLY. No option text, no answer, no solution, no "(1) … (2) …" duplicates of the options, no page headers/footers, no question numbers. |
| `options` | JSONB dict `{"A": "...", "B": "...", "C": "...", "D": "..."}`. Exactly the choice text — never explanations, never "The trap is…", never correct-answer hints. `null` for numerical. |
| `question_type` | `single_correct` \| `numerical` \| `assertion_reason` \| `match_the_following`. A question answered by a number typed by the student is `numerical` even if the PDF printed it with option digits (1)(2)(3)(4) — and vice versa: four labelled choices means MCQ even if the choices are numbers. |
| `correct_option` | Single uppercase letter A–D (MCQ only). Must pass the verification gate below. |
| `correct_value` | Number (numerical only). State the convention the stem demands (see rounding/units below). |
| `value_tolerance` | Set it explicitly when the answer is a decimal (e.g. 0.01 for two-decimal answers). The legacy rows all have 0/NULL and grading falls back to a 0.5% relative band — do not rely on that for new content. |
| `solution` | `{"steps": ["Step 1: …", …]}` — 3–6 steps, plain speakable text (NO LaTeX, no `$`), each step deriving the next, ending at the key. See "honest solutions". |
| `needs_manual` | Set a reason string whenever ANY check below fails. A defective row with `needs_manual` set is fine; a defective row that is servable is the only real failure. |

## Reject-at-sight (structural lint — no LLM needed)

Reject or flag the extraction if ANY of these hold:

1. **Scramble signatures** in the stem: `( )` followed by digits; operators
   marooned from operands (`x y z 8, x, y, z I, + + = ∈`); ≥8 isolated single
   letters in a short stem; inequality/relation chains broken across tokens.
2. **Stem references an artefact that was not extracted**: "the figure",
   "the graph shown", "the following table", "identify the regions on the
   curve" with no figure. (`missing_diagram` was a real quarantine class.)
3. **Options defects**: fewer than 4 non-empty options for `single_correct`;
   two options identical after whitespace/punctuation normalisation; options
   about a different topic than the stem (conformers stem, alcohol options —
   real example); any option containing meta-text ("The trap:", "students
   fixate", "the answer is", "explanation:").
4. **LaTeX health**: unbalanced `$`, `{`/`}`, `\left`/`\right`; literal
   private-use glyphs (`` etc.) from symbol fonts.
5. **Stem under 20 characters**, or placeholder options ("Option A").
6. **Rounding/units convention missing** for numerical: if the source says
   "round off to the nearest integer" or "answer in kJ/mol", that convention
   MUST survive into the stem — dropping it made correct keys look wrong and
   wrong keys look plausible.

## The verification gate (every key, before it is servable)

Single-model verdicts are not evidence. On numerical disputes a strong model
was wrong **62% of the time** (rounding conventions, dropped constraints, its
own arithmetic). The gate that worked:

1. **Blind solve** — a solver sees ONLY stem + options (never the candidate
   key, never the solution) and answers, with an UNREADABLE escape hatch and
   explicit instructions never to guess. Reasoning models truncate to an empty
   JSON object at low max_tokens — give ≥3000 or retry with thinking disabled,
   and never score an empty response as a disagreement.
2. **Adversarial defence** — a second pass is SHOWN the candidate key and asked
   to defend it, ruling VALID whenever the key is defensible under any standard
   reading. Opposite framing to pass 1, so their agreement is meaningful.
3. **Key ships only if both name the same answer.** If they disagree, or
   neither can read the item → `needs_manual`, human triage. Never guess a
   replacement key: of 122 wrong keys found, only 63 had both passes agreeing
   on the correction; 4 had NO correct option at all.
4. **Numerical comparison must absorb conventions**: rounding the stem asks
   for, unit differences (kJ vs J, cm vs m), magnitude-vs-signed, "find 10x"
   framings. Compare with the same tolerance rule production grading uses.

## Honest solutions (the part Drona reads aloud)

- The solution must **derive** the verified key, step by step. Banned phrases
  (each found verbatim in production): "consider the possibility of additional
  constraints", "confirming that option X is correct", "which matches the
  given answer", "based on the context, the correct answer is likely".
- Generate the solution AFTER the key is verified, prompted with: *if your
  derivation does not reach the stated option, say so — do not fudge it.*
  Then run an independent honesty check (verdicts: VALID / HANDWAVE /
  CONTRADICTS) and store only VALID. In the audit, 17 of 43 rewrite attempts
  failed this check — and most failures meant the question itself was broken,
  which is exactly the signal you want before a student sees it.
- **Key and solution move together.** If a key is ever corrected, the solution
  MUST be regenerated — a right key with a solution deriving the old answer is
  worse than the original defect.

## Quarantine vocabulary (reuse, don't invent)

`needs_manual` reasons already in use — keep to these so triage stays unified:
`broken_extraction`, `missing_diagram`, `answer_solution_mismatch`,
`options_destroyed`, `table_not_extracted`, `unrenderable_latex`,
`mcq_typed_as_numerical`, `nvq_answer_missing`, `stem_content_hole`,
`metadata_residue`, and the audit tags `audit_wrong_key`,
`audit_unreadable_stem`, `audit_bad_solution`, `audit_options_defective`,
`audit_broken_latex`, `audit_ambiguous_stem`.

## Runnable gate

`scripts/quality_gate.py` in monk-learning-api implements the full pipeline
(lint → blind solve → defence → solution write+honesty check) against any set
of candidate rows. Run it over every extraction batch before clearing
`needs_manual`:

```bash
python3 scripts/quality_gate.py --where "source=eq.<your_batch_tag>"          # dry run
python3 scripts/quality_gate.py --where "source=eq.<your_batch_tag>" --apply  # tag failures, pass survivors
```

It is resumable (JSONL journal), never guesses, and only ever *clears*
`needs_manual` on rows that pass every stage.
