"""`$` in board prose is currency, and the old check had that exactly backwards.

WHAT HAPPENED
-------------
`validate_plan_json` demanded an EVEN number of `$` in `board_content`, on the
assumption that `$` opens and closes inline maths. Measured against
`latexToText` -- the converter every board prose line actually goes through in
`app/live-classroom.tsx` -- the truth is inverted:

    "US $33 trillion per year"              1 dollar   INTACT on the board
    "US $33 trillion vs US $18 trillion"    2 dollars  BOTH SYMBOLS DELETED
    "$33 tn, $18 tn, $2 tn, $5 tn"          4 dollars  ALL DELETED

An odd count is the ONLY safe shape: with no closing delimiter the client
prints the symbol. An even count hands `indexOf` a partner, the text between
two prices is converted as maths, and the currency disappears. The check
rejected the shape that worked and admitted every shape that corrupts.

It cost a whole lesson. "Ecosystem Services and Their Economic Valuation" is
the one NEET concept whose subject IS money -- its chunks carry "US $33
trillion" and "~US $18 trillion" on nearly every page. Segment 5 landed an odd
count and the plan died: nine of ten Ecosystem concepts precomputed, and this
one had no lesson at all.

WHAT REPLACED IT
----------------
The parity rule is gone, and the client stopped eating a `$` followed by a
digit (monklearning-mobile lib/latex-text.ts, pinned by
lib/__tests__/currency-not-math.test.ts). What is refused instead is the
contract planner_segment.md actually states: formulas go in a `formula` event's
own `latex` field, undelimited. A `$` wrapping a LaTeX command means the author
reached for the wrong mechanism, which is worth refusing -- unlike a price.
"""
import pytest

from app.drona.planner import validate_plan_json


def _plan(board_line: str, segments: int = 6) -> dict:
    """One board line under test, padded with five that carry no `$`.

    THE PADDING MATTERS AND THE FIRST VERSION OF IT BROKE THIS FILE. Repeating
    `board_line` six times to satisfy the 6-item minimum multiplies its dollar
    count by six, so every ODD count becomes EVEN and the old parity rule
    passed every case here. The falsification run caught it: restoring the
    deleted rule left all eight tests green, which is the "check that passes on
    absent information" shape these tests exist to describe.

    So the line appears EXACTLY ONCE and the padding is dollar-free.
    """
    seg = {
        "objective": "o",
        "teaching_notes": "t",
        "board_content": (
            [{"seq": 1, "type": "text", "text": board_line, "emphasis": "normal"}]
            + [{"seq": i + 2, "type": "text", "text": f"filler line {i}",
                "emphasis": "normal"} for i in range(5)]
        ),
        "checkpoint": {
            "question": "q", "model_answer": "a", "rubric": "r",
            "expected_misconceptions": ["m1", "m2"],
        },
    }
    return {
        "segments": [dict(seg) for _ in range(segments)],
        "wrapup_points": ["w"] * segments,
    }


@pytest.mark.parametrize("line", [
    # The exact shape that killed the Ecosystem Services plan.
    "Ecosystem services are worth about US $33 trillion a year",
    # Even counts, which the old rule allowed and which are the ones the client
    # used to corrupt. They are safe now and must stay accepted.
    "US $33 trillion vs global GNP US $18 trillion",
    "$33 tn services, $18 tn GNP, $2 tn forests, $5 tn soil",
    "The figure everyone quotes is $33",
])
def test_a_price_on_the_board_is_not_a_plan_error(line):
    validate_plan_json(_plan(line))


@pytest.mark.parametrize("line", [
    "Area of the patch is $\\pi r^2$ here",
    "Productivity $\\dfrac{GPP}{NPP}$ matters",
])
def test_latex_wrapped_in_dollars_is_still_refused(line):
    """The real misuse, and the only thing this check now exists for."""
    with pytest.raises(ValueError, match="wraps LaTeX"):
        validate_plan_json(_plan(line))


def test_the_refusal_names_the_right_mechanism():
    """A rejection that does not say what to do instead just gets retried."""
    with pytest.raises(ValueError) as exc:
        validate_plan_json(_plan("Area is $\\pi r^2$"))
    msg = str(exc.value)
    assert "`latex` field" in msg and "planner_segment.md" in msg


def test_prose_with_no_dollars_at_all_is_untouched():
    """The overwhelmingly common case, asserted so the regex cannot start
    rejecting ordinary sentences without a test noticing."""
    validate_plan_json(_plan("Decomposers break detritus into inorganic nutrients"))


def _events(*items) -> dict:
    """A segment whose board_content is the given board events, padded to six."""
    evts = list(items) + [
        {"seq": len(items) + i + 1, "type": "text", "text": f"filler {i}",
         "emphasis": "normal"} for i in range(max(0, 6 - len(items)))
    ]
    seg = {
        "objective": "o", "teaching_notes": "t", "board_content": evts,
        "checkpoint": {"question": "q", "model_answer": "a", "rubric": "r",
                       "expected_misconceptions": ["m1", "m2"]},
    }
    return {"segments": [dict(seg) for _ in range(6)], "wrapup_points": ["w"] * 6}


def test_a_dollar_cannot_pair_across_two_board_events():
    """Two events are two lines on the board; a delimiter cannot span them.

    The first cut of this check stringified the whole board_content list, so a
    `$` in one event found its "partner" in a later one and the captured span
    ran through the JSON in between. It killed the Ecosystem Services plan a
    SECOND time, on a message quoting `'emphasis': 'key'}, {'seq': 5` as though
    that were maths.
    """
    validate_plan_json(_events(
        {"seq": 1, "type": "text", "text": "Costanza priced them at US $33 trillion",
         "emphasis": "key"},
        {"seq": 2, "type": "text", "text": "against a global GNP of US $18 trillion",
         "emphasis": "normal"},
    ))


def test_a_formula_events_latex_field_may_be_full_of_backslashes():
    """The field is FOR LaTeX. Scanning it for backslashes rejected every
    legitimate formula, which is how the second failure got its message."""
    validate_plan_json(_events(
        {"seq": 1, "type": "formula", "latex": "\\dfrac{GPP - R}{GPP}",
         "emphasis": "key"},
    ))


def test_a_latex_field_carrying_its_own_dollar_delimiter_is_refused():
    """The mirror image of the prose rule: that field is undelimited."""
    with pytest.raises(ValueError, match="undelimited"):
        validate_plan_json(_events(
            {"seq": 1, "type": "formula", "latex": "$\\dfrac{a}{b}$", "emphasis": "key"},
        ))


def test_an_escaped_dollar_in_a_latex_field_is_correct_content():
    r"""`\$` is LaTeX's literal dollar, and it is how a formula prices something.

    This chapter's own formula is
    `\text{Value of services} \approx \$33 \text{ trillion/yr}` -- correct
    LaTeX, and lib/latex-text.ts already emits the bare character for it.
    Refusing it failed the Ecosystem Services plan a THIRD time, on content
    that was right. Only an UNESCAPED `$` is a delimiter.
    """
    validate_plan_json(_events(
        {"seq": 1, "type": "formula",
         "latex": "\\text{Value of services} \\approx \\$33 \\text{ trillion/yr}",
         "emphasis": "key"},
    ))


def test_an_unescaped_dollar_in_a_latex_field_is_still_refused():
    """The escape carve-out must not swallow the rule it is carved out of."""
    with pytest.raises(ValueError, match="undelimited"):
        validate_plan_json(_events(
            {"seq": 1, "type": "formula",
             "latex": "$\\text{Value} \\approx \\$33$", "emphasis": "key"},
        ))
