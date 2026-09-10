# W4 — tier-3 layout post-pass (residue report, 2026-09-10)

The directive's premise ("pass rate is 50%, every remaining failure is
layout") was stale by the time W4 ran: the post-pass already existed, was
already wired, and already clears the target. This report is the measurement,
not a build.

## What exists

- `repair_layout()` in app/drona/diagram_author.py: deterministic repair of
  the layout failures validate() can see (strayed labels clamped, overlaps
  nudged, labels-on-fill lifted, font-family stripped). A PARTIAL repair is
  discarded and the original returned, so validate() fails on the real reason
  rather than passing a layout that is merely differently broken. A diagram
  with no labels at all is its own reported category — "0 overlaps" on
  nothing to overlap is a pass that tells you nothing.
- Wired at the ONE place every authored SVG passes (immediately after
  `_strip_fence`, inside author_diagram's attempt loop) — production and the
  scorer measure the same path.
- `validate()` starts with a real `ET.fromstring` parse — E.1's strict-XML
  rule was already applied on this side; "not well-formed XML: line N" is a
  named refusal class, and the frozen samples show the retry loop fixes it
  (the model corrects its own syntax when told the line).
- 8 unit tests cover the repair, including partial-discard and the
  no-labels category.

## The frozen-sample measurement (scripts/measure_tier3_layout.py --score)

Two 10-concept x 2-attempt samples captured 2026-09-05, scored offline over
identical bytes — the only difference between arms is the post-pass:

    t3_bio     raw 12/20 (60%) -> +fence-strip 15/20 -> +post-pass 20/20 (100%)
    t3_mixed   raw 14/20 (70%) -> +fence-strip 16/20 -> +post-pass 20/20 (100%)

Failure classes before, all repaired, none resisted:
    bio    malformed XML 4, overlapping labels 3, labels-on-fill 1
    mixed  overlapping labels 4, malformed XML 2

New failures introduced by the post-pass: 0 (asserted by the scorer).
Unrepairable: 0. Unlabelled diagrams: 0. Truncations: 0.

## Residue by cause

Empty, on this sample. Target was >=85% per attempt; measured 100% on both
samples. Caveats stated rather than hidden: 40 attempts, one model, one day,
temperature 0.2 — the per-concept number (which retries) was already 90/100%
before the post-pass, so the per-attempt arm is where the 40-percentage-point
gain lives, and it is the arm that halves authoring latency and cost.
