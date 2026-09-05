"""Ingest the eight Drona Master Reference books into pdf_chunks.

WHY A NEW SCRIPT RATHER THAN A RE-RUN OF ingest_pdf_chunks.py
------------------------------------------------------------
The old script assumes ONE PDF PER CHAPTER and matches the chapter by
FILENAME, from ~/Desktop/Master Content. The master books are one PDF per
BOOK -- 1,232 pages of Class 11 Mathematics in a single file whose name
contains no chapter at all. Run unchanged, its matcher would either fail or
bind an entire book to a single chapter.

These books carry a real three-level PDF outline (chapter / subtopic /
section) with page numbers, so chapter boundaries come from the document
itself rather than from a filename guess. All 106 book chapters matched a
database chapter on a dry run before anything was written.

WHAT THIS FIXES BEYOND BETTER CONTENT
-------------------------------------
page_start / page_end. Every one of the 5,266 existing rows has
page_start = page_end = 1, because ingest_pdf_chunks.py:209 hardcodes both.
The column is 100% non-null and 100% information-free. Here they are the real
page span the chunk's text came from, which is the whole reason the column
exists -- see PRE_INGEST_CHECKLIST.md item 2.

Each chunk's text is prefixed with its "Chapter N: Title | Subtopic" heading.
That line is embedded WITH the chunk, which is what separates concepts that
share a passage: today all three "Frog:" concepts and all three brain concepts
retrieve the same chunk, because chapter-level text has nothing in it to tell
them apart. It is also kept in `content`, because retrieval.py passes content
to the model and a chunk that says where it came from grounds better.

SAFETY
------
Nothing is deleted up front. Per chapter: insert the new chunks, verify they
landed, and only then delete that chapter's old rows (discriminated by
source_file, which is per-chapter for the old corpus and per-book for this
one). A failure part-way leaves earlier chapters on new content and later
chapters on old content -- both are servable. There is never a moment when a
chapter has no chunks.

Run with no flags for a dry run. Pass --execute to write.
"""
import argparse
import difflib
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import tiktoken
from openai import OpenAI
from supabase import create_client

BOOK_ROOT = "/Users/raasikhnaveed/Desktop/dronav1project/"
BOOKS = [
    ("mathematics", 11, "book_builds/Drona_Class11_Mathematics_Master_Reference.pdf"),
    ("mathematics", 12, "book_builds_c12/Drona_Class12_Mathematics_Master_Reference.pdf"),
    ("physics", 11, "book_builds_p11/Drona_Class11_Physics_Master_Reference.pdf"),
    ("physics", 12, "book_builds_p12/Drona_Class12_Physics_Master_Reference.pdf"),
    ("biology", 11, "book_builds_b11/Drona_Class11_Biology_Master_Reference.pdf"),
    ("biology", 12, "book_builds_b12/Drona_Class12_Biology_Master_Reference.pdf"),
    ("chemistry", 11, "book_builds_chem11/Drona_Class11_Chemistry_Master_Reference.pdf"),
    ("chemistry", 12, "book_builds_chem12/Drona_Class12_Chemistry_Master_Reference.pdf"),
]

CHAPTER_RE = re.compile(r"^Chapter\s+(\d+)\s*[:\-–]\s*(.+)$", re.I)
# Supplement / Round 2 Addendum belong to the chapter they follow. Errata is
# corrections metadata, not teaching content, and is excluded deliberately.
CONTINUATION_RE = re.compile(r"^Chapter\s+(\d+)\s+(Supplement|Round\s*\d*\s*Addendum)", re.I)
EXCLUDE_RE = re.compile(r"^\s*(Errata|Table of Contents|Index)\s*$", re.I)

MAX_TOKENS = 800
OVERLAP = 100
MATCH_FLOOR = 0.55

tokenizer = tiktoken.get_encoding("cl100k_base")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def sanitize(text: str) -> str:
    """Strip NULs and control characters Postgres text will not accept."""
    if not text:
        return ""
    text = text.replace("\x00", "")
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text).strip()


def chapter_spans(doc) -> List[dict]:
    """Chapter number, title and page ranges, from the level-1 outline.

    A chapter owns several ranges: its main run, its Supplement and its
    Round 2 Addendum, which appear as separate top-level entries.
    """
    l1 = [(t, pg) for lvl, t, pg in doc.get_toc() if lvl == 1]
    marks: List[Tuple[int, Optional[str], int]] = []
    for title, pg in l1:
        if EXCLUDE_RE.match(title):
            marks.append((-1, title, pg))
            continue
        m = CHAPTER_RE.match(title)
        if m:
            marks.append((int(m.group(1)), m.group(2).strip(), pg))
            continue
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


def subtopic_index(doc) -> List[Tuple[int, str]]:
    return sorted(
        [(pg, t) for lvl, t, pg in doc.get_toc() if lvl == 2], key=lambda x: x[0]
    )


def subtopic_at(idx: List[Tuple[int, str]], page: int) -> Optional[str]:
    best = None
    for pg, t in idx:
        if pg <= page:
            best = t
        else:
            break
    return best


def chunk_pages(pages: List[Tuple[int, str]]) -> List[dict]:
    """Chunk (page_no, page_text) pairs, carrying each chunk's real page span."""
    units: List[Tuple[int, str]] = []
    for pno, text in pages:
        for para in sanitize(text).split("\n\n"):
            p = sanitize(para)
            if p:
                units.append((pno, p))

    out: List[dict] = []
    cur = ""
    cur_pages: List[int] = []

    def flush() -> None:
        if cur.strip() and cur_pages:
            out.append(
                {
                    "text": cur.strip(),
                    "page_start": min(cur_pages),
                    "page_end": max(cur_pages),
                }
            )

    for pno, p in units:
        prospective = (cur + "\n\n" + p).strip() if cur else p
        if len(tokenizer.encode(prospective)) <= MAX_TOKENS:
            cur = prospective
            cur_pages.append(pno)
            continue

        flush()
        toks = tokenizer.encode(p)
        if len(toks) > MAX_TOKENS:
            # A single paragraph larger than the window: slide over it.
            step = MAX_TOKENS - OVERLAP
            for i in range(0, len(toks), step):
                w = sanitize(tokenizer.decode(toks[i : i + MAX_TOKENS]))
                if len(w) > 10:
                    out.append({"text": w, "page_start": pno, "page_end": pno})
            cur, cur_pages = "", []
        else:
            cur, cur_pages = p, [pno]

    flush()
    return [c for c in out if len(c["text"]) > 10]


def match_chapter(title: str, num: int, cands: List[dict]) -> Tuple[Optional[dict], float]:
    nt = norm(title)
    best, score = None, 0.0
    for c in cands:
        s = difflib.SequenceMatcher(None, nt, norm(c["name"])).ratio()
        if c["chapter_order"] == num:
            s += 0.15  # order agreement is strong corroborating evidence
        if s > score:
            best, score = c, s
    return best, score


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="write to the database")
    ap.add_argument("--only", help="substring filter on the book path")
    args = ap.parse_args()
    dry = not args.execute

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    oa = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    chapters = (
        sb.table("chapters")
        .select("id,name,subject,class_level,chapter_order")
        .execute()
        .data
    )

    total_chunks = total_tokens = total_chapters = 0
    unmatched: List[tuple] = []
    print("DRY RUN -- nothing will be written\n" if dry else "EXECUTING -- writing\n")

    for subj, cl, rel in BOOKS:
        if args.only and args.only not in rel:
            continue
        path = BOOK_ROOT + rel
        book = os.path.basename(path)
        doc = fitz.open(path)
        subs = subtopic_index(doc)
        cands = [c for c in chapters if c["subject"] == subj and c["class_level"] == cl]
        # UNIQUE(source_file, chunk_index) -- pdf_chunks_dedupe_idx. The legacy
        # corpus has one file per chapter, so that index silently assumes
        # source_file identifies a chapter. Here source_file is the whole book,
        # so the counter runs book-wide or chapter 2 collides with chapter 1.
        book_seq = 0
        print(f"=== {subj} {cl} -- {book} ({len(doc)} pages) ===")

        for span in chapter_spans(doc):
            best, score = match_chapter(span["title"] or "", span["num"], cands)
            if not best or score < MATCH_FLOOR:
                unmatched.append((subj, cl, span["num"], span["title"]))
                print(f"  !! UNMATCHED ch{span['num']}: {span['title']}")
                continue

            pages: List[Tuple[int, str]] = []
            for a, b in span["ranges"]:
                for pno in range(a, min(b, len(doc)) + 1):
                    pages.append((pno, doc[pno - 1].get_text()))

            rows = []
            for ch in chunk_pages(pages):
                st = subtopic_at(subs, ch["page_start"])
                head = f"[{subj.title()} Class {cl} | Chapter {span['num']}: {span['title']}"
                head = head + (f" | {st}]" if st else "]")
                rows.append(
                    {
                        "chapter_id": best["id"],
                        "subject": subj,
                        "class_level": cl,
                        "source_file": book,
                        # NOT NULL, and UNIQUE with source_file. Runs book-wide
                        # rather than per-chapter -- see book_seq above.
                        "chunk_index": book_seq + len(rows),
                        "page_start": ch["page_start"],
                        "page_end": ch["page_end"],
                        "content": f"{head}\n{ch['text']}",
                    }
                )

            book_seq += len(rows)
            toks = sum(len(tokenizer.encode(r["content"])) for r in rows)
            total_chunks += len(rows)
            total_tokens += toks
            total_chapters += 1
            pspan = f"p{min(p for p, _ in pages)}-{max(p for p, _ in pages)}"
            print(
                f"  ch{span['num']:<2} {(span['title'] or '')[:40]:42} -> "
                f"{best['name'][:24]:26} {len(rows):4} chunks  {pspan}"
            )

            if dry:
                continue

            # Idempotent re-run: drop any rows this book already wrote for this
            # chapter (a previous partial attempt), so the insert cannot collide
            # with its own leftovers. Legacy rows are NOT touched here -- they
            # are only removed after the new insert is verified below.
            sb.table("pdf_chunks").delete().eq("chapter_id", best["id"]).eq(
                "source_file", book
            ).execute()

            for i in range(0, len(rows), 128):
                batch = rows[i : i + 128]
                embs = oa.embeddings.create(
                    model="text-embedding-3-small",
                    input=[r["content"] for r in batch],
                ).data
                for r, e in zip(batch, embs):
                    r["embedding"] = e.embedding
                sb.table("pdf_chunks").insert(batch).execute()

            got = (
                sb.table("pdf_chunks")
                .select("id", count="exact")
                .eq("chapter_id", best["id"])
                .eq("source_file", book)
                .limit(1)
                .execute()
                .count
            )
            if got != len(rows):
                print(f"     ABORT: inserted {got}, expected {len(rows)} -- old rows kept")
                return 1
            sb.table("pdf_chunks").delete().eq("chapter_id", best["id"]).neq(
                "source_file", book
            ).execute()
            print(f"     inserted {got}, old rows removed")

    print(f"\nTOTAL  {total_chapters} chapters, {total_chunks} chunks, {total_tokens:,} tokens")
    print(f"embedding cost @ $0.02/1M: ${total_tokens / 1e6 * 0.02:.2f}")
    if unmatched:
        print(f"UNMATCHED: {unmatched}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
