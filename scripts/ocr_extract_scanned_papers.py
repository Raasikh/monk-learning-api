#!/usr/bin/env python3
"""Extract questions from scanned papers via Mathpix OCR (dev-time).

Dev-time script — deterministic parsing over Mathpix OCR text. Mathpix is the
OCR engine here because these are scanned image PDFs with no text layer; this
mirrors the product's snap OCR path, not a content-generation task.

Handles the two scanned formats in the corpus:

- eSaral 2022 subject reprints: ``N. Question ID: 101761`` ... options
  ``(A) .. (D)`` ... ``Official Ans. by NTA (C)`` per question.
- NTA 2022 original booklets: ``Q:N`` / ``Topic Name:Subject-Section X`` /
  ``ItemCode:101665``.

Produces real question records (qno, question_id, subject, section, text,
options, question_type) and marks the artifact ``extracted`` with
``extraction_method: mathpix_ocr``. Printed answers stay per-question
embedded data; ``scripts/join_nta_answer_keys.py`` upgrades the sheet to
``official_verified`` where the NTA final key agrees.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import extract_nta_papers as nta  # noqa: E402
from scripts.extract_diagram_questions import ocr_page, render_page_png  # noqa: E402

PAPERS_DIR = ROOT / "data" / "nta_raw" / "papers"

# eSaral 2022: "1. Question ID: 101761"
ESARAL_Q_RE = re.compile(r"(?m)^\s*(\d{1,3})\.\s*Question\s+ID\s*[:.]?\s*(\d{5,})", re.I)
# NTA 2022 original: "Q:5" ... "Topic Name:Mathematics-Section A" ... "ItemCode:101665"
NTA_Q_RE = re.compile(r"Q\s*:\s*(\d{1,3})\b")
NTA_TOPIC_RE = re.compile(r"Topic\s*Name\s*:\s*([A-Za-z]+)\s*-\s*(Section\s*[AB])", re.I)
NTA_ITEM_RE = re.compile(r"ItemCode\s*[:.]?\s*(\d{5,})", re.I)
OFFICIAL_ANS_RE = re.compile(r"Official\s+Ans\.?\s+by\s+NTA\s*\(([^)]+)\)", re.I)
ANS_RE = re.compile(r"(?m)^\s*Ans\.?\s*\(([^)]+)\)")
OPTION_RE = re.compile(r"\(([A-D])\)\s*")
SOL_MARKER_RE = re.compile(r"(?m)^\s*(Sol\.|Solution|Official Ans|Ans\.)")


def _split_options(block: str) -> dict | None:
    """Split an OCR'd block into stem + (A)-(D) options; None if no option grid."""
    marks = list(OPTION_RE.finditer(block))
    if len(marks) < 4:
        return None
    # use the first occurrence of each letter in order A,B,C,D
    seen = {}
    for m in marks:
        letter = m.group(1)
        if letter not in seen:
            seen[letter] = m
        if len(seen) == 4:
            break
    if len(seen) < 4:
        return None
    ordered = [seen[l] for l in "ABCD"]
    if not all(ordered[i].start() < ordered[i + 1].start() for i in range(3)):
        return None
    options = {}
    for i, letter in enumerate("ABCD"):
        start = ordered[i].end()
        end = ordered[i + 1].start() if i < 3 else len(block)
        options[letter] = block[start:end].strip()
    return options


def _clean_stem(text: str) -> str:
    m = SOL_MARKER_RE.search(text)
    if m:
        text = text[: m.start()]
    return re.sub(r"\n{2,}", "\n", text).strip()


SECTION_HEAD_RE = re.compile(r"(?mi)^\s*SECTION\s*[-–]?\s*([AB])\b")
PLAIN_Q_RE = re.compile(r"(?m)^\s*(\d{1,2})\.\s+(?=\S)")
BLOCK_MARK_RE = re.compile(r"Official\s+Ans|^\s*Ans\.|^\s*Sol\.", re.I | re.M)


def _renumber_section_b(questions: list[dict]) -> None:
    """eSaral reprints restart numbering at 1 in Section B; NTA convention is
    21-30. Renumber so qno never collides with Section A in answer matching."""
    for q in questions:
        if q.get("section") == "Section B" and (q.get("qno") or 0) <= 10:
            q["qno_printed"] = q["qno"]
            q["qno"] = q["qno"] + 20
            q["qno_renumbered"] = True


def parse_esaral_plain(full: str) -> list[dict]:
    """eSaral 2022 variant without Question IDs: numbered questions, (A)-(D)
    options, 'Official Ans. by NTA (X)' printed per question."""
    sections = [(m.start(), m.group(1).upper()) for m in SECTION_HEAD_RE.finditer(full)]

    def section_at(pos: int) -> str | None:
        current = None
        for spos, name in sections:
            if spos <= pos:
                current = name
        return current

    candidates = [(m.start(), int(m.group(1))) for m in PLAIN_Q_RE.finditer(full)]
    accepted: list[tuple[int, int]] = []
    expected = 1
    for pos, n in candidates:
        if n == expected:
            accepted.append((pos, n))
            expected += 1
        elif n == 1 and expected > 1:
            # numbering restart — only accept across a section boundary
            prev_pos = accepted[-1][0] if accepted else -1
            if any(prev_pos < spos < pos for spos, _ in sections):
                accepted.append((pos, n))
                expected = 2
    questions = []
    for i, (pos, qno) in enumerate(accepted):
        end = accepted[i + 1][0] if i + 1 < len(accepted) else len(full)
        block = full[pos:end]
        # drop the leading "N." number itself
        block = PLAIN_Q_RE.sub("", block, count=1)
        if not BLOCK_MARK_RE.search(block):
            continue  # false candidate: no answer/solution marker at all
        options = _split_options(block)
        stem = block
        if options:
            first = min(m2.start() for m2 in OPTION_RE.finditer(block) if m2.group(1) == "A")
            stem = block[:first]
        answer = None
        am = OFFICIAL_ANS_RE.search(block) or ANS_RE.search(block)
        if am:
            answer = nta._normalize_embedded_answer(am.group(1))
        section = section_at(pos)
        questions.append({
            "qno": qno,
            "question_id": None,
            "section": f"Section {section}" if section else None,
            "question_type": "single_correct" if options else "numerical",
            "text": _clean_stem(stem),
            "options": options,
            "embedded_answer": answer,
            "extraction": "mathpix_ocr",
        })
    _renumber_section_b(questions)
    return questions


def parse_esaral(full: str) -> list[dict]:
    matches = list(ESARAL_Q_RE.finditer(full))
    # section boundaries: eSaral reprints restart numbering in Section B
    sections = [(m.start(), m.group(1).upper()) for m in SECTION_HEAD_RE.finditer(full)]

    def section_at(pos: int) -> str | None:
        current = None
        for spos, name in sections:
            if spos <= pos:
                current = name
        return current

    questions = []
    for i, m in enumerate(matches):
        qno, qid = int(m.group(1)), m.group(2)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full)
        block = full[m.end():end]
        options = _split_options(block)
        stem = block
        if options:
            first = min(m2.start() for m2 in OPTION_RE.finditer(block) if m2.group(1) == "A")
            stem = block[:first]
        answer = None
        am = OFFICIAL_ANS_RE.search(block) or ANS_RE.search(block)
        if am:
            answer = nta._normalize_embedded_answer(am.group(1))
        section = section_at(m.start())
        questions.append({
            "qno": qno,
            "question_id": qid,
            "section": f"Section {section}" if section else None,
            "question_type": "single_correct" if options else "numerical",
            "text": _clean_stem(stem),
            "options": options,
            "embedded_answer": answer,
            "extraction": "mathpix_ocr",
        })
    _renumber_section_b(questions)
    return questions


def parse_nta2022(full: str) -> list[dict]:
    item_matches = list(NTA_ITEM_RE.finditer(full))
    questions = []
    for i, im in enumerate(item_matches):
        # question number: nearest "Q:N" before the ItemCode
        head = full[max(0, im.start() - 3000): im.start()]
        qms = list(NTA_Q_RE.finditer(head))
        qno = int(qms[-1].group(1)) if qms else None
        tm = NTA_TOPIC_RE.search(head)
        subject, section = (tm.group(1), tm.group(2)) if tm else (None, None)
        end = item_matches[i + 1].start() if i + 1 < len(item_matches) else len(full)
        # block starts after the previous ItemCode's question content; the
        # ItemCode sits in the header line, so question content follows it.
        block = full[im.end():end]
        # but the stem may precede the ItemCode line in NTA layout; take the
        # region between the "Q:N" marker and the next question instead.
        if qms:
            qstart = max(0, im.start() - 3000) + qms[-1].end()
            block = full[qstart:end]
        options = _split_options(block)
        stem = block
        if options:
            first = min(m2.start() for m2 in OPTION_RE.finditer(block) if m2.group(1) == "A")
            stem = block[:first]
        questions.append({
            "qno": qno,
            "question_id": im.group(1),
            "subject": subject,
            "section": section,
            "question_type": "single_correct" if options else "numerical",
            "text": _clean_stem(stem),
            "options": options,
            "extraction": "mathpix_ocr",
        })
    return questions


def mine_paper(pdf_path: Path, label_prefix: str) -> str:
    import fitz

    doc = fitz.open(pdf_path)
    parts = []
    try:
        for pno in range(doc.page_count):
            page = doc[pno]
            text = page.get_text().strip()
            if len(text) > 200:  # has a usable text layer already
                parts.append(text)
                continue
            png = render_page_png(page)
            try:
                ocr = ocr_page(png, f"{label_prefix}_p{pno + 1}")
            except Exception as exc:
                # tolerate per-page OCR failure (e.g. Mathpix "Content not
                # found" on blank/blankish pages); missing pages just parse
                # to nothing
                print(f"[mine] {label_prefix} p{pno + 1}: OCR failed: {exc}")
                continue
            parts.append(ocr.get("text", ""))
    finally:
        doc.close()
    return "\n\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    manifest = nta.load_manifest()
    targets = []
    for e in manifest:
        art_path = PAPERS_DIR / f"{e['paper_id']}.json"
        if not art_path.exists():
            continue
        art = json.loads(art_path.read_text())
        if art.get("status") != "needs_ocr":
            continue
        if args.only and e["paper_id"] not in args.only:
            continue
        targets.append((e, art_path, art))

    print(f"[mine] {len(targets)} needs_ocr papers selected")
    for e, art_path, art in targets:
        probe = e.get("probe") or {}
        cache = probe.get("cache_path")
        if not cache or not (ROOT / cache).exists():
            print(f"[mine] {e['paper_id']}: no cached PDF, skipping")
            continue
        full = mine_paper(ROOT / cache, e["paper_id"])
        questions = parse_esaral(full)
        fmt = "esaral"
        if not questions:
            questions = parse_esaral_plain(full)
            fmt = "esaral_plain"
        if not questions:
            questions = parse_nta2022(full)
            fmt = "nta2022"
        print(f"[mine] {e['paper_id']}: {len(questions)} questions ({fmt})")
        if not questions:
            continue
        if args.write:
            art["questions"] = questions
            art["status"] = "extracted"
            art["extraction_method"] = "mathpix_ocr"
            art["answer_sheet"] = nta.build_answer_sheet(questions, e.get("official_key_url"))
            art_path.write_text(json.dumps(art, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
