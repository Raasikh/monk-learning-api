#!/usr/bin/env python3
"""I3 — give every HELD widget a stored picture underneath it.

    python3 scripts/backfill_fallback_svg.py            # dry run
    python3 scripts/backfill_fallback_svg.py --execute

Without regenerating a single plan. This is the first thing the I2 hash split
makes possible: boards can be touched while segment structure and objective
text stay byte-identical, so the human SANE judgements keyed to those
objectives survive.

SCOPE, AND WHY IT IS NOT "every segment lacking an SVG".
--------------------------------------------------------
1,114 of 2,244 segments carry no `example_diagram_svg`. Only 49 of them are the
case this exists to fix: a chapter held below the SANE bar, holding a stored
widget payload it is not allowed to show, with nothing stored behind it — so
the board falls to `svg_live` and is authored per turn, at latency, only if
that call succeeds.

The other 1,065 have no widget at all. They resolved to `svg_live` before any
of this and still do; that is the ordinary state of a segment nobody drew a
picture for, not a regression. Backfilling them is ~22x the LLM spend for no
change to the measurable goal, so it is priced and left to Raasikh rather than
done quietly here.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

LOGDIR = REPO / "content/backfill-logs"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--all-segments", action="store_true",
                    help="the 1,114, not the 49 — price it before using this")
    args = ap.parse_args()

    from app.db import fetch_all, get_supabase
    from app.drona import planner
    from app.drona.planner import WIDGET_PAYLOAD_KEY
    from app.drona.sane_hold_back import widget_baking_allowed

    chapters = {c["id"]: c for c in fetch_all("chapters", "id,name,subject,class_level")}
    plans = fetch_all("lesson_plans", "id,chapter_id,subtopic_key,plan_json")
    LOGDIR.mkdir(parents=True, exist_ok=True)

    targets = []
    for p in plans:
        ch = chapters.get(p["chapter_id"])
        if not ch:
            continue
        allowed, _ = widget_baking_allowed(ch["subject"], ch["class_level"], ch["name"])
        segs = (p["plan_json"] or {}).get("segments") or []
        for i, s in enumerate(segs, 1):
            if s.get("example_diagram_svg"):
                continue
            has_widget = isinstance(s.get(WIDGET_PAYLOAD_KEY), dict)
            if args.all_segments or (has_widget and not allowed):
                targets.append((ch, p, i))

    by_chapter = {}
    for ch, p, i in targets:
        by_chapter.setdefault(ch["name"], []).append((ch, p, i))
    print(f"{len(targets)} segment(s) across {len(by_chapter)} chapter(s)"
          f"{'' if args.execute else '  (dry run)'}\n")
    for name, rows in sorted(by_chapter.items()):
        print(f"  {name[:48]:<48} {len(rows):>4}")
    if not args.execute:
        print("\npass --execute to author them")
        return 0

    done = failed = 0
    for name, rows in sorted(by_chapter.items()):
        t0 = time.time()
        log = []
        # group by plan so each plan_json is written once
        per_plan = {}
        for ch, p, i in rows:
            per_plan.setdefault(p["id"], (ch, p, []))[2].append(i)
        for plan_id, (ch, p, idxs) in per_plan.items():
            pj = json.loads(json.dumps(p["plan_json"] or {}))
            segs = pj.get("segments") or []
            before = [s.get("objective") for s in segs]
            for i in idxs:
                seg = segs[i - 1]
                try:
                    planner._attach_example_diagram(seg, ch["subject"],
                                                    p["subtopic_key"], force=True)
                    ok = bool(seg.get("example_diagram_svg"))
                    done += ok
                    failed += (not ok)
                    log.append({"subtopic": p["subtopic_key"], "seg": i,
                                "result": "attached" if ok else "author declined"})
                except Exception as exc:                      # noqa: BLE001
                    failed += 1
                    log.append({"subtopic": p["subtopic_key"], "seg": i,
                                "result": f"error: {str(exc)[:100]}"})
            if [s.get("objective") for s in segs] != before:
                raise SystemExit(f"REFUSED: {p['subtopic_key']} — an objective moved "
                                 f"during a board-only backfill")
            planner._stamp_plan_json_provenance(pj)
            get_supabase().table("lesson_plans").update(
                {"plan_json": pj}).eq("id", plan_id).execute()
        # CHILD OUTPUT PER CHAPTER. The 11-hour outlier in the last sweep could
        # not be explained afterwards because nothing per-chapter was kept.
        (LOGDIR / f"{name.replace('/', '-')}.json").write_text(json.dumps(
            {"chapter": name, "seconds": round(time.time() - t0, 1),
             "attempted": len(rows), "log": log}, indent=1))
        print(f"  done {name[:44]:<44} {time.time() - t0:>6.0f}s  {len(rows)} attempted")

    print(f"\nattached {done}, failed {failed}; per-chapter logs in {LOGDIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
