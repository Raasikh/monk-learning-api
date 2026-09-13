#!/usr/bin/env python3
"""Which board slot would every concept in a chapter land in? Resolve, do not run.

    python3 scripts/precompute_dry_run.py --subject biology --class-level 11 \
        --chapter "Structural Organisation in Animals" --batch 10

EXECUTES NOTHING. No plan is created, no model is called, no row is written.
It reads what already exists for each concept and puts it through the REAL
`tutor.resolve_board_slot` — the same pure function the live path uses — so
the answer cannot drift from what a class would actually do.

WHAT IT IS LOOKING FOR
======================
Two shapes are resolver bugs rather than content gaps, and both are
`--stop-on-bug` by default:

  1. the concept HAS an approved illustration asset and still resolves to
     `svg_precomputed` or `svg_live`. Slot 3 sits ABOVE both, so an asset that
     does not win means the ordering or the lookup is wrong.
  2. the concept HAS a routed widget — archetype_v2 at high confidence naming
     something in the registry — and still resolves to an svg slot. Slots 1
     and 2 sit above 3, 4 and 5.

Precedence is by TIER, never by timing: a precomputed tier-3 SVG is still tier
3, and caching it does not promote it. That sentence is the whole test.

Batches of ten with a per-batch summary, because a chapter of sixty read as
one wall of rows is a thing nobody checks.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", required=True)
    ap.add_argument("--class-level", type=int, required=True)
    ap.add_argument("--chapter", required=True, help="chapter name, exact")
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--keep-going", action="store_true",
                    help="report every bug instead of stopping at the first")
    args = ap.parse_args()

    from app.db import fetch_all
    from app.drona import tutor
    from app.drona.concept_archetypes import concept_archetype_for_session

    chapters = [c for c in fetch_all("chapters", "id,name,subject,class_level")
                if c["name"] == args.chapter
                and c["subject"] == args.subject
                and c["class_level"] == args.class_level]
    if not chapters:
        have = sorted({c["name"] for c in fetch_all("chapters", "id,name,subject,class_level")
                       if c["subject"] == args.subject and c["class_level"] == args.class_level})
        raise SystemExit(f"no chapter {args.chapter!r}; have: {have}")
    ch = chapters[0]

    # `key`, not `slug` — the column is named `key` and it is what
    # `subtopic_key` carries through a session. Ordered by teach_order so the
    # batches read the way a student meets them.
    concepts = sorted(fetch_all("concepts", "id,name,key,teach_order,active",
                                chapter_id=ch["id"]),
                      key=lambda c: (c.get("teach_order") or 0, c.get("key") or ""))
    concepts = [c for c in concepts if c.get("active") is not False]
    print(f"{ch['name']}  ({ch['subject']} {ch['class_level']})  {len(concepts)} concepts")
    print(f"chapter_id {ch['id']}")
    print("EXECUTES NOTHING — resolution only.\n")

    slots = Counter()
    bugs: List[str] = []
    rows: List[Dict[str, Any]] = []

    for i, c in enumerate(concepts):
        slug = c.get("key") or ""
        arch = concept_archetype_for_session(ch["id"], slug)
        assets = tutor._illustration_set_for(ch["id"], slug)
        asset = (assets[0] or {}).get("asset_slug") if assets else None
        svg = tutor._precomputed_diagram(ch["id"], slug)
        # Slot 1 needs a STORED payload on a segment, which only exists once a
        # plan has been built. A dry run does not build one, so slot 1 is left
        # empty here and the honest ceiling for this report is slot 2.
        slot = tutor.resolve_board_slot(
            precomputed_widget=None,
            archetype_widget=arch.widget,
            illustration_asset=asset,
            precomputed_svg=svg,
        )
        slots[slot] += 1
        rows.append({"slug": slug, "slot": slot, "asset": asset,
                     "widget": arch.widget, "conf": arch.confidence,
                     "svg": bool(svg)})

        if asset and slot in ("svg_precomputed", "svg_live"):
            bugs.append(f"{slug}: has asset {asset!r} and resolved to {slot} — "
                        f"slot 3 is ABOVE both svg slots")
        if arch.widget and slot in ("svg_precomputed", "svg_live"):
            bugs.append(f"{slug}: routes widget {arch.widget!r} "
                        f"(confidence {arch.confidence}) and resolved to {slot} — "
                        f"slots 1-2 are ABOVE 3, 4 and 5")
        if bugs and not args.keep_going:
            break

        if (i + 1) % args.batch == 0 or i + 1 == len(concepts):
            lo = (i // args.batch) * args.batch
            print(f"── batch {lo // args.batch + 1}: concepts {lo + 1}-{i + 1}")
            for r in rows[lo:]:
                mark = "  "
                if r["asset"] and r["slot"].startswith("svg"): mark = "!!"
                if r["widget"] and r["slot"].startswith("svg"): mark = "!!"
                print(f" {mark} {r['slot']:18} {r['slug'][:46]:46} "
                      f"asset={'y' if r['asset'] else '-'} "
                      f"widget={r['widget'] or '-'}/{r['conf'] or '-'} "
                      f"svg={'y' if r['svg'] else '-'}")

    print(f"\nslots: " + "  ".join(f"{k}={v}" for k, v in
                                   sorted(slots.items(), key=lambda kv: -kv[1])))
    if bugs:
        print(f"\nSTOPPED — {len(bugs)} resolver bug(s):")
        for b in bugs:
            print(f"  {b}")
        return 1
    print("\nno resolver bug: every concept with an asset or a routed widget "
          "resolves above the svg slots.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
