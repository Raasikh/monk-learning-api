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
        ("physics", 12, "Electric Charges and Fields", 75.0),
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


def test_the_precompute_consults_the_gate_BEFORE_paying_for_a_payload():
    src = Path("app/drona/planner.py").read_text()
    block = src[src.index("def _attach_widget_payload("):]
    block = block[:block.index("\ndef ")]
    gate = block.index("widget_baking_allowed")
    call = block.index("client.chat.completions.create")
    assert gate < call, ("the hold-back must be checked before the model call; "
                         "a held-back chapter should not pay for a payload it "
                         "will throw away")
