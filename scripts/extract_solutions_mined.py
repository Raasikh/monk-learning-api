#!/usr/bin/env python3
"""Extract per-question solutions from OCR-mined papers (directive §2).

Dev-time script — deterministic, no new OCR calls (reads the Mathpix page
cache written during mining). For mathpix_ocr artifacts the per-question
block contains ``Official Ans. by NTA (X)`` / ``Ans. (X)`` followed by
``Sol.`` and the worked solution. The stem was already captured; this pass
captures the part after the solution marker into ``solution.steps``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from ocr_extract_scanned_papers import (  # noqa: E402
    ESARAL_Q_RE,
    SECTION_HEAD_RE,
)

PAPERS_DIR = ROOT / "data" / "nta_raw" / "papers"
OCR_CACHE = ROOT / "scratch" / "nta_mathpix_cache"

SOL_RE = re.compile(r"(?mi)^\s*(?:Sol\.|Solution\b)")
PLAIN_Q_RE = re.compile(r"(?m)^\s*(\d{1,2})\.\s+(?=\S)")


def cached_text(paper_id: str, max_pages: int = 60) -> str:
    parts = []
    for p in range(1, max_pages + 1):
        f = OCR_CACHE / f"{paper_id}_p{p}.json"
        if not f.exists():
            break
        try:
            parts.append(json.loads(f.read_text()).get("text", ""))
        except Exception:
            break
    return "\n\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    stats = {"papers": 0, "solutions": 0}
    for art_path in sorted(PAPERS_DIR.glob("*.json")):
        art = json.loads(art_path.read_text())
        if art.get("extraction_method") != "mathpix_ocr":
            continue
        pid = art["paper_id"]
        full = cached_text(pid)
        if not full:
            continue
        # split into question blocks by "N. Question ID:" or plain "N."
        matches = list(ESARAL_Q_RE.finditer(full))
        blocks = {}  # qno -> block text
        if matches:
            for i, m in enumerate(matches):
                end = matches[i + 1].start() if i + 1 < len(matches) else len(full)
                blocks[int(m.group(1))] = full[m.start():end]
        else:
            # plain eSaral variant: numbered questions without Question IDs.
            # Section A runs 1..20, Section B restarts at 1 (renumber 21..30).
            plain = list(PLAIN_Q_RE.finditer(full))
            accepted = []  # (effective_qno, match)
            expected = 1
            in_b = False
            for m in plain:
                n = int(m.group(1))
                if not in_b and n == expected:
                    accepted.append((n, m))
                    expected += 1
                elif not in_b and n == 1 and expected > 10:
                    in_b = True
                    accepted.append((21, m))
                    expected = 22
                elif in_b and n == expected - 20:
                    accepted.append((n + 20, m))
                    expected += 1
            for i, (qno, m) in enumerate(accepted):
                end = accepted[i + 1][1].start() if i + 1 < len(accepted) else len(full)
                blocks[qno] = full[m.start():end]
        changed = False
        for q in art.get("questions") or []:
            if q.get("solution"):
                continue
            block = blocks.get(q.get("qno_printed") or q.get("qno"))
            if not block:
                continue
            m = SOL_RE.search(block)
            if not m:
                continue
            sol_text = block[m.end():].strip()
            # drop trailing next-question/page junk already bounded by block end
            if len(sol_text) < 20:
                continue
            steps = [s.strip() for s in re.split(r"\n{2,}", sol_text) if s.strip()]
            q["solution"] = {"steps": steps[:14]}
            q["solution_source"] = "mirror_printed"
            changed = True
            stats["solutions"] += 1
        if changed:
            stats["papers"] += 1
            if args.write:
                art_path.write_text(json.dumps(art, ensure_ascii=False, indent=1))
    print(f"[solutions] stats: {stats}")
    if not args.write:
        print("[solutions] dry run — pass --write")


if __name__ == "__main__":
    main()
