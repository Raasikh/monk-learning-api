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


def test_a_runaway_keeps_its_closing_question():
    """The close is the LAST sentence, so trailing-first trimming deleted it.

    Seen live: 343 chars trimmed to 280 at the cap, and the dropped tail was
    "did you get that?" — the one sentence the prompt guarantees. The trim
    now sets the close aside first and spends the budget on explanation.
    """
    filler = "This sentence pads the explanation out well past the cap. "
    close = "Did you get that, or should I take it slower?"
    runaway = (filler * 8).strip() + " " + close
    assert len(runaway) > followup_voice.MAX_SPOKEN_CHARS

    out = followup_voice.cap_spoken(runaway)
    assert len(out) <= followup_voice.MAX_SPOKEN_CHARS
    assert out.endswith(close)
    assert out.startswith("This sentence")


def test_a_runaway_without_a_close_trims_as_before():
    filler = "This sentence pads the explanation out well past the cap. "
    out = followup_voice.cap_spoken((filler * 8).strip())
    assert len(out) <= followup_voice.MAX_SPOKEN_CHARS
    assert out.endswith(".")


def test_a_long_question_is_not_a_close():
    """More explanation with a question mark on it gets no protection."""
    filler = "This sentence pads the explanation out well past the cap. "
    long_q = ("But have you considered what happens to the equilibrium when "
              "the temperature rises and the pressure falls at the same time?")
    assert len(long_q) > followup_voice.MAX_CLOSE_CHARS
    out = followup_voice.cap_spoken((filler * 8).strip() + " " + long_q)
    assert not out.endswith(long_q)


def test_the_next_sentence_is_synthesised_while_this_one_plays():
    """Serial synthesis put a hole between sentences; one-ahead closes it.

    Sentence 2's synthesis must START while sentence 1 is still being made —
    not after it has been yielded — so the clip is ready by the time the
    player runs dry.
    """
    import asyncio
    import time as _time

    starts = {}

    async def slow_synth(sentence, preset):
        starts.setdefault(sentence, _time.monotonic())
        await asyncio.sleep(0.05)
        return b"\x00\x00" * 2400

    async def run():
        out = []
        real = followup_voice._synthesize
        followup_voice._synthesize = slow_synth
        try:
            text = ("The first sentence stands on its own feet here. "
                    "The second sentence is also long enough to be a clip.")
            async for idx, total, wav in followup_voice.speak_chunks(text, "female"):
                out.append((idx, total))
        finally:
            followup_voice._synthesize = real
        return out

    got = asyncio.run(run())
    assert [g[0] for g in got] == [1, 2]
    assert len(starts) == 2
    times = sorted(starts.values())
    # Started within one synthesis-length of each other: concurrent, not serial.
    assert times[1] - times[0] < 0.04
