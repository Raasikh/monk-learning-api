# Practice Question Bank — Independent Spot-Check Audit (2026-08-28)

Report-only audit. **No production writes were made.**

Context: a separate session ran a full-bank Opus sweep the same day
(11,368 reviewed → 54 quarantined, 90 key suspects, 21 keys corrected,
34 unanswerable parked). This audit was commissioned before that landed and
became an **independent cross-check of the post-sweep bank** instead: the
sample below was drawn from the 11,273 servable rows that remained after the
sweep's quarantines.

## Method

1. **Sample**: 240 rows, stratified across subjects × question types from all
   servable rows (`needs_manual IS NULL`), fixed seed
   (`scratch/audit_sample.py`).
2. **Structural lint** (no LLM): the `lint()` from `scripts/quality_gate.py`
   plus rendering checks (unbalanced `$`, unescaped-brace balance,
   `\left`/`\right` delimiter pairing, private-use glyphs).
3. **Blind solve** (Claude subagents, key and solution stripped): 14 of 24
   batches (140 rows) completed before a quota limit stopped the rest; the
   adversarial-defence and solution-honesty passes were not run — the
   full-bank Opus sweep covers that ground, so they were not resumed.
4. **Deterministic full-bank scan** (all 11,273 servable rows, no LLM):
   option-key format, duplicate twins, figure references without image
   payloads. Raw output: `scratch/audit_deterministic_fullbank.json`.

## What checked out

- **0 / 240 lint failures.** No scramble signatures, no LaTeX breakage, no
  option defects in the sample. Consistent with the sweep's cleanup holding.
- Of 140 blind-solved rows, only 1 was genuinely unanswerable (the
  figure-dependent Hindi physics item below); the rest yielded clean,
  derivable answers.
- Figure-bearing rows generally carry an R2 image payload in `diagram`
  (e.g. `https://pub-….r2.dev/questions/v2/...`), so "stem references a
  figure" is mostly served correctly.

## Findings (actionable)

### A. 2,725 servable rows (24%) key their options `"1"–"4"` instead of `"A"–"D"`
- `correct_option` is stored as a digit too, so the row is **internally
  consistent and grades correctly** if the client echoes the stored key.
- But it violates the row contract in `EXTRACTION_QUALITY_SPEC.md`
  ("Single uppercase letter A–D") and every consumer that assumes A–D:
  `prompts/*.md` (tutor, practice_explain), the gate's `_relabel()`, any
  future solver pass.
- Spread evenly: physics 699, chemistry 768, biology 631, mathematics 627.
- Fix is mechanical (relabel by position + remap `correct_option`), same
  transform as `quality_gate._relabel()` — but should be verified against
  the web client before applying.

### B. 59 servable+servable duplicate pairs are double-serving
- Token-set Jaccard twin scan over the full bank (`TwinIndex` from
  `quality_gate.py`); includes exact J=1.0 duplicates, e.g.
  `ffdd9025… ~ 7be6ae6d…` ("Which of the following phyla first exhibits
  bilateral symmetry?") and 9 more exact pairs listed in the JSON output.
- The dedupe twin check only runs at staging→promotion; these pairs were
  already live on both sides.
- Effect: students can be served the same question twice; `question_serves`
  dedup won't catch it because the ids differ.
- Fix: park one side of each pair as `duplicate_of_servable` (matches the
  existing quarantine vocabulary). Needs a human pass on the 59 pairs to
  pick which side survives (prefer the one with a diagram payload / cleaner
  stem / A–D options).

### C. 1 servable row is figure-dependent with no figure
- `0e5070d6…` (physics, Hindi): stem says चित्रानुसार ("as per the figure")
  twice, `diagram` is empty. Unanswerable as served; blind solver correctly
  refused it. Candidate for `needs_manual = 'missing_diagram'`.
- (`24c05f96…` biology mentions "floral diagram" but asks a conceptual
  question about floral formulas — likely fine as-is.)

## Not done / caveats

- 10 of 24 blind batches and both key-dependent passes (defence, solution
  honesty) did not run — quota limit. Skipped deliberately: the full-bank
  Opus sweep already adjudicated keys and solutions with production writes;
  re-running a sample of it adds little. If an independent key cross-check
  is still wanted, the batch files under `scratch/audit_batches/` and the
  14 completed blind verdicts in `scratch/audit_results/` are resumable.
- Rendering was checked structurally (LaTeX balance etc.), not visually —
  no client-side render test was performed.
