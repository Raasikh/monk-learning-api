#!/usr/bin/env python3
"""Segment options out of question_text when the markers are all there (§2).

Dev-time script — deterministic, no LLM calls. Many rows carry the full
"(1) .. (2) .. (3) .. (4) .." option grid inside question_text because the
block parser never split it. This is segmentation, not generation:

- find the last ordered run of four markers (A-D or 1-4) in the text
- stem = text before the run; options = the four segments between markers
- HARD CONSTRAINT: every emitted option string must appear VERBATIM as a
  substring of the source text — asserted in code; failures are quarantined
  as ``options_segment_assert_failed`` and never shipped
- empty segments mean the options were printed as images; the row keeps
  ``options_segment_image_only`` and its stem is still cleaned
- ``option_source: text_segmentation`` recorded on success
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "nta_raw"
SOURCES = [
    "diagram_questions.jsonl",
    "examside_diagram_questions.jsonl",
    "examside_diagram_questions_jee_advanced.jsonl",
    "neet_mathongo_questions.jsonl",
]

MARK = re.compile(r"\(([A-D1-4])\)\s*")
TRAIL_RE = re.compile(r"(?mi)^\s*(Sol\.|Solution|Ans\.|Official\s+Ans|Answer\b|Correct\s+(?:Answer|Option)|Q\d{1,3}\.)")


def opt_have(row: dict) -> int:
    opts = row.get("options")
    n = sum(1 for v in opts.values() if str(v).strip()) if isinstance(opts, dict) else 0
    imgs = row.get("option_images")
    if isinstance(imgs, dict):
        n = max(n, sum(1 for v in imgs.values() if str(v).strip()))
    return n


def segment(text: str) -> tuple[str, dict | None, str | None]:
    """Return (stem, options|None, mode). mode: 'text'|'image_only'|None."""
    marks = [(m.group(1), m.start(), m.end()) for m in MARK.finditer(text)]
    # last ordered run of 4 markers (A-D or 1-4, in order)
    run = None
    for i in range(len(marks) - 3):
        quad = marks[i:i + 4]
        labels = [q[0] for q in quad]
        if labels == ["A", "B", "C", "D"] or labels == ["1", "2", "3", "4"]:
            run = quad  # keep the LAST valid run
    if not run:
        return text, None, None
    stem = text[: run[0][1]].strip()
    segs = []
    for j in range(4):
        start = run[j][2]
        end = run[j + 1][1] if j < 3 else len(text)
        seg = text[start:end]
        # cut trailing solution/answer/next-question material from option D
        if j == 3:
            tm = TRAIL_RE.search(seg)
            if tm:
                seg = seg[: tm.start()]
        segs.append(seg.strip())
    labels = [q[0] for q in run]
    keys = "ABCD"
    options = {k: s for k, s in zip(keys, segs)}
    if all(not s for s in segs):
        return stem, None, "image_only"
    if any(not s for s in segs):
        return stem, None, None  # partial — unusable
    return stem, options, "text"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    stats = Counter()
    for name in SOURCES:
        src = DATA / name
        if not src.exists():
            continue
        rows = []
        for line in src.open():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
        for row in rows:
            if opt_have(row) >= 4 or row.get("question_type") == "numerical":
                continue
            text = row.get("question_text") or ""
            if not text:
                continue
            stem, options, mode = segment(text)
            if mode is None and options is None:
                continue
            if mode == "image_only":
                if stem != text:
                    row["question_text"] = stem
                    row["options_segment_image_only"] = True
                    stats["image_only"] += 1
                continue
            # verbatim assertion: every emitted option must be a substring of source
            if not all(v and v in text for v in options.values()):
                row["needs_manual"] = "options_segment_assert_failed"
                stats["assert_failed"] += 1
                continue
            row["question_text"] = stem
            row["options"] = options
            row["option_source"] = "text_segmentation"
            if row.get("question_type") in (None, "type_underivable"):
                row["question_type"] = "single_correct"
            stats["segmented"] += 1
        if args.write:
            src.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"[segment-options] {dict(stats)}")
    if not args.write:
        print("[segment-options] dry run — pass --write")


if __name__ == "__main__":
    main()
