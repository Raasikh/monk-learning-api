# Directive: HALT the insertion — the figures are attached to the wrong questions

**Do not insert the 43-row tranche. Do not insert anything.** The rows are well-formed,
the keys are verified, the assets uploaded cleanly — and the diagram on most of them
belongs to a different question. This was my error to catch and I caught it after telling
you to ship, so the instruction to ship is withdrawn.

Last round's work was good and none of it is wasted. §5 of this directive credits it.
This section is the problem.

---

## 1. The evidence

### Direct visual confirmation

Row `18cfd6c80f079330`, in the tranche you just uploaded. Stem:

> The value of ∫₀^π (e^cos x · sin x) / ((1+cos²x)(e^cos x + e^−cos x)) dx

Attached figure, now live on the public CDN: **a circle with two tangent lines L₁ and L₂
and labelled points A(−1,2) and B(3,−6).** A coordinate-geometry figure on a definite
integral.

Row `0eb830c69b8aaa41`, `official_verified`, Laws of Motion:

> Two billiard balls of mass 0.05 kg each moving in opposite directions with 10 m/s
> collide and rebound with the same speed…

Attached figure: **a 20Ω / 20Ω / 15Ω resistor network.**

Row `596e510808a42632` is the worst shape. Stem:

> **In the figure**, a very large plane sheet of positive charge is shown. P₁ and P₂ are
> two points at distance l and 2l…

Attached figure: **a 5V battery with a resistor network.** The question explicitly
requires a figure, the required figure is absent, and an unrelated one occupies its slot.

### The root cause, demonstrated

Page 7 of `jee-main-2022-s2-physics-2022-07-25-shift-2` carries exactly two questions:

| qno | stem | assigned crop |
|---|---|---|
| 6 | capacitance of an isolated conducting sphere | `p007_mathpix00.png` |
| 4 | two billiard balls colliding | `p007_mathpix01.png` |

**Neither question needs a figure.** The extractor found figure regions on the page, found
questions on the page, and paired them off positionally. The unit of assembly is the
**page**, not the question.

### Scale

- Three independent blind solvers reviewed 40 rows. **~32 flagged the image as unrelated.**
  Only **4 of 40** returned no quality flag of any kind.
- Of 10 rows sampled *from the tranche you just shipped*, **8 have the wrong figure.**
- **Only 5 of the 43 tranche stems reference a figure at all.** The first six are a
  definite integral, a 3D mirror-image point, a conic parametrisation, a circle in the
  complex plane, a functional equation, and an inverse-function derivative. None of them
  needs a diagram.
- Corpus-wide, **1,722 of 11,579** stems reference a figure — yet all 11,579 carry one.

### Why six rounds of verification missed it

`has_stem_figure` is `True` on **11,577 of 11,579 rows.** It is effectively hardcoded. The
one field that claimed to answer "does this question have a figure?" never tested
anything, so it produced no signal while appearing to provide assurance.

Every other check asked *is the asset present and does the reference resolve?* — and the
answer was always yes. Crops even come from the correct page (13,351 vs 277). Nothing was
broken at the file level. The defect is entirely semantic, and no predicate was
semantic.

---

## 2. This is one bug, not four

Your own §1 finding this round points at the same cause. You diagnosed the 7 leak-letter
disagreements as *"page-boundary mashes where stem/options/answer come from different
questions."* Our blind solvers independently found the same thing: row
`75c5213087abc778` has a physics meter-bridge stem with **chemistry transition-metal-oxide
options**; `0573292ec7d563e8` has a determinants stem with **SHM block-on-block options**.

So: figures paired by page adjacency. Options mashed from page neighbours. Answers
harvested from page text. **Every major defect class in this corpus is the same bug** —
the pipeline assembles a row from fragments that share a page and never verifies they
share a *question*.

Fix the assembly unit and the whole defect family closes. Patching the classes one at a
time will keep surfacing new ones, which is what the last six rounds have been.

---

## 3. What to do

### 3.1 Replace `has_stem_figure` with a real test

Delete the always-true field. A question has a figure only when positive evidence says so:

- a Mathpix `diagram_span` whose vertical extent falls **inside that question's own text
  span** on the page — not merely on the same page; and/or
- the stem referencing a figure (`in the figure`, `as shown`, `the graph`, `shown below`).

`app/mathpix.py` already returns `diagram_spans` with per-figure `top`/`bottom` in image
coordinates, and its own comment says they exist *"for attributing a figure to the question
it belongs to"* and that empty geometry *"must be treated as 'no opinion', never as 'no
figure'."* The geometry is there. It was not used for attribution.

### 3.2 "This question has no figure" is a valid and common outcome

Given 1,722 of 11,579 stems reference a figure, **most rows should end up with no diagram
at all.** That is a correct result, not a failure, and not a reason to attach the nearest
candidate. A row with no figure and clean text is servable. A row with a wrong figure is
not — it is worse than one with none, because the student is shown a diagram that
contradicts the problem.

Never attach a figure as a fallback. Unmatched figure regions stay unattached.

### 3.3 Re-derive attribution for the whole corpus, then verify with vision

Re-run attribution from the stored `diagram_bbox` and question text spans. Then, before
anything ships: sample **at least 50 rows that still carry a figure**, render each figure
with its stem, and have a vision model answer one question — *could this figure plausibly
belong to this question?* Report the pass rate. Nothing ships below 95%.

That check is cheap, it is the only one that would have caught this, and no amount of
structural linting substitutes for it.

### 3.4 The tranche

Keep the R2 objects — keys are deterministic and re-upload is free. Strip the `diagram`
arrays from all 43 rows and re-derive them under §3.1. Expect most of the 43 to end up
with **no** figure; several are pure algebra. Re-present only rows whose figure passes the
§3.3 vision check, plus rows that legitimately have no figure.

---

## 4. Keep this in perspective

The assets do not need re-cutting. Crops are well-scoped (median 211×137), every path
resolves, every file carries sha256 and dimensions, Mathpix runs at 0.98 median
confidence. **The extraction is good. Only the association is wrong.** This is a
re-attribution pass over existing assets, not a re-scrape.

---

## 5. Credited from last round

- 383 contaminated option values truncated — **exactly matching our independent count.**
- Harvest-before-truncate: 305 leak letters captured, **280 of 287 agreeing with the
  stored key.** That is the live confirmation the §1.1 regex fix worked on real data, and
  it is the strongest single piece of evidence produced in this project so far.
- The 7 disagreements correctly diagnosed rather than explained away — and as §2 notes,
  they turned out to be the same root cause as the diagram defect.
- Per-field fidelity battery, with the options guard and scope stated. Count deltas
  (1,362 vs 2,025 marker-complete; 43 vs 48 tranche) stated plainly with their reasons —
  that is exactly the right way to report a disagreement.
- Uploader lost-update race fixed with merge-on-write-back.
- §5 numeric guards verified holding: zero year-shaped values, so the `Answer: 2024`
  false-positive class is genuinely absent.
- The capability acknowledgement is noted and settled.

## 6. Our blind-solve result, for your records

- **Positive control: 10/10 (100%)** recovery on `official_verified` keys — keys sourced
  from the NTA join, independent of anything in the row text. Clean evidence the solver
  genuinely solves this material.
- **Unverified mirror keys: 29/29 agree**, 1 honest UNSURE on a corrupted row.

At n=29 the 95% interval still reaches ~88%, so we will run the remaining 38. But the
mirror keys look accurate, and **keys are no longer the binding constraint — attribution
is.** A correct key on a question showing the wrong diagram is still unservable.

## 7. Reporting

- Attribution outcome for all 11,579 rows: figure attached / no figure / ambiguous, with
  the evidence type that decided each.
- The §3.3 vision pass rate on a ≥50-row sample. This is the gating number.
- How many rows lost their figure, and how many gained the *correct* one.
- Confirmation that `has_stem_figure` is gone rather than recomputed.
