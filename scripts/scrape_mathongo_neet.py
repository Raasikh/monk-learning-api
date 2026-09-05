#!/usr/bin/env python3
"""Scrape MathonGo NEET answer-key pages (HTML `const paper = [...]` data).

NO LLM: the page embeds the full question paper as a JavaScript array. We extract
that array with Node (available locally) and store raw question rows. Correct
answers are MathonGo/coaching answers, marked embedded_unverified — never treated
as official NTA keys. Diagram images are downloaded as durable assets.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_mod
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "nta_raw"
OUT_PATH = DATA_DIR / "neet_mathongo_questions.jsonl"
ASSET_DIR = DATA_DIR / "diagram_assets" / "neet_mathongo"
REPORT_PATH = ROOT / "reports" / "neet_mathongo_scrape.md"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/124 Safari/537.36"}
IMG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    text = html_mod.unescape(text or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_js_array(html: str, var_name: str = "paper") -> str:
    m = re.search(rf"const\s+{var_name}\s*=\s*\[", html)
    if not m:
        raise RuntimeError(f"const {var_name} = [...] not found")
    start = html.find("[", m.start())
    depth = 0
    in_str = None
    esc = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == in_str:
                in_str = None
            continue
        if ch in ("'", '"', "`"):
            in_str = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return html[start: i + 1]
    raise RuntimeError("unterminated JS array")


def js_array_to_json(array_literal: str) -> list[dict]:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(f"const paper = {array_literal};\nconsole.log(JSON.stringify(paper));\n")
        js_path = f.name
    try:
        out = subprocess.run(
            ["node", js_path], check=True, capture_output=True, text=True, timeout=30
        )
        return json.loads(out.stdout)
    finally:
        Path(js_path).unlink(missing_ok=True)


def download_asset(url: str, dest: Path) -> dict:
    resp = requests.get(url, headers=HEADERS, timeout=45)
    resp.raise_for_status()
    data = resp.content
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {"path": str(dest.relative_to(ROOT)), "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "source_url": url}


def scrape_page(page_url: str, download_assets: bool) -> list[dict]:
    html = requests.get(page_url, headers=HEADERS, timeout=45).text
    paper = js_array_to_json(extract_js_array(html))
    title_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    title = strip_html(title_m.group(1)) if title_m else page_url
    rows = []
    for q in paper:
        qid = q.get("_id")
        qhtml = (q.get("question") or {}).get("text") or ""
        option_html = [(o.get("id"), o.get("text") or "", o.get("isCorrect")) for o in q.get("options", [])]
        image_urls = []
        image_urls += IMG_RE.findall(qhtml)
        for _, otext, _ in option_html:
            image_urls += IMG_RE.findall(otext)
        image_urls = list(dict.fromkeys(image_urls))
        if not image_urls:
            continue  # this goal is diagram questions; skip text-only rows
        options = {}
        correct_option = None
        for oid, otext, is_correct in option_html:
            key = "ABCD"[int(oid) - 1] if str(oid).isdigit() and 1 <= int(oid) <= 4 else str(oid)
            options[key] = strip_html(otext)
            if is_correct:
                correct_option = key
        assets = []
        if download_assets:
            for i, url in enumerate(image_urls):
                name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", Path(url).name)
                dest = ASSET_DIR / hashlib.sha256(page_url.encode()).hexdigest()[:12] / f"q{qid}_{i}_{name}"
                try:
                    assets.append(download_asset(url, dest))
                except Exception as exc:
                    assets.append({"source_url": url, "error": str(exc)})
        rows.append({
            "diagram_question_id": hashlib.sha256(f"{page_url}#{qid}".encode()).hexdigest()[:16],
            "confirmation": "html_embedded_image",
            "paper_id": f"neet-mathongo-{hashlib.sha256(page_url.encode()).hexdigest()[:12]}",
            "exam": "neet-ug",
            "exam_tag": "neet-ug",
            "tags": ["neet-ug", "class-11", "class-12", "entrance-exam"],
            "source_tier": "mirror_html",
            "source_site": "www.mathongo.com",
            "source_page_url": page_url,
            "pdf_url": None,
            "title": title,
            "subject": (q.get("subjects") or [None])[0],
            "qno": qid,
            "question_type": "single_correct" if q.get("type") == "singleCorrect" else q.get("type"),
            "question_text": strip_html(qhtml),
            "options": options or None,
            "answer_sheet": {
                "status": "embedded_unverified",
                "source": "mathongo_html",
                "official_key_url": None,
                "validation": "not_verified",
                "entries": [{"qno": qid, "answer": {"option": correct_option, "raw": correct_option}}],
            },
            "has_figure": True,
            "has_stem_figure": bool(IMG_RE.search(qhtml)),
            "needs_manual": "pending_gate",
            "diagram_image_urls": image_urls,
            "diagram_assets": assets,
            "solution_text": strip_html((q.get("solution") or {}).get("text") or ""),
        })
    return rows


def cmd_scrape(args: argparse.Namespace) -> None:
    new_rows = []
    for url in args.urls:
        rows = scrape_page(url, args.download_assets)
        print(f"[neet] {url}: {len(rows)} image questions")
        new_rows.extend(rows)
    existing = []
    if OUT_PATH.exists() and not args.replace:
        existing = [json.loads(l) for l in OUT_PATH.read_text().splitlines() if l.strip()]
    new_ids = {r["diagram_question_id"] for r in new_rows}
    all_rows = [r for r in existing if r.get("diagram_question_id") not in new_ids] + new_rows
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in all_rows))
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        "# NEET MathonGo scrape\n\n"
        f"- pages this run: {len(args.urls)}\n"
        f"- image questions this run: {len(new_rows)}\n"
        f"- total image questions: {len(all_rows)}\n"
        f"- assets downloaded this run: {sum(len(r.get('diagram_assets', [])) for r in new_rows)}\n"
    )
    print(f"[neet] wrote {len(new_rows)} new rows ({len(all_rows)} total) to {OUT_PATH}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scrape")
    p.add_argument("urls", nargs="+")
    p.add_argument("--download-assets", action="store_true")
    p.add_argument("--replace", action="store_true")
    p.set_defaults(func=cmd_scrape)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
