#!/usr/bin/env python3
"""Join official NTA final answer keys into extracted paper artifacts.

Dev-time script — no LLM calls. Deterministic PDF text parsing only.

Each manifest entry may carry ``official_key_url``. The referenced NTA final
answer-key PDFs are cached in ``data/nta_raw/answer_keys/`` (sha256-of-URL
filename + ``.url`` sidecar). Keys come in two families:

- Family A (2022 S2, 2026 S1): Question ID -> small value (1-4 option position
  for MCQ, the numeric value itself for numerical questions, or "Drop").
- Family B (2023 S1/S2, 2024 S1/S2, 2025 S1/S2, 2026 S2): Question ID ->
  Correct Option ID for MCQ (mapped to a letter via the artifact's real
  ``option_ids``); numerical questions still get direct numeric values.

The join is by the exam board's own Question ID — never positional. Parsed
pairs whose question ID does not appear in any of our artifacts are ignored
(this also filters the International column of the 2026 S1 key).

Writes ``answer_sheet = {status: official_verified, ...}`` into each paper
artifact in ``data/nta_raw/papers/`` and prints coverage stats.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "nta_raw"
KEY_DIR = DATA_DIR / "answer_keys"
PAPERS_DIR = DATA_DIR / "papers"

sys.path.insert(0, str(ROOT))
from scripts import extract_nta_papers as nta  # noqa: E402

QID_RE = re.compile(r"^\d{6,}$")
VALUE_RE = re.compile(r"^\d{1,15}$")
VALUE_LIST_RE = re.compile(r"^\d{1,15}(,\d{1,15})*$")


def key_path_for(url: str) -> Path:
    return KEY_DIR / (hashlib.sha256(url.encode()).hexdigest()[:12] + ".pdf")


def parse_key_pdf(path: Path) -> dict[str, str]:
    """Return {question_id: raw_answer} from an NTA final-key text layer.

    Adjacent-token pairing over the whole document: a long digit token is a
    question ID, the immediately following token is its answer when it is a
    number or 'Drop'. Column headers/dates never match QID_RE, and false
    pairs are filtered later by artifact membership.
    """
    fitz = nta._fitz() if hasattr(nta, "_fitz") else __import__("fitz")
    doc = fitz.open(path)
    try:
        text = "\n".join(doc[p].get_text() for p in range(doc.page_count))
    finally:
        doc.close()
    tokens = text.split()
    pairs: dict[str, str] = {}
    i = 0
    while i < len(tokens) - 1:
        tok = tokens[i]
        if QID_RE.match(tok):
            nxt = tokens[i + 1]
            if nxt.lower() == "drop":
                pairs[tok] = nxt
                i += 2
                continue
            # consume a possibly comma-separated list of values, e.g.
            # "6911211907, 6911211908" (NTA accepted two options)
            vals: list[str] = []
            j = i + 1
            while j < len(tokens):
                t = tokens[j]
                core = t.rstrip(",")
                if not VALUE_RE.match(core):
                    break
                if vals and not tokens[j - 1].endswith(","):
                    break  # plain sequence: only the first token is the value
                vals.append(core)
                j += 1
                if not t.endswith(","):
                    break
            if vals:
                pairs[tok] = ",".join(vals)
                i = j
                continue
        i += 1
    return pairs


def resolve_answer(question: dict, raw: str, key_family_hint: str | None) -> dict:
    """Map a raw key value to a normalized answer for one question.

    Follows the repo's embedded-answer shape: ``answer`` is a dict with
    ``raw`` always set, ``option`` (A-D) only for single-letter MCQ answers,
    ``options`` for multi-correct, ``dropped`` for NTA-withdrawn questions.
    """
    if raw.lower() == "drop":
        return {"answer": {"raw": "Drop", "dropped": True}}
    qtype = question.get("question_type") or ""
    option_ids = [str(o) for o in (question.get("option_ids") or [])]
    raw_values = raw.split(",")
    if qtype == "single_correct":
        if all(v in option_ids for v in raw_values):
            letters = sorted("ABCD"[option_ids.index(v)] for v in raw_values)
            ans: dict = {"raw": raw}
            if len(letters) == 1:
                ans["option"] = letters[0]
            else:
                ans["options"] = letters
                ans["multi_correct"] = True
            return {"answer": ans}
        if all(v in {"1", "2", "3", "4"} for v in raw_values):
            letters = sorted("ABCD"[int(v) - 1] for v in raw_values)
            ans = {"raw": raw}
            if len(letters) == 1:
                ans["option"] = letters[0]
                ans["option_index"] = int(raw_values[0])
            else:
                ans["options"] = letters
                ans["multi_correct"] = True
            return {"answer": ans}
        return {"answer": {"raw": raw}, "unresolved_raw": raw}
    # numerical / anything else: the key prints the value directly
    return {"answer": {"raw": raw, "value": raw}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write answer_sheet into artifacts")
    args = ap.parse_args()

    manifest = [e for e in nta.load_manifest() if e.get("official_key_url")]
    by_key_url: dict[str, list[dict]] = {}
    for e in manifest:
        by_key_url.setdefault(e["official_key_url"], []).append(e)

    total_entries = 0
    total_papers_joined = 0
    total_dropped = 0
    total_unresolved = 0
    papers_with_ids = 0

    for url, entries in sorted(by_key_url.items()):
        kpath = key_path_for(url)
        if not kpath.exists():
            print(f"[join] MISSING key file for {url[:90]}")
            continue
        key = parse_key_pdf(kpath)
        print(f"[join] key {kpath.name}: {len(key)} pairs <- {url[:80]}")
        key_qids = set(key)

        for e in entries:
            art_path = PAPERS_DIR / f"{e['paper_id']}.json"
            if not art_path.exists():
                continue
            artifact = json.loads(art_path.read_text())
            questions = artifact.get("questions") or []
            with_qid = [q for q in questions if q.get("question_id")]
            if not with_qid:
                continue
            papers_with_ids += 1
            sheet_entries = []
            for q in with_qid:
                qid = str(q["question_id"])
                if qid not in key_qids:
                    continue
                resolved = resolve_answer(q, key[qid], None)
                entry = {
                    "qno": q.get("qno"),
                    "question_id": qid,
                    **resolved,
                }
                if (resolved.get("answer") or {}).get("dropped"):
                    total_dropped += 1
                if resolved.get("unresolved_raw"):
                    total_unresolved += 1
                sheet_entries.append(entry)
            if not sheet_entries:
                continue
            total_papers_joined += 1
            total_entries += len(sheet_entries)
            if args.write:
                artifact["answer_sheet"] = {
                    "status": "official_verified",
                    "source": "nta_final_key",
                    "key_url": url,
                    "entries": sheet_entries,
                }
                art_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=1))
            print(
                f"  {e['paper_id']}: {len(sheet_entries)}/{len(with_qid)} questions keyed"
            )

    print(
        f"[join] papers with question IDs: {papers_with_ids}; joined: {total_papers_joined}; "
        f"entries: {total_entries}; dropped-by-NTA: {total_dropped}; unresolved: {total_unresolved}"
    )
    if not args.write:
        print("[join] dry run — pass --write to update artifacts")


if __name__ == "__main__":
    main()
