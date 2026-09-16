"""History truncation must never leave a cliff the model walks off.

A hard [:600] slice ended a turn inside `$-5\\,\\text{` and the model
COMPLETED the formula instead of answering — its whole reply was
"{V}$ and the cathode…", unparseable, and deterministic on every retry
because the phone resends the same history.
"""

from app.snap import _clean_cut


def test_short_text_is_untouched():
    assert _clean_cut("short and sweet", 600) == "short and sweet"


def test_cuts_at_a_sentence_and_says_so():
    text = ("The anode sits at zero volts here. " * 30).strip()
    out = _clean_cut(text, 200)
    assert len(out) <= 203
    assert out.endswith("…")
    assert out.rstrip("… ").endswith(".")


def test_never_ends_inside_mathematics():
    text = ("The drop is found from $V_A - V_K = 0 - (-5)$ and then "
            "the cathode is pulled to $-5\\,\\text{V}$ through the resistor "
            "so the junction is forward biased across the whole range.")
    for limit in range(40, len(text), 7):
        out = _clean_cut(text, limit)
        assert out.rstrip("… ").count("$") % 2 == 0, (limit, out)


def test_a_spaceless_wall_still_cuts():
    out = _clean_cut("x" * 900, 600)
    assert len(out) <= 602
