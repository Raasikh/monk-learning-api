#!/usr/bin/env python3
"""Repair untrusted text-layer question text via Mathpix OCR (directive §1.6).

Dev-time repair script — deterministic, no LLM calls. The PDF text layer
stores matrices/Greek as positioned Symbol-font glyphs; linearising it yields
PUA mojibake and char-fragmented stems. Mathpix OCR of the same page is clean
(it is the same engine that produces the corpus's 0.98-median-confidence
diagram reads). This script re-OCRs the flagged questions' pages (cache-backed)
and rewrites the artifact question's text/options from the OCR result.

Flag predicates (published in reports/corpus_proof.md §6):
- any codepoint in U+F000..U+F0FF, or
- >=4 non-empty lines with >=40% of stripped length <= 2.

Rows that cannot be repaired cleanly keep their original text and get
``needs_manual`` with a specific reason; nothing is fabricated.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.extract_diagram_questions import ocr_page, render_page_png  # noqa: E402
from scripts.ocr_extract_scanned_papers import _split_options, _clean_stem  # noqa: E402

PAPERS_DIR = ROOT / "data" / "nta_raw" / "papers"
OCR_CACHE_DIR = ROOT / "scratch" / "nta_mathpix_cache"

PUA_RE = re.compile("[\\uf000-\\uf0ff]")  # U+F000..U+F0FF inclusive


def is_flagged(text: str) -> str | None:
    if not text:
        return None
    if PUA_RE.search(text):
        return "pua"
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) >= 4 and sum(1 for l in lines if len(l.strip()) <= 2) / len(lines) >= 0.4:
        return "frag"
    return None


def question_flag_reason(q: dict) -> str | None:
    """Flag on the stem AND on options — PUA corrupts both (found 2026-09-12:
    110 rows with clean stems but PUA in options)."""
    r = is_flagged(q.get("text") or "")
    if r:
        return r
    opts = q.get("options")
    if isinstance(opts, dict):
        for v in opts.values():
            if is_flagged(str(v)):
                return "pua_options"
    return None


def page_ocr_text(pdf_path: Path, paper_id: str, page_no: int) -> str:
    """Mathpix OCR text for one 1-based page; uses the text layer only when it
    is already clean, otherwise Mathpix (cache-backed)."""
    import fitz

    doc = fitz.open(pdf_path)
    try:
        page = doc[page_no - 1]
        text = page.get_text().strip()
        if len(text) > 200 and not PUA_RE.search(text):
            lines = [l for l in text.splitlines() if l.strip()]
            frag = len(lines) >= 4 and sum(1 for l in lines if len(l.strip()) <= 2) / len(lines) >= 0.4
            if not frag:
                return text
        png = render_page_png(page)
        ocr = ocr_page(png, f"{paper_id}_p{page_no}")
        return ocr.get("text", "")
    finally:
        doc.close()


QNO_LINE_RE = re.compile(r"(?m)^\s*(?:Q[.\s]*)?(\d{1,3})\s*[.)]\s")


NUM_OPTION_RE = re.compile(r"\(([1-4])\)\s*")
TRAIL_MARK_RE = re.compile(r"(?mi)^\s*(Sol\.|Solution|Ans\.|Official\s+Ans|Answer\b)")


def _trim_option(value: str) -> str:
    m = TRAIL_MARK_RE.search(value)
    if m:
        value = value[: m.start()]
    return value.strip()


def _split_numeric_options(block: str) -> dict | None:
    """Split an OCR'd block on printed (1)-(4) options, mapping to A-D keys
    (the client grades on option keys, not printed numbers)."""
    seen: dict[str, re.Match] = {}
    for m in NUM_OPTION_RE.finditer(block):
        digit = m.group(1)
        if digit not in seen:
            seen[digit] = m
        if len(seen) == 4:
            break
    if len(seen) < 4:
        return None
    ordered = [seen[d] for d in "1234"]
    if not all(ordered[i].start() < ordered[i + 1].start() for i in range(3)):
        return None
    options = {}
    for i, letter in enumerate("ABCD"):
        start = ordered[i].end()
        end = ordered[i + 1].start() if i < 3 else len(block)
        options[letter] = _trim_option(block[start:end])
    return options


def extract_stem_from_ocr(ocr_text: str, qno: int) -> tuple[str, dict | None]:
    """Slice question qno's stem (+options) out of one page's OCR text."""
    marks = [m for m in QNO_LINE_RE.finditer(ocr_text)]
    target = None
    for i, m in enumerate(marks):
        if int(m.group(1)) == qno:
            end = marks[i + 1].start() if i + 1 < len(marks) else len(ocr_text)
            target = ocr_text[m.end():end]
            break
    if target is None:
        return "", None
    options = _split_options(target)
    opt_start = None
    if options:
        for m2 in re.finditer(r"\(([A-D])\)\s*", target):
            if m2.group(1) == "A":
                opt_start = m2.start()
                break
    if not options:
        options = _split_numeric_options(target)
        if options:
            m2 = NUM_OPTION_RE.search(target)
            opt_start = m2.start() if m2 else None
    stem = target[:opt_start] if opt_start is not None else target
    if options:
        options = {k: _trim_option(v) for k, v in options.items()}
    return _clean_stem(stem), options


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None, help="paper_ids")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    # flagged questions per artifact
    work: dict[str, list[dict]] = {}
    for art_path in sorted(PAPERS_DIR.glob("*.json")):
        art = json.loads(art_path.read_text())
        if art.get("status") != "extracted":
            continue
        flagged = []
        for q in art.get("questions") or []:
            reason = question_flag_reason(q)
            if reason:
                flagged.append((q, reason))
        if flagged:
            work[art["paper_id"]] = flagged
    if args.only:
        work = {k: v for k, v in work.items() if k in args.only}

    n_q = sum(len(v) for v in work.values())
    print(f"[repair] {len(work)} papers, {n_q} flagged questions")

    stats = {"repaired": 0, "repair_failed": 0, "no_pages": 0}
    for paper_id, flagged in work.items():
        art_path = PAPERS_DIR / f"{paper_id}.json"
        art = json.loads(art_path.read_text())
        probe = art.get("probe") or (art.get("manifest") or {}).get("probe") or {}
        cache = probe.get("cache_path")
        if not cache or not (ROOT / cache).exists():
            print(f"[repair] {paper_id}: no cached PDF, skipping {len(flagged)}")
            stats["no_pages"] += len(flagged)
            continue
        changed = False
        # rebuild flagged list from the RELOADED artifact — the work-set
        # tuples hold objects from the first read; mutating those would never
        # reach the file (found 2026-09-12: repair stats claimed writes that
        # persisted nothing)
        flagged = [
            (q, question_flag_reason(q))
            for q in art.get("questions") or []
            if question_flag_reason(q)
        ]
        for q, reason in flagged:
            qno = q.get("qno")
            pages = []
            if q.get("page_start"):
                pages = list(range(q["page_start"], (q.get("page_end") or q["page_start"]) + 1))
            if not pages:
                # fall back: scan the whole document's OCR for the qno marker
                import fitz
                doc = fitz.open(ROOT / cache)
                pages = list(range(1, doc.page_count + 1))
                doc.close()
            new_stem, new_opts = "", None
            for pno in pages:
                ocr_text = page_ocr_text(ROOT / cache, paper_id, pno)
                if not ocr_text:
                    continue
                stem, opts = extract_stem_from_ocr(ocr_text, qno)
                if len(stem) >= 20 and not is_flagged(stem):
                    new_stem, new_opts = stem, opts
                    break
            if new_stem:
                q["text_original_textlayer"] = q.get("text")
                q["text"] = new_stem
                if new_opts:
                    q["options"] = new_opts
                q["ocr_repaired"] = reason
                stats["repaired"] += 1
                changed = True
            else:
                q.setdefault("parse_flags", []).append(f"text_untrusted_{reason}")
                q["needs_manual"] = f"text_layer_{reason}_unrepairable"
                stats["repair_failed"] += 1
                changed = True
        if changed and args.write:
            art_path.write_text(json.dumps(art, ensure_ascii=False, indent=1))
            print(f"[repair] {paper_id}: wrote")

    print(f"[repair] stats: {stats}")
    if not args.write:
        print("[repair] dry run — pass --write to update artifacts")


if __name__ == "__main__":
    main()
