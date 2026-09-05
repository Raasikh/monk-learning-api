#!/usr/bin/env python3
"""Duplicate-question analysis across the raw JEE/NEET corpus.

Dev-time analysis script — no LLM calls. Reads every extracted question
source and groups questions by normalized-text fingerprint to find the same
question appearing in multiple papers/sources (year-wise vs chapter-wise
reprints, mirror overlap, ExamSIDE/PDF overlap).

Writes ``reports/question_duplicates.md``. Read-only on data files.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "nta_raw"
REPORT = ROOT / "reports" / "question_duplicates.md"

WS_RE = re.compile(r"\s+")
LATEX_NOISE_RE = re.compile(r"\\(?:,|;|:|!|quad|qquad|,|left|right|Big|big)\b?")
NONALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    t = text.lower()
    t = LATEX_NOISE_RE.sub("", t)
    t = NONALNUM_RE.sub("", t)
    return t


def fingerprint(text: str) -> str | None:
    n = normalize(text)
    if len(n) < 40:  # too short to fingerprint reliably
        return None
    return hashlib.sha256(n.encode()).hexdigest()[:20]


def load_jsonl(path: Path) -> list[dict]:
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


def main() -> None:
    records = []  # (source_label, ref, text, exam, year)

    # 1. paper artifacts
    for art_path in sorted((DATA_DIR / "papers").glob("*.json")):
        try:
            art = json.loads(art_path.read_text())
        except Exception:
            continue
        pid = art.get("paper_id") or art_path.stem
        exam, year = art.get("exam"), art.get("year")
        for q in art.get("questions") or []:
            text = (q.get("text") or "").strip()
            if text:
                records.append((f"paper:{pid}", f"{pid}#q{q.get('qno')}", text, exam, year))

    # 2. diagram questions (already windowed into questions)
    for row in load_jsonl(DATA_DIR / "diagram_questions.jsonl"):
        text = (row.get("question_text") or "").strip()
        if text:
            records.append((
                f"diagram:{row.get('source_site')}", row.get("diagram_question_id"),
                text, row.get("exam"), row.get("year"),
            ))

    # 3. ExamSIDE + MathonGo HTML rows
    for path in sorted(DATA_DIR.glob("examside_diagram_questions*.jsonl")):
        for row in load_jsonl(path):
            text = (row.get("question_text") or row.get("text") or "").strip()
            if text:
                records.append(("examside", row.get("question_id") or row.get("id"), text, row.get("exam"), row.get("year")))
    for row in load_jsonl(DATA_DIR / "neet_mathongo_questions.jsonl"):
        text = (row.get("question_text") or row.get("text") or "").strip()
        if text:
            records.append(("mathongo_neet", row.get("question_id") or row.get("id"), text, row.get("exam"), row.get("year")))

    groups: dict[str, list[int]] = defaultdict(list)
    for i, (_, _, text, _, _) in enumerate(records):
        fp = fingerprint(text)
        if fp:
            groups[fp].append(i)

    dupe_groups = {fp: idxs for fp, idxs in groups.items() if len(idxs) > 1}
    dupe_rows = sum(len(v) for v in dupe_groups.values())

    cross_source = 0
    same_paper = 0
    for fp, idxs in dupe_groups.items():
        sources = {records[i][0] for i in idxs}
        if len(sources) > 1:
            cross_source += 1
        else:
            same_paper += 1

    lines = [
        "# Duplicate-question analysis",
        "",
        f"- question rows analyzed: {len(records)}",
        f"- fingerprintable (text >= 40 normalized chars): {sum(1 for g in groups.values() for _ in g)}",
        f"- duplicate groups: {len(dupe_groups)}",
        f"- rows in duplicate groups: {dupe_rows}",
        f"- groups spanning multiple sources/papers: {cross_source}",
        f"- groups within a single source/paper: {same_paper}",
        "",
        "## Largest duplicate groups",
        "",
    ]
    biggest = sorted(dupe_groups.items(), key=lambda kv: -len(kv[1]))[:15]
    for fp, idxs in biggest:
        srcs = Counter(records[i][0] for i in idxs)
        exams = Counter(str(records[i][3]) for i in idxs)
        years = Counter(str(records[i][4]) for i in idxs)
        sample = records[idxs[0]][2][:90].replace("\n", " ")
        lines.append(f"- `{fp}` x{len(idxs)} exams={dict(exams)} years={dict(years)}")
        lines.append(f"  sources: {dict(srcs)}")
        lines.append(f"  text: {sample}…")

    REPORT.write_text("\n".join(lines) + "\n")
    print(f"[dedup] {len(records)} rows, {len(dupe_groups)} dupe groups "
          f"({cross_source} cross-source), {dupe_rows} rows involved -> {REPORT}")


if __name__ == "__main__":
    main()
