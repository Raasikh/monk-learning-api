#!/usr/bin/env python3
"""Diagram-question extraction layer for the raw NTA/mirror corpus.

DETERMINISTIC FIRST, OCR ADAPTER SECOND: page geometry and image-block
candidates are extracted with PyMuPDF only. Mathpix is used only when `--ocr`
is passed, through the existing app/mathpix.py adapter (OCR transcription, not
LLM generation). No DB writes, no servable rows, no fabricated answers.

Outputs:
  data/nta_raw/diagram_candidates.jsonl     durable candidate rows
  data/nta_raw/diagram_assets/<paper>/…     cropped diagram PNGs when enabled
  reports/diagram_extraction.md             run summary
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import extract_nta_papers as nta

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "nta_raw"
PAPERS_DIR = DATA_DIR / "papers"
ASSET_DIR = DATA_DIR / "diagram_assets"
CANDIDATES_PATH = DATA_DIR / "diagram_candidates.jsonl"
OCR_CACHE_DIR = ROOT / "scratch" / "nta_mathpix_cache"
REPORT_PATH = ROOT / "reports" / "diagram_extraction.md"

RENDER_SCALE = 2.0
# Below this an image block is usually a logo/icon; above this it is a scan.
MIN_DIAGRAM_AREA_RATIO = 0.003
FULL_PAGE_SCAN_RATIO = 0.85
MIN_SIDE_PT = 36


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text())
    return default


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def paper_artifact(paper_id: str) -> dict:
    return load_json(PAPERS_DIR / f"{paper_id}.json", {})


def artifact_has_diagram_signal(artifact: dict) -> bool:
    if artifact.get("status") == "needs_ocr":
        return True
    for q in artifact.get("questions", []):
        flags = set(q.get("parse_flags", []))
        if flags & {
            "references_figure_not_extracted",
            "stem_image_only",
            "options_image_only",
        }:
            return True
    return False


def select_entries(manifest: list[dict], args: argparse.Namespace) -> list[dict]:
    out = []
    for entry in manifest:
        if args.source_tier and entry.get("source_tier") not in set(args.source_tier):
            continue
        if args.source_site and entry.get("source_site") not in set(args.source_site):
            continue
        probe = entry.get("probe") or {}
        if not probe.get("cache_path") or probe.get("error"):
            continue
        if args.only and not any(s in entry["paper_id"] or s in entry["pdf_url"] for s in args.only):
            continue
        if args.all:
            out.append(entry)
            continue
        artifact = paper_artifact(entry["paper_id"])
        if (
            artifact_has_diagram_signal(artifact)
            or entry.get("source_tier") in {"official", "question_bank"}
            or entry.get("source_site") == "www.selfstudys.com"
            or not probe.get("has_text_layer")
        ):
            out.append(entry)
    if args.limit:
        out = out[: args.limit]
    return out


def _block_text(block: dict) -> str:
    parts = []
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            parts.append(span.get("text", ""))
    return " ".join(parts).strip()


def image_candidates_from_page_dict(
    page_dict: dict, page_width: float, page_height: float, page_no: int
) -> list[dict]:
    """Pure PyMuPDF image-block candidates for one page.

    Flags are part of the contract: a full-page scan is not a diagram crop, but
    it is a page that must be OCR'd before diagrams can be attributed.
    """
    page_area = max(page_width * page_height, 1.0)
    candidates = []
    image_index = 0
    for block in page_dict.get("blocks", []):
        if block.get("type") != 1:  # image block
            continue
        bbox = block.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        x0, y0, x1, y1 = [float(v) for v in bbox]
        width = max(x1 - x0, 0.0)
        height = max(y1 - y0, 0.0)
        area_ratio = (width * height) / page_area
        flags = []
        if width < MIN_SIDE_PT or height < MIN_SIDE_PT:
            flags.append("tiny_image")
        if area_ratio < MIN_DIAGRAM_AREA_RATIO:
            flags.append("low_area_image")
        if area_ratio >= FULL_PAGE_SCAN_RATIO:
            flags.append("full_page_scan")
        # eSaral/selfstudys pages carry repeated watermark strips; keep them
        # visible but do not let them count as diagram questions downstream.
        if width > page_width * 0.75 and height < 80:
            flags.append("watermark_suspect")
        candidates.append({
            "page": page_no,
            "image_index": image_index,
            "method": "pymupdf_image_block",
            "bbox": [x0, y0, x1, y1],
            "width_pt": width,
            "height_pt": height,
            "area_ratio": area_ratio,
            "flags": flags,
        })
        image_index += 1
    return candidates


def question_context_from_text_blocks(
    page_dict: dict, image_bbox: list[float]
) -> dict:
    """Nearest question/subject context for an image bbox on the same page."""
    items = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        text = _block_text(block)
        bbox = block.get("bbox")
        if not text or not bbox:
            continue
        items.append({"bbox": [float(v) for v in bbox], "text": text})
    img_y0 = image_bbox[1]
    above = [it for it in items if it["bbox"][3] <= img_y0]
    below = [it for it in items if it["bbox"][1] >= img_y0]
    ordered = sorted(above, key=lambda it: it["bbox"][3], reverse=True) + sorted(
        below, key=lambda it: it["bbox"][1]
    )
    context: dict[str, Any] = {}
    for it in ordered:
        text = it["text"]
        m2026 = nta.HDR2026_RE.search(text)
        if m2026 and "qno" not in context:
            context["qno"] = int(m2026.group(1))
            context["question_id"] = m2026.group(2)
        m = nta.GENERIC_QNO_RE.search(text)
        if m and "qno" not in context:
            context["qno"] = int(m.group(1))
        subj = nta.SECTION_HEADING_RE.search(text) or nta.SUBJECT_LINE_RE.search(text)
        if subj and "subject" not in context:
            subject = subj.group(1).title()
            context["subject"] = "Mathematics" if subject == "Maths" else subject
            if subj.re is nta.SECTION_HEADING_RE:
                context["section"] = f"Section {subj.group(2)}"
    return context


def question_context_from_ocr_lines(text_lines: list[dict], span: dict) -> dict:
    """Question/subject context for a Mathpix diagram span using OCR line y-spans."""
    top = span.get("top")
    if top is None:
        return {}
    above = [ln for ln in text_lines if ln.get("bottom") is not None and ln["bottom"] <= top]
    below = [ln for ln in text_lines if ln.get("top") is not None and ln["top"] >= top]
    ordered = sorted(above, key=lambda ln: ln["bottom"], reverse=True) + sorted(
        below, key=lambda ln: ln["top"]
    )
    context: dict[str, Any] = {}
    for ln in ordered:
        text = ln.get("text") or ""
        m = nta.GENERIC_QNO_RE.search(text)
        if m and "qno" not in context:
            context["qno"] = int(m.group(1))
        subj = nta.SECTION_HEADING_RE.search(text) or nta.SUBJECT_LINE_RE.search(text)
        if subj and "subject" not in context:
            subject = subj.group(1).title()
            context["subject"] = "Mathematics" if subject == "Maths" else subject
            if subj.re is nta.SECTION_HEADING_RE:
                context["section"] = f"Section {subj.group(2)}"
    return context


def ocr_text_context(text_lines: list[dict], span: dict, max_lines: int = 10) -> str:
    """Text around a Mathpix diagram span: nearest lines above plus overlaps.

    This is the raw OCR fallback for sources (question banks) that have no
    per-question paper artifact to join against.
    """
    top = span.get("top")
    bottom = span.get("bottom")
    if top is None:
        return ""
    above = [
        ln for ln in text_lines
        if ln.get("bottom") is not None and ln["bottom"] <= top
    ]
    above.sort(key=lambda ln: ln["bottom"], reverse=True)
    overlap = [
        ln for ln in text_lines
        if ln.get("top") is not None and ln.get("bottom") is not None
        and ln["top"] <= (bottom or top) and ln["bottom"] >= top
    ]
    parts = [ln.get("text", "").strip() for ln in above[:max_lines]]
    parts.reverse()
    parts += [ln.get("text", "").strip() for ln in overlap]
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()


def _fitz():
    import fitz  # PyMuPDF — dev-only dependency (not in requirements.txt)

    return fitz


def render_page_png(page, scale: float = RENDER_SCALE) -> bytes:
    fitz = _fitz()
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return pix.tobytes("png")


def crop_pdf_region(page, bbox: list[float], out_path: Path) -> dict:
    fitz = _fitz()
    pix = page.get_pixmap(matrix=fitz.Matrix(RENDER_SCALE, RENDER_SCALE), clip=fitz.Rect(bbox), alpha=False)
    data = pix.tobytes("png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return {"path": str(out_path.relative_to(ROOT)), "sha256": sha256_bytes(data),
            "width": pix.width, "height": pix.height, "mime": "image/png"}


def crop_png_region(png_bytes: bytes, span: dict, out_path: Path) -> Optional[dict]:
    try:
        from PIL import Image
    except ImportError:
        return None
    left = span.get("left")
    right = span.get("right")
    top = span.get("top")
    bottom = span.get("bottom")
    if None in (left, right, top, bottom):
        return None
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    w, h = img.size
    box = (max(0, int(left)), max(0, int(top)), min(w, int(right)), min(h, int(bottom)))
    if box[2] - box[0] < 20 or box[3] - box[1] < 20:
        return None
    buf = io.BytesIO()
    img.crop(box).save(buf, format="PNG")
    data = buf.getvalue()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return {"path": str(out_path.relative_to(ROOT)), "sha256": sha256_bytes(data),
            "width": box[2] - box[0], "height": box[3] - box[1], "mime": "image/png"}


def ocr_page(png_bytes: bytes, label: str) -> dict:
    """Mathpix OCR adapter. Returns a compact dict; raises on hard failure."""
    cache = OCR_CACHE_DIR / f"{label}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.mathpix import read_page  # noqa: E402

    result = None
    # Mathpix rate limits are transient; back off instead of recording a hard
    # OCR error for the page. Cache remains success-only.
    for attempt, delay in enumerate([0, 20, 60, 120]):
        if delay:
            time.sleep(delay)
        try:
            result = read_page(png_bytes, "image/png", doubt_id=label)
            break
        except Exception as exc:
            if "Limit exceeded" in str(exc) and attempt < 3:
                print(f"[ocr] {label}: rate limited; backing off {delay or 'next'}s")
                continue
            raise
    if result is None:
        raise RuntimeError("Mathpix OCR failed after rate-limit backoff")
    compact = {
        "text": result.get("text", ""),
        "confidence": result.get("confidence"),
        "page_confidence": result.get("page_confidence"),
        "diagram_regions": result.get("diagram_regions", 0),
        "diagram_spans": result.get("diagram_spans", []),
        "text_lines": result.get("text_lines", []),
        "ocr_ms": result.get("ocr_ms"),
    }
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(compact, ensure_ascii=False) + "\n")
    time.sleep(0.2)
    return compact


def base_candidate(entry: dict) -> dict:
    tags = entry.get("tags") or nta.build_tags(entry, entry.get("pdf_url", ""))
    return {
        "paper_id": entry["paper_id"],
        "exam": entry.get("exam"),
        "exam_tag": entry.get("exam_tag") or tags[0],
        "tags": tags,
        "year": entry.get("year"),
        "session": entry.get("session"),
        "exam_date": entry.get("exam_date"),
        "shift": entry.get("shift"),
        "subject": entry.get("subject"),
        "paper_type": entry.get("paper_type"),
        "source_tier": entry.get("source_tier"),
        "source_site": entry.get("source_site"),
        "source_page_url": entry.get("source_page_url") or entry.get("pdf_url"),
        "pdf_url": entry.get("pdf_url"),
        "official_key_url": entry.get("official_key_url"),
    }


def load_candidates(path: Optional[Path] = None) -> list[dict]:
    path = path or CANDIDATES_PATH
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _figure_flagged_question(question: dict) -> bool:
    # stem_image_only/options_image_only are NOT enough: 2026 NTA papers render
    # ordinary text stems/options as images. Without a Mathpix diagram region,
    # only an explicit "figure/graph/diagram/table" reference counts here.
    return "references_figure_not_extracted" in set(question.get("parse_flags", []))


def find_matching_question(artifact: dict, row: dict) -> Optional[dict]:
    questions = artifact.get("questions", [])
    ctx = row.get("context") or {}
    qid = ctx.get("question_id")
    if qid:
        for q in questions:
            if q.get("question_id") == qid:
                return q
    qno = ctx.get("qno")
    if qno is not None:
        page_matches = [
            q for q in questions
            if q.get("qno") == qno and row.get("page") is not None
            and q.get("page_start") <= row["page"] <= q.get("page_end", q.get("page_start"))
        ]
        if page_matches:
            return page_matches[0]
        qno_matches = [q for q in questions if q.get("qno") == qno]
        if qno_matches:
            return qno_matches[0]
    return None


def diagram_confirmation(row: dict, artifact: dict) -> Optional[str]:
    """Return how a diagram is confirmed, or None for a mere image candidate."""
    if row.get("method") == "mathpix_line_data":
        return "mathpix_line_data"
    if row.get("method") == "pymupdf_image_block":
        flags = set(row.get("flags", []))
        if flags & {"tiny_image", "watermark_suspect", "full_page_scan", "low_area_image"}:
            return None
        q = find_matching_question(artifact, row)
        if q and _figure_flagged_question(q):
            return "figure_flag_plus_image_block"
    return None


def answer_sheet_for(artifact: dict, question: Optional[dict]) -> dict:
    sheet = artifact.get("answer_sheet") or {}
    if question is None:
        return sheet or {"status": "unavailable", "entries": []}
    qno = question.get("qno")
    entries = [
        e for e in sheet.get("entries", [])
        if e.get("qno") == qno or (
            question.get("question_id") and e.get("question_id") == question.get("question_id")
        )
    ]
    out = dict(sheet)
    out["entries"] = entries
    return out


def cmd_materialize(args: argparse.Namespace) -> None:
    rows = []
    for path in sorted(DATA_DIR.glob("diagram_candidates*.jsonl")):
        rows.extend(load_candidates(path))
    valid_ids = {e["paper_id"] for e in nta.load_manifest()}
    rows = [r for r in rows if r.get("paper_id") in valid_ids]
    out_rows = []
    seen = set()
    for row in rows:
        artifact = paper_artifact(row["paper_id"])
        confirmation = diagram_confirmation(row, artifact)
        if not confirmation:
            continue
        question = find_matching_question(artifact, row)
        bbox = row.get("bbox") or [None, None, None, None]
        key = (
            row["paper_id"], row.get("page"), (question or {}).get("question_id"),
            (question or row.get("context") or {}).get("qno"),
            tuple(round(float(v), 1) if v is not None else None for v in bbox),
        )
        if key in seen:
            continue
        seen.add(key)
        out = {
            "diagram_question_id": hashlib.sha256(
                json.dumps(key, default=str).encode()
            ).hexdigest()[:16],
            "confirmation": confirmation,
            "paper_id": row["paper_id"],
            "exam": row.get("exam"),
            "exam_tag": row.get("exam_tag"),
            "tags": row.get("tags"),
            "year": row.get("year"),
            "session": row.get("session"),
            "exam_date": row.get("exam_date"),
            "shift": row.get("shift"),
            "subject": (
                (question or {}).get("subject")
                or (row.get("context") or {}).get("subject")
                or row.get("subject")
            ),
            "section": (question or {}).get("section") or (row.get("context") or {}).get("section"),
            "qno": (question or {}).get("qno") or (row.get("context") or {}).get("qno"),
            "question_id": (question or {}).get("question_id") or (row.get("context") or {}).get("question_id"),
            "question_type": (question or {}).get("question_type"),
            "question_text": (question or {}).get("text") or row.get("ocr_text_context") or None,
            "options": (question or {}).get("options"),
            "answer_sheet": answer_sheet_for(artifact, question),
            "source_tier": row.get("source_tier"),
            "source_site": row.get("source_site"),
            "source_page_url": row.get("source_page_url") or row.get("pdf_url"),
            "pdf_url": row.get("pdf_url"),
            "official_key_url": row.get("official_key_url"),
            "page": row.get("page"),
            "diagram_bbox": row.get("bbox"),
            "diagram_asset": row.get("asset"),
            "has_figure": True,
            # The diagram belongs to the question region that contained it; for
            # option-grid figures the gate can refine this later from the asset.
            "has_stem_figure": True,
            # Raw diagram questions are never servable directly; the pending_gate
            # discipline from EXTRACTION_QUALITY_SPEC.md applies at insert time.
            "needs_manual": "pending_gate",
            "ocr": row.get("ocr"),
            "raw_candidate": row,
        }
        if not out["question_text"]:
            out["needs_ocr_text"] = True
        out_rows.append(out)
    OUT_PATH = DATA_DIR / "diagram_questions.jsonl"
    OUT_PATH.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out_rows)
    )
    print(f"[materialize] wrote {len(out_rows)} diagram questions to {OUT_PATH}")


def scan_entry(entry: dict, args: argparse.Namespace) -> list[dict]:
    fitz = _fitz()
    probe = entry.get("probe") or {}
    pdf_path = ROOT / probe["cache_path"]
    rows = []
    doc = fitz.open(pdf_path)
    try:
        for page_index in range(doc.page_count):
            if args.max_pages and page_index >= args.max_pages:
                break
            page = doc[page_index]
            page_no = page_index + 1
            page_dict = page.get_text("dict")
            candidates = image_candidates_from_page_dict(
                page_dict, page.rect.width, page.rect.height, page_no
            )
            ocr = None
            should_ocr = args.ocr and (
                candidates or not probe.get("has_text_layer") or entry.get("source_tier") == "official"
            )
            png_bytes = None
            if should_ocr:
                png_bytes = render_page_png(page)
                label = f"{entry['paper_id']}_p{page_no}"
                try:
                    ocr = ocr_page(png_bytes, label)
                except Exception as exc:  # OCR failure must not kill the scan
                    ocr = {"error": str(exc)}
            skip_flags = {"low_area_image", "tiny_image", "watermark_suspect"}
            for cand in candidates:
                if skip_flags & set(cand["flags"]) and not args.keep_low_area:
                    continue
                row = base_candidate(entry)
                row.update(cand)
                row["context"] = question_context_from_text_blocks(page_dict, cand["bbox"])
                row["ocr"] = (
                    {
                        "status": "error" if ocr.get("error") else "ok",
                        "confidence": ocr.get("confidence"),
                        "diagram_regions": ocr.get("diagram_regions"),
                        "ocr_ms": ocr.get("ocr_ms"),
                        "error": ocr.get("error"),
                    }
                    if ocr
                    else {"status": "not_run"}
                )
                if args.write_assets and "full_page_scan" not in cand["flags"]:
                    asset_name = (
                        f"{entry['paper_id']}/p{page_no:03d}_img{cand['image_index']:02d}_"
                        f"{int(cand['bbox'][0])}x{int(cand['bbox'][1])}.png"
                    )
                    row["asset"] = crop_pdf_region(page, cand["bbox"], ASSET_DIR / asset_name)
                rows.append(row)
            if ocr and ocr.get("diagram_spans"):
                for i, span in enumerate(ocr["diagram_spans"]):
                    row = base_candidate(entry)
                    row.update({
                        "page": page_no,
                        "image_index": i,
                        "method": "mathpix_line_data",
                        "bbox": [span.get("left"), span.get("top"), span.get("right"), span.get("bottom")],
                        "context": question_context_from_ocr_lines(ocr.get("text_lines", []), span),
                        "ocr_text_context": ocr_text_context(ocr.get("text_lines", []), span),
                        "flags": ["mathpix_diagram_region"],
                        "ocr": {
                            "status": "ok",
                            "confidence": ocr.get("confidence"),
                            "diagram_regions": ocr.get("diagram_regions"),
                            "ocr_ms": ocr.get("ocr_ms"),
                        },
                    })
                    if args.write_assets and png_bytes:
                        asset_name = f"{entry['paper_id']}/p{page_no:03d}_mathpix{i:02d}.png"
                        asset = crop_png_region(png_bytes, span, ASSET_DIR / asset_name)
                        if asset:
                            row["asset"] = asset
                    rows.append(row)
    finally:
        doc.close()
    return rows


def cmd_scan(args: argparse.Namespace) -> None:
    manifest = nta.load_manifest()
    entries = select_entries(manifest, args)
    selected_ids = {e["paper_id"] for e in entries}
    out_path = Path(args.out) if getattr(args, "out", None) else CANDIDATES_PATH
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    scanned_rows = []
    kept_rows = []
    if out_path.exists() and not args.replace:
        kept_rows = [r for r in load_candidates(out_path) if r.get("paper_id") not in selected_ids]
    workers = max(1, getattr(args, "workers", 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(scan_entry, entry, args): entry for entry in entries}
        for fut in as_completed(futures):
            entry = futures[fut]
            try:
                rows = fut.result()
            except Exception as exc:
                rows = [base_candidate(entry) | {
                    "page": None, "method": "scan_error", "flags": ["scan_error"],
                    "error": str(exc), "ocr": {"status": "not_run"},
                }]
            scanned_rows.extend(rows)
            all_rows = kept_rows + scanned_rows
            out_path.write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in all_rows)
            )
            print(f"[scan] {entry['paper_id']}: {len(rows)} diagram candidates")
    all_rows = kept_rows + scanned_rows
    write_summary(all_rows, len(entries))
    print(f"[scan] wrote {len(scanned_rows)} new candidates "
          f"({len(all_rows)} total) to {out_path}")


def write_summary(rows: list[dict], n_entries: int) -> None:
    by_method: dict[str, int] = {}
    by_tag: dict[str, int] = {}
    with_asset = 0
    ocr_ok = 0
    for r in rows:
        by_method[r.get("method", "?")] = by_method.get(r.get("method", "?"), 0) + 1
        by_tag[r.get("exam_tag", "?")] = by_tag.get(r.get("exam_tag", "?"), 0) + 1
        with_asset += 1 if r.get("asset") else 0
        ocr_ok += 1 if (r.get("ocr") or {}).get("status") == "ok" else 0
    lines = [
        "# Diagram extraction summary",
        "",
        f"- papers scanned: {n_entries}",
        f"- diagram candidates: {len(rows)}",
        f"- candidates with cropped assets: {with_asset}",
        f"- candidates with Mathpix OCR ok: {ocr_ok}",
        "",
        "## By method",
        "",
    ]
    lines += [f"- {k}: {v}" for k, v in sorted(by_method.items())]
    lines += ["", "## By exam tag", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(by_tag.items())]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan", help="scan cached PDFs for diagram candidates")
    p.add_argument("--all", action="store_true", help="scan every probed paper")
    p.add_argument("--only", nargs="*", default=None, help="paper_id or URL substrings")
    p.add_argument("--source-tier", nargs="*", default=None,
                   help="restrict to source_tier values (official/mirror/question_bank)")
    p.add_argument("--source-site", nargs="*", default=None,
                   help="restrict to source_site values (e.g. www.selfstudys.com)")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--max-pages", type=int, default=None,
                   help="cap pages per paper (useful for OCR smoke tests)")
    p.add_argument("--write-assets", action="store_true", help="crop diagram PNGs into data/")
    p.add_argument("--ocr", action="store_true", help="run Mathpix OCR for candidate pages")
    p.add_argument("--keep-low-area", action="store_true", help="keep low-area image blocks")
    p.add_argument("--replace", action="store_true",
                   help="overwrite candidates instead of merging with existing rows")
    p.add_argument("--workers", type=int, default=4,
                   help="parallel papers to scan/OCR")
    p.add_argument("--out", default=None,
                   help="override candidates JSONL path for parallel source scans")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("materialize", help="build question-level diagram artifacts from candidates")
    p.set_defaults(func=cmd_materialize)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
