# `apparatus` — a gap with no spec, found by H7

One row, and it had nowhere to go.

`electric-field-lines` seg 6 (physics 12 ch1):

> Explain how a gold-leaf electroscope detects charge and why quantisation is not noticeable at macroscopic scales.

The sheet calls this **the strongest decline-where-a-picture-was-needed case**
in its chapter: the board text is pure apparatus — a gold-leaf electroscope,
its disc, rod, leaves and case — and nothing was drawn at all.

## Why it has no home

`apparatus` appears in `concept_archetypes.csv` as a named archetype with 3
concepts behind it, and the widget gap ledger lists it under "what routes
today". **It is not in the registry.** The twelve registered widgets are
projectile_motion, molecule_3d, field_lines, free_body_forces, xy_plot,
data_table_trend, process_flow, reaction_scheme, molecule_struct,
circuit_network, conic_plot and lines_planes_3d. An archetype naming
`apparatus` therefore routes to nothing, and the concept falls to tier 3.

That is worth stating on its own: **a column value that names no widget is
indistinguishable, at the point of resolution, from a concept that wants no
picture.** The ledger's "routed" count includes it, which overstates coverage.

## What it is not

Not `circuit_network` — an electroscope is not a circuit, and drawing it as one
would assert current where there is none. Not `free_body_forces` — nothing is
in equilibrium. Not `labelled_figure` either, unless someone draws the plate,
at which point it is an illustration and not a widget at all.

## The cheapest honest answer first

Before anything is built: **an electroscope is a plate.** It is a fixed piece of
apparatus with named parts, which is exactly what the illustration pipeline
exists for, and a Gemini plate plus a pointed label set would serve this
segment completely. The other two `apparatus` concepts should be looked at the
same way before a widget is specified — a widget earns its place by being
PARAMETRIC, and apparatus with fixed parts may simply not be.

**Nothing is built. This file exists so the row is not lost.**
