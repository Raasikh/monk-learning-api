"""The step being written, extracted from a JSON stream still arriving.

`step` frames carry only COMPLETED steps, so the first one cannot reach the
phone before the model's last token of step one — the board sat blank while
the teacher composed. `_partial_step` reads the tail of the buffer instead:
the one unterminated "text" string is the step mid-write.
"""

from app.snap import _partial_step


def test_reads_the_step_mid_write():
    buf = '{"spoken": "done line", "steps": [{"n": 1, "text": "Divide both sides'
    assert _partial_step(buf) == (1, "Divide both sides")


def test_a_finished_step_is_not_a_partial():
    buf = '{"steps": [{"n": 1, "text": "done."}'
    assert _partial_step(buf) is None


def test_the_second_step_wins_once_the_first_closes():
    buf = '{"steps": [{"n": 1, "text": "done."}, {"n": 2, "text": "now this'
    assert _partial_step(buf) == (2, "now this")


def test_the_spoken_line_is_never_mistaken_for_a_step():
    assert _partial_step('{"spoken": "still being writ') is None
    assert _partial_step("") is None


def test_escapes_inside_the_text_survive():
    buf = '{"steps": [{"n": 1, "text": "the \\"same\\" voltage'
    assert _partial_step(buf) == (1, 'the "same" voltage')


def test_a_half_escape_at_the_boundary_is_dropped_not_shown():
    # A chunk ending mid-escape must not leak a bare backslash or half a
    # unicode escape onto the board.
    assert _partial_step('{"steps": [{"n": 1, "text": "ends with \\\\')[1] == "ends with "
    assert _partial_step('{"steps": [{"n": 2, "text": "half \\\\u00A')[1] == "half "


def test_a_complete_unicode_escape_is_kept():
    got = _partial_step('{"steps": [{"n": 1, "text": "pi \\\\u03c0 next')
    assert got == (1, "pi π next")
