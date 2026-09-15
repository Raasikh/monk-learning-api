# `ecological_pyramid@1` — spec only, build nothing

**4 segments** in bio 12 "Ecosystem" ask for a trophic pyramid and no
registered widget draws one. Smaller than the `comparison_table` gap (15) but
sharper: an ecological pyramid is a NEET set-piece with a specific trap, and
the trap is the reason the figure exists at all.

This file is a specification. No code is written against it until Raasikh says
build.

## The segments, quoted

> "Describe the three types of ecological pyramids and identify which can be
> inverted."
> "Explain why energy flow in an ecosystem is unidirectional and non-cyclic,
> using the first and second laws of thermodynamics."
> "State the percentage of incident solar radiation that is PAR and the
> percentage of PAR that producers capture."
> "List the limitations of ecological pyramids and avoid common exam errors."

## The trap, which decides the whole design

**A pyramid of energy is ALWAYS upright. A pyramid of biomass or of numbers can
be INVERTED.** The standard examples are a pond ecosystem (inverted biomass:
small producer standing crop supporting a larger consumer mass) and a single
tree with its insects and birds (inverted numbers).

So the widget must be able to draw an upside-down pyramid, and it must refuse
to draw one for `kind: "energy"`. A widget that can only draw a triangle
narrowing upward cannot teach this chapter — it can only teach the half of it
that is easy.

## Params

    kind        "energy" | "biomass" | "numbers"
    levels      3-5 tiers, BASE FIRST (producers at index 0)
    labels      one per level, <= 16 chars      e.g. "producers", "primary consumers"
    values      one per level, finite, > 0      the width of each tier
    units       <= 10 chars                     "kcal/m2/yr", "g/m2", "count"
    inverted    bool                            a tier wider than the one below it
    show_ten_percent  bool                      the 10% arrows between tiers
    caption     <= 40 chars

`values` drives tier WIDTH directly rather than being a decoration on a fixed
triangle. That is what makes an inverted pyramid a data statement instead of a
drawing mode.

## Refusals it must make

  * `kind: "energy"` with `inverted: true`, **or with any tier wider than the
    one below it** — refuse and say so. This is the one refusal the widget
    exists for: an inverted energy pyramid violates the second law, and drawing
    one on a board teaches the exact error the segment is warning against
  * fewer than 3 or more than 5 levels — below 3 it is not a pyramid; above 5
    the tiers fall under the 18pt band minimum at 236pt
  * `labels.length != levels` or `values.length != levels`
  * a non-finite or non-positive value — a zero-width tier is not a tier
  * `show_ten_percent: true` on a `numbers` or `biomass` pyramid: the 10% law
    is about ENERGY. Drawing it between biomass tiers asserts something false

## Caps, and where they came from

  * usable width at 343pt is **319pt**; the widest tier takes 300pt and the
    narrowest must stay >= 40pt or its label has nowhere to sit, which caps the
    drawable ratio at about **7.5:1**. A real energy pyramid spans three orders
    of magnitude, so the widget must either draw tiers on a compressed scale
    and SAY SO in the readout, or refuse. It must not silently compress — a
    pyramid whose tiers are not to scale, presented as if they were, is the
    same class of defect as the caption describing a figure that is not there
  * 5 tiers x 18pt + 4 gutters x 6pt + caption = 138pt, inside 236pt

## Gate, before it can be registered

The full `conic_plot@1` gate: schema + `validate()` through
`scripts/validate-payload.mjs`, verify-render at all five `GATE_FRAMES`, chrome
constants only, <= 4 animatable params, a fixture per `kind` **plus one
inverted biomass pyramid and one refused inverted energy pyramid**, and
fixtures built from payloads the server actually authored.

## What it would recover, measured

4 bio 12 Ecosystem segments. Not to be added to `comparison_table`'s 15 — they
are different segments, and the two specs together cover 19 of the 35 that
currently fire nothing. The remaining 16 are 6 that wanted `process_flow`
(which exists, and the model declined it anyway — a routing question, not a gap)
and 10 prose-only segments that correctly draw nothing.
