"""The hold-back is a RESOLUTION-time question, and this is why.

It lived in the planner for one day and did two things nobody asked for:

  * it skipped AUTHORING, so a held chapter stored nothing and a regenerated
    plan came back empty. physics 12 "Electromagnetic Waves" lost 8 payloads
    that rendered perfectly.
  * it lived in planner.py, so every change to the GATE moved
    `planner_code_sha` and invalidated every PLAN in the corpus. A policy
    about what may be SHOWN had been wired into the identity of how plans are
    BUILT.

Moved to `resolve_board_slot` on Raasikh's option (a), 2026-09-15.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.drona import sane_hold_back as hb      # noqa: E402
from app.drona.tutor import resolve_board_slot  # noqa: E402

HELD = ("physics", 12, "Electric Charges and Fields")     # 80.0%, below the bar
STORED = {"widget": "field_lines", "version": 2, "params": {}}


@pytest.fixture(autouse=True)
def _fresh():
    hb.reset_cache(); hb._OVERRIDE = None
    yield
    hb.reset_cache(); hb._OVERRIDE = None


def _allowed(subject, cls, chapter):
    return hb.widget_baking_allowed(subject, cls, chapter)[0]


def test_a_held_chapter_resolves_PAST_both_widget_slots():
    """`inert` has to mean inert. A stored precomputed payload in a held
    chapter is exactly the unreviewed picture the bar exists to keep off the
    board, and it sits in the HIGHEST slot — so the gate withholds slot 1 as
    well as slot 2, not just the archetype one."""
    assert _allowed(*HELD) is False
    assert resolve_board_slot(precomputed_widget=STORED, archetype_widget="field_lines",
                              illustration_asset="bio11-ch7-frog--a",
                              widget_allowed=False) == "illustration"
    assert resolve_board_slot(precomputed_widget=STORED,
                              precomputed_svg="<svg/>",
                              widget_allowed=False) == "svg_precomputed"
    assert resolve_board_slot(precomputed_widget=STORED,
                              widget_allowed=False) == "svg_live"


def test_flipping_the_verdict_resolves_to_the_widget_with_NO_regeneration():
    """The payload is the same object before and after. Nothing is re-authored,
    nothing is written, and `planner_code_sha` is not involved at all — which
    is the entire point of moving the gate out of the planner."""
    before = resolve_board_slot(precomputed_widget=STORED, widget_allowed=_allowed(*HELD))
    assert before == "svg_live"

    hb._OVERRIDE = {hb._key(*HELD): 85.0}          # a reviewer raises the chapter
    after = resolve_board_slot(precomputed_widget=STORED, widget_allowed=_allowed(*HELD))
    assert after == "widget_precomputed"

    # the payload was never touched by any of this
    assert STORED == {"widget": "field_lines", "version": 2, "params": {}}


def test_a_cleared_chapter_resolves_to_its_widget_ABOVE_an_illustration():
    """No real chapter clears the bar today — chem is the closest at 83.2% —
    so the cleared case is exercised through the override rather than by
    pinning a chapter that would then silently stop testing this the moment a
    verdict moved."""
    hb._OVERRIDE = {hb._key("chemistry", 12, "Aldehydes, Ketones & Carboxylic Acids"): 89.0}
    assert _allowed("chemistry", 12, "Aldehydes, Ketones & Carboxylic Acids") is True
    assert resolve_board_slot(archetype_widget="reaction_scheme",
                              illustration_asset="something",
                              widget_allowed=True) == "widget_archetype"


def test_the_gate_cannot_delete_anything_because_it_is_a_pure_function():
    """Stated as a test because the previous placement COULD delete, and did.
    `resolve_board_slot` takes values and returns a string; there is no path
    from here to a write."""
    import inspect
    src = inspect.getsource(resolve_board_slot)
    for forbidden in ("supabase", "update(", "delete(", "insert(", "pop(", "del "):
        assert forbidden not in src, f"resolve_board_slot touches {forbidden!r}"


def test_the_planner_no_longer_carries_the_gate():
    """If the gate returns to planner.py, `planner_code_sha` starts churning on
    policy changes again and the whole corpus re-authors. It has done that
    once."""
    src = Path("app/drona/planner.py").read_text()
    assert "widget_baking_allowed" not in src
    assert "held_back" not in src


def test_authoring_is_not_gated_so_a_held_chapter_still_STORES_payloads():
    """Option (a): payloads are authored and stored for every eligible routed
    row whatever the verdict says. The bar decides what is SHOWN, never what is
    kept."""
    src = Path("app/drona/planner.py").read_text()
    block = src[src.index("def _attach_widget_payload("):]
    block = block[:block.index("\ndef ")]
    assert "sane" not in block.lower(), \
        "the authoring path must not consult the verdict at all"
