#!/usr/bin/env python3
"""Build ExamSIDE/NEET-MathonGo vision-gate batches (item 1 of the closing gap list).

Rows carry remote diagram_image_urls; the fetch pass cached them locally in
scratch/vision_examside_cache/<sha16>.img. This emits judging batches of the
same shape as the PDF-pipeline gate: {id, stem, asset_path, extra_assets}.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "nta_raw"
CACHE = ROOT / "scratch" / "vision_examside_cache"
OUT = ROOT / "scratch" / "vision_batches_examside"
SOURCES = [
    "examside_diagram_questions.jsonl",
    "examside_diagram_questions_jee_advanced.jsonl",
    "neet_mathongo_questions.jsonl",
]
B = 40


def cached(u: str) -> str | None:
    p = CACHE / (hashlib.sha256(u.encode()).hexdigest()[:16] + ".img")
    return str(p) if p.exists() else None


def main() -> None:
    rows = []
    no_local = 0
    for name in SOURCES:
        for idx, line in enumerate((DATA / name).open()):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            urls = r.get("diagram_image_urls") or []
            local = [cached(u) for u in urls[:3]]
            local = [p for p in local if p]
            assets = []
            # neet_mathongo rows may already carry local assets
            for a in r.get("diagram_assets") or []:
                p = (a or {}).get("path") if isinstance(a, dict) else None
                if p and (ROOT / p).exists():
                    assets.append(str(ROOT / p))
            local.extend(assets)
            if not local:
                no_local += 1
                continue
            rows.append({
                "id": r.get("diagram_question_id") or r.get("question_id") or f"{name}:{idx}",
                "stem": (r.get("question_text") or r.get("text") or "")[:500],
                "asset_path": local[0],
                "extra_assets": local[1:4],
            })
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("vbx_*.jsonl"):
        old.unlink()
    for i in range(0, len(rows), B):
        (OUT / f"vbx_{i//B:03d}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows[i:i + B])
        )
    print(f"[vbx] {len(rows)} rows -> {(len(rows) + B - 1) // B} batches in {OUT}; no local image: {no_local}")


if __name__ == "__main__":
    main()
