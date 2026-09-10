# Widget gap ledger (W1) — report only, no builds

From `app/drona/concept_archetypes.csv` (1,154 rows: 479 high / 559 med /
105 low / 11 none). A `gap_*` name can never route by design; 294 rows carry
one. Score = concept count × jee∩neet-shared count (`exams == 'b'`).

## Baseline: what routes today (the 90)

479 high-confidence rows; of them the ROUTED set (registered widgets) is:

| widget | concepts |
|---|---|
| labelled_figure | 30 |
| process_flow | 26 |
| xy_plot | 23 |
| reaction_scheme | 21 |
| data_table_trend | 9 |
| field_lines | 4 |
| lines_planes_3d | 4 |
| apparatus | 3 |
| circuit_network | 2 |
| molecule_struct | 1 |
| **total routed** | **123** |

(The "90" of earlier reports counted the pre-labelled_figure promotion state;
labelled_figure's 30 and later promotions carry it to 123. `none_symbolic` —
220 high rows — is prose-only teaching and correctly draws nothing.)

## Top 15 gaps, ranked

| # | gap | n | both | score | nearest widget | verdict |
|---|---|---|---|---|---|---|
| 1 | gap_energy_level | 7 | 6 | 42 | none (xy_plot is axes; this is levels+arrows) | **new: energy_level@1** — Bohr/Rydberg/band ladders, chem11+12 & bio |
| 2 | gap_free_body_diagram | 6 | 6 | 36 | field_lines (arrows) but forces anchor to a BODY, not space | **new: free_body_forces@1** — also what Coulomb's Law needs |
| 3 | gap_motion_graph | 3 | 3 | 9 | xy_plot | **new: motion_path@1** (x-t/v-t families need piecewise+slope annotations xy_plot lacks); in top 5 → W2 builds it |
| 4 | gap_ray_diagram_lens | 3 | 3 | 9 | none | new (ray_diagram family; fold mirror/prism/instrument singletons in — 8 concepts total across the family) |
| 5 | gap_classification_tree | 3 | 2 | 6 | process_flow | **absorb**: process_flow with a `tree` layout param, as field_lines absorbed gaussian |
| 6 | gap_bar_chart | 5 | 1 | 5 | data_table_trend / xy_plot | **absorb**: xy_plot `bars` series type |
| 7 | gap_decision_card | 2 | 2 | 4 | process_flow | absorb (branch node) |
| 8 | gap_vector_resolution | 2 | 2 | 4 | free_body_forces | absorb into W2's widget (components toggle) |
| 9 | gap_potential_energy_curve | 2 | 2 | 4 | xy_plot | absorb (curve + marked extrema/turning points) |
| 10 | gap_mass_element_geometry | 2 | 2 | 4 | none | new, low priority (integration set-up sketches) |
| 11 | gap_flow_tube_diagram | 2 | 2 | 4 | none | new, low priority |
| 12 | gap_heating_curve | 2 | 2 | 4 | xy_plot | absorb (piecewise segments + plateau labels) |
| 13 | gap_piston_cylinder | 2 | 2 | 4 | none | new, low priority (pairs with pv_diagram) |
| 14 | gap_pv_diagram | 2 | 2 | 4 | xy_plot | absorb (closed cycle path + area shading) |
| 15 | gap_energy_flow_diagram | 2 | 2 | 4 | process_flow | absorb (weighted arrows) |

## The one big absorption outside the top 15

`gap_3d_lines_planes` is the LARGEST gap by raw count (13, all single-exam
maths) and `lines_planes_3d` already exists — the classifier itself flagged
"[both passes GAP, names differed]". These 13 are a routing/promotion pass
against the existing widget's schema, not a build. Same family:
gap_feasible_region (7) and gap_argand_diagram (7) are xy_plot-adjacent
(inequality shading; Re/Im axes) and absorbable with one params extension
each.

## Build order that falls out

1. free_body_forces@1 (fixed by directive; rank 2) — W2
2. motion_path@1 (rank 3, in top 5) — W2 continues
3. energy_level@1 (rank 1 by score) — next build after W2
4. Absorption pass: lines_planes_3d ← gap_3d_lines_planes (13);
   xy_plot ← bar/heating/pv/potential-energy/feasible (18 concepts, one
   widget's params); process_flow ← classification/decision/energy-flow (7)
5. ray_diagram family (8) — the one genuinely new family after energy_level
