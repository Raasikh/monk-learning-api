#!/usr/bin/env python3
"""Deterministic raw-extraction pipeline for JEE Main / NEET question-paper PDFs.

DETERMINISTIC / NO-LLM BY DESIGN: every step below (harvest, probe, extract,
summary) is pure regex/format logic over PDF text layers. No LLM is called —
per AGENTS.md this is dev-time tooling where output is stored permanently, and
raw extraction must be reproducible and auditable; an LLM would make the raw
layer non-deterministic and could silently "repair" (i.e. fabricate) content.
This script does NOT write to the database, does NOT mark anything servable,
and does NOT fabricate answers or solutions (see EXTRACTION_QUALITY_SPEC.md:
this is the RAW layer only — defects are flagged, not fixed).

Subcommands:
  harvest   Build data/nta_raw/manifest.json from eSaral index pages plus the
            hardcoded official NTA 2026 paper list and official answer keys.
  probe     Download PDFs into the gitignored scratch/ cache (never into
            tracked data) and record sha256 / page_count / has_text_layer /
            has_question_ids / includes_solutions heuristics in the manifest.
  extract   Parse cached PDFs into per-paper raw JSON under
            data/nta_raw/papers/<paper_id>.json.
  summary   Write reports/nta_raw_extraction_summary.md.

PDFs are cached only under scratch/ (gitignored); they are never redistributed
into tracked repo data.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import html as html_mod
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "nta_raw"
PAPERS_DIR = DATA_DIR / "papers"
CACHE_DIR = ROOT / "scratch" / "nta_pdf_cache"
MANIFEST_PATH = DATA_DIR / "manifest.json"
REPORT_PATH = ROOT / "reports" / "nta_raw_extraction_summary.md"

# Browser UA: some mirrors (selfstudys) 403 plain python-requests.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/pdf,*/*",
}
TIMEOUT = 45
POLITE_DELAY_S = 1.0

ESARAL_INDEXES = [
    (2022, "https://www.esaral.com/jee/jee-main-2022-question-papers/"),
    (2023, "https://www.esaral.com/jee/jee-main-2023-question-papers/"),
    (2024, "https://www.esaral.com/jee/jee-mains-2024-question-papers/"),
    (2025, "https://www.esaral.com/jee/jee-main-2025-question-paper/"),
]

# eSaral NEET pages are much thinner than JEE; harvest what direct PDFs exist.
ESARAL_NEET_INDEXES = [
    (2022, "https://www.esaral.com/neet/neet-2022-question-paper/"),
    (2019, "https://www.esaral.com/neet/neet-2019-question-paper/"),
    (2023, "https://www.esaral.com/neet/neet-2023-question-paper/"),
]

# SelfStudys has older JEE/NEET papers and chapter-wise PYP books. The index
# pages carry some direct show-pdf links plus many book pages that each link a PDF.
SELFSTUDYS_INDEXES = [
    ("jee-main", "https://www.selfstudys.com/books/jee-previous-year-paper"),
    ("neet-ug", "https://www.selfstudys.com/books/neet-previous-year-paper"),
]

# Official NTA final answer keys (hardcoded per task brief). 2024 via Wayback.
OFFICIAL_KEYS = {
    (2022, 1): "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2022/07/2022070665.pdf",
    (2022, 2): "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2022/08/2022080753.pdf",
    (2023, 1): "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2023/02/2023020697.pdf",
    (2023, 2): "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2023/04/2023042948.pdf",
    (2024, 1): "https://web.archive.org/web/20240212072459/https://jeemain.nta.ac.in/images/Final_Answer_Key_P1_12022024.pdf",
    (2024, 2): "https://web.archive.org/web/20240423092125/https://jeemain.nta.ac.in/images/FINAL_ANSWER_KEY_JEE_MAIN_SESSION_2_22.04.2024.pdf",
    (2025, 1): "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2025/02/2025021053.pdf",
    (2025, 2): "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2025/04/2025041892.pdf",
    (2026, 1): "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2026/02/20260216459398513.pdf",
    (2026, 2): "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2026/04/20260420409057044.pdf",
}

# Official 2026 Session-2 B.Tech papers from the jeemain.nta.nic.in
# "Question Papers" menu. 8th Apr Shift 1 and Session-1 papers are not posted.
OFFICIAL_2026_PAPERS = [
    # 2nd Apr 2026, shifts 1-2
    "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2026/04/202604092096865379.pdf",
    "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2026/04/20260409481957146.pdf",
    # 4th Apr 2026, shifts 1-2
    "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2026/04/202604091916616339.pdf",
    "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2026/04/20260409432593766.pdf",
    # 5th Apr 2026, shifts 1-2
    "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2026/04/20260409828731207.pdf",
    "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2026/04/20260409829414602.pdf",
    # 6th Apr 2026, shifts 1-2
    "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2026/04/202604092007095665.pdf",
    "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2026/04/20260409725707538.pdf",
    # 8th Apr 2026, shift 2 only
    "https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2026/04/20260409932754345.pdf",
]

# Extra verified mirror samples from the task brief (seeded into harvest output
# so a small end-to-end run does not depend on index-page scraping alone).
SEED_MIRROR_PAPERS = [
    {
        "pdf_url": "https://www.esaral.com/media/uploads/2023/9/21/171018-26-07%20MORNING%20PHYSICS%202022.pdf",
        "source_page_url": "https://www.esaral.com/jee/jee-main-2022-question-papers/",
        "link_text": "26-07 MORNING PHYSICS 2022",
        "year_hint": 2022,
    },
    {
        "pdf_url": "https://www.selfstudys.com/sitepdfs/CbhxQ7PBM7OMRjqYw2CY",
        "source_page_url": "",
        "link_text": "JEE Main 24 June 2022 Shift 1",
        "year_hint": 2022,
    },
    {
        "pdf_url": "https://www.esaral.com/media/uploads/2024/4/10/124243-JEE-Main_Morning-Shift-1_08-04-2024_Student-Copy.pdf",
        "source_page_url": "https://www.esaral.com/jee/jee-mains-2024-question-papers/",
        "link_text": "JEE-Main Morning-Shift-1 08-04-2024 Student Copy",
        "year_hint": 2024,
    },
    {
        "pdf_url": "https://www.esaral.com/media/uploads/2025/1/23/12244-JEE-Main-2025-Question-Papers-With-Solutions-22-01-2025_Shift_1-PDF-Download.pdf",
        "source_page_url": "https://www.esaral.com/jee/jee-main-2025-question-paper/",
        "link_text": "JEE Main 2025 Question Papers With Solutions 22-01-2025 Shift 1",
        "year_hint": 2025,
    },
    {
        "pdf_url": "https://cdn.targetpublications.org/admin/downloads/X9lRGMz1A39NeOfY5rpeT85oVn6RSTJJHmkmO5Gk.pdf",
        "source_page_url": "",
        "link_text": "JEE Main 28 January 2025 Shift 1 scanned",
        "year_hint": 2025,
    },
]

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def load_manifest() -> list[dict]:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return []


def save_manifest(entries: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].strip("-") or "paper"


def infer_metadata(pdf_url: str, link_text: str, year_hint: Optional[int]) -> dict:
    """Deterministic best-effort inference from link text / URL only.

    Anything uncertain is left None and explained in `notes` — never guessed.
    """
    blob = unquote(f"{link_text} {pdf_url}").lower()
    blob_decoded = blob.replace("+", " ").replace("_", " ").replace("-", " ")
    blob_decoded = re.sub(r"\s+", " ", blob_decoded)
    notes = []

    year = year_hint
    m = re.search(r"\b(20\d{2})\b", blob_decoded)
    if year is None and m:
        year = int(m.group(1))
    if year is None:
        notes.append("year not inferable from link text/URL")

    exam_date = None
    m = re.search(r"\b(\d{1,2})\s(\d{2})\s(\d{4})\b", blob_decoded)
    if m and year and int(m.group(3)) == year:
        exam_date = f"{m.group(3)}-{m.group(2)}-{int(m.group(1)):02d}"
    else:
        m = re.search(r"\b(\d{1,2})\s(\d{2})\b", blob_decoded)
        if m and year:
            day, mon = int(m.group(1)), int(m.group(2))
            if 1 <= mon <= 12 and 1 <= day <= 31:
                exam_date = f"{year}-{mon:02d}-{day:02d}"
    if exam_date is None:
        # e.g. "22 january 2025" / "08 apr 2024"
        m = re.search(
            r"\b(\d{1,2})\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
            r"[a-z]*\s*(\d{4})?\b",
            blob_decoded,
        )
        if m and (year or m.group(3)):
            y = year or int(m.group(3))
            exam_date = f"{y}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    if exam_date is None:
        # e.g. "january 27 2024" / "january 27" (eSaral title-case URLs)
        m = re.search(
            r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
            r"\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})?\b",
            blob_decoded,
        )
        if m and (year or m.group(3)):
            y = year or int(m.group(3))
            day = int(m.group(2))
            if 1 <= day <= 31:
                exam_date = f"{y}-{MONTHS[m.group(1)]:02d}-{day:02d}"
    if exam_date is None:
        notes.append("exam_date not inferable from link text/URL")

    session = None
    if year:
        if re.search(r"\b(jan|january|feb|february)\b", blob_decoded) or (
            exam_date and exam_date[5:7] in ("01", "02")
        ):
            session = 1
        elif re.search(r"\b(apr|april)\b", blob_decoded) or (
            exam_date and exam_date[5:7] == "04"
        ):
            session = 2
        elif exam_date and exam_date[5:7] in ("06", "07"):
            session = 2  # 2022 session 2 ran in June/July
        if session is None:
            notes.append("session inferred only if month is known; left null")

    shift = None
    if re.search(r"\b(morning|shift\s*1|shift1)\b", blob_decoded):
        shift = 1
    elif re.search(r"\b(evening|afternoon|shift\s*2|shift2)\b", blob_decoded):
        shift = 2
    if shift is None:
        notes.append("shift not inferable from link text/URL")

    if re.search(r"\b(chapter[\s-]?wise|question bank|pyq)\b", blob_decoded):
        paper_type = "chapterwise_question_bank"
    else:
        paper_type = (
            "question_paper_with_solutions"
            if re.search(r"\b(solution|solved|answer)\b", blob_decoded)
            else "question_paper"
        )

    subject = None
    if re.search(r"\bmath(ematics|s)?\b", blob_decoded):
        subject = "Mathematics"
    elif re.search(r"\bphysics\b", blob_decoded):
        subject = "Physics"
    elif re.search(r"\bchemistry\b", blob_decoded):
        subject = "Chemistry"
    elif re.search(r"\bbiology\b|\bbotany\b|\bzoology\b", blob_decoded):
        subject = "Biology"

    language = "Hindi" if re.search(r"\bhindi\b", blob_decoded) else "English"
    exam = "neet-ug" if "neet" in blob_decoded else "jee-main"

    return {
        "exam": exam,
        "year": year,
        "session": session,
        "exam_date": exam_date,
        "shift": shift,
        "paper_type": paper_type,
        "subject": subject,
        "language": language,
        "notes": "; ".join(notes),
    }


def build_tags(meta: dict, text: str = "") -> list[str]:
    """Paper-level tags required by consumers: exam/audience classification.

    JEE Main and NEET UG are entrance exams spanning the Class 11 + Class 12
    syllabus, so they carry both class tags plus the exam tag. Class-specific
    papers are tagged only when the source text says so explicitly.
    """
    blob = " ".join(
        str(v) for v in (meta.get("exam"), meta.get("paper_type"), text)
        if v
    ).lower()
    if "neet" in blob:
        exam_tag = "neet-ug"
    elif "jee" in blob or meta.get("exam") == "jee-main":
        exam_tag = "jee-main"
    elif re.search(r"\bclass\s*11\b|\bxi\b", blob):
        exam_tag = "class-11"
    elif re.search(r"\bclass\s*12\b|\bxii\b", blob):
        exam_tag = "class-12"
    else:
        exam_tag = meta.get("exam") or "other"

    tags = [exam_tag]
    if exam_tag in {"jee-main", "neet-ug"}:
        tags += ["class-11", "class-12", "entrance-exam"]
    elif exam_tag in {"class-11", "class-12"}:
        tags.append("board-level")
    return list(dict.fromkeys(tags))


def make_paper_id(meta: dict, pdf_url: str, link_text: str) -> str:
    parts = [meta.get("exam") or "exam"]
    if meta.get("year"):
        parts.append(str(meta["year"]))
    if meta.get("session"):
        parts.append(f"s{meta['session']}")
    if meta.get("subject"):
        parts.append(slugify(meta["subject"], max_len=20))
    if meta.get("exam_date"):
        parts.append(meta["exam_date"])
    if meta.get("shift"):
        parts.append(f"shift-{meta['shift']}")
    base = "-".join(parts)
    if meta.get("paper_type") == "chapterwise_question_bank":
        base += "-" + slugify(link_text or Path(pdf_url.split("?")[0]).stem, max_len=80)
    elif not meta.get("exam_date"):
        base += "-" + slugify(Path(pdf_url.split("?")[0]).stem or link_text)
    return base


# ---------------------------------------------------------------------------
# harvest
# ---------------------------------------------------------------------------

ESARAL_PDF_HREF_RE = re.compile(
    r'href=["\']((?:https?://www\.esaral\.com)?/media/uploads/[^"\']+?\.pdf)["\']',
    re.IGNORECASE,
)


def harvest_esaral_index(year: int, index_url: str) -> list[dict]:
    resp = requests.get(index_url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    html = resp.text
    entries = []
    seen = set()
    for m in ESARAL_PDF_HREF_RE.finditer(html):
        href = m.group(1)
        pdf_url = (
            href if href.startswith("http") else f"https://www.esaral.com{href}"
        )
        if pdf_url in seen:
            continue
        seen.add(pdf_url)
        # Grab nearby anchor text for metadata inference (deterministic).
        tail = html[m.end(): m.end() + 300]
        text_m = re.search(r">([^<>]{3,200})<", tail)
        link_text = text_m.group(1).strip() if text_m else Path(pdf_url).stem
        entries.append((pdf_url, index_url, link_text))
    return entries


MATHONGO_SEED = (
    "https://www.mathongo.com/iit-jee/"
    "jee-main-maths-chapter-wise-questions-with-solutions-april-2025"
)
MATHONGO_PAGE_RE = re.compile(
    r'href=["\'](https://www\.mathongo\.com/iit-jee/[^"\']*'
    r'(?:chapter-wise-questions-with-solutions|'
    r'nta-abhyas-question-paper-pdf-download-chapterwise-for-jee-main)'
    r'[^"\']*)["\']',
    re.IGNORECASE,
)
MATHONGO_SHORT_RE = re.compile(
    r'href=["\'](https://(?:links\.mathongo\.com|bit\.ly)/[^"\']+)["\']',
    re.IGNORECASE,
)
DRIVE_ID_RE = re.compile(r"/file/d/([^/]+)|[?&]id=([^&]+)")


def drive_file_id(url: str) -> Optional[str]:
    m = DRIVE_ID_RE.search(url)
    file_id = m.group(1) or m.group(2) if m else None
    # App-store links also carry ?id=com.package.name; those are not PDFs.
    if not file_id or "." in file_id or len(file_id) < 20:
        return None
    return file_id


def mathongo_direct_pdf(short_url: str) -> Optional[str]:
    """Resolve MathonGo's short link to a direct PDF URL (usually Drive)."""
    resp = requests.get(short_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    resp.raise_for_status()
    final_url = resp.url
    file_id = drive_file_id(final_url)
    if file_id:
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    if final_url.lower().endswith(".pdf"):
        return final_url
    if "pdf" in (resp.headers.get("Content-Type") or "").lower():
        return short_url
    return None


def harvest_mathongo_chapterwise() -> list[tuple[str, str, str, Optional[int]]]:
    """Harvest chapter-wise JEE question-bank PDFs linked from MathonGo.

    The seed page's sidebar lists the year/session/subject variants. Newer
    pages expose one `links.mathongo.com` whole-book URL; older pages expose
    per-chapter `bit.ly` links. Per-chapter short links are stored unresolved
    so harvest stays cheap; `download_pdf` follows redirects at probe time.
    """
    resp = requests.get(MATHONGO_SEED, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    pages = []
    for m in MATHONGO_PAGE_RE.finditer(resp.text):
        page = m.group(1).split("#")[0]
        if page not in pages:
            pages.append(page)
    rows = []
    for page in pages:
        try:
            html = requests.get(page, headers=HEADERS, timeout=TIMEOUT).text
            slug = Path(page).name
            ym = re.search(r"(20\d{2})", slug)
            year = int(ym.group(1)) if ym else None
            seen_short = set()
            for sm in MATHONGO_SHORT_RE.finditer(html):
                short = sm.group(1)
                if short in seen_short:
                    continue
                seen_short.add(short)
                tail = html[sm.end(): sm.end() + 220]
                text_m = re.search(r">([^<>]{3,160})<", tail)
                label = text_m.group(1).strip() if text_m else ""
                if "links.mathongo.com" in short:
                    pdf_url = mathongo_direct_pdf(short)
                    if pdf_url:
                        rows.append((pdf_url, page, slug, year))
                else:
                    # bit.ly per-chapter links: keep the chapter name in metadata.
                    # App-store/marketing short links are present on every page;
                    # only links whose anchor says PDF are question banks.
                    if "pdf" not in label.lower():
                        continue
                    link_text = f"{slug} :: {label}" if label else slug
                    rows.append((short, page, link_text, year))
            time.sleep(POLITE_DELAY_S)
        except Exception as exc:
            print(f"[harvest] WARN: mathongo {page} failed: {exc}", file=sys.stderr)
            continue
    return rows


SELFSTUDYS_PDF_RE = re.compile(
    r'(?:href|source)=["\']((?:https://www\.selfstudys\.com)?/(?:show-pdf/[^"\']+?\.pdf|sitepdfs/[A-Za-z0-9]+))["\']',
    re.IGNORECASE,
)
SELFSTUDYS_BOOK_RE = re.compile(
    r'href=["\']((?:https://www\.selfstudys\.com)?/books/(?:jee|neet)-previous-year-paper/[^"\']+)["\']',
    re.IGNORECASE,
)


def selfstudys_pdf_links(page_url: str) -> list[tuple[str, str]]:
    resp = requests.get(page_url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    html = resp.text
    out = []
    seen = set()
    for m in SELFSTUDYS_PDF_RE.finditer(html):
        href = m.group(1)
        pdf_url = href if href.startswith("http") else f"https://www.selfstudys.com{href}"
        if "/show-pdf/" in pdf_url:
            # show-pdf/<id>.pdf is an HTML viewer; the payload is sitepdfs/<id>.
            pdf_url = f"https://www.selfstudys.com/sitepdfs/{Path(pdf_url).stem}"
        if pdf_url in seen:
            continue
        seen.add(pdf_url)
        tail = html[m.end(): m.end() + 260]
        text_m = re.search(r">([^<>]{3,220})<", tail)
        label = text_m.group(1).strip() if text_m else Path(pdf_url).stem
        out.append((pdf_url, html_mod.unescape(label)))
    return out


def harvest_selfstudys(max_book_pages: Optional[int] = None) -> list[tuple[str, str, str, None]]:
    rows = []
    for exam, index_url in SELFSTUDYS_INDEXES:
        try:
            direct = selfstudys_pdf_links(index_url)
        except Exception as exc:
            print(f"[harvest] WARN: selfstudys {index_url} failed: {exc}", file=sys.stderr)
            continue
        print(f"[harvest] {index_url}: {len(direct)} direct pdf links")
        for pdf_url, label in direct:
            rows.append((pdf_url, index_url, f"{exam} {label}", None))
        try:
            resp = requests.get(index_url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            book_pages = []
            for m in SELFSTUDYS_BOOK_RE.finditer(resp.text):
                href = m.group(1)
                page = href if href.startswith("http") else f"https://www.selfstudys.com{href}"
                page = page.split("#")[0]
                if page != index_url and page not in book_pages:
                    book_pages.append(page)
        except Exception:
            book_pages = []
        if max_book_pages is not None:
            book_pages = book_pages[:max_book_pages]
        print(f"[harvest] {index_url}: {len(book_pages)} book pages")

        def book_rows(page):
            try:
                out = []
                for pdf_url, label in selfstudys_pdf_links(page):
                    slug = page.rstrip("/").split("/")[-2]
                    link_text = f"{exam} {label}".strip() or f"{exam} {slug}"
                    if label:
                        link_text = f"{link_text} {slug}"
                    out.append((pdf_url, page, link_text, None))
                return out
            except Exception as exc:
                print(f"[harvest] WARN: selfstudys book {page} failed: {exc}", file=sys.stderr)
                return []

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(book_rows, page): page for page in book_pages}
            for fut in as_completed(futures):
                rows.extend(fut.result())
    # Dedupe by URL while preserving first label.
    seen = set()
    out = []
    for row in rows:
        if row[0] in seen:
            continue
        seen.add(row[0])
        out.append(row)
    return out


def cmd_harvest(args: argparse.Namespace) -> None:
    manifest = []
    seen_urls = set()
    old_manifest = load_manifest()
    old_probe_by_url = {e.get("pdf_url"): e.get("probe") for e in old_manifest if e.get("probe")}

    def add(pdf_url, source_tier, source_site, source_page_url, link_text, year_hint):
        if pdf_url in seen_urls:
            return
        seen_urls.add(pdf_url)
        meta = infer_metadata(pdf_url, f"{link_text} {source_page_url}", year_hint)
        tags = build_tags(meta, f"{link_text} {pdf_url}")
        key_url = OFFICIAL_KEYS.get((meta.get("year"), meta.get("session")))
        entry = {
            "paper_id": make_paper_id(meta, pdf_url, link_text),
            **meta,
            "exam_tag": tags[0],
            "tags": tags,
            "source_tier": source_tier,
            "source_site": source_site,
            "source_page_url": source_page_url or pdf_url,
            "pdf_url": pdf_url,
            "official_key_url": key_url,
            "key_join_strategy": (
                "question_id"
                if source_tier == "official"
                else "sequence_within_section"
            ),
            "key_join_notes": (
                ""
                if source_tier == "official"
                else "mirror PDFs carry no NTA question IDs; joining to the "
                "official key by question order within subject/section is "
                "approximate and must be re-verified per paper"
            ),
            "probe": None,
        }
        if old_probe_by_url.get(pdf_url):
            entry["probe"] = old_probe_by_url[pdf_url]
        if key_url is None:
            entry["notes"] = (entry["notes"] + "; " if entry["notes"] else "") + \
                "no official key URL known for this year/session"
        manifest.append(entry)

    # Official NTA 2026 papers (seeded list; uploads path month 04 => session 2).
    for url in OFFICIAL_2026_PAPERS:
        meta_note = "official NTA 2026 paper; exam_date/shift not in URL"
        add(url, "official", "cdnbbsr.s3waas.gov.in", "", Path(url).stem, 2026)
        manifest[-1]["session"] = 2
        manifest[-1]["paper_id"] = make_paper_id(manifest[-1], url, Path(url).stem)
        manifest[-1]["official_key_url"] = OFFICIAL_KEYS[(2026, 2)]
        manifest[-1]["notes"] = meta_note

    # eSaral index harvest.
    if not args.skip_esaral:
        for year, index_url in ESARAL_INDEXES:
            try:
                rows = harvest_esaral_index(year, index_url)
            except Exception as exc:  # network failure must not kill harvest
                print(f"[harvest] WARN: {index_url} failed: {exc}", file=sys.stderr)
                continue
            print(f"[harvest] {index_url}: {len(rows)} pdf links")
            for pdf_url, page_url, link_text in rows:
                add(pdf_url, "mirror", "www.esaral.com", page_url, link_text, year)
            time.sleep(POLITE_DELAY_S)

    # eSaral NEET harvest (direct PDFs only; some year pages are image-only links).
    if not args.skip_esaral:
        for year, index_url in ESARAL_NEET_INDEXES:
            try:
                rows = harvest_esaral_index(year, index_url)
            except Exception as exc:
                print(f"[harvest] WARN: {index_url} failed: {exc}", file=sys.stderr)
                continue
            print(f"[harvest] {index_url}: {len(rows)} pdf links")
            for pdf_url, page_url, link_text in rows:
                add(pdf_url, "mirror", "www.esaral.com", page_url, link_text, year)
            time.sleep(POLITE_DELAY_S)

    # MathonGo chapter-wise / NTA Abhyas question banks (bigger diagram yield
    # than shift papers; these are public question compilations, not live papers).
    if not args.skip_question_banks:
        try:
            rows = harvest_mathongo_chapterwise()
        except Exception as exc:
            print(f"[harvest] WARN: mathongo chapterwise failed: {exc}", file=sys.stderr)
            rows = []
        print(f"[harvest] mathongo chapterwise: {len(rows)} pdf links")
        for pdf_url, page_url, link_text, year in rows:
            add(pdf_url, "question_bank", "www.mathongo.com", page_url, link_text, year)

    # SelfStudys older year-wise and chapter-wise papers (runs after MathonGo;
    # download_pdf's %PDF magic check rejects marketing pages).
    if not args.skip_selfstudys:
        try:
            rows = harvest_selfstudys(args.selfstudys_max_pages)
        except Exception as exc:
            print(f"[harvest] WARN: selfstudys failed: {exc}", file=sys.stderr)
            rows = []
        print(f"[harvest] selfstudys: {len(rows)} pdf links")
        for pdf_url, page_url, link_text, year in rows:
            add(pdf_url, "mirror", "www.selfstudys.com", page_url, link_text, year)

    # Extra verified seed samples from the task brief.
    for seed in SEED_MIRROR_PAPERS:
        site = re.sub(r"^https?://(www\.)?", "", seed["pdf_url"]).split("/")[0]
        add(seed["pdf_url"], "mirror", site, seed["source_page_url"],
            seed["link_text"], seed["year_hint"])

    # Ensure unique paper_ids (dedupe by suffixing).
    seen_ids = {}
    for e in manifest:
        pid = e["paper_id"]
        if pid in seen_ids:
            seen_ids[pid] += 1
            e["paper_id"] = f"{pid}-{seen_ids[pid]}"
        else:
            seen_ids[pid] = 1

    save_manifest(manifest)
    print(f"[harvest] wrote {len(manifest)} entries to {MANIFEST_PATH}")


def cmd_harvest_selfstudys(args: argparse.Namespace) -> None:
    """Refresh only SelfStudys entries in the existing manifest."""
    manifest = [e for e in load_manifest() if "selfstudys" not in e.get("source_site", "")]
    seen_urls = {e.get("pdf_url") for e in manifest}
    rows = harvest_selfstudys(args.selfstudys_max_pages)
    print(f"[harvest-selfstudys] {len(rows)} pdf links")
    added = 0
    for pdf_url, page_url, link_text, year in rows:
        if pdf_url in seen_urls:
            continue
        seen_urls.add(pdf_url)
        meta = infer_metadata(pdf_url, f"{link_text} {page_url}", year)
        tags = build_tags(meta, f"{link_text} {pdf_url}")
        manifest.append({
            "paper_id": make_paper_id(meta, pdf_url, link_text),
            **meta,
            "exam_tag": tags[0],
            "tags": tags,
            "source_tier": "mirror",
            "source_site": "www.selfstudys.com",
            "source_page_url": page_url or pdf_url,
            "pdf_url": pdf_url,
            "official_key_url": OFFICIAL_KEYS.get((meta.get("year"), meta.get("session"))),
            "key_join_strategy": "sequence_within_section",
            "key_join_notes": "mirror PDFs carry no NTA question IDs; official-key join is approximate",
            "probe": None,
        })
        added += 1
    seen_ids = {}
    for e in manifest:
        pid = e["paper_id"]
        if pid in seen_ids:
            seen_ids[pid] += 1
            e["paper_id"] = f"{pid}-{seen_ids[pid]}"
        else:
            seen_ids[pid] = 1
    save_manifest(manifest)
    print(f"[harvest-selfstudys] added {added}; wrote {len(manifest)} entries")


NEET_ARCHIVE_URL = "https://neet.nta.nic.in/archive/"
NEET_ARCHIVE_PDF_RE = re.compile(r'href=["\']([^"\']+?\.pdf)["\']', re.IGNORECASE)


def harvest_neet_official() -> list[tuple[str, str, str, int]]:
    resp = requests.get(NEET_ARCHIVE_URL, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    html = resp.text
    rows = []
    seen = set()
    for m in NEET_ARCHIVE_PDF_RE.finditer(html):
        href = m.group(1)
        pdf_url = href if href.startswith("http") else f"https://neet.nta.nic.in{href}"
        tail = html[m.end(): m.end() + 240]
        text_m = re.search(r">([^<>]{3,220})<", tail)
        label = html_mod.unescape(text_m.group(1).strip()) if text_m else Path(pdf_url).stem
        low = label.lower()
        if re.search(r"answer|key|omr|result|score|bulletin|syllabus|faq|information|notice|public", low):
            continue
        if not ("question paper" in low or "booklet" in low or re.search(r"\b[efgh][1-6]\b", low)):
            continue
        if pdf_url in seen:
            continue
        seen.add(pdf_url)
        rows.append((pdf_url, NEET_ARCHIVE_URL, f"neet-ug {label}", 2020))
    return rows


def cmd_harvest_neet_official(args: argparse.Namespace) -> None:
    """Append official NEET archive question papers to the existing manifest."""
    manifest = load_manifest()
    seen_urls = {e.get("pdf_url") for e in manifest}
    rows = harvest_neet_official()
    print(f"[harvest-neet-official] {len(rows)} pdf links")
    added = 0
    for pdf_url, page_url, link_text, year in rows:
        if pdf_url in seen_urls:
            continue
        seen_urls.add(pdf_url)
        meta = infer_metadata(pdf_url, f"{link_text} {page_url}", year)
        meta["exam"] = "neet-ug"
        tags = build_tags(meta, f"{link_text} {pdf_url}")
        manifest.append({
            "paper_id": make_paper_id(meta, pdf_url, link_text),
            **meta,
            "exam_tag": "neet-ug",
            "tags": tags,
            "source_tier": "official",
            "source_site": "neet.nta.nic.in",
            "source_page_url": page_url,
            "pdf_url": pdf_url,
            "official_key_url": None,
            "key_join_strategy": "booklet_question_number",
            "key_join_notes": "NEET official keys join by booklet code + question number, not NTA question IDs",
            "probe": None,
        })
        added += 1
    seen_ids = {}
    for e in manifest:
        pid = e["paper_id"]
        if pid in seen_ids:
            seen_ids[pid] += 1
            e["paper_id"] = f"{pid}-{seen_ids[pid]}"
        else:
            seen_ids[pid] = 1
    save_manifest(manifest)
    print(f"[harvest-neet-official] added {added}; wrote {len(manifest)} entries")


# ---------------------------------------------------------------------------
# JEE Advanced official papers (jeeadv.ac.in + Wayback snapshots)
# ---------------------------------------------------------------------------

# (year, paper_no, paper_download_url, key_download_url, source_page_url)
# Wayback URLs use the <timestamp>id_ form to fetch the raw PDF bytes.
JEE_ADVANCED_OFFICIAL = [
    (2022, 1,
     "https://web.archive.org/web/20220829222110id_/https://jeeadv.ac.in/documents/jeeadv-2022-paper1.pdf",
     "https://web.archive.org/web/20220911041758id_/https://jeeadv.ac.in/documents/jeeadv-2022-final-answer-keys.pdf",
     "https://jeeadv.ac.in/"),
    (2022, 2,
     "https://web.archive.org/web/20220829222112id_/https://jeeadv.ac.in/documents/jeeadv-2022-paper2.pdf",
     "https://web.archive.org/web/20220911041758id_/https://jeeadv.ac.in/documents/jeeadv-2022-final-answer-keys.pdf",
     "https://jeeadv.ac.in/"),
    (2023, 1,
     "https://web.archive.org/web/20230605121952id_/https://jeeadv.ac.in/documents/JEEAdv2023_Paper1.pdf",
     "https://web.archive.org/web/20230618114607id_/https://jeeadv.ac.in/documents/Paper1_Final_Answer_Keys.pdf",
     "https://jeeadv.ac.in/"),
    (2023, 2,
     "https://web.archive.org/web/20230605122213id_/https://jeeadv.ac.in/documents/JEEAdv2023_Paper2.pdf",
     "https://web.archive.org/web/20230618114609id_/https://jeeadv.ac.in/documents/Paper2_Final_Answer_Keys.pdf",
     "https://jeeadv.ac.in/"),
    (2024, 1,
     "https://web.archive.org/web/20240527012201id_/https://www.jeeadv.ac.in/documents/JEEAdv2024_Paper1_English.pdf",
     "https://web.archive.org/web/20240609043803id_/https://jeeadv.ac.in/documents/Paper1_English_2024_With_Final_Keys.pdf",
     "https://jeeadv.ac.in/"),
    (2024, 2,
     "https://web.archive.org/web/20240527012214id_/https://www.jeeadv.ac.in/documents/JEEAdv2024_Paper2_English.pdf",
     "https://web.archive.org/web/20240609164114id_/https://jeeadv.ac.in/documents/Paper2_English_2024_With_Final_Keys.pdf",
     "https://jeeadv.ac.in/"),
    (2025, 1,
     "https://web.archive.org/web/20250518172502id_/https://jeeadv.ac.in/documents/p1_english.pdf",
     "https://web.archive.org/web/20250602022251id_/https://jeeadv.ac.in/documents/p1_solutions_final.pdf",
     "https://jeeadv.ac.in/"),
    (2025, 2,
     "https://web.archive.org/web/20250518172501id_/https://jeeadv.ac.in/documents/p2_english.pdf",
     "https://web.archive.org/web/20250602022251id_/https://jeeadv.ac.in/documents/p2_solutions_final.pdf",
     "https://jeeadv.ac.in/"),
    (2026, 1,
     "https://jeeadv.ac.in/documents/p1_english.pdf",
     "https://jeeadv.ac.in/documents/p1_solutions_final.pdf",
     "https://jeeadv.ac.in/"),
    (2026, 2,
     "https://jeeadv.ac.in/documents/p2_english.pdf",
     "https://jeeadv.ac.in/documents/p2_solutions_final.pdf",
     "https://jeeadv.ac.in/"),
]


def cmd_harvest_jee_advanced(args: argparse.Namespace) -> None:
    """Append official JEE Advanced papers (2022-2026) to the manifest.

    Fixed URL table — jeeadv.ac.in only hosts the current year, so older
    papers resolve through Wayback snapshots of the same official paths.
    """
    manifest = load_manifest()
    seen_urls = {e.get("pdf_url") for e in manifest}
    existing_ids = {e["paper_id"] for e in manifest}
    added = 0
    for year, paper_no, pdf_url, key_url, page_url in JEE_ADVANCED_OFFICIAL:
        if pdf_url in seen_urls:
            continue
        pid = f"jee-advanced-{year}-paper-{paper_no}"
        if pid in existing_ids:
            continue
        manifest.append({
            "paper_id": pid,
            "exam": "jee-advanced",
            "year": year,
            "session": None,
            "exam_date": None,
            "shift": None,
            "paper_type": "question_paper",
            "subject": None,
            "language": "English",
            "notes": "official JEE Advanced paper (organizing IIT site / Wayback snapshot)",
            "exam_tag": "jee-advanced",
            "tags": ["jee-advanced", "class-11", "class-12", "entrance-exam"],
            "source_tier": "official",
            "source_site": "jeeadv.ac.in",
            "source_page_url": page_url,
            "pdf_url": pdf_url,
            "official_key_url": key_url,
            "key_join_strategy": "jee_advanced_key_pdf",
            "key_join_notes": "JEE Advanced final keys are per-paper PDFs, not NTA Question-ID tables",
            "probe": None,
        })
        added += 1
    save_manifest(manifest)
    print(f"[harvest-jee-advanced] added {added}; wrote {len(manifest)} entries")


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------

def resolve_download_url(pdf_url: str) -> str:
    """Resolve short links / Google Drive view URLs to a direct download URL."""
    if not re.search(r"(bit\.ly|links\.mathongo\.com|drive\.google\.com)", pdf_url):
        return pdf_url
    file_id = drive_file_id(pdf_url)
    if file_id and "uc?export=download" not in pdf_url:
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    try:
        with requests.get(pdf_url, headers=HEADERS, timeout=TIMEOUT, stream=True,
                          allow_redirects=True) as r:
            final_url = r.url
        file_id = drive_file_id(final_url)
        if file_id:
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        return final_url
    except requests.RequestException:
        return pdf_url


def _stream_download(pdf_url: str, dest: Path) -> str:
    with requests.get(pdf_url, headers=HEADERS, timeout=TIMEOUT, stream=True) as r:
        r.raise_for_status()
        ctype = r.headers.get("Content-Type", "")
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
    return ctype


def download_pdf(pdf_url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    resolved = resolve_download_url(pdf_url)
    try:
        ctype = _stream_download(resolved, dest)
    except requests.exceptions.HTTPError:
        # Some Drive files need the confirm token form; retry once before
        # recording the source as broken.
        file_id = drive_file_id(resolved) or drive_file_id(pdf_url)
        if not file_id:
            raise
        alt = f"https://drive.google.com/uc?export=download&confirm=t&id={file_id}"
        ctype = _stream_download(alt, dest)
    if dest.stat().st_size < 1024:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"suspiciously small download ({ctype})")
    with open(dest, "rb") as f:
        magic = f.read(5)
    if magic != b"%PDF-":
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"download is not a PDF ({ctype}, magic={magic!r})")


SOLUTIONS_HEADING_RE = re.compile(
    r"(?im)^\s*(solutions?|answer\s*key|hints?\s*(?:&|and)\s*solutions?|answers)"
    r"\s*(?:section)?\s*[:.\-]?\s*$"
)
ANSWER_MARKER_RE = re.compile(r"(?i)\bans(?:wer)?\s*[.:\)]")


def probe_pdf(path: Path) -> dict:
    import fitz  # PyMuPDF — dev-only dependency (not in requirements.txt)

    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with open(path, "rb") as f:
        if f.read(5) != b"%PDF-":
            raise RuntimeError("cached file is not a PDF")
    doc = fitz.open(path)
    page_texts = [page.get_text() for page in doc]
    page_count = doc.page_count
    doc.close()

    full = "\n".join(page_texts)
    text_chars = sum(len(t.strip()) for t in page_texts)
    has_text = text_chars > 200 * max(1, page_count // 2)
    has_qids = bool(re.search(r"Question\s*Id\s*:|ItemCode", full))
    n_headings = len(SOLUTIONS_HEADING_RE.findall(full))
    n_ans_markers = len(ANSWER_MARKER_RE.findall(full))
    includes_solutions = n_headings > 0 or n_ans_markers >= 5

    return {
        "sha256": sha,
        "page_count": page_count,
        "text_chars": text_chars,
        "has_text_layer": has_text,
        "has_question_ids": has_qids,
        "includes_solutions": includes_solutions,
        "solutions_heading_hits": n_headings,
        "answer_marker_hits": n_ans_markers,
        "cache_path": str(path.relative_to(ROOT)),
    }


def _select_entries(manifest: list[dict], args: argparse.Namespace) -> list[dict]:
    entries = manifest
    if args.only:
        wanted = set(args.only)
        entries = [e for e in entries if e["paper_id"] in wanted
                   or any(w in e["paper_id"] for w in wanted)
                   or any(w in e["pdf_url"] for w in wanted)]
    if args.limit:
        entries = entries[: args.limit]
    return entries


def cmd_probe(args: argparse.Namespace) -> None:
    manifest = load_manifest()
    by_id = {e["paper_id"]: e for e in manifest}
    entries = _select_entries(manifest, args)

    def work(entry: dict) -> tuple[str, dict]:
        pid = entry["paper_id"]
        cache_path = CACHE_DIR / f"{pid}.pdf"
        try:
            if not cache_path.exists() or args.redownload:
                download_pdf(entry["pdf_url"], cache_path)
            return pid, probe_pdf(cache_path)
        except Exception as exc:
            return pid, {"error": str(exc)}

    workers = max(1, getattr(args, "workers", 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, entry): entry["paper_id"] for entry in entries}
        for fut in as_completed(futures):
            pid = futures[fut]
            try:
                pid, probe = fut.result()
            except Exception as exc:
                probe = {"error": str(exc)}
            by_id[pid]["probe"] = probe
            save_manifest(manifest)  # persist after every PDF so long runs are resumable
            if probe.get("error"):
                print(f"[probe] {pid}: ERROR {probe['error']}", file=sys.stderr)
            else:
                print(
                    f"[probe] {pid}: pages={probe['page_count']} "
                    f"text={probe['has_text_layer']} "
                    f"qids={probe['has_question_ids']} "
                    f"solutions={probe['includes_solutions']}"
                )


# ---------------------------------------------------------------------------
# extract — format detection + parsers (pure functions, unit-testable)
# ---------------------------------------------------------------------------

FMT_2026 = "nta_2026"
FMT_2022 = "nta_2022"
FMT_GENERIC = "generic_mirror"

HDR2026_RE = re.compile(
    r"Question\s*Number\s*:\s*(\d+)\s*"
    r"Question\s*Id\s*:\s*(\d+)\s*"
    r"Question\s*Type\s*:\s*([A-Za-z]+)"
)
HDR2022_Q_RE = re.compile(r"(?m)^\s*Q\s*:\s*(\d+)\s*$")
ITEMCODE_RE = re.compile(r"ItemCode\s*:?\s*(\d+)")
TOPIC_RE = re.compile(r"Topic\s*Name\s*:?\s*([^\n]+)")

# 2026 official papers: section headings carry the subject ("Mathematics
# Section A"), and the paper header carries date/shift
# ("Question Paper Name : B Tech 2nd Apr 2026 Shift 1").
SECTION_HEADING_RE = re.compile(
    r"(?m)^\s*(Mathematics|Physics|Chemistry|Botany|Zoology|Biology)"
    r"\s+Section\s+([AB])\s*$"
)
SUBJECT_LINE_RE = re.compile(
    r"(?m)^\s*(MATHEMATICS|MATHS|PHYSICS|CHEMISTRY|BOTANY|ZOOLOGY|BIOLOGY)"
    r"\s*$"
)
QP_NAME_RE = re.compile(
    r"Question\s*Paper\s*Name\s*:\s*([^\n]+)"
)

# Boilerplate field lines in 2026 official blocks (layout metadata, not
# content). The actual stem/option text in some 2026 papers is image-only;
# what remains after stripping these is the usable text-layer content.
BOILERPLATE_2026_RES = [
    re.compile(p, re.IGNORECASE)
    for p in (
        # Order matters: longer/compound field names first, and
        # "Is Question Mandatory" before "Display Question Number" (whose
        # value tail would otherwise swallow a trailing "Is").
        r"Is\s*Question\s*Mandatory\s*:[^\n]*",
        r"Question\s*Mandatory\s*:[^\n]*",
        r"Option\s*Shuffling\s*:[^\n]*",
        r"Display\s*Question\s*Number\s*:[^\n]*",
        r"Single\s*Line\s*Question\s*Option\s*:[^\n]*",
        r"Option\s*Orientation\s*:[^\n]*",
        r"Keyboard\s*Layout\s*:[^\n]*",
        r"Response\s*Type\s*:[^\n]*",
        r"Evaluation\s*Required\s*For\s*SA\s*:[^\n]*",
        r"Show\s*Word\s*Count\s*:[^\n]*",
        r"Answers\s*Type\s*:[^\n]*",
        r"Text\s*Areas\s*:[^\n]*",
        r"Possible\s*Answers\s*:\s*\n?\s*\d*",
        r"Options\s*:",
    )
]
# Option lines in 2026 papers carry NTA option IDs: "6911211. <text>".
OPTION_ID_LINE_RE = re.compile(r"(?m)^\s*(\d{6,})\s*\.\s*")

# Mirror PDFs often embed per-question "Answer (2)" / "Sol." inline; these
# are source-printed answers (NOT verified keys) — capture them into the raw
# answer_sheet, then truncate them out of the question text and flag.
EMBEDDED_ANSWER_RE = re.compile(
    r"(?im)^\s*(Answer\s*[:.(]|Ans\s*[.:\)]|Sol\s*[.:]|Official\s+Ans)"
)
EMBEDDED_ANSWER_VALUE_RE = re.compile(
    r"(?i)\b(?:Official\s+Ans(?:\.|\s+by\s+NTA)?|Answer|Ans)"
    r"\s*(?:[.:\)]|\()\s*\(?\s*([A-Da-d]|[1-4])\s*\)?"
)

# Question-number markers for generic mirror papers: "Q.12", "Q 12", "12."
# or "12)" at the start of a line.
GENERIC_QNO_RE = re.compile(
    r"(?m)^\s*(?:Q[.\s:]?\s*)?(\d{1,3})\s*[.)]\s+"
)
# Memory-based papers often use repeated unnumbered "Question:" blocks.
QUESTION_COLON_RE = re.compile(r"(?im)^\s*Question\s*[:\-]\s*")
OPTION_LINE_RE = re.compile(
    r"(?m)^\s*(?:\(\s*([1-4])\s*\)|([1-4])[.)]|\(\s*([A-Da-d])\s*\)|([A-Da-d])[.)])\s+"
)
SECTION_CUT_RE = re.compile(
    r"(?im)^\s*(?:section\s*[:\-]?\s*)?"
    r"(solutions?|answer\s*key|answers|hints?\s*(?:&|and)\s*solutions?)"
    r"\s*(?:section)?\s*[:.\-]?\s*$"
)


def detect_format(pages: list[str]) -> str:
    """Classify a paper's text layer into one of the known layouts."""
    full = "\n".join(pages)
    if re.search(r"Question\s*Number\s*:", full) and re.search(
        r"Question\s*Id\s*:", full
    ):
        return FMT_2026
    if re.search(r"ItemCode", full) or (
        re.search(r"Topic\s*Name\s*:", full) and HDR2022_Q_RE.search(full)
    ):
        return FMT_2022
    return FMT_GENERIC


def _join_pages(pages: list[str]) -> tuple[str, list[int]]:
    """Concatenate page texts, returning (full_text, offsets of each page)."""
    offsets = []
    pos = 0
    chunks = []
    for t in pages:
        offsets.append(pos)
        chunks.append(t)
        pos += len(t) + 1
    return "\n".join(chunks), offsets


def _page_of(offsets: list[int], pos: int) -> int:
    return bisect.bisect_right(offsets, pos)  # 1-based page number


def _extract_options(block: str) -> tuple[dict, list[str]]:
    """Pull (1)..(4) / (A)..(D) options out of a raw block.

    Returns (options dict keyed A-D, flags). Options with embedded newlines
    are re-joined; anything not matching 4 options is flagged, not fixed.
    """
    matches = list(OPTION_LINE_RE.finditer(block))
    flags = []
    options: dict[str, str] = {}
    for i, m in enumerate(matches):
        digit = m.group(1) or m.group(2)
        letter = m.group(3) or m.group(4)
        if digit:
            key = "ABCD"[int(digit) - 1]
        else:
            key = letter.upper()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(block)
        text = block[start:end].strip()
        if key in options:
            flags.append(f"duplicate_option_marker_{key}")
        options.setdefault(key, re.sub(r"\s+", " ", text))
    if len(options) != 4:
        flags.append(f"options_count_{len(options)}")
    return options, flags


def _stem_before_options(block: str) -> str:
    m = OPTION_LINE_RE.search(block)
    stem = block[: m.start()] if m else block
    return stem.strip()


def _common_flags(q: dict) -> list[str]:
    flags = list(q.get("parse_flags", []))
    stem = q.get("text", "")
    if not stem.strip():
        if "stem_image_only" not in flags:
            flags.append("empty_stem")
    elif len(stem) < 20:
        flags.append("stem_under_20_chars")
    if ANSWER_MARKER_RE.search(q.get("text", "")) or any(
        ANSWER_MARKER_RE.search(v) for v in (q.get("options") or {}).values()
    ):
        flags.append("possible_embedded_answer_marker")
    if re.search(r"(?i)\b(the|following)\s+(figure|graph|diagram|table)\b", stem):
        flags.append("references_figure_not_extracted")
    # Scramble signature from EXTRACTION_QUALITY_SPEC.md: math rendered as
    # glyph dumps leaves many isolated tiny tokens in the text layer.
    short_lines = [ln for ln in stem.splitlines() if 0 < len(ln.strip()) <= 2]
    if len(short_lines) >= 8:
        flags.append("possible_text_scramble")
    return flags


def _subjects_by_position(full: str) -> list[tuple[int, str, Optional[str]]]:
    """(position, subject, section) for every subject heading in the text."""
    out = []
    for m in SECTION_HEADING_RE.finditer(full):
        out.append((m.start(), m.group(1).title(), f"Section {m.group(2)}"))
    for m in SUBJECT_LINE_RE.finditer(full):
        subj = m.group(1).title()
        out.append((m.start(), "Mathematics" if subj == "Maths" else subj, None))
    out.sort()
    return out


def _subject_at(headings: list[tuple[int, str, Optional[str]]], pos: int):
    subject, section = None, None
    for hpos, hsubj, hsec in headings:
        if hpos > pos:
            break
        subject = hsubj
        if hsec:
            section = hsec
    return subject, section


def _strip_2026_boilerplate(text: str) -> str:
    for rx in BOILERPLATE_2026_RES:
        text = rx.sub("\n", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def _normalize_embedded_answer(token: str) -> dict:
    raw = token.strip().upper()
    out = {"raw": raw}
    if raw in ("A", "B", "C", "D"):
        out["option"] = raw
    elif raw in ("1", "2", "3", "4"):
        out["option"] = "ABCD"[int(raw) - 1]
        out["option_index"] = int(raw)
    return out


def _truncate_embedded_answer(block: str) -> tuple[str, Optional[dict]]:
    m = EMBEDDED_ANSWER_RE.search(block)
    if not m:
        return block, None
    vm = EMBEDDED_ANSWER_VALUE_RE.search(block, m.start())
    answer = _normalize_embedded_answer(vm.group(1)) if vm else {"raw": None}
    return block[: m.start()], answer


def detect_paper_meta(pages: list[str]) -> dict:
    """Deterministic paper-level facts from the text layer itself.

    Handles 2026 NTA headers ('Question Paper Name : B Tech 2nd Apr 2026
    Shift 1') and eSaral memory headers ('JEE-Main-31-01-2024 ... [MORNING
    SHIFT]').
    """
    full = "\n".join(pages[:2])
    out: dict = {}
    m = QP_NAME_RE.search(full)
    if m:
        name = m.group(1).strip()
        out["question_paper_name"] = name
        dm = re.search(
            r"(\d{1,2})(?:st|nd|rd|th)?\s+"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})",
            name, re.IGNORECASE,
        )
        if dm:
            out["exam_date"] = (
                f"{dm.group(3)}-{MONTHS[dm.group(2).lower()[:3]]:02d}"
                f"-{int(dm.group(1)):02d}"
            )
        sm = re.search(r"Shift\s*[-:]?\s*(\d)", name, re.IGNORECASE)
        if sm:
            out["shift"] = int(sm.group(1))
    gm = re.search(r"JEE[- ]?Main[- ](\d{2})-(\d{2})-(\d{4})", full, re.I)
    if gm and "exam_date" not in out:
        out["exam_date"] = f"{gm.group(3)}-{gm.group(2)}-{gm.group(1)}"
    if "shift" not in out:
        if re.search(r"\bmorning\s+shift\b|\bshift[- ]?1\b", full, re.I):
            out["shift"] = 1
        elif re.search(r"\bevening\s+shift\b|\bshift[- ]?2\b", full, re.I):
            out["shift"] = 2
    return out


def parse_nta_2026(pages: list[str]) -> list[dict]:
    full, offsets = _join_pages(pages)
    headings = _subjects_by_position(full)
    matches = list(HDR2026_RE.finditer(full))
    questions = []
    for i, m in enumerate(matches):
        qno, qid, qtype = int(m.group(1)), m.group(2), m.group(3).upper()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full)
        block = full[start:end]
        subject, section = _subject_at(headings, m.start())
        qtype_map = {"MCQ": "single_correct", "SA": "numerical"}
        question = {
            "qno": qno,
            "question_id": qid,
            "question_type": qtype_map.get(qtype, qtype),
            "subject": subject,
            "section": section,
            "text": "",
            "options": None,
            "option_ids": None,
            "page_start": _page_of(offsets, m.start()),
            "page_end": _page_of(offsets, end),
            "parse_flags": [],
        }
        if qtype == "MCQ":
            # Split stem from the "Options :" option-ID list.
            opt_split = re.split(r"(?m)^\s*Options\s*:\s*$", block, maxsplit=1)
            stem_part = opt_split[0]
            opts_part = opt_split[1] if len(opt_split) > 1 else ""
            oid_matches = list(OPTION_ID_LINE_RE.finditer(opts_part))
            options, option_ids = {}, []
            if oid_matches:
                for j, om in enumerate(oid_matches):
                    oend = (
                        oid_matches[j + 1].start()
                        if j + 1 < len(oid_matches)
                        else len(opts_part)
                    )
                    key = "ABCD"[j] if j < 4 else f"X{j}"
                    options[key] = re.sub(
                        r"\s+", " ", opts_part[om.end():oend].strip()
                    )
                    option_ids.append(om.group(1))
                question["text"] = _strip_2026_boilerplate(stem_part)
            else:
                # Fallback: no "Options :" ID list — try paren-style options.
                opts, oflags = _extract_options(block)
                options = opts
                question["text"] = _strip_2026_boilerplate(
                    _stem_before_options(block)
                )
                question["parse_flags"].extend(oflags)
            question["options"] = options or None
            question["option_ids"] = option_ids or None
            count_flag = f"options_count_{len(options)}"
            if len(options) != 4 and count_flag not in question["parse_flags"]:
                question["parse_flags"].append(count_flag)
            if options and all(not v for v in options.values()):
                question["parse_flags"].append("options_image_only")
        else:
            question["text"] = _strip_2026_boilerplate(block)
        if not question["text"]:
            # 2026 papers whose stems are images: IDs/structure are real and
            # key-joinable, but content needs OCR — flag, do not invent text.
            question["parse_flags"].append("stem_image_only")
        question["parse_flags"] = _common_flags(question)
        questions.append(question)
    return questions, {}


def parse_nta_2022(pages: list[str]) -> list[dict]:
    full, offsets = _join_pages(pages)
    headings = _subjects_by_position(full)
    matches = list(HDR2022_Q_RE.finditer(full))
    questions = []
    for i, m in enumerate(matches):
        qno = int(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full)
        block = full[start:end]
        block, embedded_answer = _truncate_embedded_answer(block)
        topic_m = TOPIC_RE.search(block)
        item_m = ITEMCODE_RE.search(block)
        subject = None
        section = None
        if topic_m:
            topic = topic_m.group(1).strip()
            parts = re.split(r"\s*-\s*", topic, maxsplit=1)
            subject = parts[0].strip() or None
            section = parts[1].strip() if len(parts) > 1 else None
        if subject is None:
            subject, hsec = _subject_at(headings, m.start())
            section = section or hsec
        question = {
            "qno": qno,
            "question_id": item_m.group(1) if item_m else None,
            "question_type": None,
            "subject": subject,
            "section": section,
            "text": _stem_before_options(block),
            "options": None,
            "page_start": _page_of(offsets, m.start()),
            "page_end": _page_of(offsets, end),
            "parse_flags": [],
        }
        if embedded_answer is not None:
            question["embedded_answer"] = embedded_answer
            question["parse_flags"].append("embedded_answer_captured")
            question["parse_flags"].append("embedded_answer_truncated")
        opts, oflags = _extract_options(block)
        stem_source = ITEMCODE_RE.sub("", TOPIC_RE.sub("", block))
        question["text"] = _stem_before_options(stem_source)
        if opts:
            question["options"] = opts
            question["question_type"] = "single_correct"
            question["parse_flags"].extend(oflags)
        elif section and "b" in section.lower():
            question["question_type"] = "numerical"
        else:
            question["parse_flags"].append("no_options_found")
        if not item_m:
            question["parse_flags"].append("missing_itemcode")
        question["parse_flags"] = _common_flags(question)
        questions.append(question)
    return questions, {}


def parse_generic_mirror(pages: list[str]) -> list[dict]:
    # Cut trailing solution/answer-key SECTIONS before block splitting.
    kept_pages = []
    for t in pages:
        cut = SECTION_CUT_RE.search(t)
        kept_pages.append(t[: cut.start()] if cut else t)
    full, offsets = _join_pages(kept_pages)
    headings = _subjects_by_position(full)

    candidates = list(GENERIC_QNO_RE.finditer(full))
    # Keep consecutive question-number runs. Full papers run 1..75; subject
    # PDFs often run 31..60 (Chemistry) or 61..90 (Maths). Isolated numbers
    # inside worked solutions are noise, so a run must have at least 2 markers
    # unless it is an explicit subject restart after a heading.
    heading_positions = [h[0] for h in headings]
    runs: list[list[re.Match]] = []
    current: list[re.Match] = []
    skipped: list[int] = []  # out-of-order higher numbers = likely lost questions

    def flush_run():
        nonlocal current
        if len(current) >= 2:
            runs.append(current)
        elif current:
            skipped.extend(int(m.group(1)) for m in current)
        current = []

    last = None
    for m in candidates:
        n = int(m.group(1))
        if last is None:
            current, last = [m], n
            continue
        if n == last + 1:
            current.append(m)
            last = n
            continue
        if n == last:
            continue  # duplicate marker in two-column text
        if n == 1 and current and any(
            current[-1].start() < hp < m.start() for hp in heading_positions
        ):
            flush_run()
            current, last = [m], n
            continue
        if n > last:
            flush_run()
            current, last = [m], n
            continue
        skipped.append(n)
    flush_run()
    markers: list[tuple[re.Match, int]] = [
        (m, seg) for seg, run in enumerate(runs) for m in run
    ]
    if not markers:
        # Fallback for memory-based papers with repeated unnumbered
        # "Question:" blocks (seen in 2024 Session-1 eSaral PDFs).
        qmarks = list(QUESTION_COLON_RE.finditer(full))
        if len(qmarks) >= 2:
            questions = []
            for i, m in enumerate(qmarks, start=1):
                start = m.end()
                end = qmarks[i].start() if i < len(qmarks) else len(full)
                block = full[start:end]
                block, embedded_answer = _truncate_embedded_answer(block)
                subject, section = _subject_at(headings, m.start())
                question = {
                    "qno": i,
                    "question_id": None,
                    "question_type": None,
                    "subject": subject,
                    "section": section,
                    "segment": 0,
                    "text": _stem_before_options(block),
                    "options": None,
                    "page_start": _page_of(offsets, m.start()),
                    "page_end": _page_of(offsets, end),
                    "parse_flags": ["unnumbered_question_colon_format"],
                }
                if embedded_answer is not None:
                    question["embedded_answer"] = embedded_answer
                    question["parse_flags"].append("embedded_answer_captured")
                    question["parse_flags"].append("embedded_answer_truncated")
                opts, oflags = _extract_options(block)
                if opts:
                    question["options"] = opts
                    question["question_type"] = "single_correct"
                    question["parse_flags"].extend(oflags)
                else:
                    question["parse_flags"].append("no_options_found")
                question["parse_flags"] = _common_flags(question)
                questions.append(question)
            return questions, {"skipped_markers": skipped}
    questions = []
    for i, (m, seg) in enumerate(markers):
        qno = int(m.group(1))
        start = m.end()
        end = markers[i + 1][0].start() if i + 1 < len(markers) else len(full)
        block = full[start:end]
        block, embedded_answer = _truncate_embedded_answer(block)
        subject, section = _subject_at(headings, m.start())
        question = {
            "qno": qno,
            "question_id": None,  # mirror PDFs have no NTA question IDs
            "question_type": None,
            "subject": subject,
            "section": section,
            "segment": seg,
            "text": _stem_before_options(block),
            "options": None,
            "page_start": _page_of(offsets, m.start()),
            "page_end": _page_of(offsets, end),
            "parse_flags": [],
        }
        if embedded_answer is not None:
            question["embedded_answer"] = embedded_answer
            question["parse_flags"].append("embedded_answer_captured")
            question["parse_flags"].append("embedded_answer_truncated")
        if seg > 0:
            question["parse_flags"].append(f"numbering_restart_segment_{seg}")
        opts, oflags = _extract_options(block)
        if opts:
            question["options"] = opts
            question["question_type"] = "single_correct"
            question["parse_flags"].extend(oflags)
        else:
            question["parse_flags"].append("no_options_found")
        question["parse_flags"] = _common_flags(question)
        questions.append(question)

    # A final segment of short, option-less stubs is a trailing answer key
    # that dodged the section cut — drop it and say so in the flags.
    if questions:
        last_seg = questions[-1]["segment"]
        tail = [q for q in questions if q["segment"] == last_seg]
        if last_seg > 0 and tail and all(
            len(q["text"]) < 40 and not q["options"] for q in tail
        ):
            questions = [q for q in questions if q["segment"] != last_seg]
            for q in questions:
                if q["segment"] == last_seg - 1:
                    q["parse_flags"].append("trailing_answer_key_segment_dropped")
    return questions, {"skipped_markers": skipped}


PARSERS = {
    FMT_2026: parse_nta_2026,
    FMT_2022: parse_nta_2022,
    FMT_GENERIC: parse_generic_mirror,
}


def build_answer_sheet(questions: list[dict], official_key_url=None) -> dict:
    """Structured raw answer sheet. Embedded mirror answers are captured as
    unverified source-printed answers; official NTA keys are referenced, never
    guessed. No entry is fabricated when the source has no answer text."""
    entries = []
    for q in questions:
        ans = q.get("embedded_answer")
        if not ans:
            continue
        entries.append({
            "qno": q.get("qno"),
            "question_id": q.get("question_id"),
            "subject": q.get("subject"),
            "section": q.get("section"),
            "answer": ans,
        })
    if entries:
        status, source = "embedded_unverified", "mirror_pdf_embedded"
    elif official_key_url:
        status, source = "official_key_pending", "official_nta_key"
    else:
        status, source = "unavailable", None
    return {
        "status": status,
        "source": source,
        "official_key_url": official_key_url,
        "validation": "not_verified",
        "entries": entries,
    }


def extract_paper(pages: list[str]) -> dict:
    """Parse one paper's per-page text into raw question blocks."""
    fmt = detect_format(pages)
    questions, aux = PARSERS[fmt](pages)
    status = "extracted" if questions else "parse_failed"
    defects = []
    if status == "parse_failed":
        defects.append(
            "text layer present but no question blocks matched any known "
            "layout; paper may be solutions-only, image-based, or an "
            "unrecognized format"
        )
    # Question numbers restart per subject in mirror papers, and subject PDFs
    # may start at 31/61; require consecutive numbering within each segment,
    # not a start at 1.
    segs: dict[int, list[int]] = {}
    for q in questions:
        segs.setdefault(q.get("segment", 0), []).append(q["qno"])
    bad = [
        s for s, qnos in segs.items()
        if qnos and qnos != list(range(qnos[0], qnos[0] + len(qnos)))
    ]
    if bad:
        defects.append(
            f"non_sequential_qnos in segments {bad}: "
            + "; ".join(f"seg {s}: {segs[s][:12]}" for s in bad[:3])
        )
    skipped = aux.get("skipped_markers") or []
    if skipped:
        defects.append(
            f"{len(skipped)} question markers skipped as out-of-order "
            f"(text-layer reading order scrambled; likely lost questions): "
            f"{skipped[:15]}"
        )
    n_flagged = sum(1 for q in questions if q["parse_flags"])
    if n_flagged:
        defects.append(f"{n_flagged}/{len(questions)} questions carry parse_flags")
    n_image_stems = sum(
        1 for q in questions if "stem_image_only" in q["parse_flags"]
    )
    if questions and n_image_stems > len(questions) / 2:
        defects.append(
            f"{n_image_stems}/{len(questions)} stems are image-only in the "
            "text layer; IDs/structure extracted but content needs OCR"
        )
    return {
        "format": fmt,
        "status": status,
        "detected_paper_meta": detect_paper_meta(pages),
        "question_count": len(questions),
        "answer_sheet": build_answer_sheet(questions),
        "defects": defects,
        "questions": questions,
    }


def cmd_extract(args: argparse.Namespace) -> None:
    import fitz  # PyMuPDF — dev-only dependency (not in requirements.txt)

    manifest = load_manifest()
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    for entry in _select_entries(manifest, args):
        pid = entry["paper_id"]
        probe = entry.get("probe") or {}
        cache_rel = probe.get("cache_path")
        out_path = PAPERS_DIR / f"{pid}.json"
        tags = entry.get("tags") or build_tags(entry, entry.get("pdf_url", ""))
        result = {
            "paper_id": pid,
            "exam_tag": entry.get("exam_tag") or tags[0],
            "tags": tags,
            "manifest": {k: v for k, v in entry.items() if k != "probe"},
            "probe": probe or None,
            "answer_sheet": build_answer_sheet([], entry.get("official_key_url")),
        }
        if probe.get("error") or not cache_rel:
            result.update(
                format=None, status="probe_failed", question_count=0,
                defects=["probe failed or no cached PDF"], questions=[],
            )
        elif not probe.get("has_text_layer"):
            result.update(
                format=None, status="needs_ocr", question_count=0,
                defects=["no usable text layer; OCR deferred per task scope"],
                questions=[],
            )
        else:
            try:
                doc = fitz.open(ROOT / cache_rel)
                pages = [page.get_text() for page in doc]
                doc.close()
                result.update(extract_paper(pages))
                result["answer_sheet"] = build_answer_sheet(
                    result.get("questions", []), entry.get("official_key_url")
                )
            except Exception as exc:
                result.update(
                    format=None, status="parse_failed", question_count=0,
                    defects=[f"exception: {exc}"], questions=[],
                )
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(f"[extract] {pid}: {result['status']} "
              f"({result.get('question_count', 0)} questions)")


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

def cmd_summary(args: argparse.Namespace) -> None:
    manifest = load_manifest()
    lines = [
        "# NTA raw extraction summary",
        "",
        "Deterministic pipeline (`scripts/extract_nta_papers.py`) — no LLM, no DB writes.",
        "Raw layer only: no answers fabricated, nothing marked servable; defects are flagged.",
        "",
        "## Manifest",
        "",
        f"- entries: {len(manifest)}",
    ]
    by_tier: dict[str, int] = {}
    probed = 0
    for e in manifest:
        by_tier[e["source_tier"]] = by_tier.get(e["source_tier"], 0) + 1
        if e.get("probe") and not e["probe"].get("error"):
            probed += 1
    for tier, n in sorted(by_tier.items()):
        lines.append(f"- {tier}: {n}")
    lines.append(f"- probed OK: {probed}")

    lines += [
        "",
        "## Per-paper extraction results",
        "",
        "| paper_id | exam_tag | format | status | questions | answer_sheet | flagged | defects |",
        "|---|---|---|---|---|---|---|---|",
    ]
    totals: dict[str, int] = {}
    answer_totals: dict[str, int] = {}
    paper_files = sorted(PAPERS_DIR.glob("*.json")) if PAPERS_DIR.exists() else []
    for pf in paper_files:
        r = json.loads(pf.read_text())
        totals[r["status"]] = totals.get(r["status"], 0) + 1
        answer_status = (r.get("answer_sheet") or {}).get("status") or "-"
        answer_totals[answer_status] = answer_totals.get(answer_status, 0) + 1
        n_flagged = sum(
            1 for q in r.get("questions", []) if q.get("parse_flags")
        )
        defects = "; ".join(r.get("defects", []))[:120]
        lines.append(
            f"| {r['paper_id']} | {r.get('exam_tag') or '-'} "
            f"| {r.get('format') or '-'} | {r['status']} "
            f"| {r.get('question_count', 0)} | {answer_status} "
            f"| {n_flagged} | {defects or '-'} |"
        )
    lines += ["", "## Status totals", ""]
    for status, n in sorted(totals.items()):
        lines.append(f"- {status}: {n}")
    lines += ["", "## Answer-sheet totals", ""]
    for status, n in sorted(answer_totals.items()):
        lines.append(f"- {status}: {n}")
    lines += [
        "",
        "## Goal audit",
        "",
        f"- extracted paper artifacts: {totals.get('extracted', 0)}",
        f"- needs_ocr artifacts: {totals.get('needs_ocr', 0)}",
        f"- parse_failed artifacts: {totals.get('parse_failed', 0)}",
        "- counting rule: each sourced PDF is counted as one paper artifact;",
        "  subject-wise PDFs are not merged into full shifts in this count.",
        "- official-key status is stored per artifact as answer_sheet.status;",
        "  embedded mirror answers remain validation=not_verified.",
    ]
    if not paper_files:
        lines.append("- (no papers extracted yet)")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n")
    print(f"[summary] wrote {REPORT_PATH}")


# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("harvest", help="build data/nta_raw/manifest.json")
    p.add_argument("--skip-esaral", action="store_true",
                   help="only seed official 2026 + brief sample URLs")
    p.add_argument("--skip-question-banks", action="store_true",
                   help="skip MathonGo/NTA-Abhyas chapter-wise question banks")
    p.add_argument("--skip-selfstudys", action="store_true",
                   help="skip SelfStudys year-wise/chapter-wise papers")
    p.add_argument("--selfstudys-max-pages", type=int, default=None,
                   help="cap SelfStudys book pages for smoke tests")
    p.set_defaults(func=cmd_harvest)

    p = sub.add_parser("harvest-selfstudys", help="refresh only SelfStudys entries in the manifest")
    p.add_argument("--selfstudys-max-pages", type=int, default=None,
                   help="cap SelfStudys book pages for smoke tests")
    p.set_defaults(func=cmd_harvest_selfstudys)

    p = sub.add_parser("harvest-neet-official", help="append official NEET archive papers")
    p.set_defaults(func=cmd_harvest_neet_official)

    p = sub.add_parser("harvest-jee-advanced", help="append official JEE Advanced papers 2022-2026")
    p.set_defaults(func=cmd_harvest_jee_advanced)

    p = sub.add_parser("probe", help="download + fingerprint PDFs into scratch cache")
    p.add_argument("--only", nargs="*", default=None,
                   help="paper_ids (or URL substrings) to probe")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--redownload", action="store_true")
    p.add_argument("--workers", type=int, default=4,
                   help="parallel PDF download/probe workers")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("extract", help="parse cached PDFs into data/nta_raw/papers/")
    p.add_argument("--only", nargs="*", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("summary", help="write reports/nta_raw_extraction_summary.md")
    p.set_defaults(func=cmd_summary)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
