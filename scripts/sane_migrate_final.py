#!/usr/bin/env python3
"""THE LAST TIME sane_proposals.md IS EVER PARSED.

    python3 scripts/sane_migrate_final.py --write

After this runs, `content/sane-rows.json` is the only source of truth for SANE
verdicts and the markdown is a BUILD ARTEFACT rendered from it. Every
markdown-reading path is deleted in the same commit.

That inversion is not tidiness. Reading verdicts out of prose bit four times in
two sessions, and every failure had the same shape — a regex that matched
nothing and returned a clean empty result:

  * the row's key was built from the widget stored NOW, not the one judged;
  * `**objective:**` is lowercase in the chem sheet, so a case-sensitive match
    found ZERO objectives for physics and chem — 29 rows;
  * bio's table abbreviates the subtopic (`decomposition`) while its headers
    spell it out, so an exact lookup found 4 of 17;
  * three bio headers truncate the key outright (`ecological-succession-...`).

None raised. Each produced a confident, empty answer, which is the defect this
project keeps finding in other people's code.

This parse extracts EVERY judged row — y as well as n — because a store holding
only the n rows would silently drop 208 y verdicts the first time the sheet was
regenerated from it. It validates against each sheet's OWN stated counts and
refuses to write if they disagree.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

MD = REPO / "scripts/sane_proposals.md"
STORE = REPO / "content/sane-rows.json"

SHEETS = {
    "physics 12 ch1": ("physics", 12, "Electric Charges and Fields"),
    "maths 12 ch8": ("mathematics", 12, "Application of Integrals"),
    "chem 12 ch8": ("chemistry", 12, "Aldehydes, Ketones & Carboxylic Acids"),
    "biology 12 Ecosystem": ("biology", 12, "Ecosystem"),
}

#: "proposed y: 30 ; proposed n: 10 (of 40)" — the sheet's own arithmetic, used
#: as the check that this parse is COMPLETE rather than merely successful.
STATED = re.compile(r"proposed y:\s*(\d+)\s*;\s*proposed n:\s*(\d+)\s*\(of\s*(\d+)")


def section(md: str, title: str) -> str:
    start = md.index(f"# {title} — SANE proposals")
    rest = md[start + 10:]
    nxt = rest.find("\n# ")
    return md[start:start + 10 + nxt] if nxt > 0 else md[start:]


def rows_of(sec: str) -> list[dict]:
    """Every verdict row, both shapes, y and n alike."""
    out = []
    for line in sec.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        # shape A: subtopic | seg | widget | slot | verdict
        # shape B: # | subtopic | seg | widget | slot | verdict | in sheet?
        if len(cells) >= 7 and re.fullmatch(r"\d+", cells[0]):
            cells = cells[1:]
        if len(cells) < 5:
            continue
        key, seg, widget, slot, verdict = cells[0], cells[1], cells[2], cells[3], cells[4]
        if not re.fullmatch(r"[a-z0-9\-]+(?:\.{3})?", key) or not re.fullmatch(r"\d+", seg):
            continue
        v = verdict.strip()
        is_n = bool(re.match(r"\*{0,2}n\b", v, re.I))
        is_y = bool(re.fullmatch(r"\*{0,2}y\*{0,2}", v, re.I))
        if not (is_n or is_y):
            continue
        out.append({"subtopic_key": key.rstrip("."), "legacy_segment_index": int(seg),
                    "widget_sheet": widget, "slot": slot,
                    "verdict": "n" if is_n else "y",
                    "verdict_cell": v})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--i-have-restored-the-parsers", action="store_true",
                    help=argparse.SUPPRESS)
    args = ap.parse_args()

    # THIS HAS ALREADY RUN AND CANNOT RUN AGAIN.
    # The markdown parsers it depends on were deleted in the same commit that
    # made the store authoritative — which is the point: there is no path back
    # to prose being the source. The file is kept because it is the audit trail
    # for how 294 verdicts got their keys, not because it is still callable.
    if STORE.exists() and not args.i_have_restored_the_parsers:
        print("REFUSED: content/sane-rows.json already exists.")
        print("  This migration ran once, on 2026-09-17, and the markdown parsers it")
        print("  needed were deleted with it. The store is the source of truth now;")
        print("  edit it directly and re-render with scripts/render_sane_sheet.py.")
        return 1

    from scripts.sane_review_sheet import OBJECTIVES, full_reasons
    from scripts.sane_rows import (judged_widget, live_segments, normalise,
                                   objective_sha, verdict_key, widget_of, _word_diff)
    import difflib

    md = MD.read_text()
    all_rows, problems = [], []
    for sheet, (subject, level, chapter) in SHEETS.items():
        sec = section(md, sheet)
        rows = rows_of(sec)
        prose = full_reasons(sheet)

        def resolve(store, key, seg):
            if (key, seg) in store:
                return store[(key, seg)]
            for (k2, s2), val in store.items():
                if s2 == seg:
                    a, b = k2.rstrip("."), key.rstrip(".")
                    if a.startswith(b) or b.startswith(a):
                        return val
            return ""

        m = STATED.search(sec)
        if m:
            want_y, want_n, want_tot = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            got_y = sum(1 for r in rows if r["verdict"] == "y")
            got_n = sum(1 for r in rows if r["verdict"] == "n")
            if (got_y, got_n, got_y + got_n) != (want_y, want_n, want_tot):
                problems.append(f"{sheet}: sheet states y={want_y} n={want_n} of {want_tot}, "
                                f"parsed y={got_y} n={got_n} of {got_y + got_n}")
        for r in rows:
            r.update(sheet=sheet, subject=subject, class_level=level, chapter=chapter,
                     objective=resolve(OBJECTIVES, r["subtopic_key"], r["legacy_segment_index"]),
                     reason=(resolve(prose, r["subtopic_key"], r["legacy_segment_index"])
                             if r["verdict"] == "n" else ""))
        all_rows += rows

    if problems:
        print("REFUSED — the parse does not agree with the sheets' own counts:")
        for p in problems:
            print(f"   {p}")
        print("\n  A partial parse written as the source of truth would lose verdicts")
        print("  silently, which is the whole failure this migration exists to end.")
        return 1

    print(f"parsed {len(all_rows)} judged rows, and every sheet's own counts agree\n")
    live = live_segments()
    present, present_obj = {}, set()
    for (chapter, subtopic), segs in live.items():
        for i, s in enumerate(segs, 1):
            present.setdefault(verdict_key(s.get("objective") or "", widget_of(s)), []).append(
                {"chapter": chapter, "subtopic_key": subtopic, "segment_index": i})
            present_obj.add(normalise(s.get("objective") or ""))

    buckets = {"carried": [], "reconfirm": [], "superseded": [], "unkeyable": []}
    for r in all_rows:
        widget = judged_widget(r["widget_sheet"])
        entry = dict(r, widget_id=widget,
                     objective_sha=objective_sha(r["objective"]),
                     verdict_key=verdict_key(r["objective"], widget),
                     legacy_key=f"{r['subtopic_key']}:{r['legacy_segment_index']}")
        if not normalise(r["objective"]):
            entry["why"] = "the sheet does not record the objective that was judged"
            buckets["unkeyable"].append(entry); continue
        if entry["verdict_key"] in present:
            entry["found_at"] = present[entry["verdict_key"]]
            buckets["carried"].append(entry); continue
        best, ratio = "", 0.0
        for cand in present_obj:
            rr = difflib.SequenceMatcher(None, normalise(r["objective"]), cand).ratio()
            if rr > ratio:
                best, ratio = cand, rr
        if ratio > 0.9:
            entry.update(reconfirm_against=best, similarity=round(ratio, 3),
                         changed_words=_word_diff(normalise(r["objective"]), best))
            buckets["reconfirm"].append(entry)
        else:
            entry.update(superseded_on=str(date.today()), closest_similarity=round(ratio, 3))
            buckets["superseded"].append(entry)

    for k, v in buckets.items():
        ny = sum(1 for e in v if e["verdict"] == "n")
        print(f"  {k:<12} {len(v):>4}   ({ny} of them n)")

    if args.write:
        STORE.write_text(json.dumps({
            "_what": ("THE source of truth for SANE verdicts. scripts/sane_proposals.md and "
                      "every review sheet are RENDERED from this file and are never parsed. "
                      "Edit here; regenerate the markdown."),
            "_key": "verdict_key = sha256(normalised objective)[:16] + ':' + widget_id",
            "_migrated_on": str(date.today()),
            "_counts": {k: len(v) for k, v in buckets.items()},
            "_unkeyable_note": (
                "210 rows carry no objective because the sheets quote one only in the "
                "per-row prose sections, and those exist only for n rows. 206 of the 210 "
                "are y verdicts. They are ARCHIVE: we know the subtopic, the index and "
                "that a reviewer said y, and we cannot tie that to a current question. "
                "They drive nothing — the hold-back reads the chapter percentage, which "
                "lives in content/sane-verdicts.json — so nothing is lost by not "
                "re-judging them. The 4 unkeyable n rows are archived on Raasikh's line "
                "of 2026-09-17."),
            **buckets,
        }, indent=1))
        print(f"\nwrote {STORE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
