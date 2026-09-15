#!/usr/bin/env python3
"""Compose the per-chapter review page from the extracted rows + rendered SVGs.

    python3 scripts/sane_review_page.py

One PNG per chapter under
<mobile>/content/illustrations/v1/reports/sane/<chapter>.png, each row showing
the objective, the widget, the render at 343x236, and the proposal's reason.
Rows with no stored payload show WHY there is nothing to look at rather than an
empty box — a decline and a missing render are different facts.
"""
from __future__ import annotations

import json
import re
import textwrap
from io import BytesIO
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw, ImageFont

MOB = Path("/Users/raasikhnaveed/Desktop/monk-learning-mobile/monklearning-mobile")
OUT = MOB / "content/illustrations/v1/reports/sane"
SVGS = Path("/tmp/sane-review-svgs")
META = Path("/tmp/sane-review-meta.json")

W = 1500
PAD = 26
BOARD_W, BOARD_H = 514, 354          # 343x236 at 1.5x, legible on a laptop
ROW_H = BOARD_H + 34
F = "/System/Library/Fonts/Supplemental/Arial.ttf"
FB = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
INK, MUTED, RULE, FAIL = (21, 25, 28), (97, 108, 118), (198, 206, 211), (154, 43, 43)


def font(sz, bold=False):
    return ImageFont.truetype(FB if bold else F, sz)


def wrap(d, text, fnt, width, max_lines):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=fnt) <= width:
            cur = t
        else:
            lines.append(cur); cur = w
            if len(lines) == max_lines:
                return lines[:-1] + [lines[-1][:60] + "…"]
    if cur:
        lines.append(cur)
    return lines[:max_lines]


def main() -> int:
    meta = json.loads(META.read_text())
    by_chapter = {}
    for m in meta:
        by_chapter.setdefault(m["chapter"], []).append(m)
    OUT.mkdir(parents=True, exist_ok=True)

    for chapter, rows in by_chapter.items():
        # A row with no render does not need the height of one. Two thirds of
        # these rows declined — a fixed row height made every page mostly white
        # space, which is its own way of not being read.
        def row_h(r):
            return ROW_H if r["has_payload"] else 150
        h = PAD * 2 + 100 + sum(row_h(r) for r in rows)
        img = Image.new("RGB", (W, h), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((PAD, PAD), chapter, font=font(30, True), fill=INK)
        drawn = sum(1 for r in rows if r["has_payload"])
        d.text((PAD, PAD + 42),
               f"{len(rows)} rows proposed n — the only rows that need a judgement. "
               f"{drawn} have a stored payload rendered below at 343x236.",
               font=font(15), fill=MUTED)
        need = {"Electric Charges and Fields": "2 more y", "Ecosystem": "7 more y"}.get(chapter)
        d.text((PAD, PAD + 64),
               "Write y or n beside each. A chapter clears the hold-back at 85%."
               + (f"  This one needs {need}." if need else ""),
               font=font(15), fill=INK if need else MUTED)
        if chapter == "Ecosystem":
            d.text((PAD, PAD + 84),
                   "The bio sheet groups its reasons rather than writing one per row, so the "
                   "criterion letter is all that exists here.",
                   font=font(13), fill=MUTED)
        y = PAD + 100
        for i, r in enumerate(rows, 1):
            d.line([(PAD, y), (W - PAD, y)], fill=RULE, width=1)
            ty = y + 12
            d.text((PAD, ty), f"{i}.  {r['key']}  seg {r['seg']}", font=font(16, True), fill=INK)
            ty += 24
            d.text((PAD, ty), f"widget: {r['widget_stored'] or r['widget_sheet']}",
                   font=font(14), fill=MUTED)
            ty += 22
            tw = W - PAD * 2 - BOARD_W - 30
            for line in wrap(d, r["objective"] or "(objective not found in the plan)",
                             font(15), tw, 4):
                d.text((PAD, ty), line, font=font(15), fill=INK); ty += 20
            ty += 8
            d.text((PAD, ty), "reason for n:", font=font(13, True), fill=FAIL); ty += 18
            for line in wrap(d, r["reason"], font(14), tw, 4):
                d.text((PAD, ty), line, font=font(14), fill=FAIL); ty += 18

            bx = W - PAD - BOARD_W
            svg = SVGS / f"{r['id']}.svg"
            if svg.exists():
                png = cairosvg.svg2png(url=str(svg), output_width=BOARD_W,
                                       output_height=BOARD_H)
                img.paste(Image.open(BytesIO(png)).convert("RGB"), (bx, y + 12))
                d.rectangle([bx, y + 12, bx + BOARD_W, y + 12 + BOARD_H],
                            outline=RULE, width=1)
            else:
                # The box has to match the COMPACT row height or it bleeds into
                # the row below and the page reads as one run-on column.
                bh = row_h(r) - 24
                d.rectangle([bx, y + 12, bx + BOARD_W, y + 12 + bh],
                            outline=RULE, width=1)
                why = ("no widget payload stored — this row declined and fell to an "
                       "SVG or to text, so there is no widget picture to judge")
                yy = y + 12 + max(bh // 2 - 20, 8)
                for line in wrap(d, why, font(14), BOARD_W - 30, 3):
                    d.text((bx + 15, yy), line, font=font(14), fill=MUTED); yy += 19
            y += row_h(r)
        p = OUT / f"{chapter.replace('/', '-')}.png"
        img.save(p)
        print(f"  {len(rows):>3} rows  {drawn:>2} rendered  -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
