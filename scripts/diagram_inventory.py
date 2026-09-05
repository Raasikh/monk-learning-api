#!/usr/bin/env python3
"""Unified diagram-question inventory across all raw sources.

Reads the durable JSONL artifacts produced by the PDF/OCR pipeline and HTML
scrapers, checks the required field contract, and writes reports/diagram_inventory.md.
No network, no LLM, no DB writes.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "nta_raw"
REPORT = ROOT / "reports" / "diagram_inventory.md"

SOURCES = [
    DATA / "diagram_questions.jsonl",
    DATA / "neet_mathongo_questions.jsonl",
] + sorted(DATA.glob("examside_diagram_questions*.jsonl"))

REQUIRED = [
    "diagram_question_id", "exam", "exam_tag", "tags", "question_text",
    "answer_sheet", "source_tier", "source_site", "source_page_url",
    "has_figure", "needs_manual",
]


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def has_image_ref(r: dict) -> bool:
    return bool(
        r.get("diagram_asset")
        or r.get("diagram_assets")
        or r.get("diagram_image_urls")
        or r.get("diagram_bbox")
    )


def main() -> None:
    rows = []
    per_source = {}
    for path in SOURCES:
        rs = load(path)
        per_source[path.name] = len(rs)
        rows.extend(rs)
    missing = collections.Counter()
    for r in rows:
        for field in REQUIRED:
            value = r.get(field)
            if value is None or value == "" or value == []:
                missing[field] += 1
        if not has_image_ref(r):
            missing["image_ref"] += 1
    by_exam = collections.Counter(r.get("exam") for r in rows)
    by_subject = collections.Counter(r.get("subject") for r in rows)
    by_answer = collections.Counter((r.get("answer_sheet") or {}).get("status") for r in rows)
    with_options = sum(1 for r in rows if r.get("options"))
    with_assets = sum(1 for r in rows if r.get("diagram_asset") or r.get("diagram_assets"))

    lines = [
        "# Diagram question inventory",
        "",
        f"- total diagram questions: {len(rows)}",
        f"- target: 10000",
        f"- remaining to target: {max(0, 10000 - len(rows))}",
        f"- with options: {with_options}",
        f"- with downloaded assets: {with_assets}",
        f"- with any image reference: {len(rows) - missing['image_ref']}",
        "",
        "## By source file",
        "",
    ]
    lines += [f"- {name}: {n}" for name, n in per_source.items()]
    lines += ["", "## By exam", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(by_exam.items(), key=lambda kv: str(kv[0]))]
    lines += ["", "## By subject", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(by_subject.items(), key=lambda kv: str(kv[0]))]
    lines += ["", "## Answer-sheet status", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(by_answer.items(), key=lambda kv: str(kv[0]))]
    lines += ["", "## Missing required fields", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(missing.items())] or ["- none"]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n")
    print(f"[inventory] {len(rows)} diagram questions -> {REPORT}")
    if missing:
        print("[inventory] missing fields:", dict(missing))


if __name__ == "__main__":
    main()
