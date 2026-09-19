"""Order disputes are decided by code, never by a small model's coin flip.

Measured live: the stepcheck model inverted (I4, I5) on the exact swap the
override exists for, and answered confidently where order was
unestablishable. On a permutation dispute its LABEL is ignored; its MAPPING
plus the stem's own ordering decide, or nobody overrides at all.
"""

from app.snap import _is_permutation_dispute, _option_parts, _resolve_ordered_dispute

ALPHA_OPTS = [
    {"label": "A", "text": "proton, neutron, positron"},
    {"label": "B", "text": "neutron, positron, proton"},
    {"label": "C", "text": "proton, positron, neutron"},
    {"label": "D", "text": "positron, proton, neutron"},
]
RESISTOR_OPTS = [
    {"label": "1", "text": "8/5 A, 2/5 A"},
    {"label": "4", "text": "2/5 A, 8/5 A"},
]


def test_permutation_disputes_are_recognised():
    assert _is_permutation_dispute(ALPHA_OPTS, ["A"], ["B"])
    assert _is_permutation_dispute(RESISTOR_OPTS, ["1"], ["4"])
    # Different CONTENT is the checker's home turf — not a permutation case.
    opts = [{"label": "B", "text": "tetrahedral, square planar"},
            {"label": "D", "text": "octahedral, tetrahedral"}]
    assert not _is_permutation_dispute(opts, ["B"], ["D"])
    # Single-part options can never be an order dispute.
    single = [{"label": "1", "text": "proton"}, {"label": "2", "text": "neutron"}]
    assert not _is_permutation_dispute(single, ["1"], ["2"])


def test_the_alpha_mapping_resolves_to_a():
    stem = ("Bombardment of aluminum by alpha-particle leads to disintegration "
            "in two ways. Products X, Y and Z respectively are,")
    mapping = {"X": "proton", "Y": "neutron", "Z": "positron"}
    assert _resolve_ordered_dispute(stem, mapping, ALPHA_OPTS) == "A"


def test_the_resistor_mapping_resolves_the_swap_correctly():
    """The original bug, decided by evidence instead of the coin."""
    stem = "In the network shown, the currents I4 and I5 respectively are:"
    mapping = {"I4": "2/5 A", "I5": "8/5 A"}
    assert _resolve_ordered_dispute(stem, mapping, RESISTOR_OPTS) == "4"


def test_unknowns_missing_from_the_stem_resolve_nothing():
    stem = "The two currents in the network respectively are:"
    mapping = {"I4": "2/5 A", "I5": "8/5 A"}
    assert _resolve_ordered_dispute(stem, mapping, RESISTOR_OPTS) is None


def test_an_ambiguous_match_resolves_nothing():
    stem = "The values of P and Q respectively are:"
    mapping = {"P": "2", "Q": "2"}
    opts = [{"label": "1", "text": "2, 2"}, {"label": "2", "text": "2, 2 exactly"}]
    assert _resolve_ordered_dispute(stem, mapping, opts) is None


def test_option_parts_split_on_the_real_separators():
    assert _option_parts("proton, neutron and positron") == [
        "proton", "neutron", "positron"]
    assert _option_parts("2/5 A; 8/5 A") == ["2/5 A", "8/5 A"]
