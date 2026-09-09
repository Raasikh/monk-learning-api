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


def accepted_rows(manifest: Path) -> List[Dict[str, str]]:
    """Every ingested row, in manifest order."""
    return [r for r in csv.DictReader(manifest.open(encoding="utf-8"))
            if (r.get("status") or "").strip() == "accepted"]


def draft_one(slug: str, art: Path, terms: List[str], out_dir: Path,
              force: bool = False) -> Dict[str, Any]:
    """One plate, written to disk. Resumable: an existing draft is not redone.

    Resumability is not a nicety at this size — 112 plates is 112 vision calls,
    and a crash at plate 90 that redid the first 89 would cost the run twice.
    """
    out = out_dir / f"{slug}.draft.json"
    if out.is_file() and not force:
        return json.loads(out.read_text(encoding="utf-8"))
    draft = build_draft(slug, art, terms, propose(art, terms))
    out.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    return draft


def summarise(draft: Dict[str, Any], terms: List[str]) -> Dict[str, Any]:
    """The three numbers §5 asks for, per asset.

    DRAFTED / OMITTED / DEFAULTED are three different things and collapsing any
    two of them loses the one fact an author needs:

      drafted    an anchor the model placed on a structure. Still a guess, but
                 a located guess — the editor shows it on the art.
      omitted    the model says the structure is NOT IN THIS FIGURE. For a
                 sub-asset set this is the expected answer for most terms: the
                 concept's label list is shared by every figure in the set, so
                 the earthworm's reproductive terms are legitimately absent
                 from its circulatory plate. An omission is a decision, not a
                 failure.
      defaulted  several terms given the SAME point. The model stopped
                 locating and started defaulting. These are the dangerous ones:
                 a centred anchor looks deliberate. Counted separately AND
                 still counted as drafted, because that is what they are on
                 disk — the point is that they need re-placing first.
    """
    shared = draft["_draft"]["shared_anchors"]
    defaulted = sorted({i for ids in shared.values() for i in ids})
    drafted = [l for l in draft["labels"] if l["anchor"] is not None]
    return {
        "terms": len(terms),
        "drafted": len(drafted),
        "omitted": list(draft["_draft"]["unplaced"]),
        "defaulted": defaulted,
        "reviewed_by": draft.get("reviewed_by", None),
        # Carried through, because "where did this anchor come from" is the
        # first thing a reviewer needs and the summary is what they open. A
        # vision proposal and an anchor read out of a drawing we authored are
        # not the same claim, and the summary dropped that distinction.
        "source": draft.get("source", "vision"),
    }


def cmd_all(args) -> int:
    manifest = Path(args.manifest)
    art_dir = Path(args.dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = accepted_rows(manifest)
    todo, nolabels, noart = [], [], []
    for r in rows:
        slug = r["asset_slug"].strip()
        terms = [t.strip() for t in (r.get("ncert_labels") or "").split(",")
                 if t.strip()]
        art = art_dir / (r.get("file") or f"masters/{slug}.png")
        if not terms:
            nolabels.append(slug)
        elif not art.is_file():
            noart.append(slug)
        else:
            todo.append((slug, art, terms))

    print(f"manifest   {manifest}  ({len(rows)} accepted)")
    print(f"to draft   {len(todo)}")
    if nolabels:
        # NOT drafted with an invented list. The terms come from the work order
        # a subject author wrote; a model asked to decide WHICH terms a figure
        # needs is doing a different job, and not a vision one.
        print(f"no ncert_labels ({len(nolabels)}) — cannot draft, reported:")
        for s in nolabels:
            print(f"    {s}")
    if noart:
        print(f"NO ART ({len(noart)}):")
        for s in noart:
            print(f"    {s}")
    print()

    summary: Dict[str, Dict[str, Any]] = {}
    failed: List[str] = []
    for n, (slug, art, terms) in enumerate(todo, 1):
        try:
            draft = draft_one(slug, art, terms, out_dir, force=args.force)
        except Exception as err:
            failed.append(f"{slug}: {err}")
            print(f"[{n:3}/{len(todo)}] {slug}  FAILED: {err}")
            continue
        s = summarise(draft, terms)
        summary[slug] = s
        print(f"[{n:3}/{len(todo)}] {slug}  "
              f"drafted {s['drafted']}/{s['terms']}  "
              f"omitted {len(s['omitted'])}  defaulted {len(s['defaulted'])}")

    (out_dir / "_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    total_anchors = sum(s["drafted"] for s in summary.values())
    unreviewed = [k for k, s in summary.items() if s["reviewed_by"] is not None]
    print(f"\nsets {len(summary)}   anchors {total_anchors}   "
          f"omitted {sum(len(s['omitted']) for s in summary.values())}   "
          f"defaulted {sum(len(s['defaulted']) for s in summary.values())}")
    if unreviewed:
        print(f"!! {len(unreviewed)} set(s) carry a reviewed_by. This tool must "
              f"never write one: {unreviewed}")
    else:
        print("every set has reviewed_by = NULL, as it must — the resolver "
              "refuses a set without a human name on it.")
    if failed:
        print(f"\nFAILED ({len(failed)}):")
        for f in failed:
            print(f"  {f}")
    return 1 if failed or unreviewed else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    if "--all" in sys.argv:
        ap.add_argument("--all", action="store_true")
        ap.add_argument("--manifest", required=True)
        ap.add_argument("--dir", required=True,
                        help="folder holding masters/, as named in the manifest's `file`")
        ap.add_argument("--out", default="content/label-drafts")
        ap.add_argument("--force", action="store_true",
                        help="redo drafts that already exist")
        return cmd_all(ap.parse_args())
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
