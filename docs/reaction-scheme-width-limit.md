# `reaction_scheme` — the width constraint, measured

Eight chemistry segments have no stored payload because no `reaction_scheme`
payload can be authored for them at a phone board's width. This file records
the measurement so the next person does not re-derive it, and does not mistake
it for an authoring failure.

**Nothing is built against this file.** It is the record of a limit.

## The eight

All in chem 12 "Aldehydes, Ketones & Carboxylic Acids", all multi-species
organic mechanisms:

| subtopic | seg | refused because |
|---|---|---|
| `reactions-of-carboxylic-acids` | 2 | 7 species share one stage; at most 5 fit at 343x236 |
| `nucleophilic-addition-reactions-of-aldehydes-and-ketones` | 5 | needs 457.7pt of width, 319pt usable |
| `nucleophilic-addition-reactions-of-aldehydes-and-ketones` | 6 | needs 677.7pt of width, 319pt usable |
| `aldol-condensation` | 5 | labels over 20 chars; the width budget cannot hold more |
| `aldol-condensation` | 6 | needs 422.9pt of width, 319pt usable |
| `aldol-condensation` | 7 | labels over 20 chars |
| `aldol-condensation` | 8 | `step_reagent[1]` over 20 chars |
| `oxidation-and-reduction-of-aldehydes-and-ketones` | 7 | two reagents over 20 chars |

Each was re-authored twice — once fresh against the corrected spec, once more
with the renderer's measured refusal handed back. On `aldol-condensation` seg 5
the author, shown the measurement, **declined** rather than truncate, which is
the spec working as intended.

## The measurement

At the 343x236 board, after the board's own padding, **319pt of width is
usable**. A scheme's width is:

    sum(chipW(label)) + (species - 1) * GAP_MIN
    chipW(L) = 6.96L + 12          GAP_MIN  = 21 + ARROW_LEN

which gives the real ceiling:

| species in one stage | longest label that fits |
|---|---|
| 2 | 12 characters |
| 3 | 7 characters |
| 4 | 5 characters |
| 5+ | does not fit at any length |

## Why the character cap is not the limit

The caps were raised **10 -> 20 (species) and 12 -> 20 (reagent)** on
2026-09-12. The estimate before the change was that ~8 stored payloads would
start rendering. The measured effect was **2** — 16/38 to 18/38.

The estimate was wrong because it checked only the character cap. The real gate
is `fitProblems`' width and collision check, and a 20-character species name
still does not fit in a 3-species scheme. **The cap is a cheap pre-filter in
front of the real check, and treating it as the rule over-promises by 4x.**

## What would recover these eight

Not a bigger cap. Three options, in the order they are worth considering:

1. **A wider board for chemistry.** 702x289 is already a `GATE_FRAME` and gives
   ~660pt usable, which clears every one of the eight. The question is whether
   a mechanism is allowed to be a landscape-only figure. This is a product
   decision, not an engineering one.
2. **A `stages` param** that splits one scheme across two or three rows, the way
   a textbook wraps a long mechanism. Roughly doubles the drawable species count
   at 343pt and needs no new widget — but it is a real layout change to a widget
   that currently assumes one row.
3. **Condensed structural formulae as a first-class label type**, so `enolate`
   and `CH3CHO` can sit in a chip that renders subscripts properly and costs
   fewer points per character than the 6.96pt/char the plain face uses.

Option 1 costs nothing to try and would be measured in an afternoon. Options 2
and 3 are builds and should not start before someone has ruled on 1.

## What this is NOT

It is not a reason to lower the bar. A truncated species label teaches a wrong
formula, and a scheme drawn wider than the board clips silently on a real
phone. The eight segments currently resolve down the precedence chain to an
authored SVG, which is a picture a student can read. **That is the correct
outcome, not a gap** — the gap is only that the widget cannot be the thing
drawing it.
