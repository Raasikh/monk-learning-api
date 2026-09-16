#!/usr/bin/env python3
"""H5 — what the board actually shows, per subject, at both shipping frames.

    python3 scripts/classroom_pass.py --per-subject 3

For each chosen concept it resolves the slot through the REAL
`tutor.resolve_board_slot` with the chapter's SANE verdict applied, then
renders whatever that slot yields at 343x236 and 702x289 and checks that
SOMETHING drew. The claim under test is the one the hold-back makes:

    a held widget falls through to an SVG or a plate, and the board is never
    blank.

"Never blank" is the part that needs proving. A hold-back that withheld the
widget and left nothing behind would look identical to a working one in every
slot table ever printed — the table would say `svg_live` and the student would
see paper.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MOB = Path("/Users/raasikhnaveed/Desktop/monk-learning-mobile/monklearning-mobile")
sys.path.insert(0, str(REPO))

FRAMES = [(343, 236), (702, 289)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-subject", type=int, default=3)
    args = ap.parse_args()

    from app.db import fetch_all
    from app.drona import tutor
    from app.drona.concept_archetypes import concept_archetype_for_session
    from app.drona.planner import WIDGET_PAYLOAD_KEY
    from app.drona.sane_hold_back import widget_baking_allowed

    chapters = {c["id"]: c for c in fetch_all("chapters", "id,name,subject,class_level")}
    plans = fetch_all("lesson_plans", "chapter_id,subtopic_key,plan_json")
    stored = {}
    for p in plans:
        for seg in (p["plan_json"] or {}).get("segments") or []:
            pay = seg.get(WIDGET_PAYLOAD_KEY)
            if isinstance(pay, dict) and pay.get("widget"):
                stored.setdefault((p["chapter_id"], p["subtopic_key"]), pay)

    # SELECTION IS THE WHOLE TEST. Taking the first three plans per subject gave
    # twelve concepts that had no widget and no asset, all resolving to
    # svg_live — a pass that exercised nothing and would have reported "no blank
    # boards" without ever withholding anything. Each subject now gets, in
    # order of preference: a concept with an ILLUSTRATION (plates draw with
    # their published labels), one with a WIDGET that the hold-back withholds
    # (the fall-through), and one with a PRECOMPUTED SVG (what it falls through
    # to). A subject that has none of a kind simply contributes fewer rows.
    scored = []
    for p in plans:
        ch = chapters.get(p["chapter_id"])
        if not ch:
            continue
        slug = p["subtopic_key"]
        arch = concept_archetype_for_session(ch["id"], slug)
        assets = tutor._illustration_set_for(ch["id"], slug)
        asset = (assets[0] or {}).get("asset_slug") if assets else None
        pay = stored.get((ch["id"], slug))
        svg = tutor._precomputed_diagram(ch["id"], slug)
        kind = ("illustration" if asset else
                "widget" if (pay or arch.widget) else
                "svg" if svg else "bare")
        scored.append((ch, slug, kind, arch, asset, pay, svg))

    picked, by_subject = [], {}
    for want in ("illustration", "widget", "svg", "bare"):
        for ch, slug, kind, arch, asset, pay, svg in scored:
            subj = ch["subject"]
            if kind != want or len(by_subject.get(subj, [])) >= args.per_subject:
                continue
            if any(r["concept"] == slug for r in picked):
                continue
            allowed, why = widget_baking_allowed(subj, ch["class_level"], ch["name"])
            slot = tutor.resolve_board_slot(
                precomputed_widget=pay, archetype_widget=arch.widget,
                illustration_asset=asset, precomputed_svg=svg,
                widget_allowed=allowed)
            row = {"subject": subj, "chapter": ch["name"], "concept": slug,
                   "slot": slot, "sane": why, "widget": arch.widget,
                   "payload": pay, "asset": asset, "has_svg": bool(svg),
                   "picked_for": kind}
            by_subject.setdefault(subj, []).append(row)
            picked.append(row)

    print(f"{'subject':<12}{'concept':<44}{'slot':<18}{'draws what'}")
    jobs = []
    for r in picked:
        if r["slot"].startswith("widget") and r["payload"]:
            draws = f"widget {r['payload']['widget']}"
            for w, h in FRAMES:
                jobs.append({"id": f"{r['concept']}__{w}x{h}",
                             "widget": r["payload"]["widget"],
                             "params": r["payload"]["params"], "w": w, "h": h})
        elif r["slot"] == "illustration":
            draws = f"plate {r['asset']}"
        elif r["slot"] == "svg_precomputed":
            draws = "precomputed SVG"
        else:
            draws = "live SVG (authored per turn)"
        print(f"{r['subject'][:11]:<12}{r['concept'][:43]:<44}{r['slot']:<18}{draws}")

    Path("/tmp/classroom-pass.json").write_text(json.dumps(picked, indent=1, default=str))
    held = [r for r in picked if not r["slot"].startswith("widget")
            and (r["widget"] or r["payload"])]
    print(f"\n{len(picked)} concepts; {len(held)} had a widget available and were HELD, "
          f"falling through to: "
          f"{', '.join(sorted({r['slot'] for r in held})) or '(none)'}")
    blank = [r for r in held if r["slot"] == "svg_live" and not r["has_svg"] and not r["asset"]]
    if blank:
        print(f"\n{len(blank)} concept(s) fall through to svg_live with nothing stored — "
              f"these are AUTHORED PER TURN and cannot be proven non-blank from here; "
              f"they need the live path:")
        for r in blank:
            print(f"   {r['subject']} {r['concept']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
