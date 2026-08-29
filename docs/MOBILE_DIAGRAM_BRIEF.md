# Rendering board diagrams in the MonkLearning mobile app

Hand this to the session working on the app. Written 2026-08-29.

## What you are receiving

Board diagrams arrive over the live-session WebSocket as one board event:

```json
{ "seq": 4, "type": "diagram", "svg": "<svg xmlns=... viewBox=\"0 0 340 240\">…</svg>",
  "caption": "optional one-liner" }
```

The `svg` is **complete, static, self-contained markup**. No external references,
no scripts, no fonts to load, no network calls. Render it as-is. The API has
already validated it — see "What is guaranteed" below.

The web app's reference implementation is
`monk-learning-web/src/components/PremiumBoardEvent.tsx`. Match its behaviour;
you do not have to match its code.

## What is guaranteed about every SVG

These are enforced server-side by `app/drona/diagram_author.validate()`, and a
diagram failing any of them is dropped rather than sent. You can rely on them:

- Elements are only: `path, line, polyline, polygon, circle, ellipse, rect, text, g`
- **No** `<defs>`, `<marker>`, `<script>`, `<image>`, `<foreignObject>`, `<use>`,
  no `href`/`xlink:href`, no `on*` attributes, no `font-family`
- An explicit `viewBox`, always starting at `0 0`
- Under 14,000 characters and under 110 total elements
- Every colour is one of exactly nine hex values (listed below)
- Well-formed XML
- No two text labels overlap (checked geometrically)

## Three things you MUST do to it

### 1. Remap the colours

The generator emits a neutral palette. Every colour must be swapped for the
house one or the diagram will clash with the board. This is a literal string
replace — the exact table the web app uses:

```
#ffffff -> transparent     ← background rects; let the paper show through
#1f2933 -> #1C1A16         ink
#2563eb -> #9A6A12         blue     -> deep amber
#dbeafe -> #FCF4E0         pale blue fill -> cream
#64748b -> #9C988C         muted
#f1f5f9 -> #FFFEFB         pale grey fill -> cream-soft
#d97706 -> #B87A14         amber
#dc2626 -> #DD4433         red
#059669 -> #157A45         green
```

`#ffffff -> transparent` is the one that surprises people. Skip it and every
diagram sits on a white card instead of the cream board.

### 2. Set the font

The SVG carries **no** `font-family` — deliberately, so the host app decides.
Apply the app's own body font to all `<text>`. On web that is Anek Latin.

### 3. Size it for the column, not the canvas

The SVG must scale to the width of its container, height auto, preserving
aspect ratio. On web: `svg { width: 100%; height: auto }`.

## The sizing maths, which is why diagrams are drawn small

This is the part worth understanding rather than copying, because it decides
whether labels are readable.

Diagrams are authored on a **340x240** canvas with **15-17px labels**. Those
look oversized next to a 340-wide canvas on purpose: the SVG scales down to
whatever column you give it, and the labels scale with it.

Measured on a 375px phone through the web layout:

```
viewport                       375px
- board padding                 -56  ->  319px
- diagram container padding     -16  ->  303px   the SVG's real width
340 canvas -> scale 0.89 -> a 15px label renders at 13.4px    readable
```

The earlier version used a 380-520 canvas with 11-13px labels and rendered
labels at **7-9px on a phone** — unreadable. That is the trap.

### Landscape inverts this — and the app is landscape

Everything above assumes PORTRAIT, where width is scarce. In landscape the
constraint flips to HEIGHT, and the advice flips with it. On an 812x375 phone
the board gets ~740px of width but only ~285px of usable height, so a
1.42-aspect figure at full width renders 522px tall and overflows.

**In landscape, size by HEIGHT and let width follow:**

```css
svg { max-height: 100%; width: auto; max-width: 100%; }
```

The app team measured this independently and landed on capping a figure at 72%
of visible board height, which puts it near 354pt wide — above the 300px floor
below, so no retune of DETAIL_LEVELS is needed.

**So the rule for portrait: give the diagram as much width as you can.**
Every 16px of horizontal padding costs about 5% of label size. The web app
dropped its diagram padding from 36px to 8px on mobile for exactly this reason.

If your column ends up much narrower than ~300px, tell the API team — the
canvas and label sizes are two constants in
`app/drona/diagram_author.py` (`DETAIL_LEVELS` and the `STYLE_SPEC` style
section) and can be retuned. Do not try to fix it by scaling text in the app;
that breaks the layout the author computed.

## The draw animation, if you want it

The web app animates each element in document order — strokes draw via
`stroke-dasharray`/`stroke-dashoffset` over their `getTotalLength()`, text fades
in. Document order IS the intended drawing order: outline, then internal
structure, then arrows, then labels.

```
TOTAL_BUDGET = min(7000, max(1800, steps * 120))   // ms
per_step     = max(60, TOTAL_BUDGET / steps)
```

**This is optional.** A diagram that simply appears is correct and much simpler.
If you skip the animation, nothing else changes. If you implement it, keep the
`max(60, …)` floor — without it a dense diagram flickers.

## What NOT to do

- **Do not sanitise creatively.** The server already stripped everything unsafe.
  An over-eager filter that removes `<g>` or attributes it does not recognise
  will silently break diagrams — and every failure mode here is silent, which is
  why the server validates rather than trusting.
- **Do not re-layout the SVG.** The author computed positions against the
  viewBox. Moving or re-wrapping text will cause the overlaps the server just
  spent effort preventing. If a label sits badly, report it rather than moving
  it — the fix belongs in the authoring spec or the validator.
- **Do not set `font-size` yourself.** It is on each `<text>` already and is
  load-bearing for the sizing maths above.
- **Do not clip.** The web app sets `overflow="visible"` because a label can
  slightly exceed the viewBox. Clipping cuts labels off mid-word.

## Coverage — set expectations accordingly

As of today, of 1,154 concepts:

```
  8  ( 0.7%)  have a precomputed diagram   (Class 11 Physics ch 1 only)
191  (16.6%)  match a template cue
955  (82.8%)  have no diagram at all
```

So **most turns carry no diagram event**, and the board must look right without
one. Build the diagram path as an enhancement to a text board, never as
something the layout depends on.

Class 11 Physics chapter 1 ("Units & Measurements") is the chapter to test
against — all 8 of its concepts have one.

## A quick test fixture

Any stored diagram works as a fixture:

```sql
SELECT c.name, d.svg
  FROM concept_diagrams d
  JOIN concepts c ON c.id = d.concept_id
 WHERE d.active
 ORDER BY c.teach_order;
```

Render one at 300px wide and check: cream background (not white), house amber
rather than blue, labels legible at arm's length, nothing clipped at the edges.
