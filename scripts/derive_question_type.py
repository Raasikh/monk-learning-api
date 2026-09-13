#!/usr/bin/env python3
"""Derive question_type for every corpus row (directive §1).

Dev-time script — deterministic, no LLM calls. Rules (in order):

1. Stem carries a match structure (Column I/II, List-I/II, "match the
   following", match table) -> ``match_the_following``.
2. 4 non-empty options (text or image) -> ``single_correct``.
3. A numeric answer value and no usable options -> ``numerical`` and
   ``options`` is set to null (a numerical row with options renders broken
   in the client — the 52-row production defect class).
4. Otherwise: leave unset and flag ``needs_manual: type_underivable``.

Idempotent: rows whose question_type is already set correctly are untouched;
rows whose stored type contradicts the derivation (e.g. numerical with 4
options and a letter key) are corrected and counted.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "nta_raw"
SOURCES = [
    "diagram_questions.jsonl",
    "examside_diagram_questions.jsonl",
    "examside_diagram_questions_jee_advanced.jsonl",
    "neet_mathongo_questions.jsonl",
]

MATCH_RE = re.compile(
    r"(?i)column[\s-]*(?:i{1,2}|1|one)\b.{0,40}column[\s-]*(?:i{2,3}|2|two)\b"
    r"|list[\s-]*(?:i{1,2}|1)\b.{0,40}list[\s-]*(?:i{2,3}|2)\b"
    r"|match\s+(?:the\s+)?(?:following|lists|list[\s-]*i)"
    r"|match\s+list"
)


def usable_options(row: dict) -> int:
    opts = row.get("options")
    n = 0
    if isinstance(opts, dict):
        n = sum(1 for v in opts.values() if str(v).strip())
    imgs = row.get("option_images")
    if isinstance(imgs, dict):
        n = max(n, sum(1 for v in imgs.values() if str(v).strip()))
    return n


def answer_value(row: dict) -> str | None:
    """A numeric answer value from the row's own key entry, if any."""
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
    if not mine:
        return None
    ans = mine.get("answer") or {}
    if not isinstance(ans, dict) or ans.get("dropped"):
        return None
    raw = str(ans.get("value") or ans.get("raw") or "").strip()
    if re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
        return raw
    return None


def derive(row: dict) -> tuple[str | None, dict]:
    text = row.get("question_text") or ""
    n_opts = usable_options(row)
    meta: dict = {}
    if MATCH_RE.search(text):
        return "match_the_following", meta
    if n_opts >= 4:
        return "single_correct", meta
    val = answer_value(row)
    if val is not None:
        meta["correct_value"] = val
        meta["options_null"] = True
        return "numerical", meta
    return None, meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    stats = {"single_correct": 0, "numerical": 0, "match_the_following": 0,
             "underivable": 0, "corrected": 0, "already": 0}
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
        for row in rows:
            new_type, meta = derive(row)
            old_type = row.get("question_type")
            if new_type is None:
                if not old_type:
                    row["needs_manual"] = "type_underivable"
                    stats["underivable"] += 1
                else:
                    stats["already"] += 1
                continue
            stats[new_type] += 1
            if new_type == "numerical":
                row["options"] = None
                row.pop("option_images", None)
                if meta.get("correct_value") is not None:
                    row["correct_value"] = meta["correct_value"]
            if old_type == new_type:
                stats["already"] += 1
            else:
                if old_type:
                    stats["corrected"] += 1
                row["question_type"] = new_type
                row.pop("needs_manual", None) if row.get("needs_manual") == "type_underivable" else None
        if args.write:
            src.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"[qtype] stats: {stats}")
    if not args.write:
        print("[qtype] dry run — pass --write")


if __name__ == "__main__":
    main()
