#!/usr/bin/env python3
"""Which anchors sit on BACKGROUND when they should sit on a structure?

    python3 scripts/anchor_audit.py                 # every chapter
    python3 scripts/anchor_audit.py --chapter bio11-ch2

THE FAILURE THIS FINDS, and the one it must not "fix". The blood plate's
`platelet` pointed at open plasma a few pixels from the fragment; ch2's
`sporangiophore` points at white paper beside the stalk. That class — anchor on
background, ink a short hop away — is mechanical and can be found by looking at
pixels instead of at 687 crops.

The class it must NOT touch is the opposite: terms whose referent IS the empty
space. `plasma`, `matrix`, `haemocoel`, `lumen`, `intercellular space`,
`gastrovascular cavity` are correct precisely when they sit on background, and
an audit that "corrected" them would be introducing the very error it claims to
remove. Those are listed and skipped by name.

So this REPORTS and PROPOSES. It never rewrites a points file: a proposal that
moved an anchor onto the nearest ink would be right for a spore and wrong for a
septum, and only a person looking at the crop can tell which.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image

API = Path(__file__).resolve().parent.parent
MOB = Path("/Users/raasikhnaveed/Desktop/monk-learning-mobile/monklearning-mobile")
MASTERS = MOB / "content/illustrations/v1/masters"
DRAFTS = API / "content/label-drafts"

#: Terms whose referent IS the background. Pointing them at ink would be the
#: error. Matched case-insensitively on the whole term.
SPACE_TERMS = {
    "plasma", "matrix", "haemocoel", "lumen", "intercellular space",
    "gastrovascular cavity", "spongocoel", "air cavity", "pleural fluid",
    "ground tissue", "cortex", "medulla", "pith", "conjunctive tissue",
    "fat droplet", "fourth ventricle", "cerebral aqueduct", "central disc",
    "haemocoel ", "body wall", "trunk", "abdomen", "thorax", "head",
    # A pore IS the gap between the guard cells. Pointing it at either cell
    # would name the cell, not the opening.
    "stomatal pore",
    "mycelium", "colony", "exoskeleton", "cerebrum", "cerebral cortex",
}

#: How far from the anchor to look for ink, in MASTER pixels. 12 is the
#: platelet's own miss distance rounded up; beyond that the "nearest ink" is
#: a different structure and the proposal would be worse than the problem.
SEARCH = 12

#: Plates that draw a structure as a WHITE-FILLED outline, where an anchor
#: inside the shape is correct and looks like paper to any pixel test. The
#: frog heart's great vessels are drawn this way: `conus arteriosus` and
#: `truncus arteriosus` sit inside vessels whose fill is the page colour, and
#: flagging them would have moved two correct, already-published anchors onto
#: the black outline beside them. Checked by eye at 3x before adding.
WHITE_FILLED = {"bio11-ch7-frog--circulatory-and-respiratory-systems--a"}


def is_bg(master: Image.Image, x: int, y: int) -> bool:
    """Paper, not a pale structure — and the difference is the whole audit.

    The first version tested `r > 228 and g > 222 and b > 205`, which calls a
    pale fill paper. Measured: the frog `ventricle` sits on rgb(234,225,235),
    `cotyledon` on (246,238,220), `cranium` on (240,237,226) — all correct
    anchors on lightly-tinted organs, all flagged as misses. That inflated the
    flag rate to 17.8% and would have had me "correcting" anchors that were
    already right, which is the exact error the audit exists to remove.

    True paper on these plates is pure white AND FLAT. A tint has a hue; an
    organ has local variation. So: near-255 on every channel, and almost no
    spread in the 5x5 around the point.
    """
    W, H = master.size
    r, g, b = master.getpixel((x, y))[:3]
    if r < 248 or g < 248 or b < 244:
        return False
    lo, hi = 255, 0
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            px2, py2 = x + dx, y + dy
            if not (0 <= px2 < W and 0 <= py2 < H):
                continue
            v = master.getpixel((px2, py2))[:3]
            lo = min(lo, min(v)); hi = max(hi, max(v))
    return (hi - lo) <= 6


def audit_one(master: Image.Image, u: float, v: float) -> Dict[str, Any] | None:
    W, H = master.size
    cx, cy = int(u * W), int(v * H)
    if not (0 <= cx < W and 0 <= cy < H):
        return {"why": "outside the image", "dx": 0, "dy": 0, "dist": 0}
    if not is_bg(master, cx, cy):
        return None                      # on ink already
    best = None
    for dy in range(-SEARCH, SEARCH + 1):
        for dx in range(-SEARCH, SEARCH + 1):
            x, y = cx + dx, cy + dy
            if not (0 <= x < W and 0 <= y < H):
                continue
            if is_bg(master, x, y):
                continue
            d = dx * dx + dy * dy
            if best is None or d < best[0]:
                best = (d, dx, dy)
    if best is None:
        return {"why": f"on background, no ink within {SEARCH}px", "dx": 0, "dy": 0, "dist": None}
    d, dx, dy = best
    return {"why": "on background", "dx": dx, "dy": dy, "dist": round(d ** 0.5, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", default=None)
    args = ap.parse_args()

    files = sorted(DRAFTS.glob("*.pointed.json"))
    files += [p for p in DRAFTS.glob("bio11-ch7-*.draft.json")
              if not (DRAFTS / p.name.replace(".draft.json", ".pointed.json")).exists()]
    if args.chapter:
        files = [f for f in files if f.name.startswith(args.chapter + "-")]

    total = flagged = skipped = 0
    by_ch: Dict[str, List[str]] = defaultdict(list)
    for f in sorted(files):
        slug = f.name.replace(".pointed.json", "").replace(".draft.json", "")
        m = MASTERS / f"{slug}.png"
        if not m.exists():
            continue
        master = Image.open(m).convert("RGB")
        W, H = master.size
        d = json.loads(f.read_text(encoding="utf-8"))
        ch = "-".join(slug.split("-")[:2])
        for l in d.get("labels") or []:
            a = l.get("anchor")
            if not a:
                continue
            total += 1
            term = ((l.get("text") or {}).get("en") or l.get("id") or "").strip()
            if slug in WHITE_FILLED or term.lower() in SPACE_TERMS:
                skipped += 1
                continue
            r = audit_one(master, float(a[0]), float(a[1]))
            if not r:
                continue
            flagged += 1
            nu = round((int(a[0] * W) + r["dx"]) / W, 4)
            nv = round((int(a[1] * H) + r["dy"]) / H, 4)
            by_ch[ch].append(
                f"{slug} | {term} | {a[0]},{a[1]} -> {nu},{nv} | "
                f"{r['why']}, nearest ink {r['dist']}px")
    for ch in sorted(by_ch):
        print(f"\n{ch}  ({len(by_ch[ch])} flagged)")
        for line in by_ch[ch]:
            print("  " + line)
    pct = 100 * flagged / total if total else 0
    print(f"\n{total} anchors · {skipped} skipped as space-terms · "
          f"{flagged} flagged ({pct:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
