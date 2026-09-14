# `conic_plot` — proposed widget spec

**Params only. Nothing is built.** Written so the decision to build can be made
against a concrete shape rather than a description of a shape.

The gap it closes is the only one in maths 12 ch8 that the widget says of
itself it cannot draw: `area-of-regions-bounded-by-circles-and-ellipses`, 8 of
71 rows, measured 2026-09-13 (`docs/maths-widget-gap.md`).

## Why this is not a new `curve` kind on `xy_plot`

`xy_plot`'s whole geometry is `v = f(u)` — one value per integration
coordinate, shaded by a difference of antiderivatives. A circle has **two**
values of y for most x, and the region between a chord and an arc is not the
difference of two functions over an interval. Adding `circle` to
`curve` would mean either a silently wrong picture or a second geometry engine
living inside a widget whose header says it has one. The conic belongs in its
own module for the same reason `named-curves.ts` is separate: a shape the book
prints without a formula is a different kind of object.

## Params

```
kind            "circle" | "ellipse" | "parabola" | "hyperbola"     required
a, b            semi-axes. circle: a = r, b ignored. parabola: y² = 4ax.
                hyperbola: x²/a² − y²/b² = 1.
cx, cy          centre (circle/ellipse/hyperbola) or vertex (parabola). default 0,0
rotate_deg      0 | 90 | 180 | 270 only — the four the syllabus prints.
                Arbitrary rotation needs a rotated quadratic form and no NCERT
                figure in scope asks for one.

show            array from: "foci" | "directrix" | "axes" | "vertices" |
                "latus_rectum" | "asymptotes"   (asymptotes: hyperbola only)
                Named individually rather than a single "annotate" flag because
                a segment teaching the directrix and one teaching the foci want
                different pictures of the same conic.

region          null | "interior" | "chord" | "with_line" | "with_conic"
line_a, line_b, line_c     the line ax + by = c, when region needs one
other           a nested conic (kind/a/b/cx/cy), when region = "with_conic"
shade           bool — fill the named region
area_readout    bool — print the region's exact area

x_min,x_max,y_min,y_max    view box; omitted means fit the conic with margin
x_label, y_label, caption  as elsewhere. caption max 40 chars.
highlight       -1 none, else index into `show`
```

## Animatable — four, and these four

`xy_plot`'s cue track allocates a fixed pool of four, and the same ceiling
applies here.

1. `a` — the semi-major axis. The one that shows eccentricity changing.
2. `b` — the semi-minor axis.
3. `line_c` — slides the chord across the conic, which is how "the area cut off
   by a chord" is taught.
4. `rotate_deg` — the only genuinely discrete one; it steps, and a cue that
   tweens it must snap.

Deliberately NOT animatable: `kind`, `region`, `show`. Changing any of those
mid-tween changes what the picture *is*, and the scaffolding-invariance rule
says the frame must not move while the values do.

## Derived

`area`, `eccentricity`, `focal_distance`, `latus_rectum_length`. All four are
closed-form, so `computeDerived` is arithmetic rather than quadrature — which
is the point of a dedicated conic widget over a numerical one.

## Caps, from the failure this project already had

`reaction_scheme` shipped without character caps in its spec and 30 of its 38
stored payloads could not be drawn. So, stated up front and enforced by
`validate()`:

* every label at most **12 characters**; `caption` at most **40**
* at most **6** entries in `show`
* `a`, `b` finite and > 0; `a ≥ b` for an ellipse, refused rather than swapped
* the view box must contain the conic, or `validate()` refuses — a conic drawn
  half outside its frame is the "renders, but wrong" failure that no gate
  catches unless it is checked here

## What it does not do

No conic through five points, no general `Ax² + Bxy + Cy² + Dx + Ey + F = 0`,
no 3-D sections of a cone. Each is a different teaching object and a bigger
build, and none of the 71 measured segments asks for one.

## Estimated recovery

**8 rows outright** — the whole of `area-of-regions-bounded-by-circles-and-
ellipses`, which is the only subtopic the widget itself declines.

Possibly some of `area-of-regions-described-by-inequalities` (7 rows), whose
regions are often circle-bounded. **Not counted**, because those rows are
`model_chose_no_widget` and nothing measured so far explains that class —
counting them would repeat the exact error the maths note was rewritten to
correct.
