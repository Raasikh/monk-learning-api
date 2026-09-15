# `comparison_table@1` — spec only, build nothing

The largest measured widget gap in the corpus. **15 of 70 segments** in bio 12
"Ecosystem" declined every registered widget and asked for a `comparison_table`
via `diag_hint`; nothing in the registry draws one. It is the single biggest
reason that chapter sits at 75.7% SANE.

This file is a specification. No code is written against it until Raasikh says
build.

## What the board actually wants

Measured from the segments that asked for it, not imagined:

> "Distinguish between species composition and stratification as structural
> features of an ecosystem."
> "Define productivity as a rate of biomass production per unit area per unit
> time and distinguish it from standing crop."
> "Define GPP as the total rate of photosynthesis by producers and identify its
> units."

The shape is always the same: **two or three named things, two to four named
properties, and a short phrase in each cell.** It is not numeric trend data —
`data_table_trend` is for a quantity moving across an ordered axis, and it
refuses text cells, which is correct and is why it cannot stand in here.

## Why this is not `data_table_trend` with strings switched on

`data_table_trend` earns its layout from the numbers: it right-aligns, it uses
tabular figures, and its whole point is that a column of values reads as a
trend. A comparison table has no trend and no ordering — swapping two columns
changes nothing about what it says. Sharing an implementation would mean one
widget whose layout rules contradict themselves depending on a flag, and the
first time they disagreed the board would pick the wrong one.

## Params

    kind          "comparison"                       (reserved; one shape for now)
    columns       2-3 strings, <= 14 chars each      the things being compared
    rows          2-4 strings, <= 18 chars each      the properties compared on
    cells         ONE FLAT array, row-major,
                  length exactly rows x columns,
                  each <= 24 chars
    highlight     null | [row, col]                  one cell the narration is on
    caption       <= 40 chars

`cells` is **one flat row-major array**, not an array of rows. Stated here in
advance because `data_table_trend` shipped the other way round, every model
emitted nested rows, and **0 of 14 stored payloads rendered** until the spec
said this sentence.

## Caps, and where they came from

These are the caps a 343x236 board can hold, derived the way
`reaction_scheme`'s were — from the width budget, not from taste:

  * usable width at 343pt is **319pt** after the board's own padding
  * a 3-column table gives each column ~106pt, which at the board's 13pt body
    face is **14 characters** before the pill clips
  * 4 rows plus a header plus a caption is **5 text bands**; at 236pt with an
    18pt band and 6pt gutters that is the ceiling, so 4 rows is the cap

**The cap is a pre-filter, not the gate.** `reaction_scheme` taught this: its
character caps were raised 10 -> 20 and only **2 of 38** stored payloads moved,
because the real limit was `fitProblems`' width check. This widget must ship
with the same discipline — a `fits()` that measures the actual laid-out table
and refuses, with the measurement in the refusal string so the author can
repair against it.

## Refusals it must make

  * `cells.length != rows.length * columns.length` — the nested-array shape
  * a cell, column or row label over its cap: refuse, and say by how much.
    **Never truncate.** A clipped word in a definitions table teaches a wrong
    definition, which is worse than no table
  * 1 column, or more than 3 — a "comparison" of one thing is not one
  * `highlight` naming a cell outside the grid
  * the laid-out table exceeding the frame at any of the five `GATE_FRAMES`

## Gate, before it can be registered

Everything `conic_plot@1` went through on 2026-09-14, no exceptions:

  1. schema + `validate()` in the client, exposed through
     `scripts/validate-payload.mjs`
  2. verify-render at all five `GATE_FRAMES`
  3. chrome constants from `lib/widgets/chrome.ts`; no invented colours
  4. <= 4 animatable params — realistically `highlight` only, so likely 1
  5. a fixture per shape (2-col, 3-col, with and without highlight)
  6. **fixtures built from payloads the SERVER actually authored**, not only
     hand-written ones. Hand-written fixtures test the widget against the
     author's idea of a payload; the mis-sexed cockroach draft on 2026-09-14
     is what that blind spot looks like in practice

## What it would recover, measured

15 bio 12 Ecosystem segments. Four more want an ecological pyramid
(`docs/ecological-pyramid-spec.md`) and are NOT counted here. The 10 segments
with no `diag_hint` at all are prose-only teaching and correctly draw nothing —
counting those would repeat exactly the error the maths gap ledger had to
correct.
