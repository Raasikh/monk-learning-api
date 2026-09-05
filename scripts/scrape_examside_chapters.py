#!/usr/bin/env python3
"""Scrape ExamSIDE chapter pages for diagram-bearing JEE/NEET questions.

NO LLM: chapter pages are server-rendered question lists. This scraper keeps only
questions whose preview contains an embedded image, records the source question
URL, and optionally downloads the image as a durable asset. Options/answers are
not fetched from detail pages in this pass, so answer_sheet.status is explicit
("unavailable") and every row stays pending_gate.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_mod
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "nta_raw"
OUT_PATH = DATA_DIR / "examside_diagram_questions.jsonl"
ASSET_DIR = DATA_DIR / "diagram_assets" / "examside"
REPORT_PATH = ROOT / "reports" / "examside_diagram_scrape.md"
HTML_CACHE_DIR = ROOT / "scratch" / "examside_html_cache"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/124 Safari/537.36"}
CHAPTER_LINK_RE = re.compile(r'href="([^"]+)"')
QUESTION_RE = re.compile(
    r'<a class="cp-q[^"]*" href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL
)
IMG_RE = re.compile(r'<img[^>]+src="([^"]+)"[^>]*>', re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


def get_text(url: str) -> str:
    cache = HTML_CACHE_DIR / f"{hashlib.sha256(url.encode()).hexdigest()}.html"
    if cache.exists():
        return cache.read_text()
    resp = requests.get(url, headers=HEADERS, timeout=45)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(resp.text)
    return resp.text


def strip_html(text: str) -> str:
    text = html_mod.unescape(text or "")
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def exam_from_url(url: str) -> str:
    if "/medical/neet" in url:
        return "neet-ug"
    if "/jee/jee-advanced" in url:
        return "jee-advanced"
    if "/jee/jee-main" in url:
        return "jee-main"
    return "other"


def tags_for(exam: str) -> list[str]:
    if exam in {"neet-ug", "jee-main", "jee-advanced"}:
        return [exam, "class-11", "class-12", "entrance-exam"]
    return [exam]


def download_asset(url: str, dest: Path) -> dict:
    resp = requests.get(url, headers=HEADERS, timeout=45)
    resp.raise_for_status()
    data = resp.content
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {"path": str(dest.relative_to(ROOT)), "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "source_url": url}


def chapter_links(subject_url: str) -> list[str]:
    html = get_text(subject_url)
    base = subject_url.rstrip("/") + "/"
    links = []
    for m in CHAPTER_LINK_RE.finditer(html):
        full = urljoin(subject_url, m.group(1)).split("#")[0].rstrip("/")
        if not full.startswith(base):
            continue
        if full not in links:
            links.append(full)
    return links


def scrape_question_detail(qurl: str, image_url: str) -> dict:
    """Fetch one ExamSIDE question page and extract options for the component
    containing image_url. Correctness is not marked in static HTML, so answers
    remain unavailable rather than guessed."""
    html = get_text(qurl)
    components = re.split(r'<div class="question-component', html)[1:]
    for comp in components:
        if image_url not in comp:
            continue
        options = {}
        for om in re.finditer(
            r'<div class="option"[^>]*data-option="(\d+)".*?'
            r'HTML_TAG_START -->(.*?)<!-- HTML_TAG_END',
            comp, re.DOTALL,
        ):
            key = "ABCD"[int(om.group(1))] if int(om.group(1)) < 4 else om.group(1)
            options[key] = strip_html(om.group(2))
        exp = ""
        em = re.search(
            r'<h2 class="q-section-title"[^>]*>Explanation</h2>.*?'
            r'HTML_TAG_START -->(.*?)<!-- HTML_TAG_END',
            comp, re.DOTALL,
        )
        if em:
            exp = strip_html(em.group(1))
        return {"options": options or None, "explanation": exp}
    return {"options": None, "explanation": ""}


def scrape_chapter(chapter_url: str, download_assets: bool, fetch_details: bool = False) -> list[dict]:
    html = get_text(chapter_url)
    exam = exam_from_url(chapter_url)
    parts = [p for p in chapter_url.rstrip("/").split("/") if p]
    subject = parts[-2].title() if len(parts) >= 2 else None
    chapter = parts[-1].replace("-", " ").title() if parts else None
    rows = []
    for m in QUESTION_RE.finditer(html):
        href, body = m.group(1), m.group(2)
        imgs = IMG_RE.findall(body)
        if not imgs:
            continue
        idx_m = re.search(r'cp-q-index[^>]*>(\d+)<', body)
        paper_m = re.search(r'cp-q-paper[^>]*>(.*?)</span>', body, re.DOTALL)
        preview_m = re.search(r'HTML_TAG_START -->(.*?)<!-- HTML_TAG_END', body, re.DOTALL)
        preview = strip_html(preview_m.group(1) if preview_m else body)
        qurl = urljoin(chapter_url, href)
        qindex = int(idx_m.group(1)) if idx_m else None
        assets = []
        if download_assets:
            for i, img in enumerate(imgs):
                name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", Path(img.split("?")[0]).name)
                dest = ASSET_DIR / exam / (subject or "unknown") / f"{qindex or 0:04d}_{i}_{name}"
                try:
                    assets.append(download_asset(img, dest))
                except Exception as exc:
                    assets.append({"source_url": img, "error": str(exc)})
        detail = {"options": None, "explanation": ""}
        if fetch_details:
            try:
                detail = scrape_question_detail(qurl, imgs[0])
            except Exception as exc:
                detail = {"options": None, "explanation": "", "detail_error": str(exc)}
        rows.append({
            "diagram_question_id": hashlib.sha256(qurl.encode()).hexdigest()[:16],
            "confirmation": "html_embedded_image_preview",
            "paper_id": f"examside-{exam}-{hashlib.sha256(chapter_url.encode()).hexdigest()[:10]}",
            "exam": exam,
            "exam_tag": exam,
            "tags": tags_for(exam),
            "subject": subject,
            "chapter": chapter,
            "qno": qindex,
            "question_text": preview,
            "options": detail.get("options"),
            "explanation": detail.get("explanation") or None,
            "answer_sheet": {"status": "unavailable", "source": None,
                             "official_key_url": None, "validation": "not_verified",
                             "entries": []},
            "source_tier": "mirror_html",
            "source_site": "questions.examside.com",
            "source_page_url": qurl,
            "chapter_page_url": chapter_url,
            "paper_label": strip_html(paper_m.group(1)) if paper_m else None,
            "pdf_url": None,
            "has_figure": True,
            "has_stem_figure": True,
            "needs_manual": "pending_gate",
            "diagram_image_urls": imgs,
            "diagram_assets": assets,
        })
    return rows


def cmd_scrape(args: argparse.Namespace) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else OUT_PATH

    def load_existing() -> list[dict]:
        if out_path.exists() and not args.replace:
            return [json.loads(l) for l in out_path.read_text().splitlines() if l.strip()]
        return []

    def merge_write(rows: list[dict]) -> int:
        if not rows:
            return len(load_existing())
        existing = load_existing()
        new_ids = {r["diagram_question_id"] for r in rows}
        all_rows = [r for r in existing if r.get("diagram_question_id") not in new_ids] + rows
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in all_rows))
        return len(all_rows)

    total_new = 0
    total_rows = 0
    for subject_url in args.subjects:
        links = chapter_links(subject_url)
        if args.max_chapters:
            links = links[: args.max_chapters]
        print(f"[examside] {subject_url}: {len(links)} chapters")
        subject_rows = []
        workers = max(1, args.workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(scrape_chapter, link, args.download_assets, args.fetch_details): link
                for link in links
            }
            for fut in as_completed(futures):
                link = futures[fut]
                try:
                    rows = fut.result()
                except Exception as exc:
                    print(f"[examside] WARN {link}: {exc}")
                    continue
                if rows:
                    print(f"[examside]   {link}: {len(rows)} image questions")
                subject_rows.extend(rows)
        total_rows = merge_write(subject_rows)
        total_new += len(subject_rows)
        print(f"[examside] saved {len(subject_rows)} rows from {subject_url} ({total_rows} total)")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        "# ExamSIDE diagram scrape\n\n"
        f"- subject pages: {len(args.subjects)}\n"
        f"- image questions this run: {total_new}\n"
        f"- total image questions: {total_rows}\n"
        f"- output: {out_path}\n"
        f"- assets downloaded this run: {sum(len(r.get('diagram_assets', [])) for r in load_existing())}\n"
    )
    print(f"[examside] wrote {total_new} new rows ({total_rows} total) -> {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scrape")
    p.add_argument("subjects", nargs="+", help="subject pages, e.g. .../medical/neet/biology")
    p.add_argument("--max-chapters", type=int, default=None)
    p.add_argument("--download-assets", action="store_true")
    p.add_argument("--fetch-details", action="store_true",
                   help="fetch each image question's detail page for options/explanation")
    p.add_argument("--replace", action="store_true")
    p.add_argument("--out", default=None, help="override output JSONL path")
    p.add_argument("--workers", type=int, default=4,
                   help="chapter-level parallelism for fetch-details runs")
    p.set_defaults(func=cmd_scrape)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
