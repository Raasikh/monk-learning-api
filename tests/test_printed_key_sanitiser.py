"""A page that prints no key must not manufacture one.

The structuring model was asked for JSON null and wrote the STRING "null" —
which then passed every truthiness check as a real printed key, disagreed
with a correct derivation of 6x10^8 N/m^2, and got that answer withheld with
a card reading 'the answer printed on the page is "null"'.
"""

from app.snap import _real_printed_key


def test_the_junk_strings_a_model_writes_for_nothing():
    for junk in ("null", "None", "NONE", "nil", "N/A", "na", "-", "–", "—",
                 "(null)", "?", "", "  ", None):
        assert _real_printed_key(junk) is None, junk


def test_real_keys_survive():
    for key in ("D", "2", "B, C", "44.1", "6 × 10^8"):
        assert _real_printed_key(key) == key


def test_whitespace_is_trimmed_not_fatal():
    assert _real_printed_key("  C ") == "C"
