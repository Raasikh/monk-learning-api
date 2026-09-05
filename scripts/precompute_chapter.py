"""Precompute every concept in one chapter, and WAIT for each plan to finish.

WHY THIS EXISTS RATHER THAN A LOOP OVER get_or_create_plan
----------------------------------------------------------
create_plan_streaming returns as soon as segment 1 exists and fills segments
2..N on a DAEMON thread, so that a live session can start teaching at ~24s
instead of ~5 minutes. That is right for a server, whose process outlives the
thread.

It is wrong for a script. A daemon thread is killed the moment the process
exits, so a loop that finishes and returns leaves whatever was still filling
PERMANENTLY PARTIAL -- and logs nothing, because the thread never got to its
own error handler. The first C1 run left "Biodiversity and the Need for
Classification" at 1 of 7 segments, an hour later still 1 of 7, with zero
BACKGROUND PLAN FILL FAILED lines. Nothing was wrong except that the process
had gone home.

So: poll _status until complete, with a deadline, and treat a timeout as a
LOUD failure rather than a plan. Measuring time-to-first-segment and calling it
time-to-plan is how the first run reported 27.9s for something that took
minutes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import supabase
from app.drona.planner import get_or_create_plan, plan_provenance

POLL_SECONDS = 5
DEFAULT_DEADLINE = 900  # 15 min per concept; the slowest C1 concept took ~6


def wait_for_complete(plan_id: str, deadline: int) -> tuple[bool, dict, float]:
    """Poll until _status == complete. Returns (ok, plan_json, seconds)."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < deadline:
        row = supabase.table("lesson_plans").select("plan_json").eq("id", plan_id).execute().data
        pj = (row[0]["plan_json"] if row else {}) or {}
        if pj.get("_status", "complete") == "complete":
            return True, pj, time.perf_counter() - t0
        time.sleep(POLL_SECONDS)
    row = supabase.table("lesson_plans").select("plan_json").eq("id", plan_id).execute().data
    return False, ((row[0]["plan_json"] if row else {}) or {}), time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", required=True)
    ap.add_argument("--class-level", type=int, required=True)
    ap.add_argument("--chapter", required=True, help="chapter name, exact")
    ap.add_argument("--deadline", type=int, default=DEFAULT_DEADLINE)
    args = ap.parse_args()

    chapters = supabase.table("chapters").select("id,name").eq("subject", args.subject) \
        .eq("class_level", args.class_level).execute().data
    match = [c for c in chapters if c["name"] == args.chapter]
    if not match:
        print(f"no chapter named {args.chapter!r}; have: {[c['name'] for c in chapters][:8]}")
        return 2
    ch = match[0]
    concepts = supabase.table("concepts").select("id,name,key,display_order") \
        .eq("chapter_id", ch["id"]).order("display_order").execute().data

    prov = plan_provenance()
    print(f"chapter: {ch['name']}   concepts: {len(concepts)}")
    print(f"provenance: {json.dumps({k: v for k, v in prov.items() if k != 'retrieval_config'})}\n")

    results, failures = [], []
    for i, c in enumerate(concepts, 1):
        key = c.get("key") or c["name"]
        t0 = time.perf_counter()
        try:
            plan = get_or_create_plan(ch["id"], key)
            ok, pj, waited = wait_for_complete(plan["id"], args.deadline)
            total = time.perf_counter() - t0
            segs = pj.get("segments") or []
            board = sum(len(s.get("board_content") or []) for s in segs)
            if not ok:
                # LOUD. A partial plan is not a plan: the student reaches
                # segment 2 and there is nothing there.
                msg = (f"INCOMPLETE after {args.deadline}s — {len(segs)} of "
                       f"{pj.get('_expected_segments', '?')} segments")
                failures.append((c["name"], msg))
                print(f"[{i}/{len(concepts)}] !! {msg}  {c['name'][:40]}")
            else:
                print(f"[{i}/{len(concepts)}] {total:6.1f}s  {len(segs)} seg  "
                      f"{board:3} board  {c['name'][:42]}")
            results.append({"concept": c["name"], "complete": ok, "sec": total,
                            "segments": len(segs), "board": board, "plan_id": plan["id"]})
        except Exception as e:
            failures.append((c["name"], f"{type(e).__name__}: {e}"))
            print(f"[{i}/{len(concepts)}] !! FAILED {c['name'][:40]}\n      {str(e)[:160]}")

    json.dump(results, open("/tmp/precompute_results.json", "w"), indent=1)
    done = [r for r in results if r["complete"]]
    print(f"\n=== {ch['name']} ===")
    print(f"  complete {len(done)}/{len(concepts)}")
    if done:
        secs = sorted(r["sec"] for r in done)
        print(f"  wall time to COMPLETE plan: min {secs[0]:.0f}s  "
              f"median {secs[len(secs)//2]:.0f}s  max {secs[-1]:.0f}s")
        print(f"  segments {sum(r['segments'] for r in done)}  "
              f"board items {sum(r['board'] for r in done)}")
    if failures:
        print(f"\n  FAILURES ({len(failures)}):")
        for name, why in failures:
            print(f"    {name[:48]:50} {why}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
