"""The per-turn directives must reach the model, not just exist in the prompt.

Three times in this project a behaviour was written into prompts/tutor.md as a
general rule, looked correct on the page, and was skipped by the model:

  * the worked-example offer — 0 of 3 subjects
  * the diagram trigger table — 2 of 4 subjects
  * (and a probe written against the prompt alone measured 0 of 4 diagrams,
    which nearly got reported as a product failure)

Each was fixed the same way: stop relying on the general rule and inject a
directive into THAT turn naming THAT template or THAT instruction. Diagrams
went 2/4 -> 4/4, worked examples 0/3 -> 3/3.

So the injection is the load-bearing part, and the prompt rule is decoration.
That is a fragile arrangement: if someone tidies the injection out of tutor.py,
prompts/tutor.md still reads correctly, every existing test still passes, and
diagrams silently stop appearing. Nothing would catch it.

This file catches it. It asserts the directives are BUILT and that they are
INTERPOLATED INTO THE MESSAGE — building a string and forgetting to include it
is the exact shape of the failure.
"""

import re
from pathlib import Path

import pytest

SRC = (Path(__file__).resolve().parents[2] / "app" / "drona" / "tutor.py").read_text()
PROMPT = (Path(__file__).resolve().parents[2] / "prompts" / "tutor.md").read_text()


@pytest.mark.parametrize("name", ["diagram_directive", "example_directive", "board_answer_ban"])
def test_the_directive_is_built(name):
    assert re.search(rf"^\s*{name} = ", SRC, re.M), f"{name} is no longer constructed"


@pytest.mark.parametrize("name", ["diagram_directive", "example_directive", "board_answer_ban"])
def test_the_directive_actually_reaches_the_message(name):
    """Built but not interpolated is the failure that looks fine in review.

    tutor.py assembles the user content in two places — the two turn shapes —
    and a directive added to one and not the other works on some turns and not
    others, which is worse than not working at all.
    """
    used = re.findall(rf"\{{{name}\}}", SRC)
    assert len(used) >= 2, (
        f"{name} is interpolated into {len(used)} message template(s); "
        f"tutor.py builds two, so it must appear in both"
    )


def test_the_diagram_directive_names_the_specific_template():
    """A generic "draw a diagram if useful" is what failed at 2/4.

    The directive has to carry the chosen template name into the turn, which
    means interpolating the cue result — not just mentioning diagrams.
    """
    start = SRC.index("diagram_directive = (")
    block = SRC[start:start + 900]
    assert "{_diag_hint}" in block, "the directive no longer names the chosen template"
    assert "DIAGRAM FOR THIS TURN" in block


def test_the_cue_still_feeds_the_directive():
    # suggest_diagram_template's result is what makes the directive specific.
    # If the two are decoupled, the cue fires into nothing.
    assert re.search(r"_diag_hint\s*=\s*suggest_diagram_template\(", SRC)
    assert re.search(r"if\s+_diag_hint\s+and\s+not\s+_precomputed_svg\s*:", SRC)


def test_the_two_diagram_tiers_cannot_both_fire():
    """A precomputed diagram suppresses the template directive.

    Both tiers producing a picture in one turn is worse than either alone — the
    board would carry two diagrams of the same idea, drawn differently, and the
    speech only introduces one. The suppression is the whole reason the tiers
    are ordered rather than merely both available.
    """
    assert re.search(r"if\s+_diag_hint\s+and\s+not\s+_precomputed_svg\s*:", SRC)
    # and the delivery side refuses to append over a diagram the model emitted
    idx = SRC.index("Tier 1 delivery")
    block = SRC[idx:idx + 700]
    assert 'e.get("type") == "diagram"' in block, "appends without checking for an existing one"


def test_the_precomputed_lookup_cannot_fail_a_lesson():
    """It runs on every turn, so it must be total.

    It also has to survive the table not existing — that is the state before
    migration 0029 is applied, and a lesson must not care.
    """
    idx = SRC.index("def _precomputed_diagram(")
    block = SRC[idx:SRC.index("\ndef ", idx + 10)]
    assert "try:" in block and "except Exception" in block
    assert "return None" in block


def test_the_prompt_rule_and_the_injection_both_exist():
    """Belt and braces, deliberately.

    The prompt rule alone does not produce diagrams — that is measured, not
    assumed. But it is what tells the model what the templates ARE and how to
    fill their params, so the injection alone would not work either. Both have
    to be present; this pins that neither gets removed as redundant.
    """
    assert "diagram" in PROMPT.lower()
    assert "diagram_directive = (" in SRC


def test_the_turn_summary_reports_which_cues_fired():
    """The log line that makes a missing diagram diagnosable.

    "The diagram didn't appear" has meant both "the cue never fired" and "the
    cue fired and the model ignored it", which need opposite fixes. The summary
    separates them, so it is part of the guardrail rather than nice-to-have.
    """
    assert "cues: diagram=" in SRC
    assert "emitted: diagram=" in SRC


def test_a_planned_turn_still_delivers_a_model_chosen_diagram():
    """The directive asks for a template on planned turns, so one must survive.

    On a turn with assigned plan items the model's board_events are discarded
    wholesale — correct for text, since authored lines beat improvised ones.
    But tier 2's ONLY delivery path used to be the branch for turns with no
    plan items, so on every ordinary explanation turn the cue fired, the
    directive was injected, the model emitted a template diagram, and it was
    dropped. Tier 2 looked implemented and never appeared on a board.

    A diagram is additive, not a replacement, so it is appended instead.
    """
    start = SRC.index("if assigned_items:")
    # anchored on the newline: a bare 8-space "else:" also matches the
    # deeper-indented else inside the item-type chain, truncating the slice.
    block = SRC[start:SRC.index("\n        else:", start)]
    assert "_materialise_template(e)" in block, (
        "the planned-turn branch no longer renders a model-chosen template; "
        "tier 2 is unreachable on ordinary explanation turns again"
    )
    assert 'e.get("type") != "diagram"' in block, "appends non-diagram events too"
    guard = block[block.index("if not any("):block.index("for e in (model_board_events")]
    assert '"diagram"' in guard, (
        "the append is not guarded on the board being diagram-free, so it can "
        "add a second picture over one the plan already carries"
    )


def test_tier_three_is_started_before_the_llm_call():
    """Started after it, it could never beat the board flush.

    A turn emits exactly ONE board_events event, so an authored figure that
    arrives after the flush cannot be sent at all. Running the authoring
    concurrently with the turn is the only thing that gives it a chance, which
    makes the ORDER of these two statements load-bearing rather than stylistic.
    """
    kick = SRC.index("start_live_diagram(")
    llm = SRC.index("diagram_directive = (")
    assert kick < llm, "tier 3 no longer starts before the turn is assembled"


def test_tier_three_only_fires_when_the_cheap_tiers_missed():
    """Paying a model call where an indexed read would have done is the waste."""
    idx = SRC.index("_live_diagram_future = None")
    block = SRC[idx:idx + 260]
    assert "not _precomputed_svg and not _diag_hint" in block


def test_tier_three_is_polled_never_awaited():
    """This runs inside the SSE generator.

    Blocking on the future would hold the board — and the speech queued behind
    it — for however long authoring takes, turning an enhancement into a
    regression on exactly the turns that have no diagram today.
    """
    idx = SRC.index("Tier 3 delivery")
    block = SRC[idx:idx + 900]
    assert "_live_diagram_future.done()" in block, "no readiness check before use"
    assert "result(timeout=0)" in block, "result() without timeout=0 can block"


def test_tier_three_stores_what_it_authors():
    """The half of tier 3 that does not depend on winning the race.

    Coverage grows along the paths students actually walk: a figure authored
    for one turn is served to every later turn on that concept from tier 1, in
    one indexed read. Without the store, tier 3 re-pays for the same figure on
    every session and 955 concepts stay uncovered forever.
    """
    idx = SRC.index("def _author_and_store(")
    block = SRC[idx:SRC.index("\ndef ", idx + 10)]
    assert 'table("concept_diagrams").insert' in block
    assert 'update({"active": False})' in block, "stores without retiring the old row"
    assert "_DIAGRAM_CACHE.pop" in block, (
        "the miss stays cached, so later turns never see the new figure"
    )


def test_tier_three_cannot_author_the_same_concept_twice_at_once():
    """Two sessions on one concept would store two active rows.

    The reader takes the newest active row blindly, so a duplicate is not
    merely wasteful — it makes which figure a student sees a race.
    """
    idx = SRC.index("def start_live_diagram(")
    block = SRC[idx:SRC.index("\ndef ", idx + 10)]
    assert "_LIVE_DIAGRAM_INFLIGHT" in block and "_LIVE_DIAGRAM_LOCK" in block
    assert "discard" in SRC[SRC.index("def _author_and_store("):idx], (
        "the in-flight marker is never cleared, so one failure blocks the "
        "concept for the life of the process"
    )
