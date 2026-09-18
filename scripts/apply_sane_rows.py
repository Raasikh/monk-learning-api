#!/usr/bin/env python3
"""J5 — adopt a chapter's SANE proposals by one confirmation line.

    python3 scripts/apply_sane_rows.py --chapter "Ecosystem" \
        --confirmation "confirmed: Ecosystem, sane verdicts as proposed except n: <sha>,<sha>, verdict_by raasikh"
    ... --execute

The line names the chapter, adopts the proposals as they stand, and lists the
`objective_sha` of any row Raasikh disagrees with — those become n whatever the
proposal said. Everything else takes the proposal's verdict.

Rows are written to `sane_row_verdicts`, keyed by `objective_sha:widget_id`.
A key that no longer matches a live segment is REFUSED by name rather than
written: a verdict about a question nobody is asking any more is not a verdict,
and this is the failure that voided 72 of 86 judgements on 2026-09-15.

The chapter percentage is recomputed from the adopted rows and written to
`chapters.sane_percent`, so the hold-back in `resolve_board_slot` serves that
chapter's widgets the same minute — no regeneration, because nothing about the
plans changed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
STORE = REPO / "content/sane-rows.json"

LINE = re.compile(r"confirmed:\s*(?P<chapter>[^,]+),\s*sane verdicts as proposed"
                  r"(?:\s*except\s*n:\s*(?P<except>[0-9a-f,\s]*))?,\s*"
                  r"verdict_by\s+(?P<by>\w+)", re.I)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", required=True)
    ap.add_argument("--confirmation", required=True,
                    help="Raasikh's own line, quoted")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    m = LINE.search(args.confirmation)
    if not m:
        raise SystemExit(
            "REFUSED: the confirmation does not parse. Expected:\n"
            '  confirmed: <chapter>, sane verdicts as proposed except n: <sha>,<sha>, '
            'verdict_by raasikh')
    if m.group("chapter").strip().lower() != args.chapter.strip().lower():
        raise SystemExit(f"REFUSED: --chapter {args.chapter!r} but the line names "
                         f"{m.group('chapter').strip()!r}")
    overrides = {s.strip() for s in (m.group("except") or "").split(",") if s.strip()}
    by = m.group("by")

    from app.db import fetch_all, get_supabase
    from scripts.sane_rows import normalise, verdict_key, widget_of

    doc = json.loads(STORE.read_text())
    rows = [r for r in doc.get("proposals_2026_09_17", [])
            if r["chapter"].lower() == args.chapter.strip().lower()]
    if not rows:
        raise SystemExit(f"REFUSED: no proposals for {args.chapter!r}. A chapter with "
                         f"nothing to adopt is a typo, not an empty adoption.")

    # every (objective_sha:widget) the corpus is asking RIGHT NOW
    chapters = {c["id"]: c for c in fetch_all("chapters", "id,name,subject,class_level")}
    live = set()
    for p in fetch_all("lesson_plans", "chapter_id,subtopic_key,plan_json"):
        ch = chapters.get(p["chapter_id"])
        if not ch or ch["name"].lower() != args.chapter.strip().lower():
            continue
        for s in (p["plan_json"] or {}).get("segments") or []:
            live.add(verdict_key(s.get("objective") or "", widget_of(s)))

    stale = [r for r in rows if r["verdict_key"] not in live]
    unknown = overrides - {r["objective_sha"] for r in rows}
    if unknown:
        raise SystemExit(f"REFUSED: the line excepts {len(unknown)} sha(s) that are not "
                         f"in this chapter's proposals: {', '.join(sorted(unknown))}")

    adopted = []
    for r in rows:
        if r["verdict_key"] not in live:
            continue
        v = "n" if r["objective_sha"] in overrides else r["verdict"]
        adopted.append(dict(r, verdict=v,
                            overridden=r["objective_sha"] in overrides))

    y = sum(1 for a in adopted if a["verdict"] == "y")
    pct = round(100.0 * y / len(adopted), 2) if adopted else 0.0
    print(f"{args.chapter}")
    print(f"  proposals            {len(rows)}")
    print(f"  stale, refused       {len(stale)}")
    print(f"  overridden to n      {len(overrides)}")
    print(f"  adopted              {len(adopted)}   y={y}  n={len(adopted)-y}")
    print(f"  sane_percent         {pct}%   -> widgets "
          f"{'RESOLVE' if pct >= 85 else 'stay held'}")
    if stale:
        print(f"\n  refused as stale (the question is no longer asked):")
        for r in stale[:8]:
            print(f"    {r['subtopic_key'][:40]:<40} seg{r['legacy_segment_index']}")
        if len(stale) > 8:
            print(f"    … and {len(stale) - 8} more")

    if not args.execute:
        print("\nDRY RUN — sane_row_verdicts untouched, chapters.sane_percent untouched.")
        return 0

    sb = get_supabase()
    payload = [{
        "objective_sha": a["objective_sha"], "widget_id": a["widget_id"],
        "verdict_key": a["verdict_key"], "subject": a["subject"],
        "class_level": a["class_level"], "chapter": a["chapter"],
        "subtopic_key": a["subtopic_key"], "objective": a["objective"],
        "verdict": a["verdict"], "bucket": "carried",
        "reason": a.get("reason") or None, "verdict_by": by,
        "legacy_key": f"{a['subtopic_key']}:{a['legacy_segment_index']}",
    } for a in adopted]
    for i in range(0, len(payload), 200):
        sb.table("sane_row_verdicts").upsert(
            payload[i:i + 200], on_conflict="verdict_key").execute()
    cid = next((c["id"] for c in chapters.values()
                if c["name"].lower() == args.chapter.strip().lower()), None)
    sb.table("chapters").update({
        "sane_percent": pct, "sane_rows": len(adopted), "sane_y": y,
        "sane_n": len(adopted) - y, "sane_verdict_by": by,
        "sane_source": "content/sane-rows.json proposals_2026_09_17",
    }).eq("id", cid).execute()
    print(f"\n  wrote {len(payload)} row(s); chapters.sane_percent = {pct}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
