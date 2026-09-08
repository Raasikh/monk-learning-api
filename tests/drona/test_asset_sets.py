"""Sub-asset sets: the ordered set, and the cue that picks from it.

drona-illustrations-v1 delivers 112 assets across 48 concepts. Cockroach
morphology is a 2-asset set; connective tissue and Phylum Arthropoda are 6.
Before this, slot 3 asked for ONE asset with `.limit(1)` and no `order by`, so a
six-plate concept got whichever row Postgres returned first — a wrong figure
chosen at random per process, on a board, with nothing to say so.
"""
import pytest

from app.drona.tutor import figure_letter, resolve_figure


def A(sub_index: int, slug: str = None):
    return {"sub_index": sub_index,
            "asset_slug": slug or f"concept--{figure_letter(sub_index)}",
            "concept_slug": "concept"}


SIX = [A(i) for i in range(6)]


def test_the_letter_is_derived_not_stored():
    """0036 has no figure_letter column on purpose: two fields that can
    disagree about one fact is the defect this subsystem keeps producing."""
    assert [figure_letter(i) for i in range(6)] == ["a", "b", "c", "d", "e", "f"]


def test_no_cue_gives_figure_a():
    got, why = resolve_figure(SIX, None)
    assert got["asset_slug"].endswith("--a")
    assert why == "no cue"


def test_a_cue_picks_its_member():
    got, why = resolve_figure(SIX, "d")
    assert got["sub_index"] == 3
    assert why == "cue d"


def test_the_cue_is_case_and_space_insensitive():
    """Content is authored by a model; ' C ' is the same cue as 'c' and
    refusing it would blank a board over whitespace."""
    for cue in ("C", " c ", "c"):
        got, _ = resolve_figure(SIX, cue)
        assert got["sub_index"] == 2, cue


@pytest.mark.parametrize("cue", ["z", "g", "ab", "1", "", "  "])
def test_an_unresolvable_cue_falls_back_and_says_so(cue):
    """THE WHOLE CONTRACT. A segment may cue a figure the set does not have,
    because a row was refused at ingest. It must show figure a and explain —
    never blank the board. A wrong figure and no figure are both worse than the
    default one, and the student is owed a picture either way."""
    got, why = resolve_figure(SIX, cue)
    assert got is SIX[0]
    if cue.strip():
        assert "using figure a" in why


def test_the_fallback_names_what_the_set_actually_has():
    """A reason that does not say what WAS available cannot be acted on."""
    _, why = resolve_figure([A(0), A(1)], "e")
    assert "cue e not in set [a,b]" in why


def test_an_empty_set_is_no_illustration_not_a_crash():
    """A concept with no art must fall to the next tier, not raise."""
    got, why = resolve_figure([], "a")
    assert got is None and why == "empty set"


def test_a_gap_in_the_set_still_resolves_by_ordinal():
    """If figure b was refused at ingest, the set is [a, c]. Cueing c must find
    c — not the second element. Index and ordinal are different things, and
    conflating them is how a refused row silently shifts every later figure."""
    gapped = [A(0), A(2)]
    got, why = resolve_figure(gapped, "c")
    assert got["sub_index"] == 2 and why == "cue c"
    # And b, which really is absent, falls back rather than picking c.
    got_b, why_b = resolve_figure(gapped, "b")
    assert got_b is gapped[0] and "not in set [a,c]" in why_b


def test_the_default_is_the_lowest_ordinal_not_the_first_row():
    """The DB orders by sub_index, but resolve_figure must not depend on the
    caller having done that — the default is figure a, whoever hands it over."""
    got, _ = resolve_figure([A(3), A(0), A(1)], None)
    assert got["sub_index"] == 0
