#!/usr/bin/env python3
"""Stem hygiene pass (directive §1.6) — deterministic, no LLM calls.

Cleans artifact question text (and, via rematerialize, diagram rows):
- strips publisher/marketing headers from the start of stems
- strips the trailing question number of the FOLLOWING question
- captures `Qn. (k)` answer stamps as embedded-answer candidates and removes
  them from the stem (never leaves the answer in the text)
- removes control characters
- rows that reduce to a worked solution rather than a question get
  ``needs_manual`` instead of being emitted as questions

Reports before/after counts per defect class. Nothing is fabricated: cleaning
only removes or reclassifies text, never invents it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PAPERS_DIR = ROOT / "data" / "nta_raw" / "papers"

CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
WATERMARK_RE = re.compile(
    r"\\text\s*\{\s*(?:mathongo|esaral|selfstudys)\s*\}", re.I
)
HEADER_LINE_RE = re.compile(
    r"(?i)^\s*(?:[\w .&|-]*\b(?:chapter-wise question bank|mathongo|esaral|"
    r"selfstudys|target publications|download \S+\s*app|jee\s*\|\s*neet|"
    r"www\.\w+\.(?:com|in|org)|jee exam solution)\b[\w .&|-]*)\s*$"
)
PAGE_NUM_LINE_RE = re.compile(r"^\s*\d{1,3}\s*$")
TRAILING_QNO_RE = re.compile(r"(?:\s|^)(\d{1,3})\s*[.]?\s*$")
STAMP_RE = re.compile(r"\bQ(\d{1,3})\.\s*\(([A-D1-4])\)")
SOLUTION_START_RE = re.compile(
    r"(?i)^\s*(sol\.|solution\b|answer\s*:|explanation\b)"
)
# same-line header prefix — any header-ish run (chapter title / exam name /
# year) ending at a publisher brand word, e.g.
# "Probability Chapter-wise Question Bank JEE Main 2025 April MathonGo  $$..."
# "Three Dimensional Geometry JEE Main 2025 April MathonGo $$..."
# "JEE Main 2025 April MathonGo Therefore distance ..."
INLINE_HEADER_RE = re.compile(
    r"(?i)^[\w .&|()/–-]{0,80}?\b(?:mathongo|esaral|selfstudys)\b"
    r"(?:[\w .&|()/–-]{0,60}?\b(?:mathongo|esaral|selfstudys)\b)?\s*(?:\(\d+\)\s*)?"
    r"|^[\w .&|()/–-]{0,80}?\b(?:chapter-wise )?question bank\b[\w .&|()/–-]{0,60}?"
    r"\bJEE\s+(?:Main|Advanced)\s+\d{4}\s+\w+\s*(?:\(\d+\)\s*)*"
)
MATH_ONLY_RE = re.compile(r"^\s*\$")
SOLUTION_MARK_RE = re.compile(
    r"(?i)correct\s+answer|correct\s+option|^\s*ans\b|^\s*sol\b"
)
SOLUTION_BRAND_RE = re.compile(
    r"(?i)\bsolutions?\b[\w .&|()/\\–-]{0,250}\b(?:mathongo|esaral|selfstudys)\b"
    r"|(?:mathongo|esaral|selfstudys)\b[\w .&|()/\\–-]{0,250}\bsolutions?\b"
    r"|\bquestion bank\b[\w .&|()/\\–-]{0,250}\bsolutions?\b"
)


def _looks_like_solution_fragment(text: str) -> bool:
    """Content after a header strip that is a worked-solution snippet, not a
    question stem. Genuine stems keep question prose; solution captures are
    workings ('$$\\begin{array}...'), a bare answer stamp ('Q1. ... (3)'), or
    explicit answer markers."""
    if len(text) < 20:
        return True
    if SOLUTION_MARK_RE.search(text[:120]):
        return True
    # "Q1. <fragment> (3) $$workings$$" — question number + answer stamp
    if re.match(r"^\s*Q\d{1,3}\.\s", text) and re.search(r"\([A-D1-4]\)", text[:80]):
        return True
    # math workings with almost no prose in the opening
    head = text[:150]
    if MATH_ONLY_RE.match(text) or "\\begin{array}" in head:
        prose = re.sub(r"\$[^$]*\$", " ", head)
        prose = re.sub(r"\\[a-zA-Z]+|[{}()\[\]|\\^_=+\-]", " ", prose)
        words = re.findall(r"[A-Za-z]{3,}", prose)
        if len(words) < 8:
            return True
    return False


def clean_stem(text: str) -> tuple[str, dict]:
    """Return (cleaned_text, meta) where meta records what was stripped.

    If cleaning would hollow the stem out entirely, the original is returned
    with ``meta["boilerplate_only"]`` so the caller can quarantine instead of
    emitting an empty question.
    """
    meta: dict = {}
    if not text:
        return text, meta

    t = CONTROL_RE.sub("", text)
    if t != text:
        meta["control_chars_removed"] = True

    # Mathpix OCRs the source watermark as a \text{} command inside math
    t2 = WATERMARK_RE.sub("", t)
    if t2 != t:
        meta["watermark_text_removed"] = True
        t = t2

    # worked-solution captures from coaching books ("Solutions ... MathonGo",
    # "Question Bank ... Solutions $$workings$$") — never a question
    if SOLUTION_BRAND_RE.search(t[:300]):
        return text, {**meta, "solution_fragment": True}
    # answer-grid captures: smile-image chains from a solutions table
    if t.lstrip().startswith("<smiles>") and re.search(
        r"(?i)mathongo|esaral|selfstudys", t
    ):
        return text, {**meta, "solution_fragment": True}

    # same-line header prefix ("Probability Chapter-wise Question Bank JEE
    # Main 2025 April MathonGo  $$...") — strip the prefix, then judge the rest
    m_inline = INLINE_HEADER_RE.match(t)
    if m_inline:
        t = t[m_inline.end():].strip()
        meta["inline_header_stripped"] = True
        if _looks_like_solution_fragment(t) or len(t) < 20:
            return text, {**meta, "solution_fragment": True}

    lines = t.splitlines()
    stripped = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if HEADER_LINE_RE.match(line):
            stripped += 1
            i += 1
            continue
        # a bare page number is boilerplate only when boilerplate follows it
        if (
            PAGE_NUM_LINE_RE.match(line)
            and i + 1 < len(lines)
            and HEADER_LINE_RE.match(lines[i + 1] or "")
        ):
            stripped += 1
            i += 1
            continue
        break
    if stripped:
        meta["publisher_header_lines"] = stripped
    rest = lines[i:]
    # boilerplate lines bled mid-stem (page-boundary artifacts) — strip full
    # standalone publisher lines anywhere, never partial lines
    kept = []
    mid = 0
    for line in rest:
        if line.strip() and HEADER_LINE_RE.match(line):
            mid += 1
            continue
        kept.append(line)
    if mid:
        meta["publisher_header_lines"] = stripped + mid
    t = "\n".join(kept).strip()

    # answer stamp anywhere in the stem: capture, then remove
    stamps = STAMP_RE.findall(t)
    if stamps:
        meta["answer_stamps"] = [f"Q{q}.({v})" for q, v in stamps]
        t = STAMP_RE.sub("", t)
        t = re.sub(r"\n{2,}", "\n", t).strip()

    # trailing next-question number at the very end ("... x = 3\n181.")
    m = TRAILING_QNO_RE.search(t)
    if m and len(t) > 30:
        # only strip if preceded by line break or sentence end — a bare
        # trailing integer that is part of the math is not a qno
        prefix = t[: m.start()]
        if prefix.rstrip().endswith(("\n", ".", ":", "?", "$", ")")):
            t = prefix.rstrip()
            meta["trailing_qno_removed"] = m.group(1)

    cleaned = t.strip()
    if len(cleaned) < 20 and len(text.strip()) >= 20:
        return text, {**meta, "boilerplate_only": True}
    return cleaned, meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    from collections import Counter
    stats = Counter()
    examples = []
    for art_path in sorted(PAPERS_DIR.glob("*.json")):
        art = json.loads(art_path.read_text())
        if art.get("status") != "extracted":
            continue
        changed = False
        for q in art.get("questions") or []:
            text = q.get("text") or ""
            if not text:
                continue
            cleaned, meta = clean_stem(text)
            if meta.get("boilerplate_only") or meta.get("solution_fragment"):
                q["needs_manual"] = "solution_fragment" if meta.get("solution_fragment") else "boilerplate_only"
                stats["solution_fragment" if meta.get("solution_fragment") else "boilerplate_only"] += 1
                changed = True
                continue
            if SOLUTION_START_RE.match(cleaned):
                q["needs_manual"] = "solution_not_question"
                stats["solution_rows_flagged"] += 1
                changed = True
                continue
            if meta:
                for k in meta:
                    stats[k] += 1
                if len(examples) < 5 and ("publisher_header_lines" in meta or "answer_stamps" in meta):
                    examples.append((art["paper_id"], q.get("qno"), text[:80], cleaned[:80], meta))
                if meta.get("answer_stamps") and not q.get("embedded_answer"):
                    # capture the stamp as an embedded-answer candidate
                    from scripts import extract_nta_papers as nta
                    q["embedded_answer"] = nta._normalize_embedded_answer(
                        meta["answer_stamps"][0].split("(")[1].rstrip(")")
                    )
                    q.setdefault("parse_flags", []).append("answer_from_stamp")
                if cleaned != text:
                    q["text"] = cleaned
                    changed = True
        if changed and args.write:
            # rebuild the sheet so stamp-captured answers land in entries
            from scripts import extract_nta_papers as nta
            art["answer_sheet"] = nta.build_answer_sheet(
                art.get("questions") or [],
                (art.get("manifest") or {}).get("official_key_url"),
            )
            art_path.write_text(json.dumps(art, ensure_ascii=False, indent=1))

    print(f"[hygiene] artifacts stats: {dict(stats)}")
    for pid, qno, before, after, meta in examples:
        print(f"  {pid} q{qno} {meta}")
        print(f"    before: {before!r}")
        print(f"    after : {after!r}")

    # --- diagram candidates: clean ocr_text_context (durable source of the
    # diagram rows' question_text; survives rematerialize) -------------------
    cand_stats = Counter()
    for cand_path in sorted((ROOT / "data" / "nta_raw").glob("diagram_candidates*.jsonl")):
        rows = []
        changed_any = False
        for line in cand_path.open():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                rows.append(line)
                continue
            ctx = row.get("ocr_text_context") or ""
            if ctx:
                cleaned, meta = clean_stem(ctx)
                if meta:
                    for k in meta:
                        cand_stats[k] += 1
                if meta.get("boilerplate_only") or meta.get("solution_fragment"):
                    # not a question at all — materialize skips these
                    row["hygiene_boilerplate_only"] = True
                    changed_any = True
                elif cleaned != ctx:
                    row["ocr_text_context"] = cleaned
                    changed_any = True
            rows.append(json.dumps(row, ensure_ascii=False))
        if changed_any and args.write:
            cand_path.write_text("\n".join(rows) + "\n")
    print(f"[hygiene] candidates stats: {dict(cand_stats)}")
    if not args.write:
        print("[hygiene] dry run — pass --write to update artifacts")


if __name__ == "__main__":
    main()
