#!/usr/bin/env python3
"""Build chapter/concept/difficulty classification batches (directive §2).

Dev-time prep — deterministic. Emits batch files of rows that need LLM
classification, each carrying the deterministic hint when one exists
(ExamSIDE chapter label or MathonGo page header) so the classifier starts
 from evidence, not thin air.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "nta_raw"
OUT = ROOT / "scratch" / "classify_batches"
BATCH_SIZE = 40

SOURCES = [
    "diagram_questions.jsonl",
    "examside_diagram_questions.jsonl",
    "examside_diagram_questions_jee_advanced.jsonl",
    "neet_mathongo_questions.jsonl",
]

HDR1 = re.compile(r"(?m)^\s*([A-Z][\w ,&()'-]{2,60}?)\s+Chapter-wise Question Bank", re.I)
HDR2 = re.compile(r"Chapter-wise Question Bank\s+([A-Z][\w ,&()'-]{2,60}?)(?:\s+JEE|\s*$)", re.I)


def load(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.open():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def opt_count(row: dict) -> int:
    opts = row.get("options")
    n = 0
    if isinstance(opts, dict):
        n = sum(1 for v in opts.values() if str(v).strip())
    imgs = row.get("option_images")
    if isinstance(imgs, dict):
        n = max(n, sum(1 for v in imgs.values() if str(v).strip()))
    return n


def main() -> None:
    page_chapters = {}
    pc_path = DATA / "mathongo_page_chapters.json"
    if pc_path.exists():
        page_chapters = json.loads(pc_path.read_text())

    def mathongo_hint(row: dict) -> str | None:
        cands = [
            (pg, c) for k, c in page_chapters.items()
            for p, pg in [k.rsplit("|", 1)]
            if p == row.get("paper_id") and int(pg) <= (row.get("page") or 1)
        ]
        return cands[-1][1] if cands else None

    OUT.mkdir(parents=True, exist_ok=True)
    batch_rows = []
    for name in SOURCES:
        for idx, row in enumerate(load(DATA / name)):
            text = (row.get("question_text") or "").strip()
            if len(text) < 20:
                continue
            # funnel-priority: servable candidates only (options or numerical)
            if opt_count(row) < 4 and row.get("question_type") != "numerical":
                continue
            hint = None
            if row.get("chapter"):
                hint = f"examside_label:{row['chapter']}"
            elif row.get("source_site") == "www.mathongo.com":
                h = mathongo_hint(row)
                if h and h != "MathonGo":
                    hint = f"mathongo_header:{h}"
            batch_rows.append({
                "source_file": name,
                "row_index": idx,
                "id": row.get("diagram_question_id") or row.get("question_id") or f"{name}:{idx}",
                "exam": row.get("exam"),
                "subject": row.get("subject"),
                "text": text[:1200],
                "options": row.get("options"),
                "question_type": row.get("question_type"),
                "hint": hint,
            })

    batches = [batch_rows[i:i + BATCH_SIZE] for i in range(0, len(batch_rows), BATCH_SIZE)]
    for old in OUT.glob("batch_*.jsonl"):
        old.unlink()
    for i, b in enumerate(batches):
        (OUT / f"batch_{i:03d}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in b)
        )
    print(f"[classify-prep] {len(batch_rows)} rows -> {len(batches)} batches in {OUT}")


if __name__ == "__main__":
    main()
