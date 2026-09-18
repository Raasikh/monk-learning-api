"""The store is the source of truth; the markdown is rendered from it.

Reading verdicts out of prose failed FOUR times in two sessions, and every
failure had the same shape — a regex that matched nothing and returned a clean
empty result rather than raising:

  1. a row's key built from the widget stored NOW, not the one judged;
  2. `**objective:**` is lowercase in the chem sheet, so a case-sensitive match
     found ZERO objectives for physics and chem (29 rows);
  3. bio's table abbreviates the subtopic (`decomposition`) while its prose
     spells it out (`decomposition-and-its-steps`) — 4 of 17 found;
  4. three bio headers truncate the key outright (`ecological-succession-...`).

These tests exist so the direction cannot quietly flip back.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

STORE = REPO / "content/sane-rows.json"
SHEET = REPO / "scripts/sane_proposals.md"
BUCKETS = ("carried", "reconfirm", "superseded", "unkeyable")


@pytest.fixture(scope="module")
def doc():
    return json.loads(STORE.read_text())


def test_the_rendered_sheet_round_trips_to_the_store_byte_for_byte():
    """`--check` re-renders from the store and compares to the file on disk.

    This is the whole guarantee: the markdown carries no fact the store does
    not have. A hand-edit fails here, naming the command that regenerates it.
    """
    r = subprocess.run([sys.executable, "scripts/render_sane_sheet.py", "--check"],
                       cwd=str(REPO), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_rendering_is_deterministic():
    """Same store, same bytes — twice. A renderer that iterated a set would
    round-trip against itself once and fail on someone else's machine."""
    out = [subprocess.run([sys.executable, "scripts/render_sane_sheet.py"],
                          cwd=str(REPO), capture_output=True, text=True).stdout
           for _ in range(2)]
    assert out[0] == out[1]


def test_no_script_parses_the_markdown_any_more():
    """The four regex failures all lived in code that read this file.

    `render_sane_sheet.py` WRITES it and `--check` reads it only to compare
    against freshly rendered bytes; the migration is refused while the store
    exists. Nothing else may open it.
    """
    allowed = {"render_sane_sheet.py", "sane_migrate_final.py"}
    offenders = []
    for py in (REPO / "scripts").glob("*.py"):
        if py.name in allowed:
            continue
        src = py.read_text()
        # Look for ACCESS, not mention. A docstring that explains why this file
        # no longer parses the sheet is exactly what we want to keep; the first
        # version of this test flagged that docstring and would have pushed the
        # next person to delete the explanation to get green.
        import re as _re
        for line in src.splitlines():
            if "sane_proposals.md" not in line:
                continue
            if _re.search(r"(open|read_text|read|load|Path|glob|parse)\s*\(", line):
                offenders.append(f"{py.name}: {line.strip()[:70]}")
    assert not offenders, "these still touch the generated sheet:\n" + "\n".join(offenders)


def test_the_migration_refuses_to_run_while_the_store_exists():
    r = subprocess.run([sys.executable, "scripts/sane_migrate_final.py", "--write"],
                       cwd=str(REPO), capture_output=True, text=True)
    assert r.returncode == 1
    assert "REFUSED" in r.stdout


def test_every_row_carries_the_key_and_the_buckets_are_disjoint(doc):
    seen = {}
    for b in BUCKETS:
        for e in doc[b]:
            assert e["verdict"] in ("y", "n")
            if b == "unkeyable":
                assert not e.get("objective", "").strip()
                continue
            assert e["verdict_key"].count(":") == 1
            sha, widget = e["verdict_key"].split(":")
            assert len(sha) == 16 and widget
            legacy = e["legacy_key"]
            assert legacy not in seen, f"{legacy} appears in {seen.get(legacy)} and {b}"
            seen[legacy] = b


def test_the_counts_block_matches_the_buckets(doc):
    assert doc["_counts"] == {b: len(doc[b]) for b in BUCKETS}
    assert sum(doc["_counts"].values()) == 294


def test_a_reworded_row_carries_the_words_that_changed(doc):
    """A reconfirm is only cheaper than a re-judgement if it says what moved."""
    assert doc["reconfirm"], "no reworded rows to check"
    for e in doc["reconfirm"]:
        assert e["changed_words"], e["legacy_key"]
        assert 0.9 < e["similarity"] <= 1.0


def test_the_original_reviewer_prose_was_archived_not_deleted():
    """The generated sheet cannot reproduce the reviewer's long-form analysis,
    so overwriting it in place would have destroyed the human record."""
    archived = list((REPO / "content/archive").glob("sane-proposals-*-original.md"))
    assert archived, "the pre-migration sheet is not archived anywhere"
    assert archived[0].stat().st_size > 100_000
