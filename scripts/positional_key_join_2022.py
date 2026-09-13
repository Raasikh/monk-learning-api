#!/usr/bin/env python3
"""Positional, self-validated official-key join for ID-less 2022 papers.

Dev-time script — deterministic, no LLM calls.

The eSaral 2022 subject reprints (``esaral_plain`` mined format) carry no
Question IDs, but they print questions in exam order (Section A q1-20, then
Section B q21-30) and they print the official answer per question. The 2022
NTA keys list 90 question IDs per (exam_date, shift) as 3 consecutive
subject blocks of 30, in the exam's own subject order.

For each mined paper we try all 3 blocks of its (date, shift) section and
align the block's 30 key entries to qno 1-30. A block is accepted only when
the key answers agree with the paper's own printed answers on >= MIN_AGREE
of 30 questions — the paper's printed answers validate the positional
assignment end to end. question_ids are then written from the official key,
with the sheet marked official_verified + assignment=positional_block_validated.
Papers with no block reaching the threshold are left untouched.

2022 key formats: June key gives direct letters for MCQ; July key gives
option positions 1-4; both give numeric values for numerical and Drop for
withdrawn questions.
"""

from __future__ import annotations

import argparse
import fitz  # noqa: F401  (pymupdf)
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from join_nta_answer_keys import key_path_for, LETTER_RE  # noqa: E402

PAPERS_DIR = ROOT / "data" / "nta_raw" / "papers"
MIN_AGREE = 28

DATE_HDR_RE = re.compile(r"Exam Date\s*:\s*([\d.\-]+)")
SHIFT_HDR_RE = re.compile(r"Shift\s*:\s*(\w+)")
TOKEN_RE = re.compile(r"^\d{6,}$")


def parse_key_sections(key_path: Path) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """(dd-mm-yyyy, shift) -> ordered [(qid, raw_value)] from the key PDF."""
    doc = fitz.open(key_path)
    sections: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    cur = None
    for pno in range(doc.page_count):
        text = doc[pno].get_text()
        dm = DATE_HDR_RE.search(text)
        sm = SHIFT_HDR_RE.search(text)
        if dm:
            cur = (dm.group(1), (sm.group(1) if sm else "?"))
        toks = text.split()
        i = 0
        while i < len(toks) - 1:
            if TOKEN_RE.match(toks[i]):
                nxt = toks[i + 1]
                if re.fullmatch(r"\d{1,15}", nxt) or LETTER_RE.match(nxt) or nxt.lower() == "drop":
                    sections[cur].append((toks[i], nxt))
                    i += 2
                    continue
            i += 1
    doc.close()
    return sections


def key_letter(raw: str) -> str | None:
    if LETTER_RE.match(raw):
        return raw
    if raw in ("1", "2", "3", "4"):
        return "ABCD"[int(raw) - 1]
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--min-agree", type=int, default=MIN_AGREE)
    args = ap.parse_args()

    man = json.loads((ROOT / "data" / "nta_raw" / "manifest.json").read_text())
    by_key: dict[str, list[dict]] = defaultdict(list)
    for e in man:
        if e.get("official_key_url"):
            by_key[e["official_key_url"]].append(e)

    total_assigned = total_validated = total_failed = 0
    for url, entries in sorted(by_key.items()):
        kpath = key_path_for(url)
        if not kpath.exists() or "2022" not in url:
            continue
        sections = parse_key_sections(kpath)
        for e in entries:
            art_path = PAPERS_DIR / f"{e['paper_id']}.json"
            if not art_path.exists():
                continue
            art = json.loads(art_path.read_text())
            if art.get("extraction_method") != "mathpix_ocr":
                continue
            questions = art.get("questions") or []
            if len(questions) != 30 or any(q.get("question_id") for q in questions):
                continue  # only esaral_plain 30-question papers
            date = e.get("exam_date")
            shift = e.get("shift")
            # key section lookup (date in dd-mm-yyyy)
            dkey = None
            if date:
                y, m, d = date.split("-")
                dkey = (f"{d}.{m}.{y}", None)
            # candidate blocks: the paper's own (date, shift) section first;
            # if absent (the provisional key omits some shift-2 dates), search
            # every section of the key. A spurious 28+/30 agreement against an
            # entire wrong section is combinatorially negligible, so the
            # widened search stays safe.
            candidate_blocks = []
            for (kd, ks), pairs in sorted(sections.items()):
                own = dkey and kd == dkey[0] and (
                    (str(shift) in ("1", "First") and ks in ("1", "First"))
                    or (str(shift) in ("2", "Second") and ks in ("2", "Second"))
                )
                if own:
                    candidate_blocks.insert(0, ((kd, ks), pairs))
                else:
                    candidate_blocks.append(((kd, ks), pairs))
            printed = []
            for q in sorted(questions, key=lambda q: q.get("qno") or 0):
                emb = q.get("embedded_answer") or {}
                printed.append((q.get("question_type"), emb.get("option"), str(emb.get("raw") or "")))

            best = None
            for (kd, ks), pairs in candidate_blocks:
                for bi in range(0, len(pairs) // 30):
                    block = pairs[bi * 30:(bi + 1) * 30]
                    if len(block) < 30:
                        continue
                    agree = 0
                    for (qtype, popt, praw), (qid, kraw) in zip(printed, block):
                        if qtype == "single_correct":
                            if popt and key_letter(kraw) == popt:
                                agree += 1
                        else:
                            if praw and praw == kraw:
                                agree += 1
                    if best is None or agree > best[2]:
                        best = (kd, ks, agree, bi, block)
            if not best or best[2] < args.min_agree:
                print(f"[posjoin] {e['paper_id']}: best block agree={best[2] if best else 0}/30 < {args.min_agree} — skipped")
                total_failed += 1
                continue
            kd, ks, agree, bi, block = best
            for q, (qid, kraw) in zip(sorted(questions, key=lambda q: q.get("qno") or 0), block):
                q["question_id"] = qid
                q["question_id_assignment"] = "positional_block_validated"
            # build the verified sheet from the key
            entries = []
            for q, (qid, kraw) in zip(sorted(questions, key=lambda q: q.get("qno") or 0), block):
                if kraw.lower() == "drop":
                    entries.append({"qno": q.get("qno"), "question_id": qid,
                                    "answer": {"raw": "Drop", "dropped": True}})
                elif q.get("question_type") == "single_correct":
                    entries.append({"qno": q.get("qno"), "question_id": qid,
                                    "answer": {"raw": kraw, "option": key_letter(kraw)}})
                else:
                    entries.append({"qno": q.get("qno"), "question_id": qid,
                                    "answer": {"raw": kraw, "value": kraw}})
            total_assigned += 30
            total_validated += 1
            if args.write:
                art["questions"] = questions
                art["answer_sheet"] = {
                    "status": "official_verified",
                    "source": "nta_final_key",
                    "key_url": url,
                    "assignment": "positional_block_validated",
                    "block_index": bi,
                    "xval_printed_agree": agree,
                    "entries": entries,
                }
                art_path.write_text(json.dumps(art, ensure_ascii=False, indent=1))
            print(f"[posjoin] {e['paper_id']}: block {bi}, agree {agree}/30 -> official_verified")

    print(f"[posjoin] papers validated: {total_validated}; skipped: {total_failed}; ids assigned: {total_assigned}")
    if not args.write:
        print("[posjoin] dry run — pass --write")


if __name__ == "__main__":
    main()
