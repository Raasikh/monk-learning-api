"""What the follow-up voice is allowed to say."""

from app import followup_voice




def test_cap_spoken_leaves_an_ordinary_answer_alone():
    """The cap is a backstop, not a style rule — it must not touch normal answers."""
    ordinary = (
        "The two resistors share the same voltage, so the bigger one takes less "
        "current. That is where the eight over twenty comes from."
    )
    assert len(ordinary) < followup_voice.MAX_SPOKEN_CHARS
    assert followup_voice.cap_spoken(ordinary) == ordinary


def test_cap_spoken_trims_a_runaway_at_a_sentence_boundary():
    """A long answer loses whole sentences, never half of one.

    Mid-clause truncation is worse than the verbosity it fixes: the voice sounds
    interrupted. The dropped part is on the board regardless.
    """
    sentence = "This sentence is here to pad the spoken line out past the cap. "
    runaway = (sentence * 8).strip()
    assert len(runaway) > followup_voice.MAX_SPOKEN_CHARS

    out = followup_voice.cap_spoken(runaway)
    assert len(out) <= followup_voice.MAX_SPOKEN_CHARS
    assert out.endswith(".")
    # Whole sentences only — no dangling fragment.
    assert "cap This" not in out.replace(". ", ". ")
    assert runaway.startswith(out.rstrip("."))


def test_cap_spoken_keeps_a_single_over_long_sentence():
    """Better a long opener than silence: one sentence over the cap still speaks."""
    one = "and so on " * 60
    out = followup_voice.cap_spoken(one)
    assert out.strip()


def test_cap_spoken_handles_empty():
    assert followup_voice.cap_spoken("") == ""
    assert followup_voice.cap_spoken(None) == ""


def test_a_long_first_sentence_splits_at_a_clause_break():
    """The first clip is the whole wait; a clause break is a free cut point."""
    text = ("The current divides in inverse proportion, so the larger "
            "resistor carries less of it and the smaller one carries more. "
            "That is the whole idea.")
    sentences = followup_voice._spoken_sentences(text)
    assert len(sentences[0]) <= followup_voice.FIRST_CLIP_MAX_CHARS
    # Nothing lost: the pieces reassemble to the original words.
    rebuilt = " ".join(sentences).replace("  ", " ")
    for word in ("divides", "proportion", "carries", "whole idea"):
        assert word in rebuilt


def test_a_short_first_sentence_is_left_alone():
    sentences = followup_voice._spoken_sentences(
        "Because it starts at 200. The graph shows why, look at the origin there."
    )
    assert sentences[0] == "Because it starts at 200."


def test_no_clause_break_means_no_split():
    one = "x" * 30 + " " + "y" * 60  # long, but no comma anywhere
    assert followup_voice._split_first_clip(one) == [one]


def test_a_break_beyond_the_window_still_beats_no_split():
    """Comma at 90 chars on a 144-char sentence: half the silence is a win."""
    sentence = ("The current divides between the two resistors in inverse "
                "proportion to their total resistance, so the larger one "
                "carries much less of it")
    pieces = followup_voice._split_first_clip(sentence)
    assert len(pieces) == 2
    assert len(pieces[0]) < len(sentence)
    assert pieces[0].endswith("resistance,")
