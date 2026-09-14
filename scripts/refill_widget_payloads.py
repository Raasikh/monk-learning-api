#!/usr/bin/env python3
"""Re-author ONLY the stored payloads the client would refuse. No hand edits.

    python3 scripts/refill_widget_payloads.py --chapter "Aldehydes, Ketones & Carboxylic Acids" \
        --subject chemistry --class-level 12 [--execute]

WHY NOT JUST REBUILD THE PLANS. `example_widget_payload` is filled during plan
authoring, so the obvious way to regenerate it is `--force` on the plan — which
re-authors the objectives, teaching notes and board content too. Those have been
reviewed; the payload has not. Throwing away reviewed text to fix a picture is
a bad trade, so this calls `_attach_widget_payload` per segment and leaves
everything else alone.

WHAT DECIDES WHICH SEGMENTS. Not a list, and not "everything". Each stored
payload is put through the CLIENT'S validator — the same one
`sanitize_widget_payload` now calls — and only the refusals are re-authored.
A payload that draws is left exactly as it is, including the seven corrected
by hand, because re-rolling a correct payload risks replacing it with a worse
one for no gain.

The re-authored payload goes through the same gate on the way back in, so a
model that produces another unrenderable payload is recorded as `rejected`
rather than stored. That is the whole point of doing this after E1 and not
before: without the gate this script would faithfully store fresh garbage.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
CLI = (REPO.parent / "monk-learning-mobile" / "monklearning-mobile"
       / "scripts" / "validate-payload.mjs")


def would_draw(payload: Dict[str, Any]) -> tuple[bool, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(payload, fh)
        tmp = fh.name
    try:
        r = subprocess.run(["node", str(CLI), tmp, "--json"],
                           capture_output=True, text=True, timeout=180)
        line = next((l for l in r.stdout.splitlines() if l.startswith("{")), "")
        if not line:
            return True, "no verdict"
        res = (json.loads(line).get("results") or [{}])[0]
        if res.get("ok") is None:
            return True, "unjudgeable"
        return bool(res.get("ok")), "; ".join(res.get("errors") or [])
    finally:
        Path(tmp).unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--class-level", type=int, required=True)
    ap.add_argument("--execute", action="store_true",
                    help="write the results back; without it nothing is stored")
    ap.add_argument("--force", default="",
                    help="comma-separated <subtopic_key>:<seg> to re-author EVEN IF "
                         "they already draw. For the case the render gate cannot "
                         "see: a payload that renders perfectly and shows the "
                         "wrong picture — an infinite line charge drawn as a "
                         "point, a single sheet drawn as parallel plates. Each "
                         "one here is a named human judgement, never a sweep.")
    args = ap.parse_args()

    from app.db import fetch_all, get_supabase
    from app.drona import planner
    from app.drona.concept_archetypes import concept_archetype_for_session

    chs = [c for c in fetch_all("chapters", "id,name,subject,class_level")
           if c["name"] == args.chapter and c["subject"] == args.subject
           and c["class_level"] == args.class_level]
    if not chs:
        raise SystemExit(f"no chapter {args.chapter!r} in {args.subject} {args.class_level}")
    ch = chs[0]
    plans = fetch_all("lesson_plans", "id,subtopic_key,plan_json", chapter_id=ch["id"])
    print(f"{ch['name']}  {len(plans)} plans   "
          f"{'EXECUTE' if args.execute else 'DRY RUN — nothing will be written'}\n")

    forced = set()
    for spec in filter(None, (x.strip() for x in args.force.split(","))):
        key, _, seg = spec.rpartition(":")
        forced.add((key, int(seg)))
    if forced:
        print(f"forcing re-author of {len(forced)} segment(s) that already draw\n")

    refilled = still_bad = left_alone = dropped = 0
    for p in plans:
        plan = json.loads(json.dumps(p["plan_json"]))
        segs = plan.get("segments") or []
        arch = concept_archetype_for_session(ch["id"], p["subtopic_key"])
        touched = False
        for i, seg in enumerate(segs, 1):
            old = seg.get(planner.WIDGET_PAYLOAD_KEY)
            if not isinstance(old, dict) or not old.get("widget"):
                continue
            ok, why = would_draw(old)
            if ok and (p["subtopic_key"], i) not in forced:
                left_alone += 1
                continue
            before = json.dumps(old, sort_keys=True)
            status = planner._attach_widget_payload(
                seg, arch, {"id": ch["id"], "name": ch["name"]},
                p["subtopic_key"], subtopic_key=p["subtopic_key"], plan_id=p["id"])
            new = seg.get(planner.WIDGET_PAYLOAD_KEY)
            # `_attach_widget_payload` writes the segment ONLY through
            # sanitize_widget_payload, so a rejected author call leaves the OLD
            # payload in place, untouched. Until 2026-09-14 this script read
            # that back and printed "STILL BAD <old reason>", which read as
            # "the author tried and produced something equally bad". It had
            # not: nothing was written at all. The reasons were byte-identical
            # across two runs, which is what gave it away.
            unchanged = isinstance(new, dict) and json.dumps(new, sort_keys=True) == before
            if isinstance(new, dict) and new.get("widget") and not unchanged:
                ok2, why2 = would_draw(new)
                if ok2:
                    refilled += 1; touched = True
                    print(f"  REFILLED  {p['subtopic_key'][:44]:44} seg{i}")
                else:
                    # Cannot happen while sanitize gates every write; kept so
                    # that if it ever does, it is loud rather than counted as
                    # a refill.
                    still_bad += 1
                    print(f"  WROTE BAD {p['subtopic_key'][:43]:43} seg{i}  {why2[:56]}")
            else:
                # The author could not produce a drawable payload. REMOVE the
                # one that is there. A stored payload that the client refuses
                # is strictly worse than none: slot 1 outranks every fallback
                # in `resolve_board_slot`, so it wins precedence and then draws
                # nothing -- a blank board where an authored SVG would have
                # gone. Dropping it lets the segment fall through to a lower
                # slot and lets the live path ask again per turn.
                old_drew, why_old = would_draw(old)
                if old_drew and status == "declined":
                    # A FORCED segment whose author, shown the objective again,
                    # says no picture belongs here. That is an answer, and it
                    # is the answer for the two Gauss segments that draw a
                    # fifth identical point-charge starburst beside a
                    # three-way comparison. Drop it: a wrong picture at slot 1
                    # outranks the authored SVG that would otherwise show.
                    seg.pop(planner.WIDGET_PAYLOAD_KEY, None)
                    dropped += 1; touched = True
                    print(f"  DECLINED  {p['subtopic_key'][:43]:43} seg{i}  "
                          f"author says no widget draws this")
                elif old_drew:
                    # Forced, and the author could not do better. KEEP what is
                    # there. It draws; dropping it would trade a questionable
                    # picture for none and make the render rate look better by
                    # deleting the evidence.
                    left_alone += 1
                    print(f"  KEPT      {p['subtopic_key'][:43]:43} seg{i}  "
                          f"forced re-author failed ({status}); old payload draws")
                else:
                    seg.pop(planner.WIDGET_PAYLOAD_KEY, None)
                    dropped += 1; touched = True
                    print(f"  DROPPED   {p['subtopic_key'][:43]:43} seg{i}  "
                          f"status={status}  was: {why_old[:48]}")
        if touched and args.execute:
            get_supabase().table("lesson_plans").update(
                {"plan_json": plan}).eq("id", p["id"]).execute()

    print(f"\nleft alone (already draw) {left_alone}   refilled {refilled}   "
          f"dropped (author could not fix) {dropped}   wrote-bad {still_bad}")
    print(f"stored payloads that draw after this run: "
          f"{left_alone + refilled}/{left_alone + refilled + still_bad}")
    if not args.execute:
        print("DRY RUN — nothing was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
