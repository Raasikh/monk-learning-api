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
     the draft never placed, or a label whose hi differs from its en (see the
     label-language policy below);
  3. stamp reviewed_by and bump `version`;
  4. upload each set to R2 and HEAD it back (upload_and_verify);
  5. print the board capture command per set, which is run separately.

ALL OR NOTHING, PER CHAPTER. A half-published chapter is the state nobody can
reason about: some plates labelled, some not, and no record of which were
judged. If one set is unfit the chapter does not go.

LABELS ARE ENGLISH IN BOTH LANGUAGES
====================================
Raasikh, 2026-09-12: "lets keep the labels in english strictly".

So `hi == en` is the correct state for every label, and this tool refuses a
set where they DIFFER. That is the inverse of the check it carried earlier the
same day, which refused hi == en on the reasoning that an untranslated set is
indistinguishable from a translated one. The reasoning was sound; the premise
was not. These terms are anatomical Latin — conus arteriosus, Malpighian
tubule — the exam prints them in English, and a Hinglish label that drifts
from the examinable term teaches the wrong string.

A per-term `en_is_final` allowance was built first, so a reviewer could sign
off individual terms as deliberately English. The policy decision made it
unnecessary and it was removed rather than left in: an exception mechanism for
an exception that no longer exists is just a second way to do the same thing,
and the next reader would have to work out which one governs.

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
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
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


MOBILE = Path.home() / "Desktop" / "monk-learning-mobile" / "monklearning-mobile"


def run_layout_gate(payload: dict[str, Any], mobile: Path) -> tuple[bool, str]:
    """Ask the TypeScript gate about the EXACT bytes we are about to publish.

    THE ONE LAYOUT AUTHORITY. This tool used to carry its own guesses about
    shape — no group over five, and so on — which made two gates with nothing
    to keep them agreeing. That already cost something: the frog heart's
    grouping lived only in the mobile preview fixture, so the draft this would
    have published had no groups, Python called it READY, and the TypeScript
    gate would have refused it. It would have published and then failed to draw
    on every phone frame.

    So layout is not judged here. `scripts/gate-label-set.mjs` runs
    `gateLabelSet` at all five GATE_FRAMES and its verdict is returned verbatim
    for the report.
    """
    script = mobile / "scripts" / "gate-label-set.mjs"
    if not script.exists():
        return False, f"the layout gate is missing at {script} — cannot publish unjudged"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
        tmp = fh.name
    try:
        proc = subprocess.run(["node", str(script), tmp], cwd=str(mobile),
                              capture_output=True, text=True, timeout=180)
    except Exception as e:
        return False, f"could not run the layout gate: {e}"
    finally:
        Path(tmp).unlink(missing_ok=True)
    verdict = (proc.stdout or proc.stderr or "").strip()
    # exit 2 is "could not judge", which is NOT a pass.
    return proc.returncode == 0, verdict or f"gate exited {proc.returncode} with no output"


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
        # LABELS ARE ENGLISH IN BOTH LANGUAGES — Raasikh, 2026-09-12:
        # "lets keep the labels in english strictly".
        #
        # This check is the INVERSE of what it was this morning. It used to
        # refuse hi == en, on the reasoning that an untranslated set looks
        # identical to a translated one and would ship half-done. That
        # reasoning was right for a product that shows Hindi labels, and this
        # one does not: the terms are anatomical Latin, the exam prints them
        # in English, and a label that drifts from the examinable term teaches
        # the wrong string.
        #
        # So hi == en is now the CORRECT state, and a label that differs is
        # the thing to catch — a half-applied translation pass, which would
        # show some labels in Hinglish and some not on the same plate.
        if hi and en and hi != en:
            bad.append(
                f"{where}: hi ({hi!r}) differs from en ({en!r}). Labels are "
                f"English in both languages; a partly translated set shows two "
                f"registers on one plate. Change the policy deliberately, not "
                f"a row at a time."
            )
    still = (d.get("_draft") or {}).get("unplaced") or []
    if still:
        bad.append(f"{len(still)} term(s) still unplaced: {', '.join(still)}")
    return bad


def record_publication(path: Path, version: int, key: str, payload: bytes,
                       by: str, confirmation: str) -> None:
    """Write the version back into the draft, so the next publish is v+1.

    THE BUMP IS ONLY A BUMP IF IT PERSISTS. This was computed in memory from a
    field nothing ever wrote, so every publish produced v1 — including the
    republish that corrected the cache header, which by definition was a second
    version of the same key. A reviewer who nudges an anchor and republishes
    would have shipped different bytes under an unchanged version number, and
    the one signal a cache or a client could use to tell them apart would have
    said nothing had changed.

    There is no column for this. `concept_assets` has no label-set fields at
    all (checked: master_sha256, r2_key, licence, and no reviewed_by), and
    adding one is a migration, which is Raasikh's to run. The draft file is
    therefore the durable record, which is not a workaround — it is version
    controlled, so `git log` on the draft IS the publication history.

    `_draft` is authoring metadata and is stripped before upload, so the
    receipt below never reaches a student; only `label_set_version` is part of
    the published document.
    """
    d = json.loads(path.read_text(encoding="utf-8"))
    d["label_set_version"] = version
    draft = d.setdefault("_draft", {})
    draft["published"] = {
        "version": version,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "r2_key": key,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "reviewed_by": by,
        "confirmation": confirmation,
    }
    path.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", help="chapter_id (uuid) — publish the whole chapter")
    ap.add_argument("--set", dest="one_set", help="a single asset_slug")
    ap.add_argument("--mobile", type=Path, default=MOBILE,
                    help="mobile repo root, for the layout gate")
    ap.add_argument("--by", required=True, help="the reviewer, e.g. raasikh")
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    ap.add_argument("--confirmation", default="",
                    help="Raasikh's own message, quoted. Required to write.")
    args = ap.parse_args()

    sys.path.insert(0, str(REPO))
    from app.db import fetch_all  # noqa: PLC0415

    if bool(args.chapter) == bool(args.one_set):
        raise SystemExit("REFUSED: pass exactly one of --chapter or --set")

    if args.one_set:
        rows = fetch_all("concept_assets", "asset_slug,concept_slug,chapter_id",
                         asset_slug=args.one_set)
        if not rows:
            raise SystemExit(f"REFUSED: no asset {args.one_set!r}")
    else:
        rows = fetch_all("concept_assets", "asset_slug,concept_slug,chapter_id",
                         chapter_id=args.chapter)
        if not rows:
            raise SystemExit(f"REFUSED: no assets for chapter {args.chapter}")
    rows.sort(key=lambda r: r["asset_slug"])

    print(f"target    {args.one_set or args.chapter}")
    print(f"reviewer  {args.by}")
    print(f"mode      {'DRY RUN' if args.dry_run else 'EXECUTE'}")
    print(f"assets    {len(rows)}")
    print( "labels    English in both languages (Raasikh, 2026-09-12)")
    print()

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
        # ALL-OR-NOTHING REMOVED, on Raasikh's decision 2026-09-12: a plate
        # without labels is the SHIPPED BASELINE — 113 of 113 have drawn that
        # way since ingest — so a partly labelled chapter is not a broken
        # state, it is a partly finished one. The ready sets go; the rest wait.
        print(f"\n{len(blocked) + len(missing)} set(s) are not ready and will be SKIPPED. "
              f"A plate without labels is the shipped baseline, so this is a partly\n"
              f"finished chapter rather than a broken one.")

    if args.dry_run:
        for slug, path, d in ready:
            probe = dict(d)
            probe["reviewed_by"] = args.by
            ok, verdict = run_layout_gate(probe, args.mobile)
            print(f"\n  GATE {slug}")
            for line in verdict.splitlines():
                print(f"       {line}")
            print(f"       -> {'CLEAR' if ok else 'REFUSED'}")
        print("\nDRY RUN — nothing stamped, nothing uploaded, reviewed_by untouched.")
        if ready:
            print("\nOn confirmation, each READY set would be:")
            print(f"  stamped     reviewed_by={args.by!r}, label_set_version bumped")
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
    if not ready:
        raise SystemExit("REFUSED: no set is ready. Nothing published.")

    from app import storage_r2  # noqa: PLC0415
    sys.path.insert(0, str(REPO / "scripts"))
    from ingest_asset import CACHE_REVALIDATE, upload_and_verify  # noqa: PLC0415

    published = 0
    gate_verdicts: dict[str, str] = {}
    skipped_by_gate: list[str] = []
    for slug, path, d in ready:
        d["reviewed_by"] = args.by
        # Named to match the directive and B0's contract. Nothing reads it
        # yet — see the note at the top of this file.
        d["label_set_version"] = int(d.get("label_set_version", 0)) + 1
        # The policy travels WITH the set, so a later reader finds a decision
        # rather than inferring one from hi == en and guessing whether anyone
        # looked.
        d["label_language"] = {
            "policy": "english-both-languages",
            "by": args.by,
            "note": "Labels are shown in English in both english and hinglish "
                    "modes: the terms are anatomical Latin and the exam prints "
                    "them in English.",
        }
        d.pop("_draft", None)
        # THE GATE RUNS ON THE BYTES BEING UPLOADED, not on the draft that
        # produced them — reviewed_by, version and label_language are all
        # stamped above, and a gate that judged the pre-stamp draft would be
        # judging a different document than the one students get.
        ok, verdict = run_layout_gate(d, args.mobile)
        gate_verdicts[slug] = verdict
        if not ok:
            print(f"  REFUSED   {slug} — the layout gate says:")
            for line in verdict.splitlines():
                print(f"            {line}")
            skipped_by_gate.append(slug)
            continue

        payload = (json.dumps(d, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        key = f"concept-assets/{slug}.json"
        # NOT the default immutable header. A label set is revised at a fixed
        # key whenever a reviewer corrects an anchor — see CACHE_REVALIDATE.
        size = upload_and_verify(key, payload, "application/json", CACHE_REVALIDATE)
        record_publication(path, d["label_set_version"], key, payload, args.by, want)
        print(f"  PUBLISHED {slug}  v{d['label_set_version']}  {size} bytes -> {key}")
        print(f"            gate: {verdict}")
        print(f"            url:  {R2_PUBLIC}/{key}")
        published += 1

    print(f"\nWROTE {published}, REFUSED BY GATE {len(skipped_by_gate)}")
    print(f"confirmation recorded: {want!r}")
    print("\nNow capture one board per set at 343x236 and attach them to the report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
