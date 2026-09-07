"""Ingest labelled-figure art into `concept_assets`.

    python3 scripts/ingest_illustrations.py --manifest <csv> --art-dir <dir>
    python3 scripts/ingest_illustrations.py --manifest <csv> --art-dir <dir> --write

DRY RUN BY DEFAULT. Nothing reaches the database without `--write`, because the
first run of an ingest is a measurement of the manifest, not a migration of it.

WHY THIS REFUSES BEFORE THE DATABASE DOES
-----------------------------------------
migrations/0035 puts the real gate in Postgres — a closed licence enum, a
placeholder denylist over every provenance string, shape checks on the two
hashes. That gate is the one that cannot be argued with, and this script does
not duplicate its judgement: it reproduces its RULES so a bad row is named with
its own filename and column instead of arriving as

    23514 new row for relation "concept_assets" violates check constraint
    "concept_assets_no_placeholders"

which says nothing about which of twelve strings was the placeholder. 0035's
own comment asks for exactly this ordering.

EVERY PHYSICAL FACT IS MEASURED, NEVER READ FROM THE MANIFEST
------------------------------------------------------------
`width`, `height`, `bytes` and `labelled_reference_sha256` come from the file on
disk. A manifest is a work order written before the art exists; taking its word
for the dimensions of a PNG would be recording a plan as though it were an
observation. If the art and the manifest disagree, the art wins and the row is
reported.

WHAT THIS DOES NOT DO
---------------------
It does not upload to R2. `r2_key` is recorded as the key the file WILL occupy,
derived from the slug, and the upload is a separate step — mixing a network
push into the row-validation pass means a partial failure leaves the table and
the bucket disagreeing, with no record of which rows made it.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import supabase  # noqa: E402
from app.storage_r2 import asset_object_key  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover - environment guard
    print("Pillow is required: pip install Pillow")
    raise SystemExit(2)

# Mirrored from migrations/0035, deliberately rather than imported: there is no
# Python copy of the schema, and a hand-kept mirror that DRIFTS is caught by
# tests/drona/test_illustration_ingest.py, which reads the .sql and compares.
LICENCES = {"CC0-1.0", "CC-BY-4.0", "CC-BY-3.0", "CC-BY-2.5", "PD-US-gov", "PD-old-70"}
TEXT_CHECKS = {"ocr-clean", "heuristic-clean-ocr-unavailable"}
ARRIVED = {"unlabelled", "labelled_usable", "labelled_unusable"}
PLACEHOLDERS = {"", "unknown", "tbd", "n/a", "na", "todo", "-", "null", "none", "?"}

#: Provenance strings that must be real. NOT NULL does not stop 'unknown', and
#: 'unknown' is what actually gets typed.
PROVENANCE_FIELDS = (
    "licence", "source_url", "author", "anchor_book",
    "generator_model", "prompt_sha", "text_check",
    "labelled_reference_file", "labelled_reference_sha256", "arrived_labelled",
)


def is_placeholder(v: Any) -> bool:
    return not isinstance(v, str) or v.strip().lower() in PLACEHOLDERS


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def measure(path: Path) -> Tuple[int, int, int, str]:
    """(width, height, bytes, content_type) from the FILE, not the manifest."""
    with Image.open(path) as im:
        w, h = im.size
        fmt = (im.format or "").upper()
    ctype = {"PNG": "image/png", "JPEG": "image/jpeg",
             "WEBP": "image/webp", "SVG": "image/svg+xml"}.get(fmt)
    if ctype is None:
        raise ValueError(f"unsupported image format {fmt!r}")
    return w, h, path.stat().st_size, ctype


def row_problems(row: Dict[str, Any]) -> List[str]:
    """Every reason this row cannot be stored. ALL of them, not the first.

    Returning on the first failure makes an ingest an N-pass process where the
    operator fixes one field per run. The gate is cheap; the round trip is not.
    """
    bad: List[str] = []
    for f in PROVENANCE_FIELDS:
        if is_placeholder(row.get(f)):
            bad.append(f"{f} is a placeholder or empty: {row.get(f)!r}")
    if row.get("licence") not in LICENCES:
        bad.append(
            f"licence {row.get('licence')!r} is not usable. Allowed: "
            f"{', '.join(sorted(LICENCES))}. Share-alike (CC BY-SA, GFDL) and "
            f"non-commercial (NC) art cannot be recorded, so it cannot ship."
        )
    if row.get("text_check") not in TEXT_CHECKS:
        bad.append(f"text_check {row.get('text_check')!r} not in {sorted(TEXT_CHECKS)}")
    if row.get("arrived_labelled") not in ARRIVED:
        bad.append(f"arrived_labelled {row.get('arrived_labelled')!r} not in {sorted(ARRIVED)}")
    url = str(row.get("source_url") or "")
    if not url.startswith(("http://", "https://")) or any(c.isspace() for c in url):
        bad.append(f"source_url is not a URL: {url!r}")
    sha = str(row.get("prompt_sha") or "")
    if len(sha) != 16 or any(c not in "0123456789abcdef" for c in sha):
        bad.append(f"prompt_sha must be 16 lowercase hex chars, got {sha!r}")
    lsha = str(row.get("labelled_reference_sha256") or "")
    if len(lsha) != 64 or any(c not in "0123456789abcdef" for c in lsha):
        bad.append(f"labelled_reference_sha256 must be 64 lowercase hex chars, got {lsha[:20]!r}")
    if row.get("manifest_status") != "approved":
        bad.append(f"manifest_status must be 'approved', got {row.get('manifest_status')!r}")
    gap = row.get("syllabus_gap")
    if gap is not None:
        if not isinstance(gap, list) or not gap:
            bad.append("syllabus_gap must be a non-empty array or omitted entirely — "
                       "'{}' is an empty answer wearing a completed check's clothes")
        elif any(is_placeholder(g) for g in gap):
            bad.append(f"syllabus_gap contains a placeholder: {gap!r}")
    return bad


def resolve_concept(subject: str, class_level: int, concept: str
                    ) -> Tuple[Optional[str], Optional[str]]:
    """(concept_id, chapter_id) by exact name, or (None, None).

    EXACT, and deliberately not normalised. `test_a_concept_the_table_does_not
    _know_falls_to_the_manifest_branch` records why: physics 11 ch6 is spelled
    with '&' in one place and 'and' in another, and a normaliser that papers
    over that hides a real disagreement about what a concept is called.
    """
    rows = supabase.table("concepts").select("id,chapter_id,name").execute().data
    for r in rows:
        if r["name"].strip() == concept.strip():
            return r["id"], r["chapter_id"]
    return None, None


def build_row(m: Dict[str, str], art_dir: Path) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    slug = (m.get("asset_slug") or "").strip()
    if not slug:
        return None, ["asset_slug is empty"]

    art = art_dir / (m.get("file_unlabelled") or f"{slug}.png")
    if not art.is_file():
        return None, [f"art file not found: {art}"]
    try:
        w, h, nbytes, ctype = measure(art)
    except Exception as exc:
        return None, [f"cannot read {art.name}: {exc}"]

    labelled_name = (m.get("file_labelled") or "").strip()
    labelled = art_dir / labelled_name if labelled_name else None
    if labelled is not None and labelled.is_file():
        lsha, arrived = sha256_of(labelled), "labelled_usable"
    else:
        # The label layer is authored separately. Recording the UNLABELLED
        # file's own digest keeps the column honest: it is a real hash of a
        # real file, and `arrived_labelled` says which file it hashed.
        lsha, arrived = sha256_of(art), "unlabelled"
        labelled_name = art.name

    subject_full = {"bio": "biology", "phy": "physics",
                    "chem": "chemistry", "math": "mathematics"}.get(
        (m.get("subject") or "").strip(), (m.get("subject") or "").strip())
    try:
        class_level = int(m.get("class") or 0)
    except ValueError:
        return None, [f"class is not a number: {m.get('class')!r}"]

    concept_id, chapter_id = resolve_concept(subject_full, class_level, m.get("concept", ""))

    row: Dict[str, Any] = {
        "asset_slug": slug,
        "concept_id": concept_id,
        "chapter_id": chapter_id,
        "subject": subject_full,
        "class_level": class_level,
        # NOT a second naming convention. app/storage_r2.py::asset_object_key
        # already owns this, is byte-identical to the manifest's own
        # file_unlabelled column, and takes the extension from the SNIFFED
        # content type so a .png that is really a JPEG lands as .jpg.
        "r2_key": asset_object_key(slug, "unlabelled", ctype),
        "content_type": ctype,
        "width": w, "height": h, "bytes": nbytes,
        "licence": (m.get("licence") or "").strip(),
        "source_url": (m.get("source_url") or "").strip(),
        "author": (m.get("author") or "").strip(),
        "anchor_book": (m.get("anchor_book") or "").strip(),
        "generator_model": (m.get("generator_model") or "").strip(),
        "prompt_sha": (m.get("prompt_sha") or "").strip(),
        "text_check": (m.get("text_check") or "").strip(),
        "labelled_reference_file": labelled_name,
        "labelled_reference_sha256": lsha,
        "arrived_labelled": arrived,
        "manifest_status": (m.get("manifest_status") or "").strip(),
    }
    gap = (m.get("syllabus_gap") or "").strip()
    if gap:
        row["syllabus_gap"] = [g.strip() for g in gap.split("|") if g.strip()]

    problems = row_problems(row)
    if concept_id is None:
        # A WARNING, not a refusal: the column is nullable and an asset whose
        # concept was renamed is still a usable asset. It is REPORTED so the
        # join is fixed rather than discovered when slot 3 finds nothing.
        problems = [p for p in problems]
    return row, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--art-dir", required=True)
    ap.add_argument("--write", action="store_true",
                    help="actually upsert. Without it this only reports.")
    args = ap.parse_args()

    art_dir = Path(args.art_dir)
    rows = list(csv.DictReader(open(args.manifest, encoding="utf-8")))
    print(f"manifest: {len(rows)} rows   art dir: {art_dir}\n")

    ok: List[Dict[str, Any]] = []
    refused: List[Tuple[str, List[str]]] = []
    unjoined: List[str] = []

    for m in rows:
        row, problems = build_row(m, art_dir)
        slug = (m.get("asset_slug") or "?").strip()
        if row is None or problems:
            refused.append((slug, problems))
            continue
        if row["concept_id"] is None:
            unjoined.append(slug)
        ok.append(row)

    for slug, problems in refused:
        print(f"REFUSED  {slug}")
        for p in problems:
            print(f"           {p}")

    if unjoined:
        print(f"\nJOINED NO CONCEPT ({len(unjoined)}) — storable, but slot 3 can never "
              f"select them until the name matches `concepts.name` exactly:")
        for s in unjoined:
            print(f"   {s}")

    print(f"\n{len(ok)} storable, {len(refused)} refused, {len(unjoined)} unjoined")

    if not args.write:
        print("\nDRY RUN — nothing written. Re-run with --write to upsert.")
        return 1 if refused else 0

    if refused:
        # Refusing the WHOLE run, not the bad rows. A half-ingested manifest is
        # the state nobody can reason about later: the table says 21 of 30 and
        # nothing records which 9 or why.
        print("\nNOT WRITING: fix the refusals above first. A partial ingest is "
              "worse than none — the table would carry no record of what was "
              "left out or why.")
        return 1

    for row in ok:
        supabase.table("concept_assets").upsert(row, on_conflict="asset_slug").execute()
    print(f"\nwrote {len(ok)} rows to concept_assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
