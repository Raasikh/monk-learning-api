"""Ingest the Drona master books via Mathpix, with section keys and QA gates.

Replaces the PyMuPDF text path in ingest_master_books.py. That path is kept
for reference; this one is what runs.

WHAT CHANGED AND WHY
--------------------
Content comes from Mathpix .lines.json instead of page.get_text(). Measured on
30 hand-transcribed equations: Mathpix 30/30 exact, the incumbent 1/30. See
scripts/mathpix_extract.py for the full bake-off and the mu-zero evidence.

Structure comes from Mathpix's own line typing rather than regexes:

    section_header  ->  section_key, carried on every chunk
    page_info       ->  running furniture, dropped
    table_of_contents_* -> contents pages, dropped
    math            ->  the QA gate

That typing is more correct than the regexes it replaces, not merely more
convenient. In the pilot slice my folio regex flagged four pages; three were
contents pages and the fourth was a genuine binary data table whose cells hold
0 and 1. The regex would have deleted real data, because "a line of only
digits" describes both a folio and a matrix entry.

The chunker keeps the two fixes from the previous ingest -- sentence-level
overlap (whole-paragraph overlap fired on 4% of boundaries; sentences fire on
50%) and word-sliding for oversize paragraphs (token-slice decoding cut
multi-byte characters and produced 795 mojibake chunks).
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz
import tiktoken
from openai import OpenAI
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mathpix_extract as mx  # noqa: E402

BOOK_ROOT = "/Users/raasikhnaveed/Desktop/dronav1project/"
BOOKS = [
    ("biology", 11, "book_builds_b11/Drona_Class11_Biology_Master_Reference.pdf"),
    ("biology", 12, "book_builds_b12/Drona_Class12_Biology_Master_Reference.pdf"),
    ("chemistry", 11, "book_builds_chem11/Drona_Class11_Chemistry_Master_Reference.pdf"),
    ("chemistry", 12, "book_builds_chem12/Drona_Class12_Chemistry_Master_Reference.pdf"),
    ("mathematics", 11, "book_builds/Drona_Class11_Mathematics_Master_Reference.pdf"),
    ("mathematics", 12, "book_builds_c12/Drona_Class12_Mathematics_Master_Reference.pdf"),
    ("physics", 11, "book_builds_p11/Drona_Class11_Physics_Master_Reference.pdf"),
    ("physics", 12, "book_builds_p12/Drona_Class12_Physics_Master_Reference.pdf"),
]

CHAPTER_RE = re.compile(r"^Chapter\s+(\d+)\s*[:\-–]\s*(.+)$", re.I)
CONTINUATION_RE = re.compile(r"^Chapter\s+(\d+)\s+(Supplement|Round\s*\d*\s*Addendum)", re.I)
EXCLUDE_RE = re.compile(r"^\s*(Errata|Table of Contents|Index)\s*$", re.I)

MAX_TOKENS, OVERLAP, MATCH_FLOOR = 800, 100, 0.55
tokenizer = tiktoken.get_encoding("cl100k_base")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def sanitize(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\x00", "")
    # Mathpix reflows hyphenated line breaks to "tem-\n\nperature" -- a BLANK
    # line, not a single newline. The previous regex only matched \w-\n\w and
    # therefore reported 0 soft hyphens on Mathpix output while 41 of 50 pages
    # still had them. Measured, not assumed.
    text = re.sub(r"(\w)-\s*\n\s*\n?\s*(\w)", r"\1\2", text)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text).strip()


def chapter_spans(doc) -> List[dict]:
    """Chapter number, title and page ranges from the PDF outline.

    Still from fitz: the outline is structural metadata and is correct. Only
    the page CONTENT moves to Mathpix.
    """
    l1 = [(t, pg) for lvl, t, pg in doc.get_toc() if lvl == 1]
    marks: List[Tuple[int, Optional[str], int]] = []
    for title, pg in l1:
        if EXCLUDE_RE.match(title):
            marks.append((-1, title, pg)); continue
        m = CHAPTER_RE.match(title)
        if m:
            marks.append((int(m.group(1)), m.group(2).strip(), pg)); continue
        c = CONTINUATION_RE.match(title)
        marks.append((int(c.group(1)), None, pg) if c else (-1, title, pg))

    spans: Dict[int, dict] = {}
    for i, (num, title, pg) in enumerate(marks):
        end = (marks[i + 1][2] - 1) if i + 1 < len(marks) else len(doc)
        if num < 0:
            continue
        s = spans.setdefault(num, {"num": num, "title": title, "ranges": []})
        if title and not s["title"]:
            s["title"] = title
        s["ranges"].append((pg, end))
    return [v for _, v in sorted(spans.items())]


def section_key(chapter_num: int, heading: Optional[str]) -> str:
    """Stable identifier for a book section.

    This is the fix for the retrieval finding that mattered most: a concept
    that OWNS a book section retrieves at 100% top-1, one that SHARES a
    section with a sibling retrieves at 44%, and chapter size is irrelevant
    (r = +0.048). Retrieval cannot separate what the source never separated,
    so the section a chunk came from has to be recorded, not inferred.
    """
    if not heading:
        return f"ch{chapter_num}"
    slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")[:60]
    return f"ch{chapter_num}:{slug}" if slug else f"ch{chapter_num}"


def units_for_chapter(pages_by_no: Dict[int, dict], span: dict) -> List[Tuple[int, str, str]]:
    """(page, section_key, paragraph) for every content unit in a chapter.

    Walks pages in order, tracking the most recent section_header so each unit
    knows which section it belongs to.
    """
    out: List[Tuple[int, str, str]] = []
    heading: Optional[str] = None
    for a, b in span["ranges"]:
        for pno in range(a, b + 1):
            page = pages_by_no.get(pno)
            if page is None or mx.page_is_contents(page):
                continue
            if mx.page_dropped_math(page):
                print(f"     [DROPPED MATHS] p{pno} is a figure page carrying display "
                      f"maths; Mathpix transcribes only the caption")
            for ln in page.get("lines", []):
                ltype = ln.get("type")
                if ltype in mx.SKIP_TYPES:
                    continue
                text = sanitize(ln.get("text") or "")
                if not text:
                    continue
                if ltype == "section_header":
                    heading = re.sub(r"\\[&%$#_]", lambda m: m.group(0)[1], text)
                    continue
                out.append((pno, section_key(span["num"], heading), text))
    return out


def chunk_units(units: List[Tuple[int, str, str]]) -> List[dict]:
    """Chunk within a section, never across one.

    Chunking across a section boundary is what produced chunks whose heading
    described only their first paragraph. A section break is a real semantic
    boundary in these books, so it is also a chunk boundary.
    """
    out: List[dict] = []
    cur: List[Tuple[int, str, str]] = []

    def body(u):
        return "\n\n".join(t for _, _, t in u).strip()

    def tail(u):
        # Trailing SENTENCES up to OVERLAP tokens. Whole-paragraph overlap
        # fired on 4% of boundaries here because paragraphs routinely exceed
        # the budget; sentences fire on 50%.
        if not u:
            return []
        pno, key, _ = u[-1]
        sents = re.findall(r"[^.!?\n]*[.!?]|\n?[^.!?\n]+$", body(u))
        keep, total = [], 0
        for s in reversed(sents):
            st = s.strip()
            if not st:
                continue
            n = len(tokenizer.encode(st))
            if total + n > OVERLAP and keep:
                break
            keep.insert(0, st); total += n
            if total >= OVERLAP:
                break
        joined = " ".join(keep).strip()
        return [(pno, key, joined)] if joined else []

    def flush():
        nonlocal cur
        b = body(cur)
        if b:
            out.append({"text": b, "page_start": min(p for p, _, _ in cur),
                        "page_end": max(p for p, _, _ in cur),
                        "section_key": cur[0][1]})
        cur = tail(cur)

    for pno, key, text in units:
        if cur and cur[0][1] != key:      # section boundary is a chunk boundary
            flush(); cur = []
        prospective = body(cur + [(pno, key, text)])
        if len(tokenizer.encode(prospective)) <= MAX_TOKENS:
            cur.append((pno, key, text)); continue
        flush()
        toks = tokenizer.encode(text)
        if len(toks) > MAX_TOKENS:
            words, window, count = text.split(" "), [], 0
            for w in words:
                wn = len(tokenizer.encode(w + " "))
                if count + wn > MAX_TOKENS and window:
                    seg = sanitize(" ".join(window))
                    if len(seg) > 10:
                        out.append({"text": seg, "page_start": pno, "page_end": pno,
                                    "section_key": key})
                    back = max(1, int(len(window) * OVERLAP / max(count, 1)))
                    window = window[-back:]
                    count = sum(len(tokenizer.encode(x + " ")) for x in window)
                window.append(w); count += wn
            cur = [(pno, key, sanitize(" ".join(window)))] if window else []
        else:
            cur.append((pno, key, text))
    if body(cur):
        out.append({"text": body(cur), "page_start": min(p for p, _, _ in cur),
                    "page_end": max(p for p, _, _ in cur), "section_key": cur[0][1]})
    return [c for c in out if len(c["text"]) > 10]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--only", help="substring filter on the book path")
    args = ap.parse_args()
    dry = not args.execute

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    oa = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    chapters = sb.table("chapters").select("id,name,subject,class_level,chapter_order").execute().data
    script_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]

    total_chunks = total_tokens = 0
    gate_failures: List[str] = []
    print(("DRY RUN" if dry else "EXECUTING") + f"  (script {script_sha})\n")

    for subj, cl, rel in BOOKS:
        if args.only and args.only not in rel:
            continue
        path = BOOK_ROOT + rel
        book = os.path.basename(path)
        doc = fitz.open(path)
        lines = mx.extract(path)
        pages_by_no = {p["page"]: p for p in lines.get("pages", [])}
        cands = [c for c in chapters if c["subject"] == subj and c["class_level"] == cl]
        print(f"=== {subj} {cl} — {book}  ({len(doc)} pdf pages, {len(pages_by_no)} mathpix pages) ===")

        # ---- QA GATE: local maths classifier vs Mathpix's own line typing ----
        missed = []
        for pno, page in pages_by_no.items():
            src = doc[pno - 1].get_text()
            looks_mathy = bool(re.search(r"[∫∑∏√]", src))
            if looks_mathy and not mx.page_has_math(page):
                missed.append(pno)
        if missed:
            msg = (f"{book}: {len(missed)} page(s) contain a big operator in the PDF "
                   f"but Mathpix returned no math line: {missed[:12]}")
            gate_failures.append(msg)
            print(f"  !! GATE {msg}")

        seq = 0
        for span in chapter_spans(doc):
            nt = norm(span["title"] or "")
            best, score = None, 0.0
            for c in cands:
                s = difflib.SequenceMatcher(None, nt, norm(c["name"])).ratio()
                if c["chapter_order"] == span["num"]:
                    s += 0.15
                if s > score:
                    best, score = c, s
            if not best or score < MATCH_FLOOR:
                gate_failures.append(f"{book}: chapter {span['num']} unmatched")
                print(f"  !! UNMATCHED ch{span['num']}: {span['title']}")
                continue

            units = units_for_chapter(pages_by_no, span)
            raw = chunk_units(units)
            keys = {c["section_key"] for c in raw}
            rows = []
            for ch in raw:
                head = (f"[{subj.title()} Class {cl} | Chapter {span['num']}: {span['title']}"
                        f" | {ch['section_key']}]")
                rows.append({
                    "chapter_id": best["id"], "subject": subj, "class_level": cl,
                    "source_file": book, "chunk_index": seq + len(rows),
                    "page_start": ch["page_start"], "page_end": ch["page_end"],
                    "content": f"{head}\n{ch['text']}",
                })
            seq += len(rows)
            total_chunks += len(rows)
            total_tokens += sum(len(tokenizer.encode(r["content"])) for r in rows)
            print(f"  ch{span['num']:<2} {(span['title'] or '')[:38]:40} -> {best['name'][:22]:24} "
                  f"{len(rows):4} chunks  {len(keys):3} sections")

            if dry:
                continue
            sb.table("pdf_chunks").delete().eq("chapter_id", best["id"]).eq("source_file", book).execute()
            for i in range(0, len(rows), 128):
                batch = rows[i:i + 128]
                embs = oa.embeddings.create(model="text-embedding-3-small",
                                            input=[r["content"] for r in batch]).data
                for r, e in zip(batch, embs):
                    r["embedding"] = e.embedding
                sb.table("pdf_chunks").insert(batch).execute()
            got = (sb.table("pdf_chunks").select("id", count="exact")
                   .eq("chapter_id", best["id"]).eq("source_file", book).limit(1).execute().count)
            if got != len(rows):
                print(f"     ABORT: inserted {got}, expected {len(rows)} — old rows kept")
                return 1
            sb.table("pdf_chunks").delete().eq("chapter_id", best["id"]).neq("source_file", book).execute()

    print(f"\nTOTAL {total_chunks} chunks, {total_tokens:,} tokens")
    print(f"extractor=mathpix  ingest_date={date.today()}  script_sha={script_sha}")
    if gate_failures:
        print(f"\nQA GATE FAILURES ({len(gate_failures)}):")
        for g in gate_failures:
            print(f"  {g}")
        return 2
    print("QA gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
