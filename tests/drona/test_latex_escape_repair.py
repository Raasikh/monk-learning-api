r"""LaTeX commands that json.loads silently eats as string escapes.

`\neq` written inside a JSON string is VALID JSON — `\n` is a legal escape — so
the parser yields a newline followed by "eq" and nothing downstream can tell
that apart from a real line break. A saved Integrals note rendered exactly
that: a broken line with a stray "eq" sitting on it. sanitize_double_escaped_latex
could never have caught it, because the damage happened before it ran.

The same trap catches every command whose first letter is a JSON escape:
\theta and \times (tab), \rho and \rightarrow (carriage return), \beta and
\bar (backspace), \frac and \forall (form feed), \vec (vertical tab), \alpha
and \approx (bell).
"""

import json

import pytest

from app.drona.json_utils import repair_latex_control_escapes as repair


def test_the_reported_note_case():
    # Byte-for-byte the payload shape that produced the broken note.
    raw = r'{"latex": "\\int x^n \\, dx = \\dfrac{x^{n+1}}{n+1} + C, \\quad n \neq -1"}'
    broken = json.loads(raw)["latex"]
    assert "\n" in broken and "eq -1" in broken      # the corruption
    fixed = repair(broken)
    assert "\n" not in fixed
    assert fixed.endswith(r"\neq -1")


@pytest.mark.parametrize("broken,expected", [
    ("\theta = 30", r"\theta = 30"),
    ("2 \times 3", r"2 \times 3"),
    ("\frac{a}{b}", r"\frac{a}{b}"),
    ("\beta decay", r"\beta decay"),
    ("\alpha particle", r"\alpha particle"),
    ("\vec{F}", r"\vec{F}"),
    ("x \rightarrow 0", r"x \rightarrow 0"),
    ("\nabla \times B", r"\nabla \times B"),
])
def test_each_control_character_victim_is_restored(broken, expected):
    assert repair(broken) == expected


@pytest.mark.parametrize("text", [
    "line one\nnext we look at forces",   # \n + "next" — "ext" then a letter
    "step 1\nthen step 2",                # \n + "then"
    "result\nextra detail here",          # \n + "extra"
    "col a\tcol b",                       # a real tab between columns
    "para\n\nnew para",                   # blank line
    "",
])
def test_genuine_whitespace_is_never_touched(text):
    # An over-eager repair would corrupt ordinary prose, which is worse than
    # the bug: the guard is that a trailing letter blocks the match.
    assert repair(text) == text


def test_repair_is_idempotent():
    # It runs on every string in every plan; applying it twice must not
    # double-escape anything.
    once = repair("\theta and \frac{1}{2}")
    assert repair(once) == once


def test_plan_sanitizer_applies_the_repair():
    # The wiring, not just the helper: plan JSON is what reaches saved notes.
    from app.drona.planner import sanitize_double_escaped_latex
    broken = json.loads(r'{"board_content": ["x \neq 0", "\theta = 45"]}')
    out = sanitize_double_escaped_latex(broken)
    assert out["board_content"] == [r"x \neq 0", r"\theta = 45"]
