"""A term added to the REPO manifest is visible to pointing, with no other step.

Two copies of a term list can disagree, and twice they did. Adding the blood
terms (erythrocyte, leucocyte, platelet, plasma) and then the nematocyst terms
to the repo manifest left `draft_anchors_pointed` still reading a copy in
~/Downloads, so a term that WAS in the list came back "not in the concept's
ncert_labels". That failure reads as a content problem and is a path problem,
which is the worst way round.
"""
import csv
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location(
    "dap", REPO / "scripts" / "draft_anchors_pointed.py")
dap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dap)


def test_the_default_manifest_is_the_version_controlled_one():
    m = dap.DEFAULT_MANIFEST
    assert m.exists(), f"{m} is not on disk"
    # The specific path that caused the bug must not be reachable by default.
    assert "Downloads" not in str(m), f"default manifest is still {m}"
    assert m.is_relative_to(Path.home() / "Desktop" / "monk-learning-mobile")


def test_a_term_added_to_the_repo_list_is_visible_to_pointing(tmp_path):
    """Write a term into a COPY of the repo manifest and read it straight back.

    The copy is the point: this asserts the reading path, not the file. If
    `terms_for` ever grows a second source again, the term written here will
    not come back and this fails.
    """
    src = dap.DEFAULT_MANIFEST
    rows = list(csv.DictReader(src.open(encoding="utf-8")))
    fields = list(rows[0].keys())
    concept = "bio11-ch7-connective-tissue--types-and-matrix"
    sentinel = "zzz-sentinel-term"

    touched = 0
    for r in rows:
        slug = (r.get("asset_slug") or "").strip()
        if slug and (slug.startswith(concept) or concept.startswith(slug)):
            r["ncert_labels"] = (r["ncert_labels"] or "") + f", {sentinel}"
            touched += 1
    assert touched, "no manifest row for the concept under test"

    copy = tmp_path / "illustration-manifest.csv"
    with copy.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    assert sentinel in dap.terms_for(copy, concept)
    # And the real list does NOT have it — the test did not leak.
    assert sentinel not in dap.terms_for(src, concept)


def test_the_blood_terms_are_actually_in_the_repo_list():
    """The regression that started this: added once, invisible for an hour."""
    got = dap.terms_for(dap.DEFAULT_MANIFEST,
                        "bio11-ch7-connective-tissue--types-and-matrix")
    for t in ("erythrocyte", "leucocyte", "platelet", "plasma"):
        assert t in got, f"{t} missing from the repo term list"
