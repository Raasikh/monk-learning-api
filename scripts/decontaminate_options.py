#!/usr/bin/env python3
"""Decontaminate options: answer/solution leaks inside option values (§1).

Dev-time script — deterministic, no LLM calls.

Mirror PDFs print "Official Ans. by NTA (D)" / "Ans. (D)" / "Sol. ..." right
after an option; the option parser swallowed them into the option value.
A student would see the answer and a wall of LaTeX inside an option button.

Protocol per row:
1. HARVEST first: the leaked letter becomes a second, independent key claim
   (compared against the row's stored key — disagreements reported, since one
   of the two extraction paths must be wrong); the Sol. body becomes a
   solution candidate for rows missing one.
2. TRUNCATE each option value at the first leak marker.
3. If fewer than 4 non-empty options remain, quarantine
   ``options_leak_unrecoverable`` — a 3-option row does not ship.
4. Options over ~300 chars with no leak marker are suspect (swallowed the
   next block): truncate at next-question markers, quarantine if still
   unrecoverable.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "nta_raw"
SOURCES = ["diagram_questions.jsonl"]

LEAK_RE = re.compile(r"Official\s+Ans|(?:^|\n)\s*Ans\s*[.:\)]|(?:^|\n)\s*Sol\s*[.:]", re.I)
LETTER_RES = [
    re.compile(r"Official\s+Ans\.?\s+by\s+NTA\s*\(([A-D1-4])\)", re.I),
    re.compile(r"(?:^|\n)\s*Ans\s*[.:]\s*\(\s*([A-D1-4])\s*\)", re.I),
    re.compile(r"(?:^|\n)\s*Ans\s*[.:]\s*([A-D1-4])\b", re.I),
]
SOL_RE = re.compile(r"(?:^|\n)\s*Sol\s*[.:]\s*", re.I)
NEXT_Q_RE = re.compile(r"(?:^|\n)\s*(?:Q\s*)?\d{1,3}\s*[.)]\s|Question\s+Number\s*:", re.I)
LONG_OPT = 300


def harvest_letter(tail: str) -> str | None:
    for rx in LETTER_RES:
        m = rx.search(tail)
        if m:
            v = m.group(1)
            return "ABCD"[int(v) - 1] if v in "1234" else v.upper()
    return None


def row_stored_letter(row: dict) -> str | None:
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
    if not isinstance(ans, dict):
        return None
    if ans.get("option") in ("A", "B", "C", "D"):
        return ans["option"]
    raw = str(ans.get("raw") or "")
    if raw in ("1", "2", "3", "4"):
        return "ABCD"[int(raw) - 1]
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    stats = Counter()
    disagreements = []
    for name in SOURCES:
        src = DATA / name
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
            opts = row.get("options")
            if not isinstance(opts, dict) or not opts:
                continue
            harvested_letter = None
            harvested_solution = None
            leaked = False
            new_opts = {}
            for k, v in opts.items():
                v = str(v)
                m = LEAK_RE.search(v)
                if m:
                    leaked = True
                    tail = v[m.start():]
                    if harvested_letter is None:
                        harvested_letter = harvest_letter(tail)
                    if harvested_solution is None:
                        sm = SOL_RE.search(tail)
                        if sm:
                            sol_body = tail[sm.end():].strip()
                            if len(sol_body) >= 20:
                                harvested_solution = sol_body
                    v = v[: m.start()].strip()
                    stats["options_truncated"] += 1
                elif len(v) > LONG_OPT:
                    nm = NEXT_Q_RE.search(v)
                    if nm and nm.start() > 10:
                        v = v[: nm.start()].strip()
                        stats["long_options_trimmed"] += 1
                    else:
                        stats["long_options_suspect"] += 1
                new_opts[k] = v
            if not leaked and not any(len(str(v)) > LONG_OPT for v in opts.values()):
                continue
            stats["rows_touched"] += 1
            usable = sum(1 for v in new_opts.values() if str(v).strip())
            if leaked and usable < 4:
                row["needs_manual"] = "options_leak_unrecoverable"
                stats["quarantined"] += 1
            else:
                row["options"] = new_opts
            if harvested_letter:
                stats["letters_harvested"] += 1
                stored = row_stored_letter(row)
                if stored and stored != harvested_letter:
                    stats["key_disagreements"] += 1
                    disagreements.append({
                        "id": row.get("diagram_question_id"),
                        "paper": row.get("paper_id"),
                        "stored": stored,
                        "leaked": harvested_letter,
                    })
                    row["key_disagreement"] = {"stored": stored, "leaked": harvested_letter}
                    row["needs_manual"] = "key_disagreement"
                elif stored == harvested_letter:
                    stats["key_agreements"] += 1
                elif not stored:
                    # a key the row didn't have — additional claim, unverified
                    row.setdefault("answer_sheet", {"status": "embedded_unverified", "entries": []})
                    row["answer_sheet"].setdefault("entries", []).append({
                        "qno": row.get("qno"),
                        "question_id": row.get("question_id"),
                        "answer": {"raw": harvested_letter, "option": harvested_letter},
                        "source": "leak_harvest",
                    })
                    stats["keys_gained"] += 1
            if harvested_solution and not (row.get("solution") or {}).get("steps"):
                steps = [s.strip() for s in re.split(r"\n{2,}", harvested_solution) if s.strip()]
                row["solution"] = {"steps": steps[:14]}
                row["solution_source"] = "leak_harvest"
                stats["solutions_gained"] += 1
        if args.write:
            src.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))

    print(f"[decontaminate] {dict(stats)}")
    if disagreements:
        print("[decontaminate] DISAGREEMENTS (stored vs leaked):")
        for d in disagreements[:25]:
            print(f"  {d['id']} {str(d['paper'])[:50]} stored={d['stored']} leaked={d['leaked']}")
    if not args.write:
        print("[decontaminate] dry run — pass --write")


if __name__ == "__main__":
    main()
