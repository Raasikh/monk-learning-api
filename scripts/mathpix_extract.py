"""Extract a Drona master book through the Mathpix PDF API, with caching.

WHY MATHPIX AND NOT THE LOCAL EXTRACTOR
---------------------------------------
Measured on 30 hand-transcribed equations from Maths 12 Ch 8, four extractors:

    PyMuPDF get_text()            (the incumbent)   1 exact / 30
    get_text("dict") + geometry   (~200 lines)     14 exact / 30
    pdftotext -layout                               1 exact / 30
    Mathpix                                        30 exact / 30

Not close, and 14/30 is not shippable either: more than half of displayed
maths still wrong, 11 of them actively false statements rather than merely
under-delimited. Plausible errors are worse than obvious ones.

There is also damage no local extractor can reach. Class 12 Physics p416
renders B1 = mu0*N1*I1/(2R); the PDF text layer contains a DejaVuSerif span
whose text is literally '0'. U+03BC survives 18 times in 925 pages. The
character is not in the document, so dict mode sees exactly what plain mode
sees. Only pixel OCR recovers it.

WHY .lines.json AND NOT .md
--------------------------
The markdown export loses the page number, and page_start/page_end must be
real (they were hardcoded to 1 across all 5,266 rows of the corpus before
last). .lines.json carries, per line: the page, a `type`, and `text` with
LaTeX already in it. Two of those types do work we would otherwise hand-roll:

    section_header  ->  heading hierarchy, i.e. section_key, for free
    page_info       ->  running headers, footers and folios, ALREADY
                        classified, so the regex furniture stripping this
                        replaces becomes unnecessary

CACHING IS NOT OPTIONAL
-----------------------
Mathpix bills per page. A re-run that re-submits is a re-charge, and this
script will be re-run — every ingest so far has needed at least two attempts.
Results are cached to disk keyed by the file's content hash, so re-running is
free and a partial corpus can be resumed.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

API = "https://api.mathpix.com/v3/pdf"
CACHE = Path(__file__).resolve().parent.parent / "data" / "mathpix_cache"
POLL_SECONDS = 5
POLL_LIMIT = 720  # 60 minutes; a 1,232-page book is the worst case


def _headers() -> Dict[str, str]:
    app_id = os.environ.get("MATHPIX_APP_ID")
    app_key = os.environ.get("MATHPIX_APP_KEY")
    if not app_id or not app_key:
        raise SystemExit("MATHPIX_APP_ID / MATHPIX_APP_KEY not set")
    return {"app_id": app_id, "app_key": app_key}


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


def extract(pdf_path: str, force: bool = False) -> dict:
    """Return Mathpix .lines.json for a PDF, from cache when possible.

    The cache key is the file's CONTENT hash, not its name: a rebuilt book
    with the same filename is a different document and must not silently
    reuse the previous extraction.
    """
    path = Path(pdf_path)
    digest = _file_hash(path)
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{path.stem}.{digest}.lines.json"

    if cached.exists() and not force:
        print(f"  cache hit  {cached.name}")
        return json.loads(cached.read_text())

    hdr = _headers()
    print(f"  submitting {path.name} ({path.stat().st_size / 1e6:.1f} MB) — this is billed")
    with path.open("rb") as f:
        r = requests.post(
            API, headers=hdr, files={"file": f},
            data={"options_json": json.dumps({"conversion_formats": {"md": True}})},
            timeout=600,
        )
    r.raise_for_status()
    pdf_id = r.json().get("pdf_id")
    if not pdf_id:
        raise SystemExit(f"no pdf_id returned: {r.text[:300]}")

    # Record the id immediately. If polling dies, the work is already paid for
    # and must be recoverable rather than repurchased.
    (CACHE / f"{path.stem}.{digest}.pdf_id").write_text(pdf_id)

    for i in range(POLL_LIMIT):
        st = requests.get(f"{API}/{pdf_id}", headers=hdr, timeout=120).json()
        status = st.get("status")
        if status == "completed":
            break
        if status == "error":
            raise SystemExit(f"mathpix error: {json.dumps(st)[:400]}")
        if i % 12 == 0:
            print(f"    {status} … {i * POLL_SECONDS}s")
        time.sleep(POLL_SECONDS)
    else:
        raise SystemExit(f"timed out; pdf_id {pdf_id} is paid for and resumable")

    lines = requests.get(f"{API}/{pdf_id}.lines.json", headers=hdr, timeout=300).json()
    cached.write_text(json.dumps(lines))
    print(f"  cached -> {cached.name}  ({len(lines.get('pages', []))} pages)")
    return lines


# --------------------------------------------------------------- page assembly

# Line types that are furniture rather than content. Mathpix classifies these
# itself, which is strictly better than the regexes this replaces: those were
# written by reading a handful of pages and would miss any book that formats
# its footer differently.
SKIP_TYPES = {
    "page_info",                 # running header, footer, folio
    "table_of_contents_item",    # dot-leader contents pages
    "table_of_contents_number",
}


def page_text(page: dict) -> str:
    """Content of one page, furniture removed, LaTeX preserved."""
    out: List[str] = []
    for ln in page.get("lines", []):
        if ln.get("type") in SKIP_TYPES:
            continue
        t = ln.get("text")
        if t:
            out.append(t)
    return "\n\n".join(out).strip()


def page_headings(page: dict) -> List[str]:
    """section_header lines on this page, in order."""
    return [ln.get("text", "").strip()
            for ln in page.get("lines", [])
            if ln.get("type") == "section_header" and ln.get("text")]


def page_has_math(page: dict) -> bool:
    """True if Mathpix classified at least one line as math.

    THIS IS THE QA GATE, and it reads Mathpix's own line typing rather than
    grepping the output for `$...$`. Using the classifier we switched to is
    the point of switching: a grep would also match a stray dollar sign in
    prose and would miss a math line rendered without delimiters.
    """
    return any(ln.get("type") == "math" for ln in page.get("lines", []))


def page_is_contents(page: dict) -> bool:
    """A contents page: mostly dot leaders and page numbers, no teaching text.

    Found in the pilot slice, and worth its own predicate rather than a
    length heuristic: my earlier regex-based folio strip would have deleted
    the 0/1 values in a genuine binary data table, because both look like
    "a line containing only digits". Mathpix separates them by TYPE --
    table_of_contents_number versus simple_cell -- which the regex could not.
    """
    lines = page.get("lines", [])
    if not lines:
        return False
    toc = sum(1 for ln in lines if (ln.get("type") or "").startswith("table_of_contents"))
    return toc >= max(5, 0.4 * len(lines))


def page_dropped_math(page: dict) -> bool:
    """A figure page that carries display maths.

    Mathpix crops figures to an image and transcribes only the caption --
    verified, including with include_diagram_text=True, which changes nothing.
    So the formulas rendered INSIDE a figure are lost. 56 of 6,888 pages are
    affected (0.8%), concentrated in physics 11 (21) and maths 12 (14).

    We accept that loss, but it must be LOGGED per page: a formula that was
    dropped has to be distinguishable from one that never existed. Silent
    deletion is the defect shape this project keeps finding -- it is exactly
    what _latex_to_speech was doing to \\int and \\log.
    """
    text = page_text(page)
    return "FIGURES" in text[:200].upper() and "$" in text


if __name__ == "__main__":
    for p in sys.argv[1:]:
        d = extract(p)
        pages = d.get("pages", [])
        math_pages = sum(1 for pg in pages if page_has_math(pg))
        heads = sum(len(page_headings(pg)) for pg in pages)
        print(f"{Path(p).name}: {len(pages)} pages, {math_pages} with maths, {heads} section headers")
