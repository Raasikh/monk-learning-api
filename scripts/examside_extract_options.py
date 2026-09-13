#!/usr/bin/env python3
"""Extract ExamSIDE options (text or image) from cached detail pages.

Dev-time script — deterministic HTML parsing, no LLM calls.

ExamSIDE diagram questions often have image options: the detail page renders
``<div class="option" data-option="0"><span class="option-badge">A</span>
<div class="option-content question">...`` where the content is either text
or an ``<img>``. The scraper wrote empty strings for these. This pass fills
``options`` (A-D) with the text when present, and ``option_images`` with the
CDN URLs when the option is an image. Rows whose options are images get
``options_image_only: true`` — the client needs the images, text is not
fabricated from them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "nta_raw"
CACHE = ROOT / "scratch" / "examside_html_cache"

OPTION_START_RE = re.compile(r'<div class="option"[^>]*data-option="(\d)"')
IMG_RE = re.compile(r'<img[^>]+src="([^"]+)"')
TAG_RE = re.compile(r"<[^>]+>")
BADGE_RE = re.compile(r'<span class="option-badge">[A-D]</span>')


def cache_path_for(url: str) -> Path:
    return CACHE / (hashlib.sha256(url.encode()).hexdigest() + ".html")


def extract_options(html: str) -> tuple[dict, dict]:
    """Return (options_text, option_images) keyed A-D.

    Slices between data-option markers (ExamSIDE nests divs, so a balanced-
    tag regex under/over-matches), then reads the first img or the text of
    each option block.
    """
    options: dict[str, str] = {}
    images: dict[str, str] = {}
    starts = [(int(m.group(1)), m.start()) for m in OPTION_START_RE.finditer(html)]
    starts = [(i, s) for i, s in starts if i <= 3]
    for pos, (idx, start) in enumerate(starts):
        letter = "ABCD"[idx]
        end = starts[pos + 1][1] if pos + 1 < len(starts) else start + 4000
        body = html[start:end]
        img = IMG_RE.search(body)
        text = TAG_RE.sub(" ", BADGE_RE.sub("", body))
        text = unescape(re.sub(r"\s+", " ", text)).strip()
        # strip feedback labels that trail/lead the option content
        text = re.sub(r"(?i)\s*(your answer|correct|incorrect)\s*$", "", text).strip()
        text = re.sub(r"(?i)^(correct|incorrect)\s+", "", text).strip()
        if img:
            # image option: text is not fabricated; page chrome around it
            # (feedback labels, "Check Answer" buttons) is not option content
            images[letter] = img.group(1)
        elif text:
            options[letter] = text
    return options, images


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    for src in sorted(DATA.glob("examside_diagram_questions*.jsonl")):
        rows = []
        n_text = n_img = n_cache_miss = n_already = 0
        for line in src.open():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            opts = row.get("options") or {}
            have = sum(1 for v in opts.values() if str(v).strip())
            if have >= 4:
                n_already += 1
                rows.append(row)
                continue
            url = row.get("source_page_url") or ""
            cp = cache_path_for(url)
            if not cp.exists():
                n_cache_miss += 1
                rows.append(row)
                continue
            html = cp.read_text(errors="ignore")
            new_opts, new_imgs = extract_options(html)
            if len(new_opts) >= 4 or len(new_imgs) >= 4:
                merged = {k: new_opts.get(k, "") for k in "ABCD"}
                row["options"] = merged
                if new_imgs:
                    row["option_images"] = new_imgs
                if len(new_imgs) >= 4 and not any(merged.values()):
                    row["options_image_only"] = True
                    n_img += 1
                else:
                    n_text += 1
            else:
                # partial: keep what we got if it fills all four
                if len(new_opts) + len(new_imgs) >= 4:
                    row["options"] = {k: new_opts.get(k, "") for k in "ABCD"}
                    if new_imgs:
                        row["option_images"] = new_imgs
                    n_img += 1
            rows.append(row)
        print(f"[examside-opts] {src.name}: text-filled={n_text} image-options={n_img} "
              f"already-ok={n_already} cache-miss={n_cache_miss} total={len(rows)}")
        if args.write:
            src.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
            print(f"[examside-opts] wrote {src.name}")


if __name__ == "__main__":
    main()
