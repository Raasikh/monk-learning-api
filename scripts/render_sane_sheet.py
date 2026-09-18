#!/usr/bin/env python3
"""content/sane-rows.json -> scripts/sane_proposals.md. One direction only.

    python3 scripts/render_sane_sheet.py --write
    python3 scripts/render_sane_sheet.py --check     # CI / test use

The markdown is a BUILD ARTEFACT. Nothing reads it; editing it by hand is a
mistake the `--check` mode catches, because the rendered bytes will no longer
match the file on disk.

Rendering is deterministic: rows are sorted by (sheet order, subtopic,
segment index) and every field is written in a fixed order, so the same store
always produces the same bytes. `--check` is exactly that claim, which is why
it can be a test.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STORE = REPO / "content/sane-rows.json"
OUT = REPO / "scripts/sane_proposals.md"

SHEET_ORDER = ["physics 12 ch1", "maths 12 ch8", "chem 12 ch8", "biology 12 Ecosystem"]
BUCKETS = ["carried", "reconfirm", "superseded", "unkeyable"]


def load() -> tuple[dict, list[dict]]:
    doc = json.loads(STORE.read_text())
    rows = []
    for b in BUCKETS:
        for e in doc.get(b, []):
            rows.append(dict(e, bucket=b))
    return doc, rows


def render() -> str:
    doc, rows = load()
    L: list[str] = []
    w = L.append

    w("# SANE proposals")
    w("")
    w("> **GENERATED FILE — do not edit.** The source of truth is")
    w("> `content/sane-rows.json`; this is rendered from it by")
    w("> `scripts/render_sane_sheet.py`. Nothing parses this file.")
    w(">")
    w("> It used to be the other way round, and reading verdicts out of prose")
    w("> failed four times in two sessions — a widget read from the wrong place,")
    w("> a lowercase `**objective:**`, an abbreviated subtopic, a truncated key.")
    w("> Every one returned a confident empty result rather than raising.")
    w("")
    w(f"Migrated {doc.get('_migrated_on')}. Key: `{doc.get('_key')}`.")
    w("")

    w("## Buckets")
    w("")
    w("| bucket | rows | y | n | meaning |")
    w("|---|---|---|---|---|")
    meaning = {
        "carried": "same question, same widget — the verdict still applies",
        "reconfirm": "reworded; the changed words are listed per row",
        "superseded": "the question is no longer asked anywhere",
        "unkeyable": "the sheet never recorded the objective — archive",
    }
    for b in BUCKETS:
        rs = [r for r in rows if r["bucket"] == b]
        w(f"| {b} | {len(rs)} | {sum(1 for r in rs if r['verdict'] == 'y')} | "
          f"{sum(1 for r in rs if r['verdict'] == 'n')} | {meaning[b]} |")
    w("")
    if doc.get("_unkeyable_note"):
        w(f"{doc['_unkeyable_note']}")
        w("")

    for sheet in SHEET_ORDER:
        srows = sorted((r for r in rows if r["sheet"] == sheet),
                       key=lambda r: (r["subtopic_key"], r["legacy_segment_index"]))
        if not srows:
            continue
        ys = sum(1 for r in srows if r["verdict"] == "y")
        ns = sum(1 for r in srows if r["verdict"] == "n")
        w(f"## {sheet} — {srows[0]['chapter']}")
        w("")
        w(f"proposed y: {ys} ; proposed n: {ns} (of {len(srows)})")
        w("")
        w("| subtopic_key | seg | widget judged | verdict | bucket | verdict_key |")
        w("|---|---|---|---|---|---|")
        for r in srows:
            w(f"| {r['subtopic_key']} | {r['legacy_segment_index']} | {r['widget_id']} | "
              f"{r['verdict']} | {r['bucket']} | `{r['verdict_key']}` |")
        w("")
        nrows = [r for r in srows if r["verdict"] == "n" and r["bucket"] != "unkeyable"]
        if nrows:
            w(f"### the {len(nrows)} n rows that can still be acted on")
            w("")
            for r in nrows:
                w(f"#### `{r['subtopic_key']}` seg {r['legacy_segment_index']} — {r['bucket']}")
                w("")
                w(f"**objective:** {r['objective']}")
                w("")
                w(f"**widget judged:** `{r['widget_id']}`")
                w("")
                if r.get("changed_words"):
                    diffs = "; ".join(f"`{d['was']}` -> `{d['now']}`"
                                      for d in r["changed_words"] if d["was"] or d["now"])
                    w(f"**reworded ({r.get('similarity')}):** {diffs}")
                    w("")
                if r.get("reason"):
                    w(f"**reason:** {r['reason']}")
                    w("")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = render()
    if args.check:
        on_disk = OUT.read_text() if OUT.exists() else ""
        if on_disk != text:
            print("sane_proposals.md does NOT match content/sane-rows.json.")
            print("It is a generated file: edit the store and re-render, do not edit it.")
            print("  python3 scripts/render_sane_sheet.py --write")
            return 1
        print("sane_proposals.md matches the store byte-for-byte")
        return 0
    if args.write:
        OUT.write_text(text)
        print(f"wrote {OUT} ({len(text)} bytes)")
    else:
        sys.stdout.write(text[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
