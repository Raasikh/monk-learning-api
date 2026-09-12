# SANE proposals — pre-review for Raasikh

**Nothing here has been written to the sheets.** All four
`scripts/routing_*_payloads.txt` files still have every SANE line blank
(264 rows, 0 filled, verified 2026-09-11). This file proposes verdicts; on
your confirmation, with any overrides, the sheets get written exactly as
confirmed and pushed.

## How these were judged, and the one limitation that matters

Criteria, as given: (a) wrong widget for what is taught; (b) parameters that
contradict the narration; (c) a decline where a student needed a picture.

**The harness never captured the spoken narration.** It records the segment
objective, title and the board events, not the speech. So criterion (b) has
been applied as "contradicts the objective or the on-board text". Where a
verdict would turn on wording only heard aloud, it is flagged as uncertain
rather than guessed. Four independent reviewers did the four sheets; each
wrote its own full findings, reproduced verbatim below.

## Counts

| sheet | rows | proposed y | proposed n | proposed sane% |
|---|---|---|---|---|
| physics 12 ch1 | 40 | 30 | 10 | 75.0% |
| maths 12 ch8 | 71 | 31 | 40 | 43.7% |
| chem 12 ch8 | 113 | 94 | 19 | 83.2% |
| bio 12 Ecosystem (in-sheet 40) | 40 | 28 | 12 | 70.0% |
| bio 12 Ecosystem (full 70 measured) | 70 | 53 | 17 | 75.7% |

Read against the 85% hold-back bar you set, **no chapter clears it on these
proposals**, and maths 12 ch8 is not close. Per-widget figures are computed
only after you confirm — a proposed n is not a finding until you agree it is.

---

# The "33 Coulomb declines" — the premise does not hold

You asked for a re-measure of physics 12 ch1 "with free_body_forces@1 wired,
targeting the 33 Coulomb declines". Three things are wrong with that as
stated, all checkable:

**1. None of the 33 declines are Coulomb segments.** "Coulomb's Law and
Electric Forces" has NO lesson plan in this chapter — the measured run covers
5 plans, and Coulomb is not one of them (`coulomb` matches 0 of 40 rows). The
33 declines come from:

| subtopic | declines |
|---|---|
| electric-field-lines | 9 |
| electric-charge-properties-quantisation-and-charging | 8 |
| electric-field | 8 |
| equilibrium-of-charges | 8 |

**2. `free_body_forces` routes nothing in physics 12 ch1.** All 7 of its
high-confidence rows in `content/concept-archetypes.csv` are physics **11**:
ch3 Vector Algebra and Resolution, ch4 Common Forces / Concurrent Forces /
Banking, ch6 Rolling Motion, ch9 Stokes' Law, ch13 Simple Pendulum. Physics
12 ch1's own Coulomb concept is archetyped `gap_charge_force_vectors` — a
NAMED GAP, meaning the column's judgement is that no existing widget draws
it. Wiring free_body_forces changes zero rows in this chapter; a re-measure
would produce a byte-identical routing table, which is why one has not been
run.

**3. What probably produced the association:** 13 of the 33 declines carry a
`diag_hint` of `free_body_diagram`. That is a tier-3 DIAGRAM TEMPLATE cue
used when authoring an SVG — not the registry widget `free_body_forces@1`,
and not a routing decision. The two share a name and nothing else.

Also worth stating plainly: **31 of the 33 "declines" still drew a picture**
(an authored SVG); only 2 emitted text alone. So criterion (c) had two real
candidates in this chapter, not 33.

What WOULD change physics 12 ch1 is building the widget the column already
names — `gap_charge_force_vectors` — or promoting a concept to `high`. Both
are decisions for you, not re-measures.

---
# physics 12 ch1 — SANE proposals

> **Evidence limitation (read first).** The harness did **not** capture the spoken
> narration text. Nothing below is based on having read narration. Every verdict is
> inferred from three captured fields only: `segment_title`, `segment_objective`, and
> `model_raw_board_events` (the board lines, which are themselves truncated to the
> first 4–5 events per segment — the trailing `diagram` event is visible for some
> segments and only inferable from `emitted_event_types` for others). Where the board
> capture cuts off before the picture, the verdict rests on the objective plus
> `diag_hint` / `svg_source`, and I say so.
>
> **Second framing note.** 33 of 40 segments are recorded as `fired=false`, but in 31
> of those 33 the student still saw a picture: `emitted_instead="svg"` with a
> `diagram` event on the board. A "decline" here means *the precomputed widget did not
> route*, **not** *the board was blank*. Only two segments emitted no picture at all
> (`emitted_instead="text_only"`): electric-field seg 8 and electric-field-lines seg 6.
> Criterion (c) is therefore scoped almost entirely to those two.

## Counts

proposed y: 30 ; proposed n: 10 (of 40)

## Per-segment verdicts

| subtopic_key | seg | fired widget or decline | slot | verdict |
|---|---|---|---|---|
| electric-charge-properties-quantisation-and-charging | 1 | decline → svg (live, untyped) | svg_precomputed | y |
| electric-charge-properties-quantisation-and-charging | 2 | decline → svg `comparison_table` | svg_precomputed | y |
| electric-charge-properties-quantisation-and-charging | 3 | decline → svg (precomputed example) | svg_precomputed | y |
| electric-charge-properties-quantisation-and-charging | 4 | decline → svg (precomputed example) | svg_precomputed | y |
| electric-charge-properties-quantisation-and-charging | 5 | decline → svg `free_body_diagram` | svg_precomputed | **n (a)+(b)** |
| electric-charge-properties-quantisation-and-charging | 6 | decline → svg `comparison_table` | svg_precomputed | y |
| electric-charge-properties-quantisation-and-charging | 7 | decline → svg (precomputed example) | svg_precomputed | y |
| electric-charge-properties-quantisation-and-charging | 8 | decline → svg (precomputed example) | svg_precomputed | y |
| electric-field | 1 | decline → svg `vector_resolution` | svg_live | **n (a)** |
| electric-field | 2 | decline → svg `free_body_diagram` | svg_live | y |
| electric-field | 3 | decline → svg `free_body_diagram` | svg_live | y |
| electric-field | 4 | decline → svg `free_body_diagram` | svg_live | **n (a)** |
| electric-field | 5 | decline → svg (live, untyped) | svg_live | y |
| electric-field | 6 | decline → svg `free_body_diagram` | svg_precomputed | y |
| electric-field | 7 | decline → svg `boxed_derivation` | svg_precomputed | y |
| electric-field | 8 | decline → **text_only** | svg_live | y |
| electric-field-lines | 1 | decline → svg `process_flow` | svg_live | y |
| electric-field-lines | 2 | decline → svg `comparison_table` | svg_live | y |
| electric-field-lines | 3 | decline → svg (precomputed example) | svg_precomputed | y |
| electric-field-lines | 4 | decline → svg `free_body_diagram` | svg_live | **n (a)** |
| electric-field-lines | 5 | decline → svg `comparison_table` | svg_live | y |
| electric-field-lines | 6 | decline → **text_only** | svg_live | **n (c)** |
| electric-field-lines | 7 | decline → svg (live, untyped) | svg_live | y |
| electric-field-lines | 8 | decline → svg (precomputed example) | svg_precomputed | y |
| electric-field-lines | 9 | decline → svg `comparison_table` | svg_precomputed | y |
| equilibrium-of-charges | 1 | decline → svg `free_body_diagram` | svg_live | y |
| equilibrium-of-charges | 2 | decline → svg `free_body_diagram` | svg_precomputed | y |
| equilibrium-of-charges | 3 | decline → svg `free_body_diagram` | svg_precomputed | y |
| equilibrium-of-charges | 4 | decline → svg `comparison_table` | svg_live | y |
| equilibrium-of-charges | 5 | decline → svg `free_body_diagram` | svg_live | **n (b)** |
| equilibrium-of-charges | 6 | decline → svg `free_body_diagram` | svg_precomputed | y |
| equilibrium-of-charges | 7 | decline → svg `free_body_diagram` | svg_precomputed | y |
| equilibrium-of-charges | 8 | decline → svg `free_body_diagram` | svg_precomputed | y |
| gauss-s-law-and-its-applications | 1 | **fired** `field_lines` v2 (parallel_plates) | widget_precomputed | y |
| gauss-s-law-and-its-applications | 2 | **fired** `field_lines` v2 (point) | widget_precomputed | y |
| gauss-s-law-and-its-applications | 3 | **fired** `field_lines` v2 (point) | widget_archetype | **n (b)** |
| gauss-s-law-and-its-applications | 4 | **fired** `field_lines` v2 (parallel_plates) | widget_precomputed | **n (b)** |
| gauss-s-law-and-its-applications | 5 | **fired** `field_lines` v2 (point) | widget_precomputed | y |
| gauss-s-law-and-its-applications | 6 | **fired** `field_lines` v2 (point) | widget_precomputed | **n (a)** |
| gauss-s-law-and-its-applications | 7 | **fired** `field_lines` v2 (point) | widget_precomputed | **n (a)** |

## Every proposed n, in full

### 1. electric-charge-properties-quantisation-and-charging seg 5 — "Charging by Friction and Conduction"
**Objective (quoted):** "Describe charging by friction and conduction, including charge sharing between identical conductors."
**On the board:** decline (`non_fire_reason=model_chose_no_widget`), emitted `svg` with
`template="free_body_diagram"`, `params={"body_label":"glass rod","forces":[{"label":"e⁻ out","angle":0},{"label":"e⁻ in","angle":180}]}`,
caption "Electrons leave glass, enter silk".
**board_slot:** `svg_precomputed`
**Reason — (a) and (b).** (a) A free-body diagram is a force diagram; its arrows are
read by students as forces. Electron *transfer* is not a force, so the template mis-teaches
the quantity being drawn. (b) The parameters also contradict the board text directly: the
board says "glass loses electrons → positive; silk gains them → negative", i.e. a
one-directional transfer *off* the glass rod, but the diagram puts both an "e⁻ out" and an
"e⁻ in" arrow on the single body labelled "glass rod". The caption ("leave glass, enter
silk") describes two different bodies while the figure has one.

### 2. electric-field seg 1 — "How Does One Charge Know the Other Is There?"
**Objective (quoted):** "Explain why the electric field concept is needed and how it resolves the action-at-a-distance problem."
**On the board:** decline, emitted `svg` with `template="vector_resolution"`,
`params={"magnitude_label":"E","angle_deg":35,"x_label":"E cos(theta)","y_label":"E sin(theta)"}`,
caption "Field vector E resolved into components at a point in space".
**board_slot:** `svg_live`
**Reason — (a).** The segment is conceptual and its board text is explicit about the
mechanism it wants pictured: "The field concept splits the interaction into two stages: a
charge modifies the space around it … a second charge responds to the field at its own
location." The picture drawn is a component-resolution triangle — a computational device
for a later, different skill. It shows neither the two-stage mechanism nor the
action-at-a-distance problem. Nothing on this board mentions components or angles.

### 3. electric-field seg 4 — "Electric Field Lines and Their Four Rules"
**Objective (quoted):** "Interpret electric field line diagrams and state the four rules they obey."
**On the board:** decline, emitted `svg` with `template="free_body_diagram"`,
`params={"body_label":"+Q","forces":[{"label":"E","angle":0},{"label":"E","angle":90},{"label":"E","angle":180},{"label":"E","angle":270}]}`,
caption "Field lines radiate outward from a positive charge".
**board_slot:** `svg_live`
**Reason — (a).** This is the clearest wrong-widget case in the set. The objective is
*literally* "interpret electric field line diagrams", and `field_lines` is an existing
widget whose `configuration:"point"` draws exactly this. Instead an FBD is bent into
four arrows to imitate a radial field. The board text says "the density of lines gives its
magnitude" — a four-arrow FBD has no line density to read, so the figure cannot support
the rule the board just stated. (Caveat: this subtopic is `electric-field`, routed as
*med / gap_dipole_field_geometry*, so the archetype column was never going to route
anything here; the defect is in the fallback template choice, not in the archetype gate.)

### 4. electric-field-lines seg 4 — "Charging by Friction and by Conduction"
**Objective (quoted):** "Describe the outcomes of charging by friction and by conduction, including the sign of charge acquired."
**On the board:** decline, emitted `svg` with `template="free_body_diagram"`,
`params={"body_label":"Glass rod","forces":[{"label":"e⁻ transfer","angle":0}]}`,
caption "Electrons leave the glass and go to the silk".
**board_slot:** `svg_live`
**Reason — (a).** Same category error as item 1: a force template used to depict electron
transfer, so the single arrow reads as a force on the glass rod. The objective's actual
payload — "the sign of charge acquired" — is what needs picturing, and an FBD cannot
carry sign. `process_flow` (which this same subtopic used correctly in seg 1 for exactly
this idea) would have been the right template. Less severe than item 1 because the single
arrow at least does not contradict the direction stated on the board.

### 5. electric-field-lines seg 6 — "The Gold-Leaf Electroscope and Why Quantisation Hides"
**Objective (quoted):** "Explain how a gold-leaf electroscope detects charge and why quantisation is not noticeable at macroscopic scales."
**On the board:** decline, `emitted_instead="text_only"`, `svg_source=null`,
`diag_hint=null`, `emitted_event_types=["heading","text","text","text"]` — **no picture at all.**
**board_slot:** `svg_live`
**Reason — (c).** This is the strongest decline-where-a-picture-was-needed case. The board
text is pure apparatus description: "a metal rod ending in two thin gold leaves inside a
glass case, topped by a metal disc", then "both leaves … repel each other, causing them to
diverge", then "the angle of divergence indicates how much charge is present". Three
consecutive text lines describing a physical object's parts and its observable geometry,
with zero visual support. `labelled_figure` exists and is precisely this template. Note
the contrast: the same electroscope content in
`electric-charge-properties-quantisation-and-charging seg 7` *did* get a picture
(`svg_source=segment_example_diagram_svg`), so the asset gap is not the cause here.

### 6. equilibrium-of-charges seg 5 — "Equilibrium on a Ring: Symmetry in Action"
**Objective (quoted):** "Determine equilibrium configurations of charges constrained to a ring and analyze their stability."
**On the board:** decline, emitted `svg` with `template="free_body_diagram"`,
`params={"body_label":"q","forces":[{"label":"F_rep","angle":90},{"label":"F_rep","angle":210},{"label":"F_rep","angle":330}]}`,
caption "Net repulsion on one ring charge points radially outward".
**board_slot:** `svg_live`
**Reason — (b).** The parameters contradict the board text. The board sets up "For N=3:
three equal charges q at 120° intervals on a ring" and the caption scopes the figure to
"**one** ring charge". A single one of three mutually repelling charges experiences
**two** repulsions, not three — but the params draw three `F_rep` arrows at 90°/210°/330°,
which are the *positions* of the three charges, not the forces on one of them. A student
counting arrows gets the wrong free-body count for the very force balance the segment is
deriving. The in-file counter-example is decisive: seg 8 of this same subtopic sets up the
identical three-charges-on-a-ring problem and correctly draws two `F_rep` plus one
`F_att`, so the template is capable of the right thing and seg 5 is an outlier.

### 7. gauss-s-law-and-its-applications seg 3 — "Field of an Infinite Line Charge"
**Objective (quoted):** "Derive the electric field of an infinite line charge using Gauss's law."
**On the board:** **fired** `field_lines` v2, `route=archetype_high`, `board_slot=widget_archetype`,
`params={"configuration":"point","charge_uc":10,"show_arrows":true,"annotate":"termination"}`,
caption "Radial field lines around the charged wire — a coaxial cylinder is the matching Gaussian surface."
**Reason — (b).** The parameters contradict the caption and the board text. The board says
"An infinite straight wire carries uniform linear charge density lambda", "the field is
radial (perpendicular to the wire)", "choose a coaxial cylindrical Gaussian surface". The
rendered figure is `configuration:"point"` — a point charge. The caption asserts to the
student that they are looking at a wire and an implied coaxial cylinder; neither is in the
picture. Point-charge radial (3D, 1/r²) and line-charge radial (cylindrical, 1/r) are
different geometries and the distinction is the entire content of the segment. This is the
worst kind of mismatch: a confident caption describing a figure that is not there.

### 8. gauss-s-law-and-its-applications seg 4 — "Field of an Infinite Plane Sheet"
**Objective (quoted):** "Derive the electric field of an infinite plane sheet of charge."
**On the board:** **fired** `field_lines` v2, `route=archetype_high`,
`params={"annotate":"termination","charge_uc":12,"show_arrows":true,"configuration":"parallel_plates"}`,
caption None.
**PRIOR:** segment 3 — `field_lines` {configuration: point, annotate: termination, charge_uc: 10}.
**board_slot:** `widget_precomputed`
**Reason — (b).** The board text is explicit that this is a **single** sheet and that
the field "has equal magnitude on **both sides**". `configuration:"parallel_plates"` draws
two oppositely charged plates with the field confined *between* them and (near-)zero
outside — the exact opposite of what the board just asserted. This is not a neutral
approximation: single-sheet σ/2ε₀ versus parallel-plate σ/ε₀ is one of the standard NEET/JEE
traps in this chapter, and the picture silently teaches the wrong one of the pair.

### 9. gauss-s-law-and-its-applications seg 6 — "Applying Gauss's Law: Symmetry and Strategy"
**Objective (quoted):** "Choose appropriate Gaussian surfaces for symmetric charge distributions and compute fields."
**On the board:** **fired** `field_lines` v2, `route=archetype_high`,
`params={"annotate":null,"charge_uc":8,"show_arrows":true,"configuration":"point"}`, caption **None**.
**PRIOR:** segment 3 — `field_lines` {configuration: point, …}.
**board_slot:** `widget_precomputed`
**Reason — (a).** The segment teaches a *selection procedure* across three cases — the
board lists them: "spherical (point charge, shell, solid sphere), cylindrical (infinite
line, coaxial cable), planar (infinite sheet, slab)" and then "match the Gaussian surface
to the symmetry: sphere … coaxial cylinder … pillbox". The widget can draw none of the
three surfaces and covers only one of the three symmetries. With `annotate:null` and
`caption:null` the student gets an unexplained point-charge starburst next to a
three-way comparison. A comparison/table-shaped figure is what this board wants; the
`field_lines` firing here looks driven by `archetype_high` on the concept rather than by
this segment's need. Flagging as a judgement call, not a hard error.

### 10. gauss-s-law-and-its-applications seg 7 — "Common Pitfalls and Exam Traps"
**Objective (quoted):** "Avoid typical mistakes in flux and Gauss's law problems."
**On the board:** **fired** `field_lines` v2, `route=archetype_high`,
`params={"annotate":"termination","charge_uc":8,"show_arrows":true,"configuration":"point"}`, caption None.
**PRIOR:** segment 3 — `field_lines` {configuration: point, annotate: termination, charge_uc: 10} — i.e. the same figure modulo `charge_uc`.
**board_slot:** `widget_precomputed`
**Reason — (a).** Two problems. First, redundancy: this is the fifth `configuration:"point"`
field-lines figure in a seven-segment subtopic (segs 2, 3, 5, 6, 7) and is parametrically
near-identical to the one the PRIOR block records as already drawn in seg 3 — the harness's
own framing question ("is it different from what the prior-payload lines say was already
drawn?") answers no. Second, fit: the trap on the board is "field lines entering one side
leave the other" for an **external** charge crossing a **closed surface**. The figure has no
closed surface and no external charge, so it cannot depict the trap. An unchanged repeat
figure beside a pitfalls list is board noise.

## Notes and uncertainties

1. **No narration was captured.** Stated again because it is the single largest limit on
   these verdicts. Several y's would flip to n if the spoken line contradicted the figure,
   and several n's (notably items 2 and 9) would soften if narration explicitly bridged the
   picture to the objective. `sane` is null on all 40 records; nothing here is a
   confirmation of a prior human judgement.

2. **`model_raw_board_events` is truncated.** Each record holds only the first 3–5 events.
   For 12 segments the trailing `diagram` event is cut off and its existence is known only
   from `emitted_event_types`; for those I could not see the template or its params at all.
   Affected y-verdicts resting on inference rather than a seen figure:
   charge segs 1, 3, 4, 7, 8; electric-field segs 5, 7; electric-field-lines segs 3, 7, 8;
   gauss segs 1, 2, 4, 5, 6, 7 (params were available from the `params` column for the
   gauss firings, so only the caption/placement is unseen there). No n-verdict rests on an
   unseen figure except items 8–10, where the `params` column supplied the full payload.

3. **The "decline" framing is misleading in this dataset.** `fired=false` is recorded for 33
   segments, but 31 of them put an SVG diagram on the board. If a reviewer reads this
   file's counts as "33 segments had no picture", that is wrong. Criterion (c) only had two
   candidates to work with, and I flagged one of them.

4. **Content drift in `electric-field-lines`.** All nine segments under that subtopic_key
   teach basic electrostatics (two kinds of charge, conductors/insulators, quantisation,
   friction/conduction/induction, electroscope, q=ne worked examples) — not field lines.
   Their content is near-duplicate of the eight `electric-charge-properties-…` segments.
   This is a lesson-planning defect, not a board defect, and I judged each segment against
   what it actually teaches (so the declines there are sane). But it also means the
   low-confidence archetype gate on "Electric Field Lines" was never exercised, and the
   `field_lines` widget's real home subtopic has no segments in this sample. Worth raising
   separately.

5. **Borderline y's I chose not to flag,** listed so Raasikh can overrule:
   - `electric-field` seg 3: FBD shows one force on q0, but the objective includes
     "apply superposition to multiple charges" — the figure shows a single source. Incomplete
     rather than contradictory.
   - `electric-field` seg 7: `boxed_derivation` for the ring axial field. The cancellation
     argument ("perpendicular components of dE cancel") is geometric and would be better
     served by a ring figure; a boxed derivation is still a defensible choice for a
     derivation segment.
   - `electric-field-lines` seg 9: `comparison_table` of removing-vs-adding electrons, in a
     segment whose objective is "quantisation with Coulomb's law and repeated charge
     sharing". The table shows neither Coulomb nor repeated sharing — low value, but it does
     not contradict anything, so y.
   - `gauss` seg 5 (spherical shell): `configuration:"point"` correctly renders the
     external field (which *is* point-like), but cannot show E=0 inside, which is half the
     objective. Partial rather than wrong; contrast with seg 4, which I did flag because
     there the widget shows something actively false.
   - `gauss` seg 1: `parallel_plates` for "flux through a flat surface in a uniform field"
     is a reasonable uniform-field stand-in. Note the same configuration is *not* reasonable
     in seg 4, for a different reason.
   - `charge` seg 6 / `electric-field-lines` seg 5: `comparison_table` covers the
     "contrast with conduction" half of the objective but not the "steps of induction" half,
     which `process_flow` would carry.
   - `electric-field` seg 8 (`text_only`): a pitfalls/pro-tips list is legitimately textual,
     and the `diag_hint` was `projectile_scene` — declining that hint was correct.

6. **Systematic pattern worth acting on.** Two distinct failure modes, cleanly separated:
   (i) in the *declining* subtopics, `free_body_diagram` is being used as a generic
   "labelled blob with arrows" template, which is correct wherever real forces are balanced
   (all of `equilibrium-of-charges` except seg 5) and wrong wherever the arrows are not
   forces (electron transfer, field lines) — items 1, 3, 4;
   (ii) in the one *firing* subtopic, `archetype_high` routes `field_lines` into all seven
   segments regardless of whether the geometry matches, producing `configuration:"point"` for
   a line charge, `parallel_plates` for a single sheet, and three near-duplicate point
   figures — items 7–10. Four of seven firings flagged versus six of thirty-three declines
   suggests the forced archetype route is currently the higher-defect path, not the safer one.

7. **Cosmetic, not judged:** `equilibrium-of-charges` seg 4's caption contains untranslated
   Hinglish ("Stable, unstable aur neu…"). Several fired payloads carry `caption: null`
   (gauss segs 1, 2, 4, 5, 6, 7), leaving figures unlabelled on the board.
# maths 12 ch8 — SANE proposals

Source: `/Users/raasikhnaveed/Desktop/monk-learning-api/scripts/routing_maths12_ch8.jsonl` (71 records).

**LIMITATION — read this first.** The harness did **not** capture spoken narration. Every verdict
below is judged from `segment_objective`, `segment_title` and `model_raw_board_events` (the board text
the student sees) only. I have **not** read the narration and make no claim about what was said aloud.
Where I write "contradicts the narration", read it as "contradicts the objective and the board text".

Second evidence note: parameter semantics are not guessed. They are read from the renderer -
`/Users/raasikhnaveed/Desktop/monk-learning-mobile/monklearning-mobile/lib/widgets/xy-plot/plot-math.ts`
(`evalCurve`) and `.../xy-plot/index.tsx` (the v3/v4 header ledger and `validate()`), plus the registry
blurb in `/Users/raasikhnaveed/Desktop/monk-learning-api/app/drona/widget_registry.py`. Two facts from
there do most of the work:

- `line` evaluates **a*x + c**. `b` is ignored for a line, so an intercept placed in `b` silently vanishes.
- `reciprocal` is `a/x + c` and `validate()` **refuses** a domain spanning x = 0.
- The registry says plainly: **"No circles/regions/panels."**
- index.tsx carries a per-concept coverage ledger for *this exact chapter*: concepts 1, 2, 3 (line/parabola
  pairs), 4 (tangent/normal, via `tangent_at`/`tangent_kind`), 8 (modulus, via `pieces`) and 10
  (`integrate_along`) are **YES**; concept 7 (circles/ellipses) is **NO**; 5, 6 and 9 are partial.
  That ledger is the yardstick I use for whether a decline was honest.

## Counts

proposed y: 31 ; proposed n: 40 (of 71)

Of the 40 proposed n: 16 are fired-widget parameter faults (criterion b), 15 are wrong-picture
substitutions (criterion a), 9 are declines where the student needed a picture the widget could draw
(criterion c).

## Systematic patterns (the reusable findings)

**1. `b` is not an intercept on a `line`, and two payloads were written as if it were.**
`evalCurve` for `line` returns `a*x + c`; `b` is dead. Segment 56 wrote `a:-1, b:2, c:0` meaning
y = 2 - x and got y = -x (a triangle below the axis, derived area -2 where the caption promises +2).
Segment 57 wrote `a2:1, b2:2, c2:0` meaning y = x + 2 and got y = x. This is a silent, validator-clean
class of error: the payload passes, the picture is wrong, and nothing in the pipeline notices. Worth a
server-side lint - **`b`/`b2` set to non-zero while `curve`/`curve2` is `line` is always a mistake.**

**2. Circles are drawn as parabolas and hyperbolas.** The widget says "No circles/regions/panels" and
the chapter ledger lists concept 7 as NO. The circles-and-ellipses subtopic respected that perfectly
(8/8 honest declines to conic_figure, which draws real circles and ellipses). But four segments in OTHER
subtopics faked a circle inside xy_plot anyway: 59 and 60 draw sqrt(2-x^2) and sqrt(8-x^2) as downward
parabolas, 68 draws a quarter circle as y = 1 - x^2 while labelling the y-axis "y = sqrt(a^2 - x^2)",
and 70 draws the cap of x^2+y^2=16 as the hyperbola y = 4/x. The decline logic knows circles are out of
scope in one subtopic and not in another.

**3. Two payloads will not render at all.** `validate()` refuses a `reciprocal` whose domain spans
x = 0. Segments 67 (`x_min:-1.2, x_max:1.2`) and 70 (`x_min:-4.5, x_max:4.5`) both do. `client_validate`
is null for all 23 fired records, so the harness never ran the check that would have caught them - the
run reports `server_validated: true` and the board is still likely to come up empty.

**4. `pieces` is never used, so every modulus is drawn as a straight line.** Segments 54, 55 and 58 all
caption a V-shape (`y = |x|`) over params that draw y = x. The index.tsx header specifically advertises
"y = x^2 against y = |x| is ONE payload now, and reports 1/3". Zero of the 71 segments set `pieces`.

**5. `tangent_at`/`tangent_kind` is never used, and the whole tangent/normal subtopic went to SVG.**
0 of 8 segments fired; seven of them show a bare `conic_figure` parabola under a caption naming a
tangent or normal that is not on the board. This is the v3 feature whose entire purpose was to stop the
payload author hand-deriving `y = 2x - 1` - and segment 21 has the board printing `y = 2x - 1` by hand
next to a figure with no line in it.

**6. The decline reason `widget_cannot_express_concept` is unreliable in one direction.**
All 16 structured declines fall in exactly two subtopics: circles/ellipses (8, all honest) and
integration along the y-axis (8, of which I propose 5 are false). `integrate_along` is the named v3
feature for that concept and it is used successfully at segments 27 and 64 of the same run, so the
declines contradict the run's own behaviour. Conversely, several segments that SHOULD have declined
(the faked circles) did not - the reason field is not tracking capability, it is tracking something else.

**7. Identical objectives route differently depending on subtopic.** "Area between two curves,
top minus bottom" fires xy_plot 7/7 in `area-bounded-by-a-parabola-and-a-line` and 0/9 in
`area-between-two-intersecting-curves`. "Sketch the intersection of two inequality regions" gets
text_only at idx 50 and a correct `area_between` payload at idx 57. "dx vs dy" declines at idx 35 and
fires at idx 69. Whatever is driving the decision, it is not the concept.

**8. Where the model fired correctly, it fired well.** Segments 29, 30, 56 (bug aside), 57, 62, 63, 64,
65 show the routing is capable: real coefficients matching the board's own example, `integrate_along:'y'`
used correctly for a dy objective, a genuinely below-axis parabola for the below-axis segment. The
failure mode is not "cannot", it is "pastes a default y = x^2 / y = x pair under a caption naming
different curves" - segments 25, 26, 27 and 28 are four consecutive instances of that same boilerplate.

## Per-segment verdicts

| subtopic_key | seg | fired widget or decline | slot | verdict |
|---|---|---|---|---|
| area-between-a-function-and-its-inverse | 1 | no widget -> ray_diagram | svg_live | **n — (a)** |
| area-between-a-function-and-its-inverse | 2 | no widget -> text_only | svg_live | **n — (c)** |
| area-between-a-function-and-its-inverse | 3 | no widget -> comparison_table | svg_precomputed | y |
| area-between-a-function-and-its-inverse | 4 | no widget -> labeled_axes_plot | svg_precomputed | y |
| area-between-a-function-and-its-inverse | 5 | no widget -> ray_diagram | svg_precomputed | **n — (a)** |
| area-between-a-function-and-its-inverse | 6 | no widget -> comparison_table | svg_precomputed | y |
| area-between-a-function-and-its-inverse | 7 | no widget -> svg | svg_precomputed | y |
| area-between-two-intersecting-curves | 1 | no widget -> labeled_axes_plot | svg_live | **n — (a)** |
| area-between-two-intersecting-curves | 2 | no widget -> labeled_axes_plot | svg_precomputed | **n — (a)** |
| area-between-two-intersecting-curves | 3 | no widget -> conic_figure | svg_precomputed | **n — (a)** |
| area-between-two-intersecting-curves | 4 | no widget -> conic_figure | svg_precomputed | **n — (a)** |
| area-between-two-intersecting-curves | 5 | no widget -> number_line | svg_live | y |
| area-between-two-intersecting-curves | 6 | no widget -> conic_figure | svg_precomputed | **n — (a)** |
| area-between-two-intersecting-curves | 7 | no widget -> conic_figure | svg_precomputed | y |
| area-between-two-intersecting-curves | 8 | no widget -> labeled_axes_plot | svg_precomputed | y |
| area-between-two-intersecting-curves | 9 | no widget -> svg | svg_precomputed | y |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 1 | no widget -> conic_figure | svg_live | **n — (a)** |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 2 | no widget -> labeled_axes_plot | svg_precomputed | **n — (a)** |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 3 | no widget -> labeled_axes_plot | svg_precomputed | **n — (a)** |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 4 | no widget -> conic_figure | svg_live | **n — (a)** |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 5 | no widget -> labeled_axes_plot | svg_precomputed | **n — (a)** |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 6 | no widget -> conic_figure | svg_precomputed | **n — (a)** |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 7 | no widget -> conic_figure | svg_precomputed | **n — (a)** |
| area-bounded-by-a-curve-and-its-tangent-or-normal | 8 | no widget -> conic_figure | svg_precomputed | y |
| area-bounded-by-a-parabola-and-a-line | 1 | xy_plot v4 | widget_archetype | **n — (b)** |
| area-bounded-by-a-parabola-and-a-line | 2 | xy_plot v4 | widget_archetype | **n — (b)** |
| area-bounded-by-a-parabola-and-a-line | 3 | xy_plot v4 | widget_archetype | **n — (b)** |
| area-bounded-by-a-parabola-and-a-line | 4 | xy_plot v4 | widget_archetype | **n — (b)** |
| area-bounded-by-a-parabola-and-a-line | 5 | xy_plot v4 | widget_archetype | **n — (b)** |
| area-bounded-by-a-parabola-and-a-line | 6 | xy_plot v4 | widget_archetype | y |
| area-bounded-by-a-parabola-and-a-line | 7 | xy_plot v4 | widget_archetype | y |
| area-by-integration-along-the-y-axis | 1 | DECLINE cannot_express -> conic_figure | svg_precomputed | **n — (c)** |
| area-by-integration-along-the-y-axis | 2 | DECLINE cannot_express -> number_line | svg_precomputed | **n — (c)** |
| area-by-integration-along-the-y-axis | 3 | DECLINE cannot_express -> number_line | svg_precomputed | y |
| area-by-integration-along-the-y-axis | 4 | DECLINE cannot_express -> conic_figure | svg_precomputed | **n — (c)** |
| area-by-integration-along-the-y-axis | 5 | DECLINE cannot_express -> conic_figure | svg_precomputed | y |
| area-by-integration-along-the-y-axis | 6 | DECLINE cannot_express -> conic_figure | svg_precomputed | **n — (c)** |
| area-by-integration-along-the-y-axis | 7 | DECLINE cannot_express -> conic_figure | svg_precomputed | **n — (c)** |
| area-by-integration-along-the-y-axis | 8 | DECLINE cannot_express -> labeled_axes_plot | svg_precomputed | y |
| area-of-regions-bounded-by-circles-and-ellipses | 1 | DECLINE cannot_express -> conic_figure | svg_live | y |
| area-of-regions-bounded-by-circles-and-ellipses | 2 | DECLINE cannot_express -> conic_figure | svg_precomputed | y |
| area-of-regions-bounded-by-circles-and-ellipses | 3 | DECLINE cannot_express -> boxed_derivation | svg_precomputed | y |
| area-of-regions-bounded-by-circles-and-ellipses | 4 | DECLINE cannot_express -> conic_figure | svg_live | y |
| area-of-regions-bounded-by-circles-and-ellipses | 5 | DECLINE cannot_express -> boxed_derivation | svg_precomputed | y |
| area-of-regions-bounded-by-circles-and-ellipses | 6 | DECLINE cannot_express -> conic_figure | svg_precomputed | y |
| area-of-regions-bounded-by-circles-and-ellipses | 7 | DECLINE cannot_express -> conic_figure | svg_precomputed | y |
| area-of-regions-bounded-by-circles-and-ellipses | 8 | DECLINE cannot_express -> conic_figure | svg_live | y |
| area-of-regions-described-by-inequalities | 1 | no widget -> number_line | svg_live | **n — (a)** |
| area-of-regions-described-by-inequalities | 2 | no widget -> number_line | svg_live | y |
| area-of-regions-described-by-inequalities | 3 | no widget -> boxed_derivation | svg_precomputed | **n — (c)** |
| area-of-regions-described-by-inequalities | 4 | no widget -> text_only | svg_live | **n — (c)** |
| area-of-regions-described-by-inequalities | 5 | no widget -> number_line | svg_live | y |
| area-of-regions-described-by-inequalities | 6 | no widget -> svg | svg_precomputed | **n — (c)** |
| area-of-regions-described-by-inequalities | 7 | no widget -> number_line | svg_live | y |
| area-of-regions-involving-modulus-and-piecewise-defined-functions | 1 | xy_plot v4 | widget_archetype | **n — (b)** |
| area-of-regions-involving-modulus-and-piecewise-defined-functions | 2 | xy_plot v4 | widget_archetype | **n — (b)** |
| area-of-regions-involving-modulus-and-piecewise-defined-functions | 3 | xy_plot v4 | widget_archetype | **n — (b)** |
| area-of-regions-involving-modulus-and-piecewise-defined-functions | 4 | xy_plot v4 | widget_archetype | **n — (b)** |
| area-of-regions-involving-modulus-and-piecewise-defined-functions | 5 | xy_plot v4 | widget_archetype | **n — (b)** |
| area-of-regions-involving-modulus-and-piecewise-defined-functions | 6 | xy_plot v4 | widget_archetype | **n — (b)** |
| area-of-regions-involving-modulus-and-piecewise-defined-functions | 7 | xy_plot v4 | widget_archetype | **n — (b)** |
| area-of-regions-involving-modulus-and-piecewise-defined-functions | 8 | no widget -> text_only | widget_archetype | y |
| area-under-a-simple-curve-bounded-by-the-axes | 1 | xy_plot v4 | widget_precomputed | y |
| area-under-a-simple-curve-bounded-by-the-axes | 2 | xy_plot v4 | widget_archetype | y |
| area-under-a-simple-curve-bounded-by-the-axes | 3 | xy_plot v4 | widget_precomputed | y |
| area-under-a-simple-curve-bounded-by-the-axes | 4 | xy_plot v4 | widget_precomputed | y |
| area-under-a-simple-curve-bounded-by-the-axes | 5 | xy_plot v4 | widget_archetype | **n — (b)** |
| area-under-a-simple-curve-bounded-by-the-axes | 6 | xy_plot v4 | widget_precomputed | **n — (b)** |
| area-under-a-simple-curve-bounded-by-the-axes | 7 | xy_plot v4 | widget_archetype | **n — (b)** |
| area-under-a-simple-curve-bounded-by-the-axes | 8 | xy_plot v4 | widget_precomputed | y |
| area-under-a-simple-curve-bounded-by-the-axes | 9 | xy_plot v4 | widget_precomputed | **n — (b)** |

## Every proposed n, in full

### idx 0 — area-between-a-function-and-its-inverse / seg 1 — The Mirror Property of Inverse Functions

- **Objective:** "Explain why the graph of an inverse function is the reflection of the original graph across the line y = x."
- **board_slot:** `svg_live`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `ray_diagram` (svg template), params verbatim:

```json
{
  "optic_type": "convex_lens",
  "object_pos": 30,
  "focal_length": 10
}
```

- **Caption:** "Reflection across y = x swaps coordinates"
- **diag_hint was:** `ray_diagram`

- **Proposed n, criterion (a)** — confidence high. The segment teaches that the graph of f-inverse is the reflection of f in y = x. The board emitted a **ray_diagram** with `optic_type: convex_lens, object_pos: 30, focal_length: 10`, captioned 'Reflection across y = x swaps coordinates'. That is an OPTICS lens-and-rays figure standing in for a coordinate reflection. Nothing in it shows a curve, a diagonal, or a swapped point pair. Wrong widget outright.

### idx 1 — area-between-a-function-and-its-inverse / seg 2 — The Mirror Trick for Area Between Inverses

- **Objective:** "State and prove the mirror trick formula for the area between a function and its inverse when the function is increasing and lies above the diagonal."
- **board_slot:** `svg_live`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `text_only` — no diagram node on the board at all.
- **diag_hint was:** `ray_diagram`

- **Proposed n, criterion (c)** — confidence medium. A geometric proof: 'the diagonal y=x cuts the region into two pieces... reflection fixes the diagonal and swaps the graphs, so the two pieces are congruent. The piece above the diagonal has area int(f(x)-x). Double it.' The entire argument is about two congruent halves of a picture, and the board is four text nodes with no figure at all. Even under the widget's documented limit for this concept (line/line pairs only), a line-against-line payload with y=x as curve2 and the upper piece shaded is the exact picture the proof describes.

### idx 4 — area-between-a-function-and-its-inverse / seg 5 — Area Between x^3 and x^{1/3}

- **Objective:** "Apply the mirror trick to find the area enclosed between y=x^3 and y=x^{1/3}."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `ray_diagram` (svg template), params verbatim:

```json
{
  "optic_type": "convex_lens",
  "object_pos": 30,
  "focal_length": 20
}
```

- **Caption:** "Reflection across y = x mirrors the two inverse curves"
- **diag_hint was:** `ray_diagram`

- **Proposed n, criterion (a)** — confidence high. Same optics figure again: **ray_diagram** `optic_type: convex_lens, object_pos: 30, focal_length: 20`, captioned 'Reflection across y = x mirrors the two inverse curves', for the area between y=x^3 and y=x^(1/3). A convex lens is not a reflection in y=x. (The xy_plot decline itself is honest here - the widget header records concept 6 as PART, line/line pairs only - but the substitute is the wrong picture.)

### idx 7 — area-between-two-intersecting-curves / seg 1 — The Core Idea: Top Minus Bottom

- **Objective:** "Understand the formula for area between two curves using vertical strips and apply it when the upper and lower curves are known."
- **board_slot:** `svg_live`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `labeled_axes_plot` (svg template), params verbatim:

```json
{
  "x_label": "x",
  "y_label": "y",
  "curve_points": [
    [
      0,
      0.2
    ],
    [
      0.5,
      0.5
    ],
    [
      1,
      1
    ],
    [
      1.5,
      1.6
    ],
    [
      2,
      2.2
    ]
  ],
  "annotations": [
    {
      "x": 1,
      "y": 1,
      "text": "f(x) upper"
    },
    {
      "x": 1,
      "y": 0.4,
      "text": "g(x) lower"
    }
  ],
  "title": "Vertical strip: height = f(x) - g(x)"
}
```

- **Caption:** "Thin vertical strip between the two curves"
- **diag_hint was:** `labeled_axes_plot`

- **Proposed n, criterion (a)** — confidence high. This is the flagship 'area between two curves, top minus bottom' segment. The widget header records concept 3, 'Area between two intersecting curves', as YES for line/parabola pairs, and segments 24 and 30 of this same chapter fire exactly that payload. Instead the board drew **labeled_axes_plot** with a SINGLE `curve_points` list ([[0,0.2],...,[2,2.2]]) and two annotations that merely NAME 'f(x) upper' and 'g(x) lower'. Only one curve is on the board; there is no second curve, no strip and no shaded region, so the one thing the segment teaches is the one thing not drawn.

### idx 8 — area-between-two-intersecting-curves / seg 2 — Finding the Limits: Intersection Points

- **Objective:** "Determine the limits of integration by solving for the points where the two curves intersect."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `labeled_axes_plot` (svg template), params verbatim:

```json
{
  "x_label": "x",
  "y_label": "y",
  "title": "y = x and y = x^2 meet at x = 0 and x = 1",
  "curve_points": [
    [
      0,
      0
    ],
    [
      0.25,
      0.25
    ],
    [
      0.5,
      0.5
    ],
    [
      0.75,
      0.75
    ],
    [
      1,
      1
    ]
  ],
  "annotations": [
    [
      0,
      0,
      "a = 0"
    ],
    [
      1,
      1,
      "b = 1"
    ]
  ]
}
```

- **Caption:** "Intersection points give the limits a and b"
- **diag_hint was:** `labeled_axes_plot`

- **Proposed n, criterion (a)** — confidence high. Objective is finding the limits by intersecting the curves. The emitted **labeled_axes_plot** `curve_points` are [[0,0],[0.25,0.25],[0.5,0.5],[0.75,0.75],[1,1]] - a straight segment of y=x and nothing else - under the title 'y = x and y = x^2 meet at x = 0 and x = 1'. The parabola whose intersection is the entire point is absent. xy_plot area_between (line + parabola) draws both curves and both crossings and is the documented supported case.

### idx 9 — area-between-two-intersecting-curves / seg 3 — Which Curve is on Top? Sampling and Sketching

- **Objective:** "Identify the upper and lower curves on an interval by testing a sample point and sketching the region."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `conic_figure` (svg template), params verbatim:

```json
{
  "kind": "parabola",
  "a": 1,
  "b": 1
}
```

- **Caption:** "y = x^2 opens upward; the line y = x lies above it between x = 0 and x = 1."
- **diag_hint was:** `conic_figure`

- **Proposed n, criterion (a)** — confidence high. Objective: identify the upper and lower curve by testing a sample point. Emitted **conic_figure** `{kind: parabola, a: 1, b: 1}`, i.e. the parabola alone, captioned 'y = x^2 opens upward; the line y = x lies above it between x = 0 and x = 1'. The line the student is asked to compare against is not drawn, so nothing can be 'on top' of anything on this board.

### idx 10 — area-between-two-intersecting-curves / seg 4 — Worked Example: Line and Parabola

- **Objective:** "Compute the area between y=x and y=x^2 from x=0 to x=1 using the top-minus-bottom formula."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `conic_figure` (svg template), params verbatim:

```json
{
  "kind": "parabola",
  "a": 1,
  "b": 1
}
```

- **Caption:** "Parabola y = x^2 meeting the line y = x at x = 0 and x = 1"
- **diag_hint was:** `conic_figure`

- **Proposed n, criterion (a)** — confidence high. The worked example is the area between y=x and y=x^2 from 0 to 1 - the canonical `area_between` payload, fired correctly at segment 24/30 of the parabola-and-line subtopic. Here the board emitted **conic_figure** `{kind: parabola, a: 1, b: 1}`: a bare parabola, no line, no shaded region, no limits.

### idx 12 — area-between-two-intersecting-curves / seg 6 — Horizontal Strips: Integrating with Respect to y

- **Objective:** "Use horizontal strips (right minus left) when the region is more naturally described by functions of y."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `conic_figure` (svg template), params verbatim:

```json
{
  "kind": "parabola",
  "a": 1,
  "b": 1
}
```

- **Caption:** "Sideways parabola x = y^2/4 — horizontal strips fit naturally"
- **diag_hint was:** `conic_figure`

- **Proposed n, criterion (a)** — confidence high. Objective is horizontal strips / integrating with respect to y. `integrate_along: 'y'` is the v3 parameter built for exactly this (the widget header lists concept 10 as YES), and segments 27 and 64 use it. The board instead emitted **conic_figure** `{kind: parabola, a: 1, b: 1}` captioned 'Sideways parabola x = y^2/4 - horizontal strips fit naturally'. conic_figure draws an upright parabola and cannot draw a horizontal strip; the caption describes a figure that is not on the board.

### idx 16 — area-bounded-by-a-curve-and-its-tangent-or-normal / seg 1 — The Tangent/Normal Area Problem

- **Objective:** "Identify the region bounded by a curve and its tangent or normal and set up the area integral using top-minus-bottom."
- **board_slot:** `svg_live`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `conic_figure` (svg template), params verbatim:

```json
{
  "kind": "parabola",
  "a": 1,
  "b": 1
}
```

- **Caption:** "Parabola with its tangent line — the region between them"
- **diag_hint was:** `conic_figure`

- **Proposed n, criterion (a)** — confidence high. Opening segment of the tangent/normal subtopic. The widget header records concept 4 as YES at v3: 'the widget differentiates the curve itself, so the payload names the POINT and not the line' (`tangent_at`, `tangent_kind`). The board emitted **conic_figure** `{kind: parabola, a: 1, b: 1}` captioned 'Parabola with its tangent line - the region between them'. There is no tangent line and no region on the board. Across all eight segments of this subtopic `tangent_at`/`tangent_kind` is never used once.

### idx 17 — area-bounded-by-a-curve-and-its-tangent-or-normal / seg 2 — Finding the Tangent and Normal Equations

- **Objective:** "Compute the equation of the tangent or normal to a given curve at a specified point."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `labeled_axes_plot` (svg template), params verbatim:

```json
{
  "x_label": "x",
  "y_label": "y",
  "title": "y = x^2 with tangent and normal at (1,1)",
  "curve_points": [
    [
      -1.5,
      2.25
    ],
    [
      -1,
      1
    ],
    [
      -0.5,
      0.25
    ],
    [
      0,
      0
    ],
    [
      0.5,
      0.25
    ],
    [
      1,
      1
    ],
    [
      1.5,
      2.25
    ]
  ],
  "annotations": [
    [
      1,
      1,
      "(1,1)"
    ],
    [
      0,
      1.5,
      "normal"
    ],
    [
      1.5,
      2,
      "tangent"
    ]
  ]
}
```

- **Caption:** "Curve y = x^2 with its tangent and normal at (1,1)"
- **diag_hint was:** `labeled_axes_plot`

- **Proposed n, criterion (a)** — confidence high. Objective: compute the tangent and normal to y=x^2 at (1,1). Emitted **labeled_axes_plot** with `curve_points` for the parabola and annotations reading 'normal' at (0,1.5) and 'tangent' at (1.5,2) - floating text labels for two lines that are not drawn. `curve: parabola, a: 1, tangent_at: 1, tangent_kind: tangent|normal` draws both, with the slope computed rather than typed.

### idx 18 — area-bounded-by-a-curve-and-its-tangent-or-normal / seg 3 — Intersection Points: Where Curve Meets Line

- **Objective:** "Find the points of intersection between a curve and its tangent or normal by solving equations simultaneously."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `labeled_axes_plot` (svg template), params verbatim:

```json
{
  "x_label": "x",
  "y_label": "y",
  "title": "y = x^2 with tangent and normal at (1,1)",
  "curve_points": [
    [
      -1.5,
      2.25
    ],
    [
      -1,
      1
    ],
    [
      -0.5,
      0.25
    ],
    [
      0,
      0
    ],
    [
      0.5,
      0.25
    ],
    [
      1,
      1
    ],
    [
      1.5,
      2.25
    ]
  ],
  "annotations": [
    [
      1,
      1,
      "tangent point (1,1)"
    ],
    [
      -1.5,
      2.25,
      "normal meets curve"
    ]
  ]
}
```

- **Caption:** "Curve y = x^2, its tangent and normal at (1,1)"
- **diag_hint was:** `labeled_axes_plot`

- **Proposed n, criterion (a)** — confidence medium. Objective: find where the curve meets its tangent/normal. The same tangent-less parabola figure is reused, annotated 'tangent point (1,1)' and 'normal meets curve'. Both named intersections are with lines that are absent from the picture.

### idx 19 — area-bounded-by-a-curve-and-its-tangent-or-normal / seg 4 — Setting Up the Area Integral

- **Objective:** "Set up the definite integral for the area between a curve and its tangent or normal using top-minus-bottom."
- **board_slot:** `svg_live`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `conic_figure` (svg template), params verbatim:

```json
{
  "kind": "parabola",
  "a": 1,
  "b": 1
}
```

- **Caption:** "Parabola y = x^2 — the curve whose area with a line we compute"
- **diag_hint was:** `conic_figure`

- **Proposed n, criterion (a)** — confidence medium. Objective: set up the top-minus-bottom integral for the region between a curve and its tangent/normal. Emitted **conic_figure** `{kind: parabola, a: 1, b: 1}`, caption 'Parabola y = x^2 - the curve whose area with a line we compute'. The caption concedes the line is missing. A set-up segment whose figure omits the second boundary and the region cannot show the set-up.

### idx 20 — area-bounded-by-a-curve-and-its-tangent-or-normal / seg 5 — Evaluating the Integral

- **Objective:** "Evaluate the definite integral to find the area between a curve and its tangent or normal."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `labeled_axes_plot` (svg template), params verbatim:

```json
{
  "x_label": "x",
  "y_label": "y",
  "curve_points": [
    [
      -1.5,
      2.25
    ],
    [
      -1,
      1
    ],
    [
      -0.5,
      0.25
    ],
    [
      0,
      0
    ],
    [
      0.5,
      0.25
    ],
    [
      1,
      1
    ]
  ],
  "annotations": [
    [
      -1.5,
      2.25,
      "(-3/2, 9/4)"
    ],
    [
      1,
      1,
      "(1,1)"
    ]
  ],
  "title": "Area between y = x^2 and its normal"
}
```

- **Caption:** "Region between parabola and normal, x = -3/2 to x = 1"
- **diag_hint was:** `labeled_axes_plot`

- **Proposed n, criterion (a)** — confidence high. Objective: evaluate the integral for the area between y=x^2 and its normal from x=-3/2 to x=1; the board even prints the integrand -x/2 + 3/2 - x^2. Emitted **labeled_axes_plot** with parabola points and two endpoint annotations, titled 'Area between y = x^2 and its normal'. The normal is not drawn and the area is not shaded. Fully expressible: curve parabola a=1, curve2 line a2=-0.5 c2=1.5, shade_from -1.5, shade_to 1 - or `tangent_at: 1, tangent_kind: normal`.

### idx 21 — area-bounded-by-a-curve-and-its-tangent-or-normal / seg 6 — Tangent with an Additional Boundary

- **Objective:** "Find the area bounded by a curve, its tangent, and another line (like an axis or a vertical line)."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `conic_figure` (svg template), params verbatim:

```json
{
  "kind": "parabola",
  "a": 1,
  "b": 1
}
```

- **Caption:** "Parabola y = x^2 with its tangent and the x-axis bounding the region"
- **diag_hint was:** `conic_figure`

- **Proposed n, criterion (a)** — confidence high. Region bounded by y=x^2, its tangent y=2x-1, and the x-axis; the board gives the tangent's equation and both x-intercepts. Emitted **conic_figure** `{kind: parabola, a: 1, b: 1}` - parabola only, no tangent, no axis cut, no shading.

### idx 22 — area-bounded-by-a-curve-and-its-tangent-or-normal / seg 7 — Normal with an Additional Boundary

- **Objective:** "Find the area bounded by a curve, its normal, and an axis or another line."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `conic_figure` (svg template), params verbatim:

```json
{
  "kind": "parabola",
  "a": 1,
  "b": 1
}
```

- **Caption:** "Parabola y = x^2 with its normal at (1,1) and the y-axis bounding the region"
- **diag_hint was:** `conic_figure`

- **Proposed n, criterion (a)** — confidence high. Region bounded by y=x^2, its normal y=-x/2+3/2, and the y-axis; the board prints the normal's equation. Emitted **conic_figure** `{kind: parabola, a: 1, b: 1}` - parabola only. Two of the three boundaries of the region are missing from the picture.

### idx 24 — area-bounded-by-a-parabola-and-a-line / seg 1 — The Area Between Two Curves: The Core Formula

- **Objective:** "State and apply the formula for the area between two curves using vertical strips."
- **board_slot:** `widget_archetype`
- **Fired:** `xy_plot` v4, params verbatim:

```json
{
  "mode": "area_between",
  "curve": "line",
  "curve2": "parabola",
  "a": 1,
  "b": 0,
  "c": 0,
  "a2": -1,
  "b2": 0,
  "c2": 0,
  "x_min": 0,
  "x_max": 1,
  "shade_from": 0,
  "shade_to": 1,
  "x_label": "x",
  "y_label": "y"
}
```

- **Caption on the board:** "Area between y = x (top) and y = x^2 (bottom) from x = 0 to x = 1"

- **Proposed n, criterion (b)** — confidence high. `curve2: parabola` with `a2: -1` is y = -x^2, an INVERTED parabola, while the caption and the whole segment say the lower curve is y = x^2. The board therefore shades between y=x and y=-x^2 on [0,1]; the widget's derived area readout comes out 5/6 instead of the 1/6 this example is famous for.

### idx 25 — area-bounded-by-a-parabola-and-a-line / seg 2 — Finding Intersections: The Limits of Integration

- **Objective:** "Find the points of intersection of a parabola and a line by solving their equations simultaneously."
- **board_slot:** `widget_archetype`
- **Fired:** `xy_plot` v4, params verbatim:

```json
{
  "mode": "area_between",
  "curve": "line",
  "curve2": "parabola",
  "a": 1,
  "a2": 1,
  "b": 0,
  "b2": 0,
  "c": 0,
  "c2": 0,
  "x_min": -0.5,
  "x_max": 4.5,
  "shade_from": 0,
  "shade_to": 4,
  "x_label": "x",
  "y_label": "y"
}
```

- **Caption on the board:** "Intersection points (0,0) and (4,4) give the limits of integration."

- **Proposed n, criterion (b)** — confidence high. The drawn pair is y = x (line a=1,c=0) and y = x^2 (parabola a2=1), which intersect at x=0 and x=1 - but the caption asserts 'Intersection points (0,0) and (4,4)' and `shade_from/shade_to` run 0 to 4. The figure's own crossings contradict the limits it is being used to justify, in the one segment whose objective is finding those crossings. The board's worked pair is y^2=4x against y=x; y^2=4x is not expressible as `curve: parabola`.

### idx 26 — area-bounded-by-a-parabola-and-a-line / seg 3 — Vertical Strips: Parabola on Top

- **Objective:** "Compute the area between a parabola and a line when the parabola is the upper curve using vertical strips."
- **board_slot:** `widget_archetype`
- **Fired:** `xy_plot` v4, params verbatim:

```json
{
  "mode": "area_between",
  "curve": "parabola",
  "curve2": "line",
  "a": 1,
  "a2": 1,
  "b": 0,
  "b2": 0,
  "c": 0,
  "c2": 0,
  "x_min": 0,
  "x_max": 4.5,
  "shade_from": 0,
  "shade_to": 4,
  "x_label": "x",
  "y_label": "y"
}
```

- **Caption on the board:** "Region between y = 2√x and y = x, from x = 0 to x = 4"

- **Proposed n, criterion (b)** — confidence high. Caption: 'Region between y = 2sqrt(x) and y = x, from x = 0 to x = 4', and the board text establishes the parabola branch y = 2sqrt(x) is on top. The params draw `curve: parabola, a: 1, b: 0, c: 0` = y = x^2, which is BELOW y=x on (0,1) and above it after. The picture contradicts the 'parabola on top' claim the segment title makes, and the shaded 0-to-4 interval is not a region these two curves bound.

### idx 27 — area-bounded-by-a-parabola-and-a-line / seg 4 — Horizontal Strips: When the Parabola is Sideways

- **Objective:** "Decide when to integrate with respect to y and compute the area using horizontal strips."
- **board_slot:** `widget_archetype`
- **Fired:** `xy_plot` v4, params verbatim:

```json
{
  "mode": "area_between",
  "curve": "parabola",
  "curve2": "line",
  "a": 1,
  "a2": 1,
  "b": 0,
  "b2": 0,
  "c": 0,
  "c2": 0,
  "x_min": -0.5,
  "x_max": 4.5,
  "shade_from": 0,
  "shade_to": 4,
  "x_label": "x",
  "y_label": "y",
  "integrate_along": "y"
}
```

- **Caption on the board:** "Region between y^2 = 4x and y = 2x - 4, sliced horizontally"

- **Proposed n, criterion (b)** — confidence high. `integrate_along: 'y'` is right for the objective - that part is correct. The curves are not: the board works y^2 = 4x against y = 2x - 4, i.e. x = y^2/4 and x = (y+4)/2, while the params give `a: 1` (x = y^2) and `curve2: line, a2: 1, b2: 0, c2: 0`. Note `b2` is not an intercept - for `line` the widget evaluates a*x + c - so the second curve is the diagonal through the origin, not y = 2x - 4. The transposed limits y = -2 and y = 4 are nowhere in the payload (shade 0 to 4).

### idx 28 — area-bounded-by-a-parabola-and-a-line / seg 5 — The Latus Rectum: A Special Chord

- **Objective:** "Compute the area bounded by a parabola and its latus rectum using symmetry."
- **board_slot:** `widget_archetype`
- **Fired:** `xy_plot` v4, params verbatim:

```json
{
  "mode": "area_between",
  "curve": "parabola",
  "curve2": "line",
  "a": 1,
  "a2": 1,
  "b": 0,
  "b2": 0,
  "c": 0,
  "c2": 0,
  "integrate_along": "x",
  "shade_from": 0,
  "shade_to": 1,
  "x_min": -0.5,
  "x_max": 1.5,
  "x_label": "x",
  "y_label": "y"
}
```

- **Caption on the board:** "Region between y^2 = 4x and its latus rectum x = 1"

- **Proposed n, criterion (b)** — confidence high. The latus rectum of y^2 = 4x is the VERTICAL line x = 1. `curve2: line` is y = a2*x + c2 and cannot be vertical, so the board draws y = x^2 against y = x on [0,1] and labels it 'Region between y^2 = 4x and its latus rectum x = 1'. Neither boundary in the caption is on the board, and the derived area readout belongs to a different region entirely. (Transposing with `integrate_along: 'y'` would have given the real picture - parabola x = y^2/4 against the constant x = 1.)

### idx 31 — area-by-integration-along-the-y-axis / seg 1 — Why Integrate Along the y-axis?

- **Objective:** "Recognize when a region is more naturally described by horizontal strips and explain why integrating with respect to y is advantageous."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = widget_cannot_express_concept`
- **Emitted instead:** `conic_figure` (svg template), params verbatim:

```json
{
  "kind": "parabola",
  "a": 1,
  "b": 1
}
```

- **Caption:** "Parabola y^2 = 4x opening to the right"
- **diag_hint was:** `conic_figure`

- **Proposed n, criterion (c)** — confidence high. Structured decline `widget_cannot_express_concept` on the opening segment of the y-axis subtopic. The widget header lists concept 10, 'Area by integration along the y-axis', as YES at v3 via `integrate_along`, 'with the axis labels telling the truth', and segment 64 of this same chapter fires it. The substitute, **conic_figure** `{kind: parabola, a: 1, b: 1}`, shows no horizontal strip, which is the whole concept.

### idx 32 — area-by-integration-along-the-y-axis / seg 2 — The Horizontal Strip Formula

- **Objective:** "State and apply the formula A = ∫ x dy for a region bounded by a curve, the y-axis, and horizontal lines."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = widget_cannot_express_concept`
- **Emitted instead:** `number_line` (svg template), params verbatim:

```json
{
  "title": "Limits along the y-axis: y = c to y = d",
  "intervals": [
    {
      "lo": 0,
      "hi": 2,
      "lo_closed": true,
      "hi_closed": true,
      "label": "y from c to d"
    }
  ]
}
```

- **Caption:** "Horizontal strips sweep from y = c to y = d"
- **diag_hint was:** `number_line`

- **Proposed n, criterion (c)** — confidence high. Objective is literally A = int x dy. Declined as `widget_cannot_express_concept`, and the board emitted a **number_line** `{intervals: [{lo: 0, hi: 2, label: 'y from c to d'}]}` - a 1-D segment standing in for a 2-D region sliced horizontally. Segment 64 fires xy_plot with `integrate_along: 'y'` for an objective phrased almost identically. The decline is not honest: the feature exists and is used elsewhere in the same run.

### idx 34 — area-by-integration-along-the-y-axis / seg 4 — Worked Example: Parabola and y-axis

- **Objective:** "Compute the area of a region bounded by a parabola, the y-axis, and horizontal lines using integration with respect to y."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = widget_cannot_express_concept`
- **Emitted instead:** `conic_figure` (svg template), params verbatim:

```json
{
  "kind": "parabola",
  "a": 1,
  "b": 1
}
```

- **Caption:** "Parabola x = y^2 opening to the right"
- **diag_hint was:** `conic_figure`

- **Proposed n, criterion (c)** — confidence high. Worked example: area bounded by x=y^2, the y-axis, y=0 and y=2. Declined as `widget_cannot_express_concept`; emitted **conic_figure** `{kind: parabola, a: 1, b: 1}` with no strip, no shading and no limits. Segment 64's payload - `mode: area, curve: parabola, a: 1, b: 0, c: 0, integrate_along: 'y', shade_from: 0, shade_to: 2` - IS this region, so the decline is contradicted by a payload the same run produced.

### idx 36 — area-by-integration-along-the-y-axis / seg 6 — Area Between Two Curves Using dy

- **Objective:** "Compute the area between two curves by integrating with respect to y, using right minus left."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = widget_cannot_express_concept`
- **Emitted instead:** `conic_figure` (svg template), params verbatim:

```json
{
  "kind": "parabola",
  "a": 1,
  "b": 1
}
```

- **Caption:** "Parabola y^2 = 4x opening to the right"
- **diag_hint was:** `conic_figure`

- **Proposed n, criterion (c)** — confidence medium. Objective: area between two curves by dy, right minus left, worked on y^2=4x against y=2x-4. Declined as `widget_cannot_express_concept`; emitted a bare **conic_figure** parabola. Along y those boundaries are x = y^2/4 (a parabola) and x = (y+4)/2 (a line) - the documented transposition case, and exactly what segment 27 attempts. The decline is not honest.

### idx 37 — area-by-integration-along-the-y-axis / seg 7 — Symmetry and Efficiency

- **Objective:** "Use symmetry about the x-axis to simplify area calculations when integrating with respect to y."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = widget_cannot_express_concept`
- **Emitted instead:** `conic_figure` (svg template), params verbatim:

```json
{
  "kind": "parabola",
  "a": 1,
  "b": 1
}
```

- **Caption:** "y^2 = 4x — right-opening parabola, symmetric about the x-axis"
- **diag_hint was:** `conic_figure`

- **Proposed n, criterion (c)** — confidence medium. Objective: use symmetry about the x-axis when integrating with respect to y, on y^2=4x and x=4. Declined as `widget_cannot_express_concept`; emitted a bare **conic_figure** parabola. Along y this is parabola a=0.25 against the vertical boundary x=4, with `shade_from: 0, shade_to: 4` giving precisely the 'upper half then double' the board describes.

### idx 47 — area-of-regions-described-by-inequalities / seg 1 — Decoding Inequalities: The Region Game

- **Objective:** "Translate a single inequality into a shaded region and verify the correct side using a test point."
- **board_slot:** `svg_live`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `number_line` (svg template), params verbatim:

```json
{
  "intervals": [
    {
      "lo": -3,
      "hi": 0,
      "lo_closed": false,
      "hi_closed": true,
      "label": "y \u2264 f(x): below"
    },
    {
      "lo": 0,
      "hi": 3,
      "lo_closed": true,
      "hi_closed": false,
      "label": "y \u2265 f(x): above"
    }
  ],
  "title": "Which side of the curve?"
}
```

- **Caption:** "Inequality decides the side of the boundary curve."
- **diag_hint was:** `number_line`

- **Proposed n, criterion (a)** — confidence high. Objective: translate an inequality into a SHADED REGION and test which side of the curve. Emitted **number_line** with intervals labelled 'y <= f(x): below' and 'y >= f(x): above'. A number line has one dimension and cannot express 'which side of a curve' in the plane; the labels assert a 2-D fact the figure cannot show. Segment 57, the same objective in the modulus subtopic, fires xy_plot for it. (The widget header lists concept 5 as PART - two bounds only - and this is one bound.)

### idx 49 — area-of-regions-described-by-inequalities / seg 3 — The Diamond Region: |x| + |y| ≤ a

- **Objective:** "Compute the area of the diamond region using symmetry and the formula 2a²."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `boxed_derivation` (svg template), params verbatim:

```json
{
  "title": "Area of the diamond |x| + |y| \u2264 a",
  "steps": [
    "First quadrant: |x| = x, |y| = y",
    "Condition becomes x + y \u2264 a, x \u2265 0, y \u2265 0",
    "This is a right triangle with legs of length a",
    "Area of one triangle = (1/2) a \u00b7 a = a\u00b2/2",
    "Total area = 4 \u00d7 (a\u00b2/2) = 2a\u00b2",
    "For a = 2: A = 2(2)\u00b2 = 8 square units"
  ]
}
```

- **Caption:** "Symmetry gives the diamond area in four easy steps."
- **diag_hint was:** `boxed_derivation`

- **Proposed n, criterion (c)** — confidence medium. Objective: compute the area of the diamond |x| + |y| <= a. Emitted **boxed_derivation** - five lines of algebra, no picture of the diamond. The region is the entire content of the segment ('vertices at (a,0), (0,a), (-a,0), (0,-a)'), and segment 56 fires xy_plot for the same objective to draw the first-quadrant triangle.

### idx 50 — area-of-regions-described-by-inequalities / seg 4 — Systems of Inequalities: Finding the Overlap

- **Objective:** "Sketch the intersection of two inequality regions and identify the boundaries for integration."
- **board_slot:** `svg_live`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `text_only` — no diagram node on the board at all.
- **diag_hint was:** `ray_diagram`

- **Proposed n, criterion (c)** — confidence high. Objective quoted below is 'Sketch the intersection of two inequality regions'. The board emitted **text_only** - no figure whatsoever - for a segment whose verb is 'sketch'. The example is {y >= x^2, y <= x+2}: exactly two bounds, which the widget header records as the supported half of concept 5, and which segment 57 fires as a single `area_between` payload.

### idx 52 — area-of-regions-described-by-inequalities / seg 6 — Putting It All Together: A JEE-Style Problem

- **Objective:** "Solve a multi-condition region problem involving modulus and circle, using symmetry and geometry check."
- **board_slot:** `svg_precomputed`
- **Decline:** `non_fire_reason = model_chose_no_widget`
- **Emitted instead:** `svg` — no diagram node on the board at all.
- **diag_hint was:** `None`

- **Proposed n, criterion (c)** — confidence medium. Capstone problem {y >= |x|, x^2 + y^2 <= 2} with an intersection, a symmetry argument and a wedge-shaped region - and no diagram node on the board at all. The xy_plot decline is honest (circles are a documented NO), but `has_example_diagram_svg` is true for this segment, so an authored SVG existed and still nothing reached the board.

### idx 54 — area-of-regions-involving-modulus-and-piecewise-defined-functions / seg 1 — Decoding the Disguises: Modulus, Inequalities, and Composite Regions

- **Objective:** "Recognize that advanced area problems are just basic area problems with a modulus, inequality, or switching boundary, and identify which disguise is present."
- **board_slot:** `widget_archetype`
- **Fired:** `xy_plot` v4, params verbatim:

```json
{
  "mode": "curve",
  "curve": "line",
  "a": 1,
  "b": 0,
  "c": 0,
  "x_min": -3,
  "x_max": 3,
  "x_label": "x",
  "y_label": "y"
}
```

- **Caption on the board:** "y = |x| — V-shape with a corner at the origin"

- **Proposed n, criterion (b)** — confidence high. Caption: 'y = |x| - V-shape with a corner at the origin'. The params draw `mode: curve, curve: line, a: 1, b: 0, c: 0` = the straight line y = x. There is no corner and no V; the segment's entire point ('a modulus curve like y = |x| has a V-shape with a corner') is contradicted by the figure. `pieces` exists for exactly this - the widget header calls out concept 8 as YES at v3 and names y = x^2 against y = |x| as one payload.

### idx 55 — area-of-regions-involving-modulus-and-piecewise-defined-functions / seg 2 — Splitting Modulus Curves at Their Corners

- **Objective:** "Find the area under a modulus curve by locating its corners and integrating piecewise."
- **board_slot:** `widget_archetype`
- **Fired:** `xy_plot` v4, params verbatim:

```json
{
  "mode": "curve",
  "curve": "line",
  "a": 1,
  "b": 0,
  "c": 0,
  "x_min": -3,
  "x_max": 3,
  "x_label": "x",
  "y_label": "y"
}
```

- **Caption on the board:** "y = |x| — V-shape with a corner at the origin"

- **Proposed n, criterion (b)** — confidence high. Byte-identical straight-line payload to segment 1, same 'y = |x| - V-shape with a corner at the origin' caption, on a segment whose objective is locating the corners. Same defect, and the repeat means the student sees the same wrong picture twice in a row.

### idx 56 — area-of-regions-involving-modulus-and-piecewise-defined-functions / seg 3 — The Diamond Theorem: Area of |x| + |y| ≤ a

- **Objective:** "Compute the area of the diamond region |x| + |y| ≤ a using symmetry and the formula 2a²."
- **board_slot:** `widget_archetype`
- **Fired:** `xy_plot` v4, params verbatim:

```json
{
  "mode": "area",
  "curve": "line",
  "a": -1,
  "b": 2,
  "c": 0,
  "x_min": 0,
  "x_max": 2,
  "shade_from": 0,
  "shade_to": 2,
  "x_label": "x",
  "y_label": "y"
}
```

- **Caption on the board:** "First-quadrant triangle: x + y ≤ 2, legs of length 2"

- **Proposed n, criterion (b)** — confidence high. `curve: line, a: -1, b: 2, c: 0`. For `line` the widget evaluates a*x + c and IGNORES b (lib/widgets/xy-plot/plot-math.ts, evalCurve: `case 'line': return a * x + c`). The intercept 2 was put in `b`, so the drawn line is y = -x, not y = 2 - x. Shading 0 to 2 under y = -x is a triangle BELOW the x-axis with derived area -2, where the caption promises 'First-quadrant triangle: x + y <= 2, legs of length 2'.

### idx 57 — area-of-regions-involving-modulus-and-piecewise-defined-functions / seg 4 — Decoding Inequalities: Which Side of the Curve?

- **Objective:** "Translate inequalities like y ≤ f(x) or y ≥ f(x) into shaded regions and identify the overlap for a system."
- **board_slot:** `widget_archetype`
- **Fired:** `xy_plot` v4, params verbatim:

```json
{
  "mode": "area_between",
  "curve": "parabola",
  "a": 1,
  "b": 0,
  "c": 0,
  "curve2": "line",
  "a2": 1,
  "b2": 2,
  "c2": 0,
  "x_min": -1.5,
  "x_max": 2.5,
  "shade_from": -1,
  "shade_to": 2,
  "x_label": "x",
  "y_label": "y"
}
```

- **Caption on the board:** "Region between y = x² and y = x + 2"

- **Proposed n, criterion (b)** — confidence high. Same `b`-is-not-the-intercept error on curve2: `curve2: line, a2: 1, b2: 2, c2: 0` evaluates to y = x, not y = x + 2. The region is therefore drawn between y = x^2 and y = x, which meet at 0 and 1, while `shade_from: -1, shade_to: 2` are the limits for the intended y = x + 2. The student sees shading that runs past the crossings of the curves actually on the board.

### idx 58 — area-of-regions-involving-modulus-and-piecewise-defined-functions / seg 5 — Composite Regions: When the Ceiling Switches

- **Objective:** "Find the area of a region whose upper boundary changes from one curve to another by splitting at the switch point."
- **board_slot:** `widget_archetype`
- **Fired:** `xy_plot` v4, params verbatim:

```json
{
  "mode": "area_between",
  "curve": "parabola",
  "a": -1,
  "b": 0,
  "c": 2,
  "curve2": "line",
  "a2": 1,
  "b2": 0,
  "c2": 0,
  "x_min": -1.5,
  "x_max": 1.5,
  "shade_from": -1,
  "shade_to": 1,
  "x_label": "x",
  "y_label": "y"
}
```

- **Caption on the board:** "Region between y = 2 - x^2 and y = |x|, split at x = 0"

- **Proposed n, criterion (b)** — confidence high. Caption: 'Region between y = 2 - x^2 and y = |x|, split at x = 0'. `curve2` is `line, a2: 1, b2: 0, c2: 0` = y = x, so the V is drawn as a single straight line: on [-1,0] the lower boundary is drawn as y = x (negative) instead of y = -x, and the 'split at x = 0' the segment teaches has nothing to split. `pieces` covers modulus and is unused.

### idx 59 — area-of-regions-involving-modulus-and-piecewise-defined-functions / seg 6 — Symmetry as a Shortcut: Halving and Doubling

- **Objective:** "Use symmetry about axes or origin to reduce the integration work by integrating over a smaller region and multiplying."
- **board_slot:** `widget_archetype`
- **Fired:** `xy_plot` v4, params verbatim:

```json
{
  "mode": "area_between",
  "curve": "parabola",
  "curve2": "line",
  "a": -1,
  "a2": 1,
  "b": 0,
  "b2": 0,
  "c": 2,
  "c2": 0,
  "x_min": -1.5,
  "x_max": 1.5,
  "shade_from": 0,
  "shade_to": 1,
  "x_label": "x",
  "y_label": "y"
}
```

- **Caption on the board:** "Right half of the region: bottom y = x, top y = sqrt(2 - x^2)"

- **Proposed n, criterion (b)** — confidence medium. Caption: 'Right half of the region: bottom y = x, top y = sqrt(2 - x^2)' - a circular arc. `curve: parabola, a: -1, b: 0, c: 2` draws y = 2 - x^2. The widget cannot draw circles at all (registry: 'No circles/regions/panels'; the index.tsx header lists concept 7 as NO), so this is a circle faked with a parabola. The crossing with y=x happens to land at x=1 for both, which hides the substitution, but the top boundary is 2 at x=0 where the true arc is 1.414, and the derived area readout is wrong for the region named.

### idx 60 — area-of-regions-involving-modulus-and-piecewise-defined-functions / seg 7 — Putting It All Together: A Multi-Concept JEE Problem

- **Objective:** "Solve a complex area problem involving modulus, inequalities, and composite boundaries by decoding, sketching, splitting, and integrating."
- **board_slot:** `widget_archetype`
- **Fired:** `xy_plot` v4, params verbatim:

```json
{
  "mode": "area_between",
  "curve": "parabola",
  "a": -1,
  "b": 0,
  "c": 8,
  "curve2": "line",
  "a2": 1,
  "b2": 0,
  "c2": 0,
  "x_min": -2.5,
  "x_max": 2.5,
  "shade_from": 0,
  "shade_to": 2,
  "x_label": "x",
  "y_label": "y"
}
```

- **Caption on the board:** "Right half of the wedge: between y = x and y = √(8 − x²), x from 0 to 2"

- **Proposed n, criterion (b)** — confidence high. Same circle-faked-as-parabola substitution, and here it does not even hide: caption 'between y = x and y = sqrt(8 - x^2), x from 0 to 2', params `parabola, a: -1, c: 8` = y = 8 - x^2. That parabola meets y = x at x = 2.37, not at the x = 2 the board derives and `shade_to` uses, and it sits at 8 above the origin where the circle sits at 2.83. The intersection the segment computes is not the intersection the picture shows.

### idx 66 — area-under-a-simple-curve-bounded-by-the-axes / seg 5 — Splitting at Roots: When the Curve Crosses the Axis

- **Objective:** "Compute the area when the curve crosses the x-axis within the interval by splitting the integral at the roots."
- **board_slot:** `widget_archetype`
- **Fired:** `xy_plot` v4, params verbatim:

```json
{
  "mode": "area",
  "curve": "parabola",
  "a": 1,
  "b": 0,
  "c": 0,
  "x_min": -2,
  "x_max": 2,
  "shade_from": -2,
  "shade_to": 2,
  "x_label": "x",
  "y_label": "y = f(x)"
}
```

- **Caption on the board:** "Curve crossing the x-axis: the two shaded pieces have opposite signs and cancel in the signed integral."

- **Proposed n, criterion (b)** — confidence high. Objective and caption are about a curve CROSSING the x-axis so the signed pieces cancel ('the two shaded pieces have opposite signs and cancel in the signed integral'). The params draw `curve: parabola, a: 1, b: 0, c: 0` = y = x^2, which is non-negative everywhere and only touches the axis at the origin. Shading -2 to 2 gives two pieces that are both positive and sum to 16/3 - the exact opposite of the cancellation being taught. `c: -1` (y = x^2 - 1), or a cubic via pieces, would have shown it.

### idx 67 — area-under-a-simple-curve-bounded-by-the-axes / seg 6 — Symmetry: A Time-Saving Shortcut

- **Objective:** "Use symmetry to compute areas of symmetric regions by integrating over a smaller part and multiplying."
- **board_slot:** `widget_precomputed`
- **Fired:** `xy_plot` v4, params verbatim:

```json
{
  "a": 1,
  "b": 1,
  "c": 0,
  "mode": "area",
  "curve": "reciprocal",
  "x_max": 1.2,
  "x_min": -1.2,
  "x_label": "x",
  "y_label": "y",
  "shade_to": 1,
  "shade_from": 0
}
```

- **Proposed n, criterion (b)** — confidence high. Two separate problems. (i) The objective is symmetry about an axis; `curve: reciprocal` is y = a/x + c, which has point symmetry about the origin and no axis symmetry, so it cannot demonstrate 'symmetry about the x-axis gives 2 equal halves'. (ii) `x_min: -1.2, x_max: 1.2` spans x = 0, and the renderer explicitly refuses that: 'is a reciprocal and cannot span x = 0; keep the domain on one side of it' (index.tsx validate). `client_validate` was not run in this harness, so the failure is unrecorded - on a real board this slot is likely to render nothing at all.

### idx 68 — area-under-a-simple-curve-bounded-by-the-axes / seg 7 — Standard Results: Circle and Ellipse

- **Objective:** "Apply the standard area formulas for a circle and an ellipse, and understand their derivation via integration."
- **board_slot:** `widget_archetype`
- **Fired:** `xy_plot` v4, params verbatim:

```json
{
  "mode": "area",
  "curve": "parabola",
  "a": -1,
  "b": 0,
  "c": 1,
  "x_min": 0,
  "x_max": 1,
  "shade_from": 0,
  "shade_to": 1,
  "x_label": "x",
  "y_label": "y = sqrt(a^2 - x^2)"
}
```

- **Caption on the board:** "First-quadrant piece of the circle: integrate y = sqrt(a^2 - x^2) from x = 0 to x = a."

- **Proposed n, criterion (b)** — confidence high. `y_label` is 'y = sqrt(a^2 - x^2)' and the board derives the quarter-circle area pi*a^2/4, but the params draw `curve: parabola, a: -1, b: 0, c: 1` = y = 1 - x^2. The widget cannot draw circles by design, so labelling a parabola as a circular arc puts a false claim on the board; the derived area readout for the shaded 0-to-1 strip is 2/3 against the pi/4 = 0.785 printed beside it.

### idx 70 — area-under-a-simple-curve-bounded-by-the-axes / seg 9 — Putting It All Together: A Multi-Concept Problem

- **Objective:** "Solve a problem that combines sign handling, splitting, symmetry, and variable choice."
- **board_slot:** `widget_precomputed`
- **Fired:** `xy_plot` v4, params verbatim:

```json
{
  "a": 4,
  "b": 0,
  "c": 0,
  "mode": "area",
  "curve": "reciprocal",
  "x_max": 4.5,
  "x_min": -4.5,
  "x_label": "x",
  "y_label": "y",
  "shade_to": 4,
  "shade_from": 2
}
```

- **Proposed n, criterion (b)** — confidence high. Capstone on the cap of x^2 + y^2 = 16 to the right of x = 2. The params draw `curve: reciprocal, a: 4, c: 0` = y = 4/x, a hyperbola branch, for a circle - again a shape the widget documents as out of scope. And `x_min: -4.5, x_max: 4.5` spans x = 0, which the renderer's validate() rejects for a reciprocal, so the final segment of the subtopic most likely shows an empty slot.

## Notes and uncertainties

- **idx 2 (area-between-a-function-and-its-inverse seg 3, verdict y):** comparison_table is right - xy_plot has no table mode, and the content is a sign-trap comparison.
- **idx 3 (area-between-a-function-and-its-inverse seg 4, verdict y):** Only one curve is actually plotted (the `curve_points` are arcsin values); both curves are named in annotations and the region is not shown. Weak, but arcsin/arccos are not xy_plot curve kinds, so the decline is honest.
- **idx 5 (area-between-a-function-and-its-inverse seg 6, verdict y):** comparison_table of tan^-1 vs cot^-1 at x = 0 and x = 1 is the honest picture for 'which curve is on top'.
- **idx 6 (area-between-a-function-and-its-inverse seg 7, verdict y):** Practice/pitfalls recap, text only. Acceptable.
- **idx 11 (area-between-two-intersecting-curves seg 5, verdict y):** x against x^3 is a cubic - not an xy_plot curve kind - so the decline is honest, and the number_line honestly encodes 'x^3 on top' / 'x on top' either side of the crossing.
- **idx 13 (area-between-two-intersecting-curves seg 7, verdict y):** y^2 = 4ax is not a function of x; conic_figure is the right fallback. Noted only because the caption claims two parabolas meeting at (0,0) and (4a,4a) while one parabola is drawn.
- **idx 14 (area-between-two-intersecting-curves seg 8, verdict y):** labeled_axes_plot with real points for y^2 = 4x and symmetry annotations - a reasonable substitute for a case xy_plot refuses (circle).
- **idx 15 (area-between-two-intersecting-curves seg 9, verdict y):** Pitfalls recap, text only. Acceptable.
- **idx 23 (area-bounded-by-a-curve-and-its-tangent-or-normal seg 8, verdict y):** y^2 = 4ax with a tangent - sideways, so the straightforward payload is refused. Arguably reachable by transposing with integrate_along, but not obviously, so I am not calling this insane.
- **idx 29 (area-bounded-by-a-parabola-and-a-line seg 6, verdict y):** Correct: y = 4 - x^2 shaded -2 to 2 is the region the board computes. The dividing line y = k is not drawn (curve2 line a2=0, c2=k would have added it), which would have made the segment's actual question visible.
- **idx 30 (area-bounded-by-a-parabola-and-a-line seg 7, verdict y):** Correct: parabola y = x^2 against line y = x, shaded 0 to 1, matching the caption. Contrast with segment 24 in the same subtopic, which inverted the parabola.
- **idx 33 (area-by-integration-along-the-y-axis seg 3, verdict y):** x = y^3 is a cubic, outside the curve kinds, so this decline is honest even though the rest of this subtopic's declines are not.
- **idx 35 (area-by-integration-along-the-y-axis seg 5, verdict y):** A dx-vs-dy DECISION is a two-panel comparison, which xy_plot cannot do, so declining is defensible. Flagged only for inconsistency: segment 69 in another subtopic fired xy_plot for the same objective.
- **idx 38 (area-by-integration-along-the-y-axis seg 8, verdict y):** Good instinct: labeled_axes_plot with x_label 'y' and y_label 'x' to show x = y^3 crossing. Honest for a cubic.
- **idx 39 (area-of-regions-bounded-by-circles-and-ellipses seg 1, verdict y):** Honest decline: xy_plot documents 'No circles/regions/panels' and index.tsx lists concept 7 as NO. conic_figure kind:circle is the right substitute and it is parameterised correctly (a = 5 for x^2+y^2=25).
- **idx 40 (area-of-regions-bounded-by-circles-and-ellipses seg 2, verdict y):** Honest decline; conic_figure circle a = 4 with the first-quadrant quarter called out.
- **idx 41 (area-of-regions-bounded-by-circles-and-ellipses seg 3, verdict y):** Honest decline; boxed_derivation carries the five-step antiderivative evaluation, which no plot widget can do.
- **idx 42 (area-of-regions-bounded-by-circles-and-ellipses seg 4, verdict y):** Honest decline; conic_figure kind:ellipse a=5 b=3 is a real ellipse, correctly parameterised.
- **idx 43 (area-of-regions-bounded-by-circles-and-ellipses seg 5, verdict y):** Honest decline; boxed_derivation sets up the segment integral.
- **idx 44 (area-of-regions-bounded-by-circles-and-ellipses seg 6, verdict y):** Honest decline; conic_figure ellipse a=3 b=2 for the horizontal cut.
- **idx 45 (area-of-regions-bounded-by-circles-and-ellipses seg 7, verdict y):** Honest decline; a circle-and-parabola intersection is a quartic, explicitly out of scope for xy_plot.
- **idx 46 (area-of-regions-bounded-by-circles-and-ellipses seg 8, verdict y):** Honest decline; conic_figure ellipse matches the x^2/9 + y^2/4 = 1 on the board.
- **idx 48 (area-of-regions-described-by-inequalities seg 2, verdict y):** The number_line split at the kink is on-concept. Noted because `pieces` could have drawn the V, and because the two segments that DID fire xy_plot for a modulus (54, 55) drew a straight line instead - so declining here was arguably the safer call.
- **idx 51 (area-of-regions-described-by-inequalities seg 5, verdict y):** number_line of the switch point is a reasonable stand-in for 'split the interval'; the skyline itself is not drawn.
- **idx 53 (area-of-regions-described-by-inequalities seg 7, verdict y):** Pitfalls recap; the number_line of the four pieces of ||x|-1| is genuinely useful and on-concept.
- **idx 61 (area-of-regions-involving-modulus-and-piecewise-defined-functions seg 8, verdict y):** Pitfalls recap, implicit decline to text_only. Acceptable.
- **idx 62 (area-under-a-simple-curve-bounded-by-the-axes seg 1, verdict y):** Correct and specific: y = x^2 + 1 on [0,2] is the example the board names.
- **idx 63 (area-under-a-simple-curve-bounded-by-the-axes seg 2, verdict y):** Generic f(x) >= 0 example; y = x^2 + 2 on [0,2] is consistent with the board.
- **idx 64 (area-under-a-simple-curve-bounded-by-the-axes seg 3, verdict y):** `integrate_along: 'y'` is right for A = int x dy. Minor: x = y^2 reaches x = 4 at the shade_to = 2 limit while x_max is 2.5, so the curve will clip at the top of the strip range.
- **idx 65 (area-under-a-simple-curve-bounded-by-the-axes seg 4, verdict y):** Correct: y = -x^2 is genuinely below the axis, which is what the segment teaches.
- **idx 69 (area-under-a-simple-curve-bounded-by-the-axes seg 8, verdict y):** One dx panel for a dx-vs-dy decision segment - incomplete rather than wrong. diag_hint was comparison_table, which is probably the better call.

# chem 12 ch8 — SANE proposals

Chapter: Aldehydes, Ketones & Carboxylic Acids (class 12 chemistry), 15 concepts, 113 lesson segments.
Source: `/Users/raasikhnaveed/Desktop/monk-learning-api/scripts/routing_chem12_ch8.jsonl`.

**LIMITATION — read this before trusting any verdict below.** The harness did **not** capture spoken
narration. Every verdict here is inferred from `segment_title`, `segment_objective` and
`model_raw_board_events` (the text/formula/diagram events the student actually sees on the board),
plus the widget `params`. I have **not** read what the tutor said. So criterion (b) —
"parameters that contradict the narration" — is applied as *contradicts the objective or the
on-board text*, never as *contradicts the narration*, which I cannot see. A scheme that a spoken
aside would have rescued ("ignore the last arrow, that's just the catalyst") will read as a defect
here. Treat the (b) flags as "the picture does not stand on its own", not as "the tutor was wrong".

Two further scoping notes:

1. A `fired=False` row is **not** the same as "no picture". All 67 declines are
   `non_fire_reason = model_chose_no_widget`; 61 of them still drew a live/precomputed SVG from a
   named template (`comparison_table`, `process_flow`, `boxed_derivation`, `ray_diagram`,
   `free_body_diagram`, `labeled_axes_plot`) and only 6 emitted `text_only`. So criterion (c)
   ("a decline where a student needed a picture") really only bites on those 6, and I judge the
   other 61 on whether the template they fell back to was the right picture.
2. As briefed, a decline on a med/low concept or a `gap_*` archetype is normally SANE — the column
   deliberately does not route it — so I have not flagged declines merely for being declines.

## Counts

proposed y: 94 ; proposed n: 19 (of 113)

By criterion: (a) wrong widget — 6 ; (b) params contradict objective/board text — 10 ;
(c) decline where a picture was needed — 3.

Where the n's land:

| concept | archetype confidence | segments | proposed n |
|---|---|---|---|
| preparation-of-aldehydes-and-ketones | high (reaction_scheme) | 8 | 2 |
| reactions-of-carboxylic-acids | high (reaction_scheme) | 7 | 3 |
| oxidation-and-reduction-of-aldehydes-and-ketones | high (reaction_scheme) | 8 | 3 |
| nucleophilic-addition-reactions... | high (reaction_scheme) | 8 | 2 |
| aldol-condensation | high (reaction_scheme) | 9 | 1 |
| acidity-of-carboxylic-acids... | high (data_table_trend) | 6 | 0 |
| distinguishing-tests... | med (gap_test_matrix) | 8 | 2 |
| haloform-reaction | med | 9 | 2 |
| physical-properties... | med | 8 | 2 |
| nomenclature... | med | 8 | 1 |
| multi-step-conversions... | med | 9 | 1 |
| alpha-halogenation / cannizzaro / prep-of-acids / ammonia-derivatives | med/low | 25 | 0 |

**The six data_table_trend firings (Acidity) are the cleanest block in the chapter — all six
proposed y, with every pKa value spot-checked against NCERT and every trend direction matching the
objective.** Every one of the 19 n's sits on a reaction_scheme firing or on a declined row's SVG
fallback.

## Per-segment verdicts

| subtopic_key | seg | board | slot | verdict |
|---|---|---|---|---|
| acidity-of-carboxylic-acids-and-substituent-effects | 1 | data_table_trend | widget_precomputed | y |
| acidity-of-carboxylic-acids-and-substituent-effects | 2 | data_table_trend | widget_precomputed | y |
| acidity-of-carboxylic-acids-and-substituent-effects | 3 | data_table_trend | widget_precomputed | y |
| acidity-of-carboxylic-acids-and-substituent-effects | 4 | data_table_trend | widget_precomputed | y |
| acidity-of-carboxylic-acids-and-substituent-effects | 5 | data_table_trend | widget_precomputed | y |
| acidity-of-carboxylic-acids-and-substituent-effects | 6 | data_table_trend | widget_precomputed | y |
| aldol-condensation | 1 | reaction_scheme | widget_precomputed | y |
| aldol-condensation | 2 | reaction_scheme | widget_precomputed | y |
| aldol-condensation | 3 | reaction_scheme | widget_precomputed | y |
| aldol-condensation | 4 | reaction_scheme | widget_precomputed | y |
| aldol-condensation | 5 | reaction_scheme | widget_precomputed | **n — (b) crossed-aldol product names wrong (2 of 4)** |
| aldol-condensation | 6 | reaction_scheme | widget_precomputed | y |
| aldol-condensation | 7 | reaction_scheme | widget_precomputed | y |
| aldol-condensation | 8 | reaction_scheme | widget_precomputed | y |
| aldol-condensation | 9 | reaction_scheme | widget_precomputed | y |
| alpha-halogenation-and-hell-volhard-zelinsky-reaction | 1 | decline -> svg | svg_live | y |
| alpha-halogenation-and-hell-volhard-zelinsky-reaction | 2 | decline -> svg | svg_live | y |
| alpha-halogenation-and-hell-volhard-zelinsky-reaction | 3 | decline -> svg | svg_live | y |
| alpha-halogenation-and-hell-volhard-zelinsky-reaction | 4 | decline -> svg | svg_live | y |
| alpha-halogenation-and-hell-volhard-zelinsky-reaction | 5 | decline -> svg | svg_live | y |
| alpha-halogenation-and-hell-volhard-zelinsky-reaction | 6 | decline -> svg | svg_live | y |
| cannizzaro-reaction | 1 | decline -> svg | svg_live | y |
| cannizzaro-reaction | 2 | decline -> svg | svg_live | y |
| cannizzaro-reaction | 3 | decline -> svg | svg_precomputed | y |
| cannizzaro-reaction | 4 | decline -> svg | svg_live | y |
| cannizzaro-reaction | 5 | decline -> svg | svg_precomputed | y |
| cannizzaro-reaction | 6 | decline -> svg | svg_live | y |
| distinguishing-tests-for-aldehydes-ketones-and-acids | 1 | decline -> svg | svg_live | y |
| distinguishing-tests-for-aldehydes-ketones-and-acids | 2 | decline -> svg | svg_precomputed | y |
| distinguishing-tests-for-aldehydes-ketones-and-acids | 3 | decline -> svg | svg_live | y |
| distinguishing-tests-for-aldehydes-ketones-and-acids | 4 | decline -> svg | svg_live | y |
| distinguishing-tests-for-aldehydes-ketones-and-acids | 5 | decline -> svg | svg_live | y |
| distinguishing-tests-for-aldehydes-ketones-and-acids | 6 | decline -> svg | svg_live | y |
| distinguishing-tests-for-aldehydes-ketones-and-acids | 7 | decline -> text_only | svg_live | **n — (c) four-station decision tree, nothing drawn** |
| distinguishing-tests-for-aldehydes-ketones-and-acids | 8 | decline -> svg | svg_precomputed | **n — (a) convex-lens ray_diagram captioned as Tollens'** |
| haloform-reaction | 1 | decline -> svg | svg_live | **n — (a) invented kinetics plot for a qualitative test** |
| haloform-reaction | 2 | decline -> svg | svg_live | y |
| haloform-reaction | 3 | decline -> svg | svg_precomputed | y |
| haloform-reaction | 4 | decline -> svg | svg_live | y |
| haloform-reaction | 5 | decline -> svg | svg_precomputed | y |
| haloform-reaction | 6 | decline -> svg | svg_live | **n — (b) caption says boiling destroys ppt; curve plateaus** |
| haloform-reaction | 7 | decline -> svg | svg_precomputed | y |
| haloform-reaction | 8 | decline -> svg | svg_live | y |
| haloform-reaction | 9 | decline -> svg | svg_live | y |
| multi-step-conversions-and-reaction-maps | 1 | decline -> svg | svg_live | y |
| multi-step-conversions-and-reaction-maps | 2 | decline -> svg | svg_live | y |
| multi-step-conversions-and-reaction-maps | 3 | decline -> text_only | svg_live | y |
| multi-step-conversions-and-reaction-maps | 4 | decline -> text_only | svg_live | y |
| multi-step-conversions-and-reaction-maps | 5 | decline -> svg | svg_precomputed | y |
| multi-step-conversions-and-reaction-maps | 6 | decline -> text_only | svg_live | **n — (c) decision tree, nothing drawn** |
| multi-step-conversions-and-reaction-maps | 7 | decline -> svg | svg_precomputed | y |
| multi-step-conversions-and-reaction-maps | 8 | decline -> svg | svg_precomputed | y |
| multi-step-conversions-and-reaction-maps | 9 | decline -> svg | svg_precomputed | y |
| nomenclature-and-structure-of-carbonyl-compounds | 1 | decline -> svg | svg_live | y |
| nomenclature-and-structure-of-carbonyl-compounds | 2 | decline -> svg | svg_live | y |
| nomenclature-and-structure-of-carbonyl-compounds | 3 | decline -> svg | svg_precomputed | y |
| nomenclature-and-structure-of-carbonyl-compounds | 4 | decline -> svg | svg_precomputed | y |
| nomenclature-and-structure-of-carbonyl-compounds | 5 | decline -> svg | svg_live | y |
| nomenclature-and-structure-of-carbonyl-compounds | 6 | decline -> svg | svg_live | y |
| nomenclature-and-structure-of-carbonyl-compounds | 7 | decline -> text_only | svg_live | **n — (c) isomer structures, nothing drawn** |
| nomenclature-and-structure-of-carbonyl-compounds | 8 | decline -> svg | svg_live | y |
| nucleophilic-addition-reactions-of-aldehydes-and-ketones | 1 | reaction_scheme | widget_precomputed | y |
| nucleophilic-addition-reactions-of-aldehydes-and-ketones | 2 | reaction_scheme | widget_precomputed | y |
| nucleophilic-addition-reactions-of-aldehydes-and-ketones | 3 | reaction_scheme | widget_precomputed | **n — (a) reactivity ranking drawn as a reaction sequence** |
| nucleophilic-addition-reactions-of-aldehydes-and-ketones | 4 | reaction_scheme | widget_precomputed | y |
| nucleophilic-addition-reactions-of-aldehydes-and-ketones | 5 | reaction_scheme | widget_precomputed | y |
| nucleophilic-addition-reactions-of-aldehydes-and-ketones | 6 | reaction_scheme | widget_precomputed | y |
| nucleophilic-addition-reactions-of-aldehydes-and-ketones | 7 | reaction_scheme | widget_precomputed | y |
| nucleophilic-addition-reactions-of-aldehydes-and-ketones | 8 | reaction_scheme | widget_precomputed | **n — (b) arrow ends on reagent NH2OH; oxime missing** |
| oxidation-and-reduction-of-aldehydes-and-ketones | 1 | reaction_scheme | widget_precomputed | y |
| oxidation-and-reduction-of-aldehydes-and-ketones | 2 | reaction_scheme | widget_archetype | **n — (b) caption recycled from seg 1; Fehling's/Benedict's absent** |
| oxidation-and-reduction-of-aldehydes-and-ketones | 3 | reaction_scheme | widget_precomputed | y |
| oxidation-and-reduction-of-aldehydes-and-ketones | 4 | reaction_scheme | widget_precomputed | **n — (a) three reducing agents concatenated, nothing compared** |
| oxidation-and-reduction-of-aldehydes-and-ketones | 5 | reaction_scheme | widget_precomputed | **n — (b) Clemmensen/Wolff-Kishner share one identical reagent label** |
| oxidation-and-reduction-of-aldehydes-and-ketones | 6 | reaction_scheme | widget_precomputed | y |
| oxidation-and-reduction-of-aldehydes-and-ketones | 7 | reaction_scheme | widget_precomputed | y |
| oxidation-and-reduction-of-aldehydes-and-ketones | 8 | reaction_scheme | widget_archetype | y |
| physical-properties-and-hydrogen-bonding-in-carbonyl-compounds | 1 | decline -> svg | svg_live | **n — (a) free_body_diagram for intermolecular forces** |
| physical-properties-and-hydrogen-bonding-in-carbonyl-compounds | 2 | decline -> svg | svg_live | y |
| physical-properties-and-hydrogen-bonding-in-carbonyl-compounds | 3 | decline -> svg | svg_live | y |
| physical-properties-and-hydrogen-bonding-in-carbonyl-compounds | 4 | decline -> svg | svg_precomputed | y |
| physical-properties-and-hydrogen-bonding-in-carbonyl-compounds | 5 | decline -> svg | svg_live | **n — (a) 'mass' drawn as a force vector** |
| physical-properties-and-hydrogen-bonding-in-carbonyl-compounds | 6 | decline -> svg | svg_live | y |
| physical-properties-and-hydrogen-bonding-in-carbonyl-compounds | 7 | decline -> svg | svg_precomputed | y |
| physical-properties-and-hydrogen-bonding-in-carbonyl-compounds | 8 | decline -> svg | svg_precomputed | y |
| preparation-of-aldehydes-and-ketones | 1 | reaction_scheme | widget_precomputed | **n — (b) LiAlH4 arrow drawn ketone -> aldehyde** |
| preparation-of-aldehydes-and-ketones | 2 | reaction_scheme | widget_precomputed | y |
| preparation-of-aldehydes-and-ketones | 3 | reaction_scheme | widget_precomputed | y |
| preparation-of-aldehydes-and-ketones | 4 | reaction_scheme | widget_precomputed | y |
| preparation-of-aldehydes-and-ketones | 5 | reaction_scheme | widget_precomputed | y |
| preparation-of-aldehydes-and-ketones | 6 | reaction_scheme | widget_precomputed | y |
| preparation-of-aldehydes-and-ketones | 7 | reaction_scheme | widget_precomputed | y |
| preparation-of-aldehydes-and-ketones | 8 | reaction_scheme | widget_precomputed | **n — (b) R'2Cd from RCN; Friedel-Crafts from RCOCl and ArCHO** |
| preparation-of-carboxylic-acids | 1 | decline -> text_only | svg_live | y |
| preparation-of-carboxylic-acids | 2 | decline -> svg | svg_live | y |
| preparation-of-carboxylic-acids | 3 | decline -> svg | svg_live | y |
| preparation-of-carboxylic-acids | 4 | decline -> svg | svg_precomputed | y |
| preparation-of-carboxylic-acids | 5 | decline -> svg | svg_precomputed | y |
| preparation-of-carboxylic-acids | 6 | decline -> svg | svg_live | y |
| preparation-of-carboxylic-acids | 7 | decline -> svg | svg_precomputed | y |
| reactions-of-carbonyl-compounds-with-ammonia-derivatives | 1 | decline -> svg | svg_live | y |
| reactions-of-carbonyl-compounds-with-ammonia-derivatives | 2 | decline -> svg | svg_live | y |
| reactions-of-carbonyl-compounds-with-ammonia-derivatives | 3 | decline -> svg | svg_live | y |
| reactions-of-carbonyl-compounds-with-ammonia-derivatives | 4 | decline -> svg | svg_live | y |
| reactions-of-carbonyl-compounds-with-ammonia-derivatives | 5 | decline -> svg | svg_live | y |
| reactions-of-carbonyl-compounds-with-ammonia-derivatives | 6 | decline -> svg | svg_live | y |
| reactions-of-carboxylic-acids | 1 | reaction_scheme | widget_precomputed | y |
| reactions-of-carboxylic-acids | 2 | reaction_scheme | widget_precomputed | y |
| reactions-of-carboxylic-acids | 3 | reaction_scheme | widget_precomputed | **n — (b) final arrow draws ester -> H2O** |
| reactions-of-carboxylic-acids | 4 | reaction_scheme | widget_precomputed | **n — (b) reagent labels shifted; anhydride arrow blank** |
| reactions-of-carboxylic-acids | 5 | reaction_scheme | widget_precomputed | y |
| reactions-of-carboxylic-acids | 6 | reaction_scheme | widget_precomputed | **n — (b) propanoate decarboxylation drawn giving CH4** |
| reactions-of-carboxylic-acids | 7 | reaction_scheme | widget_precomputed | y |

## Every proposed n, in full

Ordered highest-value first: chemically wrong schemes, then wrong-widget calls, then the
picture-less declines. Each entry gives the objective verbatim, the payload verbatim, the slot,
and the criterion.

---

### n-1. `preparation-of-aldehydes-and-ketones` seg 1 — "The Carbonyl Family and Why Preparation Matters"
**slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high`
**objective:** "Recall the structural difference between aldehydes and ketones and explain why selective preparation is important."
**params:**
```json
{"caption": "Selective routes stop at the aldehyde; strong reagents overshoot to acid or alcohol.",
 "species": ["R-CH2OH", "R-CHO", "R-COOH", "R-CO-R'"],
 "step_to": [1, 2, 1], "step_from": [0, 1, 3],
 "step_kind": ["major", "minor", "minor"],
 "step_reagent": ["PCC / cold DIBAL-H (selective)", "strong oxidant (KMnO4/HNO3)", "strong hydride (LiAlH4)"],
 "step_progress": 0.5, "highlight_step": 0}
```
**Criterion (b) — chemically wrong edge.** The third step is `step_from[2]=3 -> step_to[2]=1`,
i.e. **`R-CO-R'` (a ketone) → `R-CHO` (an aldehyde), reagent LiAlH4.** LiAlH4 reduces a ketone to a
**secondary alcohol** (`R2CHOH`); it cannot give an aldehyde, and no hydride converts a ketone into
an aldehyde at all. Even on the charitable reading that index 3 was meant to be `R-COOH` (index 2),
LiAlH4 on an acid gives the **primary alcohol**, not the aldehyde. The caption itself says strong
reagents "overshoot to acid or **alcohol**" — but the arrow the caption is describing points at the
aldehyde node, so caption and arrow disagree. There is no alcohol node on the reduction side to
point at. First-segment-of-concept, so this is the first scheme a student sees in this concept.

---

### n-2. `preparation-of-aldehydes-and-ketones` seg 8 — "Preparation Map and Selectivity Logic"
**slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high`
**objective:** "Given a target aldehyde or ketone, select an appropriate preparation route from the full map and justify the choice."
**params:**
```json
{"caption": "Preparation map: gentle reagents stop at the target — poisoned Pd/BaSO4 gives RCHO, R'2Cd gives RCOR'",
 "species": ["RCH2OH", "RCHO", "RCOCl", "RCN", "RCOR'", "ArCHO", "ArCOCH3"],
 "step_to": [1, 1, 1, 4, 4, 6], "step_from": [0, 2, 3, 3, 2, 5],
 "step_kind": ["plain", "major", "major", "major", "major", "major"],
 "step_reagent": ["Cu, 573 K", "Pd/BaSO4 (poisoned)", "DIBAL-H, cold", "R'2Cd", "CH3COCl / anhyd. AlCl3", "CH3COCl / anhyd. AlCl3"],
 "step_progress": 1.0, "highlight_step": 1}
```
**Criterion (b) — three of six edges are chemically wrong.** Decoding `(from → to, reagent)`:

| # | edge | reagent | verdict |
|---|---|---|---|
| 1 | RCH2OH → RCHO | Cu, 573 K | correct |
| 2 | RCOCl → RCHO | Pd/BaSO4 (poisoned) | correct (Rosenmund) |
| 3 | RCN → RCHO | DIBAL-H, cold | correct |
| 4 | **RCN → RCOR'** | R'2Cd | **wrong** — dialkylcadmium acylates an **acyl chloride** (`RCOCl`, index 2), not a nitrile. `step_from` should be 2, not 3. |
| 5 | **RCOCl → RCOR'** | CH3COCl / anhyd. AlCl3 | **wrong** — Friedel-Crafts acylation needs an **arene** as the substrate. Here the acyl chloride is drawn as both substrate and reagent. |
| 6 | **ArCHO → ArCOCH3** | CH3COCl / anhyd. AlCl3 | **wrong** — should be ArH → ArCOCH3. Worse, `-CHO` is the deactivating, meta-directing group this very chapter teaches ([physical-properties seg 6] and [reactions-of-carboxylic-acids seg 7] both spend a segment on exactly that), so a ring already carrying `-CHO` will **not** undergo Friedel-Crafts acylation. The map contradicts the chapter. |

This is the "full map" summary segment, so a student is invited to read routes off it directly.

---

### n-3. `reactions-of-carboxylic-acids` seg 4 — "Conversion to Acyl Chlorides and Anhydrides"
**slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high`
**objective:** "Choose the best reagent to convert a carboxylic acid to an acyl chloride or anhydride and justify the choice."
**params:**
```json
{"caption": "Breaking the C–OH bond: SOCl2 wins for acyl chlorides, H2SO4/P2O5 for anhydrides",
 "species": ["RCOOH", "RCOCl", "POCl3 + HCl", "H3PO3 + HCl", "SO2↑ + HCl↑", "(RCO)2O + H2O"],
 "step_to": [1, 1, 1, 1, 5], "step_from": [0, 0, 0, 0, 0],
 "step_kind": ["plain", "minor", "major", "plain", "plain"],
 "step_reagent": ["PCl5", "PCl3", "SOCl2", "conc. H2SO4 or P2O5, Δ", ""],
 "step_progress": 1, "highlight_step": 2}
```
**Criterion (b) — reagent labels are shifted by one relative to the products.** The fourth edge is
`RCOOH → RCOCl` with reagent **"conc. H2SO4 or P2O5, Δ"**. Those are dehydrating agents: they give
the **anhydride**, never the acyl chloride. Meanwhile the fifth edge — the one that actually reaches
the anhydride node `(RCO)2O` — carries **an empty reagent string `""`**, so the anhydride arrow is
drawn unlabelled. The caption states the correct pairing ("H2SO4/P2O5 for anhydrides"), so the
picture directly contradicts its own caption. A student reading the arrows learns the wrong reagent
for the acid-chloride conversion, which is a standard one-mark board question.

---

### n-4. `reactions-of-carboxylic-acids` seg 6 — "Decarboxylation and HVZ Halogenation"
**slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high`
**objective:** "Predict the products of decarboxylation (sodalime) and HVZ alpha-halogenation of carboxylic acids."
**params:**
```json
{"caption": "Decarboxylation (n → n−1 carbons) vs HVZ α-bromination (COOH kept, α-H swapped)",
 "species": ["CH3COONa", "CH4", "CH3CH2COONa", "CH3CH2COOH", "CH3CHBrCOOH"],
 "step_to": [1, 1, 4], "step_from": [0, 2, 3],
 "step_kind": ["major", "major", "major"],
 "step_reagent": ["NaOH/CaO, Δ", "NaOH/CaO, Δ", "Br2, red P"],
 "step_progress": 1, "highlight_step": -1}
```
**Criterion (b) — chemically wrong product.** The second edge is
`step_from[1]=2 -> step_to[1]=1`, i.e. **`CH3CH2COONa` (sodium propanoate) → `CH4` (methane)** under
sodalime. Sodium propanoate decarboxylates to **ethane, C2H6**. There is no ethane node in
`species`, so both decarboxylation arrows converge on methane. This flatly contradicts the caption's
own rule "n → n−1 carbons": propanoate is C3, so the product must be C2. The third edge
(`CH3CH2COOH + Br2/red P → CH3CHBrCOOH`) is correct.

---

### n-5. `aldol-condensation` seg 5 — "Crossed Aldol: The Four-Product Problem"
**slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high`
**objective:** "Predict the four possible products when two different aldehydes with alpha-H are mixed."
**params:**
```json
{"caption": "Two aldehydes with alpha-H give four products: two self-aldols and two crossed aldols",
 "species": ["ethanal enolate", "ethanal", "propanal", "propanal enolate", "3-hydroxybutanal",
             "3-hydroxy-2-methylpentanal", "3-hydroxy-2-methylbutanal", "3-hydroxy-2-methylhexanal"],
 "step_to": [4, 5, 6, 7], "step_from": [0, 0, 3, 3],
 "step_kind": ["plain", "plain", "plain", "plain"],
 "step_reagent": ["ethanal", "propanal", "ethanal", "propanal"],
 "step_progress": 1, "highlight_step": -1}
```
**Criterion (b) — two of the four product names are chemically wrong.** Working each edge:

| edge | enolate + electrophile | correct product | drawn as | verdict |
|---|---|---|---|---|
| 1 | ethanal enolate + ethanal | 3-hydroxybutanal | 3-hydroxybutanal | correct |
| 2 | ethanal enolate + propanal | **3-hydroxypentanal** | 3-hydroxy-2-methylpentanal | **wrong** — the attacking carbon is `⁻CH2CHO`, unsubstituted, so there is no 2-methyl branch |
| 3 | propanal enolate + ethanal | 3-hydroxy-2-methylbutanal | 3-hydroxy-2-methylbutanal | correct |
| 4 | propanal enolate + propanal | **3-hydroxy-2-methylpentanal** | 3-hydroxy-2-methylhexanal | **wrong** — the product is C6 but the principal chain is pentanal with a 2-methyl, not hexanal |

Note the drawn name for edge 2 is the *correct* name for edge 4, so it looks like a one-row shift
plus a miscount. "Predict the four possible products" is exactly the skill this segment is for, and
half the answer key on the board is wrong.

---

### n-6. `nucleophilic-addition-reactions-of-aldehydes-and-ketones` seg 8 — "Putting It All Together: Predicting Products and Solving Problems"
**slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high`
**objective:** "Apply the nucleophilic addition framework to predict products and answer exam-style questions."
**params:**
```json
{"caption": "One engine, three nucleophiles: attack, rehybridise, protonate (or eliminate)",
 "species": ["CH3CH2CHO", "CN-", "CH3CH2CH(O-)CN", "CH3CH2CH(OH)CN", "CH3MgBr",
             "CH3CH2CH(O-)CH3", "CH3CH2CH(OH)CH3", "NH2OH"],
 "step_to": [2, 3, 5, 6, 7], "step_from": [0, 2, 0, 5, 0],
 "step_kind": ["plain", "plain", "plain", "plain", "plain"],
 "step_reagent": ["CN-", "H+", "CH3MgBr", "H3O+", "NH2OH"],
 "step_progress": 1, "highlight_step": -1}
```
**Criterion (b) — the third branch has no product.** The final edge is
`step_from[4]=0 -> step_to[4]=7` with `step_reagent[4]="NH2OH"`, i.e.
**propanal --NH2OH--> NH2OH.** The arrow terminates on the *reagent itself*. The oxime
(`CH3CH2CH=N-OH`) is simply absent from `species`. The caption promises "three nucleophiles" and the
board text lists `H2N-Z` among them, so the student is told to expect a third product and shown a
reagent instead. The CN⁻ branch and the Grignard branch (→ butan-2-ol) are both correct.

---

### n-7. `reactions-of-carboxylic-acids` seg 3 — "Esterification: Nucleophilic Acyl Substitution Mechanism"
**slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high`
**objective:** "Describe the acid-catalyzed esterification mechanism and explain how to drive the equilibrium forward."
**params:**
```json
{"caption": "Acid-catalyzed esterification: protonation → nucleophilic attack → proton transfer → loss of water gives the ester; all steps reversible.",
 "species": ["RCOOH", "R-C(OH)2+ (protonated)", "tetrahedral intermediate", "R-C(OH)(OH2+)", "RCOOR'", "H2O"],
 "step_to": [1, 2, 3, 4, 5], "step_from": [0, 1, 2, 3, 4],
 "step_kind": ["plain", "plain", "plain", "major", "plain"],
 "step_reagent": ["H+ (H2SO4/HCl)", "R'OH", "proton transfer", "–H2O, –H+", "catalyst regenerated"],
 "step_progress": 0.0, "highlight_step": 3}
```
**Criterion (b) — the last arrow converts the product into water.** Steps 1–4 are a correct
Fischer esterification. Step 5 is `step_from[4]=4 -> step_to[4]=5`, i.e.
**`RCOOR'` (the ester) → `H2O`**, labelled "catalyst regenerated". Water is a *co-product* of step 4,
not something the ester turns into, and catalyst regeneration is not a species transformation at
all. Drawn as the terminal arrow of a mechanism the student is meant to reproduce, it teaches that
the ester decomposes to water. Lower severity than n-1..n-6 (the four real mechanistic steps are
right and a narrator may well have talked over it) but it is still wrong on the board.

---

### n-8. `oxidation-and-reduction-of-aldehydes-and-ketones` seg 5 — "Reduction to Hydrocarbons: Clemmensen and Wolff-Kishner"
**slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high`
**objective:** "Apply Clemmensen and Wolff-Kishner reductions to convert carbonyl compounds to alkanes, **choosing the appropriate method based on acid/base sensitivity**."
**params:**
```json
{"caption": "Deoxygenation: >C=O → >CH2 — Clemmensen (acidic) or Wolff-Kishner (basic)",
 "species": ["C6H5COCH3", "C6H5CH2CH3", "R2C=O", "R2CH2"],
 "step_to": [1, 3], "step_from": [0, 2],
 "step_kind": ["major", "major"],
 "step_reagent": ["Zn-Hg / conc. HCl  (or NH2NH2, KOH / ethylene glycol, 180-200°C)",
                  "Zn-Hg / conc. HCl  (or NH2NH2, KOH / ethylene glycol, 180-200°C)"],
 "step_progress": 1, "highlight_step": 0}
```
**Criterion (b) — the params cannot express the distinction the objective demands.** There are two
arrows and they carry **byte-identical** reagent strings, each containing *both* named reactions
joined by "(or …)". The whole point of the segment — pick Clemmensen for base-sensitive substrates,
Wolff-Kishner for acid-sensitive ones — is therefore invisible: the board shows two arrows that
differ only in whether the substrate is specific (acetophenone → ethylbenzene, which is correct) or
generic. A two-arrow scheme with one method per arrow was available and free. The scheme is not
*wrong*, it is *uninformative in exactly the place the objective is*.

---

### n-9. `oxidation-and-reduction-of-aldehydes-and-ketones` seg 4 — "Reduction to Alcohols: NaBH4, LiAlH4, and Catalytic Hydrogenation"
**slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high`
**objective:** "**Compare** the reducing agents NaBH4, LiAlH4, and H2/catalyst for converting aldehydes and ketones to alcohols."
**params:**
```json
{"caption": "Reduction adds H across C=O: aldehyde → 1° alcohol, ketone → 2° alcohol",
 "species": ["RCHO (aldehyde)", "R2C=O (ketone)", "RCH2OH (1° alcohol)", "R2CHOH (2° alcohol)"],
 "step_to": [2, 3], "step_from": [0, 1],
 "step_kind": ["major", "major"],
 "step_reagent": ["NaBH4 / LiAlH4 / H2,catalyst", "NaBH4 / LiAlH4 / H2,catalyst"],
 "step_progress": 1.0, "highlight_step": -1}
```
**Criterion (a) — wrong widget for a comparison.** Same defect as n-8, one segment earlier: the
objective is a three-way **comparison** of reagents (selectivity, what each spares, cost of choosing
wrong), and a `reaction_scheme` has nowhere to put that, so all three reagents are concatenated onto
both arrows and the comparison disappears. What the scheme *does* draw (aldehyde → 1°, ketone → 2°)
is correct but is a different, easier fact. A `data_table_trend` / comparison table was the right
shape — and the chapter proves the model knows it, because the *declined* segment
`multi-step-conversions seg 3` teaches the identical NaBH4-vs-LiAlH4 content and the
`acidity` seg 6 board note ("Pitfall 3: Thinking NaBH4 reduces -COOH") states the very distinction
this scheme drops. Lower confidence than n-8 because the objective's verb is softer.

---

### n-10. `oxidation-and-reduction-of-aldehydes-and-ketones` seg 2 — "Mild Oxidizing Agents: Tollens', Fehling's, and Benedict's"
**slot:** `widget_archetype` · fired `reaction_scheme` · route `archetype_high`
**objective:** "Identify the reagents, observations, and limitations of Tollens', Fehling's, and Benedict's tests for aldehydes."
**params:**
```json
{"species": ["R-CHO", "R-COO-", "R-CO-R'"],
 "step_from": [0, 2], "step_to": [1, 2],
 "step_reagent": ["Tollens' [Ag(NH3)2]+ (mild)", "mild oxidant"],
 "step_kind": ["major", "minor"], "highlight_step": 0, "step_progress": 1,
 "caption": "Aldehyde ka carbonyl H aasani se C-OH se swap ho jata hai; ketone ke paas H hi nahi, isliye mild oxidant usse chhoota nahi."}
```
**Criterion (b) — caption belongs to the previous segment, and two of the three named tests are
missing.** Compare segment 1 of the same concept, which fired
`{"species": ["R-CHO","R-COOH","R-CO-R'"], "caption": "Aldehyde's carbonyl C-H swaps for C-OH under
mild oxidants; ketone has no H, so mild oxidants leave it unchanged."}` — this segment's caption is a
**Hinglish translation of segment 1's caption**, and the scheme is segment 1's scheme with `R-COOH`
swapped for `R-COO-` and one reagent relabelled. So (i) the caption describes *why aldehydes oxidise*,
which was segment 1's objective, not *the reagents, observations and limitations of three named
tests*, which is this one's; (ii) **Fehling's and Benedict's appear in the title and the objective but
nowhere in the payload**; (iii) no observation (silver mirror / brick-red Cu2O) is on the board
diagram at all, though the board text carries them. The student is shown near-enough the same picture
twice. Note this is one of only **two** `widget_archetype` slots in the whole chapter, so it is worth
checking whether that path skips the caption-regeneration the `widget_precomputed` path gets.

---

### n-11. `nucleophilic-addition-reactions-of-aldehydes-and-ketones` seg 3 — "Reactivity Order: Aldehydes vs Ketones and Electronic Effects"
**slot:** `widget_precomputed` · fired `reaction_scheme` · route `archetype_high`
**objective:** "Rank carbonyl compounds by reactivity toward nucleophilic addition using steric and electronic factors."
**params:**
```json
{"caption": "Reactivity toward nucleophilic addition falls as electron donation and steric bulk increase",
 "species": ["CCl3CHO", "HCHO", "CH3CHO", "CH3COCH3"],
 "step_to": [1, 2, 3], "step_from": [0, 1, 2],
 "step_kind": ["major", "plain", "minor"],
 "step_reagent": ["3× Cl (-I) withdraw", "1× CH3 (+I) donate", "2× CH3 (+I) + steric"],
 "step_progress": 1, "highlight_step": -1}
```
**Criterion (a) — a ranking rendered as a reaction.** The *ranking* is correct
(CCl3CHO > HCHO > CH3CHO > CH3COCH3). But `reaction_scheme` draws reaction arrows, so the board
reads **CCl3CHO → HCHO → CH3CHO → CH3COCH3**, i.e. chloral converting to formaldehyde converting to
acetaldehyde converting to acetone, with the "reagents" on the arrows being electronic-effect
phrases rather than reagents. Nothing in this segment is a reaction. This is the one place in the
chapter where the archetype column's `high`-confidence forcing of `reaction_scheme` visibly
misfires: `data_table_trend` is the right widget and is **already wired for this chapter** (the
Acidity concept uses it six times for exactly this kind of ranking). Worth asking whether a concept
can carry a secondary archetype for its ranking segments.

---

### n-12. `distinguishing-tests-for-aldehydes-ketones-and-acids` seg 8 — "Stoichiometry and Exam Traps"
**slot:** `svg_precomputed` · **declined** (`model_chose_no_widget`), emitted `svg` from `segment_example_diagram_svg`
**objective:** "Calculate moles of silver or Cu2O formed in oxidation tests and avoid common exam pitfalls."
**what it emitted instead** (the `diagram` board event the student sees):
```json
{"template": "ray_diagram",
 "params": {"optic_type": "convex_lens", "object_pos": 30, "focal_length": 10},
 "caption": "Tollens' test: aldehyde reduces Ag+ to a silver mirror"}
```
**Criterion (a) — a physics ray diagram on a chemistry board.** The student is shown a **convex lens
with object and focal-length construction rays**, captioned as if it were the Tollens' test. There is
no relationship whatsoever between the picture and the caption, the objective, or the board text
(which is a correct 1 mol RCHO : 2 mol Ag stoichiometry note). Note `diag_hint` for this row is
`ray_diagram`, so the hint appears to have leaked a physics template into a chemistry segment and the
model rendered it literally rather than rejecting it. **This is the single most visibly broken board
in the chapter** and is worth treating as a harness bug, not a content judgement: check why
`diag_hint=ray_diagram` is being produced for carbonyl chemistry at all. (`diag_hint=ray_diagram`
also appears on rows 33, 46, 49, 52, 69, 72, 75 — the other seven either declined to text or ignored
the hint, so this is the one that got through.)

---

### n-13. `haloform-reaction` seg 1 — "The Yellow Solid That Tells a Story"
**slot:** `svg_live` · **declined**, emitted `svg` from `template_or_live`
**objective:** "Recognize the iodoform test as a qualitative test for methyl ketones and methyl carbinols, and recall its visual signature."
**what it emitted instead:**
```json
{"template": "labeled_axes_plot",
 "params": {"x_label": "Time (minutes)", "y_label": "Amount of yellow precipitate",
            "curve_points": [[0,0],[1,2],[2,5],[3,8],[4,10],[5,10]],
            "annotations": [{"x":2,"y":5,"text":"Yellow solid appears"},{"x":5,"y":10,"text":"Precipitate settles"}],
            "title": "Formation of Iodoform Precipitate Over Time"},
 "caption": "Yellow precipitate builds up as the test proceeds"}
```
**Criterion (a) — a fabricated quantitative plot for an explicitly qualitative test.** The objective
says "**qualitative** test … recall its visual signature". The board draws a **kinetics curve with
invented numbers** on an unlabelled-unit y-axis ("Amount of yellow precipitate" 0→10). No such data
is taught, measured, or examinable; the rate of iodoform precipitation is not in the syllabus. The
one thing the objective asks for — the *visual signature*, a yellow solid — is the one thing a plot
cannot show. `diag_hint` here is `labeled_axes_plot`, so again the hint appears to be driving a
physics-shaped template into a qualitative-chemistry segment.

---

### n-14. `haloform-reaction` seg 6 — "Test Conditions and Limitations"
**slot:** `svg_live` · **declined**, emitted `svg` from `template_or_live`
**objective:** "State the reagents and conditions for the iodoform test and list common false positives and negatives."
**what it emitted instead:**
```json
{"template": "labeled_axes_plot",
 "params": {"x_label": "Time (minutes)", "y_label": "Amount of yellow precipitate",
            "curve_points": [[0,0],[2,1],[4,3],[6,5],[8,6],[10,6]],
            "annotations": [[4,3,"gentle warming"],[8,6,"plateau"]],
            "title": "Iodoform precipitate vs warming time"},
 "caption": "Gentle warming builds the yellow precipitate; boiling destroys it."}
```
**Criterion (b) — caption contradicts the curve, and the annotation shape is inconsistent.**
The caption's second clause, "**boiling destroys it**", is the pedagogically important half (it is
the "limitation" in the segment title). The curve does the opposite: it rises and then **plateaus at
6 and stays there**. Nothing on the plot ever falls, so the board asserts in words the reverse of
what it draws. Two further problems: (i) the numbers are again invented, same objection as n-13;
(ii) `annotations` here are **3-element arrays** `[x, y, text]` whereas the same template in n-13
(one segment sibling, same concept) uses **objects** `{"x":…, "y":…, "text":…}`. One of those two
shapes is presumably not what the renderer expects — worth a schema check, since a silently-dropped
annotation would strip the labels off this plot entirely.

---

### n-15. `physical-properties-and-hydrogen-bonding-in-carbonyl-compounds` seg 1 — "The Boiling-Point Ladder: Why Carbonyls Sit Where They Do"
**slot:** `svg_live` · **declined**, emitted `svg` from `template_or_live`
**objective:** "Rank a given set of compounds (hydrocarbon, ether, aldehyde/ketone, alcohol, carboxylic acid) by boiling point using the intermolecular force ladder."
**what it emitted instead:**
```json
{"template": "free_body_diagram",
 "params": {"body_label": "molecule",
            "forces": [{"label":"dispersion","angle":0},{"label":"dipole-dipole","angle":90},
                       {"label":"H-bond","angle":180},{"label":"dimer","angle":270}]},
 "caption": "Intermolecular grips holding a molecule in the liquid"}
```
**Criterion (a) — wrong widget, and it asserts something false.** A free-body diagram means "these
forces act on this body **simultaneously**, in these directions". The four labels here are not four
forces on one molecule; they are the **four rungs of a ranking ladder**, each belonging to a
*different* compound class, which is precisely what the objective and the board formula
(`hydrocarbon < ether < aldehyde ≈ ketone < alcohol < carboxylic acid`) are about. Drawing them as
four arrows at 0/90/180/270° on one generic "molecule" tells the student that a single molecule is
simultaneously held by dispersion, dipole-dipole, an H-bond and a dimer — which is wrong, and erases
the ordering that is the entire lesson. The sibling segment 3 of this same concept declines to a
`comparison_table` with rows Hydrocarbon → Carboxylic acid and a "Boiling point" column, which is the
right picture; segment 1 should have had it.

---

### n-16. `physical-properties-and-hydrogen-bonding-in-carbonyl-compounds` seg 5 — "Physical States and Odours: Reading the Ladder in the Lab"
**slot:** `svg_live` · **declined**, emitted `svg` from `template_or_live`
**objective:** "Relate intermolecular forces and molecular mass to physical state (gas, liquid, solid) and odour trends."
**what it emitted instead:**
```json
{"template": "free_body_diagram",
 "params": {"body_label": "Molecule",
            "forces": [{"label":"weak grip","angle":0},{"label":"mass","angle":270}]},
 "caption": "Weak grip + low mass = escapes as gas"}
```
**Criterion (a) — "mass" is drawn as a force vector.** Same template abuse as n-15, but this one
also puts a scalar on a vector diagram: `{"label": "mass", "angle": 270}` renders an arrow labelled
**mass** pointing down. Mass is not a force, and a chemistry board showing a labelled force arrow
called "mass" is teaching bad physics in passing. Neither arrow relates to the objective's actual
content (state and odour trends across the homologous series); the "weak grip" arrow at 0° is not a
grip at all — a cohesive force would point *inward*, not outward, so the direction also contradicts
the caption's meaning. A `comparison_table` (compound / mass / dominant force / state at RT) or a
simple ordered ladder was the right call.

---

### n-17. `distinguishing-tests-for-aldehydes-ketones-and-acids` seg 7 — "Putting It All Together: The Decision Tree"
**slot:** `svg_live` · **declined**, emitted **`text_only`** (no picture at all)
**objective:** "Apply a systematic sequence of tests to identify an unknown carbonyl compound."
**board (all four events, verbatim types):** `heading`, `text`, `text`, `text` — no `diagram`, no `formula`.
> "The Identification Chain: A Four-Station Decision Tree" / "Think like a diagnostic lab: run tests
> in a fixed order, each result narrows the field…" / "Station 1 - 2,4-DNP (Brady's reagent): …
> No precipitate = not a carbonyl; test with NaHCO3 - fizz means carboxylic acid." /
> "Station 2 - Tollens' reagent: silver mirror = ALDEHYDE. No mirror = KETONE."

**Criterion (c) — a decline where a student needed a picture.** The segment's own title and first
line declare it a **four-station decision tree**, and a decision tree is a branching structure whose
entire value is spatial: at each node a yes/no answer sends you down a different branch. Rendered as
four sequential sentences, the branching is gone and the student has to rebuild the tree in their
head from prose — which is the exact task the segment was supposed to do *for* them. This is a
`gap_test_matrix` archetype and the brief says such declines are normally SANE, and I agree the
**routing** is behaving as designed. I am flagging it as evidence that **the gap is real and costly**:
of the 8 segments in this concept, this is the summary segment, and it is the one that most needed
the matrix that does not exist yet. Confirming this as "n" would mean prioritising
`gap_test_matrix`; confirming it "y" would mean accepting the gap. Raasikh's call.

---

### n-18. `multi-step-conversions-and-reaction-maps` seg 6 — "Distinguishing Tests: A Decision Tree"
**slot:** `svg_live` · **declined**, emitted **`text_only`** (no picture at all)
**objective:** "Choose the correct chemical test to distinguish between given aldehydes and ketones, including Tollens', Fehling's, and iodoform tests."
**board (all four events):** `heading`, `text`, `text`, `formula`
> "Distinguishing Tests: A Decision Tree" / "A decision tree narrows possibilities step by step.
> Each test is a filter: ask one question, eliminate, move to the next." /
> "Step 1 — Is there a -CHO group? Tollens' reagent [Ag(NH3)2]+ gives a silver mirror with ALL
> aldehydes (aliphatic and aromatic). Ketones give no reaction." /
> `RCHO + 2[Ag(NH_3)_2]^+ + 3OH^- \rightarrow RCOO^- + 2Ag\downarrow + 4NH_3 + 2H_2O`

**Criterion (c) — same defect as n-17, in a second concept.** Again the segment is *named* "A
Decision Tree" and again nothing is drawn. Two independent concepts reaching for the same missing
picture on the same topic is a strong signal. Worth noting that the **high**-confidence concept
`oxidation-and-reduction seg 7` teaches this identical decision tree and **did** get a picture — it
fired a branching `reaction_scheme` with species `["Unknown carbonyl","2,4-DNP ppt","Aldehyde",
"Ketone","Aliphatic aldehyde","Aromatic aldehyde","Methyl ketone"]` and reagents
`["2,4-DNP (Brady's)","Tollens' [Ag(NH3)2]+","Tollens' — no reaction","Fehling's Cu2+",
"Fehling's — no reaction","I2/NaOH"]`, which I checked and judged SANE. So **a correct rendering of
this exact tree already exists in this chapter's payloads** — the med-confidence concepts just
cannot reach it. That may be the cheapest fix available: let a med concept borrow a verified
branching scheme from a high concept covering the same content.

---

### n-19. `nomenclature-and-structure-of-carbonyl-compounds` seg 7 — "Isomerism in Carbonyl Compounds: Same Formula, Different Structures"
**slot:** `svg_live` · **declined**, emitted **`text_only`** (no picture at all)
**objective:** "Identify functional and chain isomers of aldehydes and ketones."
**board (all four events):** `heading`, `text`, `formula`, `text`
> "Isomerism in Carbonyl Compounds" / "Aldehydes and ketones share the general formula CnH2nO, so
> they are functional isomers of each other." / `\text{General formula: } C_nH_{2n}O` /
> "Functional isomers have the same molecular formula but different functional groups."

**Criterion (c) — the segment is literally titled "Same Formula, **Different Structures**" and shows
no structures.** Isomerism is the canonical draw-it-to-understand-it topic: the skill being taught is
to look at two structures, see that the atom counts match, and name how they differ. The board states
the definition abstractly (`CnH2nO`) and never instantiates it — not even as text, e.g. the standard
C3H6O pair propanal / propanone, which the *same concept's* segment 8 and the physical-properties
concept both use elsewhere. Even a `comparison_table` with two columns of condensed formulae would
have carried it. Lower confidence than n-17/n-18 because a determined student can work from the
definition, but for a "identify the isomers" objective this is a bare board.

---

## Notes and uncertainties

### The big limitation, again
No narration was captured. Everything above is judged from objective + title + board events +
payload params. Three consequences worth holding onto:

- **The (b) flags may be partly rescued by speech.** n-7 (ester → H2O) and n-10 (recycled caption)
  are the two most likely to have been papered over by what the tutor said. n-1, n-2, n-3, n-4, n-5
  and n-6 are **not** rescuable that way: a wrong product name or a wrong reagent on an arrow is
  wrong on the board regardless of what was spoken, and a student copying the board into their
  notebook copies the error.
- **I cannot check "did the widget match the narration's pacing"** — e.g. whether a scheme drew
  step 3 while the tutor was still on step 1. `step_progress` and `highlight_step` are populated and
  vary sensibly (0, 0.5, 1.0), but with no narration timeline I cannot verify any of them, and I
  have flagged none on that basis.
- **I cannot judge whether a decline was covered by speech.** A segment that declined to `text_only`
  may have been perfectly clear if the tutor was describing the tree aloud. The three (c) flags are
  therefore the softest in the set.

### Systematic patterns (the thing to act on, more than any individual segment)

1. **The chemistry errors cluster in the last-step / summary schemes of `high`-confidence concepts.**
   n-1 (prep seg 1), n-2 (prep seg 8, the "full map"), n-3, n-4, n-6 (nuc-add seg 8, "putting it all
   together"), n-7. These are the segments with the *most* species and the *most* edges, and the
   error is almost always an **index error in `step_from` / `step_to` / `step_reagent`** rather than
   a conceptual misunderstanding: an arrow pointing at the reagent instead of the product (n-6), a
   reagent list shifted one position off its products (n-3), an edge sourced from the wrong species
   (n-2 edge 4, n-1 edge 3). The prose on the same boards is consistently correct. **Hypothesis
   worth testing: payload quality degrades as `len(species)` grows**, because the model is
   hand-maintaining three parallel index arrays. 5 of the 6 wrong-chemistry schemes have ≥5 species;
   every scheme with ≤4 species that I checked was correct. If that holds, a cheap validator —
   "every species index appears in at least one edge; no edge terminates on a species that is named
   in a `step_reagent`; `len(step_reagent) == len(step_from) == len(step_to)` **and no reagent is
   the empty string**" — would have caught n-3 and n-6 mechanically, and flagged n-2 and n-5 for
   review. I did not write that validator; it is a suggestion, not a result.
2. **Physics `diag_hint`s are leaking into chemistry segments.** `diag_hint` takes values
   `ray_diagram`, `free_body_diagram`, `vector_resolution`, `labeled_axes_plot` across this chapter.
   Where a widget fired, the hint is harmlessly ignored (e.g. nuc-add seg 1 has
   `hint=free_body_diagram` and fired a perfectly good `reaction_scheme`). Where the row **declined**
   and fell through to a live SVG, the hint sometimes drives the template choice, and that produces
   n-12 (convex lens captioned "Tollens' test"), n-13, n-14, n-15, n-16. All ten physics-template
   diagrams in the chapter are listed below. **This looks like a hint-vocabulary bug, not a content
   bug** — the hint vocabulary appears to be physics-derived and nothing filters it by subject.
3. **`reaction_scheme` is being asked to do jobs it cannot do.** n-8, n-9 and n-11 are all the same
   shape: the objective is a *comparison* or a *ranking*, the archetype column forces
   `reaction_scheme` at `high` confidence, and the model shoehorns. Note this is the cost of the
   high-confidence routing working exactly as designed — it is not a model failure. The fix is at
   the archetype layer (allow a per-segment secondary widget), not in the payloads.
4. **Med-confidence concepts re-teach content that a high concept already has a verified picture
   for.** Clearest case in n-18. Also: `multi-step-conversions` seg 2 (nucleophilic addition) and
   `alpha-halogenation` seg 3 (haloform) both re-teach high/med content that exists elsewhere in the
   chapter with better payloads.

### The full list of physics-template diagrams (for pattern 2)
Row indices are 0-based positions in the JSONL.

| row | concept / seg | template | verdict |
|---|---|---|---|
| 34 | distinguishing-tests seg 8 | `ray_diagram` (convex_lens) | **n-12** |
| 35 | haloform seg 1 | `labeled_axes_plot` | **n-13** |
| 40 | haloform seg 6 | `labeled_axes_plot` | **n-14** |
| 53 | nomenclature seg 1 | `free_body_diagram` | y — see below |
| 60 | nomenclature seg 8 | `labeled_axes_plot` | y — see below |
| 77 | physical-properties seg 1 | `free_body_diagram` | **n-15** |
| 78 | physical-properties seg 2 | `free_body_diagram` | y — borderline |
| 80 | physical-properties seg 4 | `free_body_diagram` | y — borderline |
| 81 | physical-properties seg 5 | `free_body_diagram` | **n-16** |
| 84 | physical-properties seg 8 | `free_body_diagram` | y — trivial but harmless |

### Close calls I proposed **y** on, and why — please sanity-check these

- **row 53, nomenclature seg 1, `free_body_diagram` for the carbonyl carbon.** Params are
  `forces: [{"label":"C=O","angle":90},{"label":"R","angle":210},{"label":"H","angle":330}]`,
  caption "trigonal planar, 120 degree bond angles". This *abuses* a force template to draw bonds —
  but 90/210/330 are exactly 120° apart, so the picture it produces is a geometrically correct
  trigonal-planar centre with the three substituents labelled. It works. Flag it if you would rather
  never see a force template on a chemistry board on principle; I judged output over provenance.
- **row 60, nomenclature seg 8, `labeled_axes_plot` of steric crowding vs reactivity.** Invented
  numbers again (10→2 on unlabelled axes), same objection as n-13 in principle. I let it pass
  because unlike n-13 the plotted relationship **is** what the segment teaches (more crowding → less
  reactive) and the two endpoints are annotated "Aldehyde (1 H)" and "Ketone (2 alkyl)", so the
  student reads the right trend off it. If you want a consistent rule against fabricated
  quantitative data, this becomes an n and n-13/n-14 are joined by it.
- **rows 78 / 80 / 84, physical-properties, `free_body_diagram`.** Row 80 ("Water Solubility: The
  Tug-of-War Between Head and Tail") is the strongest of the three — the segment title is literally a
  tug-of-war and two opposed arrows is a fair picture of it. Rows 78 and 84 are near-empty (two
  arrows, one arrow) but not wrong. Marked y; they are the weakest y's in the set.
- **row 6, aldol seg 1, "The Two Reactive Sites of a Carbonyl".** Objective is anatomy ("identify the
  carbonyl carbon and alpha-carbon as the two reactive sites"), and the fired `reaction_scheme` draws
  enolate formation — which is **segment 2's** content, and segment 2 then fires a near-identical
  scheme. Arguably (a) wrong widget plus a duplicate. I marked y because deprotonation genuinely does
  demonstrate "why alpha-hydrogens are acidic", the second half of the objective. Borderline.
- **row 93, preparation-of-carboxylic-acids seg 1, "the Six Routes", `text_only`.** A six-route
  overview is the kind of thing a route map exists for, and nothing was drawn. I marked y because the
  segment's verb is "**recall** the six routes and identify the starting material for each", which a
  numbered list serves adequately. This was my closest (c) call — it is the 4th-most defensible (c)
  after n-17/n-18/n-19.
- **rows 46 and 47, multi-step-conversions segs 3 and 4, `text_only`.** Both are reagent-selection /
  fork-decision segments with no picture. Marked y: seg 3 is a reagent list that reads fine as prose,
  seg 4 carries its key idea in a formula. Mentioned for completeness since they are the remaining
  two of the six `text_only` rows.

### Chemistry I checked and found **correct** (so the n-list is not just "everything complex")
Recorded so the human knows the depth of the pass, and so a later reviewer does not re-do it:

- **All six `data_table_trend` firings (Acidity).** pKa values spot-checked against NCERT:
  CF3COOH 0.23, CCl3COOH 0.7, CHCl2COOH 1.29, FCH2COOH 2.59, ClCH2COOH 2.87, BrCH2COOH 2.9,
  HCOOH 3.75, CH3COOH 4.76, CH3CH2COOH 4.87; 2-/3-/4-chlorobutanoic 2.86 / 4.05 / 4.52;
  4-nitrobenzoic 3.41, o-toluic 3.9, benzoic 4.19, 4-methoxybenzoic 4.46. All correct, all with
  `trend_col` pointing at pKa and the caption stating the right direction ("smaller pKa = stronger
  acid"). `highlight_row` is used sensibly (row 0 = the extreme, or row 2 = benzoic as the reference).
- **Intramolecular aldol (aldol seg 7).** hexane-2,5-dione → 3-methylcyclopent-2-en-1-one and
  heptane-2,6-dione → 3-methylcyclohex-2-en-1-one. Both ring sizes and both product names correct.
- **Acetone aldol (aldol seg 8).** → diacetone alcohol → mesityl oxide. Correct.
- **Aldol vs Cannizzaro fork (aldol seg 9).** Ethanal/dil. NaOH → aldol; benzaldehyde/conc. NaOH →
  benzyl alcohol + sodium benzoate. Correct, including both base concentrations.
- **Aldehyde-specific reductions (prep seg 5).** Rosenmund (RCOCl + H2/Pd-BaSO4), nitrile → imine →
  RCHO via DIBAL-H then H2O, ester → RCHO via cold DIBAL-H, ester → RCH2OH via LiAlH4 marked `minor`
  as the over-reduction. All five edges correct — this is the best-built scheme in the chapter and a
  good template for fixing n-2.
- **Aromatic aldehyde routes (prep seg 6).** Étard (toluene/CrO2Cl2 then H2O), side-chain
  chlorination (toluene/Cl2, hv → benzal chloride → hydrolysis), Gattermann-Koch (benzene/CO+HCl,
  AlCl3-CuCl). All correct, including the two-step chlorination path.
- **Ozonolysis and alkyne hydration (prep seg 4).** But-2-ene → ethanal; ethyne → ethanal (the
  exception); RC≡CH → RCOCH3. Correct, and the ethyne exception is explicitly carried.
- **Strong oxidation (ox/red seg 3).** Cyclohexanone → adipic acid under hot conc. KMnO4/H+.
  Correct, including that ketone oxidation needs C–C cleavage.
- **Cannizzaro (ox/red seg 6).** HCHO → HCOO⁻ + CH3OH. Correct.
- **Decision tree (ox/red seg 7).** Verified branch by branch — see n-18.
- **Grignard addition (nuc-add seg 5).** CH3MgBr + CH3CHO → propan-2-ol. Correct.
- **Oxime formation (nuc-add seg 7).** Ethanal + hydroxylamine → carbinolamine → CH3CH=N-OH.
  Correct (contrast n-6, where the same reaction is drawn wrong two segments later).
- **HVZ (reactions-of-acids seg 6, third edge).** CH3CH2COOH + Br2/red P → CH3CHBrCOOH. Correct.
- **Amide formation and acid reduction (reactions-of-acids seg 5).** RCOOH → RCOO⁻NH4⁺ → RCONH2 on
  heating; RCOOH → RCH2OH with LiAlH4 or B2H6. Correct, and correctly *not* using NaBH4.
- **Benzoic acid nitration (reactions-of-acids seg 7).** → m-nitrobenzoic acid. Correct.

### Open questions I could not resolve from this data

1. **Do orphaned `species` render?** Several schemes list species that no edge ever touches —
   `reactions-of-carboxylic-acids` seg 2 lists 8 species but all three edges run `0 → 2`, leaving
   `Na`, `H2`, `NaOH`, `H2O`, `NaHCO3`, `CO2` unreferenced; `preparation` seg 7 leaves `CdCl2` and
   `HCl` dangling; `aldol` seg 3 leaves "CH3CHO (molecule B)" dangling. If the renderer draws them as
   co-reagents/by-products this is fine and idiomatic. **If it drops them, then
   `reactions-of-carboxylic-acids` seg 2 loses the CO2 fizz — which is the observable the bicarbonate
   test in its objective turns on — and it should become an n.** I did not flag it because I could
   not read the renderer. **This is the single highest-value thing to check before confirming this
   review**, because it decides one verdict and possibly a pattern.
2. **`\ce{}` in board formulae.** `aldol` seg 1 emits `\ce{>C^{\delta+}=O^{\delta-}}` and `nuc-add`
   seg 4 emits `\ce{R2C=O + HCN ->[base] R2C(OH)CN}`. Most other formulae in the chapter use plain
   `\text{}` LaTeX. Out of scope for sane/insane and not counted in the 19, but flagging it because
   it matches a known issue: if mobile has no mhchem, `\ce{` leaks a literal "ce" onto the board.
   Two rows affected.
3. **Hinglish captions.** Three payload captions are Hinglish (`ox/red` segs 2 and 8,
   `preparation` seg 3's board caption, `alpha-halogenation` seg 6's "Substrate pehle, phir
   conditions"). Both of the `widget_archetype`-slot rows in the chapter are Hinglish-captioned. Not
   judged here — I do not know the product's language policy — but the correlation with
   `widget_archetype` is suspicious and worth a look alongside n-10.
4. **Is `diag_hint` ever *supposed* to drive the fallback template?** If it is advisory only, then
   n-12..n-16 are model failures. If it is authoritative, they are routing failures. Different fix,
   same symptom, and I could not tell which from the JSONL alone.
# biology 12 Ecosystem — SANE proposals

> **These are PROPOSED verdicts for Raasikh to confirm. Nothing here is a decision.**

## Limitation of this review (read first)

**The harness did not capture spoken narration.** Every verdict below is judged from
`segment_objective`, `segment_title` and `model_raw_board_events` (the board text the
student actually sees), plus `params` / `prior_payload_block`. I have **not** read the
tutor's spoken line for any segment. Where a verdict turns on "the objective says X but
the picture shows Y", it is possible the narration filled the gap in words — that is
exactly the kind of call a human should make, and it is flagged per-finding.

**Second limitation.** `fired=False` is not the same as "the student saw no picture".
Only 9 of the 70 segments are true declines (`emitted_instead == "text_only"`).
In the other 26 non-firing segments the model emitted an SVG / named template instead
(`emitted_instead == "svg"`), so a picture did reach the board — it just did not come
through the archetype widget branch. Criterion (c) is therefore applied only to the
9 genuine text-only segments.

**Third limitation.** I cannot see how `process_flow` renders `branch_at`. Two findings
(ROW31, and the shape criticism in ROW15/ROW57) depend on whether a `chain` layout with
`branch_at = -1` really draws one straight arrow sequence. I have assumed it does,
because that is what "layout chain" states. If it does not, ROW15 and ROW57 weaken.

## Counts

proposed y: 53 ; proposed n: 17 (of 70; of which the first 40 — the 40 `widget_archetype`
rows — are in the committed sheet)

- **In-sheet (40 `widget_archetype` rows = the 40 rows of `routing_bio_ch12_v5_payloads.txt`):
  28 y, 12 n.**
- **Out-of-sheet (30 `svg_live` / `svg_precomputed` rows): 25 y, 5 n. These five have no
  row in the committed sheet to be filled in.**

Mapping note: the sheet's 40 rows are *not* JSONL lines 1–40. The sheet covers exactly the
40 rows whose `board_slot == "widget_archetype"`, which are JSONL lines
**1–17, 26–32, 39–46, 56–63**. The remaining 30 lines (18–25, 33–38, 47–55, 64–70) are the
svg-slot rows and are marked `NO` in the table.

## Per-segment verdicts

| # | subtopic | seg | fired widget / decline | slot | verdict | in sheet? |
|---|---|---|---|---|---|---|
| 1 | carbon-cycle | 1 | DECLINE -> text_only | widget_archetype | y | yes |
| 2 | carbon-cycle | 2 | DECLINE -> text_only | widget_archetype | y | yes |
| 3 | carbon-cycle | 3 | process_flow | widget_archetype | y | yes |
| 4 | carbon-cycle | 4 | process_flow | widget_archetype | y | yes |
| 5 | carbon-cycle | 5 | process_flow | widget_archetype | y | yes |
| 6 | carbon-cycle | 6 | process_flow | widget_archetype | y | yes |
| 7 | carbon-cycle | 7 | process_flow | widget_archetype | y | yes |
| 8 | carbon-cycle | 8 | process_flow | widget_archetype | y | yes |
| 9 | carbon-cycle | 9 | DECLINE -> text_only | widget_archetype | y | yes |
| 10 | decomposition | 1 | process_flow | widget_archetype | y | yes |
| 11 | decomposition | 2 | process_flow | widget_archetype | y | yes |
| 12 | decomposition | 3 | process_flow | widget_archetype | n (b) | yes |
| 13 | decomposition | 4 | process_flow | widget_archetype | y | yes |
| 14 | decomposition | 5 | process_flow | widget_archetype | y | yes |
| 15 | decomposition | 6 | process_flow | widget_archetype | n (a) | yes |
| 16 | decomposition | 7 | process_flow | widget_archetype | y | yes |
| 17 | decomposition | 8 | process_flow | widget_archetype | n (b) | yes |
| 18 | eco-pyramids | 1 | no widget -> svg (template_or_live) | svg_live | y | NO |
| 19 | eco-pyramids | 2 | no widget -> svg (template_or_live) | svg_live | y | NO |
| 20 | eco-pyramids | 3 | no widget -> svg (segment_example_diagram_svg) | svg_precomputed | y | NO |
| 21 | eco-pyramids | 4 | no widget -> svg (template_or_live) | svg_live | n (b) | NO |
| 22 | eco-pyramids | 5 | no widget -> svg (segment_example_diagram_svg) | svg_precomputed | y | NO |
| 23 | eco-pyramids | 6 | DECLINE -> text_only | svg_live | y | NO |
| 24 | eco-pyramids | 7 | no widget -> svg (template_or_live) | svg_live | y | NO |
| 25 | eco-pyramids | 8 | no widget -> svg (segment_example_diagram_svg) | svg_precomputed | y | NO |
| 26 | succession | 1 | process_flow | widget_archetype | y | yes |
| 27 | succession | 2 | process_flow | widget_archetype | n (a) | yes |
| 28 | succession | 3 | process_flow | widget_archetype | y | yes |
| 29 | succession | 4 | process_flow | widget_archetype | y | yes |
| 30 | succession | 5 | process_flow | widget_archetype | n (b) | yes |
| 31 | succession | 6 | process_flow | widget_archetype | y | yes |
| 32 | succession | 7 | process_flow | widget_archetype | n (b) | yes |
| 33 | eco-structure | 1 | no widget -> svg (template_or_live) | svg_live | y | NO |
| 34 | eco-structure | 2 | no widget -> svg (template_or_live) | svg_live | y | NO |
| 35 | eco-structure | 3 | no widget -> svg (template_or_live) | svg_live | y | NO |
| 36 | eco-structure | 4 | no widget -> svg (segment_example_diagram_svg) | svg_precomputed | y | NO |
| 37 | eco-structure | 5 | no widget -> svg (template_or_live) | svg_live | y | NO |
| 38 | eco-structure | 6 | no widget -> svg (template_or_live) | svg_live | y | NO |
| 39 | energy-flow | 1 | process_flow | widget_archetype | y | yes |
| 40 | energy-flow | 2 | process_flow | widget_archetype | y | yes |
| 41 | energy-flow | 3 | process_flow | widget_archetype | y | yes |
| 42 | energy-flow | 4 | process_flow | widget_archetype | y | yes |
| 43 | energy-flow | 5 | process_flow | widget_archetype | y | yes |
| 44 | energy-flow | 6 | DECLINE -> text_only | widget_archetype | n (c) | yes |
| 45 | energy-flow | 7 | DECLINE -> text_only | widget_archetype | y | yes |
| 46 | energy-flow | 8 | process_flow | widget_archetype | n (b) | yes |
| 47 | food-chains | 1 | no widget -> svg (template_or_live) | svg_live | y | NO |
| 48 | food-chains | 2 | no widget -> svg (template_or_live) | svg_live | y | NO |
| 49 | food-chains | 3 | no widget -> svg (segment_example_diagram_svg) | svg_precomputed | n (b) | NO |
| 50 | food-chains | 4 | no widget -> svg (segment_example_diagram_svg) | svg_precomputed | y | NO |
| 51 | food-chains | 5 | no widget -> svg (template_or_live) | svg_live | y | NO |
| 52 | food-chains | 6 | DECLINE -> text_only | svg_live | n (c) | NO |
| 53 | food-chains | 7 | no widget -> svg (template_or_live) | svg_live | y | NO |
| 54 | food-chains | 8 | no widget -> svg (template_or_live) | svg_live | y | NO |
| 55 | food-chains | 9 | no widget -> svg (segment_example_diagram_svg) | svg_precomputed | n (b) | NO |
| 56 | phosphorus-cycle | 1 | process_flow | widget_archetype | y | yes |
| 57 | phosphorus-cycle | 2 | process_flow | widget_archetype | n (a) | yes |
| 58 | phosphorus-cycle | 3 | process_flow | widget_archetype | y | yes |
| 59 | phosphorus-cycle | 4 | process_flow | widget_archetype | n (b) | yes |
| 60 | phosphorus-cycle | 5 | process_flow | widget_archetype | y | yes |
| 61 | phosphorus-cycle | 6 | process_flow | widget_archetype | n (b) | yes |
| 62 | phosphorus-cycle | 7 | process_flow | widget_archetype | n (a) | yes |
| 63 | phosphorus-cycle | 8 | process_flow | widget_archetype | y | yes |
| 64 | productivity | 1 | no widget -> svg (template_or_live) | svg_live | y | NO |
| 65 | productivity | 2 | DECLINE -> text_only | svg_live | y | NO |
| 66 | productivity | 3 | no widget -> svg (segment_example_diagram_svg) | svg_precomputed | y | NO |
| 67 | productivity | 4 | DECLINE -> text_only | svg_live | y | NO |
| 68 | productivity | 5 | no widget -> svg (template_or_live) | svg_live | n (b) | NO |
| 69 | productivity | 6 | no widget -> svg (template_or_live) | svg_live | y | NO |
| 70 | productivity | 7 | no widget -> svg (segment_example_diagram_svg) | svg_precomputed | y | NO |
## Every proposed n, in full

### IN-SHEET (12) — rows that exist in `routing_bio_ch12_v5_payloads.txt`

---

#### n-1 · ROW12 · `decomposition-and-its-steps` seg 3 · slot `widget_archetype`
**Title:** Fragmentation and Leaching: Physical and Chemical Prep
**Objective:** "Describe fragmentation and leaching, and explain their roles in decomposition."
**Params (verbatim):**
```json
{"layout": "chain", "nodes": ["Detritus", "Fragmentation", "Leaching"], "closes": false, "branch_at": -1, "active_node": 1, "caption": "Fragmentation prepares detritus for leaching"}
```
**Prior payload block named:** segment 2 — `process_flow` `{"nodes": ["Detritus", "Fragmentation", "Leaching", "Catabolism", "Humification", "Mineralisation"], "active_node": 1, ...}`

**Reason — criterion (b).** This is a strict three-node **prefix of the chain drawn one
segment earlier**, with the *same* `active_node: 1`. The student saw
Detritus→Fragmentation→Leaching→Catabolism→Humification→Mineralisation in seg 2, with
Fragmentation highlighted; seg 3 redraws the first three of those six nodes with
Fragmentation highlighted again. The prior-payload block explicitly listed seg 2 and told
the model not to repeat it. Nothing about leaching (the new half of this objective) is
added — no "minerals washed down", no soil layer, no downward arrow. The correct move here
was to keep seg 2's full six-node chain and move `active_node` to 2, or to draw leaching
itself.

---

#### n-2 · ROW15 · `decomposition-and-its-steps` seg 6 · slot `widget_archetype`
**Title:** Factors Affecting Decomposition Rate
**Objective:** "Identify the key factors that speed up or slow down decomposition."
**Params (verbatim):**
```json
{"layout": "chain", "nodes": ["Nitrogen-rich detritus", "Fast decomposition", "Lignin-rich detritus", "Slow decomposition"], "closes": false, "branch_at": -1, "active_node": -1, "caption": "Chemical nature decides decomposition speed"}
```
**Board text:** "Decomposition rate is controlled by: chemical nature of detritus, climate
(temperature & moisture), aeration (oxygen), and soil pH."

**Reason — criterion (a), with (b) alongside.** These are **two independent two-item
contrasts forced into one linear arrow chain**. Read as the chain it declares itself to be
(`layout: chain`, `branch_at: -1`), the picture says
*Nitrogen-rich detritus → Fast decomposition → Lignin-rich detritus → Slow decomposition* —
i.e. that fast decomposition produces lignin-rich detritus, which is false and is a
plausible thing for a student to memorise off a board. A contrast of two substrates is a
`comparison_table` (which is what `diag_hint` said: `comparison_table`), not a chain.
Secondarily (b): the board text names four controlling factors and the picture covers only
one of them, so the picture under-serves the objective it sits beside.

---

#### n-3 · ROW17 · `decomposition-and-its-steps` seg 8 · slot `widget_archetype` · **LOWER CONFIDENCE**
**Title:** Decomposition in the Ecosystem: Connecting the Dots
**Objective:** "Explain how decomposition links to nutrient cycles and the detritus food chain."
**Params (verbatim):**
```json
{"layout": "chain", "nodes": ["Dead leaf", "Detritivores shred", "Decomposers release nutrients", "Plants absorb nutrients"], "closes": true, "branch_at": -1, "active_node": -1, "caption": "Decomposition closes the nutrient loop"}
```
**Board text names:** "Detritus food chain (DFC): detritus -> detritivores -> predators."

**Reason — criterion (b).** Two things. First, this closed loop is the **same loop as this
subtopic's own seg 1** (`["Dead organic matter", "Decomposition", "Inorganic nutrients",
"Producers reuse"]`, also `closes: true`) with the middle step split in two — the nutrient
loop has already been drawn for this student. Second, the objective and the board both name
the **detritus food chain** (detritus → detritivores → **predators**), and the predator /
DFC limb is absent; the chain routes to "Plants absorb nutrients" instead, which is the
nutrient-cycle half that was already covered.

**Why lower confidence:** a closing "connect the dots" segment legitimately re-draws a
synthesis, and seg 1 was seven segments back and outside the four-deep prior-payload window,
so the model was not told. Raasikh may reasonably call this y. I flag it because the DFC
stage named in the objective is the part that is missing.

---

#### n-4 · ROW27 · `ecological-succession-...` seg 2 · slot `widget_archetype`
**Title:** Primary vs Secondary Succession
**Objective:** "Differentiate between primary and secondary succession based on starting conditions and speed."
**Params (verbatim):**
```json
{"layout": "chain", "nodes": ["Bare rock (no soil)", "Primary succession (slow)", "Soil forms", "Climax community"], "closes": false, "branch_at": -1, "active_node": -1, "caption": "Primary succession: soil must form first"}
```
**`diag_hint` was:** `comparison_table`

**Reason — criterion (a), with (b).** The objective is a **differentiation**, and the
picture shows **only one of the two things being differentiated**. Secondary succession —
the burned forest / abandoned farmland case, soil and seed bank already present, therefore
fast — is the half the student must hold against primary, and it is nowhere in the picture.
A one-sided chain beside a "X vs Y" objective teaches the comparison as if it had one term.
Separately (b): the chain largely restates seg 1's `Bare area → … → Climax community`
skeleton, and node 1 "Primary succession (slow)" is a *label for the whole process* sitting
in the middle of a chain of *stages*, so the chain's own grammar is inconsistent.

---

#### n-5 · ROW30 · `ecological-succession-...` seg 5 · slot `widget_archetype`
**Title:** Why Succession Moves Forward
**Objective:** "Explain the mechanism by which each seral stage modifies the habitat to favor the next community."
**Params (verbatim):**
```json
{"layout": "chain", "nodes": ["Crustose lichens", "Foliose lichens", "Mosses", "Herbs", "Shrubs", "Climax forest"], "closes": false, "branch_at": -1, "active_node": -1, "caption": "Each stage modifies habitat, enabling the next"}
```
**Prior payload block named:** segment 3 — `process_flow` `{"nodes": ["Bare rock", "Crustose lichens", "Foliose lichens", "Mosses", "Herbs", "Shrubs", "Climax forest"], ...}`

**Reason — criterion (b).** This is **seg 3's xerarch chain with the first node deleted** —
six of seven nodes identical, same order — drawn two segments later, with seg 3 sitting
right there in the prior-payload block. The objective has moved on from *what the sequence
is* to *why the sequence advances* (habitat modification: soil built, organic matter added,
shade, moisture). The mechanism is the whole point of this segment and appears nowhere in
the picture; only the caption asserts it. The picture the student sees is the one they saw
two segments ago.

---

#### n-6 · ROW32 · `ecological-succession-...` seg 7 · slot `widget_archetype`
**Title:** Exam-Style Sequencing and Traps
**Objective:** "Apply knowledge of succession to solve typical exam questions and avoid common mistakes."
**Params (verbatim):**
```json
{"layout": "chain", "nodes": ["Bare rock", "Crustose lichens", "Foliose lichens", "Mosses", "Herbs", "Shrubs", "Climax forest"], "closes": false, "branch_at": -1, "active_node": -1, "caption": "Xerarch succession: lichens first, mosses later"}
```
**Prior payload block named:** segment 3 — `process_flow` with a **byte-identical** `nodes` array.

**Reason — criterion (b). This is the cleanest repetition finding in the file.** The node
list is *identical* to seg 3's, character for character; only the caption differs. Seg 3
was explicitly listed in this segment's prior-payload block under "Do not draw one of these
again." The segment's actual teaching point is the trap named in the board note — *"mosses
are NOT pioneers on rock; only lichens can colonise bare rock"* — and the picture does not
mark, highlight or contrast anything (`active_node: -1`). Setting `active_node` to 1
(crustose lichens) would at least have made the picture do the work of the trap. As drawn,
this is the third appearance of the same seven-node ladder in one subtopic (segs 3, 5, 7).

---

#### n-7 · ROW44 · `energy-flow-and-the-ten-per-cent-law` seg 6 · slot `widget_archetype`
**Title:** Ecological Pyramids: Number, Biomass, Energy
**Objective:** "Describe the three types of ecological pyramids and identify which can be inverted."
**Decline:** `{"kind": "implicit", "reason": null}` → `emitted_instead: "text_only"`
(`diag_hint` was `labeled_axes_plot`)
**Board text emitted instead:** heading "Ecological Pyramids (Elton, 1927)"; "Graphical
representation of number, biomass, or energy at successive trophic levels, with producers at
the base."; "Three types: Pyramid of Number, Pyramid of Biomass, Pyramid of Energy."; "Pyramid
of Number: Usually upright in grassland and pond; can be inverted in a single large tree or
parasitic food chain."

**Reason — criterion (c).** An ecological pyramid **is a shape**. The board's own first line
calls it "a graphical representation", and the objective asks the student to *identify which
can be inverted* — a question that is purely about which way the shape points. This segment
asks a student to hold three stacked shapes and one flipped shape in their head from prose
alone. This is the single strongest "a student needed a picture and got none" case in the
chapter.

**Caveat for Raasikh (important):** `board_slot` here is `widget_archetype`, and the archetype
branch appears to offer no pyramid/stacked-bar widget — the hint `labeled_axes_plot` was not
routable in this slot. If that is right, this is a **routing/coverage gap, not a model
misjudgement**: the model declined because it had nothing correct to draw. Note also that the
parallel segments in the *other* two subtopics that teach pyramids (ROW21, ROW53) sit in
`svg_live` and did get a picture. That asymmetry is the finding worth acting on.

---

#### n-8 · ROW46 · `energy-flow-and-the-ten-per-cent-law` seg 8 · slot `widget_archetype` · **LOWER CONFIDENCE**
**Title:** Numerical Practice: Applying the 10% Law
**Objective:** "Solve typical exam numericals involving energy transfer across trophic levels."
**Params (verbatim):**
```json
{"layout": "chain", "nodes": ["Producers 48,000 kJ", "Herbivores 4,800 kJ", "Secondary 480 kJ"], "closes": false, "branch_at": -1, "active_node": -1, "caption": "Each arrow multiplies by 0.1"}
```
**Prior payload block named:** segment 5 (`Producers 100,000 kJ … Level 6: 1 kJ`) and
segment 4 (`Producers 10,000 kJ`, `Herbivores 1,000 kJ`, `Secondary 100 kJ`).

**Reason — criterion (b).** This is the **third identical energy ladder in one subtopic**
and structurally a carbon copy of seg 4 — same three-node shape, same producer/herbivore/
secondary labels, same ×0.1 caption; only the starting number changes (10,000 → 48,000).
Both seg 4 and seg 5 were in the prior-payload block. The arithmetic is correct, but as a
*picture* it adds nothing the student has not now seen twice; a worked numeric substitution
is what the formula event and the narration are for.

**Why lower confidence:** this is a deliberate worked-example segment, and re-using a
familiar visual frame with new numbers is a defensible teaching choice. If Raasikh accepts
that, seg 5 (ROW43) should be re-examined on the same logic — see Notes.

---

#### n-9 · ROW57 · `phosphorus-cycle` seg 2 · slot `widget_archetype`
**Title:** The Reservoir: Where Phosphorus Lives
**Objective:** "Identify the main reservoir of phosphorus and explain why the cycle is classified as sedimentary."
**Params (verbatim):**
```json
{"layout": "chain", "nodes": ["Atmosphere/Hydrosphere", "Gaseous cycle", "Earth's crust/Rocks", "Sedimentary cycle"], "closes": false, "branch_at": -1, "active_node": -1, "caption": "Reservoir location decides cycle type"}
```
**`diag_hint` was:** `comparison_table`

**Reason — criterion (a).** A **two-row classification table rendered as a four-node linear
arrow chain**. Read as the chain it declares itself to be, the board says
*Atmosphere/Hydrosphere → Gaseous cycle → Earth's crust/Rocks → Sedimentary cycle* — i.e.
that a gaseous cycle leads into the Earth's crust, which is false and is precisely the
carbon/phosphorus confusion this subtopic later calls "the biggest trap" (seg 8 board text).
The relationship being taught is *reservoir location ↦ cycle class*, a mapping of two
independent pairs, not a sequence. Same failure mode as n-2 (ROW15). The hint asked for
`comparison_table` and the archetype branch drew a chain instead.

---

#### n-10 · ROW59 · `phosphorus-cycle` seg 4 · slot `widget_archetype` · **MODERATE CONFIDENCE**
**Title:** Uptake and the Food Chain: Phosphorus in Living Systems
**Objective:** "Trace the movement of phosphorus from soil to producers **and through the food chain**."
**Params (verbatim):**
```json
{"layout": "chain", "nodes": ["Soil phosphate", "Plant roots", "ATP, DNA, membranes"], "closes": false, "branch_at": -1, "active_node": -1, "caption": "Phosphorus enters plants from soil"}
```

**Reason — criterion (b).** The objective and the segment title both name the **food chain**,
and the chain stops inside the plant. Tracing phosphorus "through the food chain" needs at
minimum a herbivore node; the drawn chain ends at the molecules phosphorus becomes, then
stops. This is a chain missing a stage explicitly named in the objective — the caption even
concedes the reduced scope ("Phosphorus enters plants from soil"). The captured board events
likewise never reach a consumer.

**Why moderate:** the drawn portion is entirely correct, and narration (not captured) may
have carried the consumer half. Also the subtopic's seg 8 summary (ROW63) does supply
"Plants & food chain" as a node, so the chapter closes the gap eventually.

---

#### n-11 · ROW61 · `phosphorus-cycle` seg 6 · slot `widget_archetype`
**Title:** The Slow Return: Sedimentation **and Geological Uplift**
**Objective:** "Describe how phosphorus is lost to sediments **and eventually returns via geological uplift**."
**Params (verbatim):**
```json
{"layout": "chain", "nodes": ["Soil phosphate", "Runoff to ocean", "Ocean sediments", "Locked for millions of years"], "closes": false, "branch_at": -1, "active_node": -1, "caption": "Phosphorus lost to sediments"}
```

**Reason — criterion (b).** The chain ends at "Locked for millions of years". **Geological
uplift — the return stage named in the segment title, named in the objective, and the only
reason this segment is called "The Slow Return" — is not in the chain, and `closes` is
false.** The picture therefore teaches that phosphorus goes to the sea floor and stays there:
a one-way loss, which is the opposite of the "slow but closed" point. Adding
`"Geological uplift"` → `"Rock phosphate"` with `closes: true` would have made the picture
say what the title says.

---

#### n-12 · ROW62 · `phosphorus-cycle` seg 7 · slot `widget_archetype`
**Title:** Phosphorus vs. Carbon: Gaseous vs. Sedimentary Cycles
**Objective:** "Compare the phosphorus cycle with the carbon cycle, highlighting key differences in speed and reservoir."
**Params (verbatim):**
```json
{"layout": "chain", "nodes": ["Carbon: atmosphere CO2", "Photosynthesis", "Respiration/Decomposition/Combustion", "Back to atmosphere"], "closes": true, "branch_at": -1, "active_node": -1, "caption": "Carbon cycle: gaseous and fast"}
```
**`diag_hint` was:** `comparison_table`

**Reason — criterion (a), with (b).** In a phosphorus-cycle subtopic, on a segment whose
whole job is the *comparison*, the board draws **the carbon cycle and only the carbon
cycle**. The phosphorus half — rock reservoir, weathering, no atmospheric phase, slow — is
absent, so the one-sided picture illustrates the term the student is *not* here to learn.
Worse, on a screen where the differentiator is "gaseous vs sedimentary", a closed
atmosphere-centred ring is the single most confusable image to leave up. This is a
comparison objective (hint: `comparison_table`) satisfied with a one-sided chain. A
side-by-side, or a phosphorus ring captioned "no atmospheric phase" (which is what seg 8
eventually draws), would have been the right call.

---

### OUT-OF-SHEET (5) — `svg_live` / `svg_precomputed` rows. **No row exists in the committed 40-row sheet for these; there is nothing to fill in. Recorded for the record only.**

---

#### n-13 · ROW21 · `ecological-pyramids-and-their-limitations` seg 4 · slot `svg_live` · **OUT OF SHEET**
**Title:** Ecological Pyramids: Number, Biomass, and Energy
**Objective:** "Define the three types of ecological pyramids and describe their typical shapes in different ecosystems."
**Emitted (verbatim, named template — the archetype widget did not fire):**
```json
{"template": "labeled_axes_plot", "params": {"x_label": "Trophic level", "y_label": "Quantity", "curve_points": [[1, 100], [2, 50], [3, 25]], "title": "Ecological Pyramid (Number/Biomass/Energy)"}, "caption": "Quantity decreases at higher trophic levels"}
```

**Reason — criterion (b).** The curve **halves** at each trophic level (100 → 50 → 25). This
same subtopic teaches the 10% law one segment earlier (ROW20: 48,000 → 4,800 → 480, "Each
arrow = 10% transfer"), so the plotted numbers contradict the chapter's own arithmetic by an
order of magnitude, on the axis a student will read off. Separately, one monotonically
falling curve titled "Number/Biomass/Energy" cannot deliver the objective, which asks for
**three** pyramid types and their **typical shapes in different ecosystems** — the shapes are
what distinguishes them, and inversion (taught in the very next segment) is invisible on a
single decreasing line.

---

#### n-14 · ROW49 · `food-chains-food-webs-and-trophic-levels` seg 3 · slot `svg_precomputed` · **OUT OF SHEET**
**Title:** Trophic Levels and the 10% Law
**Objective:** "Define trophic level and apply Lindeman's 10% law to calculate energy transfer between levels."
**Emitted (verbatim):**
```json
{"template": "labeled_axes_plot", "params": {"x_label": "Trophic Level", "y_label": "Energy (kJ)", "curve_points": [[1, 100], [2, 10], [3, 1], [4, 0.1]], "title": "Energy decreases by 10% at each trophic level"}, "caption": "Energy drops by a factor of 10 at each step"}
```

**Reason — criterion (b).** The **title is factually wrong**: energy decreases *to* 10% (i.e.
*by* 90%), not *by* 10%. The plotted points (100 → 10 → 1 → 0.1) and the caption ("drops by a
factor of 10") are both correct, so the title contradicts the data it labels, on the same
image. This is not a pedantic point — "10% is transferred / 90% is lost" versus "10% is lost"
is a standard NEET distractor, and ROW25 in this very chapter lists PAR-vs-capture confusion
as an exam trap of exactly this family. A title is the line a student copies.

---

#### n-15 · ROW52 · `food-chains-food-webs-and-trophic-levels` seg 6 · slot `svg_live` · **OUT OF SHEET**
**Title:** Food Webs: Interconnected Chains
**Objective:** "Explain how food chains interconnect to form food webs and why food webs are more realistic."
**Decline:** no explicit decline object; `non_fire_reason: "model_chose_no_widget"`,
`emitted_instead: "text_only"`, `svg_source: null`
**Board text emitted instead:** "A food web is a network of interconnected food chains in an
ecosystem."; "Real ecosystems are not simple linear chains; organisms often feed at multiple
trophic levels."

**Reason — criterion (c).** A food web is defined by its **branching**, and the board's own
text asserts the contrast — *not simple linear chains*, *feed at multiple trophic levels* —
without ever showing it. The concept is one the student cannot form from prose: "network of
interconnected chains" only means something once two chains are seen crossing. This slot is
`svg_live`, so a live SVG *was* available (five other segments in this same subtopic got
one) and the model chose nothing. Of the nine genuine text-only segments in the file, this
and ROW44 are the two where the missing picture is the concept itself.

---

#### n-16 · ROW55 · `food-chains-food-webs-and-trophic-levels` seg 9 · slot `svg_precomputed` · **OUT OF SHEET**
**Title:** Putting It All Together: Chains, Webs, and Pyramids
**Objective:** "Apply concepts of food chains, webs, trophic levels, and pyramids to solve typical exam questions."
**Emitted (verbatim):**
```json
{"template": "comparison_table", "params": {"headers": ["Trophic Level", "Energy (kJ)"], "rows": [["Producers (1st)", "48,000"], ["Herbivores (2nd)", "4,800"], ["Secondary consumers (3rd)", "480"]], "title": "10% Law Example"}, "caption": "Energy halves at each step"}
```

**Reason — criterion (b).** The **caption flatly contradicts the table it captions.** The rows
show a tenfold drop (48,000 → 4,800 → 480); the caption reads *"Energy halves at each step."*
On a revision/exam-application segment, a caption is the sentence a student memorises, and
this one states a wrong transfer ratio directly beneath the correct numbers. Cheap, isolated,
unambiguous fix — but as shipped it is a factual error on the board.

---

#### n-17 · ROW68 · `productivity-gpp-npp-and-secondary-productivity` seg 5 · slot `svg_live` · **OUT OF SHEET**
**Title:** Units and Measurement of Productivity
**Objective:** "State the units of productivity and explain **why dry mass is used** for measurement."
**Emitted (verbatim):**
```json
{"template": "comparison_table", "params": {"headers": ["Quantity", "Has per area per time?", "Example"], "rows": [["Productivity", "Yes", "10 g m⁻² yr⁻¹"], ["Standing crop", "No", "5000 g"]], "title": "Productivity vs Standing Crop"}, "caption": "Productivity is a rate; standing crop is a stock."}
```
**Already drawn, same subtopic seg 1 (ROW64):**
```json
{"template": "comparison_table", "params": {"headers": ["Quantity", "Meaning", "Example"], "rows": [["Productivity", "Rate of biomass production per area per time", "10 kg per hectare per year"], ["Standing crop", "Biomass present at a given time", "5000 kg in the forest"]], "title": "Productivity vs Standing Crop"}, "caption": "Productivity is a rate; standing crop is an amount."}
```

**Reason — criterion (b).** **Same template, same title string, same two row labels, same
contrast, near-identical caption** — the productivity-vs-standing-crop table is drawn twice in
one subtopic, four segments apart. Meanwhile this segment's distinctive content — *why dry
mass rather than fresh weight* (water content varies, so fresh-weight comparisons are
distorted) — is not in the table at all.

**Structural note that partly excuses the model:** `prior_payload_block` is **empty (`""`)
for every one of the 30 svg-slot rows**, including this one. The "do not draw one of these
again" repetition guard that the archetype branch receives is **not being fed to the svg
branch**, so on this row the model was never told seg 1's table existed. See Notes — this is
a wiring finding, not just a content finding.

## Notes and uncertainties

### 1. No narration was captured. (Restating, because it bounds everything above.)
Judgements rest on `segment_objective`, `segment_title`, `model_raw_board_events`, `params`
and `prior_payload_block` only. Several findings — n-3, n-8, n-10 especially — could flip to
y if the narration is carrying the part the picture omits. Raasikh should treat those three
as "look at the transcript before deciding".

### 2. The systematic pattern: **repetition of a chain the student has already seen.** 7 of 17 findings.
n-1, n-3, n-5, n-6, n-8, n-17, plus the near-misses below. Its clearest form is the succession
subtopic, where the seven-node xerarch ladder is drawn **three times** in one session:

| seg | nodes | verdict |
|---|---|---|
| 3 (ROW28) | Bare rock, Crustose, Foliose, Mosses, Herbs, Shrubs, Climax forest | y — first, correct, canonical |
| 5 (ROW30) | Crustose, Foliose, Mosses, Herbs, Shrubs, Climax forest | **n** — same minus node 0 |
| 7 (ROW32) | Bare rock, Crustose, Foliose, Mosses, Herbs, Shrubs, Climax forest | **n** — byte-identical to seg 3 |

Second clearest: the **10% energy ladder** in `energy-flow`, drawn at seg 4, seg 5 and seg 8
(ROW42/43/46) — same shape, only the numbers change. I flagged only the third (n-8) and left
seg 5 (ROW43) as y because extending the ladder to level 6 is what makes the "why chains are
short" point. **If Raasikh rejects that reasoning, ROW43 should flip to n on the same grounds
and the count becomes 52 y / 18 n.** I did not flag ROW42 under any reading: it is the first
ladder.

**The repetition guard is working, but only as a suggestion.** In every archetype-slot case
above, the offending prior chain was *sitting in that segment's own `prior_payload_block`*
under "Do not draw one of these again", and the model drew it anyway. So the finding is not
"the model was not told" — it is "telling it in the prompt is not enough". The obvious
mitigation is server-side: reject or force-mutate a payload whose normalised `nodes` array
overlaps a prior payload's above some threshold (byte-identical, as in ROW32, is trivially
detectable).

### 3. Wiring finding: the repetition guard never reaches the svg branch.
`prior_payload_block == ""` on **all 30** `svg_live` / `svg_precomputed` rows, including
segments 5–9 of subtopics where 4–8 pictures had already been drawn. The archetype branch
gets the "already drawn" block; the svg branch does not. n-17 is a direct consequence. This
is worth checking in the routing code independent of any verdict on this chapter.

### 4. Second systematic pattern: **a comparison forced into a `chain`.** 4 of 17 findings.
n-2 (ROW15), n-4 (ROW27), n-9 (ROW57), n-12 (ROW62). In all four, `diag_hint` was
`comparison_table` (n-4, n-9, n-12) or the content was plainly a contrast (n-2), and the
archetype branch emitted `process_flow` with `layout: "chain"`, `branch_at: -1`. Two of them
(n-2, n-9) produce a board that asserts something false when read left-to-right. **The
archetype route appears to fire `process_flow` regardless of what the hint asked for:** across
all 40 archetype rows, every single fire is `process_flow` (35/35), including 13 rows whose
`diag_hint` was `comparison_table`, 1 `labeled_axes_plot`, 1 `vector_resolution` and 1
`boxed_derivation`. If `process_flow` is genuinely the only widget the archetype branch can
route in this chapter, then n-2/n-4/n-9/n-12 are **coverage gaps, not model errors**, and the
fix is a routable comparison widget rather than a prompt change. Raasikh should confirm which
before marking those four.

### 5. Note on `diag_hint: "vector_resolution"` at ROW26 (succession seg 1).
A physics archetype hint appearing on a biology segment. It did not cause harm — the model
drew a correct succession chain — so ROW26 stays y. Flagging it only because a physics hint
leaking into a biology plan suggests the hint source is not chapter-scoped.

### 6. Criterion (c) was applied narrowly, on purpose.
Only 9 of 70 segments are true declines. The other 26 non-firing segments emitted an SVG, so a
picture reached the board and (c) cannot apply. Of the 9 true declines, I flagged 2 (ROW44
pyramids, ROW52 food webs) and passed 7 — carbon seg 1 (why carbon matters), carbon seg 2
(reservoirs), carbon seg 9 (exam edge), pyramids seg 6 (limitations list), energy seg 7
(blind-spots list), productivity seg 2 (GPP definition), productivity seg 4 (secondary
productivity). All seven are definitions, lists or trap-recall, where prose is the right
medium and a forced chain would have been the worse call. **The decline behaviour in this
chapter is mostly healthy; the problems are in what gets drawn, not in what gets skipped.**

### 7. Things I looked at and deliberately did **not** flag (so the human can disagree cheaply).
- **ROW5** carbon seg 5 — objective says decomposers return carbon "to the atmosphere **and
  soil**"; chain ends at atmosphere. Partial, but the drawn chain is correct.
- **ROW6** carbon seg 6 — objective names **deforestation**; the chain (and the board text)
  cover only fossil-fuel combustion.
- **ROW14** decomposition seg 5 — humification/mineralisation contrast drawn as a chain. Left
  as y because humification *does* precede mineralisation, so the sequence is real, unlike n-2
  and n-9 where it is not.
- **ROW16** decomposition seg 7 — detritivores-vs-decomposers drawn as a chain. Left as y
  because the chain (fragment, then enzymes, then nutrients) is a true division-of-labour
  sequence, not a false one.
- **ROW29** succession seg 4 — hydrarch chain omits marsh-meadow and scrub stages. Order of
  what is shown is correct; NCERT-abbreviated rather than wrong.
- **ROW31** succession seg 6 — convergence drawn with `branch_at: 1` on nodes
  `["Hydrarch: pond", "Xerarch: bare rock", "Habitat modification", "Mesic climax forest"]`.
  The intent is a **merge** (two starts, one climax); `branch_at` reads like a **fork**. If the
  renderer draws a fork after node 1, this picture says the opposite of the objective and
  should be **n (b)**. **I could not verify the renderer, so I left it y — this is the single
  verdict most likely to be wrong, and it is in-sheet.**
- **ROW18** pyramids seg 1 — objective demands the first and second laws of thermodynamics; the
  money-vs-energy table contains no thermodynamics. Analogy is sound, so y.
- **ROW19** pyramids seg 2 — caption "Energy descending staircase" does not describe the
  three-stage flow it captions, and the 2–10% capture figure named in the objective is absent
  (contrast ROW48, which includes it). Weak; left y.
- **ROW40** energy seg 2, **ROW41** energy seg 3, **ROW56** phosphorus seg 1, **ROW60**
  phosphorus seg 5 (phosphate-solubilising bacteria named in the title, absent from the chain),
  **ROW24** / **ROW51** (GFC-vs-DFC tables omitting the terrestrial/aquatic dominance the
  objective asks for) — all partial-coverage cases where the drawn content is correct. I drew
  the line at: **flag when the drawn chain is wrong, misleading, or a duplicate; note when it is
  correct but partial** — with an exception for pure "X vs Y" objectives drawn one-sided
  (n-4, n-9, n-12), where the missing half *is* the lesson.
- **ROW38** eco-structure seg 6 — pond components table pairs `Water|Producers`,
  `Light|Consumers`, `Temperature|Decomposers` row-wise, implying correspondences that do not
  exist. Two independent lists in two columns is a common, generally harmless convention. y.
