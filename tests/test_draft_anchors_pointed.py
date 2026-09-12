"""The pointing script refuses what it cannot check, and writes nothing when it does.

Three cases, as specified: one file with a bad term, one with a point outside
the plate, and one clean file. Everything is synthetic — a generated master, a
generated draft and a generated manifest — so the test says what the SCRIPT
does rather than what today's content happens to contain.

The refusal cases assert that NOTHING was written, not merely that the exit
code was non-zero. A script that refuses loudly and still leaves a
half-written draft behind has the failure this one exists to prevent.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "draft_anchors_pointed.py"


def _load():
    spec = importlib.util.spec_from_file_location("draft_anchors_pointed", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["draft_anchors_pointed"] = mod
    spec.loader.exec_module(mod)
    return mod


SLUG = "bio11-ch9-testplate--structure--a"
CONCEPT = "bio11-ch9-testplate--structure"
TERMS = ["nucleus", "cell wall", "vacuole"]


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A master, a draft and a manifest that agree with each other."""
    mod = _load()

    # Master: white paper with ink only in the middle third, so "outside the
    # content box" is a real region and not a rounding artefact.
    art = tmp_path / "master.png"
    img = Image.new("RGB", (800, 600), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([200, 150, 600, 450], fill=(40, 40, 40))
    img.save(art)

    drafts = tmp_path / "label-drafts"
    drafts.mkdir()
    (drafts / f"{SLUG}.draft.json").write_text(json.dumps({
        "asset_slug": SLUG, "image_w": 800, "image_h": 600, "schema_version": 1,
        "labels": [
            {"id": "nucleus", "text": {"en": "nucleus", "hi": "nucleus"},
             "anchor": [0.4, 0.4], "side": "auto"},
            {"id": "cell-wall", "text": {"en": "cell wall", "hi": "cell wall"},
             "anchor": [0.5, 0.5], "side": "auto"},
            {"id": "vacuole", "text": {"en": "vacuole", "hi": "vacuole"},
             "anchor": None, "side": "auto"},
        ],
        "_draft": {"generated_by": "test", "unplaced": ["vacuole"]},
    }), encoding="utf-8")

    manifest = tmp_path / "illustration-manifest.csv"
    manifest.write_text(
        "asset_slug,ncert_labels\n" + f"{CONCEPT},\"{', '.join(TERMS)}\"\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "DRAFTS", drafts)
    monkeypatch.setattr(mod, "DEFAULT_MANIFEST", manifest)
    monkeypatch.setattr(mod, "DEFAULT_MOBILE", tmp_path / "mobile")
    return mod, tmp_path, art, manifest, drafts


def _run(mod, points, tmp_path, art, manifest, extra=()):
    p = tmp_path / "points.json"
    p.write_text(json.dumps(points), encoding="utf-8")
    argv = ["--set", SLUG, "--in", str(p), "--art", str(art),
            "--manifest", str(manifest), "--mobile", str(tmp_path / "mobile"), *extra]
    old = sys.argv
    sys.argv = ["draft_anchors_pointed.py", *argv]
    try:
        return mod.main()
    finally:
        sys.argv = old


def test_a_clean_file_is_accepted_and_writes_both_outputs(rig, capsys):
    mod, tmp, art, manifest, drafts = rig
    code = _run(mod, [
        {"term": "nucleus", "x": 0.4, "y": 0.4, "confidence": 0.9},
        {"term": "cell wall", "x": 0.55, "y": 0.6, "confidence": 0.8},
    ], tmp, art, manifest)
    assert code == 0

    out = drafts / f"{SLUG}.pointed.json"
    assert out.exists()
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["source"] == "gemini-pointed"
    # THE POINT OF THE WHOLE PIPELINE: never reviewed by a machine.
    assert "reviewed_by" not in written
    assert written["_draft"]["repointed"] == 2
    # The pointed anchors replaced the drafted ones.
    by_id = {l["id"]: l for l in written["labels"]}
    assert by_id["nucleus"]["anchor"] == [0.4, 0.4]
    assert by_id["cell-wall"]["anchor"] == [0.55, 0.6]
    # The unplaced one is untouched and still reported.
    assert by_id["vacuole"]["anchor"] is None
    assert "vacuole" in written["_draft"]["still_unplaced"]

    sheet = tmp / "mobile" / "content" / "illustrations" / "v1" / "reports" / "pointed" / f"{SLUG}.png"
    assert sheet.exists()


def test_a_term_outside_ncert_labels_is_refused_and_nothing_is_written(rig, capsys):
    mod, tmp, art, manifest, drafts = rig
    code = _run(mod, [
        {"term": "nucleus", "x": 0.4, "y": 0.4, "confidence": 0.9},
        {"term": "mitochondrion", "x": 0.5, "y": 0.5, "confidence": 0.9},
    ], tmp, art, manifest)
    assert code == 1

    text = capsys.readouterr().out
    assert "REFUSED" in text
    # Named by row AND by term, so the operator can fix the right line.
    assert "row 1" in text and "mitochondrion" in text
    assert "not in the concept's ncert_labels" in text
    # The GOOD row is not written either — the file is rejected whole.
    assert not (drafts / f"{SLUG}.pointed.json").exists()


def test_a_point_off_the_plate_is_refused_and_nothing_is_written(rig, capsys):
    mod, tmp, art, manifest, drafts = rig
    # (0.05, 0.05) is white paper: the ink starts at x=200/800 = 0.25.
    code = _run(mod, [
        {"term": "nucleus", "x": 0.05, "y": 0.05, "confidence": 0.9},
    ], tmp, art, manifest)
    assert code == 1

    text = capsys.readouterr().out
    assert "REFUSED" in text
    assert "row 0" in text and "nucleus" in text
    assert "outside the plate's content box" in text
    assert not (drafts / f"{SLUG}.pointed.json").exists()


def test_an_unplaced_term_needs_the_flag(rig, capsys):
    """`vacuole` is in ncert_labels and in the draft, but recorded unplaced.

    Strict by default, because `unplaced` means "on another sub-figure" in an
    SVG-authored draft. The flag opts into the other reading, per set.
    """
    mod, tmp, art, manifest, drafts = rig
    pts = [{"term": "vacuole", "x": 0.5, "y": 0.5, "confidence": 0.7}]

    assert _run(mod, pts, tmp, art, manifest) == 1
    assert "unplaced" in capsys.readouterr().out
    assert not (drafts / f"{SLUG}.pointed.json").exists()

    assert _run(mod, pts, tmp, art, manifest, extra=("--allow-unplaced",)) == 0
    written = json.loads((drafts / f"{SLUG}.pointed.json").read_text(encoding="utf-8"))
    assert {l["id"]: l["anchor"] for l in written["labels"]}["vacuole"] == [0.5, 0.5]


def test_pixel_coordinates_are_caught_rather_than_silently_wrapped(rig, capsys):
    mod, tmp, art, manifest, drafts = rig
    code = _run(mod, [{"term": "nucleus", "x": 320, "y": 240}], tmp, art, manifest)
    assert code == 1
    text = capsys.readouterr().out
    assert "not normalised 0..1" in text and "pixels?" in text
    assert not (drafts / f"{SLUG}.pointed.json").exists()


def test_the_truncated_manifest_slug_still_resolves(rig, tmp_path):
    """The real manifest cuts asset_slug at 70 characters.

    Measured on the pilot's own concept:
    'bio11-ch6-simple-permanent-tissues--parenchyma--collenchyma-and-sclere'
    is the stored value for '...-and-sclerenchyma'. An exact-match lookup
    finds nothing, so the prefix fallback is what makes the first three pilot
    sets runnable at all.
    """
    mod, tmp, art, manifest, drafts = rig
    truncated = tmp / "truncated.csv"
    truncated.write_text(
        "asset_slug,ncert_labels\n" + f"{CONCEPT[:20]},\"{', '.join(TERMS)}\"\n",
        encoding="utf-8",
    )
    assert mod.terms_for(truncated, CONCEPT) == TERMS


def test_two_manifest_rows_that_could_both_match_are_refused(rig, tmp_path):
    """Guessing between two rows is how a figure gets the wrong term list."""
    mod, tmp, art, manifest, drafts = rig
    ambiguous = tmp / "ambiguous.csv"
    ambiguous.write_text(
        "asset_slug,ncert_labels\n"
        f"{CONCEPT[:20]},\"a, b\"\n"
        f"{CONCEPT[:25]},\"c, d\"\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as e:
        mod.terms_for(ambiguous, CONCEPT)
    assert "could be" in str(e.value)
