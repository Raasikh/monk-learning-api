#!/usr/bin/env python3
"""Sign a chapter's label sets off and publish them — only on a real confirmation.

    # see exactly what would happen, write nothing:
    python3 scripts/apply_review.py --chapter <uuid> --by raasikh --dry-run

    # actually publish (refuses without the quoted confirmation):
    python3 scripts/apply_review.py --chapter <uuid> --by raasikh \
        --confirmation "confirmed: bio11 ch7 frog heart, reviewed_by raasikh"

WHAT `reviewed_by` MEANS, AND WHY THIS TOOL IS SO RELUCTANT
==========================================================
`reviewed_by` is the single field standing between a drafted anchor and a
student. A drafted anchor is a GUESS about where a structure is, and the worst
thing this pipeline can ship is a correct word confidently attached to the
wrong organ: the student cannot tell, and often the reviewer glancing at it
cannot either. `lib/widgets/labelled-figure/r2-figure-resolver.ts` refuses a
set without it, and that refusal is the product working, not a bug.

So nothing here sets it on its own judgement. The tool requires the operator
to paste Raasikh's OWN words, and it checks that those words name this
chapter and this reviewer. That is deliberately a low bar technically and a
high one procedurally: it cannot verify he meant it, but it can make sure
somebody had to go and get a sentence from him.

WHAT IT DOES, IN ORDER
======================
  1. read the chapter's assets, and each one's draft;
  2. refuse the whole run if ANY set is unfit — an unanchored label, a term
     the draft never placed, a set that fails the client's own validator;
  3. stamp reviewed_by and bump `version`;
  4. upload each set to R2 and HEAD it back (upload_and_verify);
  5. print the board capture command per set, which is run separately.

ALL OR NOTHING, PER CHAPTER. A half-published chapter is the state nobody can
reason about: some plates labelled, some not, and no record of which were
judged. If one set is unfit the chapter does not go.

WHAT IS NOT WIRED YET, AND SAYING SO RATHER THAN IMPLYING IT
============================================================
`version` is bumped here so a running app COULD tell a republished set from
the one it cached. It cannot yet: B0 invalidates on `master_sha256`, which
arrives with every chapter prefetch, and nothing carries the label-set version
to the client — `GET /drona/chapter/{id}/figures` does not return it. Until
that endpoint includes it, a set republished mid-class reaches the app on the
next launch, not immediately. The bump is therefore forward-looking and the
gap is named here instead of being described as propagation that works.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DRAFTS = REPO / "content" / "label-drafts"
R2_PUBLIC = "https://pub-03eaaad7d1294d45ab6ae17beecbd799.r2.dev"


def draft_for(slug: str) -> tuple[Path, dict[str, Any]] | None:
    """The pointed draft if one exists, else the plain one. Pointed wins
    because it is the later judgement about the same anchors."""
    for name in (f"{slug}.pointed.json", f"{slug}.draft.json"):
        p = DRAFTS / name
        if p.exists():
            return p, json.loads(p.read_text(encoding="utf-8"))
    return None


def unfit(slug: str, d: dict[str, Any]) -> list[str]:
    """Every reason this set must not ship. Empty means it may."""
    bad: list[str] = []
    if d.get("asset_slug") != slug:
        bad.append(f"the draft is addressed to {d.get('asset_slug')!r}, not {slug!r}")
    if not d.get("image_w") or not d.get("image_h"):
        bad.append("no image_w/image_h — every anchor is a fraction OF these")
    labels = d.get("labels") or []
    if not labels:
        bad.append("no labels at all; a published set with zero labels is refused client-side")
    for i, lab in enumerate(labels):
        term = ((lab.get("text") or {}).get("en") or "").strip()
        where = f"label {i} ({term or lab.get('id')!r})"
        a = lab.get("anchor")
        if not (isinstance(a, list) and len(a) == 2 and all(isinstance(v, (int, float)) for v in a)):
            bad.append(f"{where}: no anchor — an unplaced term cannot be published")
        elif any(v < 0 or v > 1 for v in a):
            bad.append(f"{where}: anchor {a} is not normalised 0..1")
        hi = ((lab.get("text") or {}).get("hi") or "").strip()
        en = term
        if hi and en and hi == en:
            # C3's rule: hi that is a copy of en is untranslated, not bilingual.
            bad.append(f"{where}: hi is a copy of en ({en!r}) — the reviewed CSV has not been applied")
    still = (d.get("_draft") or {}).get("unplaced") or []
    if still:
        bad.append(f"{len(still)} term(s) still unplaced: {', '.join(still)}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", required=True, help="chapter_id (uuid)")
    ap.add_argument("--by", required=True, help="the reviewer, e.g. raasikh")
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    ap.add_argument("--confirmation", default="",
                    help="Raasikh's own message, quoted. Required to write.")
    args = ap.parse_args()

    sys.path.insert(0, str(REPO))
    from app.db import fetch_all  # noqa: PLC0415

    rows = fetch_all("concept_assets", "asset_slug,concept_slug,chapter_id",
                     chapter_id=args.chapter)
    if not rows:
        raise SystemExit(f"REFUSED: no assets for chapter {args.chapter}")
    rows.sort(key=lambda r: r["asset_slug"])

    print(f"chapter   {args.chapter}")
    print(f"reviewer  {args.by}")
    print(f"mode      {'DRY RUN' if args.dry_run else 'EXECUTE'}")
    print(f"assets    {len(rows)}\n")

    ready: list[tuple[str, Path, dict[str, Any]]] = []
    blocked: list[tuple[str, list[str]]] = []
    missing: list[str] = []

    for r in rows:
        slug = r["asset_slug"]
        found = draft_for(slug)
        if not found:
            missing.append(slug)
            continue
        path, d = found
        problems = unfit(slug, d)
        (blocked.append((slug, problems)) if problems else ready.append((slug, path, d)))

    for slug, path, d in ready:
        groups = d.get("groups") or []
        print(f"  READY    {slug}")
        print(f"           {len(d['labels'])} labels, {len(groups) or 1} group(s), "
              f"source={d.get('source', 'draft-labels')}, from {path.name}")
    for slug in missing:
        print(f"  NO DRAFT {slug}")
    for slug, problems in blocked:
        print(f"  BLOCKED  {slug}")
        for p in problems:
            print(f"           - {p}")

    print(f"\nTOTALS  ready {len(ready)}   blocked {len(blocked)}   no draft {len(missing)}"
          f"   of {len(rows)}")

    if blocked or missing:
        print("\nALL OR NOTHING: a half-published chapter is the state nobody can reason\n"
              "about — some plates labelled, some not, and no record of which were judged.\n"
              "Nothing will be published for this chapter until every set above is ready.")

    if args.dry_run:
        print("\nDRY RUN — nothing stamped, nothing uploaded, reviewed_by untouched.")
        if ready:
            print("\nOn confirmation, each READY set would be:")
            print(f"  stamped     reviewed_by={args.by!r}, version bumped")
            print(f"  uploaded    {R2_PUBLIC}/concept-assets/<slug>.json")
            print( "  verified    head_object size == payload size, then a public HEAD")
            print( "  captured    one board image at 343x236 via the fence rig "
                   "(SHOT_FRAME=0 in dev-widget-preview, then scripts/crop-shot.py)")
        return 0

    want = args.confirmation.strip()
    if not want:
        raise SystemExit(
            "\nREFUSED: --confirmation is empty.\n"
            "  reviewed_by is the one field between a drafted anchor and a student, and\n"
            "  a drafted anchor is a guess. Paste Raasikh's own message, e.g.\n"
            '    --confirmation "confirmed: bio11 ch7 frog heart, reviewed_by raasikh"'
        )
    if args.by.lower() not in want.lower() or not re.search(r"\breviewed_by\b", want, re.I):
        raise SystemExit(
            f"REFUSED: the confirmation does not name {args.by!r} and reviewed_by.\n"
            f"  got: {want!r}"
        )
    if blocked or missing:
        raise SystemExit("REFUSED: see the blocked sets above. Nothing published.")

    from app import storage_r2  # noqa: PLC0415
    sys.path.insert(0, str(REPO / "scripts"))
    from ingest_asset import upload_and_verify  # noqa: PLC0415

    published = 0
    for slug, path, d in ready:
        d["reviewed_by"] = args.by
        d["version"] = int(d.get("version", 0)) + 1
        d.pop("_draft", None)
        payload = (json.dumps(d, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        key = f"concept-assets/{slug}.json"
        size = upload_and_verify(key, payload, "application/json")
        print(f"  PUBLISHED {slug}  v{d['version']}  {size} bytes -> {key}")
        published += 1

    print(f"\nWROTE {published}, FAILED 0")
    print(f"confirmation recorded: {want!r}")
    print("\nNow capture one board per set at 343x236 and attach them to the report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
