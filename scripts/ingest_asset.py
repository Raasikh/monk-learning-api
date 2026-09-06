"""Ingest approved illustration masters from a work-order folder into R2 + Postgres.

    # validate the whole manifest — THIS IS THE DEFAULT, nothing is written
    python3 scripts/ingest_asset.py ingest \
        --dir  ~/Downloads/geminiillustrationworkorder/out \
        --manifest ~/Downloads/geminiillustrationworkorder/illustration-manifest.csv \
        --work-order ~/Downloads/geminiillustrationworkorder/gemini-work-order.md \
        --generator-model gemini-3-pro-image

    # actually write
    ... --execute

    # every row still has its object, every object still has its row
    python3 scripts/ingest_asset.py verify
    python3 scripts/ingest_asset.py list

Against today's manifest — 48 rows, all `status=todo` — a correct run ingests
ZERO and reports 48 skipped. That is not a failure and it is not silence; it is
the SKIPPED table at the bottom of the report, itemised by status.


WHAT THIS COMMAND IS FOR
========================
It is the gate on the front of the illustration pipeline. This is what Gemini
output is fed through, and MOST OF WHAT IT DOES IS SAY NO. That is not a side
effect of validation; it is the feature. An asset that gets in without
provenance is one nobody can ever remove, because nobody can prove it needs
removing.

Six provenance failures in this project so far, all one shape — a field that
could be satisfied by a plausible value nobody supplied. prompt_version did not
cover the planner. grounded was always true. topic_hash was never populated.
page_start was hardcoded to 1 across 5,266 rows. Six documents were cited as
reviewed that were never written. source_model named the wrong model.

Every one passed a completeness check while asserting nothing. So this command
is built against THAT shape rather than against forgetfulness:

  * no default for any provenance field, anywhere — not in argparse, not in the
    row builder, not in the migration. `page_start: 1` failed BECAUSE a default
    existed: the field was never missing, so nothing ever complained;
  * a placeholder denylist, because NOT NULL stops `null` and does not stop
    'unknown', and 'unknown' is what actually gets typed;
  * a closed licence enum, so unusable art is not a value-with-a-warning but a
    value that cannot be expressed;
  * a MISSING COLUMN is a hard error naming the column, never "every row is
    missing this field, so skip them all" — see THE MISSING-COLUMN RULE;
  * the text check records WHICH DETECTOR SPOKE, so "nobody really checked" is
    a queryable value rather than a green tick — see scripts/asset_text_probe.py;
  * `syllabus_gap` is left NULL rather than `{}`, because this command has not
    looked — see THE ONE FIELD THIS COMMAND REFUSES TO FILL IN.

The contract is docs/label-layer.md §4 in the mobile repo. This file enforces
it; migrations/0035_concept_assets.sql is the backstop for the path this file
does not own (somebody pasting an INSERT into the Supabase SQL editor).


THE MISSING-COLUMN RULE
=======================
The manifest must carry all fifteen columns. If `licence` is absent from the
header, that is a hard error that names the column and stops the run.

It is worth saying why this needs stating. The natural implementation is
`row.get("licence")`, which returns None, which fails the missing-licence check,
which refuses every row — and the run then reports "48 refused: missing
licence", which LOOKS like a correct, careful refusal. It is not. It cannot
distinguish "48 rows nobody filled in" from "somebody handed us the wrong file",
and those need different responses. A whole column silently absent is the
`topic_hash` failure with the polarity flipped: there, a column existed and was
never populated; here, a column would be expected and never exist, and both
produce a tidy-looking result that answers no question.

So the header is validated before any row is read, and an unexpected EXTRA
column is reported too — a manifest that has grown a column is a manifest whose
producer changed.


THE TEXT CHECK, AND WHY IT IS NOT A TICK
========================================
Step 3 of the spec: verify the unlabelled master contains no text. The detector
and its measured numbers live in scripts/asset_text_probe.py; read that file
before trusting a green line in this one. In summary, measured on synthetic
plates:

    normal horizontal labels               100% detected  (30/30)
    labels overlapping the drawing         100% detected  (30/30)
    rotated text 25-90 degrees              63% detected  (19/30)
    single-character labels ("A", "B")        0% detected  ( 0/30)  BLIND
    large display text (a title)              0% in the strict tier  BLIND *
    clean plates / rows of cells              0% false positives

    * the advisory second tier catches 26/30 of those, and also fires on 30/30
      plates with a regular row of cells, so it warns and never refuses.

NO OCR ENGINE IS INSTALLED ON THIS MACHINE — no tesseract binary, no
pytesseract, and neither is in requirements.txt. So the strict shape heuristic
is all that runs today, and it is blind to exactly two of the things the work
order forbids: a plate number ("42") and a title.

Given that, "the detector did not fire" MUST NOT be recorded as "this plate has
no text". It is recorded as what it is:

    text_check = 'heuristic-clean-ocr-unavailable'

and `--execute` REFUSES to write such a row unless
`--accept-inconclusive-text-check` is passed, which is an explicit, per-run,
recorded acknowledgement rather than a default. `select text_check, count(*)
from concept_assets` then says exactly how many assets were never really
checked. Installing tesseract upgrades new rows to 'ocr-clean' with no other
change, and the old rows keep saying what they were.


THE ONE FIELD THIS COMMAND REFUSES TO FILL IN
=============================================
`syllabus_gap` — the structures the syllabus requires that the art does not
draw — is written as NULL, and NULL here means "nobody has looked yet".

The manifest has `must_show` and `ncert_labels`, which say what the art SHOULD
contain. Neither says what it actually does contain; only a subject author
looking at the plate can say that. Writing `{}` would assert that the check was
done and came back empty, which is precisely the page_start failure, and it
would do it 48 times in one run.

Note this deliberately differs from docs/label-layer.md §4.5, which makes NULL a
hard error. That rule is correct for the FIGURE RECORD, which is written after a
subject author has reviewed the plate. It is wrong at ingest, which happens
before. The column is therefore nullable here and the invariant "not shippable
while syllabus_gap is NULL" belongs to the mobile-side gate, where a human has
actually looked. `verify` counts the NULLs so the backlog is visible.


TWO FILES, ONE ROW
==================
Each figure has `<slug>.png` (the unlabelled master) and `<slug>.labelled.png`.
Only the MASTER is uploaded. The labelled file is Gemini's proof that every
required structure is present and correctly identified; our own bilingual label
layer is drawn over the master at render time (docs/label-layer.md §2), so
shipping Gemini's burnt-in English labels would put two competing label systems
on one image — the exact thing §6.3 rejects.

So the labelled file is VERIFIED TO EXIST and RECORDED BY NAME AND SHA-256
(`labelled_reference_file`, `labelled_reference_sha256`) without being stored.
That keeps one row per figure — the slug stays exactly the manifest's slug, so
the join to illustration-manifest.csv and content/concept-archetypes.csv is
intact — while making "which labelled reference did the author review?"
answerable later. A hash of a file we did not keep is still an identifier; it is
what lets somebody prove the reference they are looking at is the one that was
checked.

`anchor_book` and `licence` stay separate columns. The generated plate is a NEW
work derived from a public-domain anchor, and a derivative of a PD work is not
automatically PD. Collapsing them would let a book title stand in for a licence
nobody stated, which would be the seventh provenance failure and would look
populated.


ORDERING: UPLOAD, VERIFY, THEN INSERT
=====================================
Never the other way round. The two failure modes are not symmetrical.

  insert-then-upload, upload fails  ->  a row whose r2_key points at nothing.
      Invisible: the row is well-formed, passes every constraint, and joins
      correctly. It fails at RENDER TIME, in front of a student, and looks like
      a bug in the widget rather than a bug in the ingest.

  upload-then-insert, insert fails  ->  an object with no row. Costs storage
      and nothing else. Nothing reads R2 by enumeration; the row is the index.
      `verify` finds it, and this command names it loudly on the way out.

So the order is: put_object -> head_object (the object is CONFIRMED present and
the right size before anything is recorded) -> upsert the row.


IDEMPOTENCY
===========
Every ingest in this project has needed at least two attempts, so re-running is
the normal case rather than the error case. The R2 key is deterministic from the
slug, so a re-ingest overwrites the same object; the row is matched on
asset_slug and updated. A run over a partially-ingested manifest finishes the
job and reports what it already had.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import io
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asset_text_probe  # noqa: E402

# ---------------------------------------------------------------------------
# The manifest contract
# ---------------------------------------------------------------------------

# All fifteen. A missing one is a hard error naming the column; see THE
# MISSING-COLUMN RULE in the module docstring.
MANIFEST_COLUMNS = (
    "asset_slug", "subject", "class", "chapter", "concept", "anchor_book",
    "ncert_specimen", "must_show", "ncert_labels", "file_unlabelled",
    "file_labelled", "status", "licence", "source_url", "author",
)

# Only this status is ingested. Everything else is skipped and REPORTED —
# skipped is a category with a count, not silence.
APPROVED_STATUS = "approved"

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

# 2 MiB. Justification, because a cap picked by feel is a cap that gets raised
# by feel:
#
#   Every asset is BUNDLED into the app binary — lib/widgets/CLAUDE.md §3,
#   "never fetch at render time", because a live class renders in airplane mode.
#   So an asset's bytes are paid once per install by every student, not once per
#   view by the interested ones.
#
#   Only the MASTER ships (the labelled reference is not stored), so this work
#   order costs 48 files, not 96: a 96 MiB ceiling, against realistic aged-paper
#   line art at 200-600 KiB giving an expected ~20 MiB. content/
#   concept-archetypes.csv has 146 illustration rows in total, so the ceiling
#   for the whole library is ~292 MiB — already the largest single item in the
#   bundle, and a 4 MiB cap would double it.
#
#   And the cap does a second job: at these dimensions a file over 2 MiB is
#   almost never a better figure. It is a PNG that should have been quantised,
#   or a photograph, or an unprocessed scan. Refusing it catches a production
#   mistake, not a quality choice.
MAX_BYTES = 2 * 1024 * 1024
MIN_BYTES = 1024

# Dimension bounds, from the board arithmetic in docs/label-layer.md §1.3.
#
#   The largest board is 900x430. A 16:10 art — which the work order specifies
#   for all 48 — letterboxed into it is drawn at 688x430 points, which is
#   2064x1290 device pixels at 3x. So ~2000px on the long edge is where the art
#   stops being the limiting factor.
#
#   MIN is 400, not 2000, on purpose: below 400 the art is unusable at EVERY
#   board size and there is no judgement to make, so it is a refusal. Between
#   400 and WARN_LONG_EDGE it is soft, so it warns and lets a human decide.
MIN_DIMENSION = 400
MAX_DIMENSION = 8000
WARN_LONG_EDGE = 1200

# docs/label-layer.md §4.3, unchanged. Closed: no CC-BY-SA-* member and no
# *-NC-* member exists, so share-alike and non-commercial art cannot be
# recorded, let alone shipped.
#
# The measured rule from the 149-figure audit is that the split is by WHO DREW
# IT, not by how good it looks: community-drawn Commons schematics are CC BY-SA
# and viral into a closed-source app; institution-dropped art (OpenStax/CNX, NIH
# BioArt, Berkshire CC0, CDC PHIL, Servier) is CC BY or PD and is usable. The CC
# BY-SA schematics are the BEST-LABELLED art in the audit, which is exactly why
# this is an enum and not a note in a doc.
#
# WIDENING THIS IS A CODE REVIEW, NOT A CONFIG CHANGE, and it is never the way
# to make a manifest row fit.
LICENCE_ENUM = (
    "CC0-1.0",
    "CC-BY-4.0",
    "CC-BY-3.0",
    "CC-BY-2.5",
    "PD-US-gov",
    "PD-old-70",
)

# docs/label-layer.md §4.4. Three-valued because a boolean cannot describe the
# PD plate labelled only "A head, B thorax, C abdomen" — it arrived labelled AND
# is unusable, and those are the two facts a triage queue needs.
ARRIVED_LABELLED_ENUM = ("unlabelled", "labelled_usable", "labelled_unusable")

# NOT NULL stops `null`. It does not stop 'unknown', and 'unknown' is what
# actually gets typed. This list is the one that catches the page_start shape:
# a value that is present, well-formed, and asserts nothing.
PLACEHOLDERS = frozenset(
    {
        "", "-", "–", "—", "?", "??", ".", "..", "...",
        "unknown", "unkown", "tbd", "tba", "todo", "to do", "n/a", "na", "nil",
        "null", "none", "nan", "empty", "blank", "missing", "pending",
        "unclear", "unspecified", "unsourced", "various", "misc",
        "see source", "see above", "see url", "as above", "same as above",
        "public domain", "public domain?", "pd", "cc", "cc?", "free",
        "anon", "anonymous", "unattributed", "uncredited",
        "internet", "google", "web", "online", "archive", "archive.org",
        # Bare 'gemini' / 'ai' name no model and pin no version — the
        # source_model failure exactly. A real model id ('gemini-3-pro-image')
        # is longer than one token and passes.
        "gemini", "ai", "llm", "model", "generated", "generative",
        "x", "xx", "xxx", "test", "example", "placeholder", "foo", "bar",
    }
)

# Raster only. SVG has no reliable intrinsic size for §1.3's normalisation and
# GIF is either animated or a 256-colour degradation of something better.
SNIFFERS: List[Tuple[str, object]] = [
    ("image/png", lambda b: b[:8] == b"\x89PNG\r\n\x1a\n"),
    ("image/jpeg", lambda b: b[:3] == b"\xff\xd8\xff"),
    ("image/webp", lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
]

REFUSED_MAGIC: List[Tuple[str, object, str]] = [
    (
        "GIF",
        lambda b: b[:6] in (b"GIF87a", b"GIF89a"),
        "GIF is refused: it is either animated (the label layer draws a still "
        "frame) or a 256-colour degradation of a better original.",
    ),
    (
        "SVG",
        lambda b: b.lstrip()[:5] == b"<?xml" or b.lstrip()[:4] == b"<svg",
        "SVG is refused: docs/label-layer.md §1.3 normalises label anchors "
        "against the art's INTRINSIC pixel size, and an SVG does not reliably "
        "have one. Rasterise it and ingest the PNG.",
    ),
    (
        "PDF",
        lambda b: b[:5] == b"%PDF-",
        "PDF is refused: this ingests one figure, not a document.",
    ),
    (
        "TIFF",
        lambda b: b[:4] in (b"II*\x00", b"MM\x00*"),
        "TIFF is refused: the app cannot decode it. Convert to PNG.",
    ),
]

# Accepts the manifest's real slugs, INCLUDING the double hyphen that stands in
# for a colon or comma in the concept name:
#
#     bio11-ch7-cockroach--nervous-system-and-reproduction
#     bio11-ch4-phylum-porifera
#
# Measured over all 48 rows: 256 single-hyphen runs, 50 double, none longer,
# none leading or trailing, lengths 25..71. The double hyphen is SIGNIFICANT —
# it is where "Cockroach: Nervous System and Reproduction" lost its colon — so
# it is accepted rather than normalised away. Collapsing it would produce a
# string that no longer matches the filenames Gemini emits, the manifest, or
# content/concept-archetypes.csv, all 48 of which join exactly today.
import re  # noqa: E402

SLUG_RE = re.compile(r"^[a-z0-9]+(-{1,2}[a-z0-9]+)*$")
URL_RE = re.compile(r"^https?://[^\s]+$")

TABLE = "concept_assets"

ROW_COLUMNS = (
    "id,asset_slug,concept_id,chapter_id,subject,class_level,r2_key,"
    "content_type,width,height,bytes,licence,source_url,author,anchor_book,"
    "generator_model,prompt_sha,text_check,labelled_reference_file,"
    "labelled_reference_sha256,arrived_labelled,syllabus_gap,manifest_status,"
    "created_at"
)


class Refusal(Exception):
    """This input is not admissible. Carries the message the operator reads.

    Deliberately not a ValueError: refusing is this command's job, and a
    distinct type keeps a refusal from being confused with a bug in it.
    """


# ---------------------------------------------------------------------------
# Field validation — pure, no network, no database. This is what the tests hit.
# ---------------------------------------------------------------------------


def is_placeholder(value: Optional[str]) -> bool:
    """True for a value that is present and asserts nothing.

    Case-insensitive and whitespace-stripped, because '  Unknown  ' is the same
    non-answer as 'unknown' and the difference is invisible in a terminal.
    """
    if value is None:
        return True
    return value.strip().lower() in PLACEHOLDERS


def require_text(value: Optional[str], field: str, what: str) -> str:
    """A provenance string that is present, non-empty and not a placeholder."""
    if value is None or not value.strip():
        raise Refusal(
            f"{field} is empty.\n"
            f"      {what}\n"
            f"      There is no default for this field, deliberately: a default "
            f"is what turned page_start into 5,266 rows that all said '1' and "
            f"meant nothing."
        )
    if is_placeholder(value):
        raise Refusal(
            f"{field} is {value.strip()!r}, which is a placeholder.\n"
            f"      {what}\n"
            f"      A placeholder satisfies NOT NULL and asserts nothing, which "
            f"is exactly the failure this command exists to stop. Supply the "
            f"real value or leave the row unapproved."
        )
    return value.strip()


def require_url(value: Optional[str], field: str, what: str) -> str:
    url = require_text(value, field, what)
    if not URL_RE.match(url):
        raise Refusal(
            f"{field} is {url!r}, which is not an http(s) URL.\n"
            f"      {what}\n"
            f"      A prose reference ('the archive.org page') passes a NOT NULL "
            f"check and cites nothing."
        )
    return url


def validate_licence(value: Optional[str]) -> str:
    """The closed enum, with the share-alike and NC cases named explicitly."""
    if value is None or not value.strip():
        raise Refusal(
            "licence is empty.\n"
            "      Every asset must carry the licence of THE FILE BEING "
            "SHIPPED. There is no default and no 'assume permissive' path: an "
            "asset whose licence nobody recorded is one nobody can ever prove "
            "we may ship.\n"
            "      Note anchor_book is NOT a substitute. The generated plate is "
            "a new work derived from a public-domain anchor, and a derivative "
            "of a PD work is not automatically PD. Accepting the book title in "
            "place of a licence would look populated and assert nothing — the "
            "seventh provenance failure.\n"
            f"      Allowed: {', '.join(LICENCE_ENUM)}"
        )

    raw = value.strip()
    if is_placeholder(raw):
        raise Refusal(
            f"licence is {raw!r}, which is a placeholder, not a licence.\n"
            f"      'unknown' and a bare 'public domain' both pass NOT NULL and "
            f"tell a future reader nothing about whether this art may be "
            f"shipped.\n"
            f"      Allowed: {', '.join(LICENCE_ENUM)}"
        )

    upper = raw.upper()
    if "SA" in re.split(r"[-_ ]", upper):
        raise Refusal(
            f"licence {raw!r} is share-alike, and share-alike art is not usable "
            f"here.\n"
            f"      Measured rule from the 149-figure audit: community-drawn "
            f"Commons schematics are CC BY-SA and viral into a closed-source "
            f"app; institution-dropped art (OpenStax/CNX, NIH BioArt, "
            f"Berkshire, CDC PHIL, Servier) is CC BY or PD and is usable.\n"
            f"      The CC BY-SA schematics are the best-labelled art in the "
            f"audit. That is why this is an enum and not a warning, and why the "
            f"answer is to re-source rather than to widen the enum.\n"
            f"      Allowed: {', '.join(LICENCE_ENUM)}"
        )
    if "NC" in re.split(r"[-_ ]", upper):
        raise Refusal(
            f"licence {raw!r} is non-commercial, and this is a commercial "
            f"product.\n"
            f"      Note openstax.org now serves CC BY-NC-SA site-wide while "
            f"its older Commons mirrors remain CC BY, because CC grants are "
            f"irrevocable. Record the licence at the MIRROR actually copied.\n"
            f"      Allowed: {', '.join(LICENCE_ENUM)}"
        )

    if raw not in LICENCE_ENUM:
        raise Refusal(
            f"licence {raw!r} is not a member of the closed enum.\n"
            f"      Allowed: {', '.join(LICENCE_ENUM)}\n"
            f"      Widening this list is a code review, not a config change, "
            f"and it is never the way to make a manifest row fit. NCERT figures "
            f"are all-rights-reserved and deliberately have no member here."
        )
    return raw


def validate_slug(slug: str) -> str:
    """Validated, never sanitised — the slug is the join key.

    Quietly rewriting a name would mean the file on disk, the manifest row and
    the database row disagree about the asset's name, and the next person to
    re-ingest from the same directory would not know which one won.
    """
    if not SLUG_RE.match(slug or ""):
        raise Refusal(
            f"asset_slug {slug!r} is not a usable slug.\n"
            f"      Needs lowercase a-z, 0-9, and hyphen runs of one or two, "
            f"e.g. 'bio11-ch7-cockroach--nervous-system-and-reproduction'.\n"
            f"      The DOUBLE hyphen is significant and is preserved — it is "
            f"where a colon or comma in the concept name went, and it is the "
            f"join key into illustration-manifest.csv and "
            f"content/concept-archetypes.csv."
        )
    if not 3 <= len(slug) <= 120:
        raise Refusal(
            f"asset_slug {slug!r} must be 3-120 characters "
            f"(the work order's longest is 71)."
        )
    return slug


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------


def read_manifest(path: str) -> List[Dict[str, str]]:
    """Validate the HEADER first, then return the rows.

    See THE MISSING-COLUMN RULE. A missing column is a hard error naming the
    column, never 48 tidy-looking per-row refusals.
    """
    if not os.path.isfile(path):
        raise Refusal(f"--manifest {path} does not exist.")

    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = list(reader.fieldnames or [])
        rows = [dict(r) for r in reader]

    missing = [c for c in MANIFEST_COLUMNS if c not in header]
    if missing:
        raise Refusal(
            f"{os.path.basename(path)} is missing "
            f"{len(missing)} required column(s): {', '.join(missing)}.\n"
            f"  Header found: {', '.join(header) or '(empty)'}\n"
            f"  This is a hard error and not a per-row refusal ON PURPOSE. If "
            f"the licence column is absent, every row 'has no licence' and the "
            f"run would report a tidy '{len(rows)} refused: missing licence' "
            f"that cannot tell 'nobody filled these in' from 'you were handed "
            f"the wrong file'. Those need different responses.\n"
            f"  Fix the manifest; do not fix the rows."
        )

    extra = [c for c in header if c not in MANIFEST_COLUMNS]
    if extra:
        sys.stderr.write(
            f"NOTE: {os.path.basename(path)} has {len(extra)} column(s) this "
            f"command does not know: {', '.join(extra)}. Ignored, but a "
            f"manifest that has grown a column is a manifest whose producer "
            f"changed — check that this one still means what it did.\n"
        )

    if not rows:
        raise Refusal(f"{os.path.basename(path)} has a valid header and no rows.")
    return rows


def prompt_sha(work_order_path: str) -> str:
    """sha256 of the work order, first 16 hex — the prompt that produced the art.

    This is the analogue of planner_prompt_hash, and it is deliberately a hash
    of THE ACTUAL FILE rather than a version string somebody types.
    `prompt_version` failed because it was a sha over all prompts: it moved when
    an unrelated prompt moved and stayed still when the planner changed. A hash
    over exactly the document that specifies these 48 figures moves when, and
    only when, that document moves.

    What it does NOT cover, said plainly rather than left to be assumed: the
    per-figure conversation with the model, any retry or reroll, and the model's
    own version. The model is recorded separately in generator_model.
    """
    if not os.path.isfile(work_order_path):
        raise Refusal(
            f"--work-order {work_order_path} does not exist.\n"
            f"  It is hashed into every row as the prompt that produced the "
            f"art. Without it a row cannot say which specification it was made "
            f"against, which is the prompt_version failure."
        )
    with open(work_order_path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# File validation
# ---------------------------------------------------------------------------


def sniff_content_type(data: bytes) -> str:
    """The real format, from the file HEADER. The extension is not evidence.

    Gemini output arrives named .png and is sometimes a JPEG, and a failed
    generation arrives named .png and is sometimes a JSON error body. Trusting
    the extension would store the wrong Content-Type on the object and hand the
    app bytes it cannot decode — at render time, in front of a student.
    """
    for name, test, message in REFUSED_MAGIC:
        if test(data):
            raise Refusal(f"{name} file refused.\n      {message}")

    for content_type, test in SNIFFERS:
        if test(data):
            return content_type

    head = data[:16]
    printable = "".join(chr(b) if 32 <= b < 127 else "." for b in head)
    raise Refusal(
        "not an image.\n"
        f"      The first 16 bytes are {head.hex(' ')} ({printable!r}), which "
        f"match no accepted image header.\n"
        "      Accepted: PNG, JPEG, WebP. The header is read directly — the "
        "file extension is not evidence, and a .png that is really an API "
        "error body is the common case here."
    )


def measure_image(data: bytes) -> Tuple[int, int, str]:
    """(width, height, content_type), decoded rather than merely parsed.

    The sniff proves the header; Pillow proves the rest of the file is actually
    decodable. A PNG header on a truncated body passes the sniff and fails here,
    which is the right place for it to fail.
    """
    content_type = sniff_content_type(data)
    try:
        from PIL import Image
    except ImportError as err:  # pragma: no cover - Pillow is in requirements
        raise Refusal(f"Pillow is required to validate images: {err}")

    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
            pil_format = (im.format or "").upper()
    except Refusal:
        raise
    except Exception as err:
        raise Refusal(
            f"has a valid {content_type} header but does not decode: {err}\n"
            f"      Usually a truncated or partially-written file. Re-generate "
            f"it."
        )

    expected = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
    if pil_format and pil_format != expected[content_type]:
        raise Refusal(
            f"header says {content_type} but the decoder says {pil_format}. "
            f"The file is inconsistent with itself; do not ingest it."
        )
    return width, height, content_type


def validate_image_file(path: str, label: str) -> Dict[str, object]:
    """Everything an image file has to be. Raises Refusal on anything else."""
    if not os.path.isfile(path):
        raise Refusal(
            f"{label} file is missing: {os.path.basename(path)}\n"
            f"      Both files are required. The master is what ships; the "
            f"labelled version is the reference a subject author reviews "
            f"against (docs/label-layer.md §3.3 gate 4). A figure with only "
            f"one of them is unfinished, not ingestable."
        )

    size = os.path.getsize(path)
    if size < MIN_BYTES:
        raise Refusal(
            f"{label} file is {size} bytes, under the {MIN_BYTES}-byte floor. "
            f"That is a failed generation, not a figure."
        )
    if size > MAX_BYTES:
        raise Refusal(
            f"{label} file is {size / 1024 / 1024:.2f} MiB, over the "
            f"{MAX_BYTES / 1024 / 1024:.0f} MiB cap.\n"
            f"      Every asset is bundled into the app binary (never fetched "
            f"at render time, because a live class renders in airplane mode), "
            f"so these bytes are paid once per install by every student.\n"
            f"      At these dimensions a file over the cap is almost always an "
            f"unquantised PNG or an unprocessed scan rather than a better "
            f"figure."
        )

    with open(path, "rb") as fh:
        data = fh.read()

    width, height, content_type = measure_image(data)

    # Step 2 of the spec. The work order specifies landscape ~16:10 for all 48,
    # and it is not cosmetic: docs/label-layer.md §2.2 pins the label columns to
    # the ART's edges, so at the 343x236 board a portrait 1200x1600 art is only
    # 177pt wide and the anchor-separation bound in §2.5 tightens from 0.032 to
    # 0.057 in u. A portrait plate is a different layout problem, not a
    # differently-shaped version of the same one.
    if height >= width:
        raise Refusal(
            f"{label} file is {width}x{height}, which is not landscape.\n"
            f"      The work order specifies landscape ~16:10 for all 48 "
            f"figures. docs/label-layer.md §2.2 pins the label columns to the "
            f"art's edges, so a portrait plate leaves only ~177pt of art width "
            f"at the 343x236 board and tightens the §2.5 anchor separation from "
            f"0.032 to 0.057 in u. Re-generate it landscape."
        )

    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        raise Refusal(
            f"{label} file is {width}x{height}; the floor is "
            f"{MIN_DIMENSION}px on each side.\n"
            f"      The largest board (900x430) draws a 16:10 art at 688x430 "
            f"points — 2064x1290 device pixels at 3x — so art below "
            f"{MIN_DIMENSION}px is visibly upscaled at every board size and "
            f"there is no judgement to make."
        )
    if width > MAX_DIMENSION or height > MAX_DIMENSION:
        raise Refusal(
            f"{label} file is {width}x{height}; the ceiling is "
            f"{MAX_DIMENSION}px. That is an unprocessed scan. Downsample it."
        )

    warnings: List[str] = []
    if max(width, height) < WARN_LONG_EDGE:
        warnings.append(
            f"{label} is {width}x{height}, under {WARN_LONG_EDGE}px on the long "
            f"edge; it will be upscaled on the 900x430 board (2064px at 3x)."
        )
    ratio = width / height
    if not 1.4 <= ratio <= 1.9:
        warnings.append(
            f"{label} aspect is {ratio:.2f}:1; the work order specifies ~16:10 "
            f"(1.60). Not refused — a re-crop is a human decision — but the "
            f"label columns were sized against 16:10."
        )

    return {
        "data": data,
        "bytes": size,
        "width": width,
        "height": height,
        "content_type": content_type,
        "sha256": hashlib.sha256(data).hexdigest(),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# One manifest row -> one validated row, or a Refusal
# ---------------------------------------------------------------------------


class RowResult:
    def __init__(self, slug: str, state: str, message: str = "",
                 row: Optional[dict] = None, data: Optional[bytes] = None,
                 warnings: Optional[List[str]] = None):
        self.slug = slug
        self.state = state           # 'ready' | 'refused' | 'skipped'
        self.message = message
        self.row = row
        self.data = data
        self.warnings = warnings or []


def validate_row(entry: Dict[str, str], folder: str, generator_model: str,
                 sha: str, accept_inconclusive: bool) -> RowResult:
    """Everything that must be true before a byte is uploaded."""
    slug = (entry.get("asset_slug") or "").strip()

    status = (entry.get("status") or "").strip().lower()
    if status != APPROVED_STATUS:
        return RowResult(
            slug, "skipped",
            f"status={status or '(empty)'}, not '{APPROVED_STATUS}'",
        )

    try:
        validate_slug(slug)

        # Step 5's provenance, refused per the spec if absent. Checked before
        # the files are opened: a row with no licence is not worth reading a
        # 2 MiB PNG for, and the refusal should name the real problem rather
        # than whichever check happened to run first.
        licence = validate_licence(entry.get("licence"))
        source_url = require_url(
            entry.get("source_url"), "source_url",
            "Where this exact file, or the anchor it was made from, can be "
            "found by somebody who was not here.",
        )
        author = require_text(
            entry.get("author"), "author",
            "Who is responsible for the shipped file. Attribution is a licence "
            "condition under every CC BY member of the enum, so an "
            "unattributed asset is not merely untidy — it is unshippable.",
        )
        anchor_book = require_text(
            entry.get("anchor_book"), "anchor_book",
            "The public-domain plate this was derived from. Kept SEPARATE from "
            "licence: the generated plate is a new work, and a derivative of a "
            "PD work is not automatically PD.",
        )

        name_unlabelled = (entry.get("file_unlabelled") or "").strip()
        name_labelled = (entry.get("file_labelled") or "").strip()
        if not name_unlabelled or not name_labelled:
            raise Refusal(
                "file_unlabelled and file_labelled must both be named in the "
                "manifest."
            )

        # Step 1: BOTH files exist. Step 2: both landscape.
        master = validate_image_file(
            os.path.join(folder, name_unlabelled), "unlabelled master")
        labelled = validate_image_file(
            os.path.join(folder, name_labelled), "labelled reference")

        # Step 3. See THE TEXT CHECK in the module docstring, and
        # scripts/asset_text_probe.py for the measured numbers.
        probe = asset_text_probe.probe(master["data"])
        if probe.found_text:
            raise Refusal(
                f"the unlabelled master CONTAINS TEXT.\n"
                f"      {probe.detail}\n"
                f"      The work order is explicit: the master is the drawing "
                f"only, no text of any kind. Our own bilingual label layer is "
                f"drawn over it at render time, and burnt-in English labels "
                f"would put two competing label systems on one image "
                f"(docs/label-layer.md §6.3). Re-generate the master."
            )
        if probe.verdict == "unavailable":
            raise Refusal(
                f"the text check could not run: {probe.detail}\n"
                f"      An unrunnable check is not a passed check. Fix the "
                f"environment rather than skipping the step."
            )
        if (probe.verdict == "heuristic-clean-ocr-unavailable"
                and not accept_inconclusive):
            raise Refusal(
                f"the text check is INCONCLUSIVE, and that is not a pass.\n"
                f"      {probe.detail}\n"
                f"      No OCR engine is installed, so only the shape "
                f"heuristic ran. Measured, it is blind to single-character "
                f"labels (0/30 detected) and to display text in its strict "
                f"tier — which are exactly the plate number and the title the "
                f"work order forbids.\n"
                f"      Either install tesseract + pytesseract, or look at the "
                f"plate yourself and re-run with "
                f"--accept-inconclusive-text-check. That flag is recorded in "
                f"text_check, so a later query can find every asset admitted "
                f"this way."
            )

        row = {
            "asset_slug": slug,
            "r2_key": f"concept-assets/{slug}."
                      f"{master['content_type'].split('/')[-1]}",
            "content_type": master["content_type"],
            "width": master["width"],
            "height": master["height"],
            "bytes": master["bytes"],
            "licence": licence,
            "source_url": source_url,
            "author": author,
            "anchor_book": anchor_book,
            "generator_model": generator_model,
            "prompt_sha": sha,
            "text_check": probe.verdict,
            # Verified to exist, recorded by name and hash, NOT uploaded. See
            # TWO FILES, ONE ROW.
            "labelled_reference_file": name_labelled,
            "labelled_reference_sha256": labelled["sha256"],
            # The text check is the EVIDENCE for this value rather than an
            # assertion about it — which is the difference between this column
            # and `grounded`, which was always true because nothing ever
            # computed it.
            "arrived_labelled": "unlabelled",
            # NULL, not {}. See THE ONE FIELD THIS COMMAND REFUSES TO FILL IN.
            "syllabus_gap": None,
            "manifest_status": status,
            "subject": {"bio": "biology"}.get(
                (entry.get("subject") or "").strip().lower(),
                (entry.get("subject") or "").strip().lower()) or None,
            "class_level": int(entry["class"]) if (entry.get("class") or
                                                   "").strip().isdigit() else None,
        }
        warnings = list(master["warnings"]) + list(labelled["warnings"]) + \
            list(probe.warnings)
        return RowResult(slug, "ready", row=row, data=master["data"],
                         warnings=warnings)

    except Refusal as err:
        return RowResult(slug, "refused", str(err))


# ---------------------------------------------------------------------------
# R2 + database
# ---------------------------------------------------------------------------


def fetch_existing(slug: str) -> Optional[dict]:
    from app.db import supabase

    rows = (
        supabase.table(TABLE).select(ROW_COLUMNS)
        .eq("asset_slug", slug).limit(1).execute().data or []
    )
    return rows[0] if rows else None


def upload_and_verify(key: str, data: bytes, content_type: str) -> int:
    """put_object, then head_object. Returns the size R2 reports.

    The head is not paranoia about boto3; it is what makes the row's claim
    checked rather than optimistic. A put that returns 200 and a bucket that
    does not have the object (wrong bucket, a lifecycle rule, an eventually
    consistent overwrite) is exactly the case a row must not be written for.
    """
    from app import storage_r2

    client = storage_r2.get_client()
    bucket = storage_r2.assets_bucket_name()
    client.put_object(
        Bucket=bucket, Key=key, Body=data, ContentType=content_type,
        # Bundled into the app and keyed by a slug that is never reused, so the
        # object at a given key is immutable in practice.
        CacheControl="public, max-age=31536000, immutable",
    )
    head = client.head_object(Bucket=bucket, Key=key)
    stored = int(head.get("ContentLength", -1))
    if stored != len(data):
        raise RuntimeError(
            f"R2 stored {stored} bytes for {key} but the file is {len(data)}. "
            f"NOT writing a row for a truncated object."
        )
    return stored


def orphan_shout(bucket: str, key: str, err: Exception) -> None:
    """The insert failed after the upload landed. Say so, loudly, by name."""
    sys.stderr.write(
        "\n"
        "!! ORPHANED OBJECT ------------------------------------------------\n"
        f"!! The upload SUCCEEDED and the database write FAILED.\n"
        f"!!   bucket : {bucket}\n"
        f"!!   key    : {key}\n"
        f"!!   error  : {err}\n"
        f"!!\n"
        f"!! Nothing points at that object. It costs storage and nothing else —\n"
        f"!! this is the cheap side of the ordering, and it is why the upload\n"
        f"!! goes first. Re-run (this command is idempotent and overwrites the\n"
        f"!! same key), or delete it:\n"
        f"!!   aws s3api delete-object --endpoint-url $R2_ENDPOINT_URL \\\n"
        f"!!       --bucket {bucket} --key {key}\n"
        f"!! `ingest_asset.py verify` also lists it as an object with no row.\n"
        "!! -----------------------------------------------------------------\n"
        "\n"
    )


def list_r2_objects() -> Dict[str, dict]:
    """Every object under the illustrations prefix, keyed by key.

    Paginated: list_objects_v2 caps at 1000 and reports truncation in a flag
    nobody reads, which is the same shape as the PostgREST 1000-row ceiling that
    silently returned two thirds of `concepts`.
    """
    from app import storage_r2

    client = storage_r2.get_client()
    bucket = storage_r2.assets_bucket_name()
    out: Dict[str, dict] = {}
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": storage_r2.ASSETS_KEY_PREFIX,
                  "MaxKeys": 1000}
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        for obj in page.get("Contents", []) or []:
            out[obj["Key"]] = obj
        if not page.get("IsTruncated"):
            return out
        token = page.get("NextContinuationToken")
        if not token:
            return out


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_ingest(args) -> int:
    dry = not args.execute

    try:
        entries = read_manifest(args.manifest)
        sha = prompt_sha(args.work_order)
        model = require_text(
            args.generator_model, "--generator-model",
            "The exact model identifier that produced the art, e.g. "
            "'gemini-3-pro-image'. A bare 'gemini' names no model and pins no "
            "version — that is the source_model failure, which recorded a name "
            "that turned out to be the wrong model.",
        )
        if not os.path.isdir(args.dir):
            raise Refusal(f"--dir {args.dir} is not a directory.")
    except Refusal as err:
        sys.stderr.write(f"\nREFUSED: {err}\n\n")
        return 2

    print(f"manifest        {args.manifest}  ({len(entries)} rows, "
          f"all {len(MANIFEST_COLUMNS)} columns present)")
    print(f"folder          {args.dir}")
    print(f"work order      {os.path.basename(args.work_order)}  "
          f"prompt_sha={sha}")
    print(f"generator_model {model}")
    print(f"mode            {'DRY RUN' if dry else 'EXECUTE'}")
    print()

    results = [
        validate_row(e, args.dir, model, sha, args.accept_inconclusive_text_check)
        for e in entries
    ]
    ready = [r for r in results if r.state == "ready"]
    refused = [r for r in results if r.state == "refused"]
    skipped = [r for r in results if r.state == "skipped"]

    if refused:
        print(f"REFUSED ({len(refused)})")
        for r in refused:
            print(f"  {r.slug}")
            print(f"      {r.message}")
        print()

    if ready:
        print(f"READY ({len(ready)})")
        for r in ready:
            row = r.row or {}
            print(f"  {r.slug}")
            print(f"      {row['width']}x{row['height']}  "
                  f"{row['bytes'] // 1024:,} KiB  {row['content_type']}  "
                  f"-> {row['r2_key']}")
            print(f"      licence={row['licence']}  author={row['author']}")
            print(f"      anchor_book={row['anchor_book']}")
            print(f"      text_check={row['text_check']}")
            print(f"      labelled ref {row['labelled_reference_file']} "
                  f"sha={row['labelled_reference_sha256'][:12]} (verified, "
                  f"not uploaded)")
            for w in r.warnings:
                print(f"      WARNING: {w}")
        print()

    # Skipped is a REPORTED category, not silence. Grouped by status so "48 at
    # todo" reads as one fact rather than 48 lines.
    if skipped:
        by_reason: Dict[str, List[str]] = {}
        for r in skipped:
            by_reason.setdefault(r.message, []).append(r.slug)
        print(f"SKIPPED ({len(skipped)}) — not marked '{APPROVED_STATUS}'")
        for reason, slugs in sorted(by_reason.items()):
            print(f"  {len(slugs):3d}  {reason}")
            for s in slugs[:5]:
                print(f"         {s}")
            if len(slugs) > 5:
                print(f"         ... and {len(slugs) - 5} more")
        print()

    print(f"TOTALS  ready {len(ready)}   refused {len(refused)}   "
          f"skipped {len(skipped)}   of {len(entries)}")

    if dry:
        print("\nDRY RUN — nothing uploaded, nothing written. "
              "Re-run with --execute.")
        return 2 if refused else 0

    if not ready:
        print("\nNothing to write.")
        return 2 if refused else 0

    from app import storage_r2
    from app.db import supabase

    bucket = storage_r2.assets_bucket_name()
    wrote, failed = 0, 0
    print()
    for r in ready:
        row = r.row or {}
        try:
            existing = fetch_existing(r.slug)
        except Exception as err:
            sys.stderr.write(f"{r.slug}: FAILED before uploading anything: "
                             f"{err}\n")
            failed += 1
            continue

        # 1. upload, 2. confirm it is there. Only then, 3. record it.
        try:
            stored = upload_and_verify(row["r2_key"], r.data,
                                       row["content_type"])
        except Exception as err:
            sys.stderr.write(
                f"{r.slug}: UPLOAD FAILED for {bucket}/{row['r2_key']}: {err}\n"
                f"  No row was written — that is the point of the ordering. "
                f"Nothing in the database now points at an object that does "
                f"not exist.\n"
            )
            failed += 1
            continue

        try:
            if existing:
                (supabase.table(TABLE).update(row)
                 .eq("asset_slug", r.slug).execute())
                verb = "updated"
            else:
                supabase.table(TABLE).insert(row).execute()
                verb = "inserted"
        except Exception as err:
            orphan_shout(bucket, row["r2_key"], err)
            failed += 1
            continue

        wrote += 1
        print(f"{r.slug}: uploaded {stored:,} bytes and {verb} the row")

    print(f"\nWROTE {wrote}, FAILED {failed}")
    return 1 if failed else (2 if refused else 0)


def cmd_verify(args) -> int:
    """Both directions: a row with no object, and an object with no row."""
    from app.db import fetch_all
    from app import storage_r2

    try:
        rows = fetch_all(TABLE, ROW_COLUMNS)
    except Exception as err:
        sys.stderr.write(f"could not read {TABLE}: {err}\n")
        return 1
    try:
        objects = list_r2_objects()
        bucket = storage_r2.assets_bucket_name()
    except Exception as err:
        sys.stderr.write(f"could not list R2: {err}\n")
        return 1

    by_key: Dict[str, dict] = {}
    dup_keys: List[str] = []
    for row in rows:
        if row["r2_key"] in by_key:
            dup_keys.append(row["r2_key"])
        by_key[row["r2_key"]] = row

    dangling = [r for r in rows if r["r2_key"] not in objects]
    unreferenced = sorted(k for k in objects if k not in by_key)
    mismatched = [
        (r, objects[r["r2_key"]]["Size"]) for r in rows
        if r["r2_key"] in objects
        and int(objects[r["r2_key"]]["Size"]) != int(r["bytes"])
    ]

    print(f"bucket   {bucket}")
    print(f"prefix   {storage_r2.ASSETS_KEY_PREFIX}")
    print(f"rows     {len(rows)}")
    print(f"objects  {len(objects)}")
    print()

    if dangling:
        # The failure the upload-then-insert ordering exists to prevent. If any
        # appear, something wrote a row outside this command.
        print(f"DANGLING ROWS — a row whose object is gone ({len(dangling)}).")
        print("  This should be impossible via this command; it means either a "
              "hand-written INSERT or an object deleted out from under a row. "
              "It fails at render time, in front of a student.")
        for r in dangling:
            print(f"  {r['asset_slug']}  {r['r2_key']}")
        print()

    if unreferenced:
        print(f"ORPHANED OBJECTS — an object no row points at "
              f"({len(unreferenced)}).")
        print("  The cheap side of the ordering: costs storage, breaks nothing. "
              "Usually an ingest whose database write failed.")
        for k in unreferenced:
            print(f"  {k}  ({objects[k]['Size']:,} bytes)")
        print()

    if mismatched:
        print(f"SIZE MISMATCH — the row and the object disagree "
              f"({len(mismatched)}).")
        for r, size in mismatched:
            print(f"  {r['asset_slug']}  row says {r['bytes']:,}, R2 says "
                  f"{size:,}")
        print()

    if dup_keys:
        print(f"DUPLICATE r2_key across rows ({len(dup_keys)}): "
              f"{', '.join(dup_keys)}")
        print()

    # Not storage problems, but they are the two ways a row can be present and
    # not yet trustworthy, and neither is visible unless something counts it.
    inconclusive = [r for r in rows
                    if r.get("text_check") == "heuristic-clean-ocr-unavailable"]
    ungapped = [r for r in rows if r.get("syllabus_gap") is None]
    if inconclusive:
        print(f"TEXT CHECK INCONCLUSIVE ({len(inconclusive)} of {len(rows)}) — "
              f"admitted on the shape heuristic with no OCR installed. Not a "
              f"pass; see scripts/asset_text_probe.py for what it is blind to.")
        print()
    if ungapped:
        print(f"SYLLABUS GAP NOT YET CHECKED ({len(ungapped)} of {len(rows)}) — "
              f"NULL means nobody has looked. Not shippable until a subject "
              f"author fills it in; the ingest cannot.")
        print()

    broken = bool(dangling or unreferenced or mismatched or dup_keys)
    if not broken:
        print("OK on storage — every row has its object and every object has "
              "its row.")
    else:
        print("PROBLEMS FOUND (see above).")
    return 1 if broken else 0


def cmd_list(args) -> int:
    from app.db import fetch_all

    rows = fetch_all(TABLE, ROW_COLUMNS)
    rows.sort(key=lambda r: (r.get("subject") or "", r["asset_slug"]))
    if not rows:
        print("no rows in concept_assets")
        return 0
    for r in rows:
        print(f"{r['asset_slug']}")
        print(f"    {r['licence']:11s} {r['width']}x{r['height']}  "
              f"{r['bytes'] // 1024:,} KiB  text_check={r['text_check']}")
        print(f"    author={r['author']}  model={r.get('generator_model')}  "
              f"prompt_sha={r.get('prompt_sha')}")
        print(f"    anchor={r.get('anchor_book')}")
    print(f"\n{len(rows)} rows")

    # A uniform provenance column is the page_start shape: present everywhere,
    # asserting nothing. Surfaced here so it is noticed rather than discovered.
    # Some of these WILL be uniform for a single work order — that is fine and
    # expected — but it should be a fact somebody has seen.
    for col in ("licence", "author", "generator_model", "prompt_sha",
                "text_check", "arrived_labelled"):
        distinct = {r.get(col) for r in rows}
        if len(rows) >= 5 and len(distinct) == 1:
            print(f"NOTE: every row has the same {col} "
                  f"({next(iter(distinct))!r}). Expected within one work order; "
                  f"check it was recorded rather than repeated.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="ingest_asset.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    ing = sub.add_parser("ingest",
                         help="validate (and optionally write) a work-order folder")
    ing.add_argument("--dir", required=True, help="folder holding the image files")
    ing.add_argument("--manifest", required=True,
                     help="illustration-manifest.csv, all "
                          f"{len(MANIFEST_COLUMNS)} columns")
    ing.add_argument("--work-order", required=True,
                     help="gemini-work-order.md; hashed into every row")
    ing.add_argument("--generator-model", required=True,
                     help="exact model id, e.g. gemini-3-pro-image")
    ing.add_argument("--accept-inconclusive-text-check", action="store_true",
                     help="admit rows whose text check could only run the shape "
                          "heuristic. Recorded in text_check.")
    # Dry run is the default, matching scripts/ingest_mathpix_books.py.
    ing.add_argument("--execute", action="store_true",
                     help="actually upload and write (default is a dry run)")
    ing.set_defaults(func=cmd_ingest)

    ver = sub.add_parser("verify", help="orphan check in both directions")
    ver.set_defaults(func=cmd_verify)

    lst = sub.add_parser("list", help="what is registered")
    lst.set_defaults(func=cmd_list)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Refusal as err:
        sys.stderr.write(f"\nREFUSED: {err}\n\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
