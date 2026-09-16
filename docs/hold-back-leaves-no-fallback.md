# The hold-back leaves 34 segments with nothing behind them

Found by H5 on 2026-09-15, after the gate moved to resolution time. **Not yet
fixed** — the fix changes `planner_code_sha` and the 29-chapter sweep was still
running, so it waits.

## The measurement

chem 12 "Aldehydes, Ketones & Carboxylic Acids", swept under the new code, 111
segments:

| | count |
|---|---|
| stored widget payload | 38 |
| stored example SVG | 27 |
| both | 4 |
| neither | 50 |
| **payload but NO SVG behind it** | **34** |

The chapter is held at 83.2%, so those 34 resolve **past** the widget to
`svg_live` — and `svg_live` has nothing stored to fall back on. The board is
not blank, because the live path authors an SVG per turn, but it is authored at
latency on every turn and only if that call succeeds.

## Why it happens

`_attach_segment_board` force-authors a tier-3 SVG only when slot 1 failed:

```python
status = _attach_widget_payload(...)
_attach_example_diagram(segment, subject, sub_title)
if status in ("declined", "rejected", "error") and not segment.get("example_diagram_svg"):
    _attach_example_diagram(segment, subject, sub_title, force=True)
```

That condition was written when **slot 1 stored implied slot 1 shown**. It was
true for as long as the only reason a widget did not appear was that it was
never authored.

The resolution-time hold-back breaks the implication. Authoring now succeeds
for every eligible row — that is the whole of Raasikh's option (a) — while the
*showing* is decided later, per turn, from the chapter's SANE verdict. So a
held chapter now produces the one state the fallback was never written for:
**slot 1 stored, slot 1 withheld, and nothing authored underneath.**

## Why the previous placement hid it

Under the planner-side gate the status was `held_back`, which is not in that
tuple either — so it did not force an SVG. But it also stored no payload, so
the segment looked like a concept with no widget at all and fell through the
ordinary way. The bug existed and was invisible. Moving the gate did not create
it; it made it measurable.

## The fix

Add the held case to the condition, so a chapter that cannot show its widget
still has something stored:

```python
if (status in ("declined", "rejected", "error") or not widget_will_resolve) \
        and not segment.get("example_diagram_svg"):
    _attach_example_diagram(segment, subject, sub_title, force=True)
```

`widget_will_resolve` is the chapter's verdict — the same call
`resolve_board_slot` makes, read once per chapter rather than per segment.

Two things to get right when it is written:

* **It must not delete or replace a stored payload.** The payload stays; this
  only adds a picture underneath it. When the chapter's verdict clears, the
  widget resolves again and the SVG goes back to being the fallback it always
  was.
* **It costs a diagram_author call per held segment.** On chem alone that is 34.
  Worth measuring before running it corpus-wide, and worth asking whether a
  held chapter should pay for a fallback it will stop needing the moment a
  reviewer raises it.

## What it does not change

Nothing about the 50 segments that have neither a payload nor an SVG. Those
resolved to `svg_live` before any of this and still do; they are segments the
author declined on, which is a different question.
