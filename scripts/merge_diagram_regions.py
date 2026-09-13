#!/usr/bin/env python3
"""Merge same-question multi-region diagram rows (directive §1.3).

Dev-time restructuring script — deterministic, no LLM calls.

The diagram scan emits one row per detected diagram region, so one question
with several figures appears as several rows. Merge key is the normalized
question-text fingerprint — NEVER (paper_id, qno): chapter-wise books restart
numbering per chapter, so same-qno rows are usually *different* questions.

Action per same-fingerprint group (same paper_id):
- keep the row with the best completeness score (numeric values preserved >
  full stem > option count > OCR confidence), per directive §1.4
- fold every group member's diagram into ONE row whose `diagram_regions`
  array carries each region's bbox/page/asset
- record discarded row IDs in `merged_from`

Different-question same-qno rows are left untouched by construction (their
fingerprints differ).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "nta_raw"

NORM_RE = re.compile(r"[^a-z0-9]+")
NUMERIC_VALUE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:Ω|ohm|V|A|W|J|N|kg|m/s|Pa|K|°|%)")


def fingerprint(row: dict) -> str | None:
    n = NORM_RE.sub("", (row.get("question_text") or "").lower())
    if len(n) < 40:
        return None
    return hashlib.sha256(n.encode()).hexdigest()[:20]


def completeness(row: dict) -> tuple:
    text = row.get("question_text") or ""
    numeric_values = len(NUMERIC_VALUE_RE.findall(text))
    opts = row.get("options") or {}
    opt_count = sum(1 for v in opts.values() if str(v).strip()) if isinstance(opts, dict) else 0
    conf = (row.get("ocr") or {}).get("confidence") or 0.0
    return (numeric_values, len(text), opt_count, conf)


def region_of(row: dict) -> dict:
    asset = row.get("diagram_asset") or {}
    return {
        "page": row.get("page"),
        "bbox": row.get("diagram_bbox"),
        "asset": asset or None,
        "confirmation": row.get("confirmation"),
        "ocr": row.get("ocr"),
    }


def row_own_entry(row: dict) -> dict | None:
    entries = (row.get("answer_sheet") or {}).get("entries") or []
    mine = None
    for e in entries:
        if row.get("question_id") and e.get("question_id") == row.get("question_id"):
            mine = e
            break
        if e.get("qno") is not None and e.get("qno") == row.get("qno"):
            mine = e
            break
    if mine is None and len(entries) == 1:
        mine = entries[0]
    return mine


def row_has_key(row: dict) -> bool:
    e = row_own_entry(row)
    if not e:
        return False
    ans = e.get("answer") or {}
    return isinstance(ans, dict) and bool(ans.get("option") or str(ans.get("raw") or "").strip())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    src = DATA / "diagram_questions.jsonl"
    rows = []
    for line in src.open():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass

    groups: dict[tuple, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        fp = fingerprint(r)
        if fp:
            groups[(r.get("paper_id"), fp)].append(i)

    merged_groups = 0
    merged_rows_out = 0
    multi_region_rows = 0
    keep_idx = set()
    drop_idx = set()
    merged_from_map: dict[int, list[str]] = defaultdict(list)

    for (paper_id, fp), idxs in groups.items():
        if len(idxs) < 2:
            continue
        best = max(idxs, key=lambda i: completeness(rows[i]))
        keep_idx.add(best)
        merged_groups += 1
        merged_rows_out += len(idxs) - 1
        for i in idxs:
            if i != best:
                drop_idx.add(i)
                merged_from_map[best].append(rows[i].get("diagram_question_id"))

    out_rows = []
    for i, r in enumerate(rows):
        if i in drop_idx:
            continue
        if i in merged_from_map or i in keep_idx and len(groups.get((r.get("paper_id"), fingerprint(r)) or "", [])) > 1:
            idxs = groups[(r.get("paper_id"), fingerprint(r))]
            regions = [region_of(rows[j]) for j in idxs]
            # dedupe identical regions (same page+bbox)
            seen = set()
            uniq = []
            for reg in regions:
                sig = (reg.get("page"), json.dumps(reg.get("bbox")))
                if sig not in seen:
                    seen.add(sig)
                    uniq.append(reg)
            r["diagram_regions"] = uniq
            if len(uniq) > 1:
                multi_region_rows += 1
            pages = sorted(p for p in (reg.get("page") for reg in uniq) if p is not None)
            if len(pages) >= 2 and pages[-1] - pages[0] > 10:
                # same stem text far apart in one book (question section vs
                # solutions section, or a reused stem) — merged per directive
                # but flagged for the quality gate to review
                r["merged_with_distant_regions"] = True
            if merged_from_map.get(i):
                r["merged_from"] = merged_from_map[i]
            # key inheritance: if the keeper lacks a key but a folded sibling
            # carried one (same text ⇒ same question ⇒ same key), adopt the
            # sibling's matched entry under the keeper's identity
            if not row_has_key(r):
                for j in idxs:
                    if j == i:
                        continue
                    sib_entry = row_own_entry(rows[j])
                    if sib_entry:
                        sib_ans = sib_entry.get("answer") or {}
                        if isinstance(sib_ans, dict) and (
                            sib_ans.get("option") or str(sib_ans.get("raw") or "").strip()
                        ):
                            sheet = dict(r.get("answer_sheet") or {})
                            entries = list(sheet.get("entries") or [])
                            entries.append({
                                "qno": r.get("qno"),
                                "question_id": r.get("question_id"),
                                "answer": sib_ans,
                                "merged_answer_from": rows[j].get("diagram_question_id"),
                            })
                            sheet["entries"] = entries
                            if sheet.get("status") in (None, "unavailable"):
                                sheet["status"] = "embedded_unverified"
                            r["answer_sheet"] = sheet
                            break
            # back-compat: primary asset stays in diagram_asset
        out_rows.append(r)

    print(f"[merge] same-text groups merged: {merged_groups}")
    print(f"[merge] rows folded away: {merged_rows_out}")
    print(f"[merge] rows with >1 diagram region: {multi_region_rows}")
    print(f"[merge] {len(rows)} -> {len(out_rows)} rows")
    if args.write:
        src.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out_rows))
        print(f"[merge] wrote {src}")
    else:
        print("[merge] dry run — pass --write to update")


if __name__ == "__main__":
    main()
