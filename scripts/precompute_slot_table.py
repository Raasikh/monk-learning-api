#!/usr/bin/env python3
"""Resolved board slot per concept, BEFORE and AFTER the SANE hold-back.

    python3 scripts/precompute_slot_table.py            # every chapter with plans
    python3 scripts/precompute_slot_table.py --json

EXECUTES NOTHING. It reads what exists and puts each concept through the REAL
`tutor.resolve_board_slot`, twice:

  BEFORE  the archetype's widget is offered to slot 2, as it was before
          2026-09-14 — what a chapter would resolve to with no hold-back.
  AFTER   the widget is offered only where the chapter's SANE verdict clears
          the bar. Below it, or unmeasured, slot 2 is withheld and the concept
          falls to illustration -> precomputed SVG -> live SVG.

The two resolver-bug shapes from the directive are checked on the AFTER pass,
because that is the one that will run: a concept with an asset, or with an
ELIGIBLE routed widget, that lands on an svg slot is a bug rather than a
content gap. A concept whose widget was withheld by the hold-back and which
then lands on an svg slot is NOT a bug — that is the rule working.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from app.db import fetch_all
    from app.drona import tutor
    from app.drona.concept_archetypes import concept_archetype_for_session
    from app.drona.sane_hold_back import widget_baking_allowed, SANE_BAR_PERCENT

    chapters = {c["id"]: c for c in fetch_all("chapters", "id,name,subject,class_level")}
    with_plans = {p["chapter_id"] for p in fetch_all("lesson_plans", "id,chapter_id")}
    targets = sorted((c for cid, c in chapters.items() if cid in with_plans),
                     key=lambda c: (c["subject"], c["class_level"], c["name"]))

    out, moved, bugs = [], [], []
    before_tot, after_tot = Counter(), Counter()
    print(f"SANE bar {SANE_BAR_PERCENT:.0f}%   {len(targets)} chapters with authored plans\n")
    print(f"{'chapter':<46}{'bake?':>6}  {'concepts':>8}  slot changes")

    for ch in targets:
        allowed, why = widget_baking_allowed(ch["subject"], ch["class_level"], ch["name"])
        concepts = [c for c in fetch_all("concepts", "id,name,key,teach_order,active",
                                         chapter_id=ch["id"])
                    if c.get("active") is not False]
        concepts.sort(key=lambda c: (c.get("teach_order") or 0, c.get("key") or ""))
        ch_moved = 0
        for c in concepts:
            slug = c.get("key") or ""
            arch = concept_archetype_for_session(ch["id"], slug)
            assets = tutor._illustration_set_for(ch["id"], slug)
            asset = (assets[0] or {}).get("asset_slug") if assets else None
            svg = tutor._precomputed_diagram(ch["id"], slug)

            before = tutor.resolve_board_slot(
                precomputed_widget=None, archetype_widget=arch.widget,
                illustration_asset=asset, precomputed_svg=svg)
            after = tutor.resolve_board_slot(
                precomputed_widget=None,
                archetype_widget=(arch.widget if allowed else None),
                illustration_asset=asset, precomputed_svg=svg)

            before_tot[before] += 1
            after_tot[after] += 1
            if before != after:
                ch_moved += 1
                moved.append({"chapter": ch["name"], "concept": slug,
                              "before": before, "after": after,
                              "widget": arch.widget, "why": why})
            # Resolver bugs, judged on the pass that will run.
            if asset and after.startswith("svg"):
                bugs.append(f"{slug}: has asset {asset!r} and resolved to {after}"
                            f" — slot 3 is ABOVE both svg slots")
            if allowed and arch.widget and after.startswith("svg"):
                bugs.append(f"{slug}: routes {arch.widget!r} ({arch.confidence}), is"
                            f" ELIGIBLE to bake, and resolved to {after}")
            out.append({"subject": ch["subject"], "class_level": ch["class_level"],
                        "chapter": ch["name"], "concept": slug,
                        "before": before, "after": after,
                        "asset": bool(asset), "widget": arch.widget,
                        "confidence": arch.confidence, "bakes": allowed})
        print(f"{ch['name'][:44]:<46}{('BAKE' if allowed else 'hold'):>6}  "
              f"{len(concepts):>8}  {ch_moved if ch_moved else '-'}")

    print(f"\nresolved slot, all {len(out)} concepts")
    print(f"{'slot':<20}{'before':>8}{'after':>8}{'delta':>8}")
    for s in sorted(set(before_tot) | set(after_tot)):
        d = after_tot[s] - before_tot[s]
        print(f"{s:<20}{before_tot[s]:>8}{after_tot[s]:>8}{d:>+8}")
    print(f"\n{len(moved)} concept(s) moved slot because of the hold-back")

    if bugs:
        print(f"\nRESOLVER BUGS ({len(bugs)}) — stop and fix, do not patch around:")
        for b in bugs[:40]:
            print(f"  {b}")
    else:
        print("\nno resolver bugs: every concept with an asset resolved to "
              "`illustration`, and every ELIGIBLE routed widget got its slot.")

    if args.json:
        Path("scripts/precompute_slot_table.json").write_text(
            json.dumps({"rows": out, "moved": moved, "bugs": bugs}, indent=1))
        print("\n-> scripts/precompute_slot_table.json")
    return 1 if bugs else 0


if __name__ == "__main__":
    raise SystemExit(main())
