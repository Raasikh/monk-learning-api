#!/usr/bin/env python3
"""Sample figure-carrying rows for the §3.3 vision attribution check.

Emits scratch/vision_check_sample.jsonl: {id, paper_id, qno, stem, asset_path,
attribution} for a stratified random sample (by source_site) of rows that
still carry a figure after re-attribution. The vision model (the agent
reading this) then answers per row: could this figure plausibly belong to
this question? Pass rate must reach 95% before anything ships.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "nta_raw"
OUT = ROOT / "scratch" / "vision_check_sample.jsonl"

random.seed(20260912)


def main() -> None:
    rows = []
    for line in (DATA / "diagram_questions.jsonl").open():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        assets = []
        a = r.get("diagram_asset") or {}
        if a.get("path") and (ROOT / a["path"]).exists():
            assets.append(a["path"])
        for reg in r.get("diagram_regions") or []:
            p = (reg.get("asset") or {}).get("path")
            if p and (ROOT / p).exists():
                assets.append(p)
        if not assets:
            continue
        rows.append({
            "id": r.get("diagram_question_id"),
            "paper_id": r.get("paper_id"),
            "qno": r.get("qno"),
            "subject": r.get("subject"),
            "source_site": r.get("source_site"),
            "stem": (r.get("question_text") or "")[:600],
            "asset_path": assets[0],
            "attribution": r.get("figure_attribution"),
        })
    by_site: dict[str, list] = defaultdict(list)
    for r in rows:
        by_site[r["source_site"] or "unknown"].append(r)
    sample = []
    per_site = max(6, 50 // max(1, len(by_site)))
    for site, site_rows in sorted(by_site.items()):
        random.shuffle(site_rows)
        sample.extend(site_rows[:per_site])
    random.shuffle(sample)
    sample = sample[:60]
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in sample))
    print(f"[vision-sample] {len(rows)} figure rows -> sampled {len(sample)} "
          f"from {len(by_site)} sources -> {OUT}")


if __name__ == "__main__":
    main()
