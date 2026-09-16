#!/usr/bin/env python3
"""Re-adopt a chapter's SANE verdict from a proposal. DRY RUN unless --execute.

    python3 scripts/apply_sane.py --chapter <id> --adopt proposal_v2 --by raasikh

One line per chapter, so re-adoption is a decision Raasikh makes per chapter
rather than a file he edits. It writes `content/sane-verdicts.json`, which is
what `resolve_board_slot` reads; once migration 0046 is applied it writes the
columns too.

IT REFUSES TO ADOPT A PROJECTION. proposal_v2 classifies rows; it does not
re-judge them. A (i) row only becomes sane once the routing harness has been
re-run and the row actually declines, and a (ii) row only once it has been
re-authored AND re-judged — `nucleophilic-addition` seg 3 is the standing proof
that a re-authored payload can still be wrong. So a kind is not a verdict, and
this command will not turn one into the other on its own: `--adopt proposal_v2`
requires `--confirmed-rows`, the rows a human has actually signed off.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
VERDICTS = REPO / "content/sane-verdicts.json"
V2 = Path("/tmp/sane-v2.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", required=True, help="chapter uuid, or its exact name")
    ap.add_argument("--adopt", default="proposal_v2")
    ap.add_argument("--by", required=True)
    ap.add_argument("--confirmed-rows", default="",
                    help="comma-separated <subtopic>:<seg> the reviewer has signed off "
                         "as now sane. Without it nothing moves — a classification is "
                         "not a judgement.")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    from app.db import fetch_all

    chapters = fetch_all("chapters", "id,name,subject,class_level")
    match = [c for c in chapters
             if c["id"] == args.chapter or c["name"] == args.chapter]
    if not match:
        raise SystemExit(f"no chapter {args.chapter!r}")
    ch = match[0]

    doc = json.loads(VERDICTS.read_text())
    cur = next((v for v in doc["verdicts"]
                if v["subject"] == ch["subject"]
                and v["class_level"] == ch["class_level"]
                and v["chapter"] == ch["name"]), None)
    if not cur:
        raise SystemExit(f"{ch['name']} has no adopted verdict to move from; it is "
                         f"UNMEASURED, and unmeasured is held back.")

    rows = [r for r in json.loads(V2.read_text())
            if r["sheet"] == cur["sheet"]] if V2.exists() else []
    signed = {tuple(x.rsplit(":", 1)) for x in
              filter(None, (s.strip() for s in args.confirmed_rows.split(",")))}
    signed = {(k, int(v)) for k, v in signed}

    # A SANE ROW IS KEYED BY POSITION, AND POSITION IS NOT IDENTITY.
    # The sheets record (subtopic, seg). A precompute re-authors the SEGMENTS,
    # not just their payloads, so seg 3 after a sweep can be a different
    # segment. Measured 2026-09-16 after the 29-chapter sweep: of 86 judged n
    # rows, 14 still carry the same objective, 59 changed, and 13 no longer
    # exist at that index. Adopting a judgement about a segment that has since
    # been rewritten is adopting it about something nobody read.
    import difflib
    import re as _re

    def _norm(t):
        return _re.sub(r"\W+", " ", (t or "").lower()).strip()

    from app.drona.planner import WIDGET_PAYLOAD_KEY  # noqa: F401
    live = {}
    for pl in fetch_all("lesson_plans", "chapter_id,subtopic_key,plan_json"):
        if pl["chapter_id"] != ch["id"]:
            continue
        live[pl["subtopic_key"]] = (pl["plan_json"] or {}).get("segments") or []

    stale = []
    for r in rows:
        if (r["key"], r["seg"]) not in signed:
            continue
        segs = live.get(r["key"]) or next(
            (v for k, v in live.items()
             if k.startswith(r["key"]) or r["key"].startswith(k)), [])
        if not (1 <= r["seg"] <= len(segs)):
            stale.append((r, "that segment index no longer exists"))
            continue
        now, was = _norm(segs[r["seg"] - 1].get("objective")), _norm(r.get("objective"))
        if was and difflib.SequenceMatcher(None, was, now).ratio() <= 0.9:
            stale.append((r, f"objective changed since it was judged — now: {now[:70]}"))
    if stale:
        print(f"\nREFUSED: {len(stale)} signed row(s) no longer describe what was judged:")
        for r, why in stale:
            print(f"    {r['key']} seg{r['seg']} — {why}")
        print("\n  A SANE verdict is keyed by position, and a precompute re-authors the")
        print("  SEGMENTS. Re-review these against the current plan before signing them.")
        raise SystemExit(1)

    moved = [r for r in rows if (r["key"], r["seg"]) in signed]
    unknown = signed - {(r["key"], r["seg"]) for r in rows}

    print(f"chapter   {ch['name']}  ({ch['subject']} {ch['class_level']})")
    print(f"adopted   {cur['proposed_y']}/{cur['rows']} = {cur['sane_percent']}%  "
          f"({'clears' if cur['sane_percent'] >= doc['_bar_percent'] else 'held'})")
    print(f"proposal  {args.adopt}: {len(rows)} n rows classified")
    for k in ("i", "ii", "iii", "no-evidence"):
        n = sum(1 for r in rows if r["v2_kind"] == k)
        if n:
            print(f"            {k:<12} {n}")
    if unknown:
        raise SystemExit(f"\nREFUSED: --confirmed-rows names {len(unknown)} row(s) that "
                         f"are not proposed-n in this chapter: "
                         f"{', '.join(f'{k}:{s}' for k, s in sorted(unknown))}")
    if not signed:
        print("\nnothing to adopt: --confirmed-rows is empty.")
        print("A kind is not a verdict. (i) needs the routing harness re-run and the row")
        print("actually declining; (ii) needs re-authoring AND re-judging. Sign rows off")
        print("from the review sheet, then pass them here.")
        return 0

    new_y = cur["proposed_y"] + len(moved)
    new_pct = round(100.0 * new_y / cur["rows"], 1)
    print(f"\nwould move {len(moved)} row(s) to y:")
    for r in moved:
        print(f"    {r['key']} seg{r['seg']}  [{r['v2_kind']}]")
    print(f"\n  {cur['sane_percent']}% -> {new_pct}%  "
          f"({'CLEARS' if new_pct >= doc['_bar_percent'] else 'still held'} "
          f"the {doc['_bar_percent']}% bar)")
    print(f"  widgets in this chapter would "
          f"{'RESOLVE' if new_pct >= doc['_bar_percent'] else 'stay inert'} — no payload is "
          f"written or deleted either way; the gate is resolution-only.")

    if not args.execute:
        print("\nDRY RUN — content/sane-verdicts.json untouched.")
        return 0

    cur.update(proposed_y=new_y, proposed_n=cur["rows"] - new_y, sane_percent=new_pct,
               verdict_by=args.by, clears_bar=new_pct >= doc["_bar_percent"])
    cur["note"] = (f"Re-adopted {date.today()} from {args.adopt} by {args.by}: "
                   f"{len(moved)} row(s) signed off. " + cur.get("note", ""))[:900]
    VERDICTS.write_text(json.dumps(doc, indent=2))
    print(f"\nwrote {VERDICTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
