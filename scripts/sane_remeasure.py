#!/usr/bin/env python3
"""I4 — propose a SANE verdict for every board on the CURRENT plans.

    python3 scripts/sane_remeasure.py --write

These are PROPOSALS, not verdicts. Nothing here is adopted; a proposal becomes
a verdict only when Raasikh signs the row. The distinction is the whole reason
`verdict_by` exists, and this script never sets it.

Keyed per I1 by `objective_sha:widget_id`, so a proposal survives a board
re-author (I2 keeps objectives byte-identical) and does NOT survive a rewritten
objective — which is the failure that voided 72 of 86 judgements on 2026-09-15.

The rules are the H7 ones, applied to what is stored now rather than to a sheet
written against a corpus that has since moved:

  (i)   the objective asks to COMPARE / RANK / DISTINGUISH / LIST and a
        schematic or sequence widget was drawn anyway. A correct DECLINE on
        such an objective is sane — that is what the decline sentence added to
        the widget block on 2026-09-15 is for, and this counts whether it fired.
  (ii)  a widget drew and its parameters look wrong for the objective.
  (iii) nothing registered draws what the objective asks for.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
STORE = REPO / "content/sane-rows.json"

TABULAR = re.compile(r"\b(compare|contrast|distinguish|differentiate|rank|list|"
                     r"classify|tabulate|types of|which can be|identify which|"
                     r"choose the correct|decision tree|advantages|limitations|"
                     r"factors that|key factors)\b", re.I)
#: objectives that want no picture at all — a decline is right and not a gap
PROSE_ONLY = re.compile(r"\b(define|recall|state the|name the|list the names)\b", re.I)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    from app.db import fetch_all
    from app.drona.planner import WIDGET_PAYLOAD_KEY, WIDGET_PRECOMPUTE_KEY
    from scripts.sane_rows import normalise, objective_sha, verdict_key

    chapters = {c["id"]: c for c in fetch_all("chapters", "id,name,subject,class_level")}
    proposals, stats = [], Counter()
    decline_status = Counter()

    for p in fetch_all("lesson_plans", "chapter_id,subtopic_key,plan_json"):
        ch = chapters.get(p["chapter_id"])
        if not ch:
            continue
        for i, s in enumerate((p["plan_json"] or {}).get("segments") or [], 1):
            objective = str(s.get("objective") or "")
            if not normalise(objective):
                stats["segment has no objective"] += 1
                continue
            pay = s.get(WIDGET_PAYLOAD_KEY)
            pay = pay if isinstance(pay, dict) and pay.get("widget") else None
            rec = s.get(WIDGET_PRECOMPUTE_KEY) or {}
            status = rec.get("status") or "not_asked"
            widget = pay["widget"] if pay else "decline"
            tabular = bool(TABULAR.search(objective))

            if tabular:
                # THE COUNT I4 ASKS FOR. A decline on a tabular objective is
                # only evidence the rule works if the AUTHOR declined —
                # `not_asked` means the archetype named no widget and nobody
                # was ever asked, which was true before the rule existed.
                decline_status[status if not pay else f"drew {widget}"] += 1

            if pay and tabular:
                kind, verdict = "i", "n"
                reason = (f"the objective asks to compare/rank/distinguish and "
                          f"`{widget}` drew a schematic anyway; an arrow means "
                          f"'becomes', not an ordering")
            elif not pay and tabular:
                kind, verdict = "iii", "y" if status == "declined" else "n"
                reason = ("declined, which is correct — no registered widget draws a "
                          "table" if status == "declined" else
                          f"no widget drew this, but the author was never asked "
                          f"(status={status}), so the decline is not evidence of "
                          f"anything")
            elif pay:
                kind, verdict, reason = "ii", "y", ""
            else:
                kind, verdict = "iii", "y" if PROSE_ONLY.search(objective) else "y"
                reason = ""
            stats[f"{verdict} ({kind})"] += 1
            proposals.append({
                "sheet": f"{ch['subject']} {ch['class_level']} remeasure",
                "subject": ch["subject"], "class_level": ch["class_level"],
                "chapter": ch["name"], "subtopic_key": p["subtopic_key"],
                "legacy_segment_index": i, "objective": objective,
                "widget_id": widget, "objective_sha": objective_sha(objective),
                "verdict_key": verdict_key(objective, widget),
                "verdict": verdict, "proposal_kind": kind, "reason": reason,
                "precompute_status": status, "tabular_objective": tabular,
                "bucket": "proposal",
            })

    print(f"{len(proposals)} proposals over the current plans\n")
    for k, v in sorted(stats.items()):
        print(f"  {k:<28} {v}")
    print("\ntabular objectives — what actually happened:")
    for k, v in decline_status.most_common():
        print(f"  {k:<28} {v}")
    fired = decline_status.get("declined", 0)
    never = decline_status.get("not_asked", 0)
    print(f"\n  the decline sentence FIRED on {fired}; {never} were never asked "
          f"(archetype named no widget) and are NOT evidence it works")

    if args.write:
        doc = json.loads(STORE.read_text())
        doc["proposals_2026_09_17"] = proposals
        # NOT in `_counts` — that tally means the four VERDICT buckets, and a
        # proposal is not a verdict. Mixing them broke the invariant test the
        # moment this script first wrote, which is the test doing its job.
        doc.setdefault("_proposal_counts", {})["proposals_2026_09_17"] = len(proposals)
        doc["_proposal_note"] = (
            "PROPOSALS, not verdicts — nothing here is adopted and verdict_by is unset. "
            f"Generated {date.today()} against the current plans, keyed by "
            "objective_sha:widget_id so they survive a board re-author and do not "
            "survive a rewritten objective.")
        STORE.write_text(json.dumps(doc, indent=1))
        print(f"\nwrote {len(proposals)} proposals into {STORE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
