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
    assert re.search(r"if\s+_diag_hint\s*:", SRC)


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
