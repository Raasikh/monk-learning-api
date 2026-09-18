#!/usr/bin/env python3
"""J3 — the rows where a schematic was drawn on a compare/rank objective.

    python3 scripts/fix_kind_i.py            # dry run
    python3 scripts/fix_kind_i.py --execute

Re-authors the BOARD only, never the segment: objectives are compared before
and after and the write is refused if any moved. That is the I2 board path, and
it is why this costs minutes instead of re-running a sweep that would void the
review.

Any row the author still draws after being shown the decline rule is FORCED to
decline — the payload is removed and the segment falls down the precedence to
its stored SVG. Forcing is last, not first: the author is asked properly once,
and the count of how many needed forcing is the measure of how well the rule
works on its own.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    from app.db import fetch_all, get_supabase
    from app.drona import planner
    from app.drona.planner import WIDGET_PAYLOAD_KEY, WIDGET_PRECOMPUTE_KEY
    from app.drona.concept_archetypes import concept_archetype_for_session

    rows = json.loads(Path("/tmp/i-rows.json").read_text())
    chapters = {c["name"]: c for c in fetch_all("chapters", "id,name,subject,class_level")}
    plans = {}
    for p in fetch_all("lesson_plans", "id,chapter_id,subtopic_key,plan_json"):
        plans[(p["chapter_id"], p["subtopic_key"])] = p

    print(f"{len(rows)} kind-(i) row(s){'' if args.execute else '  (dry run)'}\n")
    redeclined = forced = still = 0
    per_plan = {}
    for r in rows:
        ch = chapters.get(r["chapter"])
        pl = plans.get((ch["id"], r["subtopic_key"])) if ch else None
        if not pl:
            print(f"  MISSING plan for {r['chapter']} / {r['subtopic_key']}")
            continue
        per_plan.setdefault(pl["id"], (ch, pl, []))[2].append(r)

    for plan_id, (ch, pl, rs) in per_plan.items():
        pj = json.loads(json.dumps(pl["plan_json"] or {}))
        segs = pj.get("segments") or []
        before = [s.get("objective") for s in segs]
        arch = concept_archetype_for_session(ch["id"], pl["subtopic_key"])
        for r in rs:
            i = r["legacy_segment_index"]
            if not (1 <= i <= len(segs)):
                continue
            seg = segs[i - 1]
            if not args.execute:
                print(f"  would re-author {r['chapter'][:28]:<28} "
                      f"{r['subtopic_key'][:30]:<30} seg{i}  ({r['widget_id']})")
                continue
            for k in (WIDGET_PAYLOAD_KEY, WIDGET_PRECOMPUTE_KEY):
                seg.pop(k, None)
            planner._attach_widget_payload(
                seg, arch, {"id": ch["id"], "name": ch["name"], "subject": ch["subject"]},
                pl["subtopic_key"], subtopic_key=pl["subtopic_key"], plan_id=plan_id)
            pay = seg.get(WIDGET_PAYLOAD_KEY)
            status = (seg.get(WIDGET_PRECOMPUTE_KEY) or {}).get("status")
            if not (isinstance(pay, dict) and pay.get("widget")):
                redeclined += 1
                print(f"  DECLINED  {r['subtopic_key'][:32]:<32} seg{i}  status={status}")
            else:
                # Asked properly and still drew. Force it.
                seg.pop(WIDGET_PAYLOAD_KEY, None)
                seg[WIDGET_PRECOMPUTE_KEY] = {
                    "status": "declined",
                    "why": ("FORCED at routing 2026-09-17: the objective asks to "
                            "compare/rank/distinguish and no registered widget draws a "
                            "table; the author drew a schematic again after being shown "
                            "the decline rule."),
                    "forced": True,
                }
                forced += 1
                print(f"  FORCED    {r['subtopic_key'][:32]:<32} seg{i}  "
                      f"had drawn {pay['widget']}")
        if args.execute:
            if [s.get("objective") for s in segs] != before:
                raise SystemExit(f"REFUSED: an objective moved in {pl['subtopic_key']}")
            planner._stamp_plan_json_provenance(pj)
            get_supabase().table("lesson_plans").update(
                {"plan_json": pj}).eq("id", plan_id).execute()

    if args.execute:
        print(f"\ndeclined on its own: {redeclined}   forced: {forced}   "
              f"total now declining: {redeclined + forced}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
