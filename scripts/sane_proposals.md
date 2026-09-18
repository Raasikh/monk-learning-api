# SANE proposals

> **GENERATED FILE — do not edit.** The source of truth is
> `content/sane-rows.json`; this is rendered from it by
> `scripts/render_sane_sheet.py`. Nothing parses this file.
>
> It used to be the other way round, and reading verdicts out of prose
> failed four times in two sessions — a widget read from the wrong place,
> a lowercase `**objective:**`, an abbreviated subtopic, a truncated key.
> Every one returned a confident empty result rather than raising.

Migrated 2026-09-17. Key: `verdict_key = sha256(normalised objective)[:16] + ':' + widget_id`.

## Buckets

| bucket | rows | y | n | meaning |
|---|---|---|---|---|
| carried | 8 | 0 | 8 | same question, same widget — the verdict still applies |
| reconfirm | 14 | 0 | 14 | reworded; the changed words are listed per row |
| superseded | 62 | 4 | 58 | the question is no longer asked anywhere |
| unkeyable | 210 | 206 | 4 | the sheet never recorded the objective — archive |

210 rows carry no objective because the sheets quote one only in the per-row prose sections, and those exist only for n rows. 206 of the 210 are y verdicts. They are ARCHIVE: we know the subtopic, the index and that a reviewer said y, and we cannot tie that to a current question. They drive nothing — the hold-back reads the chapter percentage, which lives in content/sane-verdicts.json — so nothing is lost by not re-judging them. The 4 unkeyable n rows are archived on Raasikh's line of 2026-09-17.

## physics 12 ch1 — Electric Charges and Fields

proposed y: 32 ; proposed n: 8 (of 40)

| subtopic_key | seg | widget judged | verdict | bucket | verdict_key |
|---|---|---|---|---|---|
| electric-charge-properties-quantisation-and-charging | 1 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-charge-properties-quantisation-and-charging | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-charge-properties-quantisation-and-charging | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-charge-properties-quantisation-and-charging | 4 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-charge-properties-quantisation-and-charging | 5 | decline | n | reconfirm | `44ce30c96717cdd7:decline` |
| electric-charge-properties-quantisation-and-charging | 6 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-charge-properties-quantisation-and-charging | 7 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-charge-properties-quantisation-and-charging | 8 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-field | 1 | decline | n | superseded | `4c15b779bff4f8b6:decline` |
| electric-field | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-field | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-field | 4 | decline | n | superseded | `f726103d590e0ac0:decline` |
| electric-field | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-field | 6 | decline | y | superseded | `3e8a6e3031e61d0e:decline` |
| electric-field | 7 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-field | 8 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-field-lines | 1 | decline | y | superseded | `4c15b779bff4f8b6:decline` |
| electric-field-lines | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-field-lines | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-field-lines | 4 | decline | n | superseded | `b7b3aaff4a508d9c:decline` |
| electric-field-lines | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-field-lines | 6 | decline | n | superseded | `3e8a6e3031e61d0e:decline` |
| electric-field-lines | 7 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-field-lines | 8 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| electric-field-lines | 9 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| equilibrium-of-charges | 1 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| equilibrium-of-charges | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| equilibrium-of-charges | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| equilibrium-of-charges | 4 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| equilibrium-of-charges | 5 | decline | n | superseded | `1243bc5ca02942fe:decline` |
| equilibrium-of-charges | 6 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| equilibrium-of-charges | 7 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| equilibrium-of-charges | 8 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| gauss-s-law-and-its-applications | 1 | field_lines | y | unkeyable | `e3b0c44298fc1c14:field_lines` |
| gauss-s-law-and-its-applications | 2 | field_lines | y | unkeyable | `e3b0c44298fc1c14:field_lines` |
| gauss-s-law-and-its-applications | 3 | field_lines | y | superseded | `06b87c9d99c5ddb7:field_lines` |
| gauss-s-law-and-its-applications | 4 | field_lines | y | superseded | `9f37661dae2b0617:field_lines` |
| gauss-s-law-and-its-applications | 5 | field_lines | y | unkeyable | `e3b0c44298fc1c14:field_lines` |
| gauss-s-law-and-its-applications | 6 | field_lines | n | superseded | `c14362a81b017129:field_lines` |
| gauss-s-law-and-its-applications | 7 | field_lines | n | superseded | `5163e4dd1f075714:field_lines` |

### the 8 n rows that can still be acted on

#### `electric-charge-properties-quantisation-and-charging` seg 5 — reconfirm

**objective:** Describe charging by friction and conduction, including charge sharing between identical conductors.

**widget judged:** `decline`

**reworded (0.907):** `` -> `sign of charges and`

**reason:** (a) and (b). (a) A free-body diagram is a force diagram; its arrows are read by students as forces. Electron *transfer* is not a force, so the template mis-teaches the quantity being drawn. (b) The parameters also contradict the board text directly: the board says "glass loses electrons → positive; silk gains them → negative", i.e. a one-directional transfer *off* the glass rod, but the diagram puts both an "e⁻ out" and an "e⁻ in" arrow on the single body labelled "glass rod". The caption ("leave glass, enter silk") describes two different bodies while the figure has one.

#### `electric-field` seg 1 — superseded

**objective:** Explain why the electric field concept is needed and how it resolves the action-at-a-distance problem.

**widget judged:** `decline`

**reason:** (a). The segment is conceptual and its board text is explicit about the mechanism it wants pictured: "The field concept splits the interaction into two stages: a charge modifies the space around it … a second charge responds to the field at its own location." The picture drawn is a component-resolution triangle — a computational device for a later, different skill. It shows neither the two-stage mechanism nor the action-at-a-distance problem. Nothing on this board mentions components or angles.

#### `electric-field` seg 4 — superseded

**objective:** Interpret electric field line diagrams and state the four rules they obey.

**widget judged:** `decline`

**reason:** (a). This is the clearest wrong-widget case in the set. The objective is *literally* "interpret electric field line diagrams", and `field_lines` is an existing widget whose `configuration:"point"` draws exactly this. Instead an FBD is bent into four arrows to imitate a radial field. The board text says "the density of lines gives its magnitude" — a four-arrow FBD has no line density to read, so the figure cannot support the rule the board just stated. (Caveat: this subtopic is `electric-field`, routed as *med / gap_dipole_field_geometry*, so the archetype column was never going to route anything here; the defect is in the fallback template choice, not in the archetype gate.)

#### `electric-field-lines` seg 4 — superseded

**objective:** Describe the outcomes of charging by friction and by conduction, including the sign of charge acquired.

**widget judged:** `decline`

**reason:** (a). Same category error as item 1: a force template used to depict electron transfer, so the single arrow reads as a force on the glass rod. The objective's actual payload — "the sign of charge acquired" — is what needs picturing, and an FBD cannot carry sign. `process_flow` (which this same subtopic used correctly in seg 1 for exactly this idea) would have been the right template. Less severe than item 1 because the single arrow at least does not contradict the direction stated on the board.

#### `electric-field-lines` seg 6 — superseded

**objective:** Explain how a gold-leaf electroscope detects charge and why quantisation is not noticeable at macroscopic scales.

**widget judged:** `decline`

**reason:** (c). This is the strongest decline-where-a-picture-was-needed case. The board text is pure apparatus description: "a metal rod ending in two thin gold leaves inside a glass case, topped by a metal disc", then "both leaves … repel each other, causing them to diverge", then "the angle of divergence indicates how much charge is present". Three consecutive text lines describing a physical object's parts and its observable geometry, with zero visual support. `labelled_figure` exists and is precisely this template. Note the contrast: the same electroscope content in `electric-charge-properties-quantisation-and-charging seg 7` *did* get a picture (`svg_source=segment_example_diagram_svg`), so the a

#### `equilibrium-of-charges` seg 5 — superseded

**objective:** Determine equilibrium configurations of charges constrained to a ring and analyze their stability.

**widget judged:** `decline`

**reason:** (b). The parameters contradict the board text. The board sets up "For N=3: three equal charges q at 120° intervals on a ring" and the caption scopes the figure to "**one** ring charge". A single one of three mutually repelling charges experiences

#### `gauss-s-law-and-its-applications` seg 6 — superseded

**objective:** Choose appropriate Gaussian surfaces for symmetric charge distributions and compute fields.

**widget judged:** `field_lines`

**reason:** (a). The segment teaches a *selection procedure* across three cases — the board lists them: "spherical (point charge, shell, solid sphere), cylindrical (infinite line, coaxial cable), planar (infinite sheet, slab)" and then "match the Gaussian surface to the symmetry: sphere … coaxial cylinder … pillbox". The widget can draw none of the three surfaces and covers only one of the three symmetries. With `annotate:null` and `caption:null` the student gets an unexplained point-charge starburst next to a three-way comparison. A comparison/table-shaped figure is what this board wants; the `field_lines` firing here looks driven by `archetype_high` on the concept rather than by this segment's need. F

#### `gauss-s-law-and-its-applications` seg 7 — superseded

**objective:** Avoid typical mistakes in flux and Gauss's law problems.

**widget judged:** `field_lines`

**reason:** (a). Two problems. First, redundancy: this is the fifth `configuration:"point"` field-lines figure in a seven-segment subtopic (segs 2, 3, 5, 6, 7) and is parametrically near-identical to the one the PRIOR block records as already drawn in seg 3 — the harness's own framing question ("is it different from what the prior-payload lines say was already drawn?") answers no. Second, fit: the trap on the board is "field lines entering one side leave the other" for an **external** charge crossing a **closed surface**. The figure has no closed surface and no external charge, so it cannot depict the trap. An unchanged repeat figure beside a pitfalls list is board noise. ## Notes and uncertainties 1. *

## maths 12 ch8 — Application of Integrals

proposed y: 31 ; proposed n: 40 (of 71)

| subtopic_key | seg | widget judged | verdict | bucket | verdict_key |
|---|---|---|---|---|---|
| area-between-a-function-and-its-inverse | 1 | decline | n | reconfirm | `b8ea0836237cc4ca:decline` |
| area-between-a-function-and-its-inverse | 2 | decline | n | superseded | `2d29dac52a9cfca2:decline` |
| area-between-a-function-and-its-inverse | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-between-a-function-and-its-inverse | 4 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-between-a-function-and-its-inverse | 5 | decline | n | superseded | `21c69d126be56395:decline` |
| area-between-a-function-and-its-inverse | 6 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-between-a-function-and-its-inverse | 7 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-between-two-intersecting-curves | 1 | decline | n | carried | `ad1e1ae585e3632a:decline` |
| area-between-two-intersecting-curves | 2 | decline | n | carried | `facd92c5f01a5369:decline` |
| area-between-two-intersecting-curves | 3 | decline | n | reconfirm | `88a74ed8b734c261:decline` |
| area-between-two-intersecting-curves | 4 | decline | n | reconfirm | `3b71df87410859ef:decline` |
| area-between-two-intersecting-curves | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-between-two-intersecting-curves | 6 | decline | n | superseded | `1ffd9920d7f9881b:decline` |
| area-between-two-intersecting-curves | 7 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-between-two-intersecting-curves | 8 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-between-two-intersecting-curves | 9 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 1 | decline | n | superseded | `93419b4efab2ab4c:decline` |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 2 | decline | n | reconfirm | `f27b7b644c270127:decline` |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 3 | decline | n | superseded | `6f55fee7318b8109:decline` |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 4 | decline | n | superseded | `9f9255ada927d397:decline` |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 5 | decline | n | superseded | `97121f7085bb7846:decline` |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 6 | decline | n | superseded | `12ed11a9fc9fbcd1:decline` |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 7 | decline | n | superseded | `1430902ea29aed24:decline` |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 8 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-bounded-by-a-parabola-and-a-line | 1 | xy_plot | n | carried | `3ed2b2cd98ba6b33:xy_plot` |
| area-bounded-by-a-parabola-and-a-line | 2 | xy_plot | n | carried | `8bd68c75c0916cf5:xy_plot` |
| area-bounded-by-a-parabola-and-a-line | 3 | xy_plot | n | superseded | `fa67eba72b4e7895:xy_plot` |
| area-bounded-by-a-parabola-and-a-line | 4 | xy_plot | n | superseded | `18811a8df1792821:xy_plot` |
| area-bounded-by-a-parabola-and-a-line | 5 | xy_plot | n | superseded | `278ad6e6cf860c53:xy_plot` |
| area-bounded-by-a-parabola-and-a-line | 6 | xy_plot | y | unkeyable | `e3b0c44298fc1c14:xy_plot` |
| area-bounded-by-a-parabola-and-a-line | 7 | xy_plot | y | unkeyable | `e3b0c44298fc1c14:xy_plot` |
| area-by-integration-along-the-y-axis | 1 | decline | n | reconfirm | `9d58024fa061fdb0:decline` |
| area-by-integration-along-the-y-axis | 2 | decline | n | reconfirm | `1dc05a8e1e508143:decline` |
| area-by-integration-along-the-y-axis | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-by-integration-along-the-y-axis | 4 | decline | n | superseded | `fa36012692b981f2:decline` |
| area-by-integration-along-the-y-axis | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-by-integration-along-the-y-axis | 6 | decline | n | superseded | `b8a086716368503a:decline` |
| area-by-integration-along-the-y-axis | 7 | decline | n | carried | `be64bff5ec556558:decline` |
| area-by-integration-along-the-y-axis | 8 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-of-regions-bounded-by-circles-and-ellipses | 1 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-of-regions-bounded-by-circles-and-ellipses | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-of-regions-bounded-by-circles-and-ellipses | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-of-regions-bounded-by-circles-and-ellipses | 4 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-of-regions-bounded-by-circles-and-ellipses | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-of-regions-bounded-by-circles-and-ellipses | 6 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-of-regions-bounded-by-circles-and-ellipses | 7 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-of-regions-bounded-by-circles-and-ellipses | 8 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-of-regions-described-by-inequalities | 1 | decline | n | superseded | `47c80ca4c3dcf49d:decline` |
| area-of-regions-described-by-inequalities | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-of-regions-described-by-inequalities | 3 | decline | n | reconfirm | `4dca4823ffe71c8d:decline` |
| area-of-regions-described-by-inequalities | 4 | decline | n | superseded | `cae92833aa19c496:decline` |
| area-of-regions-described-by-inequalities | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-of-regions-described-by-inequalities | 6 | decline | n | superseded | `8e940214ebe278ed:decline` |
| area-of-regions-described-by-inequalities | 7 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-of-regions-involving-modulus-and-piecewise-defined-functions | 1 | xy_plot | n | superseded | `72be0b94c5756253:xy_plot` |
| area-of-regions-involving-modulus-and-piecewise-defined-functions | 2 | xy_plot | n | superseded | `8a10d0083ccb3d4f:xy_plot` |
| area-of-regions-involving-modulus-and-piecewise-defined-functions | 3 | xy_plot | n | carried | `176b08efbf427608:xy_plot` |
| area-of-regions-involving-modulus-and-piecewise-defined-functions | 4 | xy_plot | n | reconfirm | `545a75d0ff7a7434:xy_plot` |
| area-of-regions-involving-modulus-and-piecewise-defined-functions | 5 | xy_plot | n | superseded | `8451d9783cea7c9d:xy_plot` |
| area-of-regions-involving-modulus-and-piecewise-defined-functions | 6 | xy_plot | n | superseded | `6edfef47ab95503f:xy_plot` |
| area-of-regions-involving-modulus-and-piecewise-defined-functions | 7 | xy_plot | n | superseded | `86efd988356195f6:xy_plot` |
| area-of-regions-involving-modulus-and-piecewise-defined-functions | 8 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| area-under-a-simple-curve-bounded-by-the-axes | 1 | xy_plot | y | unkeyable | `e3b0c44298fc1c14:xy_plot` |
| area-under-a-simple-curve-bounded-by-the-axes | 2 | xy_plot | y | unkeyable | `e3b0c44298fc1c14:xy_plot` |
| area-under-a-simple-curve-bounded-by-the-axes | 3 | xy_plot | y | unkeyable | `e3b0c44298fc1c14:xy_plot` |
| area-under-a-simple-curve-bounded-by-the-axes | 4 | xy_plot | y | unkeyable | `e3b0c44298fc1c14:xy_plot` |
| area-under-a-simple-curve-bounded-by-the-axes | 5 | xy_plot | n | superseded | `c7a87f8f36780945:xy_plot` |
| area-under-a-simple-curve-bounded-by-the-axes | 6 | xy_plot | n | superseded | `2487ccc3009fd7a6:xy_plot` |
| area-under-a-simple-curve-bounded-by-the-axes | 7 | xy_plot | n | superseded | `4b2298420a2f6948:xy_plot` |
| area-under-a-simple-curve-bounded-by-the-axes | 8 | xy_plot | y | unkeyable | `e3b0c44298fc1c14:xy_plot` |
| area-under-a-simple-curve-bounded-by-the-axes | 9 | xy_plot | n | superseded | `208a2a3c786a4c8a:xy_plot` |

### the 40 n rows that can still be acted on

#### `area-between-a-function-and-its-inverse` seg 1 — reconfirm

**objective:** Explain why the graph of an inverse function is the reflection of the original graph across the line y = x.

**widget judged:** `decline`

**reworded (0.961):** `across` -> `in`

**reason:** — The Mirror Property of Inverse Functions - **Objective:** "Explain why the graph of an inverse function is the reflection of the original graph across the line y = x." - **board_slot:** `svg_live` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `ray_diagram` (svg template), params verbatim: ```json { "optic_type": "convex_lens", "object_pos": 30, "focal_length": 10 } ``` - **Caption:** "Reflection across y = x swaps coordinates" - **diag_hint was:** `ray_diagram` - **Proposed n, criterion (a)** — confidence high. The segment teaches that the graph of f-inverse is the reflection of f in y = x. The board emitted a **ray_diagram** with `optic_type: convex_lens,

#### `area-between-a-function-and-its-inverse` seg 2 — superseded

**objective:** State and prove the mirror trick formula for the area between a function and its inverse when the function is increasing and lies above the diagonal.

**widget judged:** `decline`

**reason:** — The Mirror Trick for Area Between Inverses - **Objective:** "State and prove the mirror trick formula for the area between a function and its inverse when the function is increasing and lies above the diagonal." - **board_slot:** `svg_live` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `text_only` — no diagram node on the board at all. - **diag_hint was:** `ray_diagram` - **Proposed n, criterion (c)** — confidence medium. A geometric proof: 'the diagonal y=x cuts the region into two pieces... reflection fixes the diagonal and swaps the graphs, so the two pieces are congruent. The piece above the diagonal has area int(f(x)-x). Double it.' The entire argumen

#### `area-between-a-function-and-its-inverse` seg 5 — superseded

**objective:** Apply the mirror trick to find the area enclosed between y=x^3 and y=x^{1/3}.

**widget judged:** `decline`

**reason:** — Area Between x^3 and x^{1/3} - **Objective:** "Apply the mirror trick to find the area enclosed between y=x^3 and y=x^{1/3}." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `ray_diagram` (svg template), params verbatim: ```json { "optic_type": "convex_lens", "object_pos": 30, "focal_length": 20 } ``` - **Caption:** "Reflection across y = x mirrors the two inverse curves" - **diag_hint was:** `ray_diagram` - **Proposed n, criterion (a)** — confidence high. Same optics figure again: **ray_diagram** `optic_type: convex_lens, object_pos: 30, focal_length: 20`, captioned 'Reflection across y = x mirrors the two inverse curves'

#### `area-between-two-intersecting-curves` seg 1 — carried

**objective:** Understand the formula for area between two curves using vertical strips and apply it when the upper and lower curves are known.

**widget judged:** `decline`

**reason:** — The Core Idea: Top Minus Bottom - **Objective:** "Understand the formula for area between two curves using vertical strips and apply it when the upper and lower curves are known." - **board_slot:** `svg_live` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `labeled_axes_plot` (svg template), params verbatim: ```json { "x_label": "x", "y_label": "y", "curve_points": [ [ 0, 0.2 ], [ 0.5, 0.5 ], [ 1, 1 ], [ 1.5, 1.6 ], [ 2, 2.2 ] ], "annotations": [ { "x": 1, "y": 1, "text": "f(x) upper" }, { "x": 1, "y": 0.4, "text": "g(x) lower" } ], "title": "Vertical strip: height = f(x) - g(x)" } ``` - **Caption:** "Thin vertical strip between the two curves" - **diag_hint

#### `area-between-two-intersecting-curves` seg 2 — carried

**objective:** Determine the limits of integration by solving for the points where the two curves intersect.

**widget judged:** `decline`

**reason:** — Finding the Limits: Intersection Points - **Objective:** "Determine the limits of integration by solving for the points where the two curves intersect." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `labeled_axes_plot` (svg template), params verbatim: ```json { "x_label": "x", "y_label": "y", "title": "y = x and y = x^2 meet at x = 0 and x = 1", "curve_points": [ [ 0, 0 ], [ 0.25, 0.25 ], [ 0.5, 0.5 ], [ 0.75, 0.75 ], [ 1, 1 ] ], "annotations": [ [ 0, 0, "a = 0" ], [ 1, 1, "b = 1" ] ] } ``` - **Caption:** "Intersection points give the limits a and b" - **diag_hint was:** `labeled_axes_plot` - **Proposed n, criterion (a)*

#### `area-between-two-intersecting-curves` seg 3 — reconfirm

**objective:** Identify the upper and lower curves on an interval by testing a sample point and sketching the region.

**widget judged:** `decline`

**reworded (0.916):** `and` -> `or`; `the region` -> ``

**reason:** — Which Curve is on Top? Sampling and Sketching - **Objective:** "Identify the upper and lower curves on an interval by testing a sample point and sketching the region." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `conic_figure` (svg template), params verbatim: ```json { "kind": "parabola", "a": 1, "b": 1 } ``` - **Caption:** "y = x^2 opens upward; the line y = x lies above it between x = 0 and x = 1." - **diag_hint was:** `conic_figure` - **Proposed n, criterion (a)** — confidence high. Objective: identify the upper and lower curve by testing a sample point. Emitted **conic_figure** `{kind: parabola, a: 1, b: 1}`, i.e. 

#### `area-between-two-intersecting-curves` seg 4 — reconfirm

**objective:** Compute the area between y=x and y=x^2 from x=0 to x=1 using the top-minus-bottom formula.

**widget judged:** `decline`

**reworded (0.901):** `from x 0 to x 1` -> ``

**reason:** — Worked Example: Line and Parabola - **Objective:** "Compute the area between y=x and y=x^2 from x=0 to x=1 using the top-minus-bottom formula." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `conic_figure` (svg template), params verbatim: ```json { "kind": "parabola", "a": 1, "b": 1 } ``` - **Caption:** "Parabola y = x^2 meeting the line y = x at x = 0 and x = 1" - **diag_hint was:** `conic_figure` - **Proposed n, criterion (a)** — confidence high. The worked example is the area between y=x and y=x^2 from 0 to 1 - the canonical `area_between` payload, fired correctly at segment 24/30 of the parabola-and-line subtopic. Her

#### `area-between-two-intersecting-curves` seg 6 — superseded

**objective:** Use horizontal strips (right minus left) when the region is more naturally described by functions of y.

**widget judged:** `decline`

**reason:** — Horizontal Strips: Integrating with Respect to y - **Objective:** "Use horizontal strips (right minus left) when the region is more naturally described by functions of y." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `conic_figure` (svg template), params verbatim: ```json { "kind": "parabola", "a": 1, "b": 1 } ``` - **Caption:** "Sideways parabola x = y^2/4 — horizontal strips fit naturally" - **diag_hint was:** `conic_figure` - **Proposed n, criterion (a)** — confidence high. Objective is horizontal strips / integrating with respect to y. `integrate_along: 'y'` is the v3 parameter built for exactly this (the widget hea

#### `area-bounded-by-a-curve-and-its-tangent-or-normal` seg 1 — superseded

**objective:** Identify the region bounded by a curve and its tangent or normal and set up the area integral using top-minus-bottom.

**widget judged:** `decline`

**reason:** — The Tangent/Normal Area Problem - **Objective:** "Identify the region bounded by a curve and its tangent or normal and set up the area integral using top-minus-bottom." - **board_slot:** `svg_live` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `conic_figure` (svg template), params verbatim: ```json { "kind": "parabola", "a": 1, "b": 1 } ``` - **Caption:** "Parabola with its tangent line — the region between them" - **diag_hint was:** `conic_figure` - **Proposed n, criterion (a)** — confidence high. Opening segment of the tangent/normal subtopic. The widget header records concept 4 as YES at v3: 'the widget differentiates the curve itself, so the payload na

#### `area-bounded-by-a-curve-and-its-tangent-or-normal` seg 2 — reconfirm

**objective:** Compute the equation of the tangent or normal to a given curve at a specified point.

**widget judged:** `decline`

**reworded (0.921):** `compute` -> `write`; `or` -> `and`

**reason:** — Finding the Tangent and Normal Equations - **Objective:** "Compute the equation of the tangent or normal to a given curve at a specified point." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `labeled_axes_plot` (svg template), params verbatim: ```json { "x_label": "x", "y_label": "y", "title": "y = x^2 with tangent and normal at (1,1)", "curve_points": [ [ -1.5, 2.25 ], [ -1, 1 ], [ -0.5, 0.25 ], [ 0, 0 ], [ 0.5, 0.25 ], [ 1, 1 ], [ 1.5, 2.25 ] ], "annotations": [ [ 1, 1, "(1,1)" ], [ 0, 1.5, "normal" ], [ 1.5, 2, "tangent" ] ] } ``` - **Caption:** "Curve y = x^2 with its tangent and normal at (1,1)" - **diag_hint was:**

#### `area-bounded-by-a-curve-and-its-tangent-or-normal` seg 3 — superseded

**objective:** Find the points of intersection between a curve and its tangent or normal by solving equations simultaneously.

**widget judged:** `decline`

**reason:** — Intersection Points: Where Curve Meets Line - **Objective:** "Find the points of intersection between a curve and its tangent or normal by solving equations simultaneously." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `labeled_axes_plot` (svg template), params verbatim: ```json { "x_label": "x", "y_label": "y", "title": "y = x^2 with tangent and normal at (1,1)", "curve_points": [ [ -1.5, 2.25 ], [ -1, 1 ], [ -0.5, 0.25 ], [ 0, 0 ], [ 0.5, 0.25 ], [ 1, 1 ], [ 1.5, 2.25 ] ], "annotations": [ [ 1, 1, "tangent point (1,1)" ], [ -1.5, 2.25, "normal meets curve" ] ] } ``` - **Caption:** "Curve y = x^2, its tangent and norma

#### `area-bounded-by-a-curve-and-its-tangent-or-normal` seg 4 — superseded

**objective:** Set up the definite integral for the area between a curve and its tangent or normal using top-minus-bottom.

**widget judged:** `decline`

**reason:** — Setting Up the Area Integral - **Objective:** "Set up the definite integral for the area between a curve and its tangent or normal using top-minus-bottom." - **board_slot:** `svg_live` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `conic_figure` (svg template), params verbatim: ```json { "kind": "parabola", "a": 1, "b": 1 } ``` - **Caption:** "Parabola y = x^2 — the curve whose area with a line we compute" - **diag_hint was:** `conic_figure` - **Proposed n, criterion (a)** — confidence medium. Objective: set up the top-minus-bottom integral for the region between a curve and its tangent/normal. Emitted **conic_figure** `{kind: parabola, a: 1, b: 1}`, capti

#### `area-bounded-by-a-curve-and-its-tangent-or-normal` seg 5 — superseded

**objective:** Evaluate the definite integral to find the area between a curve and its tangent or normal.

**widget judged:** `decline`

**reason:** — Evaluating the Integral - **Objective:** "Evaluate the definite integral to find the area between a curve and its tangent or normal." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `labeled_axes_plot` (svg template), params verbatim: ```json { "x_label": "x", "y_label": "y", "curve_points": [ [ -1.5, 2.25 ], [ -1, 1 ], [ -0.5, 0.25 ], [ 0, 0 ], [ 0.5, 0.25 ], [ 1, 1 ] ], "annotations": [ [ -1.5, 2.25, "(-3/2, 9/4)" ], [ 1, 1, "(1,1)" ] ], "title": "Area between y = x^2 and its normal" } ``` - **Caption:** "Region between parabola and normal, x = -3/2 to x = 1" - **diag_hint was:** `labeled_axes_plot` - **Proposed n, crite

#### `area-bounded-by-a-curve-and-its-tangent-or-normal` seg 6 — superseded

**objective:** Find the area bounded by a curve, its tangent, and another line (like an axis or a vertical line).

**widget judged:** `decline`

**reason:** — Tangent with an Additional Boundary - **Objective:** "Find the area bounded by a curve, its tangent, and another line (like an axis or a vertical line)." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `conic_figure` (svg template), params verbatim: ```json { "kind": "parabola", "a": 1, "b": 1 } ``` - **Caption:** "Parabola y = x^2 with its tangent and the x-axis bounding the region" - **diag_hint was:** `conic_figure` - **Proposed n, criterion (a)** — confidence high. Region bounded by y=x^2, its tangent y=2x-1, and the x-axis; the board gives the tangent's equation and both x-intercepts. Emitted **conic_figure** `{kind: 

#### `area-bounded-by-a-curve-and-its-tangent-or-normal` seg 7 — superseded

**objective:** Find the area bounded by a curve, its normal, and an axis or another line.

**widget judged:** `decline`

**reason:** — Normal with an Additional Boundary - **Objective:** "Find the area bounded by a curve, its normal, and an axis or another line." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `conic_figure` (svg template), params verbatim: ```json { "kind": "parabola", "a": 1, "b": 1 } ``` - **Caption:** "Parabola y = x^2 with its normal at (1,1) and the y-axis bounding the region" - **diag_hint was:** `conic_figure` - **Proposed n, criterion (a)** — confidence high. Region bounded by y=x^2, its normal y=-x/2+3/2, and the y-axis; the board prints the normal's equation. Emitted **conic_figure** `{kind: parabola, a: 1, b: 1}` - parabola on

#### `area-bounded-by-a-parabola-and-a-line` seg 1 — carried

**objective:** State and apply the formula for the area between two curves using vertical strips.

**widget judged:** `xy_plot`

**reason:** — The Area Between Two Curves: The Core Formula - **Objective:** "State and apply the formula for the area between two curves using vertical strips." - **board_slot:** `widget_archetype` - **Fired:** `xy_plot` v4, params verbatim: ```json { "mode": "area_between", "curve": "line", "curve2": "parabola", "a": 1, "b": 0, "c": 0, "a2": -1, "b2": 0, "c2": 0, "x_min": 0, "x_max": 1, "shade_from": 0, "shade_to": 1, "x_label": "x", "y_label": "y" } ``` - **Caption on the board:** "Area between y = x (top) and y = x^2 (bottom) from x = 0 to x = 1" - **Proposed n, criterion (b)** — confidence high. `curve2: parabola` with `a2: -1` is y = -x^2, an INVERTED parabola, while the caption and the whole segm

#### `area-bounded-by-a-parabola-and-a-line` seg 2 — carried

**objective:** Find the points of intersection of a parabola and a line by solving their equations simultaneously.

**widget judged:** `xy_plot`

**reason:** — Finding Intersections: The Limits of Integration - **Objective:** "Find the points of intersection of a parabola and a line by solving their equations simultaneously." - **board_slot:** `widget_archetype` - **Fired:** `xy_plot` v4, params verbatim: ```json { "mode": "area_between", "curve": "line", "curve2": "parabola", "a": 1, "a2": 1, "b": 0, "b2": 0, "c": 0, "c2": 0, "x_min": -0.5, "x_max": 4.5, "shade_from": 0, "shade_to": 4, "x_label": "x", "y_label": "y" } ``` - **Caption on the board:** "Intersection points (0,0) and (4,4) give the limits of integration." - **Proposed n, criterion (b)** — confidence high. The drawn pair is y = x (line a=1,c=0) and y = x^2 (parabola a2=1), which inte

#### `area-bounded-by-a-parabola-and-a-line` seg 3 — superseded

**objective:** Compute the area between a parabola and a line when the parabola is the upper curve using vertical strips.

**widget judged:** `xy_plot`

**reason:** — Vertical Strips: Parabola on Top - **Objective:** "Compute the area between a parabola and a line when the parabola is the upper curve using vertical strips." - **board_slot:** `widget_archetype` - **Fired:** `xy_plot` v4, params verbatim: ```json { "mode": "area_between", "curve": "parabola", "curve2": "line", "a": 1, "a2": 1, "b": 0, "b2": 0, "c": 0, "c2": 0, "x_min": 0, "x_max": 4.5, "shade_from": 0, "shade_to": 4, "x_label": "x", "y_label": "y" } ``` - **Caption on the board:** "Region between y = 2√x and y = x, from x = 0 to x = 4" - **Proposed n, criterion (b)** — confidence high. Caption: 'Region between y = 2sqrt(x) and y = x, from x = 0 to x = 4', and the board text establishes th

#### `area-bounded-by-a-parabola-and-a-line` seg 4 — superseded

**objective:** Decide when to integrate with respect to y and compute the area using horizontal strips.

**widget judged:** `xy_plot`

**reason:** — Horizontal Strips: When the Parabola is Sideways - **Objective:** "Decide when to integrate with respect to y and compute the area using horizontal strips." - **board_slot:** `widget_archetype` - **Fired:** `xy_plot` v4, params verbatim: ```json { "mode": "area_between", "curve": "parabola", "curve2": "line", "a": 1, "a2": 1, "b": 0, "b2": 0, "c": 0, "c2": 0, "x_min": -0.5, "x_max": 4.5, "shade_from": 0, "shade_to": 4, "x_label": "x", "y_label": "y", "integrate_along": "y" } ``` - **Caption on the board:** "Region between y^2 = 4x and y = 2x - 4, sliced horizontally" - **Proposed n, criterion (b)** — confidence high. `integrate_along: 'y'` is right for the objective - that part is correct.

#### `area-bounded-by-a-parabola-and-a-line` seg 5 — superseded

**objective:** Compute the area bounded by a parabola and its latus rectum using symmetry.

**widget judged:** `xy_plot`

**reason:** — The Latus Rectum: A Special Chord - **Objective:** "Compute the area bounded by a parabola and its latus rectum using symmetry." - **board_slot:** `widget_archetype` - **Fired:** `xy_plot` v4, params verbatim: ```json { "mode": "area_between", "curve": "parabola", "curve2": "line", "a": 1, "a2": 1, "b": 0, "b2": 0, "c": 0, "c2": 0, "integrate_along": "x", "shade_from": 0, "shade_to": 1, "x_min": -0.5, "x_max": 1.5, "x_label": "x", "y_label": "y" } ``` - **Caption on the board:** "Region between y^2 = 4x and its latus rectum x = 1" - **Proposed n, criterion (b)** — confidence high. The latus rectum of y^2 = 4x is the VERTICAL line x = 1. `curve2: line` is y = a2*x + c2 and cannot be vertica

#### `area-by-integration-along-the-y-axis` seg 1 — reconfirm

**objective:** Recognize when a region is more naturally described by horizontal strips and explain why integrating with respect to y is advantageous.

**widget judged:** `decline`

**reworded (0.959):** `recognize` -> `identify`

**reason:** — Why Integrate Along the y-axis? - **Objective:** "Recognize when a region is more naturally described by horizontal strips and explain why integrating with respect to y is advantageous." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = widget_cannot_express_concept` - **Emitted instead:** `conic_figure` (svg template), params verbatim: ```json { "kind": "parabola", "a": 1, "b": 1 } ``` - **Caption:** "Parabola y^2 = 4x opening to the right" - **diag_hint was:** `conic_figure` - **Proposed n, criterion (c)** — confidence high. Structured decline `widget_cannot_express_concept` on the opening segment of the y-axis subtopic. The widget header lists concept 10, 'Area by in

#### `area-by-integration-along-the-y-axis` seg 2 — reconfirm

**objective:** State and apply the formula A = ∫ x dy for a region bounded by a curve, the y-axis, and horizontal lines.

**widget judged:** `decline`

**reworded (0.916):** `` -> `x g y`; `` -> `y c and y d`

**reason:** — The Horizontal Strip Formula - **Objective:** "State and apply the formula A = ∫ x dy for a region bounded by a curve, the y-axis, and horizontal lines." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = widget_cannot_express_concept` - **Emitted instead:** `number_line` (svg template), params verbatim: ```json { "title": "Limits along the y-axis: y = c to y = d", "intervals": [ { "lo": 0, "hi": 2, "lo_closed": true, "hi_closed": true, "label": "y from c to d" } ] } ``` - **Caption:** "Horizontal strips sweep from y = c to y = d" - **diag_hint was:** `number_line` - **Proposed n, criterion (c)** — confidence high. Objective is literally A = int x dy. Declined as `widget

#### `area-by-integration-along-the-y-axis` seg 4 — superseded

**objective:** Compute the area of a region bounded by a parabola, the y-axis, and horizontal lines using integration with respect to y.

**widget judged:** `decline`

**reason:** — Worked Example: Parabola and y-axis - **Objective:** "Compute the area of a region bounded by a parabola, the y-axis, and horizontal lines using integration with respect to y." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = widget_cannot_express_concept` - **Emitted instead:** `conic_figure` (svg template), params verbatim: ```json { "kind": "parabola", "a": 1, "b": 1 } ``` - **Caption:** "Parabola x = y^2 opening to the right" - **diag_hint was:** `conic_figure` - **Proposed n, criterion (c)** — confidence high. Worked example: area bounded by x=y^2, the y-axis, y=0 and y=2. Declined as `widget_cannot_express_concept`; emitted **conic_figure** `{kind: parabola, a: 1

#### `area-by-integration-along-the-y-axis` seg 6 — superseded

**objective:** Compute the area between two curves by integrating with respect to y, using right minus left.

**widget judged:** `decline`

**reason:** — Area Between Two Curves Using dy - **Objective:** "Compute the area between two curves by integrating with respect to y, using right minus left." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = widget_cannot_express_concept` - **Emitted instead:** `conic_figure` (svg template), params verbatim: ```json { "kind": "parabola", "a": 1, "b": 1 } ``` - **Caption:** "Parabola y^2 = 4x opening to the right" - **diag_hint was:** `conic_figure` - **Proposed n, criterion (c)** — confidence medium. Objective: area between two curves by dy, right minus left, worked on y^2=4x against y=2x-4. Declined as `widget_cannot_express_concept`; emitted a bare **conic_figure** parabola. Alon

#### `area-by-integration-along-the-y-axis` seg 7 — carried

**objective:** Use symmetry about the x-axis to simplify area calculations when integrating with respect to y.

**widget judged:** `decline`

**reason:** — Symmetry and Efficiency - **Objective:** "Use symmetry about the x-axis to simplify area calculations when integrating with respect to y." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = widget_cannot_express_concept` - **Emitted instead:** `conic_figure` (svg template), params verbatim: ```json { "kind": "parabola", "a": 1, "b": 1 } ``` - **Caption:** "y^2 = 4x — right-opening parabola, symmetric about the x-axis" - **diag_hint was:** `conic_figure` - **Proposed n, criterion (c)** — confidence medium. Objective: use symmetry about the x-axis when integrating with respect to y, on y^2=4x and x=4. Declined as `widget_cannot_express_concept`; emitted a bare **conic_figu

#### `area-of-regions-described-by-inequalities` seg 1 — superseded

**objective:** Translate a single inequality into a shaded region and verify the correct side using a test point.

**widget judged:** `decline`

**reason:** — Decoding Inequalities: The Region Game - **Objective:** "Translate a single inequality into a shaded region and verify the correct side using a test point." - **board_slot:** `svg_live` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `number_line` (svg template), params verbatim: ```json { "intervals": [ { "lo": -3, "hi": 0, "lo_closed": false, "hi_closed": true, "label": "y \u2264 f(x): below" }, { "lo": 0, "hi": 3, "lo_closed": true, "hi_closed": false, "label": "y \u2265 f(x): above" } ], "title": "Which side of the curve?" } ``` - **Caption:** "Inequality decides the side of the boundary curve." - **diag_hint was:** `number_line` - **Proposed n, criterio

#### `area-of-regions-described-by-inequalities` seg 3 — reconfirm

**objective:** Compute the area of the diamond region using symmetry and the formula 2a².

**widget judged:** `decline`

**reworded (0.96):** `` -> `x y a`

**reason:** — The Diamond Region: |x| + |y| ≤ a - **Objective:** "Compute the area of the diamond region using symmetry and the formula 2a²." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `boxed_derivation` (svg template), params verbatim: ```json { "title": "Area of the diamond |x| + |y| \u2264 a", "steps": [ "First quadrant: |x| = x, |y| = y", "Condition becomes x + y \u2264 a, x \u2265 0, y \u2265 0", "This is a right triangle with legs of length a", "Area of one triangle = (1/2) a \u00b7 a = a\u00b2/2", "Total area = 4 \u00d7 (a\u00b2/2) = 2a\u00b2", "For a = 2: A = 2(2)\u00b2 = 8 square units" ] } ``` - **Caption:** "Symmetry giv

#### `area-of-regions-described-by-inequalities` seg 4 — superseded

**objective:** Sketch the intersection of two inequality regions and identify the boundaries for integration.

**widget judged:** `decline`

**reason:** — Systems of Inequalities: Finding the Overlap - **Objective:** "Sketch the intersection of two inequality regions and identify the boundaries for integration." - **board_slot:** `svg_live` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `text_only` — no diagram node on the board at all. - **diag_hint was:** `ray_diagram` - **Proposed n, criterion (c)** — confidence high. Objective quoted below is 'Sketch the intersection of two inequality regions'. The board emitted **text_only** - no figure whatsoever - for a segment whose verb is 'sketch'. The example is {y >= x^2, y <= x+2}: exactly two bounds, which the widget header records as the supported half of conce

#### `area-of-regions-described-by-inequalities` seg 6 — superseded

**objective:** Solve a multi-condition region problem involving modulus and circle, using symmetry and geometry check.

**widget judged:** `decline`

**reason:** — Putting It All Together: A JEE-Style Problem - **Objective:** "Solve a multi-condition region problem involving modulus and circle, using symmetry and geometry check." - **board_slot:** `svg_precomputed` - **Decline:** `non_fire_reason = model_chose_no_widget` - **Emitted instead:** `svg` — no diagram node on the board at all. - **diag_hint was:** `None` - **Proposed n, criterion (c)** — confidence medium. Capstone problem {y >= |x|, x^2 + y^2 <= 2} with an intersection, a symmetry argument and a wedge-shaped region - and no diagram node on the board at all. The xy_plot decline is honest (circles are a documented NO), but `has_example_diagram_svg` is true for this segment, so an authored S

#### `area-of-regions-involving-modulus-and-piecewise-defined-functions` seg 1 — superseded

**objective:** Recognize that advanced area problems are just basic area problems with a modulus, inequality, or switching boundary, and identify which disguise is present.

**widget judged:** `xy_plot`

**reason:** — Decoding the Disguises: Modulus, Inequalities, and Composite Regions - **Objective:** "Recognize that advanced area problems are just basic area problems with a modulus, inequality, or switching boundary, and identify which disguise is present." - **board_slot:** `widget_archetype` - **Fired:** `xy_plot` v4, params verbatim: ```json { "mode": "curve", "curve": "line", "a": 1, "b": 0, "c": 0, "x_min": -3, "x_max": 3, "x_label": "x", "y_label": "y" } ``` - **Caption on the board:** "y = |x| — V-shape with a corner at the origin" - **Proposed n, criterion (b)** — confidence high. Caption: 'y = |x| - V-shape with a corner at the origin'. The params draw `mode: curve, curve: line, a: 1, b: 0, c

#### `area-of-regions-involving-modulus-and-piecewise-defined-functions` seg 2 — superseded

**objective:** Find the area under a modulus curve by locating its corners and integrating piecewise.

**widget judged:** `xy_plot`

**reason:** — Splitting Modulus Curves at Their Corners - **Objective:** "Find the area under a modulus curve by locating its corners and integrating piecewise." - **board_slot:** `widget_archetype` - **Fired:** `xy_plot` v4, params verbatim: ```json { "mode": "curve", "curve": "line", "a": 1, "b": 0, "c": 0, "x_min": -3, "x_max": 3, "x_label": "x", "y_label": "y" } ``` - **Caption on the board:** "y = |x| — V-shape with a corner at the origin" - **Proposed n, criterion (b)** — confidence high. Byte-identical straight-line payload to segment 1, same 'y = |x| - V-shape with a corner at the origin' caption, on a segment whose objective is locating the corners. Same defect, and the repeat means the student

#### `area-of-regions-involving-modulus-and-piecewise-defined-functions` seg 3 — carried

**objective:** Compute the area of the diamond region |x| + |y| ≤ a using symmetry and the formula 2a².

**widget judged:** `xy_plot`

**reason:** — The Diamond Theorem: Area of |x| + |y| ≤ a - **Objective:** "Compute the area of the diamond region |x| + |y| ≤ a using symmetry and the formula 2a²." - **board_slot:** `widget_archetype` - **Fired:** `xy_plot` v4, params verbatim: ```json { "mode": "area", "curve": "line", "a": -1, "b": 2, "c": 0, "x_min": 0, "x_max": 2, "shade_from": 0, "shade_to": 2, "x_label": "x", "y_label": "y" } ``` - **Caption on the board:** "First-quadrant triangle: x + y ≤ 2, legs of length 2" - **Proposed n, criterion (b)** — confidence high. `curve: line, a: -1, b: 2, c: 0`. For `line` the widget evaluates a*x + c and IGNORES b (lib/widgets/xy-plot/plot-math.ts, evalCurve: `case 'line': return a * x + c`). The

#### `area-of-regions-involving-modulus-and-piecewise-defined-functions` seg 4 — reconfirm

**objective:** Translate inequalities like y ≤ f(x) or y ≥ f(x) into shaded regions and identify the overlap for a system.

**widget judged:** `xy_plot`

**reworded (0.911):** `shaded` -> ``; `identify` -> `sketch`

**reason:** — Decoding Inequalities: Which Side of the Curve? - **Objective:** "Translate inequalities like y ≤ f(x) or y ≥ f(x) into shaded regions and identify the overlap for a system." - **board_slot:** `widget_archetype` - **Fired:** `xy_plot` v4, params verbatim: ```json { "mode": "area_between", "curve": "parabola", "a": 1, "b": 0, "c": 0, "curve2": "line", "a2": 1, "b2": 2, "c2": 0, "x_min": -1.5, "x_max": 2.5, "shade_from": -1, "shade_to": 2, "x_label": "x", "y_label": "y" } ``` - **Caption on the board:** "Region between y = x² and y = x + 2" - **Proposed n, criterion (b)** — confidence high. Same `b`-is-not-the-intercept error on curve2: `curve2: line, a2: 1, b2: 2, c2: 0` evaluates to y = x,

#### `area-of-regions-involving-modulus-and-piecewise-defined-functions` seg 5 — superseded

**objective:** Find the area of a region whose upper boundary changes from one curve to another by splitting at the switch point.

**widget judged:** `xy_plot`

**reason:** — Composite Regions: When the Ceiling Switches - **Objective:** "Find the area of a region whose upper boundary changes from one curve to another by splitting at the switch point." - **board_slot:** `widget_archetype` - **Fired:** `xy_plot` v4, params verbatim: ```json { "mode": "area_between", "curve": "parabola", "a": -1, "b": 0, "c": 2, "curve2": "line", "a2": 1, "b2": 0, "c2": 0, "x_min": -1.5, "x_max": 1.5, "shade_from": -1, "shade_to": 1, "x_label": "x", "y_label": "y" } ``` - **Caption on the board:** "Region between y = 2 - x^2 and y = |x|, split at x = 0" - **Proposed n, criterion (b)** — confidence high. Caption: 'Region between y = 2 - x^2 and y = |x|, split at x = 0'. `curve2` is

#### `area-of-regions-involving-modulus-and-piecewise-defined-functions` seg 6 — superseded

**objective:** Use symmetry about axes or origin to reduce the integration work by integrating over a smaller region and multiplying.

**widget judged:** `xy_plot`

**reason:** — Symmetry as a Shortcut: Halving and Doubling - **Objective:** "Use symmetry about axes or origin to reduce the integration work by integrating over a smaller region and multiplying." - **board_slot:** `widget_archetype` - **Fired:** `xy_plot` v4, params verbatim: ```json { "mode": "area_between", "curve": "parabola", "curve2": "line", "a": -1, "a2": 1, "b": 0, "b2": 0, "c": 2, "c2": 0, "x_min": -1.5, "x_max": 1.5, "shade_from": 0, "shade_to": 1, "x_label": "x", "y_label": "y" } ``` - **Caption on the board:** "Right half of the region: bottom y = x, top y = sqrt(2 - x^2)" - **Proposed n, criterion (b)** — confidence medium. Caption: 'Right half of the region: bottom y = x, top y = sqrt(2 -

#### `area-of-regions-involving-modulus-and-piecewise-defined-functions` seg 7 — superseded

**objective:** Solve a complex area problem involving modulus, inequalities, and composite boundaries by decoding, sketching, splitting, and integrating.

**widget judged:** `xy_plot`

**reason:** — Putting It All Together: A Multi-Concept JEE Problem - **Objective:** "Solve a complex area problem involving modulus, inequalities, and composite boundaries by decoding, sketching, splitting, and integrating." - **board_slot:** `widget_archetype` - **Fired:** `xy_plot` v4, params verbatim: ```json { "mode": "area_between", "curve": "parabola", "a": -1, "b": 0, "c": 8, "curve2": "line", "a2": 1, "b2": 0, "c2": 0, "x_min": -2.5, "x_max": 2.5, "shade_from": 0, "shade_to": 2, "x_label": "x", "y_label": "y" } ``` - **Caption on the board:** "Right half of the wedge: between y = x and y = √(8 − x²), x from 0 to 2" - **Proposed n, criterion (b)** — confidence high. Same circle-faked-as-parabola 

#### `area-under-a-simple-curve-bounded-by-the-axes` seg 5 — superseded

**objective:** Compute the area when the curve crosses the x-axis within the interval by splitting the integral at the roots.

**widget judged:** `xy_plot`

**reason:** — Splitting at Roots: When the Curve Crosses the Axis - **Objective:** "Compute the area when the curve crosses the x-axis within the interval by splitting the integral at the roots." - **board_slot:** `widget_archetype` - **Fired:** `xy_plot` v4, params verbatim: ```json { "mode": "area", "curve": "parabola", "a": 1, "b": 0, "c": 0, "x_min": -2, "x_max": 2, "shade_from": -2, "shade_to": 2, "x_label": "x", "y_label": "y = f(x)" } ``` - **Caption on the board:** "Curve crossing the x-axis: the two shaded pieces have opposite signs and cancel in the signed integral." - **Proposed n, criterion (b)** — confidence high. Objective and caption are about a curve CROSSING the x-axis so the signed pie

#### `area-under-a-simple-curve-bounded-by-the-axes` seg 6 — superseded

**objective:** Use symmetry to compute areas of symmetric regions by integrating over a smaller part and multiplying.

**widget judged:** `xy_plot`

**reason:** — Symmetry: A Time-Saving Shortcut - **Objective:** "Use symmetry to compute areas of symmetric regions by integrating over a smaller part and multiplying." - **board_slot:** `widget_precomputed` - **Fired:** `xy_plot` v4, params verbatim: ```json { "a": 1, "b": 1, "c": 0, "mode": "area", "curve": "reciprocal", "x_max": 1.2, "x_min": -1.2, "x_label": "x", "y_label": "y", "shade_to": 1, "shade_from": 0 } ``` - **Proposed n, criterion (b)** — confidence high. Two separate problems. (i) The objective is symmetry about an axis; `curve: reciprocal` is y = a/x + c, which has point symmetry about the origin and no axis symmetry, so it cannot demonstrate 'symmetry about the x-axis gives 2 equal halv

#### `area-under-a-simple-curve-bounded-by-the-axes` seg 7 — superseded

**objective:** Apply the standard area formulas for a circle and an ellipse, and understand their derivation via integration.

**widget judged:** `xy_plot`

**reason:** — Standard Results: Circle and Ellipse - **Objective:** "Apply the standard area formulas for a circle and an ellipse, and understand their derivation via integration." - **board_slot:** `widget_archetype` - **Fired:** `xy_plot` v4, params verbatim: ```json { "mode": "area", "curve": "parabola", "a": -1, "b": 0, "c": 1, "x_min": 0, "x_max": 1, "shade_from": 0, "shade_to": 1, "x_label": "x", "y_label": "y = sqrt(a^2 - x^2)" } ``` - **Caption on the board:** "First-quadrant piece of the circle: integrate y = sqrt(a^2 - x^2) from x = 0 to x = a." - **Proposed n, criterion (b)** — confidence high. `y_label` is 'y = sqrt(a^2 - x^2)' and the board derives the quarter-circle area pi*a^2/4, but the 

#### `area-under-a-simple-curve-bounded-by-the-axes` seg 9 — superseded

**objective:** Solve a problem that combines sign handling, splitting, symmetry, and variable choice.

**widget judged:** `xy_plot`

**reason:** — Putting It All Together: A Multi-Concept Problem - **Objective:** "Solve a problem that combines sign handling, splitting, symmetry, and variable choice." - **board_slot:** `widget_precomputed` - **Fired:** `xy_plot` v4, params verbatim: ```json { "a": 4, "b": 0, "c": 0, "mode": "area", "curve": "reciprocal", "x_max": 4.5, "x_min": -4.5, "x_label": "x", "y_label": "y", "shade_to": 4, "shade_from": 2 } ``` - **Proposed n, criterion (b)** — confidence high. Capstone on the cap of x^2 + y^2 = 16 to the right of x = 2. The params draw `curve: reciprocal, a: 4, c: 0` = y = 4/x, a hyperbola branch, for a circle - again a shape the widget documents as out of scope. And `x_min: -4.5, x_max: 4.5` s

## chem 12 ch8 — Aldehydes, Ketones & Carboxylic Acids

proposed y: 94 ; proposed n: 19 (of 113)

| subtopic_key | seg | widget judged | verdict | bucket | verdict_key |
|---|---|---|---|---|---|
| acidity-of-carboxylic-acids-and-substituent-effects | 1 | data_table_trend | y | unkeyable | `e3b0c44298fc1c14:data_table_trend` |
| acidity-of-carboxylic-acids-and-substituent-effects | 2 | data_table_trend | y | unkeyable | `e3b0c44298fc1c14:data_table_trend` |
| acidity-of-carboxylic-acids-and-substituent-effects | 3 | data_table_trend | y | unkeyable | `e3b0c44298fc1c14:data_table_trend` |
| acidity-of-carboxylic-acids-and-substituent-effects | 4 | data_table_trend | y | unkeyable | `e3b0c44298fc1c14:data_table_trend` |
| acidity-of-carboxylic-acids-and-substituent-effects | 5 | data_table_trend | y | unkeyable | `e3b0c44298fc1c14:data_table_trend` |
| acidity-of-carboxylic-acids-and-substituent-effects | 6 | data_table_trend | y | unkeyable | `e3b0c44298fc1c14:data_table_trend` |
| aldol-condensation | 1 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| aldol-condensation | 2 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| aldol-condensation | 3 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| aldol-condensation | 4 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| aldol-condensation | 5 | reaction_scheme | n | superseded | `63627dbb2adbda43:reaction_scheme` |
| aldol-condensation | 6 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| aldol-condensation | 7 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| aldol-condensation | 8 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| aldol-condensation | 9 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| alpha-halogenation-and-hell-volhard-zelinsky-reaction | 1 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| alpha-halogenation-and-hell-volhard-zelinsky-reaction | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| alpha-halogenation-and-hell-volhard-zelinsky-reaction | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| alpha-halogenation-and-hell-volhard-zelinsky-reaction | 4 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| alpha-halogenation-and-hell-volhard-zelinsky-reaction | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| alpha-halogenation-and-hell-volhard-zelinsky-reaction | 6 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| cannizzaro-reaction | 1 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| cannizzaro-reaction | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| cannizzaro-reaction | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| cannizzaro-reaction | 4 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| cannizzaro-reaction | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| cannizzaro-reaction | 6 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| distinguishing-tests-for-aldehydes-ketones-and-acids | 1 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| distinguishing-tests-for-aldehydes-ketones-and-acids | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| distinguishing-tests-for-aldehydes-ketones-and-acids | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| distinguishing-tests-for-aldehydes-ketones-and-acids | 4 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| distinguishing-tests-for-aldehydes-ketones-and-acids | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| distinguishing-tests-for-aldehydes-ketones-and-acids | 6 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| distinguishing-tests-for-aldehydes-ketones-and-acids | 7 | decline | n | superseded | `45fd5c9d9b45a66d:decline` |
| distinguishing-tests-for-aldehydes-ketones-and-acids | 8 | decline | n | superseded | `a929c25cbc454f9a:decline` |
| haloform-reaction | 1 | decline | n | superseded | `e017094c20f48dd1:decline` |
| haloform-reaction | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| haloform-reaction | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| haloform-reaction | 4 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| haloform-reaction | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| haloform-reaction | 6 | decline | n | superseded | `ea5e6dff0896ab82:decline` |
| haloform-reaction | 7 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| haloform-reaction | 8 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| haloform-reaction | 9 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| multi-step-conversions-and-reaction-maps | 1 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| multi-step-conversions-and-reaction-maps | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| multi-step-conversions-and-reaction-maps | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| multi-step-conversions-and-reaction-maps | 4 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| multi-step-conversions-and-reaction-maps | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| multi-step-conversions-and-reaction-maps | 6 | decline | n | carried | `34e5d7140117d0d2:decline` |
| multi-step-conversions-and-reaction-maps | 7 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| multi-step-conversions-and-reaction-maps | 8 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| multi-step-conversions-and-reaction-maps | 9 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| nomenclature-and-structure-of-carbonyl-compounds | 1 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| nomenclature-and-structure-of-carbonyl-compounds | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| nomenclature-and-structure-of-carbonyl-compounds | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| nomenclature-and-structure-of-carbonyl-compounds | 4 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| nomenclature-and-structure-of-carbonyl-compounds | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| nomenclature-and-structure-of-carbonyl-compounds | 6 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| nomenclature-and-structure-of-carbonyl-compounds | 7 | decline | n | superseded | `cfa7d88f3f8b2848:decline` |
| nomenclature-and-structure-of-carbonyl-compounds | 8 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| nucleophilic-addition-reactions-of-aldehydes-and-ketones | 1 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| nucleophilic-addition-reactions-of-aldehydes-and-ketones | 2 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| nucleophilic-addition-reactions-of-aldehydes-and-ketones | 3 | reaction_scheme | n | reconfirm | `5d00a6ded7d00166:reaction_scheme` |
| nucleophilic-addition-reactions-of-aldehydes-and-ketones | 4 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| nucleophilic-addition-reactions-of-aldehydes-and-ketones | 5 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| nucleophilic-addition-reactions-of-aldehydes-and-ketones | 6 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| nucleophilic-addition-reactions-of-aldehydes-and-ketones | 7 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| nucleophilic-addition-reactions-of-aldehydes-and-ketones | 8 | reaction_scheme | n | superseded | `fcb889bd98661854:reaction_scheme` |
| oxidation-and-reduction-of-aldehydes-and-ketones | 1 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| oxidation-and-reduction-of-aldehydes-and-ketones | 2 | reaction_scheme | n | superseded | `a706f0f8df62e152:reaction_scheme` |
| oxidation-and-reduction-of-aldehydes-and-ketones | 3 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| oxidation-and-reduction-of-aldehydes-and-ketones | 4 | reaction_scheme | n | superseded | `86f756c4533267a9:reaction_scheme` |
| oxidation-and-reduction-of-aldehydes-and-ketones | 5 | reaction_scheme | n | superseded | `52d1641636bea202:reaction_scheme` |
| oxidation-and-reduction-of-aldehydes-and-ketones | 6 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| oxidation-and-reduction-of-aldehydes-and-ketones | 7 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| oxidation-and-reduction-of-aldehydes-and-ketones | 8 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| physical-properties-and-hydrogen-bonding-in-carbonyl-compounds | 1 | decline | n | superseded | `c4f2878fc8cb2d0a:decline` |
| physical-properties-and-hydrogen-bonding-in-carbonyl-compounds | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| physical-properties-and-hydrogen-bonding-in-carbonyl-compounds | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| physical-properties-and-hydrogen-bonding-in-carbonyl-compounds | 4 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| physical-properties-and-hydrogen-bonding-in-carbonyl-compounds | 5 | decline | n | superseded | `ac5ef39f682e2950:decline` |
| physical-properties-and-hydrogen-bonding-in-carbonyl-compounds | 6 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| physical-properties-and-hydrogen-bonding-in-carbonyl-compounds | 7 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| physical-properties-and-hydrogen-bonding-in-carbonyl-compounds | 8 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| preparation-of-aldehydes-and-ketones | 1 | reaction_scheme | n | superseded | `63c40a8ecb6661be:reaction_scheme` |
| preparation-of-aldehydes-and-ketones | 2 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| preparation-of-aldehydes-and-ketones | 3 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| preparation-of-aldehydes-and-ketones | 4 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| preparation-of-aldehydes-and-ketones | 5 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| preparation-of-aldehydes-and-ketones | 6 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| preparation-of-aldehydes-and-ketones | 7 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| preparation-of-aldehydes-and-ketones | 8 | reaction_scheme | n | superseded | `ff8bb624300c2177:reaction_scheme` |
| preparation-of-carboxylic-acids | 1 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| preparation-of-carboxylic-acids | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| preparation-of-carboxylic-acids | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| preparation-of-carboxylic-acids | 4 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| preparation-of-carboxylic-acids | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| preparation-of-carboxylic-acids | 6 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| preparation-of-carboxylic-acids | 7 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| reactions-of-carbonyl-compounds-with-ammonia-derivatives | 1 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| reactions-of-carbonyl-compounds-with-ammonia-derivatives | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| reactions-of-carbonyl-compounds-with-ammonia-derivatives | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| reactions-of-carbonyl-compounds-with-ammonia-derivatives | 4 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| reactions-of-carbonyl-compounds-with-ammonia-derivatives | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| reactions-of-carbonyl-compounds-with-ammonia-derivatives | 6 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| reactions-of-carboxylic-acids | 1 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| reactions-of-carboxylic-acids | 2 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| reactions-of-carboxylic-acids | 3 | reaction_scheme | n | superseded | `70d67df648003a03:reaction_scheme` |
| reactions-of-carboxylic-acids | 4 | reaction_scheme | n | superseded | `bcc2e2f0e82e5420:reaction_scheme` |
| reactions-of-carboxylic-acids | 5 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |
| reactions-of-carboxylic-acids | 6 | reaction_scheme | n | superseded | `55950b5bfcc61781:reaction_scheme` |
| reactions-of-carboxylic-acids | 7 | reaction_scheme | y | unkeyable | `e3b0c44298fc1c14:reaction_scheme` |

### the 19 n rows that can still be acted on

#### `aldol-condensation` seg 5 — superseded

**objective:** Predict the four possible products when two different aldehydes with alpha-H are mixed.

**widget judged:** `reaction_scheme`

**reason:** — "Crossed Aldol: The Four-Product Problem" **slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high` **objective:** "Predict the four possible products when two different aldehydes with alpha-H are mixed." **params:** ```json {"caption": "Two aldehydes with alpha-H give four products: two self-aldols and two crossed aldols", "species": ["ethanal enolate", "ethanal", "propanal", "propanal enolate", "3-hydroxybutanal", "3-hydroxy-2-methylpentanal", "3-hydroxy-2-methylbutanal", "3-hydroxy-2-methylhexanal"], "step_to": [4, 5, 6, 7], "step_from": [0, 0, 3, 3], "step_kind": ["plain", "plain", "plain", "plain"], "step_reagent": ["ethanal", "propanal", "ethanal", "propanal"]

#### `distinguishing-tests-for-aldehydes-ketones-and-acids` seg 7 — superseded

**objective:** Apply a systematic sequence of tests to identify an unknown carbonyl compound.

**widget judged:** `decline`

**reason:** — "Putting It All Together: The Decision Tree" **slot:** `svg_live` · **declined**, emitted **`text_only`** (no picture at all) **objective:** "Apply a systematic sequence of tests to identify an unknown carbonyl compound." **board (all four events, verbatim types):** `heading`, `text`, `text`, `text` — no `diagram`, no `formula`. > "The Identification Chain: A Four-Station Decision Tree" / "Think like a diagnostic lab: run tests > in a fixed order, each result narrows the field…" / "Station 1 - 2,4-DNP (Brady's reagent): … > No precipitate = not a carbonyl; test with NaHCO3 - fizz means carboxylic acid." / > "Station 2 - Tollens' reagent: silver mirror = ALDEHYDE. No mirror = KETONE." **Cri

#### `distinguishing-tests-for-aldehydes-ketones-and-acids` seg 8 — superseded

**objective:** Calculate moles of silver or Cu2O formed in oxidation tests and avoid common exam pitfalls.

**widget judged:** `decline`

**reason:** — "Stoichiometry and Exam Traps" **slot:** `svg_precomputed` · **declined** (`model_chose_no_widget`), emitted `svg` from `segment_example_diagram_svg` **objective:** "Calculate moles of silver or Cu2O formed in oxidation tests and avoid common exam pitfalls." **what it emitted instead** (the `diagram` board event the student sees): ```json {"template": "ray_diagram", "params": {"optic_type": "convex_lens", "object_pos": 30, "focal_length": 10}, "caption": "Tollens' test: aldehyde reduces Ag+ to a silver mirror"} ``` **Criterion (a) — a physics ray diagram on a chemistry board.** The student is shown a **convex lens with object and focal-length construction rays**, captioned as if it were th

#### `haloform-reaction` seg 1 — superseded

**objective:** Recognize the iodoform test as a qualitative test for methyl ketones and methyl carbinols, and recall its visual signature.

**widget judged:** `decline`

**reason:** — "The Yellow Solid That Tells a Story" **slot:** `svg_live` · **declined**, emitted `svg` from `template_or_live` **objective:** "Recognize the iodoform test as a qualitative test for methyl ketones and methyl carbinols, and recall its visual signature." **what it emitted instead:** ```json {"template": "labeled_axes_plot", "params": {"x_label": "Time (minutes)", "y_label": "Amount of yellow precipitate", "curve_points": [[0,0],[1,2],[2,5],[3,8],[4,10],[5,10]], "annotations": [{"x":2,"y":5,"text":"Yellow solid appears"},{"x":5,"y":10,"text":"Precipitate settles"}], "title": "Formation of Iodoform Precipitate Over Time"}, "caption": "Yellow precipitate builds up as the test proceeds"} ``` **

#### `haloform-reaction` seg 6 — superseded

**objective:** State the reagents and conditions for the iodoform test and list common false positives and negatives.

**widget judged:** `decline`

**reason:** — "Test Conditions and Limitations" **slot:** `svg_live` · **declined**, emitted `svg` from `template_or_live` **objective:** "State the reagents and conditions for the iodoform test and list common false positives and negatives." **what it emitted instead:** ```json {"template": "labeled_axes_plot", "params": {"x_label": "Time (minutes)", "y_label": "Amount of yellow precipitate", "curve_points": [[0,0],[2,1],[4,3],[6,5],[8,6],[10,6]], "annotations": [[4,3,"gentle warming"],[8,6,"plateau"]], "title": "Iodoform precipitate vs warming time"}, "caption": "Gentle warming builds the yellow precipitate; boiling destroys it."} ``` **Criterion (b) — caption contradicts the curve, and the annotation

#### `multi-step-conversions-and-reaction-maps` seg 6 — carried

**objective:** Choose the correct chemical test to distinguish between given aldehydes and ketones, including Tollens', Fehling's, and iodoform tests.

**widget judged:** `decline`

**reason:** — "Distinguishing Tests: A Decision Tree" **slot:** `svg_live` · **declined**, emitted **`text_only`** (no picture at all) **objective:** "Choose the correct chemical test to distinguish between given aldehydes and ketones, including Tollens', Fehling's, and iodoform tests." **board (all four events):** `heading`, `text`, `text`, `formula` > "Distinguishing Tests: A Decision Tree" / "A decision tree narrows possibilities step by step. > Each test is a filter: ask one question, eliminate, move to the next." / > "Step 1 — Is there a -CHO group? Tollens' reagent [Ag(NH3)2]+ gives a silver mirror with ALL > aldehydes (aliphatic and aromatic). Ketones give no reaction." / > `RCHO + 2[Ag(NH_3)_2]^

#### `nomenclature-and-structure-of-carbonyl-compounds` seg 7 — superseded

**objective:** Identify functional and chain isomers of aldehydes and ketones.

**widget judged:** `decline`

**reason:** — "Isomerism in Carbonyl Compounds: Same Formula, Different Structures" **slot:** `svg_live` · **declined**, emitted **`text_only`** (no picture at all) **objective:** "Identify functional and chain isomers of aldehydes and ketones." **board (all four events):** `heading`, `text`, `formula`, `text` > "Isomerism in Carbonyl Compounds" / "Aldehydes and ketones share the general formula CnH2nO, so > they are functional isomers of each other." / `\text{General formula: } C_nH_{2n}O` / > "Functional isomers have the same molecular formula but different functional groups." **Criterion (c) — the segment is literally titled "Same Formula, **Different Structures**" and shows no structures.** Isomeris

#### `nucleophilic-addition-reactions-of-aldehydes-and-ketones` seg 3 — reconfirm

**objective:** Rank carbonyl compounds by reactivity toward nucleophilic addition using steric and electronic factors.

**widget judged:** `reaction_scheme`

**reworded (0.951):** `factors` -> `arguments`

**reason:** — "Reactivity Order: Aldehydes vs Ketones and Electronic Effects" **slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high` **objective:** "Rank carbonyl compounds by reactivity toward nucleophilic addition using steric and electronic factors." **params:** ```json {"caption": "Reactivity toward nucleophilic addition falls as electron donation and steric bulk increase", "species": ["CCl3CHO", "HCHO", "CH3CHO", "CH3COCH3"], "step_to": [1, 2, 3], "step_from": [0, 1, 2], "step_kind": ["major", "plain", "minor"], "step_reagent": ["3× Cl (-I) withdraw", "1× CH3 (+I) donate", "2× CH3 (+I) + steric"], "step_progress": 1, "highlight_step": -1} ``` **Criterion (a) — a ranking r

#### `nucleophilic-addition-reactions-of-aldehydes-and-ketones` seg 8 — superseded

**objective:** Apply the nucleophilic addition framework to predict products and answer exam-style questions.

**widget judged:** `reaction_scheme`

**reason:** — "Putting It All Together: Predicting Products and Solving Problems" **slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high` **objective:** "Apply the nucleophilic addition framework to predict products and answer exam-style questions." **params:** ```json {"caption": "One engine, three nucleophiles: attack, rehybridise, protonate (or eliminate)", "species": ["CH3CH2CHO", "CN-", "CH3CH2CH(O-)CN", "CH3CH2CH(OH)CN", "CH3MgBr", "CH3CH2CH(O-)CH3", "CH3CH2CH(OH)CH3", "NH2OH"], "step_to": [2, 3, 5, 6, 7], "step_from": [0, 2, 0, 5, 0], "step_kind": ["plain", "plain", "plain", "plain", "plain"], "step_reagent": ["CN-", "H+", "CH3MgBr", "H3O+", "NH2OH"], "step_progress": 1,

#### `oxidation-and-reduction-of-aldehydes-and-ketones` seg 2 — superseded

**objective:** Identify the reagents, observations, and limitations of Tollens', Fehling's, and Benedict's tests for aldehydes.

**widget judged:** `reaction_scheme`

**reason:** — "Mild Oxidizing Agents: Tollens', Fehling's, and Benedict's" **slot:** `widget_archetype` · fired `reaction_scheme` · route `archetype_high` **objective:** "Identify the reagents, observations, and limitations of Tollens', Fehling's, and Benedict's tests for aldehydes." **params:** ```json {"species": ["R-CHO", "R-COO-", "R-CO-R'"], "step_from": [0, 2], "step_to": [1, 2], "step_reagent": ["Tollens' [Ag(NH3)2]+ (mild)", "mild oxidant"], "step_kind": ["major", "minor"], "highlight_step": 0, "step_progress": 1, "caption": "Aldehyde ka carbonyl H aasani se C-OH se swap ho jata hai; ketone ke paas H hi nahi, isliye mild oxidant usse chhoota nahi."} ``` **Criterion (b) — caption belongs to the p

#### `oxidation-and-reduction-of-aldehydes-and-ketones` seg 4 — superseded

**objective:** **Compare** the reducing agents NaBH4, LiAlH4, and H2/catalyst for converting aldehydes and ketones to alcohols.

**widget judged:** `reaction_scheme`

**reason:** — "Reduction to Alcohols: NaBH4, LiAlH4, and Catalytic Hydrogenation" **slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high` **objective:** "**Compare** the reducing agents NaBH4, LiAlH4, and H2/catalyst for converting aldehydes and ketones to alcohols." **params:** ```json {"caption": "Reduction adds H across C=O: aldehyde → 1° alcohol, ketone → 2° alcohol", "species": ["RCHO (aldehyde)", "R2C=O (ketone)", "RCH2OH (1° alcohol)", "R2CHOH (2° alcohol)"], "step_to": [2, 3], "step_from": [0, 1], "step_kind": ["major", "major"], "step_reagent": ["NaBH4 / LiAlH4 / H2,catalyst", "NaBH4 / LiAlH4 / H2,catalyst"], "step_progress": 1.0, "highlight_step": -1} ``` **Criterion 

#### `oxidation-and-reduction-of-aldehydes-and-ketones` seg 5 — superseded

**objective:** Apply Clemmensen and Wolff-Kishner reductions to convert carbonyl compounds to alkanes, **choosing the appropriate method based on acid/base sensitivity**.

**widget judged:** `reaction_scheme`

**reason:** — "Reduction to Hydrocarbons: Clemmensen and Wolff-Kishner" **slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high` **objective:** "Apply Clemmensen and Wolff-Kishner reductions to convert carbonyl compounds to alkanes, **choosing the appropriate method based on acid/base sensitivity**." **params:** ```json {"caption": "Deoxygenation: >C=O → >CH2 — Clemmensen (acidic) or Wolff-Kishner (basic)", "species": ["C6H5COCH3", "C6H5CH2CH3", "R2C=O", "R2CH2"], "step_to": [1, 3], "step_from": [0, 2], "step_kind": ["major", "major"], "step_reagent": ["Zn-Hg / conc. HCl (or NH2NH2, KOH / ethylene glycol, 180-200°C)", "Zn-Hg / conc. HCl (or NH2NH2, KOH / ethylene glycol, 180-200

#### `physical-properties-and-hydrogen-bonding-in-carbonyl-compounds` seg 1 — superseded

**objective:** Rank a given set of compounds (hydrocarbon, ether, aldehyde/ketone, alcohol, carboxylic acid) by boiling point using the intermolecular force ladder.

**widget judged:** `decline`

**reason:** — "The Boiling-Point Ladder: Why Carbonyls Sit Where They Do" **slot:** `svg_live` · **declined**, emitted `svg` from `template_or_live` **objective:** "Rank a given set of compounds (hydrocarbon, ether, aldehyde/ketone, alcohol, carboxylic acid) by boiling point using the intermolecular force ladder." **what it emitted instead:** ```json {"template": "free_body_diagram", "params": {"body_label": "molecule", "forces": [{"label":"dispersion","angle":0},{"label":"dipole-dipole","angle":90}, {"label":"H-bond","angle":180},{"label":"dimer","angle":270}]}, "caption": "Intermolecular grips holding a molecule in the liquid"} ``` **Criterion (a) — wrong widget, and it asserts something false.** A fr

#### `physical-properties-and-hydrogen-bonding-in-carbonyl-compounds` seg 5 — superseded

**objective:** Relate intermolecular forces and molecular mass to physical state (gas, liquid, solid) and odour trends.

**widget judged:** `decline`

**reason:** — "Physical States and Odours: Reading the Ladder in the Lab" **slot:** `svg_live` · **declined**, emitted `svg` from `template_or_live` **objective:** "Relate intermolecular forces and molecular mass to physical state (gas, liquid, solid) and odour trends." **what it emitted instead:** ```json {"template": "free_body_diagram", "params": {"body_label": "Molecule", "forces": [{"label":"weak grip","angle":0},{"label":"mass","angle":270}]}, "caption": "Weak grip + low mass = escapes as gas"} ``` **Criterion (a) — "mass" is drawn as a force vector.** Same template abuse as n-15, but this one also puts a scalar on a vector diagram: `{"label": "mass", "angle": 270}` renders an arrow labelled **mas

#### `preparation-of-aldehydes-and-ketones` seg 1 — superseded

**objective:** Recall the structural difference between aldehydes and ketones and explain why selective preparation is important.

**widget judged:** `reaction_scheme`

**reason:** — "The Carbonyl Family and Why Preparation Matters" **slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high` **objective:** "Recall the structural difference between aldehydes and ketones and explain why selective preparation is important." **params:** ```json {"caption": "Selective routes stop at the aldehyde; strong reagents overshoot to acid or alcohol.", "species": ["R-CH2OH", "R-CHO", "R-COOH", "R-CO-R'"], "step_to": [1, 2, 1], "step_from": [0, 1, 3], "step_kind": ["major", "minor", "minor"], "step_reagent": ["PCC / cold DIBAL-H (selective)", "strong oxidant (KMnO4/HNO3)", "strong hydride (LiAlH4)"], "step_progress": 0.5, "highlight_step": 0} ``` **Criterion (b)

#### `preparation-of-aldehydes-and-ketones` seg 8 — superseded

**objective:** Given a target aldehyde or ketone, select an appropriate preparation route from the full map and justify the choice.

**widget judged:** `reaction_scheme`

**reason:** — "Preparation Map and Selectivity Logic" **slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high` **objective:** "Given a target aldehyde or ketone, select an appropriate preparation route from the full map and justify the choice." **params:** ```json {"caption": "Preparation map: gentle reagents stop at the target — poisoned Pd/BaSO4 gives RCHO, R'2Cd gives RCOR'", "species": ["RCH2OH", "RCHO", "RCOCl", "RCN", "RCOR'", "ArCHO", "ArCOCH3"], "step_to": [1, 1, 1, 4, 4, 6], "step_from": [0, 2, 3, 3, 2, 5], "step_kind": ["plain", "major", "major", "major", "major", "major"], "step_reagent": ["Cu, 573 K", "Pd/BaSO4 (poisoned)", "DIBAL-H, cold", "R'2Cd", "CH3COCl / anhyd.

#### `reactions-of-carboxylic-acids` seg 3 — superseded

**objective:** Describe the acid-catalyzed esterification mechanism and explain how to drive the equilibrium forward.

**widget judged:** `reaction_scheme`

**reason:** — "Esterification: Nucleophilic Acyl Substitution Mechanism" **slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high` **objective:** "Describe the acid-catalyzed esterification mechanism and explain how to drive the equilibrium forward." **params:** ```json {"caption": "Acid-catalyzed esterification: protonation → nucleophilic attack → proton transfer → loss of water gives the ester; all steps reversible.", "species": ["RCOOH", "R-C(OH)2+ (protonated)", "tetrahedral intermediate", "R-C(OH)(OH2+)", "RCOOR'", "H2O"], "step_to": [1, 2, 3, 4, 5], "step_from": [0, 1, 2, 3, 4], "step_kind": ["plain", "plain", "plain", "major", "plain"], "step_reagent": ["H+ (H2SO4/HCl)", "

#### `reactions-of-carboxylic-acids` seg 4 — superseded

**objective:** Choose the best reagent to convert a carboxylic acid to an acyl chloride or anhydride and justify the choice.

**widget judged:** `reaction_scheme`

**reason:** — "Conversion to Acyl Chlorides and Anhydrides" **slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high` **objective:** "Choose the best reagent to convert a carboxylic acid to an acyl chloride or anhydride and justify the choice." **params:** ```json {"caption": "Breaking the C–OH bond: SOCl2 wins for acyl chlorides, H2SO4/P2O5 for anhydrides", "species": ["RCOOH", "RCOCl", "POCl3 + HCl", "H3PO3 + HCl", "SO2↑ + HCl↑", "(RCO)2O + H2O"], "step_to": [1, 1, 1, 1, 5], "step_from": [0, 0, 0, 0, 0], "step_kind": ["plain", "minor", "major", "plain", "plain"], "step_reagent": ["PCl5", "PCl3", "SOCl2", "conc. H2SO4 or P2O5, Δ", ""], "step_progress": 1, "highlight_step": 2} ``

#### `reactions-of-carboxylic-acids` seg 6 — superseded

**objective:** Predict the products of decarboxylation (sodalime) and HVZ alpha-halogenation of carboxylic acids.

**widget judged:** `reaction_scheme`

**reason:** — "Decarboxylation and HVZ Halogenation" **slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high` **objective:** "Predict the products of decarboxylation (sodalime) and HVZ alpha-halogenation of carboxylic acids." **params:** ```json {"caption": "Decarboxylation (n → n−1 carbons) vs HVZ α-bromination (COOH kept, α-H swapped)", "species": ["CH3COONa", "CH4", "CH3CH2COONa", "CH3CH2COOH", "CH3CHBrCOOH"], "step_to": [1, 1, 4], "step_from": [0, 2, 3], "step_kind": ["major", "major", "major"], "step_reagent": ["NaOH/CaO, Δ", "NaOH/CaO, Δ", "Br2, red P"], "step_progress": 1, "highlight_step": -1} ``` **Criterion (b) — chemically wrong product.** The second edge is `step_fro

## biology 12 Ecosystem — Ecosystem

proposed y: 53 ; proposed n: 17 (of 70)

| subtopic_key | seg | widget judged | verdict | bucket | verdict_key |
|---|---|---|---|---|---|
| carbon-cycle | 1 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| carbon-cycle | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| carbon-cycle | 3 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| carbon-cycle | 4 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| carbon-cycle | 5 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| carbon-cycle | 6 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| carbon-cycle | 7 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| carbon-cycle | 8 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| carbon-cycle | 9 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| decomposition | 1 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| decomposition | 2 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| decomposition | 3 | process_flow | n | superseded | `6834bd01dcd58a7e:process_flow` |
| decomposition | 4 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| decomposition | 5 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| decomposition | 6 | process_flow | n | superseded | `52b61143881610fa:process_flow` |
| decomposition | 7 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| decomposition | 8 | process_flow | n | superseded | `f1bcc5ced1be6d77:process_flow` |
| eco-pyramids | 1 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| eco-pyramids | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| eco-pyramids | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| eco-pyramids | 4 | decline | n | unkeyable | `e3b0c44298fc1c14:decline` |
| eco-pyramids | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| eco-pyramids | 6 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| eco-pyramids | 7 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| eco-pyramids | 8 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| eco-structure | 1 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| eco-structure | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| eco-structure | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| eco-structure | 4 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| eco-structure | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| eco-structure | 6 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| energy-flow | 1 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| energy-flow | 2 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| energy-flow | 3 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| energy-flow | 4 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| energy-flow | 5 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| energy-flow | 6 | decline | n | reconfirm | `3db05eb717d0bbe9:decline` |
| energy-flow | 7 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| energy-flow | 8 | process_flow | n | superseded | `762b73a2ec334244:process_flow` |
| food-chains | 1 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| food-chains | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| food-chains | 3 | decline | n | carried | `09d8d445538386f5:decline` |
| food-chains | 4 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| food-chains | 5 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| food-chains | 6 | decline | n | reconfirm | `eb399bec85f06ef4:decline` |
| food-chains | 7 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| food-chains | 8 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| food-chains | 9 | decline | n | superseded | `8c576bcb07eed834:decline` |
| phosphorus-cycle | 1 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| phosphorus-cycle | 2 | process_flow | n | reconfirm | `1bd6e20c32e90481:process_flow` |
| phosphorus-cycle | 3 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| phosphorus-cycle | 4 | process_flow | n | reconfirm | `2ab14b5d88c26bc6:process_flow` |
| phosphorus-cycle | 5 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| phosphorus-cycle | 6 | process_flow | n | superseded | `1cb2417ad793c3cb:process_flow` |
| phosphorus-cycle | 7 | process_flow | n | superseded | `e90c0f7679d702a0:process_flow` |
| phosphorus-cycle | 8 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| productivity | 1 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| productivity | 2 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| productivity | 3 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| productivity | 4 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| productivity | 5 | decline | n | superseded | `10756a414304e181:decline` |
| productivity | 6 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| productivity | 7 | decline | y | unkeyable | `e3b0c44298fc1c14:decline` |
| succession | 1 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| succession | 2 | process_flow | n | unkeyable | `e3b0c44298fc1c14:process_flow` |
| succession | 3 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| succession | 4 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| succession | 5 | process_flow | n | unkeyable | `e3b0c44298fc1c14:process_flow` |
| succession | 6 | process_flow | y | unkeyable | `e3b0c44298fc1c14:process_flow` |
| succession | 7 | process_flow | n | unkeyable | `e3b0c44298fc1c14:process_flow` |

### the 13 n rows that can still be acted on

#### `decomposition` seg 3 — superseded

**objective:** Describe fragmentation and leaching, and explain their roles in decomposition.

**widget judged:** `process_flow`

**reason:** criterion (b). This is a strict three-node **prefix of the chain drawn one segment earlier**, with the *same* `active_node: 1`. The student saw Detritus→Fragmentation→Leaching→Catabolism→Humification→Mineralisation in seg 2, with Fragmentation highlighted; seg 3 redraws the first three of those six nodes with Fragmentation highlighted again. The prior-payload block explicitly listed seg 2 and told the model not to repeat it. Nothing about leaching (the new half of this objective) is added — no "minerals washed down", no soil layer, no downward arrow. The correct move here was to keep seg 2's full six-node chain and move `active_node` to 2, or to draw leaching itself. ---

#### `decomposition` seg 6 — superseded

**objective:** Identify the key factors that speed up or slow down decomposition.

**widget judged:** `process_flow`

**reason:** criterion (a), with (b) alongside. These are **two independent two-item contrasts forced into one linear arrow chain**. Read as the chain it declares itself to be (`layout: chain`, `branch_at: -1`), the picture says *Nitrogen-rich detritus → Fast decomposition → Lignin-rich detritus → Slow decomposition* — i.e. that fast decomposition produces lignin-rich detritus, which is false and is a plausible thing for a student to memorise off a board. A contrast of two substrates is a `comparison_table` (which is what `diag_hint` said: `comparison_table`), not a chain. Secondarily (b): the board text names four controlling factors and the picture covers only one of them, so the picture under-serves t

#### `decomposition` seg 8 — superseded

**objective:** Explain how decomposition links to nutrient cycles and the detritus food chain.

**widget judged:** `process_flow`

**reason:** criterion (b). Two things. First, this closed loop is the **same loop as this subtopic's own seg 1** (`["Dead organic matter", "Decomposition", "Inorganic nutrients", "Producers reuse"]`, also `closes: true`) with the middle step split in two — the nutrient loop has already been drawn for this student. Second, the objective and the board both name the **detritus food chain** (detritus → detritivores → **predators**), and the predator / DFC limb is absent; the chain routes to "Plants absorb nutrients" instead, which is the nutrient-cycle half that was already covered.

#### `energy-flow` seg 6 — reconfirm

**objective:** Describe the three types of ecological pyramids and identify which can be inverted.

**widget judged:** `decline`

**reworded (0.932):** `identify` -> `state`

**reason:** criterion (c). An ecological pyramid **is a shape**. The board's own first line calls it "a graphical representation", and the objective asks the student to *identify which can be inverted* — a question that is purely about which way the shape points. This segment asks a student to hold three stacked shapes and one flipped shape in their head from prose alone. This is the single strongest "a student needed a picture and got none" case in the chapter.

#### `energy-flow` seg 8 — superseded

**objective:** Solve typical exam numericals involving energy transfer across trophic levels.

**widget judged:** `process_flow`

**reason:** criterion (b). This is the **third identical energy ladder in one subtopic** and structurally a carbon copy of seg 4 — same three-node shape, same producer/herbivore/ secondary labels, same ×0.1 caption; only the starting number changes (10,000 → 48,000). Both seg 4 and seg 5 were in the prior-payload block. The arithmetic is correct, but as a *picture* it adds nothing the student has not now seen twice; a worked numeric substitution is what the formula event and the narration are for.

#### `food-chains` seg 3 — carried

**objective:** Define trophic level and apply Lindeman's 10% law to calculate energy transfer between levels.

**widget judged:** `decline`

**reason:** criterion (b). The **title is factually wrong**: energy decreases *to* 10% (i.e. *by* 90%), not *by* 10%. The plotted points (100 → 10 → 1 → 0.1) and the caption ("drops by a factor of 10") are both correct, so the title contradicts the data it labels, on the same image. This is not a pedantic point — "10% is transferred / 90% is lost" versus "10% is lost" is a standard NEET distractor, and ROW25 in this very chapter lists PAR-vs-capture confusion as an exam trap of exactly this family. A title is the line a student copies. ---

#### `food-chains` seg 6 — reconfirm

**objective:** Explain how food chains interconnect to form food webs and why food webs are more realistic.

**widget judged:** `decline`

**reworded (0.984):** `` -> `a`; `webs` -> `web`

**reason:** criterion (c). A food web is defined by its **branching**, and the board's own text asserts the contrast — *not simple linear chains*, *feed at multiple trophic levels* — without ever showing it. The concept is one the student cannot form from prose: "network of interconnected chains" only means something once two chains are seen crossing. This slot is `svg_live`, so a live SVG *was* available (five other segments in this same subtopic got one) and the model chose nothing. Of the nine genuine text-only segments in the file, this and ROW44 are the two where the missing picture is the concept itself. ---

#### `food-chains` seg 9 — superseded

**objective:** Apply concepts of food chains, webs, trophic levels, and pyramids to solve typical exam questions.

**widget judged:** `decline`

**reason:** criterion (b). The **caption flatly contradicts the table it captions.** The rows show a tenfold drop (48,000 → 4,800 → 480); the caption reads *"Energy halves at each step."* On a revision/exam-application segment, a caption is the sentence a student memorises, and this one states a wrong transfer ratio directly beneath the correct numbers. Cheap, isolated, unambiguous fix — but as shipped it is a factual error on the board. ---

#### `phosphorus-cycle` seg 2 — reconfirm

**objective:** Identify the main reservoir of phosphorus and explain why the cycle is classified as sedimentary.

**widget judged:** `process_flow`

**reworded (0.946):** `` -> `phosphorus`

**reason:** criterion (a). A **two-row classification table rendered as a four-node linear arrow chain**. Read as the chain it declares itself to be, the board says *Atmosphere/Hydrosphere → Gaseous cycle → Earth's crust/Rocks → Sedimentary cycle* — i.e. that a gaseous cycle leads into the Earth's crust, which is false and is precisely the carbon/phosphorus confusion this subtopic later calls "the biggest trap" (seg 8 board text). The relationship being taught is *reservoir location ↦ cycle class*, a mapping of two independent pairs, not a sequence. Same failure mode as n-2 (ROW15). The hint asked for `comparison_table` and the archetype branch drew a chain instead. ---

#### `phosphorus-cycle` seg 4 — reconfirm

**objective:** Trace the movement of phosphorus from soil to producers **and through the food chain**.

**widget judged:** `process_flow`

**reworded (0.988):** `to` -> `into`

**reason:** criterion (b). The objective and the segment title both name the **food chain**, and the chain stops inside the plant. Tracing phosphorus "through the food chain" needs at minimum a herbivore node; the drawn chain ends at the molecules phosphorus becomes, then stops. This is a chain missing a stage explicitly named in the objective — the caption even concedes the reduced scope ("Phosphorus enters plants from soil"). The captured board events likewise never reach a consumer.

#### `phosphorus-cycle` seg 6 — superseded

**objective:** Describe how phosphorus is lost to sediments **and eventually returns via geological uplift**.

**widget judged:** `process_flow`

**reason:** criterion (b). The chain ends at "Locked for millions of years". **Geological uplift — the return stage named in the segment title, named in the objective, and the only reason this segment is called "The Slow Return" — is not in the chain, and `closes` is false.** The picture therefore teaches that phosphorus goes to the sea floor and stays there: a one-way loss, which is the opposite of the "slow but closed" point. Adding `"Geological uplift"` → `"Rock phosphate"` with `closes: true` would have made the picture say what the title says. ---

#### `phosphorus-cycle` seg 7 — superseded

**objective:** Compare the phosphorus cycle with the carbon cycle, highlighting key differences in speed and reservoir.

**widget judged:** `process_flow`

**reason:** criterion (a), with (b). In a phosphorus-cycle subtopic, on a segment whose whole job is the *comparison*, the board draws **the carbon cycle and only the carbon cycle**. The phosphorus half — rock reservoir, weathering, no atmospheric phase, slow — is absent, so the one-sided picture illustrates the term the student is *not* here to learn. Worse, on a screen where the differentiator is "gaseous vs sedimentary", a closed atmosphere-centred ring is the single most confusable image to leave up. This is a comparison objective (hint: `comparison_table`) satisfied with a one-sided chain. A side-by-side, or a phosphorus ring captioned "no atmospheric phase" (which is what seg 8 eventually draws), 

#### `productivity` seg 5 — superseded

**objective:** State the units of productivity and explain **why dry mass is used** for measurement.

**widget judged:** `decline`

**reason:** criterion (b). **Same template, same title string, same two row labels, same contrast, near-identical caption** — the productivity-vs-standing-crop table is drawn twice in one subtopic, four segments apart. Meanwhile this segment's distinctive content — *why dry mass rather than fresh weight* (water content varies, so fresh-weight comparisons are distorted) — is not in the table at all.

