#!/usr/bin/env python3
"""Options repair for the PDF pipeline (directive §1.2 / step 5).

Dev-time script — deterministic parsing over Mathpix OCR, no LLM calls.

Three paths, each keyed to how the source actually lays options out:

1. artifact questions with <4 non-empty options: re-OCR the question's page
   (cache-backed) and split options from the OCR text — (A)-(D) or printed
   (1)-(4) mapped to A-D keys.
2. 2026 official papers: options are page images labeled by option ID
   ("6911211. <image>"); questions carry option_ids, so slice the page OCR
   at each option-ID line.
3. diagram rows with no artifact question (MathonGo etc.): split options out
   of the row's own ocr_text_context when the context window includes them.

Options that are unreadable stay empty — nothing is fabricated; rows stay
flagged via the funnel.
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

from repair_text_fidelity import (  # noqa: E402
    extract_stem_from_ocr,
    page_ocr_text,
    _split_numeric_options,
    _trim_option,
)
from ocr_extract_scanned_papers import _split_options  # noqa: E402
from extract_diagram_questions import ocr_page, render_page_png  # noqa: E402


def mathpix_page_text(cache: Path, paper_id: str, page_no: int) -> str:
    """Force Mathpix for a page (skip the text layer) — needed when options
    are page images whose content only OCR can read (2026 officials)."""
    import fitz

    doc = fitz.open(cache)
    try:
        page = doc[page_no - 1]
        png = render_page_png(page)
        return (ocr_page(png, f"{paper_id}_p{page_no}") or {}).get("text", "")
    finally:
        doc.close()

PAPERS_DIR = ROOT / "data" / "nta_raw" / "papers"
DATA = ROOT / "data" / "nta_raw"


def opt_count(opts) -> int:
    if isinstance(opts, dict):
        return sum(1 for v in opts.values() if str(v).strip())
    return 0


def split_options_any(block: str) -> dict | None:
    opts = _split_options(block)
    if opts:
        return opts
    return _split_numeric_options(block)


def split_2026_options(ocr_text: str, option_ids: list[str]) -> dict | None:
    """Slice a 2026 page's OCR text at option-ID markers — either line-start
    'ID. content' or Mathpix table cells 'ID. & content \\\\'."""
    if not option_ids or len(option_ids) < 4:
        return None
    # tabular variant first: all four IDs as table cells
    tab = {}
    for letter, oid in zip("ABCD", option_ids[:4]):
        m = re.search(
            rf"(?m)^\s*(?:\\hline\s*)?\|?\s*{re.escape(str(oid))}\s*\.\s*&\s*(.+?)\s*\\\\\s*$",
            ocr_text,
        )
        if m:
            tab[letter] = m.group(1).strip()
    if len(tab) == 4:
        return tab
    positions = []
    for oid in option_ids[:4]:
        m = re.search(rf"(?m)^{re.escape(str(oid))}\s*[.)]\s*", ocr_text)
        if not m:
            return None
        positions.append(m.end())
    # verify ordering and locality (reject header collisions like Group/Section Id)
    if positions != sorted(positions):
        return None
    if positions[-1] - positions[0] > 3000:
        return None
    options = {}
    for i, letter in enumerate("ABCD"):
        start = positions[i]
        end = positions[i + 1] - len(str(option_ids[i + 1])) - 2 if i < 3 else len(ocr_text)
        seg = ocr_text[start:end]
        # cut the trailing solution/next-question material from option D
        if i == 3:
            m2 = re.search(r"(?mi)^\s*(Sol\.|Solution|Ans\.|Official|Question Number|Correct)", seg)
            if m2:
                seg = seg[: m2.start()]
        options[letter] = _trim_option(seg)[:600]
    if opt_count(options) < 4:
        return None
    return options


def repair_artifact_options(art: dict, cache: Path, paper_id: str, stats: dict) -> bool:
    changed = False
    for q in art.get("questions") or []:
        if opt_count(q.get("options")) >= 4 or q.get("question_type") == "numerical":
            continue
        pages = []
        if q.get("page_start"):
            end = (q.get("page_end") or q["page_start"]) + (1 if q.get("option_ids") else 0)
            pages = list(range(q["page_start"], end + 1))
        if not pages:
            continue
        for pno in pages:
            opts = None
            if q.get("option_ids"):
                ocr_text = mathpix_page_text(cache, paper_id, pno)
                if ocr_text:
                    opts = split_2026_options(ocr_text, [str(o) for o in q["option_ids"]])
            if not opts:
                ocr_text = page_ocr_text(cache, paper_id, pno)
                if not ocr_text:
                    continue
                _, opts = extract_stem_from_ocr(ocr_text, q.get("qno"))
                if not opts:
                    # whole-page fallback: options may sit outside the stem slice
                    opts = split_options_any(ocr_text)
            if opts and opt_count(opts) >= 4:
                q["options"] = opts
                q.setdefault("parse_flags", []).append("options_ocr_repaired")
                stats["artifact_repaired"] += 1
                changed = True
                break
    return changed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()

    stats = {"artifact_repaired": 0, "papers_touched": 0, "row_context_filled": 0}
    for art_path in sorted(PAPERS_DIR.glob("*.json")):
        art = json.loads(art_path.read_text())
        if art.get("status") != "extracted":
            continue
        if args.only and art["paper_id"] not in args.only:
            continue
        probe = art.get("probe") or (art.get("manifest") or {}).get("probe") or {}
        cache_rel = probe.get("cache_path")
        if not cache_rel or not (ROOT / cache_rel).exists():
            continue
        if repair_artifact_options(art, ROOT / cache_rel, art["paper_id"], stats):
            stats["papers_touched"] += 1
            if args.write:
                art_path.write_text(json.dumps(art, ensure_ascii=False, indent=1))

    # row-level: options from ocr_text_context for rows with no artifact question
    for cand_path in sorted(DATA.glob("diagram_candidates*.jsonl")):
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
            if ctx and not row.get("context_options_extracted"):
                opts = split_options_any(ctx)
                if opts and opt_count(opts) >= 4:
                    row["context_options"] = opts
                    row["context_options_extracted"] = True
                    stats["row_context_filled"] += 1
                    changed_any = True
            rows.append(json.dumps(row, ensure_ascii=False))
        if changed_any and args.write:
            cand_path.write_text("\n".join(rows) + "\n")

    print(f"[repair-options] stats: {stats}")
    if not args.write:
        print("[repair-options] dry run — pass --write")


if __name__ == "__main__":
    main()
