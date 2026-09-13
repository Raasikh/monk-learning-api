#!/usr/bin/env python3
"""Re-derive diagram attribution: the assembly unit is the QUESTION, not the page.

Dev-time script — deterministic geometry + text matching, no LLM calls.

Root defect (docs/DIAGRAM_DIRECTIVE_ATTRIBUTION.md): figure regions were
paired with whatever question sat on the same page (~80% wrong). v2 fixes two
deeper failure modes found on the eSaral two-column subject reprints:

1. text_lines in the compact Mathpix cache carry NO x-coordinates, so column
   detection is structural: two question markers at nearly the same `top`
   signal a two-column page; markers are partitioned into the interleaving
   whose concatenated reading order has fewer numbering inversions, and
   figures join a column by their x-center against the page midpoint.
2. Printed question numbers collide across sections (Section A "4." vs
   Section B "4.") and section headers are not on every page, so spans are
   matched to artifact questions by TEXT PREFIX (normalized stem start),
   not by numbers at all.

Attribution outcomes per candidate row:
- ``question_span``: the figure's column + vertical span matches an artifact
  question by stem text — context.qno is set to that question (reassigning
  page-adjacency errors).
- ``none``: no span owns the figure — the figure is dropped, never attached
  as a fallback (§3.2: "no figure" is a valid, common outcome).
- ``stem_reference_absent``: the stem references a figure but none is
  in-span — quarantined, since a required-but-absent figure is not servable.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from extract_diagram_questions import ocr_page, render_page_png  # noqa: E402

DATA = ROOT / "data" / "nta_raw"
OCR_CACHE = ROOT / "scratch" / "nta_mathpix_cache"
RENDER_SCALE = 2.0

FIG_REF_RE = re.compile(
    r"(?i)\b(in\s+the\s+figure|as\s+shown|shown\s+below|the\s+graph|"
    r"the\s+figure|following\s+figure|the\s+circuit|the\s+diagram)\b"
)

MARK_RES = [
    re.compile(r"^\s*Question\s+Number\s*:\s*(\d{1,3})\b", re.I),      # 2026 NTA
    re.compile(r"^\s*(\d{1,2})\s*\.\s*Question\s+ID\s*[:.]", re.I),    # eSaral with QID
    re.compile(r"^\s*Q\s*(\d{1,3})\s*[.)]", re.I),                     # MathonGo
    re.compile(r"^\s*(\d{1,3})\s*[.)]\s+\S"),                          # generic "N." / "N)"
]
ANSWER_MARK_RE = re.compile(
    r"(?i)^\s*(Official\s+Ans|Ans\s*[.:]|Sol\s*[.:]|Correct\s+(?:Answer|Option)|Answer\s*:)"
)
NORM_TXT_RE = re.compile(r"[^a-z0-9]+")


def norm_txt(s: str) -> str:
    return NORM_TXT_RE.sub("", (s or "").lower())


def marker_qno(line_text: str) -> int | None:
    t = line_text.strip()
    for rx in MARK_RES:
        m = rx.match(t)
        if m:
            return int(m.group(1))
    return None


def page_ocr(paper_id: str, page: int, cache_pdf: Path | None) -> dict:
    f = OCR_CACHE / f"{paper_id}_p{page}.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    if cache_pdf and cache_pdf.exists():
        import fitz
        doc = fitz.open(cache_pdf)
        try:
            png = render_page_png(doc[page - 1])
        finally:
            doc.close()
        return ocr_page(png, f"{paper_id}_p{page}")
    return {}


def page_width(paper_id: str, page: int, cache_pdf: Path | None) -> float:
    if cache_pdf and cache_pdf.exists():
        try:
            import fitz
            doc = fitz.open(cache_pdf)
            try:
                return doc[page - 1].rect.width * RENDER_SCALE
            finally:
                doc.close()
        except Exception:
            pass
    return 595.0 * RENDER_SCALE  # A4 default


def build_spans(lines: list[dict], width: float) -> list[dict]:
    marks = []
    for ln in lines:
        qno = marker_qno(ln.get("text") or "")
        if qno is not None:
            marks.append({"qno": qno, "top": ln.get("top", 0), "bottom": ln.get("bottom", 0)})
    marks.sort(key=lambda m: m["top"])
    uniq = []
    for m in marks:
        if uniq and uniq[-1]["qno"] == m["qno"] and m["top"] - uniq[-1]["top"] < 60:
            continue
        uniq.append(m)

    two_col = any(
        abs(uniq[i]["top"] - uniq[i + 1]["top"]) < 50
        for i in range(len(uniq) - 1)
    )
    mid = width / 2

    def inversions(seq):
        return sum(1 for i in range(len(seq)) for j in range(i + 1, len(seq)) if seq[i] > seq[j])

    if two_col and len(uniq) >= 2:
        a = [uniq[0::2], uniq[1::2]]
        b = [uniq[1::2], uniq[0::2]]
        a_inv = inversions([m["qno"] for m in a[0] + a[1]])
        b_inv = inversions([m["qno"] for m in b[0] + b[1]])
        col1, col2 = (a if a_inv <= b_inv else b)
        columns = [("L", col1), ("R", col2)]
    else:
        columns = [(None, uniq)]

    spans = []
    page_bottom = max((l.get("bottom", 0) for l in lines), default=10**9)
    for col_name, col_marks in columns:
        col_marks = sorted(col_marks, key=lambda m: m["top"])
        for i, m in enumerate(col_marks):
            bottom = col_marks[i + 1]["top"] if i + 1 < len(col_marks) else max(page_bottom, m["top"]) + 1
            x0, x1 = (0, mid) if col_name == "L" else ((mid, 10**9) if col_name == "R" else (0, 10**9))
            seg_lines = sorted(
                [l for l in lines if m["top"] - 1 <= l.get("top", 0) < m["top"] + 160],
                key=lambda l: l.get("top", 0),
            )
            seg = [(l.get("text") or "") for l in seg_lines]
            # the answer marker ends the question block; figures BELOW it are
            # solution/option-grid content, not the stem figure (vision check
            # 2026-09-12: post-answer figures drove the wrong-attribution fails)
            answer_top = None
            for l in sorted(lines, key=lambda l: l.get("top", 0)):
                if l.get("top", 0) < m["top"]:
                    continue
                if l.get("top", 0) >= bottom:
                    break
                if ANSWER_MARK_RE.match((l.get("text") or "").strip()):
                    answer_top = l.get("top", 0)
                    break
            spans.append({
                "qno_printed": m["qno"],
                "top": m["top"],
                "bottom": bottom,
                "answer_top": answer_top,
                "x": (x0, x1),
                "text": " ".join(seg)[:400],
            })
    return spans


def owning_span(spans: list[dict], ftop: float, fleft: float, fright: float):
    fcx = (fleft + fright) / 2
    for sp in spans:
        x0, x1 = sp["x"]
        if not (x0 <= fcx < x1 and ftop >= sp["top"] - 6 and ftop < sp["bottom"]):
            continue
        # reject solution-region figures: below the answer marker they belong
        # to the worked solution (or a different question's illustration),
        # not to the stem
        if sp.get("answer_top") is not None and ftop >= sp["answer_top"]:
            return None
        return sp
    return None


def figure_pixel_span(row: dict) -> tuple[float, float, float, float] | None:
    bbox = row.get("bbox")
    if not bbox or len(bbox) < 4 or bbox[1] is None:
        return None
    if row.get("method") == "mathpix_line_data":
        return float(bbox[1]), float(bbox[3]), float(bbox[0]), float(bbox[2])
    return (
        float(bbox[1]) * RENDER_SCALE,
        float(bbox[3]) * RENDER_SCALE,
        float(bbox[0]) * RENDER_SCALE,
        float(bbox[2]) * RENDER_SCALE,
    )


BOILERPLATE_OPENERS = [
    "given below are two statements",
    "given below are two statement",
    "match list i with list ii",
    "match list i with list ii",
    "the major product of the following reaction",
    "which of the following",
    "consider the following",
    "the correct order of",
    "order of stability of the following",
    "in the following sequence of reaction",
    "the iupac name of the compound",
    "choose the correct answer",
]


def strip_boilerplate(text: str) -> str:
    t = text.lower().strip()
    changed = True
    while changed:
        changed = False
        for bp in BOILERPLATE_OPENERS:
            if t.startswith(bp):
                t = t[len(bp):].lstrip(" :.-\n")
                changed = True
    return t


def match_question(span_text: str, questions: list[dict]) -> dict | None:
    """Match a span's opening text to an artifact question by stem prefix.

    Boilerplate openers ("Given below are two statements", "Which of the
    following"…) are stripped from BOTH sides first — a 25-char LCP on shared
    boilerplate is a false match (vision-check 2026-09-12: boilerplate
    collisions attached option figures from adjacent questions).
    """
    stripped = re.sub(
        r"^\s*(?:Question\s+Number\s*:\s*|Q\s*)?\d{1,3}\s*[.)]\s*",
        "",
        span_text,
        flags=re.I,
    )
    st = norm_txt(strip_boilerplate(stripped))
    if len(st) < 30:
        return None
    probe = st[:60]
    best, best_len = None, 0
    for q in questions:
        qt = norm_txt(strip_boilerplate(q.get("text") or ""))
        if not qt:
            continue
        # longest common prefix of probe against question stem
        n = 0
        for a, b in zip(probe, qt):
            if a != b:
                break
            n += 1
        if n > best_len:
            best, best_len = q, n
    if best is not None and best_len >= 25:
        return best
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--only-paper", nargs="*", default=None)
    args = ap.parse_args()

    stats = Counter()
    manifest = json.loads((DATA / "manifest.json").read_text())
    pdf_by_paper = {
        e["paper_id"]: (ROOT / (e.get("probe") or {}).get("cache_path", ""))
        for e in manifest
    }
    questions_by_paper: dict[str, list] = {}
    for e in manifest:
        art_path = DATA / "papers" / f"{e['paper_id']}.json"
        if not art_path.exists():
            continue
        try:
            art = json.loads(art_path.read_text())
        except Exception:
            continue
        questions_by_paper[e["paper_id"]] = art.get("questions") or []

    for cand_path in sorted(DATA.glob("diagram_candidates*.jsonl")):
        out_lines = []
        for line in cand_path.open():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                out_lines.append(line)
                continue
            if args.only_paper and row.get("paper_id") not in args.only_paper:
                out_lines.append(json.dumps(row, ensure_ascii=False))
                continue
            if row.get("hygiene_boilerplate_only"):
                out_lines.append(json.dumps(row, ensure_ascii=False))
                continue
            pid = row.get("paper_id")
            page = row.get("page")
            if not pid or not page:
                row["figure_attribution"] = "none"
                row.pop("asset", None)
                stats["no_metadata"] += 1
                out_lines.append(json.dumps(row, ensure_ascii=False))
                continue
            pdf = pdf_by_paper.get(pid)
            ocr = page_ocr(pid, page, pdf)
            lines = ocr.get("text_lines") or []
            spans = build_spans(lines, page_width(pid, page, pdf))
            fspan = figure_pixel_span(row)
            sp = owning_span(spans, fspan[0], fspan[2], fspan[3]) if fspan else None
            owner_q = None
            if sp is not None:
                owner_q = match_question(sp["text"], questions_by_paper.get(pid, []))
                if owner_q is None:
                    stats["span_text_unmatched"] += 1
            if owner_q is not None:
                ctx = row.setdefault("context", {})
                old_qno = ctx.get("qno")
                ctx["qno"] = owner_q.get("qno")
                if owner_q.get("section"):
                    ctx["section"] = owner_q["section"]
                if owner_q.get("subject"):
                    ctx["subject"] = owner_q["subject"]
                row["figure_attribution"] = "question_span"
                stats["attributed_question_span"] += 1
                if old_qno is not None and old_qno != owner_q.get("qno"):
                    stats["reassigned_qno"] += 1
            else:
                stem = (row.get("ocr_text_context") or "")
                if FIG_REF_RE.search(stem):
                    row["figure_attribution"] = "stem_reference_absent"
                    row["needs_manual"] = "figure_referenced_absent"
                    row.pop("asset", None)
                    stats["figure_referenced_absent"] += 1
                else:
                    row["figure_attribution"] = "none"
                    row.pop("asset", None)
                    stats["unattached"] += 1
            out_lines.append(json.dumps(row, ensure_ascii=False))
        if args.write:
            cand_path.write_text("\n".join(out_lines) + "\n")

    print(f"[reattribute] {dict(stats)}")
    if not args.write:
        print("[reattribute] dry run — pass --write")


if __name__ == "__main__":
    main()
