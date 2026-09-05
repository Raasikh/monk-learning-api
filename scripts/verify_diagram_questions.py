#!/usr/bin/env python3
"""Deterministic verification for raw diagram-question JSONL artifacts.

No network, no LLM, no DB writes. This is the raw-layer lint that runs before the
LLM quality gate. It checks required provenance/tag/answer fields and that any
downloaded diagram asset exists and opens as an image.
"""

from __future__ import annotations

import collections
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "nta_raw"
REPORT = ROOT / "reports" / "diagram_verify.md"

SOURCES = [
    DATA / "diagram_questions.jsonl",
    DATA / "neet_mathongo_questions.jsonl",
] + sorted(DATA.glob("examside_diagram_questions*.jsonl"))

REQUIRED = ["diagram_question_id", "exam", "exam_tag", "tags", "question_text",
            "answer_sheet", "source_tier", "source_site", "source_page_url",
            "has_figure", "needs_manual"]
META_OPTION = ("the trap", "the answer is", "explanation:", "students fixate")


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def asset_paths(row: dict) -> list[str]:
    paths = []
    if row.get("diagram_asset") and row["diagram_asset"].get("path"):
        paths.append(row["diagram_asset"]["path"])
    for a in row.get("diagram_assets") or []:
        if a.get("path"):
            paths.append(a["path"])
    return paths


def verify_row(row: dict) -> list[str]:
    problems = []
    for field in REQUIRED:
        if row.get(field) in (None, "", []):
            problems.append(f"missing_{field}")
    if not (row.get("diagram_asset") or row.get("diagram_assets") or row.get("diagram_image_urls") or row.get("diagram_bbox")):
        problems.append("missing_image_ref")
    options = row.get("options")
    if options is not None:
        vals = [str(v).strip() for v in options.values()]
        if len([v for v in vals if v]) < 4:
            problems.append("options_missing_or_incomplete")
        norm = [re.sub(r"\W+", "", v.lower()) for v in vals if v]
        if len(norm) >= 4 and len(set(norm)) < len(norm):
            problems.append("duplicate_options")
        if any(any(m in v.lower() for m in META_OPTION) for v in vals):
            problems.append("option_meta_text")
    else:
        problems.append("options_missing")
    sheet = row.get("answer_sheet") or {}
    for entry in sheet.get("entries") or []:
        ans = (entry or {}).get("answer") or {}
        opt = ans.get("option")
        if opt is not None and opt not in ("A", "B", "C", "D"):
            problems.append("bad_answer_option")
    for rel in asset_paths(row):
        path = ROOT / rel
        if not path.exists():
            problems.append("asset_missing")
            continue
        try:
            head = path.read_bytes()[:200].lstrip()
            if path.suffix.lower() == ".svg" or head.startswith(b"<svg"):
                continue
            from PIL import Image
            with Image.open(path) as img:
                img.verify()
        except Exception:
            problems.append("asset_unreadable")
    return list(dict.fromkeys(problems))


def main() -> None:
    import re
    rows = []
    for path in SOURCES:
        rows.extend(load(path))
    counts = collections.Counter()
    examples = collections.defaultdict(list)
    for row in rows:
        problems = verify_row(row)
        if not problems:
            counts["ok"] += 1
        for p in problems:
            counts[p] += 1
            if len(examples[p]) < 5:
                examples[p].append(row.get("diagram_question_id"))
    lines = [
        "# Diagram raw-row verification",
        "",
        f"- rows: {len(rows)}",
        f"- ok: {counts.get('ok', 0)}",
        "",
        "## Problem counts",
        "",
    ]
    lines += [f"- {k}: {v}" for k, v in sorted(counts.items()) if k != "ok"] or ["- none"]
    lines += ["", "## Examples", ""]
    for p, ids in sorted(examples.items()):
        lines.append(f"- {p}: {', '.join(ids)}")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n")
    print(f"[verify] rows={len(rows)} ok={counts.get('ok', 0)} problems={sum(v for k,v in counts.items() if k!='ok')} -> {REPORT}")


if __name__ == "__main__":
    main()
