#!/usr/bin/env python3
"""Turn a Gemini POINTING file into a label draft, refusing anything it cannot check.

    python3 scripts/draft_anchors_pointed.py \
        --set bio11-ch7-cockroach--morphology-and-digestive-system--a \
        --in  points.json

WHAT THIS IS
============
`draft_labels.py` asks a vision model to LOCATE terms and writes a draft. This
does the same job from a different input: a JSON file of points produced
outside this repo — Raasikh pastes the plate into Gemini in chat and pastes
the answer back — so there is no API key here and no network call to a model.

    [{"term": "compound eye", "x": 0.31, "y": 0.18, "confidence": 0.9}, ...]

x and y are normalised 0..1 of the MASTER image, origin top-left, the same
convention as a label set's `anchor`.

WHAT IT WILL NOT DO, AND THE REASON IS THE WHOLE POINT
=====================================================
It never sets `reviewed_by`. A pointed anchor is a guess about where a
structure is, exactly like a drafted one, and the resolver refuses a set
without a human reviewer (lib/widgets/labelled-figure/r2-figure-resolver.ts).
`source` is recorded as `gemini-pointed` so a reviewer can see which tool
proposed each set and weigh it accordingly. A correct word on the wrong organ
is the worst thing this pipeline can produce, and nothing automated gets to
decide it is right.

It also writes NOTHING when any row fails a check. A partial write would
leave a draft that is half-pointed and half-something-else with no record of
which is which — and a reviewer opening it could not tell.

THE THREE CHECKS
================
1. TERM IS REAL. Every `term` must appear in the concept's `ncert_labels` in
   the manifest — the list a subject author wrote against the book. The model
   is allowed to say WHERE a term is, never WHICH terms a figure needs; those
   are different jobs and only the first is a vision problem.

2. TERM IS VISIBLE IN THIS SUB-FIGURE, per the existing draft. A concept's
   terms are split across its figures: the frog's `lung`, `buccal cavity`,
   `glottis` and `skin` belong to figure b, and the draft for figure a records
   them as `unplaced` with a note saying exactly that. Pointing at one of them
   on figure a would be inventing a structure.

   HONEST AMBIGUITY, FLAGGED RATHER THAN DECIDED: `unplaced` means two
   different things depending on how the draft was made. In an SVG-authored
   draft it means "no leader for it in the drawing", which really does mean
   not in this figure. In a vision-authored draft (`generated_by:
   scripts/draft_labels.py`) it means "the model could not find it", which may
   just be a model failure — and finding those is precisely what pointing is
   FOR. So the strict reading is the default and `--allow-unplaced` opts into
   the other one, per set, with the count reported either way. Do not make it
   the default without deciding what `unplaced` is supposed to mean.

3. POINT IS ON THE PLATE. x, y must land inside the master's content bounding
   box — the non-white region. A point in the white margin names nothing, and
   it is the shape a normalisation mistake takes (pixels pasted as fractions,
   or an axis flipped) — those land outside the ink almost every time.

Every violation is printed with its row index and term. The file is rejected
whole.

OUTPUT
======
  content/label-drafts/<asset_slug>.pointed.json   the draft, reviewed_by absent
  <mobile repo>/content/illustrations/v1/reports/pointed/<slug>.png   overlay

The overlay is a REVIEW SHEET, not a render of the widget: it shows each point
on the master at 900x430 with its term beside it, so a human can see whether
the dots are on the right structures. The widget's own placement is a
different algorithm (lib/widgets/labelled-figure/figure-layout.ts) with its
own tests; reimplementing it here in Python would be two layouts that drift.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
DRAFTS = REPO / "content" / "label-drafts"
#: ONE SOURCE OF TRUTH, and it is the one under version control.
#:
#: This used to default to a copy in ~/Downloads. Two copies of a term list
#: can disagree, and twice they did: adding the blood terms and then the
#: nematocyst terms to the repo manifest left pointing still reading the
#: Downloads copy, so a term that WAS in the list was refused as "not in the
#: concept's ncert_labels". The failure is silent in the worst direction — it
#: looks like a content problem and it is a path problem.
#:
#: The Downloads copy is no longer reachable from here. `--manifest` still
#: exists for a deliberate one-off, but the default cannot drift.
DEFAULT_MANIFEST = (Path(__file__).resolve().parent.parent.parent
                    / "monk-learning-mobile" / "monklearning-mobile"
                    / "content" / "illustrations" / "v1"
                    / "illustration-manifest.csv")
DEFAULT_MOBILE = Path.home() / "Desktop" / "monk-learning-mobile" / "monklearning-mobile"
R2_BASE = "https://pub-03eaaad7d1294d45ab6ae17beecbd799.r2.dev"

#: White-ish is background. Not 255: the masters are chat-transferred PNGs and
#: their paper is not perfectly white, so a strict ==255 test finds a bbox of
#: the whole image and checks nothing.
WHITE_MIN = 247


def concept_slug_of(asset_slug: str) -> str:
    """`...-systems--a` -> `...-systems`. Sub-figure letters are one char."""
    return re.sub(r"--[a-z]$", "", asset_slug)


def terms_for(manifest: Path, concept: str) -> List[str]:
    """The manifest's `ncert_labels` for this concept.

    TOLERATES A TRUNCATED SLUG, because the manifest has one. Measured
    2026-09-12: `bio11-ch6-simple-permanent-tissues--parenchyma--collenchyma-
    and-sclere` is 70 characters and the real concept slug is
    `...-and-sclerenchyma` — the column is cut at 70. An exact match would
    simply not find that row, and the pilot's first three sets are all under
    that concept. So: exact match first, then a UNIQUE prefix match, and a
    refusal if more than one row could be meant. Guessing between two rows is
    how a figure gets the wrong term list.
    """
    rows = list(csv.DictReader(manifest.open(encoding="utf-8")))

    def slug_of(r):
        return (r.get("asset_slug") or "").strip()

    # THE VERSION-CONTROLLED MANIFEST KEYS ROWS BY ASSET, NOT BY CONCEPT.
    # The old Downloads copy carried one row per concept, so an exact match
    # was enough. The repo manifest carries one row per SUB-FIGURE
    # (`...--a`, `...--b`), every one holding the same ncert_labels, and an
    # exact match finds nothing at all. Switching the default to the repo copy
    # is what surfaced this — the term list was right and unreachable.
    exact = [r for r in rows if slug_of(r) == concept]
    members = [r for r in rows if slug_of(r).startswith(concept + "--")]
    # And the truncation case the docstring above describes: the column is cut
    # at 70 characters, so a long concept slug STARTS WITH the stored one.
    truncated = [r for r in rows if slug_of(r) and concept.startswith(slug_of(r))]

    candidates = exact or members or truncated
    if not candidates:
        raise SystemExit(f"REFUSED: no manifest row for concept {concept!r} in {manifest}")

    lists = {tuple(t.strip() for t in (r.get("ncert_labels") or "").split(",") if t.strip())
             for r in candidates}
    if len(lists) > 1:
        # Sub-figures of one concept sharing one term list is the invariant the
        # whole pointing step rests on. Two different lists means somebody
        # edited one row, and guessing which is right is how a figure gets the
        # wrong terms.
        names = ", ".join(slug_of(r) for r in candidates)
        raise SystemExit(
            f"REFUSED: the rows for {concept!r} carry {len(lists)} DIFFERENT "
            f"ncert_labels ({names}). They must agree — fix the manifest."
        )
    return list(next(iter(lists)))


def load_draft(asset_slug: str) -> Dict[str, Any]:
    p = DRAFTS / f"{asset_slug}.draft.json"
    if not p.exists():
        raise SystemExit(
            f"REFUSED: no step-5 draft at {p}. Pointing REFINES a draft — it does "
            f"not create one, because the draft is what says which terms belong to "
            f"this sub-figure at all."
        )
    return json.loads(p.read_text(encoding="utf-8"))


def fetch_art(asset_slug: str, art: Path | None) -> Path:
    if art:
        if not art.exists():
            raise SystemExit(f"REFUSED: --art {art} does not exist")
        return art
    out = Path("/tmp") / f"{asset_slug}.master.png"
    if not out.exists():
        url = f"{R2_BASE}/concept-assets/{asset_slug}.png"
        try:
            # A User-Agent is REQUIRED: the bucket answers curl with 200 and
            # urllib's default agent with 403, so the naive fetch fails on a
            # file that is plainly there.
            req = urllib.request.Request(url, headers={"User-Agent": "monk-learning/pointing"})
            with urllib.request.urlopen(req, timeout=60) as r, out.open("wb") as fh:
                fh.write(r.read())
        except Exception as e:
            raise SystemExit(f"REFUSED: could not fetch the master from {url}: {e}")
    return out


def content_bbox(img) -> Tuple[int, int, int, int]:
    """Bounding box of everything that is not paper.

    Computed from the alpha channel where there is one and from darkness
    otherwise, because the masters are a mix: some are transparent PNGs and
    some are flattened onto near-white paper.
    """
    from PIL import Image  # noqa: PLC0415

    if img.mode in ("RGBA", "LA"):
        alpha = img.getchannel("A")
        box = alpha.getbbox()
        if box:
            return box
    grey = img.convert("L")
    mask = grey.point(lambda v: 255 if v < WHITE_MIN else 0)
    box = mask.getbbox()
    if not box:
        raise SystemExit("REFUSED: the master has no non-white pixels at all")
    return box


def check(points: List[Dict[str, Any]], allowed: List[str], draft: Dict[str, Any],
          bbox: Tuple[int, int, int, int], iw: int, ih: int,
          allow_unplaced: bool) -> List[str]:
    """Every problem, named by row. Empty list means the file is usable."""
    bad: List[str] = []
    allowed_lc = {t.lower(): t for t in allowed}
    known = {}
    for lab in draft.get("labels") or []:
        en = ((lab.get("text") or {}).get("en") or "").strip()
        if en:
            known[en.lower()] = lab
    unplaced = {t.strip().lower() for t in (draft.get("_draft") or {}).get("unplaced") or []}
    x0, y0, x1, y1 = bbox
    seen = set()

    for i, row in enumerate(points):
        where = f"row {i}"
        term = row.get("term")
        if not isinstance(term, str) or not term.strip():
            bad.append(f"{where}: term is missing or not a string")
            continue
        where = f"row {i} ({term!r})"
        t = term.strip().lower()

        if t in seen:
            bad.append(f"{where}: the same term is pointed twice")
        seen.add(t)

        if t not in allowed_lc:
            bad.append(f"{where}: not in the concept's ncert_labels")
        elif t not in known:
            bad.append(f"{where}: in ncert_labels but absent from the step-5 draft, "
                       f"so nothing says it belongs to THIS sub-figure")
        elif t in unplaced and not allow_unplaced:
            bad.append(f"{where}: the draft records it as unplaced — pass "
                       f"--allow-unplaced only if that means 'the model missed it' "
                       f"and not 'it is on another figure of this set'")

        for key in ("x", "y"):
            v = row.get(key)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                bad.append(f"{where}: {key} is not a number")
            elif not (0.0 <= float(v) <= 1.0):
                bad.append(f"{where}: {key}={v} is not normalised 0..1 — pixels?")
        conf = row.get("confidence")
        if conf is not None and (not isinstance(conf, (int, float))
                                 or isinstance(conf, bool)
                                 or not (0.0 <= float(conf) <= 1.0)):
            bad.append(f"{where}: confidence must be a number 0..1 when present")

        if isinstance(row.get("x"), (int, float)) and isinstance(row.get("y"), (int, float)):
            px, py = float(row["x"]) * iw, float(row["y"]) * ih
            if not (x0 <= px <= x1 and y0 <= py <= y1):
                bad.append(
                    f"{where}: ({row['x']:.4f}, {row['y']:.4f}) -> ({px:.0f}, {py:.0f})px "
                    f"is outside the plate's content box "
                    f"({x0},{y0})-({x1},{y1}) — it names paper, not a structure"
                )
    return bad


def overlay(art_path: Path, points: List[Dict[str, Any]], out: Path, slug: str) -> None:
    from PIL import Image, ImageDraw  # noqa: PLC0415

    img = Image.open(art_path).convert("RGB")
    # NATIVE RESOLUTION, NOT 900x430. The sheet used to be drawn at the board's
    # landscape size, which downsampled a 952px master by a third — and at that
    # scale a nucleus is four pixels across, so a dot sitting BESIDE one and a
    # dot sitting ON one look identical. That is the one question this sheet
    # exists to answer, so it is drawn at the master's own size (capped, since
    # the frog plate is 1800px and nobody needs that to check a dot), with the
    # marker and text scaled to match so they stay legible rather than growing
    # into the art.
    CAP = 1400
    scale_up = min(1.0, CAP / max(img.width, img.height))
    aw, ah = int(img.width * scale_up), int(img.height * scale_up)
    W, H = aw + 2 * 40, ah + 2 * 40 + 24
    s = min((W - 80) / img.width, (H - 104) / img.height)
    sw, sh = int(img.width * s), int(img.height * s)
    ox, oy = (W - sw) // 2, 30 + (H - 30 - sh) // 2
    sheet = Image.new("RGB", (W, H), (255, 253, 248))
    sheet.paste(img.resize((sw, sh), Image.LANCZOS), (ox, oy))
    d = ImageDraw.Draw(sheet, "RGBA")

    # THE SHEET CARRIES ITS OWN COORDINATES.
    # Pointing and checking used to be two different pictures: a grid image to
    # read (x, y) off, and this sheet to see where the dot landed. Reading a
    # dense plate off one and judging it on the other cost a correction pass
    # per figure — on the cardiac plate a nucleus read as y=0.53 was actually
    # at 0.476, and nothing showed that until the sheet came back. With the
    # grid drawn here, a dot that missed and the number that would fix it are
    # in the same glance.
    for i in range(21):
        f = i * 0.05
        gx, gy = ox + f * sw, oy + f * sh
        major = i % 2 == 0
        col = (0, 120, 255, 150) if major else (0, 120, 255, 55)
        d.line([(gx, oy), (gx, oy + sh)], fill=col, width=2 if major else 1)
        d.line([(ox, gy), (ox + sw, gy)], fill=col, width=2 if major else 1)
        if major:
            d.text((gx - 8, oy - 13), f"{f:.1f}", fill=(0, 80, 180))
            d.text((ox - 26, gy - 5), f"{f:.1f}", fill=(0, 80, 180))

    # STAGGERED, and sorted left to right so neighbours stagger against each
    # other. The earthworm gut is eleven structures on one horizontal midline,
    # and every pill landed in the same 14pt band — eleven overlapping boxes,
    # none of them readable. The rings were all correct and the sheet could not
    # show it. Three vertical lanes, and a short connector so a pill that moved
    # still says which ring it belongs to.
    LANES = (-19, 0, 19)
    for i, row in enumerate(sorted(points, key=lambda r: float(r["x"]))):
        x = ox + float(row["x"]) * sw
        y = oy + float(row["y"]) * sh
        lane = LANES[i % 3]
        # A ring, not a filled blob: a solid dot HIDES the thing it points at,
        # which on a four-pixel nucleus means the reviewer checks the marker
        # instead of the structure. The centre stays see-through and a single
        # pixel marks the exact point.
        d.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(238, 163, 31), width=3)
        d.ellipse([x - 1, y - 1, x + 1, y + 1], fill=(28, 26, 22))
        term = str(row["term"])
        conf = row.get("confidence")
        text = term if conf is None else f"{term} ({float(conf):.2f})"
        tw = d.textlength(text)
        tx, ty = x + 10, y - 7 + lane
        if tx + tw + 6 > W:
            tx = x - 10 - tw - 6
        # CLAMPED into the sheet. A point near the top edge put its pill half
        # off the canvas and the term was unreadable — on a review sheet whose
        # only job is to be read.
        tx = max(4.0, min(tx, W - tw - 7))
        ty = max(4.0, min(ty, H - 17))
        # TRANSLUCENT. An opaque pill sits next to the ring and covers the
        # structures around it — including, on the cardiac plate, the very
        # nucleus the ring was testing. A review sheet must not hide the thing
        # being reviewed.
        if lane:
            d.line([(x, y), (tx if tx > x else tx + tw, ty + 6)],
                   fill=(160, 155, 145, 200), width=1)
        d.rectangle([tx - 3, ty - 2, tx + tw + 3, ty + 13], fill=(255, 255, 255, 205),
                    outline=(160, 155, 145, 235))
        d.text((tx, ty), text, fill=(28, 26, 22))

    # ASCII only: the default PIL bitmap font has no em dash and drew it as a
    # tofu box in the header of the first sheet.
    d.text((8, 8), f"{slug} - {len(points)} pointed anchors - NOT REVIEWED",
           fill=(120, 115, 105))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)


#: A group is what the board shows at once. Above this the near-anchor
#: placement runs out of clear directions on the narrow shipping frame and
#: `gateLabelSet` starts refusing sets — measured on the frog heart, where
#: twelve labels in one group could not be placed at 340x340, 343x236 or
#: 495x270. Five is the largest group that placed clear there.
MAX_PER_GROUP = 5


def check_groups(rows: list, group_defs: list) -> list[str]:
    """Refuse a grouping the board cannot draw, before anything is written.

    Grouping is not cosmetic. A figure drawn with more labels than fit is not
    a crowded figure, it is a WRONG one — pills land on top of each other and
    on the structures they name. The board therefore shows one group at a time
    with a "2/3" caption saying so, and this is where the count is enforced.
    """
    out: list[str] = []
    declared = {}
    for i, g in enumerate(group_defs):
        if not isinstance(g, dict):
            out.append(f"groups[{i}]: must be an object")
            continue
        gid = str(g.get("id") or "").strip()
        label = str(g.get("label") or "").strip()
        if not gid:
            out.append(f"groups[{i}]: missing id")
        elif gid in declared:
            out.append(f"groups[{i}]: duplicate group id {gid!r}")
        elif not label:
            # A group with no name draws a caption reading " · 2/3", which
            # tells a student they are seeing a subset but not which one.
            out.append(f"groups[{i}] ({gid}): missing label")
        else:
            declared[gid] = label

    used: dict[str, int] = {}
    ungrouped = 0
    for i, r in enumerate(rows):
        gid = str((r or {}).get("group") or "").strip()
        if not gid:
            ungrouped += 1
            continue
        if declared and gid not in declared:
            out.append(f"points[{i}] ({r.get('term')!r}): group {gid!r} is not declared")
        used[gid] = used.get(gid, 0) + 1

    if declared and ungrouped:
        out.append(f"{ungrouped} point(s) carry no group while {len(declared)} "
                   f"group(s) are declared — a label with no group is drawn in "
                   f"every group, which is never what grouping was for")
    for gid, n in sorted(used.items()):
        if n > MAX_PER_GROUP:
            out.append(f"group {gid!r} has {n} labels; the board places at most "
                       f"{MAX_PER_GROUP} clear on the narrow shipping frame")
    if not declared and len(rows) > MAX_PER_GROUP:
        out.append(f"{len(rows)} points and no groups declared; a single group "
                   f"of more than {MAX_PER_GROUP} will be refused by the layout gate")
    for gid in declared:
        if gid not in used:
            out.append(f"group {gid!r} is declared but no point uses it")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", dest="slug", required=True, help="asset_slug, e.g. ...--a")
    ap.add_argument("--in", dest="points", required=True, type=Path)
    ap.add_argument("--art", type=Path, default=None,
                    help="master PNG; fetched from R2 when omitted")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--mobile", type=Path, default=DEFAULT_MOBILE,
                    help="mobile repo root, for the overlay sheet")
    ap.add_argument("--source", default="gemini-pointed",
                    help="who proposed these points, recorded in the draft's "
                         "`source`. Use claude-pointed when Claude read the "
                         "master directly rather than Gemini in chat.")
    ap.add_argument("--allow-unplaced", action="store_true",
                    help="accept terms the draft could not place — read the "
                         "module docstring before using this")
    args = ap.parse_args()

    from PIL import Image  # noqa: PLC0415

    doc = json.loads(args.points.read_text(encoding="utf-8"))
    # Two accepted shapes. The bare array is the original Gemini-in-chat
    # format and still works. The object form adds grouping, which a figure
    # with more than about five visible terms needs — see check_groups.
    if isinstance(doc, list):
        rows, group_defs = doc, []
    elif isinstance(doc, dict):
        rows = doc.get("points") or []
        group_defs = doc.get("groups") or []
    else:
        raise SystemExit("REFUSED: the points file must be a JSON array or object")
    if not isinstance(rows, list) or not rows:
        raise SystemExit("REFUSED: the points file has no points")

    gproblems = check_groups(rows, group_defs)
    if gproblems:
        print(f"REFUSED: {len(gproblems)} grouping problem(s) in {args.points}. "
              f"Nothing written.\n")
        for g in gproblems:
            print(f"  {g}")
        return 1

    concept = concept_slug_of(args.slug)
    allowed = terms_for(args.manifest, concept)
    draft = load_draft(args.slug)
    art_path = fetch_art(args.slug, args.art)
    img = Image.open(art_path)
    iw = int(draft.get("image_w") or img.width)
    ih = int(draft.get("image_h") or img.height)
    if (img.width, img.height) != (iw, ih):
        print(f"  note: master is {img.width}x{img.height}, draft says {iw}x{ih}; "
              f"points are checked against the DRAFT's dimensions, which is what "
              f"anchors are normalised to.")

    bbox = content_bbox(img)
    # Scale the bbox from master pixels to draft dimensions if they differ.
    fx, fy = iw / img.width, ih / img.height
    bbox = (bbox[0] * fx, bbox[1] * fy, bbox[2] * fx, bbox[3] * fy)

    problems = check(rows, allowed, draft, bbox, iw, ih, args.allow_unplaced)
    if problems:
        print(f"REFUSED: {len(problems)} problem(s) in {args.points}. Nothing written.\n")
        for p in problems:
            print(f"  {p}")
        print(f"\n  the concept's ncert_labels: {', '.join(allowed)}")
        return 1

    by_term = {str(r["term"]).strip().lower(): r for r in rows}
    labels = []
    omitted = []
    repointed = 0
    for lab in draft.get("labels") or []:
        en = ((lab.get("text") or {}).get("en") or "").strip()
        hit = by_term.get(en.lower())
        if not hit:
            # OMITTED, NOT KEPT. These drafts carry every term of the CONCEPT
            # on every one of its sub-figures, with placeholder anchors like
            # (0.3, 0.3) — round numbers nobody measured. Keeping an unpointed
            # label would hand the board one of those as though it were a
            # located structure, which is the "correct word on the wrong
            # organ" failure arriving through the back door. A term not
            # visible in THIS sub-figure belongs in `unplaced`, where it
            # states plainly that nobody found it here.
            omitted.append(en)
            continue
        new = dict(lab)
        # ENGLISH IN BOTH LANGUAGES, per Raasikh 2026-09-12. These terms are
        # anatomical Latin and the exam prints them in English, so `hi` is not
        # an untranslated field waiting to be filled — `hi == en` IS the final
        # state, and `validateLabelSet` refuses an empty `hi` outright. Leaving
        # it blank produced 22 sets the layout gate could not even look at.
        text = dict(new.get("text") or {})
        if not str(text.get("hi") or "").strip():
            text["hi"] = text.get("en", "")
        new["text"] = text
        new["anchor"] = [round(float(hit["x"]), 4), round(float(hit["y"]), 4)]
        if hit.get("group"):
            new["group"] = str(hit["group"]).strip()
        if hit.get("confidence") is not None:
            new.setdefault("_point", {})["confidence"] = round(float(hit["confidence"]), 2)
        repointed += 1
        labels.append(new)

    # `english`/`hinglish`, NOT `en`/`hi`. The two key sets are not
    # interchangeable: labels carry `text.en`/`text.hi` on the wire, but a
    # GROUP label is read straight off the record by `stripFor` as
    # `label[lang]` where lang is "english" or "hinglish". Writing the wire
    # keys here produced groups that validated and then threw inside layout.
    groups = [{"id": str(g["id"]).strip(),
               "label": {"english": str(g["label"]).strip(),
                         "hinglish": str(g["label"]).strip()}}
              for g in group_defs]

    # RE-POINTING MUST NOT REWIND THE PUBLISH COUNTER.
    # This rewrites the pointed draft from scratch, and `label_set_version` /
    # `_draft.published` live in that file — so correcting one anchor on an
    # already-published set silently reset it to v0, and the next publish
    # produced "v1" for the second time. Measured 2026-09-13 on the blood
    # plate: the bytes changed, the sha changed, and the version said the
    # object had never been republished. The sha is what the client compares,
    # so nothing broke — but a counter that goes backwards is a counter no
    # one can trust, and the next reader would have believed it.
    prior = {}
    dest_existing = DRAFTS / f"{args.slug}.pointed.json"
    if dest_existing.exists():
        try:
            prior = json.loads(dest_existing.read_text(encoding="utf-8"))
        except Exception:
            prior = {}

    out = {
        "asset_slug": args.slug,
        "image_w": iw,
        "image_h": ih,
        "schema_version": draft.get("schema_version", 1),
        "source": args.source,
        # Carried forward, not recomputed: publication history belongs to the
        # SET, not to this pointing run.
        "label_set_version": int(prior.get("label_set_version") or 0),
        "groups": groups,
        "labels": labels,
        "unplaced": omitted,
        "_draft": {
            "generated_by": "scripts/draft_anchors_pointed.py",
            "model": "gemini (pointed in chat, outside this repo)",
            "points_file": str(args.points),
            "repointed": repointed,
            "omitted_not_visible": omitted,
            **({"published": prior["_draft"]["published"]}
               if isinstance(prior.get("_draft"), dict)
               and prior["_draft"].get("published") else {}),
            "note": "POINTED DRAFT. reviewed_by is deliberately absent: an anchor "
                    "proposed by a model is a guess wherever it came from, and the "
                    "resolver refuses a set without a human reviewer.",
        },
    }
    dest = DRAFTS / f"{args.slug}.pointed.json"
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    sheet = args.mobile / "content" / "illustrations" / "v1" / "reports" / "pointed" / f"{args.slug}.png"
    overlay(art_path, rows, sheet, args.slug)

    print(f"OK  {args.slug}")
    print(f"    {repointed} label(s) pointed from {len(rows)} point(s), "
          f"{len(groups)} group(s)")
    print(f"    omitted as not visible in this sub-figure: {len(omitted)}"
          + (f" ({', '.join(omitted)})" if omitted else ""))
    print(f"    draft   -> {dest}")
    print(f"    overlay -> {sheet}")
    print(f"    reviewed_by is NOT set. Nothing ships until a person opens this.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
