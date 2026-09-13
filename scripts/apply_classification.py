#!/usr/bin/env python3
"""Apply chapter/concept/difficulty classifications to corpus rows (§2).

Dev-time script — deterministic. Reads the classifier outputs in
scratch/classify_results/, validates every chapter_name against the live
chapters table snapshot (taxonomy_cache.json — exact match required), maps
to chapter_id, validates concept names against that chapter's concept list
(free-form concepts are kept but tagged), and writes metadata into the
source JSONL rows. Rows with ``uncertain`` classifications are flagged, not
servable-anyway.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "nta_raw"
RESULTS = ROOT / "scratch" / "classify_results"


def _norm_concept(s: str) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def fuzzy_map_concept(concept: str, chapter_id: str, concepts_by_chapter: dict) -> str | None:
    """Conservative free-form -> taxonomy concept mapping within one chapter:
    exact-normalized or single-candidate containment only."""
    cands = concepts_by_chapter.get(chapter_id, set())
    n = _norm_concept(concept)
    if not n:
        return None
    for c in cands:
        if _norm_concept(c) == n:
            return c
    hits = [c for c in cands if n in _norm_concept(c) or _norm_concept(c) in n]
    return hits[0] if len(hits) == 1 else None

SOURCES = [
    "diagram_questions.jsonl",
    "examside_diagram_questions.jsonl",
    "examside_diagram_questions_jee_advanced.jsonl",
    "neet_mathongo_questions.jsonl",
]

EXAM_MAP = {
    "jee-main": ("JEE Main", ["JEE Main"]),
    "jee-advanced": ("JEE Advanced", ["JEE Advanced"]),
    "neet-ug": ("NEET", ["NEET"]),
}


def main() -> None:
    tax = json.loads((DATA / "taxonomy_cache.json").read_text())
    chapters = {c["name"]: c for c in tax["chapters"]}
    concepts_by_chapter: dict[str, set] = {}
    for c in tax["concepts"]:
        concepts_by_chapter.setdefault(c["chapter_id"], set()).add(c["name"])

    classified = {}
    for f in sorted(RESULTS.glob("batch_*.jsonl")):
        for line in f.open():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            classified[r["id"]] = r

    # hash ids are unstable across rematerialization (context keys change).
    # Rebind classification -> row by normalized text prefix via the batch
    # files, which carry the classified text of every row.
    import re as _re
    def normtxt(s: str) -> str:
        return _re.sub(r"[^a-z0-9]+", "", (s or "").lower())[:80]

    text_index: dict[str, dict] = {}
    batch_dir = ROOT / "scratch" / "classify_batches"
    if batch_dir.exists():
        for f in sorted(batch_dir.glob("batch_*.jsonl")):
            for line in f.open():
                line = line.strip()
                if not line:
                    continue
                try:
                    b = json.loads(line)
                except Exception:
                    continue
                r = classified.get(b.get("id"))
                if r:
                    text_index[normtxt(b.get("text") or "")] = r

    stats = {"rows": 0, "applied": 0, "bad_chapter": 0, "concept_taxonomy": 0,
             "concept_freeform": 0, "uncertain": 0}
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
        changed = False
        for idx, row in enumerate(rows):
            rid = row.get("diagram_question_id") or row.get("question_id") or f"{name}:{idx}"
            r = classified.get(rid)
            if not r:
                # hash ids changed across rematerialization — fall back to
                # the text-prefix binding
                r = text_index.get(normtxt(row.get("question_text") or ""))
            if not r:
                continue
            stats["rows"] += 1
            ch = chapters.get(r.get("chapter_name"))
            if not ch:
                stats["bad_chapter"] += 1
                continue
            row["chapter_name"] = ch["name"]
            row["chapter_id"] = ch["id"]
            row["subject"] = (row.get("subject") or ch["subject"]).lower()
            concept = (r.get("concept") or "").strip()
            if concept:
                if concept in concepts_by_chapter.get(ch["id"], set()):
                    row["concept"] = concept
                    row["concept_source"] = "taxonomy"
                    stats["concept_taxonomy"] += 1
                else:
                    mapped = fuzzy_map_concept(concept, ch["id"], concepts_by_chapter)
                    if mapped:
                        row["concept"] = mapped
                        row["concept_source"] = "taxonomy"
                        row["concept_mapped_from_freeform"] = True
                        stats["concept_taxonomy"] += 1
                    else:
                        # free-form concepts do not aggregate in Monk Score —
                        # quarantine rather than leave for serve time (audit §3.6)
                        row["concept"] = concept
                        row["concept_source"] = "freeform"
                        row["needs_manual"] = "concept_unmapped"
                        stats["concept_freeform"] += 1
            if r.get("difficulty") in (1, 2, 3):
                row["difficulty"] = r["difficulty"]
            ref_exam, target = EXAM_MAP.get(row.get("exam") or "", (None, None))
            if ref_exam:
                row["reference_exam"] = ref_exam
                row["target_exams"] = target
            if row.get("year"):
                row["reference_year"] = row["year"]
            if r.get("uncertain"):
                row["classification_uncertain"] = True
                row["needs_manual"] = "classification_uncertain"
                stats["uncertain"] += 1
            stats["applied"] += 1
            changed = True
        if changed:
            src.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"[classify-apply] {stats}")


if __name__ == "__main__":
    main()
