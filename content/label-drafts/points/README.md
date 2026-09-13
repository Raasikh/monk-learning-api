# Pointing inputs — bio11 ch7

One file per sub-figure. These are the **inputs** to
`scripts/draft_anchors_pointed.py`, kept because they are the only record of
where a normalised (x, y) came from and what it was meant to name. The
`.pointed.json` drafts are generated from them and can be regenerated at any
time; these cannot.

    python3 scripts/draft_anchors_pointed.py \
        --set <asset_slug> --in content/label-drafts/points/<name>.json \
        --source claude-pointed --allow-unplaced

`--allow-unplaced` is correct for every ch7 set and not a shortcut: all 22 were
drafted by `scripts/draft_labels.py` (gpt-4o), where `unplaced` means "the
model could not find it", which is precisely what pointing exists to fix. It
would be wrong on an SVG-authored draft, where `unplaced` means "there is no
leader for it in the drawing" — i.e. it is on another sub-figure.

## Shape

    {"groups": [{"id": "foregut", "label": "Mouth and foregut"}],
     "points": [{"term": "pharynx", "x": 0.25, "y": 0.5,
                 "confidence": 0.85, "group": "foregut"}]}

`x`/`y` are fractions of the MASTER, origin top-left. `term` must appear in the
concept's `ncert_labels`; a term not listed under `points` is written to
`unplaced` rather than kept, because these drafts carry every term of the
CONCEPT on every one of its sub-figures with placeholder anchors like
(0.3, 0.3), and keeping one would hand the board a round number nobody
measured as though it were a located structure.

## Groups are not cosmetic

A figure drawn with more labels than fit is not crowded, it is WRONG — pills
land on each other and on the structures they name. Five per group is the
enforced ceiling, but it is a ceiling and not a target: the measured limit at
the narrow frames is label WIDTH, not count. See the C1 report.
