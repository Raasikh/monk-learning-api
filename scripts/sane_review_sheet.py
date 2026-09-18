#!/usr/bin/env python3
"""One page per chapter of ONLY the rows a reviewer has to look at.

    python3 scripts/sane_review_sheet.py --chapter "Electric Charges and Fields"
    python3 scripts/sane_review_sheet.py --all

The full SANE sheet is 294 rows across four chapters and nobody reads it. What
raises a chapter is the `n` rows, and only those: physics needs 2 more y, bio
needs 7. So this puts, for each proposed-n row, the four things a judgement
needs side by side —

    the objective, quoted from the plan
    the widget that was chosen
    the payload AS IT RENDERS at 343x236, the size a student sees it
    the proposal's own reason for saying n

— and nothing else. A reviewer reads one page and writes y or n beside each.

The render comes from the REAL widget module via
lib/widgets/__tests__/emit-review-svgs, so the picture on the sheet is the
picture on the board. A sheet that drew its own approximation would be asking
for a judgement about the wrong thing.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MOB = Path("/Users/raasikhnaveed/Desktop/monk-learning-mobile/monklearning-mobile")
sys.path.insert(0, str(REPO))

SHEETS = {
    "physics 12 ch1":   ("physics", 12, "Electric Charges and Fields"),
    "chem 12 ch8":      ("chemistry", 12, "Aldehydes, Ketones & Carboxylic Acids"),
    "maths 12 ch8":     ("mathematics", 12, "Application of Integrals"),
    "biology 12 Ecosystem": ("biology", 12, "Ecosystem"),
}


def store_rows() -> list[dict]:
    """The n rows that can still be acted on, from the STORE.

    This file used to parse `sane_proposals.md` with three header regexes and a
    table regex. They were wrong four times and every failure was silent, so
    the direction is now inverted: the store is the source and the markdown is
    rendered from it. `unkeyable` rows are excluded — nothing records what
    question they judged, so there is nothing to put on a review page.
    """
    doc = json.loads((REPO / "content/sane-rows.json").read_text())
    out = []
    for bucket in ("carried", "reconfirm", "superseded"):
        for e in doc.get(bucket, []):
            if e.get("verdict") == "n":
                out.append(dict(e, bucket=bucket))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--chapter", default="")
    args = ap.parse_args()

    from app.db import fetch_all
    from app.drona.planner import WIDGET_PAYLOAD_KEY

    chapters = fetch_all("chapters", "id,name,subject,class_level")
    plans = fetch_all("lesson_plans", "chapter_id,subtopic_key,plan_json")
    by_chapter = {}
    for c in chapters:
        by_chapter[(c["subject"], c["class_level"], c["name"])] = c["id"]
    plan_idx = {(p["chapter_id"], p["subtopic_key"]): p for p in plans}

    targets = list(SHEETS.items())
    if args.chapter:
        targets = [(k, v) for k, v in targets if v[2] == args.chapter]
    if not targets:
        raise SystemExit(f"no sheet for {args.chapter!r}; have {[v[2] for v in SHEETS.values()]}")

    jobs, meta = [], []
    rows = [r for r in store_rows()
            if not targets or r["chapter"] in {t[1][2] for t in targets}]
    print(f"{len(rows)} actionable n rows from content/sane-rows.json", flush=True)
    for r in rows:
        key, seg, chname = r["subtopic_key"], r["legacy_segment_index"], r["chapter"]
        cid = by_chapter.get((r["subject"], r["class_level"], chname))
        # The CURRENT payload at that position, only so the reviewer can see
        # what is on the board now. It is NOT what keys the row — the key is
        # the objective the reviewer read, which the store carries.
        pl = plan_idx.get((cid, key))
        if pl is None:
            for (c2, k2), cand in plan_idx.items():
                if c2 == cid and (k2.startswith(key) or key.startswith(k2)):
                    pl = cand
                    break
        params, stored_widget = None, None
        if pl:
            segs = (pl["plan_json"] or {}).get("segments") or []
            if 1 <= seg <= len(segs):
                pay = segs[seg - 1].get(WIDGET_PAYLOAD_KEY)
                if isinstance(pay, dict):
                    params, stored_widget = pay.get("params"), pay.get("widget")
        rid = f"{r['sheet'].replace(' ', '_')}__{key}__seg{seg}"
        if params and stored_widget:
            jobs.append({"id": rid, "widget": stored_widget, "params": params})
        meta.append({"sheet": r["sheet"], "chapter": chname, "id": rid, "key": key,
                     "seg": seg, "widget_sheet": r["widget_id"],
                     "widget_stored": stored_widget, "bucket": r["bucket"],
                     "verdict_key": r["verdict_key"],
                     "changed_words": r.get("changed_words") or [],
                     "reason": r.get("reason") or "",
                     "objective": r["objective"],
                     "objective_source": "content/sane-rows.json",
                     "has_payload": bool(params)})

    jobf = Path("/tmp/sane-review-job.json"); jobf.write_text(json.dumps(jobs))
    out = Path("/tmp/sane-review-svgs")
    print(f"\nrendering {len(jobs)} payloads through the real widget modules…", flush=True)
    r = subprocess.run(["npx", "jest", "emit-review-svgs"], cwd=str(MOB),
                       capture_output=True, text=True,
                       env={**__import__("os").environ, "REVIEW_JOB": str(jobf),
                            "REVIEW_OUT": str(out)})
    print("   " + next((l for l in (r.stderr + r.stdout).splitlines()
                        if "emitted" in l), "render step produced no summary"))
    Path("/tmp/sane-review-meta.json").write_text(json.dumps(meta, indent=1))
    print(f"\nmeta -> /tmp/sane-review-meta.json   svgs -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
