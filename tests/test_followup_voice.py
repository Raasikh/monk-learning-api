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
