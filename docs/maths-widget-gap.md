# Maths 12 ch8 — what routes, what does not, and the one real gap

**Rewritten 2026-09-13 from `scripts/routing_maths12_ch8_e5.jsonl` only.**
Every earlier version of this file is superseded. The one before it was built
on a label the measurement harness wrote for itself, and it recommended
building two capabilities that already existed — see "What the old version got
wrong" at the end, which is kept because the mistake is more instructive than
the conclusion.

## The measurement

71 segments, every one reaching the model. **24 fired a widget (33.8%).**

| subtopic | fired | verdict |
|---|---|---|
| area-under-a-simple-curve-bounded-by-the-axes | **9/9** | — |
| area-of-regions-involving-modulus-and-piecewise | **8/8** | — |
| area-bounded-by-a-parabola-and-a-line | **7/7** | — |
| area-between-two-intersecting-curves | 0/9 | model chose no widget |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 0/8 | model chose no widget |
| area-by-integration-along-the-y-axis | 0/8 | model chose no widget |
| area-of-regions-bounded-by-circles-and-ellipses | 0/8 | **widget cannot express** |
| area-of-regions-described-by-inequalities | 0/7 | model chose no widget |
| area-between-a-function-and-its-inverse | 0/7 | model chose no widget |

**Routing is all-or-nothing per subtopic.** Nine subtopics, and every one is
either fully served or not served at all. That has survived three
measurements and is the most useful single fact here: this is not forty
scattered rows to tune, it is six capabilities, and a concept either gets one
or it does not.

The three that work are exactly those whose region is bounded by a function
and the axes, by a function and a straight line, or by pieces of functions.
Everything that fails needs something else to bound the region.

## The split that matters

**39 rows: `model_chose_no_widget`.** The model was shown `xy_plot`, did not
decline it, and drew an SVG instead. No verdict was recorded because the model
gave none.

**8 rows: `widget_cannot_express_concept`** — all of them
`area-of-regions-bounded-by-circles-and-ellipses`. This is now the ONLY
subtopic carrying that label, and it is the only one where the label is the
widget's own account of itself: `curve` offers
`line|parabola|sine|exponential|reciprocal` and nothing conic.

## What is NOT the problem — each tested, each negative

These were measured rather than reasoned about, because the previous version
of this document reasoned and was wrong.

* **`integrate_along:'y'` is not missing.** It shipped with v3, it is
  validated, six test files exercise it, and 206 xy-plot tests pass. Its
  subtopic still fires 0/8.
* **The spec wording is not the blocker.** Spelling `integrate_along` out in
  the registry spec: 0/8, no change. Replacing the blunt
  "No circles/regions/panels" with a precise statement of what the widget can
  and cannot draw: 0/8, no change.
* **A precomputed example SVG does not suppress the widget.** Rows that have
  one fire *more* often — 36.5% against 21.1%.
* **The `conic_figure` diagram hint does not suppress it either.** That hint
  fires 31% across the chapter.

So for those 39 rows the cause is not yet isolated, and this document does not
pretend otherwise. **They are not free and they should not be budgeted as
though a prompt change will recover them.**

## The one real gap: conics

Eight rows, and the only ones the widget itself says it cannot draw. A circle
is not a function of x: it needs upper and lower branches and segment
arithmetic, not a difference of antiderivatives. The earlier SANE review found
that the rows which *did* attempt one had faked it with a parabola or a
hyperbola, which is worse than declining.

The proposed spec is in **`docs/conic-plot-spec.md`**. Nothing is built.

**Estimated recovery: 8 rows outright (11% of the chapter), plus an unknown
part of `area-of-regions-described-by-inequalities` (7 rows) whose regions are
often circle-bounded.** Deliberately not claimed as a range beyond that: the
inequalities rows are `model_chose_no_widget`, and nothing above explains that
class, so counting them would be the same error this document is correcting.

## What the old version got wrong, and why it is recorded here

It read `widget_cannot_express_concept` on 16 rows as "the model was asked,
consulted the spec, and said no". The label was never the model's. It came
from a hardcoded set in `scripts/measure_widget_routing.py`:

```python
if rec["subtopic_key"] in CANNOT_EXPRESS:
    return "widget_cannot_express_concept"
```

whose own comment promised it was "copied from the widget rather than
re-derived, so the classifier and the widget agree by construction". The
widget moved to v3; the set did not. Two of its three entries were stale —
`integrate_along` is the transpose flag one of them asked for, and `pieces` is
the breakpoint array the other asked for — so this document recommended
building both. The set now contains only circles-and-ellipses, and
`area-of-regions-involving-modulus-and-piecewise` promptly measured **8/8**,
which is what a capability that already exists looks like.

The lesson is not "check the harness". It is that a derived label read as
evidence, and nothing in the pipeline distinguished a verdict the model gave
from a verdict the harness supplied.
