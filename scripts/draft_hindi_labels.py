#!/usr/bin/env python3
"""Draft the `hi` term for every label in a chapter, for a human to review.

    python3 scripts/draft_hindi_labels.py --chapter <uuid> \
        --out ../monk-learning-mobile/monklearning-mobile/content/illustrations/v1/reports/labels/hi-review.csv

`hi` IS HINGLISH, NOT DEVANAGARI, AND THAT DECIDES THE WHOLE JOB
===============================================================
`lib/widgets/labelled-figure/label-set.ts:42` is explicit:

    /** `hi` is HINGLISH — romanised Latin, not Devanagari. See `LANG_KEY`. */

and `toFigureRecord` maps `text.hi` straight onto the record's `hinglish`
field. The app has exactly two languages, `english` and `hinglish`, and
hinglish is romanised Latin — no Devanagari string exists in either repo
outside two guardrail fixtures. Drafting Devanagari here would therefore be
wrong three times over: it would name a language the product does not ship, it
would be measured against Onest's Latin advances by the label-width model, and
it would trip a width branch that exists only as a liveness guard.

So this asks for ROMANISED Hindi, the way an Indian teacher says the term out
loud in an English-medium classroom.

WHAT THAT MEANS FOR A TERM LIST LIKE THIS ONE
=============================================
Most of these are anatomical Latin — "Malpighian tubule", "Haversian canal",
"conus arteriosus". A teacher speaking Hinglish says those IN ENGLISH; there
is no Hinglish word for Haversian. Translating them anyway produces something
no one says, which is worse than leaving them alone.

So the model is told to return the term UNCHANGED when that is what a teacher
would say, and the CSV records which happened in `source`:

    hinglish-translated   a real Hinglish rendering ("koshika bhitti")
    kept-english          the term a teacher says in English anyway

A row that comes back `kept-english` is a decision, not a failure — and
because `apply_review.py` refuses any set whose `hi` equals its `en`, those
rows are exactly the ones a reviewer must look at and consciously accept.
That refusal is why this file is a REVIEW csv and not an apply step.

NOTHING IS WRITTEN TO ANY LABEL SET. Sets keep `hi == en` until the reviewed
CSV comes back.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DRAFTS = REPO / "content" / "label-drafts"
#: How many terms per model call. Small enough that one bad batch is cheap to
#: re-run, large enough that 151 terms is not 151 round trips.
BATCH = 25

PROMPT = """You give the HINGLISH form of biology diagram labels for an Indian \
JEE/NEET tutoring app.

Hinglish here means ROMANISED LATIN — how an Indian teacher says the term out \
loud in an English-medium classroom. It is NEVER Devanagari script.

Most anatomical terms are Latin and a teacher says them in English: \
"Malpighian tubule", "Haversian canal", "conus arteriosus". For those, return \
the term UNCHANGED. Inventing a Hinglish word nobody says is worse than \
leaving it.

Translate only where a teacher genuinely uses a Hindi word — common body \
parts and everyday structures. Examples: "cell wall" -> "koshika bhitti", \
"blood" -> "khoon", "skin" -> "twacha", "heart" -> "hriday", \
"bone" -> "haddi", "muscle" -> "maanspeshi".

Return STRICT JSON only, no prose:
{"terms": [{"en": "<exact input term>", "hi": "<hinglish or the unchanged term>"}]}

One object per input term, in the same order, with `en` copied EXACTLY."""


def load_terms(chapter_id: str) -> dict[str, list[str]]:
    sys.path.insert(0, str(REPO))
    from app.db import fetch_all  # noqa: PLC0415

    rows = fetch_all("concept_assets", "asset_slug", chapter_id=chapter_id)
    if not rows:
        raise SystemExit(f"REFUSED: no assets for chapter {chapter_id}")
    per: dict[str, list[str]] = {}
    for r in sorted(x["asset_slug"] for x in rows):
        for name in (f"{r}.pointed.json", f"{r}.draft.json"):
            p = DRAFTS / name
            if not p.exists():
                continue
            d = json.loads(p.read_text(encoding="utf-8"))
            terms = [((l.get("text") or {}).get("en") or "").strip()
                     for l in d.get("labels") or []]
            per[r] = [t for t in terms if t]
            break
    return per


def translate(batch: list[str], model: str) -> dict[str, str]:
    from app.drona.models import get_drona_client, model_echo_ok  # noqa: PLC0415

    client = get_drona_client()
    res = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": PROMPT},
                  {"role": "user", "content": json.dumps({"terms": batch}, ensure_ascii=False)}],
        response_format={"type": "json_object"},
        temperature=0.0,
        timeout=120,
        extra_body={"thinking": {"type": "disabled"}},
    )
    # The SAME guard the tutor uses: DeepSeek echoes its canonical id, and an
    # unlisted echo means a different model answered. models.KNOWN_MODEL_ECHOES
    # carries the dated evidence; this refuses rather than trusting the output.
    returned = getattr(res, "model", "") or ""
    if not model_echo_ok(model, returned):
        raise SystemExit(
            f"REFUSED: requested {model!r}, API returned {returned!r}. "
            f"Extend models.KNOWN_MODEL_ECHOES with dated evidence if this is a rename."
        )
    parsed = json.loads(res.choices[0].message.content or "{}")
    out: dict[str, str] = {}
    for row in parsed.get("terms") or []:
        en = str(row.get("en") or "").strip()
        hi = str(row.get("hi") or "").strip()
        if en and hi:
            out[en] = hi
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--model", default=None,
                    help="explicit model string; defaults to the tutor pin")
    args = ap.parse_args()

    sys.path.insert(0, str(REPO))
    from app.drona.models import get_model_name  # noqa: PLC0415

    model = args.model or get_model_name("tutor")
    per = load_terms(args.chapter)
    distinct = sorted({t for terms in per.values() for t in terms})
    print(f"chapter {args.chapter}")
    print(f"model   {model}")
    print(f"{len(per)} sets, {sum(len(v) for v in per.values())} label rows, "
          f"{len(distinct)} distinct terms\n")

    # Translated ONCE per distinct term, not once per row: the same term on two
    # plates must get the same hinglish, or the two figures disagree.
    table: dict[str, str] = {}
    for i in range(0, len(distinct), BATCH):
        chunk = distinct[i:i + BATCH]
        got = translate(chunk, model)
        missing = [t for t in chunk if t not in got]
        if missing:
            print(f"  batch {i // BATCH + 1}: {len(missing)} term(s) came back "
                  f"unanswered and are left for the reviewer: {', '.join(missing[:5])}")
        table.update(got)
        print(f"  batch {i // BATCH + 1}: {len(got)}/{len(chunk)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    kept = translated = 0
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["slug", "term_en", "term_hi", "source"])
        for slug in sorted(per):
            for en in per[slug]:
                hi = table.get(en, en)
                same = hi.strip().lower() == en.strip().lower()
                if same:
                    kept += 1
                else:
                    translated += 1
                w.writerow([slug, en, hi, "kept-english" if same else "hinglish-translated"])

    print(f"\nwrote {args.out}")
    print(f"  {translated} hinglish-translated, {kept} kept-english, "
          f"{translated + kept} rows")
    print("\nNothing was written to any label set. `hi` stays == `en` until this")
    print("CSV comes back reviewed. Note that apply_review.py REFUSES any set")
    print("whose hi equals its en, so every kept-english row above is a row a")
    print("reviewer has to look at and consciously accept.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
