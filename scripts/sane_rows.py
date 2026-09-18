#!/usr/bin/env python3
"""I1 — the durable SANE verdict store, keyed by WHAT WAS JUDGED.

    python3 scripts/sane_rows.py --migrate     # build content/sane-rows.json
    python3 scripts/sane_rows.py               # report carry-over vs superseded

A verdict used to be keyed by `(subtopic_key, segment_index)`. Position is not
identity: a precompute re-authors the SEGMENTS, so seg 3 after a sweep can be a
different question. Measured 2026-09-16 after the 29-chapter sweep — of 86
judged rows, 14 still carried the same objective, 59 had changed, and 13 no
longer existed at that index.

The key is now the QUESTION plus the PICTURE:

    objective_sha = sha256(normalised objective text)[:16]
    verdict_key   = f"{objective_sha}:{widget_id}"

`widget_id` is part of it because the same objective judged against a different
widget is a different judgement — "n, reaction_scheme draws a ranking as a
sequence" says nothing about whether a data_table_trend would have been sane.

Normalisation is deliberately brutal (casefold, collapse every run of
non-alphanumerics to one space, strip). A verdict should survive re-punctuation
and re-capitalisation of the same question; it should NOT survive a changed
word, because a changed word is a changed question. Measured: `Identify the
reagents, observations, and LIMITATIONS of Tollens', Fehling's and Benedict's
tests` and `Describe the Tollens' test, its reagent, observation, and the
chemical equation` are the same subtopic and the same index, and the first
wants a table while the second wants a reaction scheme.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import difflib
import re
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

STORE = REPO / "content/sane-rows.json"
SHEET_TO_CHAPTER = {
    "physics 12 ch1": ("physics", 12, "Electric Charges and Fields"),
    "chem 12 ch8": ("chemistry", 12, "Aldehydes, Ketones & Carboxylic Acids"),
    "maths 12 ch8": ("mathematics", 12, "Application of Integrals"),
    "biology 12 Ecosystem": ("biology", 12, "Ecosystem"),
}


def _word_diff(was: str, now: str) -> list[dict]:
    """The words that actually differ, so a reconfirm is a glance."""
    sm = difflib.SequenceMatcher(None, was.split(), now.split())
    return [{"was": " ".join(was.split()[i1:i2]), "now": " ".join(now.split()[j1:j2])}
            for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]


def normalise(text: str) -> str:
    """Casefold, collapse non-alphanumerics, strip. Nothing cleverer.

    Stemming or stopword removal would make two genuinely different questions
    hash the same, which is the failure this key exists to prevent — it is
    better to ask for a re-judgement that was not strictly needed than to carry
    a verdict onto a question nobody read.
    """
    return re.sub(r"[^a-z0-9]+", " ", (text or "").casefold()).strip()


def objective_sha(objective: str) -> str:
    return hashlib.sha256(normalise(objective).encode()).hexdigest()[:16]


def verdict_key(objective: str, widget_id: str | None) -> str:
    return f"{objective_sha(objective)}:{widget_id or 'decline'}"


# `judged_rows()` LIVED HERE and parsed sane_proposals.md. It is gone, with
# every other markdown-reading path, on Raasikh's line of 2026-09-17: the store
# is the only source of truth and the sheet is rendered from it. The one-time
# migration that produced the store is `scripts/sane_migrate_final.py`, kept
# for audit and refusing to run twice.


def live_segments() -> dict:
    """(chapter_name, subtopic_key) -> [segments], from the current plans."""
    from app.db import fetch_all

    chapters = {c["id"]: c for c in fetch_all("chapters", "id,name,subject,class_level")}
    out = {}
    for p in fetch_all("lesson_plans", "chapter_id,subtopic_key,plan_json"):
        ch = chapters.get(p["chapter_id"])
        if ch:
            out[(ch["name"], p["subtopic_key"])] = (p["plan_json"] or {}).get("segments") or []
    return out


#: The sheet's "fired widget / decline" cell -> the widget id that was JUDGED.
#: "reaction_scheme" -> reaction_scheme; "decline → svg `free_body_diagram`" ->
#: decline, because a tier-3 SVG template is not a registry widget and the
#: judgement was about not drawing one.
_WIDGET_CELL = re.compile(r"\b(reaction_scheme|process_flow|xy_plot|field_lines|"
                          r"data_table_trend|circuit_network|molecule_struct|"
                          r"conic_plot|lines_planes_3d|free_body_forces|"
                          r"projectile_motion|labelled_figure)\b")


def judged_widget(cell: str) -> str:
    if re.search(r"\b(decline|no widget|text_only)\b", cell or "", re.I):
        return "decline"
    m = _WIDGET_CELL.search(cell or "")
    return m.group(1) if m else "decline"


def widget_of(segment: dict) -> str | None:
    from app.drona.planner import WIDGET_PAYLOAD_KEY

    pay = segment.get(WIDGET_PAYLOAD_KEY)
    return pay.get("widget") if isinstance(pay, dict) and pay.get("widget") else None


def main() -> int:
    """Report the store's buckets. The migration itself is sane_migrate_final."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--migrate", action="store_true",
                    help="removed — use scripts/sane_migrate_final.py")
    args = ap.parse_args()
    if args.migrate:
        raise SystemExit("--migrate is gone; the store is built once by "
                         "scripts/sane_migrate_final.py and edited in place thereafter")
    doc = json.loads(STORE.read_text())
    print(f"{STORE.name}: {sum(doc['_counts'].values())} rows")
    for k, v in doc["_counts"].items():
        print(f"  {k:<12} {v}")
    return 0




if __name__ == "__main__":
    raise SystemExit(main())
