"""A failed turn apologises for the right thing.

This exists because of a measured production failure. On 2026-09-10 every
teaching turn failed (DeepSeek renamed the model it echoes; see
tests/drona/test_model_echo.py), and every one of them said:

    "I didn't quite catch that — could you say it once more?"

to students who had not spoken a word. The mobile client sends a synthetic
`"Begin lesson segment"` utterance to start a class, `failure_speech` switched
on "is the utterance string non-empty", and so an outage on our side was
voiced as the student's microphone being bad — on every turn, for hours.

The rule is now provenance, not emptiness: blame the audio only when audio is
what produced the turn.
"""
import pytest

from app.drona.persona import AUDIO_UNCLEAR, TURN_INTERRUPTED, failure_speech

LANGS = ["english", "hinglish"]


@pytest.mark.parametrize("lang", LANGS)
def test_real_speech_is_asked_to_repeat(lang):
    # The one legitimate AUDIO_UNCLEAR case: a PTT transcript drove the turn,
    # so asking the student to say it again is the right request.
    assert failure_speech(lang, True) == AUDIO_UNCLEAR[lang]


@pytest.mark.parametrize("lang", LANGS)
def test_synthetic_kickoff_is_not_blamed_on_the_student(lang):
    # THE FAILING FIXTURE for the 2026-09-10 outage. The client's
    # "Begin lesson segment" is a non-empty utterance and is not speech; under
    # the old emptiness rule this returned AUDIO_UNCLEAR.
    assert failure_speech(lang, False) == TURN_INTERRUPTED[lang]


@pytest.mark.parametrize("lang", LANGS)
def test_auto_started_teaching_turn_owns_the_failure(lang):
    # Teaching turns launch with an empty utterance; the student is listening.
    assert failure_speech(lang, False) == TURN_INTERRUPTED[lang]


def test_a_tapped_answer_chip_is_not_audio():
    # A chip tap sends a non-empty utterance and involves no microphone at
    # all. "Could you say it once more?" to someone who tapped a button reads
    # as broken. The old rule got this wrong too — it was never only about
    # the kick-off.
    assert failure_speech("english", False) == TURN_INTERRUPTED["english"]


def test_the_two_apologies_are_actually_different():
    # Guards the whole point: if these tables ever converge, every test above
    # passes while the distinction they exist to enforce is gone.
    for lang in LANGS:
        assert AUDIO_UNCLEAR[lang] != TURN_INTERRUPTED[lang]


def test_no_apology_invites_repeating_something_unsaid():
    # TURN_INTERRUPTED must not ask the student to repeat themselves — that is
    # the behaviour being removed, and a future copy edit could reintroduce it
    # in wording while the routing stays correct.
    for lang in LANGS:
        text = TURN_INTERRUPTED[lang].lower()
        assert "once more" not in text
        assert "dubara bol" not in text


def test_truthy_non_bool_sources_still_route_as_speech():
    # The parameter is typed `object` and callers pass through several layers;
    # a truthy non-bool must not silently fall to the "our fault" branch and
    # mask a genuine mishearing.
    assert failure_speech("english", 1) == AUDIO_UNCLEAR["english"]
    assert failure_speech("english", None) == TURN_INTERRUPTED["english"]
