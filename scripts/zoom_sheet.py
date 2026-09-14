#!/usr/bin/env python3
"""A 6x crop of the master at every anchor, gridded, so a miss is visible.

    python3 scripts/zoom_sheet.py --chapter bio11-ch6

WHY THIS EXISTS. The contact sheet shows where a label SITS; it cannot show
whether the anchor is on the structure. Measured 2026-09-13: the blood plate's
`platelet` pointed at open plasma and three separate looks at the 343x236 board
missed it, because the leader dot is physically wider than a platelet. Only a
6x crop of the master settled it — and the same crop CLEARED `plasma`, which
looked wrong on the board and was fine.

So this is the review surface. One cell per anchor: the master around the
point, a crosshair on the exact coordinate, and the term with its confidence.
Paged, because a chapter of 125 anchors in one image is an image nobody can
read — a sheet too big to look at is the same failure as no sheet.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from PIL import Image, ImageDraw

API = Path(__file__).resolve().parent.parent
MOB = Path("/Users/raasikhnaveed/Desktop/monk-learning-mobile/monklearning-mobile")
MASTERS = MOB / "content/illustrations/v1/masters"
DRAFTS = API / "content/label-drafts"
REPORTS = MOB / "content/illustrations/v1/reports/pointed"

#: A 60-px window at 6x. The FIRST version of this file set R=45 and then
#: wrote `CELL = R * 2 * SCALE // 2`, which is 3x — the sheet said "6x" in its
#: own header and delivered half that. Caught by checking the arithmetic
#: against the number that mattered: the platelet needed 6x to settle, so a
#: sheet quietly giving 3x is a sheet that can miss what it was built to catch.
R = 30              # half-window in MASTER pixels -> a 60px window
SCALE = 6           # the magnification the platelet needed, actually applied
CELL = R * 2 * SCALE        # 360px cell
CAPTION_H = 34
COLS, ROWS = 4, 4   # 16 per page: ~1.5k x 1.6k, which displays near 1:1


def anchors_for(slug: str) -> List[Dict[str, Any]]:
    for name in (f"{slug}.pointed.json", f"{slug}.draft.json"):
        p = DRAFTS / name
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        out = []
        for l in d.get("labels") or []:
            a = l.get("anchor")
            if not a:
                continue
            out.append({"term": (l.get("text") or {}).get("en") or l.get("id"),
                        "u": float(a[0]), "v": float(a[1]),
                        "conf": (l.get("_point") or {}).get("confidence")})
        return out
    return []


def cell(master: Image.Image, u: float, v: float) -> Image.Image:
    W, H = master.size
    cx, cy = int(u * W), int(v * H)
    box = (cx - R, cy - R, cx + R, cy + R)
    # Crop with a white pad rather than clamping: a clamped window silently
    # re-centres, and then the crosshair is no longer on the anchor.
    crop = Image.new("RGB", (R * 2, R * 2), (255, 255, 255))
    src = master.crop((max(0, box[0]), max(0, box[1]),
                       min(W, box[2]), min(H, box[3])))
    crop.paste(src, (max(0, -box[0]), max(0, -box[1])))
    big = crop.resize((CELL, CELL), Image.LANCZOS)
    d = ImageDraw.Draw(big)
    c = CELL // 2
    d.line([(c - 22, c), (c - 7, c)], fill=(255, 0, 255), width=3)
    d.line([(c + 7, c), (c + 22, c)], fill=(255, 0, 255), width=3)
    d.line([(c, c - 22), (c, c - 7)], fill=(255, 0, 255), width=3)
    d.line([(c, c + 7), (c, c + 22)], fill=(255, 0, 255), width=3)
    d.ellipse([c - 5, c - 5, c + 5, c + 5], outline=(255, 0, 255), width=2)
    return big


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", required=True, help="e.g. bio11-ch6")
    args = ap.parse_args()

    slugs = sorted(p.name.replace(".pointed.json", "")
                   for p in DRAFTS.glob(f"{args.chapter}-*.pointed.json"))
    if args.chapter == "bio11-ch7":
        slugs = sorted(set(slugs) | {p.name.replace(".draft.json", "")
                       for p in DRAFTS.glob(f"{args.chapter}-*.draft.json")
                       if (DRAFTS / p.name.replace(".draft.json", ".pointed.json")).exists()
                       is False})
    items = []
    for s in slugs:
        m = MASTERS / f"{s}.png"
        if not m.exists():
            continue
        master = Image.open(m).convert("RGB")
        for a in anchors_for(s):
            items.append((s, master, a))

    out_dir = REPORTS / args.chapter
    out_dir.mkdir(parents=True, exist_ok=True)
    per = COLS * ROWS
    pages = -(-len(items) // per) or 1
    written = []
    for pg in range(pages):
        chunk = items[pg * per:(pg + 1) * per]
        W = COLS * CELL + (COLS + 1) * 10
        H = ROWS * (CELL + CAPTION_H) + (ROWS + 1) * 10 + 28
        sheet = Image.new("RGB", (W, H), (250, 249, 245))
        d = ImageDraw.Draw(sheet)
        d.text((10, 9), f"{args.chapter} - anchor zoom {SCALE}x - page {pg+1}/{pages} "
                        f"- {len(items)} anchors in the chapter - judge the CROSSHAIR, "
                        f"not the label", fill=(40, 38, 34))
        for i, (slug, master, a) in enumerate(chunk):
            x = 10 + (i % COLS) * (CELL + 10)
            y = 28 + 10 + (i // COLS) * (CELL + CAPTION_H + 10)
            sheet.paste(cell(master, a["u"], a["v"]), (x, y))
            d.rectangle([x, y, x + CELL, y + CELL], outline=(205, 198, 186), width=1)
            conf = "" if a["conf"] is None else f"  {a['conf']:.2f}"
            d.text((x + 2, y + CELL + 4), f"{a['term']}{conf}", fill=(30, 28, 24))
            d.text((x + 2, y + CELL + 18), slug.replace(f"{args.chapter}-", "")[:40],
                   fill=(130, 124, 114))
        name = "_zoom-sheet.png" if pages == 1 else f"_zoom-sheet-{pg+1}.png"
        sheet.save(out_dir / name)
        written.append(out_dir / name)
    print(f"{args.chapter}: {len(items)} anchors -> {len(written)} page(s)")
    for w in written:
        print(f"  {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
