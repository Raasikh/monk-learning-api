"""Refusal tests for scripts/ingest_asset.py and scripts/asset_text_probe.py.

The point of this file is the NOs. Six provenance failures in this project have
all been the same shape — a field that could be satisfied by a plausible value
nobody supplied — and a constraint nobody has watched fire is a constraint
trusted on the strength of having been written. So every refusal has a test that
asserts a non-zero exit AND asserts the message names the problem, because a
refusal nobody can act on gets worked around.

R2 and the database are faked. That is deliberate: the validation logic is what
is under test and it runs entirely before either is touched. The fakes also let
the ordering test assert the thing that actually matters — that a failed upload
writes NO row, and a failed insert names the object it left behind.

test_text_probe_measured_behaviour is not a pass/fail check on a threshold; it
reproduces the recall and false-positive numbers quoted in
scripts/asset_text_probe.py, including the two cases the detector is BLIND to.
A detector whose stated blind spots have no failing fixture is a detector
described rather than measured.
"""
import csv
import hashlib
import io
import os
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import asset_text_probe as probe  # noqa: E402
import ingest_asset as ia  # noqa: E402

# The CURRENT package's manifest. Was the Downloads work order, which is
# superseded — 48 rows at status=todo, in the old two-file schema. Reading a
# manifest is not the same as depending on the 224 image files: the OCR
# controls are committed crops under tests/fixtures/ for exactly that reason.
REAL_MANIFEST = Path(
    "/Users/raasikhnaveed/Desktop/monk-learning-mobile/monklearning-mobile/"
    "content/illustrations/v1/illustration-manifest.csv"
)
REAL_WORK_ORDER = REAL_MANIFEST.parent / "DIRECTIVE.md"

FONTS = [
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
]
HAVE_FONTS = all(os.path.exists(f) for f in FONTS)


# ---------------------------------------------------------------------------
# fixtures: images
# ---------------------------------------------------------------------------


def plate(seed=0, w=1600, h=1000, n_words=0, word_size=(16, 34), text=None,
          fmt="PNG", bg=232):
    """A synthetic engraving-style plate: strokes, stipple, optional labels.

    `bg` is the ground. 232 is aged paper and is what the TEXT-DETECTOR
    benchmark uses, because that is the corpus those numbers were measured on.
    255 is what a v1.1 master looks like — white ground, flush to the board —
    and is what every ingest fixture uses, because the white-corner check is
    real and a 232 ground correctly fails it.
    """
    from PIL import Image, ImageDraw, ImageFont

    rnd = random.Random(seed)
    im = Image.new("L", (w, h), bg)
    d = ImageDraw.Draw(im)
    for _ in range(rnd.randint(18, 30)):
        pts, x, y = [], rnd.randint(100, max(101, w - 100)), rnd.randint(100, max(101, h - 100))
        for _ in range(rnd.randint(6, 14)):
            x += rnd.randint(-90, 90)
            y += rnd.randint(-70, 70)
            pts.append((max(0, min(w, x)), max(0, min(h, y))))
        d.line(pts, fill=rnd.randint(20, 70), width=rnd.randint(1, 3))
    for _ in range(rnd.randint(300, 900)):
        x, y = rnd.randint(0, w - 1), rnd.randint(0, h - 1)
        r = rnd.randint(1, 3)
        d.ellipse([x, y, x + r, y + r], fill=rnd.randint(30, 90))
    if n_words and HAVE_FONTS:
        terms = ["hypha", "mycelium", "sporangium", "Malpighian tubule",
                 "gizzard", "holdfast", "pyrenoid", "spiracle"]
        for _ in range(n_words):
            f = ImageFont.truetype(rnd.choice(FONTS),
                                   rnd.randint(*word_size))
            x, y = rnd.randint(40, max(41, w - 340)), rnd.randint(30, max(31, h - 70))
            d.text((x, y), text or rnd.choice(terms), fill=rnd.randint(10, 45),
                   font=f)
            d.line([(x - 20, y + 12), (x - 90, y + 40)], fill=40, width=1)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, format=fmt)
    return buf.getvalue()


SLUG = "bio11-ch7-cockroach--nervous-system-and-reproduction"

# drona-illustrations-v1.1's schema, not the old work order's. `sha256` is
# filled in by `write_files`, because a manifest hash that does not match the
# bytes on disk is the one thing the ingest checks it against.
GOOD_ROW = {
    "asset_slug": SLUG,
    "concept_slug": SLUG,
    "sub": "",
    "batch": "1",
    "subject": "bio",
    "class_": "11",
    "chapter": "Structural Organisation in Animals",
    "concept": "Cockroach: Nervous System and Reproduction",
    "file": f"masters/{SLUG}.png",
    "width": "1600",
    "height": "1000",
    "sha256": "",            # written by write_files
    "cleanup": "none",
    "note": "",
    "ncert_labels": "ganglion, ovary, testis",
    "status": "accepted",
    # generated-free, because this manifest has no anchor_book column and 0038
    # requires a third-party licence to name one. A batch of third-party art
    # would ship a manifest that HAS that column; this schema is for our own.
    "licence": "generated-free",
    "source_url": f"generated:gemini:batch1/{SLUG}",
    "author": "MonkLearning (AI-generated, Gemini)",
}


@pytest.fixture
def work_order(tmp_path):
    p = tmp_path / "gemini-work-order.md"
    p.write_text("# Gemini work order — 48 anchored biology plates\n")
    return str(p)


def write_manifest(tmp_path, rows, drop_columns=()):
    cols = [c for c in ia.MANIFEST_COLUMNS if c not in drop_columns]
    p = tmp_path / "illustration-manifest.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        for r in rows:
            wr.writerow(r)
    return str(p)


def write_files(folder, row, master=None, labelled=None):
    """Write the master and its raw counterpart, and pin the row's sha256.

    ONE `file` plus `raw/`, mirroring the package: the old work order named two
    files because it commissioned two. The raw copy carries words on purpose —
    it is what the master was made from, and it is the positive control that
    the text check is not vacuous.
    """
    rel = row.get("file") or f"masters/{row['asset_slug']}.png"
    m = Path(folder, rel)
    r = Path(folder, rel.replace("masters/", "raw/", 1))
    m.parent.mkdir(parents=True, exist_ok=True)
    r.parent.mkdir(parents=True, exist_ok=True)
    data = master if master is not None else plate(1, bg=255)
    m.write_bytes(data)
    r.write_bytes(labelled if labelled is not None else plate(2, n_words=6))
    # The manifest's claim about the bytes, made true. A test that leaves this
    # stale would fail on the sha256 check rather than on the thing it breaks.
    if not row.get("sha256"):
        row["sha256"] = hashlib.sha256(data).hexdigest()



@pytest.fixture
def no_ocr(monkeypatch):
    """Simulate a machine with no OCR engine.

    The inconclusive path is not dead code — it is what runs wherever
    tesseract is absent, which was this machine until the v1.1 pass. With an
    engine installed the verdict is always conclusive, so a test asserting the
    inconclusive refusal cannot fire on its own. It is made to fire here, by
    removing the detector, rather than deleted as unreachable.
    """
    monkeypatch.setattr(probe, "_ocr", lambda data: None)
    return True

@pytest.fixture
def bench(tmp_path, work_order):
    """A folder + manifest that would ingest cleanly. Break one thing per test."""
    folder = tmp_path / "out"

    def make(overrides=None, drop_columns=(), master=None, labelled=None,
             rows=None):
        if rows is None:
            row = dict(GOOD_ROW)
            row.update(overrides or {})
            rows = [row]
        for r in rows:
            write_files(str(folder), r, master=master, labelled=labelled)
        manifest = write_manifest(tmp_path, rows, drop_columns)
        return ["ingest", "--dir", str(folder), "--manifest", manifest,
                "--work-order", work_order,
                "--generator-model", "gemini-3-pro-image",
                "--accept-inconclusive-text-check"]

    return make


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class FakeS3:
    def __init__(self, fail_put=False, objects=None):
        self.objects = dict(objects or {})
        self.fail_put = fail_put
        self.puts, self.deleted = [], []

    def put_object(self, Bucket, Key, Body, ContentType, **kw):
        if self.fail_put:
            raise RuntimeError("R2 said no")
        self.puts.append(Key)
        self.objects[Key] = Body
        return {}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise RuntimeError("NoSuchKey")
        return {"ContentLength": len(self.objects[Key])}

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)
        self.objects.pop(Key, None)
        return {}

    def list_objects_v2(self, Bucket, Prefix, MaxKeys=1000, **kw):
        return {"Contents": [{"Key": k, "Size": len(v)}
                             for k, v in sorted(self.objects.items())
                             if k.startswith(Prefix)],
                "IsTruncated": False}


class FakeTable:
    def __init__(self, db, name):
        self.db, self.name, self._f = db, name, {}

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._f[col] = val
        return self

    def limit(self, n):
        return self

    def range(self, lo, hi):
        return self

    def execute(self):
        rows = [r for r in self.db.rows
                if all(r.get(c) == v for c, v in self._f.items())]
        return type("R", (), {"data": rows})()

    def insert(self, row):
        if self.db.fail_write:
            raise RuntimeError("PostgREST 500")
        self.db.rows.append(dict(row))
        self.db.inserts.append(dict(row))
        return type("Q", (), {"execute": lambda _s: None})()

    def update(self, row):
        if self.db.fail_write:
            raise RuntimeError("PostgREST 500")
        self.db.updates.append(dict(row))
        target, db = dict(row), self.db

        class _U:
            def __init__(_s):
                _s.f = {}

            def eq(_s, c, v):
                _s.f[c] = v
                return _s

            def execute(_s):
                for r in db.rows:
                    if all(r.get(c) == v for c, v in _s.f.items()):
                        r.update(target)
                return None

        return _U()


class FakeDB:
    def __init__(self, rows=None, fail_write=False):
        self.rows = [dict(r) for r in (rows or [])]
        self.inserts, self.updates = [], []
        self.fail_write = fail_write

    def table(self, name):
        return FakeTable(self, name)


@pytest.fixture
def wired(monkeypatch):
    import app.db as appdb
    import app.storage_r2 as r2

    s3, db = FakeS3(), FakeDB()
    monkeypatch.setattr(r2, "get_client", lambda: s3)
    monkeypatch.setattr(r2, "assets_bucket_name", lambda: "monk-illustrations")
    monkeypatch.setattr(appdb, "supabase", db)
    monkeypatch.setattr(appdb, "fetch_all", lambda t, c, **kw: list(db.rows))
    return s3, db


# ---------------------------------------------------------------------------
# THE MISSING-COLUMN RULE
# ---------------------------------------------------------------------------


def test_missing_licence_column_is_a_hard_error_not_48_refusals(bench, wired,
                                                                capsys):
    args = bench(drop_columns=("licence",))
    code = ia.main(args)
    err = capsys.readouterr().err
    assert code != 0
    assert "missing 1 required column(s): licence" in err
    # The whole point: it must NOT look like a tidy per-row refusal.
    assert "REFUSED (" not in capsys.readouterr().out
    assert "wrong file" in err
    s3, db = wired
    assert s3.puts == [] and db.inserts == []


def test_missing_several_columns_names_all_of_them(bench, capsys):
    code = ia.main(bench(drop_columns=("licence", "source_url", "author")))
    err = capsys.readouterr().err
    assert code != 0
    for col in ("licence", "source_url", "author"):
        assert col in err


def test_extra_column_is_noted_but_not_fatal(tmp_path, work_order, bench,
                                             wired, capsys):
    args = bench()
    manifest = Path(args[args.index("--manifest") + 1])
    text = manifest.read_text().splitlines()
    manifest.write_text(text[0] + ",reviewer\n" + "\n".join(
        r + ",r.nandy" for r in text[1:]) + "\n")
    code = ia.main(args)
    out = capsys.readouterr()
    assert code == 0
    assert "column(s) this command does not know: reviewer" in out.err


# ---------------------------------------------------------------------------
# the named refusals
# ---------------------------------------------------------------------------


def test_refuses_row_with_missing_licence(bench, wired, capsys):
    code = ia.main(bench({"licence": ""}))
    out = capsys.readouterr().out
    assert code != 0
    assert "REFUSED (1)" in out
    assert "licence is empty" in out
    # anchor_book must not be allowed to stand in for it.
    assert "anchor_book is NOT a substitute" in out
    s3, db = wired
    assert s3.puts == [] and db.inserts == []


def test_refuses_placeholder_licence(bench, wired, capsys):
    for value in ("unknown", "TBD", "n/a", "  Unknown  ", "public domain"):
        code = ia.main(bench({"licence": value}))
        out = capsys.readouterr().out
        assert code != 0, value
        assert "placeholder" in out.lower(), value


def test_refuses_share_alike_licence(bench, wired, capsys):
    for value in ("CC-BY-SA-4.0", "CC BY SA 3.0", "cc-by-sa-2.0"):
        code = ia.main(bench({"licence": value}))
        out = capsys.readouterr().out
        assert code != 0, value
        assert "share-alike" in out.lower(), value
        # The message has to carry the measured rule, or it gets argued with.
        assert "OpenStax" in out or "institution" in out.lower()
    s3, db = wired
    assert s3.puts == [] and db.inserts == []


def test_refuses_non_commercial_licence(bench, capsys):
    assert ia.main(bench({"licence": "CC-BY-NC-4.0"})) != 0
    assert "non-commercial" in capsys.readouterr().out.lower()


def test_refuses_licence_outside_the_enum(bench, capsys):
    assert ia.main(bench({"licence": "CC-BY-5.0"})) != 0
    out = capsys.readouterr().out
    assert "closed enum" in out
    for member in ia.LICENCE_ENUM:
        assert member in out
    # Never weaken the schema to make a row fit.
    assert "never the way to make a manifest row fit" in out


def test_refuses_missing_source_url(bench, wired, capsys):
    code = ia.main(bench({"source_url": ""}))
    out = capsys.readouterr().out
    assert code != 0
    assert "source_url is empty" in out
    s3, db = wired
    assert s3.puts == [] and db.inserts == []


def test_refuses_prose_instead_of_a_source_url(bench, capsys):
    assert ia.main(bench({"source_url": "the archive.org page"})) != 0
    assert "not an http(s) URL" in capsys.readouterr().out


def test_refuses_missing_author(bench, capsys):
    assert ia.main(bench({"author": ""})) != 0
    assert "author is empty" in capsys.readouterr().out


def test_refuses_placeholder_author(bench, capsys):
    for value in ("unknown", "anonymous", "n/a", "-", "uncredited"):
        assert ia.main(bench({"author": value})) != 0, value
        assert "placeholder" in capsys.readouterr().out.lower(), value


def test_refuses_non_image_file(bench, wired, capsys):
    # Named .png, actually a JSON error body — the common shape of a failed
    # generation, and the reason the extension is not evidence.
    bad = b'{"error":{"code":429,"message":"quota exceeded"}}' * 40
    code = ia.main(bench(master=bad))
    out = capsys.readouterr().out
    assert code != 0
    assert "not an image" in out.lower()
    s3, db = wired
    assert s3.puts == [] and db.inserts == []


def test_refuses_truncated_png(bench, capsys):
    assert ia.main(bench(master=plate(1)[:3000])) != 0
    assert "does not decode" in capsys.readouterr().out


def test_refuses_svg_and_gif_by_name(bench, capsys):
    assert ia.main(bench(master=b'<svg xmlns="http://www.w3.org/2000/svg">'
                                + b" " * 2000)) != 0
    assert "SVG is refused" in capsys.readouterr().out
    assert ia.main(bench(master=b"GIF89a" + b"\x00" * 2000)) != 0
    assert "GIF is refused" in capsys.readouterr().out


def test_refuses_a_portrait_plate(bench, capsys):
    assert ia.main(bench(master=plate(3, w=1000, h=1600))) != 0
    out = capsys.readouterr().out
    assert "not landscape" in out
    # The refusal must carry the arithmetic, not just the rule.
    assert "343x236" in out


def test_refuses_when_the_raw_counterpart_is_missing(bench, tmp_path,
                                                     wired, capsys):
    """Raw must EXIST and OPEN, even though it is never uploaded.

    `labelled_reference_sha256` is a hash of that file. A row carrying a hash of
    a file nobody can produce records nothing, so the row is refused rather
    than written with an unverifiable claim.

    (The old two-file model's `file_labelled` checks are gone with it; raw is
    the counterpart now, and its GEOMETRY is deliberately unchecked — see
    test_raw_geometry_is_not_checked.)
    """
    args = bench()
    os.remove(tmp_path / "out" / "raw" / f"{SLUG}.png")
    code = ia.main(args)
    out = capsys.readouterr().out
    assert code != 0
    assert "raw counterpart file is missing" in out
    s3, db = wired
    assert s3.puts == [] and db.inserts == []


def test_refuses_when_the_master_is_missing(bench, tmp_path, capsys):
    args = bench()
    os.remove(tmp_path / "out" / GOOD_ROW["file"])
    assert ia.main(args) != 0
    assert "master file is missing" in capsys.readouterr().out


def test_raw_geometry_is_not_checked(bench, tmp_path, wired, capsys):
    """Raw is provenance, not a plate. It is never uploaded and never drawn.

    v1.1 normalised the masters to 16:10 and left raw exactly as it arrived —
    which is the point of keeping it. Two 896x896 raws were refusing their
    perfectly good masters over the shape of a file no board renders. The
    positive proof is a SQUARE raw beside a valid master: it must ingest.
    """
    args = bench(labelled=plate(2, w=896, h=896, n_words=6))
    code = ia.main(args)
    out = capsys.readouterr().out
    assert code == 0, out
    assert "not landscape" not in out


def test_refuses_oversize_file(bench, capsys, monkeypatch):
    monkeypatch.setattr(ia, "MAX_BYTES", 4096)
    assert ia.main(bench()) != 0
    out = capsys.readouterr().out
    assert "over the" in out and "cap" in out
    assert "bundled into the app binary" in out


def test_refuses_bad_slug(bench, capsys):
    bad = dict(GOOD_ROW)
    bad["asset_slug"] = "Bio11 Ch7 Cockroach"
    bad["file"] = f"masters/{bad['asset_slug']}.png"
    assert ia.main(bench(rows=[bad])) != 0
    out = capsys.readouterr().out
    assert "not a usable slug" in out
    assert "DOUBLE hyphen is significant" in out


def test_refuses_bare_model_name(bench, capsys):
    args = bench()
    args[args.index("--generator-model") + 1] = "gemini"
    assert ia.main(args) != 0
    err = capsys.readouterr().err
    assert "placeholder" in err.lower()
    assert "source_model" in err


def test_refuses_a_missing_work_order(bench, tmp_path, capsys):
    args = bench()
    args[args.index("--work-order") + 1] = str(tmp_path / "nope.md")
    assert ia.main(args) != 0
    err = capsys.readouterr().err
    assert "does not exist" in err
    assert "prompt_version" in err


# ---------------------------------------------------------------------------
# the text check
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAVE_FONTS, reason="needs system fonts to render text")
def test_refuses_a_master_that_contains_text(bench, wired, capsys):
    # bg=255 so the ONLY thing wrong with this fixture is the text. On the
    # aged-paper default it refuses on the white-corner check instead, and the
    # test would pass while proving something else entirely.
    code = ia.main(bench(master=plate(7, n_words=8, bg=255)))
    out = capsys.readouterr().out
    assert code != 0
    assert "CONTAINS TEXT" in out
    assert "two competing label systems" in out
    s3, db = wired
    assert s3.puts == [] and db.inserts == []


def test_inconclusive_text_check_is_refused_without_the_explicit_flag(
    bench, wired, capsys, no_ocr
):
    args = [a for a in bench() if a != "--accept-inconclusive-text-check"]
    code = ia.main(args)
    out = capsys.readouterr().out
    assert code != 0
    assert "INCONCLUSIVE, and that is not a pass" in out
    # The refusal must state the measured blind spots, not just say "unsure".
    assert "0/30" in out
    s3, db = wired
    assert s3.puts == [] and db.inserts == []


def test_the_inconclusive_verdict_is_stored_not_flattened(bench, wired, capsys, no_ocr):
    s3, db = wired
    assert ia.main(bench() + ["--execute"]) == 0
    capsys.readouterr()
    assert db.inserts[0]["text_check"] == "heuristic-clean-ocr-unavailable"
    # Never a boolean, never 'clean'. `select text_check, count(*)` must be able
    # to find every asset that was never really checked.
    assert db.inserts[0]["text_check"] not in (True, "clean", "ok")


def test_an_unavailable_detector_is_not_a_pass(bench, monkeypatch, capsys):
    monkeypatch.setattr(
        probe, "probe",
        lambda data: probe.Result("unavailable", "numpy is missing"))
    code = ia.main(bench() + ["--execute"])
    out = capsys.readouterr().out
    assert code != 0
    assert "could not run" in out
    assert "An unrunnable check is not a passed check" in out


# ---------------------------------------------------------------------------
# skipped is a reported category
# ---------------------------------------------------------------------------


def test_todo_rows_are_skipped_and_reported_not_silently_dropped(bench, wired,
                                                                 capsys):
    rows = []
    for i in range(4):
        r = dict(GOOD_ROW)
        r["status"] = "todo"
        r["asset_slug"] = f"{SLUG}-{i}"
        r["file"] = f"masters/{r['asset_slug']}.png"
        r["sha256"] = ""            # recomputed by write_files
        rows.append(r)
    code = ia.main(bench(rows=rows))
    out = capsys.readouterr().out
    assert code == 0            # skipping is not an error
    assert "SKIPPED (4)" in out
    assert "status=todo" in out
    assert "ready 0" in out
    s3, db = wired
    assert s3.puts == [] and db.inserts == []


@pytest.mark.skipif(not REAL_MANIFEST.exists(),
                    reason="the package manifest is not on this machine")
def test_the_real_manifest_reports_the_svg_row_as_skipped(tmp_path, work_order,
                                                          wired, capsys):
    """drona-illustrations-v1.1 is 112 accepted rows and ONE svg-queue row.

    Replaces a test written against the superseded Downloads work order, which
    was 48 rows at status=todo in the two-file schema. That package is gone;
    asserting against it measured nothing.

    The skip is the point: a status this command does not ingest is a category
    with a count and a named reason, not silence. The 112 refuse here only
    because this fixture points --dir at a temp folder with none of the files
    in it — what is being measured is the SKIP, not the refusals.
    """
    code = ia.main(["ingest", "--dir", str(tmp_path), "--manifest",
                    str(REAL_MANIFEST), "--work-order", work_order,
                    "--generator-model", "gemini-3-pro-image"])
    out = capsys.readouterr().out
    assert code != 0
    assert "SKIPPED (1)" in out
    assert f"not marked '{ia.APPROVED_STATUS}'" in out
    s3, db = wired
    assert s3.puts == [] and db.inserts == []

def test_every_real_slug_passes_slug_validation():
    """The double hyphen must survive. 50 double-hyphen runs across 48 rows."""
    rows = [r for r in csv.DictReader(REAL_MANIFEST.open())
            if r["status"] == ia.APPROVED_STATUS]
    assert len(rows) == 112, "drona-illustrations-v1.1 is 112 accepted assets"
    doubles = 0
    for r in rows:
        ia.validate_slug(r["asset_slug"])          # raises on failure
        doubles += r["asset_slug"].count("--")
    assert doubles >= 40, "the double hyphen carries a colon or comma"
    # And the filenames are exactly slug + suffix, which is what the R2 key
    # mirrors.
    for r in rows:
        assert r["file"] == "masters/" + r["asset_slug"] + ".png"


# ---------------------------------------------------------------------------
# dry run is the default; ordering; idempotency
# ---------------------------------------------------------------------------


def test_dry_run_is_the_default_and_writes_nothing(bench, wired, capsys):
    code = ia.main(bench())
    out = capsys.readouterr().out
    assert code == 0
    assert "DRY RUN" in out
    assert "READY (1)" in out
    s3, db = wired
    assert s3.puts == [] and db.inserts == []


def test_execute_uploads_then_inserts(bench, wired, capsys):
    s3, db = wired
    code = ia.main(bench() + ["--execute"])
    out = capsys.readouterr().out
    assert code == 0
    assert s3.puts == [f"concept-assets/{SLUG}.png"]
    assert len(db.inserts) == 1
    row = db.inserts[0]
    assert row["asset_slug"] == SLUG
    assert row["licence"] == "generated-free"
    # And 0038's conditional: generated art carries no anchor plate.
    assert row["anchor_book"] is None
    assert row["author"] == "MonkLearning (AI-generated, Gemini)"
    assert row["generator_model"] == "gemini-3-pro-image"
    assert len(row["prompt_sha"]) == 16
    assert row["manifest_status"] == ia.APPROVED_STATUS
    assert row["arrived_labelled"] == "unlabelled"
    assert "uploaded" in out


def test_only_the_master_is_uploaded(bench, wired):
    """The labelled file is verified and hashed, never stored."""
    s3, db = wired
    assert ia.main(bench() + ["--execute"]) == 0
    assert s3.puts == [f"concept-assets/{SLUG}.png"]
    assert not any(".labelled." in k for k in s3.objects)
    row = db.inserts[0]
    # raw/, not a labelled sibling: the reference is what the master was made
    # from, recorded by name and hash and never uploaded.
    assert row["labelled_reference_file"] == f"raw/{SLUG}.png"
    assert len(row["labelled_reference_sha256"]) == 64


def test_syllabus_gap_is_null_not_empty(bench, wired):
    """NULL means nobody looked. '{}' would assert a check that never happened."""
    s3, db = wired
    assert ia.main(bench() + ["--execute"]) == 0
    assert db.inserts[0]["syllabus_gap"] is None
    assert db.inserts[0]["syllabus_gap"] != []


def test_failed_upload_writes_no_row(bench, monkeypatch, capsys):
    import app.db as appdb
    import app.storage_r2 as r2

    s3, db = FakeS3(fail_put=True), FakeDB()
    monkeypatch.setattr(r2, "get_client", lambda: s3)
    monkeypatch.setattr(r2, "assets_bucket_name", lambda: "monk-illustrations")
    monkeypatch.setattr(appdb, "supabase", db)

    code = ia.main(bench() + ["--execute"])
    err = capsys.readouterr().err
    assert code != 0
    # The whole reason the upload goes first: no row may point at nothing.
    assert db.inserts == []
    assert "UPLOAD FAILED" in err
    assert "No row was written" in err


def test_failed_insert_names_the_orphaned_object(bench, monkeypatch, capsys):
    import app.db as appdb
    import app.storage_r2 as r2

    s3, db = FakeS3(), FakeDB(fail_write=True)
    monkeypatch.setattr(r2, "get_client", lambda: s3)
    monkeypatch.setattr(r2, "assets_bucket_name", lambda: "monk-illustrations")
    monkeypatch.setattr(appdb, "supabase", db)

    code = ia.main(bench() + ["--execute"])
    err = capsys.readouterr().err
    assert code != 0
    assert "ORPHANED OBJECT" in err
    assert "monk-illustrations" in err              # named, not described
    assert f"concept-assets/{SLUG}.png" in err


def test_reingest_updates_rather_than_duplicating(bench, wired, capsys):
    s3, db = wired
    args = bench() + ["--execute"]
    assert ia.main(args) == 0
    capsys.readouterr()
    # Second attempt is the normal case, not the error case.
    assert ia.main(args) == 0
    assert len(db.inserts) == 1
    assert len(db.updates) == 1
    assert len(db.rows) == 1
    assert s3.puts == [f"concept-assets/{SLUG}.png"] * 2


def test_a_refusal_does_not_block_the_good_rows(bench, wired, capsys):
    good = dict(GOOD_ROW)
    bad = dict(GOOD_ROW)
    bad["asset_slug"] = SLUG + "-two"
    bad["file"] = f"masters/{bad['asset_slug']}.png"
    bad["licence"] = "unknown"
    code = ia.main(bench(rows=[good, bad]) + ["--execute"])
    out = capsys.readouterr().out
    s3, db = wired
    assert len(db.inserts) == 1                    # the good one landed
    assert "REFUSED (1)" in out
    assert code != 0                               # and the run still fails


# ---------------------------------------------------------------------------
# storage-independent helpers
# ---------------------------------------------------------------------------


def test_licence_enum_has_no_sharealike_or_nc_member():
    for member in ia.LICENCE_ENUM:
        parts = member.upper().split("-")
        assert "SA" not in parts, member
        assert "NC" not in parts, member


def test_placeholder_detection_is_case_and_space_insensitive():
    assert ia.is_placeholder("  UNKNOWN ")
    assert ia.is_placeholder("")
    assert ia.is_placeholder(None)
    assert ia.is_placeholder("N/A")
    assert ia.is_placeholder("public domain")
    assert not ia.is_placeholder("OpenStax College")
    assert not ia.is_placeholder("gemini-3-pro-image")   # a real model id


def test_sniff_ignores_the_extension():
    assert ia.sniff_content_type(b"\x89PNG\r\n\x1a\n" + b"x" * 40) == "image/png"
    assert ia.sniff_content_type(b"\xff\xd8\xff\xe0" + b"x" * 40) == "image/jpeg"
    assert ia.sniff_content_type(
        b"RIFF" + b"\x00" * 4 + b"WEBP" + b"x" * 40) == "image/webp"
    with pytest.raises(ia.Refusal):
        ia.sniff_content_type(b"just some text, honestly")


def test_object_key_mirrors_the_manifest_filename():
    import app.storage_r2 as r2

    assert r2.asset_object_key(SLUG, "unlabelled", "image/png") == \
        f"concept-assets/{SLUG}.png"
    assert r2.asset_object_key(SLUG, "labelled", "image/png") == \
        f"concept-assets/{SLUG}.labelled.png"
    # A file named .png that is really a JPEG lands as .jpg.
    assert r2.asset_object_key(SLUG, "unlabelled", "image/jpeg") == \
        f"concept-assets/{SLUG}.jpg"


def test_assets_bucket_never_falls_back_to_the_doubts_bucket(monkeypatch):
    import app.storage_r2 as r2

    monkeypatch.setenv("R2_ENDPOINT_URL",
                       "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "s")
    monkeypatch.setenv("R2_DOUBTS_BUCKET_NAME", "monk-doubts")
    monkeypatch.delenv("R2_ASSETS_BUCKET_NAME", raising=False)
    with pytest.raises(r2.R2NotConfigured) as err:
        r2.assets_bucket_name()
    assert "student PII" in str(err.value)


def test_prompt_sha_moves_with_the_work_order(tmp_path):
    p = tmp_path / "wo.md"
    p.write_text("figure 1")
    a = ia.prompt_sha(str(p))
    p.write_text("figure 1 and 2")
    b = ia.prompt_sha(str(p))
    assert a != b and len(a) == len(b) == 16
    # prompt_version failed by being a sha over ALL prompts: it moved when an
    # unrelated file moved. This one hashes exactly the document that specifies
    # these figures.
    (tmp_path / "unrelated.md").write_text("something else")
    assert ia.prompt_sha(str(p)) == b


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def _row(slug, key, size=2048, **kw):
    r = {"id": slug, "asset_slug": slug, "r2_key": key, "bytes": size,
         "width": 1600, "height": 1000, "content_type": "image/png",
         "licence": "PD-old-70", "author": "Monk Learning",
         "arrived_labelled": "unlabelled", "subject": "biology",
         "text_check": "ocr-clean", "syllabus_gap": []}
    r.update(kw)
    return r


def _verify_with(monkeypatch, rows, objects, public=None):
    """`verify` against fake storage.

    `public` stubs the anonymous public-read leg, which is a REAL network call
    in production and must not be one here. Default: the bucket is correctly
    public (404 on the absent probe, CORS present) and every object in `objects`
    is reachable — so these tests keep measuring the storage leg they were
    written for, and the public leg gets its own tests below.
    """
    import app.db as appdb
    import app.storage_r2 as r2

    s3 = FakeS3(objects=objects)
    monkeypatch.setattr(r2, "get_client", lambda: s3)
    monkeypatch.setattr(r2, "assets_bucket_name", lambda: "monk-illustrations")
    monkeypatch.setattr(appdb, "fetch_all", lambda t, c, **kw: rows)
    monkeypatch.setenv("ASSETS_PUBLIC_BASE_URL", "https://assets.example.test")

    def default_public(url: str):
        key = url.split("assets.example.test/", 1)[-1]
        return (404, "*") if "__probe-not-present__" in key else (
            (200, "*") if key in objects else (404, "*"))

    monkeypatch.setattr(ia, "public_head", public or default_public)
    return ia.main(["verify"])


def test_verify_clean(monkeypatch, capsys):
    code = _verify_with(monkeypatch, [_row("a", "concept-assets/a.png")],
                        {"concept-assets/a.png": b"x" * 2048})
    assert code == 0
    assert "OK on storage" in capsys.readouterr().out


def test_verify_reports_a_row_with_no_object(monkeypatch, capsys):
    code = _verify_with(monkeypatch, [_row("a", "concept-assets/a.png")], {})
    out = capsys.readouterr().out
    assert code != 0
    assert "DANGLING ROWS" in out
    assert "render time" in out


def test_verify_reports_an_object_with_no_row(monkeypatch, capsys):
    code = _verify_with(monkeypatch, [],
                        {"concept-assets/stray.png": b"x" * 2048})
    out = capsys.readouterr().out
    assert code != 0
    assert "ORPHANED OBJECTS" in out
    assert "concept-assets/stray.png" in out


def test_verify_reports_a_size_mismatch(monkeypatch, capsys):
    code = _verify_with(monkeypatch,
                        [_row("a", "concept-assets/a.png", size=999)],
                        {"concept-assets/a.png": b"x" * 2048})
    out = capsys.readouterr().out
    assert code != 0
    assert "SIZE MISMATCH" in out


def test_verify_counts_the_two_soft_backlogs(monkeypatch, capsys):
    rows = [_row("a", "concept-assets/a.png",
                 text_check="heuristic-clean-ocr-unavailable",
                 syllabus_gap=None)]
    code = _verify_with(monkeypatch, rows, {"concept-assets/a.png": b"x" * 2048})
    out = capsys.readouterr().out
    assert code == 0                     # not storage problems
    assert "TEXT CHECK INCONCLUSIVE (1 of 1)" in out
    assert "SYLLABUS GAP NOT YET CHECKED (1 of 1)" in out
    assert "nobody has looked" in out


# ---------------------------------------------------------------------------
# the text detector, measured rather than asserted
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAVE_FONTS, reason="needs system fonts to render text")
def test_text_probe_measured_behaviour():
    """Reproduces the numbers quoted in scripts/asset_text_probe.py.

    Including the two blind spots. A detector whose stated weaknesses have no
    failing fixture is a detector described rather than measured — that is the
    font-floor assertion that was live for one commit and matched nothing.
    """
    from PIL import Image, ImageDraw, ImageFont

    # MEASURES THE SHAPE HEURISTIC, and now says so.
    #
    # This asserted 20/20 through `probe()`, which was true only while no OCR
    # engine was installed — `probe` short-circuits to OCR when one is, and OCR
    # is LESS sensitive on this synthetic aged-paper corpus. Swept over every
    # threshold, OCR tops out at 16/20 here, while scoring 0 false positives on
    # the 112 real masters where the heuristic scored 29.
    #
    # So the two are measured separately, because they are separately true:
    # the heuristic's sensitivity is pinned here, and OCR's precision is what
    # `probe()` refuses on. Asserting one number through a function that may
    # run either detector measures whichever happened to be installed.
    def detected(images):
        return sum(1 for d in images if probe.find_text_like(d))

    # Detected: ordinary labels, and labels crossed by the drawing's strokes.
    normal = [plate(100 + i, n_words=6) for i in range(20)]
    assert detected(normal) == 20, "ordinary horizontal labels must be caught"

    # Not detected: no text at all, and rows of similar small structures.
    clean = [plate(300 + i) for i in range(20)]
    assert detected(clean) == 0, "clean plates must not false-positive"

    def cell_row(seed):
        im = Image.new("L", (1600, 1000), 232)
        d = ImageDraw.Draw(im)
        for r in range(4):
            for c in range(14):
                x, y = 120 + c * 95, 200 + r * 180
                d.ellipse([x, y, x + 38, y + 52], outline=35, width=2)
                d.ellipse([x + 14, y + 20, x + 24, y + 30], fill=35)
        b = io.BytesIO()
        im.convert("RGB").save(b, format="PNG")
        return b.getvalue()

    assert detected([cell_row(i) for i in range(10)]) == 0, \
        "a row of cells is not a word"

    # BLIND SPOT 1: single-character labels are below MIN_GLYPHS_PER_WORD by
    # construction. This assertion documents a real hole, on purpose.
    def singles(seed):
        im = Image.new("L", (1600, 1000), 232)
        d = ImageDraw.Draw(im)
        f = ImageFont.truetype(FONTS[0], 28)
        for i, ch in enumerate("ABCDEFGH"):
            d.text((80 + i * 180, 400), ch, fill=25, font=f)
        b = io.BytesIO()
        im.convert("RGB").save(b, format="PNG")
        return b.getvalue()

    assert detected([singles(i) for i in range(5)]) == 0, \
        "single characters are NOT detected — this is the documented blind spot"

    # BLIND SPOT 2: display text escapes the strict tier, and is picked up by
    # the advisory tier as a warning rather than a refusal.
    def title(seed):
        im = Image.new("L", (1600, 1000), 232)
        d = ImageDraw.Draw(im)
        d.text((200, 400), "THE COCKROACH", fill=25,
               font=ImageFont.truetype(FONTS[0], 90))
        b = io.BytesIO()
        im.convert("RGB").save(b, format="PNG")
        return b.getvalue()

    # THE HEURISTIC's strict tier misses display text; that is the documented
    # blind spot and it is still true of the heuristic.
    assert not probe.find_text_like(title(0)), \
        "display text escapes the heuristic's STRICT tier"

    # OCR DOES NOT MISS IT, and that is the point of it being the authority:
    # 'THE COCKROACH' at 90 pt reads back at 90% confidence. A blind spot the
    # old detector documented is simply closed, and the test says so rather
    # than asserting the weakness is still there.
    t = probe.probe(title(0))
    assert t.found_text, "OCR must catch display text the heuristic misses"
    assert "COCKROACH" in (t.ocr_text or "")


def test_probe_never_returns_a_bare_boolean():
    """'No text found' and 'no text present' are different statements."""
    r = probe.probe(plate(1))
    assert r.verdict in probe.VERDICTS
    # WHICH DETECTOR SPOKE is the point, and the answer now depends on the
    # environment: with tesseract installed the verdict is conclusive, and
    # without it the run falls back to the heuristic and says so. Both are
    # real answers; a bare boolean would be neither.
    if probe._ocr(plate(1)) is not None:
        assert r.verdict in ("ocr-clean", "ocr-found-text")
        assert r.is_conclusive
    else:
        assert r.verdict == "heuristic-clean-ocr-unavailable"
        assert not r.is_conclusive
        assert "ABSENCE OF EVIDENCE" in r.detail


# ── the public leg: what the APP sees, with no credential ───────────────────

def test_verify_fails_when_public_read_is_off(monkeypatch, capsys):
    """The failure every other check in this command is blind to.

    Object present, row present, sizes agree — and every figure blank on every
    device, because the bucket stopped being public. An S3 listing cannot see
    it: the credential still works.
    """
    code = _verify_with(
        monkeypatch, [_row("a", "concept-assets/a.png")],
        {"concept-assets/a.png": b"x" * 2048},
        public=lambda url: (403, ""),
    )
    out = capsys.readouterr().out
    assert code != 0
    assert "PUBLIC READ IS OFF" in out
    assert "blank" in out


def test_verify_fails_when_cors_is_missing(monkeypatch, capsys):
    """Fetches from curl, fails from the app — the most confusing shape of all,
    because a human checking by hand sees it working."""
    code = _verify_with(
        monkeypatch, [_row("a", "concept-assets/a.png")],
        {"concept-assets/a.png": b"x" * 2048},
        public=lambda url: (404, "") if "__probe" in url else (200, ""),
    )
    out = capsys.readouterr().out
    assert code != 0
    assert "Access-Control-Allow-Origin" in out


def test_verify_fails_when_an_object_is_present_but_not_public(monkeypatch, capsys):
    """Per row, not just the bucket. One object can be unreachable while the
    bucket is public — a botched key, or an object uploaded with the wrong
    ACL."""
    def public(url: str):
        if "__probe" in url:
            return 404, "*"
        return 403, "*"

    code = _verify_with(
        monkeypatch, [_row("a", "concept-assets/a.png")],
        {"concept-assets/a.png": b"x" * 2048}, public=public)
    out = capsys.readouterr().out
    assert code != 0
    assert "unreachable by the app" in out


def test_verify_says_so_when_the_public_leg_was_not_checked(monkeypatch, capsys):
    """No base URL is not a pass. "Nothing checked whether the app can fetch
    this art" is a different statement from "the app can fetch this art"."""
    import app.db as appdb
    import app.storage_r2 as r2

    s3 = FakeS3(objects={"concept-assets/a.png": b"x" * 2048})
    monkeypatch.setattr(r2, "get_client", lambda: s3)
    monkeypatch.setattr(r2, "assets_bucket_name", lambda: "monk-illustrations")
    monkeypatch.setattr(appdb, "fetch_all", lambda t, c, **kw: [_row("a", "concept-assets/a.png")])
    monkeypatch.delenv("ASSETS_PUBLIC_BASE_URL", raising=False)
    ia.main(["verify"])
    assert "PUBLIC LEG UNVERIFIED" in capsys.readouterr().out


# ── renditions: the @2x the client picks on every frame ─────────────────────

def _png(w, h, mode="RGB"):
    import io as _io
    from PIL import Image
    im = Image.new(mode, (w, h), "white")
    # a hard edge, so a resampler that blurs or staircases has something to do
    for x in range(w // 2):
        for y in range(h // 3):
            im.putpixel((x, y), (10, 40, 200) if mode == "RGB" else (10, 40, 200, 255))
    b = _io.BytesIO(); im.save(b, format="PNG"); return b.getvalue()


def test_a_rendition_is_exactly_twice_the_master():
    import io as _io
    from PIL import Image
    out = ia.make_rendition(_png(896, 500))
    with Image.open(_io.BytesIO(out)) as im:
        assert im.size == (1792, 1000)


def test_a_master_at_the_threshold_gets_no_rendition():
    """Not "a rendition that happens to be the same size" — None, so the caller
    uploads one object rather than two identical ones."""
    assert ia.make_rendition(_png(1600, 900)) is None
    assert ia.make_rendition(_png(2000, 1200)) is None


def test_a_palette_png_is_converted_before_resampling():
    """A palette image resampled in place quantises the interpolated pixels
    back to the original palette — the staircasing LANCZOS is here to avoid.
    The fix is invisible in the output size, so it is asserted on the mode."""
    import io as _io
    from PIL import Image
    src = Image.open(_io.BytesIO(_png(896, 500))).convert("P")
    b = _io.BytesIO(); src.save(b, format="PNG")
    out = ia.make_rendition(b.getvalue())
    with Image.open(_io.BytesIO(out)) as im:
        assert im.mode in ("RGBA", "RGB"), f"resampled while still paletted: {im.mode}"


def test_the_rendition_key_is_a_suffix_not_a_directory():
    """A bucket listing must sort a master and its rendition adjacent."""
    assert ia.rendition_key("concept-assets/x.png") == "concept-assets/x@2x.png"
    # And a slug containing dots or dashes is not mangled.
    assert (ia.rendition_key("concept-assets/bio11-ch7-frog--a.png")
            == "concept-assets/bio11-ch7-frog--a@2x.png")


def test_generating_a_rendition_does_not_touch_the_master():
    """The standing constraint. make_rendition takes BYTES and returns bytes;
    it must have no path to the file the manifest pinned a sha256 of."""
    import hashlib
    data = _png(896, 500)
    before = hashlib.sha256(data).hexdigest()
    ia.make_rendition(data)
    assert hashlib.sha256(data).hexdigest() == before


# ── OCR is the refusal authority: two committed controls ────────────────────
#
# Crops of ONE real plate and its raw, checked in under tests/fixtures/ rather
# than read from the 224-file package: a test that points at content is a test
# that breaks when content is re-cut, and these two must keep meaning the same
# thing for as long as the threshold does.

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_ocr_reads_real_labels_off_the_raw_plate():
    """POSITIVE CONTROL. Without this the bar could be raised to infinity and
    every test would still pass — 'no text found' and 'no text present' are
    different statements, and only one of them is evidence.

    The crop is the label column of the cockroach gut raw, which arrived with
    its terms burnt in.
    """
    r = probe.probe((FIXTURES / "gut-raw-labels.png").read_bytes())
    assert r.verdict == "ocr-found-text", r.detail
    assert r.found_text is True
    tokens = [w for w in (r.ocr_text or "").split() if len(w) >= 4 and w.isalpha()]
    assert len(tokens) >= 8, f"expected >= 8 legible tokens, got {len(tokens)}: {tokens}"
    # Real anatomy, not noise: these are the words a student would read.
    assert {"Pharynx", "Gizzard", "Midgut"} <= set(tokens), tokens


def test_ocr_reads_nothing_off_the_same_region_of_the_master():
    """NEGATIVE CONTROL, and the same pixels as the positive one minus the
    labels. This is the plate the old character-count bar refused over
    'Oseppe' at 0% confidence in a box 394 pixels tall."""
    r = probe.probe((FIXTURES / "gut-master-clean.png").read_bytes())
    assert r.found_text is False, r.detail
    assert r.verdict == "ocr-clean"


def test_the_ocr_bar_is_not_lowered_below_the_agreed_floor():
    """The threshold is a decision, not a tuning knob. >= 4 alphabetic
    characters at >= 60% confidence, agreed after showing the strings."""
    assert probe.OCR_MIN_CONF >= 60
    assert probe.OCR_MIN_TOKEN_LEN >= 4


def test_the_shape_heuristic_advises_and_cannot_veto():
    """It scores 20/20 on the synthetic benchmark and produced 29 false
    refusals on 112 real masters. So it still runs when OCR is clean, and what
    it finds is recorded as ADVISORY — countable and reviewable, never a
    refusal."""
    data = (FIXTURES / "gut-master-clean.png").read_bytes()
    r = probe.probe(data)
    assert r.found_text is False
    # If the heuristic fires on this plate it must say so without vetoing.
    if r.words:
        assert "ADVISORY" in r.detail
        assert r.verdict == "ocr-clean"


def test_ocr_sensitivity_is_pinned_on_the_synthetic_benchmark():
    """12 of 20 on THIS benchmark, at the agreed bar. Measured, not hoped for.

    OCR is LESS sensitive than the shape heuristic on aged-paper synthetics —
    the heuristic gets 20/20 here. No threshold closes that gap: swept over
    conf 30..60 x length 3..5, OCR tops out well short of 20. That is the whole
    reason the heuristic still runs as an ADVISORY when OCR is clean.

    The trade is deliberate and the real corpus is why. On the 112 v1.1 masters
    the heuristic produced 29 false refusals and OCR produced 0, while OCR
    still caught all 15 labelled raws. Precision is what a refusal needs;
    sensitivity is what an advisory is for.

    Pinned so a regression BELOW the measured number is visible. If this rises,
    raise the number.
    """
    labelled = [plate(100 + i, n_words=6) for i in range(20)]
    caught = sum(1 for d in labelled if (r := probe._ocr(d)) is not None
                 and r.verdict == "ocr-found-text")
    assert caught >= 12, f"OCR caught {caught}/20, below the measured 12"
