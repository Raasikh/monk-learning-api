"""split_into_sentences batches short fragments to save TTS roundtrips, but a
question must never be batched: the client mounts the answer chips against the
audio chunk that carries the question, so a question glued onto the statement
before it put the quiz on screen well before it was spoken."""

from app.drona.voice_proxy import split_into_sentences


def test_question_is_never_glued_to_the_sentence_before_it():
    speech = (
        "In the vertical channel, gravity acts fully, so it's free fall under g. "
        "Now, here's a quick check: if you roll a ball off a table and drop another "
        "ball from the same height at the same instant, which one hits the ground first?"
    )
    chunks = split_into_sentences(speech)

    assert chunks[-1].startswith("Now, here's a quick check")
    assert chunks[-1].endswith("?")
    assert "quick check" not in chunks[-2]


def test_question_shorter_than_min_chars_still_stands_alone():
    chunks = split_into_sentences("Gravity pulls it down. Which one lands first?")
    assert chunks == ["Gravity pulls it down.", "Which one lands first?"]


def test_a_question_mid_turn_does_not_swallow_what_follows():
    chunks = split_into_sentences(
        "Which one lands first? Both land together, because the vertical drop is identical."
    )
    assert chunks[0] == "Which one lands first?"
    assert chunks[1].startswith("Both land together")


def test_statements_still_batch_to_save_tts_roundtrips():
    chunks = split_into_sentences(
        "Short one. Another short one. A third short fragment here to push the "
        "buffer past a hundred characters in total length."
    )
    assert len(chunks) == 1


def test_trailing_fragment_does_not_reopen_a_question_chunk():
    # The tail-merge folds a short leftover into the previous chunk. It must not
    # do that when the previous chunk is a question — that would re-create the
    # exact gluing this split exists to prevent.
    chunks = split_into_sentences("Which one hits the ground first? Take a moment.")
    assert chunks == ["Which one hits the ground first?", "Take a moment."]


def test_empty_text_yields_nothing():
    assert split_into_sentences("") == []
