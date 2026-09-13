#!/usr/bin/env python3
"""Upload diagram assets to Cloudflare R2 and emit the `diagram` array (§3).

Dev-time script — no LLM calls. Uploads local crops (and re-hosts ExamSIDE
CDN images) into the public assets bucket with deterministic keys:

    questions/v2/<subject>/<paper_id>/p<page04>/<q>/<idx>-<sha8>.<ext>

and rewrites each row's `diagram` field to the production contract:

    [{"url", "r2_key", "form": "cdn_crop", "page", "region": {x, y, w, h}}]

Assets never live in git. Idempotent: rows whose regions already carry
r2_key are skipped; the same region re-uploads to the same key.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

DATA = ROOT / "data" / "nta_raw"
SOURCES = [
    "diagram_questions.jsonl",
    "examside_diagram_questions.jsonl",
    "examside_diagram_questions_jee_advanced.jsonl",
    "neet_mathongo_questions.jsonl",
]

MIME_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/webp": "webp", "image/svg+xml": "svg"}


def sniff_ext(data: bytes, fallback: str = "png") -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:5].lstrip()[:4] == b"<svg":
        return "svg"
    return fallback


def content_type(ext: str) -> str:
    return {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "svg": "image/svg+xml"}[ext]


def region_from_bbox(bbox) -> dict | None:
    if not bbox or len(bbox) < 4 or bbox[2] is None:
        return None
    try:
        x1, y1, x2, y2 = (float(v) for v in bbox[:4])
    except (TypeError, ValueError):
        return None
    return {"x": round(x1), "y": round(y1), "w": round(x2 - x1), "h": round(y2 - y1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only-ids-file", type=str, default=None,
                    help="upload only rows whose diagram_question_id/question_id is in this file")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    only_ids = None
    if args.only_ids_file:
        only_ids = {l.strip() for l in Path(args.only_ids_file).read_text().splitlines() if l.strip()}

    from app.storage_r2 import get_client, assets_bucket_name

    bucket = assets_bucket_name()
    base = (os.getenv("ASSETS_PUBLIC_BASE_URL") or "").rstrip("/")
    if not base:
        raise SystemExit("ASSETS_PUBLIC_BASE_URL is not set")
    client = get_client()

    def upload_one(key: str, data: bytes, ext: str) -> str:
        client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type(ext))
        return f"{base}/{key}"

    def fetch_url(url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
        return urllib.request.urlopen(req, timeout=60).read()

    stats = {"uploaded": 0, "skipped": 0, "failed": 0, "rows": 0}
    n_done = 0
    for name in SOURCES:
        src = DATA / name
        if not src.exists():
            continue
        rows = []
        for line in src.open():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass

        def row_key(r: dict, idx: int, ext: str, sha8: str) -> str:
            subject = (r.get("subject") or "misc").lower()
            paper = r.get("paper_id") or "unknown"
            page = r.get("page") or 0
            qlabel = r.get("qno") or (r.get("question_id") or "q")
            return f"questions/v2/{subject}/{paper}/p{int(page):04d}/q{qlabel}/{idx:02d}-{sha8}.{ext}"

        changed = False
        src_lock = None
        for row in rows:
            if args.limit and stats["uploaded"] >= args.limit:
                break
            if only_ids is not None:
                rid = row.get("diagram_question_id") or row.get("question_id")
                if rid not in only_ids:
                    continue
            regions = row.get("diagram_regions")
            if not regions:
                # single-region shape: diagram_asset + diagram_bbox
                a = row.get("diagram_asset") or {}
                regions = [{
                    "page": row.get("page"),
                    "bbox": row.get("diagram_bbox"),
                    "asset": a or None,
                }] if a.get("path") else []
            if not regions and row.get("diagram_image_urls"):
                regions = [{"page": None, "bbox": None, "url": u} for u in row["diagram_image_urls"]]
            if not regions:
                continue
            existing = row.get("diagram") or []
            if len(existing) >= len(regions) and all(d.get("r2_key") for d in existing):
                stats["skipped"] += len(regions)
                continue
            diagram = []
            ok = True
            for idx, reg in enumerate(regions):
                if reg.get("r2_key"):
                    diagram.append(reg)
                    stats["skipped"] += 1
                    continue
                try:
                    if reg.get("asset") and (reg["asset"] or {}).get("path"):
                        data = (ROOT / reg["asset"]["path"]).read_bytes()
                    elif reg.get("url"):
                        data = fetch_url(reg["url"])
                    else:
                        continue
                    sha8 = hashlib.sha256(data).hexdigest()[:8]
                    ext = sniff_ext(data, (reg.get("asset") or {}).get("mime", "image/png").split("/")[-1])
                    key = row_key(row, idx, ext, sha8)
                    url = upload_one(key, data, ext)
                    diagram.append({
                        "url": url,
                        "r2_key": key,
                        "form": "cdn_crop",
                        "page": reg.get("page"),
                        "region": region_from_bbox(reg.get("bbox")),
                    })
                    stats["uploaded"] += 1
                except Exception as exc:
                    stats["failed"] += 1
                    ok = False
                    print(f"[r2] FAIL {row.get('diagram_question_id') or row.get('question_id')}: {str(exc)[:100]}")
            if diagram and (ok or len(diagram) == len(regions)):
                row["diagram"] = diagram
                stats["rows"] += 1
                changed = True
            if args.limit and stats["uploaded"] >= args.limit:
                break
        if changed and args.write:
            # lost-update guard: the chain may have rewritten this file while
            # we uploaded for an hour. Re-read it NOW and merge only the
            # `diagram` fields we produced, keyed by row id — everything else
            # on the current rows wins.
            current = []
            for line in src.open():
                line = line.strip()
                if not line:
                    continue
                try:
                    current.append(json.loads(line))
                except Exception:
                    pass
            by_id = {}
            for r in rows:
                rid = r.get("diagram_question_id") or r.get("question_id")
                if rid and r.get("diagram"):
                    by_id[rid] = r["diagram"]
            merged = 0
            for r in current:
                rid = r.get("diagram_question_id") or r.get("question_id")
                if rid in by_id:
                    r["diagram"] = by_id[rid]
                    merged += 1
            src.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in current))
            print(f"[r2] {src.name}: merged diagram arrays into {merged} current rows")
        if args.limit and stats["uploaded"] >= args.limit:
            break

    print(f"[r2] stats: {stats}")
    if not args.write:
        print("[r2] dry run — pass --write to upload and update rows")


if __name__ == "__main__":
    main()
