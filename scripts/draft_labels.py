"""Propose label anchors for one plate, as a DRAFT the anchor editor opens.

    python3 scripts/draft_labels.py --slug bio11-ch16-nephron-structure-and-types \
        --art  ~/Downloads/geminiillustrationworkorder/out/bio11-....png \
        --manifest ~/Downloads/geminiillustrationworkorder/illustration-manifest.csv \
        --out  content/label-drafts/

WHAT THIS IS AND, MORE IMPORTANTLY, WHAT IT IS NOT
==================================================
It is a first pass at WHERE each term sits on the plate, so an author starts
from something to correct rather than from nothing to place. Over ~65 masters
with 10-28 labels each, that is the difference between a week and an afternoon.

It is NOT an authority on where anything is. A vision model looking at a nephron
will place "loop of Henle" somewhere plausible, and plausible-but-wrong is the
worst failure this pipeline can produce: a correct word, confidently attached to
the wrong structure, with nothing about the picture to say so. A student cannot
tell. A reviewer glancing at it may not either.

So THE OUTPUT IS NEVER SHIPPABLE. Every file this writes deliberately omits
`reviewed_by`, and the resolver refuses a set without one
(lib/widgets/labelled-figure/r2-figure-resolver.ts). The only way to ship a
draft is for a person to open it in the anchor editor, look at each anchor
against the art, and type their name. That is the whole design: this tool cannot
promote its own output, and it must not be given a flag that lets it.

THE TERM LIST IS NOT INVENTED EITHER
====================================
Terms come from the manifest's `ncert_labels` for that slug — the list a subject
author already wrote against the book. The model is asked only to LOCATE terms
it is given, never to decide which terms a figure needs. Those are different
jobs and only the first is a vision problem; the second is the work order.

A term the model cannot find is reported as unplaced rather than guessed at, and
lands in the draft with a null anchor so the editor shows it in the tray.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The VISION model and the client that can reach it, from the one place in
# this repo that already does vision. `get_model_name("diagram")` is a
# different lookup entirely — it returns the DeepSeek text model that authors
# tier-3 SVG, and pointing an OpenAI client at that name fails at the API.
from app.snap import MODEL_DIAGRAM, _openai_client  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    print("Pillow is required: pip install Pillow")
    raise SystemExit(2)

SCHEMA_VERSION = 1

SYSTEM = """You locate anatomical and structural terms on a scientific plate.

You are given an image and a list of terms. For EACH term, return the point on
the image that term names, as normalised coordinates: x from 0 (left edge) to 1
(right edge), y from 0 (top edge) to 1 (bottom edge).

Rules:
- Locate ONLY the terms you are given. Never add a term, never rename one.
- The anchor is the STRUCTURE ITSELF, not empty space near it and not where a
  label would read well. Put it on the thing.
- If a term is not visible on this plate, return it with "anchor": null. A null
  is a useful answer. A guess is not: a wrong anchor puts a correct word on the
  wrong structure, and nobody downstream can tell.
- Do not describe the image, do not solve anything, do not comment.

Return JSON: {"labels": [{"term": "<given verbatim>", "anchor": [x, y] | null}]}
"""


def terms_for(manifest: Path, slug: str) -> List[str]:
    """The manifest's own `ncert_labels` for this slug, split on commas."""
    for row in csv.DictReader(manifest.open(encoding="utf-8")):
        if (row.get("asset_slug") or "").strip() == slug:
            raw = (row.get("ncert_labels") or "").strip()
            return [t.strip() for t in raw.split(",") if t.strip()]
    raise SystemExit(f"no row for slug {slug!r} in {manifest}")


def propose(art: Path, terms: List[str]) -> Dict[str, Any]:
    client = _openai_client()

    data = art.read_bytes()
    mime = "image/png" if art.suffix.lower() == ".png" else "image/jpeg"
    data_url = f"data:{mime};base64,{base64.b64encode(data).decode()}"

    res = client.chat.completions.create(
        model=MODEL_DIAGRAM,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": "Terms to locate:\n" + "\n".join(f"- {t}" for t in terms)},
                # `detail: high` for the same reason app/snap.py uses it on a
                # photographed question: a downsampled plate loses exactly the
                # small structures the labels name.
                {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
            ]},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=2000,
    )
    return json.loads(res.choices[0].message.content or "{}")


def slugify(term: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in term.lower())
    return "-".join(p for p in out.split("-") if p) or "label"


def build_draft(slug: str, art: Path, terms: List[str], proposed: Dict[str, Any]) -> Dict[str, Any]:
    with Image.open(art) as im:
        w, h = im.size

    # Keyed by the term AS GIVEN. A model that renamed a term is not answering
    # about that term, and matching loosely would attach its coordinate to a
    # word nobody asked about.
    got = {
        str(p.get("term", "")).strip(): p.get("anchor")
        for p in (proposed.get("labels") or [])
        if isinstance(p, dict)
    }

    labels: List[Dict[str, Any]] = []
    unplaced: List[str] = []
    for t in terms:
        a = got.get(t)
        ok = (
            isinstance(a, list) and len(a) == 2
            and all(isinstance(n, (int, float)) for n in a)
            and all(0.0 <= float(n) <= 1.0 for n in a)
        )
        if not ok:
            unplaced.append(t)
        labels.append({
            "id": slugify(t),
            # `hi` is romanised Hinglish and is left EMPTY on purpose. The model
            # is not asked to translate: a transliteration it invents reads as
            # authored and would be reviewed as if a person wrote it.
            "text": {"en": t, "hi": ""},
            "anchor": [round(float(a[0]), 3), round(float(a[1]), 3)] if ok else None,
            "side": "auto",
        })

    # ANCHORS THAT REPEAT ARE A TELL, not a coincidence.
    #
    # Two different structures cannot occupy one point. When the model returns
    # the same coordinate for several terms — and on a simple plate it returns
    # (0.5, 0.5) for several — it has stopped locating and started defaulting.
    # That is the single most dangerous output this tool can produce, because
    # a centred anchor looks deliberate: it sits on the drawing, the leader
    # reaches it, and only someone who knows the anatomy can see it is wrong.
    #
    # Reported per group of terms that share a point, not counted, because
    # "3 duplicates" does not tell an author which three to re-place first.
    by_point: Dict[str, List[str]] = {}
    for lab in labels:
        if lab["anchor"] is not None:
            by_point.setdefault(f"{lab['anchor'][0]},{lab['anchor'][1]}", []).append(lab["id"])
    suspect = {pt: ids for pt, ids in by_point.items() if len(ids) > 1}

    return {
        "asset_slug": slug,
        "image_w": w,
        "image_h": h,
        "schema_version": SCHEMA_VERSION,
        # NO `reviewed_by`. See the module docstring — this tool cannot promote
        # its own output and must never be given a flag that lets it.
        "labels": labels,
        "_draft": {
            "generated_by": "scripts/draft_labels.py",
            "model": MODEL_DIAGRAM,
            "unplaced": unplaced,
            "shared_anchors": suspect,
            "note": (
                "DRAFT. Every anchor is a guess and must be checked against the "
                "art in the anchor editor. Anchors are null where the model "
                "could not find the term; those show in the editor's tray. "
                "`shared_anchors` lists terms the model gave the SAME point — "
                "two structures cannot share one, so those are defaults rather "
                "than locations and want re-placing first. "
                "Nothing here ships until a person adds reviewed_by."
            ),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--art", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", default="content/label-drafts")
    args = ap.parse_args()

    art = Path(args.art)
    if not art.is_file():
        raise SystemExit(f"no art at {art}")
    terms = terms_for(Path(args.manifest), args.slug)
    if not terms:
        raise SystemExit(f"{args.slug} has no ncert_labels in the manifest — nothing to locate")

    print(f"{args.slug}: locating {len(terms)} terms on {art.name}")
    draft = build_draft(args.slug, art, terms, propose(art, terms))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.slug}.draft.json"
    out.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    placed = sum(1 for l in draft["labels"] if l["anchor"] is not None)
    print(f"  {placed}/{len(terms)} placed -> {out}")
    if draft["_draft"]["shared_anchors"]:
        print("  SHARED ANCHORS — the model defaulted rather than located these:")
        for pt, ids in draft["_draft"]["shared_anchors"].items():
            print(f"    ({pt}): {', '.join(ids)}")
    if draft["_draft"]["unplaced"]:
        # Named, not counted. "6 unplaced" tells an author nothing about which
        # six to go looking for.
        print(f"  unplaced: {', '.join(draft['_draft']['unplaced'])}")
    print("\n  DRAFT ONLY — no reviewed_by. Open it in the anchor editor, check every")
    print("  anchor against the art, and add your name there. The resolver refuses")
    print("  a set without one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
