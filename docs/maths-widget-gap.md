# D3 — the maths gap: what the plan asked for vs what the registry can draw

**No code. A decision note.** Maths 12 ch8 proposed 31 sane / 40 insane (43.7%),
far below the 85% bar, and D3's instruction was to find out *why* before
anyone tunes a payload. Clustered from the 71 measured rows in
`scripts/routing_maths12_ch8.jsonl`.

---

## The shape of it: this is not 40 scattered failures

Routing is **all-or-nothing per subtopic**. Nine concepts, and every one is
either fully served or not served at all:

| subtopic | fired | what happened instead |
|---|---|---|
| area-under-a-simple-curve-bounded-by-the-axes | **9/9** | — |
| area-bounded-by-a-parabola-and-a-line | **7/7** | — |
| area-of-regions-involving-modulus-and-piecewise | **7/8** | — |
| area-between-two-intersecting-curves | 0/9 | svg ×9 |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 0/8 | svg ×8 |
| area-by-integration-along-the-y-axis | 0/8 | svg ×8 |
| area-of-regions-bounded-by-circles-and-ellipses | 0/8 | svg ×8 |
| area-between-a-function-and-its-inverse | 0/7 | svg ×6, text ×1 |
| area-of-regions-described-by-inequalities | 0/7 | svg ×5, text ×2 |

**23 of 71 fire; 47 of the 48 non-fires are six whole concepts.** That matters
for the fix: this is not a tuning job on forty rows, it is six capabilities,
and a concept either gets one or it does not. It also explains the 43.7% —
the chapter is not badly served, it is *unevenly* served.

The three that work are exactly the three whose region is bounded by a
function and the axes, or by a function and a straight line. Every one that
fails needs something else to bound the region.

---

## The registry's own account of itself

The full text the model is given for `xy_plot`:

> y=f(x): area under it, the area between two curves, piecewise/modulus,
> tangent/normal, secant chord … curve/curve2 (line|parabola|sine|exponential|
> reciprocal) … integrate_along … **No circles/regions/panels.**

So the spec **claims** area-between-two-curves and tangent/normal, and
**disclaims** circles and regions. Comparing that against the table above is
where the useful split appears.

---

## Two different failures, and only one is a missing capability

The decline *reason* separates them cleanly, and it was recorded per row:

**A. "widget_cannot_express_concept" — 16 rows, an honest refusal.**
`circles-and-ellipses` (8) and `integration-along-the-y-axis` (8). The model
was asked, consulted the spec, and said no.

- For circles the spec is right and the refusal is correct: `curve` has no
  conic, and the earlier SANE review found the rows that *did* attempt one had
  faked it with a parabola or a hyperbola. **A real capability gap.**
- For the y-axis the spec says `integrate_along` exists — and the model still
  declined all 8. That is the spec advertising a parameter the model does not
  believe it can use. **Not a capability gap; a spec/prompt gap.**

**B. "model_chose_no_widget" — 31 rows, the model never engaged.**
`intersecting-curves` (9), `tangent-or-normal` (8), `inverse` (7),
`inequalities` (7). The spec claims two of these four outright. The model did
not decline them — it simply did not reach for the widget, and drew an SVG.

That distinction is the finding. **Build-shaped work is a minority of the
47.**

---

## The three capabilities, and what each recovers

Ranked by rows recovered per unit of build.

### 1. Region bounded by two curves, with the intersections solved — ~24 rows (34% of the chapter)

Covers `intersecting-curves` (9), `inverse` (7), and most of `inequalities`
(7). `curve2` exists and `area_between` is a mode, but nothing solves for
where the curves *meet*, so the author must supply `shade_from`/`shade_to` by
hand — and for two intersecting curves those limits **are the answer to the
problem being taught**. A widget that makes the teacher compute the thing the
diagram is meant to reveal is one a model will avoid, which is exactly what
31 "chose no widget" rows look like.

The inverse case is this plus one line: `f`, `f⁻¹` and `y = x`, reflected.

**Estimated recovery: 20–24 rows.** Highest return, and the least new drawing
— the renderer already shades; it needs to be told where by solving rather
than by being told.

### 2. Conic sections — circle and ellipse — ~8–12 rows (11–17%)

Covers `circles-and-ellipses` (8) outright and unlocks the circle-bounded
members of `inequalities`. Needs a genuine new curve kind: a circle is not a
function of x, so it cannot join the `line|parabola|sine|exponential|
reciprocal` family without the renderer learning to draw and shade a
non-functional boundary.

**Estimated recovery: 8–12 rows.** Clean, self-contained, and the spec already
tells the truth about not having it — so the model will start using it the day
it exists.

### 3. Tangent/normal as a *boundary* of the shaded region — ~8 rows (11%)

Covers `tangent-or-normal` (8). `tangent_kind` already **draws** a tangent;
what is missing is the tangent participating in the region — the area between
a curve and its own tangent is bounded by both. The earlier SANE review found
seven of these segments drawn with the tangent absent entirely, which fits: the
model had no way to express "bounded by this line I just drew".

**Estimated recovery: ~8 rows.** Smallest build of the three, and it extends a
parameter that already exists rather than adding a new one.

---

## The free one, and it is not a build

**`integrate_along: 'y'` — 8 rows, already in the schema.**

The spec lists it; the model declined all 8 y-axis segments as
*cannot express*. Before anything is built, someone should find out which is
true:

- the parameter works and the spec describes it too thinly for the model to
  trust — a prompt fix, an afternoon; or
- it is in the schema and does not render correctly — a bug, and one that
  would have shipped silently, because no row exercises it today.

Either way it is **8 rows (11%) for no new capability**, and it is the first
thing to check. It would move the chapter from 43.7% to roughly 55% on its
own.

---

## What this adds up to

| change | rows | chapter share | shape |
|---|---|---|---|
| resolve `integrate_along:'y'` | 8 | +11% | prompt fix or bug fix |
| region between two curves, intersections solved | 20–24 | +28–34% | build |
| conics (circle, ellipse) | 8–12 | +11–17% | build |
| tangent/normal as a boundary | 8 | +11% | small build |

Doing the free one plus capability 1 is enough to clear 85% for this chapter.
All four would take it close to complete.

**Two cautions before choosing.**

This is **one chapter**. Capability 1 is plainly general — area between curves
is the whole of Application of Integrals and recurs in physics work-done
problems. Conics may be narrower than they look: worth checking the archetype
column for how many other concepts across maths would route to a circle before
building one.

And the 43.7% is a *proposal*. Those SANE verdicts were produced by a reviewer
that never saw the narration — the harness does not capture speech — and they
are not confirmed. If the split above changes anyone's mind about what to
build, the flagged rows deserve a look first.

---

**Stopping here, as directed. Raasikh chooses which capability to build;
nothing in maths is built until he does.**
