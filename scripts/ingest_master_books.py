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

# Page furniture, read off the rendered pages rather than guessed. Every book
# repeats a running header block on a chapter-opening page and a footer block
# on every page:
#     Class 11 Biology - Ch. 1 Round 2 Addendum
#     Page 27 of 27
#     61                       <- bare folio
# and chapter openers add "Drona Ed Tech" / "CBSE Boards . CUET . NEET".
# Left in, this interleaves mid-list and attaches distractor notes to the wrong
# MCQ; it polluted 29.2% of chunks in the first ingest.
FURNITURE = [
    re.compile(r"^\s*Page\s+\d+\s+of\s+\d+\s*$", re.I),
    re.compile(r"^\s*\d{1,4}\s*$"),                       # bare folio
    re.compile(r"^\s*Class\s+\d+\s+\w+\s*[-—|]", re.I),  # running header/footer
    re.compile(r"^\s*Drona\s+Ed\s+Tech\s*$", re.I),
    re.compile(r"^\s*CBSE\s+Boards\b.*$", re.I),
]
# Pages that carry no teaching text at all. Figure plates are illustrator
# build-specs and label soup -- 589 chunks of the first ingest, 486 of them
# containing no Greek letter at all, i.e. formulas stripped to arithmetic
# nonsense. Contents pages are dot leaders.
FIGURE_PLATE = re.compile(r"CHAPTER\s+\d+\s*[\u00b7\u2022\-]\s*FIGURES", re.I)
DOT_LEADER = re.compile(r"\.{6,}\s*\d+")


def strip_furniture(page_text: str) -> str:
    """Drop running headers, footers and folios, line by line."""
    keep = [ln for ln in page_text.split("\n")
            if not any(rx.match(ln) for rx in FURNITURE)]
    return "\n".join(keep)


def is_non_teaching(page_text: str) -> bool:
    """True for figure-plate and contents pages, and for pages that are
    nothing but furniture once it is stripped (chapter title pages)."""
    if FIGURE_PLATE.search(page_text):
        return True
    if len(DOT_LEADER.findall(page_text)) >= 5:
        return True
    return len(strip_furniture(page_text).strip()) < 120

tokenizer = tiktoken.get_encoding("cl100k_base")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def sanitize(text: str) -> str:
    """Strip NULs and control characters Postgres text will not accept."""
    if not text:
        return ""
    text = text.replace("\x00", "")
    # Rejoin words broken across a line by hyphenation. 49.7% of first-ingest
    # chunks carried at least one, and biology -- the pilot subject -- was
    # 78.9%. It breaks reading AND lexical retrieval: nothing matches
    # "Echin-odermata".
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
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
    """Chunk (page_no, page_text) pairs, carrying each chunk's real page span.

    Two defects from the first ingest are fixed here.

    OVERLAP WAS DEAD CODE. `step = MAX_TOKENS - OVERLAP` was applied only
    inside the oversize-paragraph branch; the normal path reset `cur` to the
    new paragraph with no carryover, so the great majority of boundaries had
    ZERO overlap. That is the direct cause of the orphan question/answer
    pattern -- chunks opening on "Since (iii) is false... the answer is (c)"
    with no question anywhere in them. Now the tail of each chunk seeds the
    next one.

    TOKEN-SLICE DECODING MANUFACTURED MOJIBAKE. `tokenizer.decode(toks[i:j])`
    cuts multi-byte characters in half, and the mathematical-alphanumeric block
    (U+1D400+, four bytes each) is exactly what a maths book is full of. 795
    chunks carried U+FFFD, one of them OPENING on a replacement character where
    a pi should be. The oversize branch now slides over WORDS, so a character
    is never split.
    """
    units: List[Tuple[int, str]] = []
    for pno, text in pages:
        if is_non_teaching(text):
            continue
        for para in sanitize(strip_furniture(text)).split("\n\n"):
            p = sanitize(para)
            if p:
                units.append((pno, p))

    out: List[dict] = []
    cur: List[Tuple[int, str]] = []          # (page, paragraph) in the open chunk

    def text_of(u: List[Tuple[int, str]]) -> str:
        return "\n\n".join(t for _, t in u).strip()

    def tail_for_overlap(u: List[Tuple[int, str]]) -> List[Tuple[int, str]]:
        """The trailing SENTENCES worth up to OVERLAP tokens, as the next
        chunk's seed -- this is what keeps a question with its answer.

        Sentences, not whole paragraphs. The first version of this kept whole
        paragraphs within the budget and fired on only 4% of boundaries,
        because a paragraph in these books routinely exceeds 100 tokens on its
        own, so the loop broke immediately and returned nothing. Measured
        before believing it worked.

        A sentence boundary is still a clean cut -- the principle was never
        "paragraphs", it was "never hand the next chunk half a sentence"."""
        if not u:
            return []
        page = u[-1][0]
        sentences = re.findall(r"[^.!?\n]*[.!?]|\n?[^.!?\n]+$", "\n\n".join(t for _, t in u))
        keep: List[str] = []
        total = 0
        for sent in reversed(sentences):
            st = sent.strip()
            if not st:
                continue
            n = len(tokenizer.encode(st))
            if total + n > OVERLAP and keep:
                break
            keep.insert(0, st)
            total += n
            if total >= OVERLAP:
                break
        body = " ".join(keep).strip()
        return [(page, body)] if body else []

    def flush() -> None:
        nonlocal cur
        body = text_of(cur)
        if body:
            out.append({"text": body,
                        "page_start": min(p for p, _ in cur),
                        "page_end": max(p for p, _ in cur)})
        cur = tail_for_overlap(cur)

    for pno, p in units:
        prospective = text_of(cur + [(pno, p)])
        if len(tokenizer.encode(prospective)) <= MAX_TOKENS:
            cur.append((pno, p))
            continue

        flush()
        if len(tokenizer.encode(p)) > MAX_TOKENS:
            # One paragraph bigger than the window. Slide over WORDS, never
            # over token slices, so no multi-byte character is bisected.
            words, window, count = p.split(" "), [], 0
            for w in words:
                wn = len(tokenizer.encode(w + " "))
                if count + wn > MAX_TOKENS and window:
                    seg = sanitize(" ".join(window))
                    if len(seg) > 10:
                        out.append({"text": seg, "page_start": pno, "page_end": pno})
                    back = max(1, int(len(window) * OVERLAP / max(count, 1)))
                    window, count = window[-back:], sum(
                        len(tokenizer.encode(x + " ")) for x in window[-back:])
                window.append(w)
                count += wn
            cur = [(pno, sanitize(" ".join(window)))] if window else []
        else:
            cur.append((pno, p))

    if text_of(cur):
        out.append({"text": text_of(cur),
                    "page_start": min(p for p, _ in cur),
                    "page_end": max(p for p, _ in cur)})
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
