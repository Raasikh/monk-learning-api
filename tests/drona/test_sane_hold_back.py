"""The hold-back, and the two ways it can be wrong.

It can hold back a chapter that should bake — that costs a cached picture and
the live path covers it. Or it can let through a chapter nobody has read —
that puts a permanent unchecked picture in the highest-precedence slot. The
second is the expensive one, so every test here is written to catch it.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.drona import sane_hold_back as hb  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh():
    hb.reset_cache()
    hb._OVERRIDE = None
    yield
    hb.reset_cache()
    hb._OVERRIDE = None


def test_the_adopted_verdicts_are_all_below_the_bar():
    """Not a tautology — it is the session's actual result, pinned.

    Raasikh adopted scripts/sane_proposals.md as verdicts and set the bar at
    85%. Every chapter the proposals cover scores below it, so precompute bakes
    NO widget anywhere. If a later edit to the verdicts file moves one of these
    over the bar, that is a decision someone should have to make on purpose,
    and this test is where they notice they made it.
    """
    for subject, cls, chapter, pct in [
        ("physics", 12, "Electric Charges and Fields", 80.0),
        ("mathematics", 12, "Application of Integrals", 43.7),
        ("chemistry", 12, "Aldehydes, Ketones & Carboxylic Acids", 83.2),
        ("biology", 12, "Ecosystem", 75.7),
    ]:
        assert hb.sane_percent(subject, cls, chapter) == pct
        allowed, why = hb.widget_baking_allowed(subject, cls, chapter)
        assert allowed is False, f"{chapter} would bake: {why}"
        assert "below the 85% bar" in why


def test_a_chapter_with_no_verdict_is_held_back_and_says_so():
    """UNMEASURED IS NOT A PASS. This is the check-that-passes-on-absent-
    information shape, and it is the one this project keeps finding."""
    allowed, why = hb.widget_baking_allowed("biology", 11,
                                            "Structural Organisation in Animals")
    assert allowed is False
    assert "unmeasured" in why
    # and it is DISTINGUISHABLE from a failing score, because the report has to
    # tell a chapter nobody read from a chapter that was read and fell short
    assert "below" not in why


def test_the_bar_is_inclusive_at_exactly_85():
    hb._OVERRIDE = {hb._key("x", 1, "c"): 85.0}
    allowed, why = hb.widget_baking_allowed("x", 1, "c")
    assert allowed is True and "clears" in why
    hb._OVERRIDE = {hb._key("x", 1, "c"): 84.99}
    assert hb.widget_baking_allowed("x", 1, "c")[0] is False


def test_an_unreadable_verdicts_file_holds_EVERYTHING_back(monkeypatch, tmp_path):
    """The failure that costs a cached picture, never the one that ships an
    unchecked one. A file that will not parse must not read as 'no
    restrictions'."""
    monkeypatch.setattr(hb, "_PATH", str(tmp_path / "does-not-exist.json"))
    hb.reset_cache()
    allowed, why = hb.widget_baking_allowed(
        "chemistry", 12, "Aldehydes, Ketones & Carboxylic Acids")
    assert allowed is False
    assert "unmeasured" in why
    assert hb.LOAD_ERROR, "a load failure must be RECORDED, not swallowed"


def test_the_verdicts_file_carries_the_confirmation_that_authorised_it():
    """A SANE verdict is a human judgement. The file that holds one has to
    carry the line that authorised it, or nobody can tell later whether these
    numbers were adopted or assumed."""
    doc = json.loads(Path(hb._PATH).read_text())
    assert doc["_confirmed_by"] == "raasikh"
    assert "adopt scripts/sane_proposals.md" in doc["_confirmation"]
    assert doc["_bar_percent"] == hb.SANE_BAR_PERCENT
    for v in doc["verdicts"]:
        assert v["verdict_by"] == "raasikh"
        assert v["proposed_y"] + v["proposed_n"] == v["rows"], v["chapter"]


def test_the_gate_is_NOT_in_the_planner_and_authoring_is_never_skipped():
    """This asserted the OPPOSITE until 2026-09-15.

    The gate was in the planner, in front of the model call, so a held chapter
    stored nothing. That skipped authoring — physics 12 "Electromagnetic Waves"
    lost 8 payloads that rendered — and it put a policy about what may be SHOWN
    into `planner_code_sha`, so every gate change invalidated every plan.

    Raasikh's option (a), 2026-09-15: author and store for every eligible row
    whatever the verdict says; hold back only at resolution. The test is kept
    rather than deleted, inverted, so the old placement cannot quietly return.
    """
    src = Path("app/drona/planner.py").read_text()
    assert "widget_baking_allowed" not in src
    assert "held_back" not in src
    tut = Path("app/drona/tutor.py").read_text()
    assert "widget_allowed" in tut, "the gate has to live in resolve_board_slot"


def test_the_verdicts_file_and_the_proposals_sheet_AGREE_on_every_value():
    """Two records of the same four numbers, and nothing stops them drifting
    except this.

    `content/sane-verdicts.json` is what the gate enforces;
    `scripts/sane_proposals.md` is what a person reads and what Raasikh's
    confirmation line actually adopted. They were already inconsistent once at
    one remove: batch6/DIRECTIVE.md quoted chem at 89.4% while the sheet it
    cited said 83.2%, and that gap is the whole difference between chem's
    widgets drawing and not drawing.
    """
    import re
    md = Path("scripts/sane_proposals.md").read_text()
    table = md[md.index("| sheet | rows | proposed y"):]
    table = table[:table.index("\n\n")]
    sheet_rows = {}
    for line in table.splitlines():
        m = re.match(r"\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|\s*\**(\d+)\**\s*\|\s*\**(\d+)\**\s*\|"
                     r"\s*\**([\d.]+)%\**\s*\|", line)
        if m:
            sheet_rows[m.group(1)] = (int(m.group(2)), int(m.group(3)),
                                      int(m.group(4)), float(m.group(5)))
    assert sheet_rows, "could not parse the counts table out of sane_proposals.md"

    doc = json.loads(Path(hb._PATH).read_text())
    for v in doc["verdicts"]:
        key = v["sheet"]
        assert key in sheet_rows, f"{key!r} is in the verdicts file but not the sheet"
        rows, y, n, pct = sheet_rows[key]
        assert (v["rows"], v["proposed_y"], v["proposed_n"]) == (rows, y, n), (
            f"{key}: verdicts file says {v['rows']}/{v['proposed_y']}/{v['proposed_n']}, "
            f"sheet says {rows}/{y}/{n}")
        assert abs(v["sane_percent"] - pct) < 0.05, (
            f"{key}: verdicts file {v['sane_percent']}%, sheet {pct}%")
        # and the percentage must be what the counts actually give
        assert abs(v["sane_percent"] - 100.0 * y / rows) < 0.06, (
            f"{key}: {y}/{rows} is {100.0 * y / rows:.1f}%, not {v['sane_percent']}%")


def test_the_reconciliation_left_chem_held_and_raised_physics():
    """The session's actual result, pinned against the directive's expectation.

    Session H expected chem at 89.4% (baking) and physics at 80% (held).
    Physics is 80%. Chem is NOT 89.4% — only one of its nineteen proposed-n
    rows was ever re-authored, because Session F fixed payloads that did not
    RENDER and this sheet judges whether the picture is RIGHT.
    """
    assert hb.sane_percent("physics", 12, "Electric Charges and Fields") == 80.0
    assert hb.sane_percent("chemistry", 12,
                           "Aldehydes, Ketones & Carboxylic Acids") == 83.2
    for s, c, ch in [("physics", 12, "Electric Charges and Fields"),
                     ("chemistry", 12, "Aldehydes, Ketones & Carboxylic Acids"),
                     ("biology", 12, "Ecosystem"),
                     ("mathematics", 12, "Application of Integrals")]:
        assert hb.widget_baking_allowed(s, c, ch)[0] is False
