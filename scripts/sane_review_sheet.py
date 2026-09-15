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
import textwrap
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


def n_rows(sheet_title: str):
    """(subtopic_key, seg, widget, reason) for every proposed-n row in a sheet."""
    md = (REPO / "scripts/sane_proposals.md").read_text()
    start = md.index(f"# {sheet_title} — SANE proposals")
    rest = md[start + 10:]
    nxt = rest.find("\n# ")
    sec = md[start:start + 10 + nxt] if nxt > 0 else md[start:]
    # TWO TABLE SHAPES, because the sheets were written at different times and
    # neither is wrong. physics/chem/maths put the reason in the verdict cell
    # (`**n — the arrow ends on the reagent**`); bio numbers its rows and puts a
    # bare `n (b)` in a verdict column of its own. Parsing only the first shape
    # silently returned ZERO bio rows — for the chapter that needs seven — which
    # is the check-that-passes-on-absent-information defect in a report
    # generator.
    out = []
    for line in sec.splitlines():
        m = re.match(r"\|\s*([a-z0-9\-]+)\s*\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|"
                     r"\s*\*\*n\s*[—-]?\s*(.+?)\*\*\s*\|", line)
        if m:
            out.append((m.group(1), int(m.group(2)), m.group(3).strip(),
                        re.sub(r"\s+", " ", m.group(5).strip())))
            continue
        m = re.match(r"\|\s*\d+\s*\|\s*([a-z0-9\-]+)\s*\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|"
                     r"\s*([^|]+?)\s*\|\s*n\s*(\([abc]\))?\s*\|", line)
        if m:
            out.append((m.group(1), int(m.group(2)), m.group(3).strip(),
                        f"criterion {m.group(4) or '(unstated)'}".replace("criterion ", "")
                        if False else (m.group(4) or "n")))
    if not out:
        raise SystemExit(f"parsed ZERO n rows out of {sheet_title!r} — the table shape "
                         f"changed and this would have produced an empty sheet")
    return out


def full_reasons(sheet_title: str) -> dict:
    """The PROSE reason, from the sheet's "Every proposed n, in full" section.

    The verdict cell in the table carries only a criterion letter — `(a)+(b)`
    — which tells a reviewer nothing they can act on. The paragraph that says
    WHY lives further down under `### 7. gauss-s-law… seg 3`. Keyed
    (subtopic, seg) so a row can pick up its own.
    """
    md = (REPO / "scripts/sane_proposals.md").read_text()
    start = md.index(f"# {sheet_title} — SANE proposals")
    rest = md[start + 10:]
    nxt = rest.find("\n# ")
    sec = md[start:start + 10 + nxt] if nxt > 0 else md[start:]
    out = {}
    # THREE HEADER SHAPES across the four sheets, and matching only the first
    # returned prose for physics and NOTHING for chem or maths — a review page
    # whose reason column said "(a)+(b)" and nothing else.
    #   physics:  ### 1. electric-field seg 4 — "…"
    #   chem/maths: ### n-1. `preparation-of-aldehydes` seg 1 — "…"
    #   bio:      grouped sections, no per-row prose at all; those keep the
    #             criterion letter from the table, which is all that exists.
    #   maths:    ### idx 0 — area-between-a-function… / seg 1 — …
    pat = (r"^###\s*(?:n-)?\d+\.\s*`?([a-z0-9\-]+)`?\s+seg\s*(\d+)(.*?)(?=^###|\Z)",
           r"^###\s*idx\s*\d+\s*[—-]\s*([a-z0-9\-]+)\s*/\s*seg\s*(\d+)(.*?)(?=^###|\Z)")
    matches = []
    for pp in pat:
        matches += list(re.finditer(pp, sec, re.M | re.S))
    for m in matches:
        key, seg, body = m.group(1), int(m.group(2)), m.group(3)
        r = re.search(r"\*\*Reason\s*[—-]\s*(.+?)\*\*\s*(.*?)(?=\n\*\*|\Z)", body, re.S)
        if r:
            prose = re.sub(r"\s+", " ", (r.group(1) + " " + r.group(2))).strip()
        else:
            prose = re.sub(r"\s+", " ", body).strip()
        out[(key, seg)] = prose[:700]
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
    for title, (subj, cls, chname) in targets:
        cid = by_chapter.get((subj, cls, chname))
        rows = n_rows(title)
        prose = full_reasons(title)
        print(f"{title:<24} {len(rows)} n rows, {len(prose)} with a written reason", flush=True)
        for key, seg, widget, reason in rows:
            pl = plan_idx.get((cid, key))
            objective, params, stored_widget = "", None, None
            if pl:
                segs = (pl["plan_json"] or {}).get("segments") or []
                if 1 <= seg <= len(segs):
                    s = segs[seg - 1]
                    objective = str(s.get("objective") or "")
                    pay = s.get(WIDGET_PAYLOAD_KEY)
                    if isinstance(pay, dict):
                        params, stored_widget = pay.get("params"), pay.get("widget")
            rid = f"{title.replace(' ', '_')}__{key}__seg{seg}"
            if params and stored_widget:
                jobs.append({"id": rid, "widget": stored_widget, "params": params})
            meta.append({"sheet": title, "chapter": chname, "id": rid, "key": key,
                         "seg": seg, "widget_sheet": widget,
                         "widget_stored": stored_widget, "reason": reason,
                         "objective": objective, "has_payload": bool(params)})

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
