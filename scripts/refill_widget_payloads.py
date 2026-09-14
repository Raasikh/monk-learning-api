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

    refilled = still_bad = left_alone = 0
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
            if ok:
                left_alone += 1
                continue
            before = json.dumps(old, sort_keys=True)
            status = planner._attach_widget_payload(
                seg, arch, {"id": ch["id"], "name": ch["name"]},
                p["subtopic_key"], subtopic_key=p["subtopic_key"], plan_id=p["id"])
            new = seg.get(planner.WIDGET_PAYLOAD_KEY)
            if isinstance(new, dict) and new.get("widget"):
                ok2, why2 = would_draw(new)
                if ok2:
                    refilled += 1; touched = True
                    print(f"  REFILLED {p['subtopic_key'][:44]:44} seg{i}  "
                          f"{'changed' if json.dumps(new, sort_keys=True) != before else 'identical'}")
                else:
                    still_bad += 1
                    print(f"  STILL BAD {p['subtopic_key'][:43]:43} seg{i}  {why2[:56]}")
            else:
                still_bad += 1
                print(f"  NO PAYLOAD {p['subtopic_key'][:42]:42} seg{i}  status={status}")
                touched = True
        if touched and args.execute:
            get_supabase().table("lesson_plans").update(
                {"plan_json": plan}).eq("id", p["id"]).execute()

    print(f"\nleft alone (already draw) {left_alone}   refilled {refilled}   "
          f"still not drawable {still_bad}")
    if not args.execute:
        print("DRY RUN — nothing was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
