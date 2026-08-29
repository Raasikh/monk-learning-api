"""A language we cannot teach in is refused before it reaches the tutor.

The reported failure: a student speaks Telugu, Deepgram transcribes it into
Telugu script, that text is handed to the tutor as an utterance, and the tutor
earnestly ANSWERS it — inventing a question the student never asked and
teaching against it. In the co-founder's words: "it assumes it to be a question
and it starts answering."

This is done in code rather than by a prompt rule on purpose. Script is a
deterministic signal, the check costs nothing, and short-circuiting before the
model call saves a turn instead of spending one to say "I didn't understand".
A prompt rule would also have to survive every other rule in the file.
"""

import pytest

from app.drona.persona import (
    UNSUPPORTED_SCRIPTS,
    unsupported_language_in,
    unsupported_language_reply,
)


@pytest.mark.parametrize("text,expected", [
    ("నాకు అర్థం కాలేదు", "Telugu"),
    ("எனக்கு புரியவில்லை", "Tamil"),
    ("ನನಗೆ ಅರ್ಥವಾಗಲಿಲ್ಲ", "Kannada"),
    ("എനിക്ക് മനസ്സിലായില്ല", "Malayalam"),
    ("আমি বুঝতে পারিনি", "Bengali"),
])
def test_a_language_we_do_not_teach_is_detected(text, expected):
    assert unsupported_language_in(text) == expected


@pytest.mark.parametrize("text", [
    "dekho yahan par net force zero hai",       # romanised Hinglish
    "देखो यहाँ पर net force जीरो है",             # Devanagari Hindi
    "The acceleration is 9.8 metres per second squared",
    "F = ma",
])
def test_everything_we_can_teach_in_passes_through(text):
    """Devanagari is deliberately NOT in the unsupported list.

    Hindi is a session language, and normalize_devanagari_to_roman() already
    converts it. Treating Devanagari as unsupported would refuse every Hinglish
    student the moment Deepgram returned its natural script — which is exactly
    what it returns, and what the STT swap depends on.
    """
    assert unsupported_language_in(text) is None


def test_one_stray_glyph_does_not_refuse_a_good_turn():
    """A threshold, not any-match.

    Transcription artefacts happen. Refusing a whole answer because a single
    non-Latin character appeared would break ordinary turns far more often than
    it would catch a real language switch.
    """
    assert unsupported_language_in("the acceleration is 9.8 ఇ metres per second") is None


def test_a_too_short_utterance_is_never_judged():
    # "ok", "haan", "" carry no evidence either way, and refusing them would
    # break the greeting path.
    for text in ("", "ok", "ఇ", "hi"):
        assert unsupported_language_in(text) is None


def test_the_reply_names_the_language_and_promises_no_date():
    """"Soon" is honest. A month is a commitment nobody made."""
    en = unsupported_language_reply("english", "Telugu")
    hi = unsupported_language_reply("hinglish", "Tamil")
    assert "Telugu" in en and "Tamil" in hi
    for reply in (en, hi):
        assert "don't support it yet" in reply or "nahi karte" in reply
        for overpromise in ("next month", "next week", "by ", "in a few"):
            assert overpromise not in reply.lower()


def test_the_reply_is_in_the_session_language():
    # Telling a Hinglish student in English that we lack their language would
    # break the language lock in the middle of explaining the language lock.
    assert "Ask me in English" in unsupported_language_reply("english", "Telugu")
    assert "Hinglish mein poochho" in unsupported_language_reply("hinglish", "Telugu")


def test_the_session_short_circuits_instead_of_launching_a_turn():
    """The point of the fix: no model call at all.

    If this ever regressed to launching the turn anyway, the tutor would go
    back to answering a question nobody asked — and it would look like a model
    problem rather than a routing one.
    """
    import inspect
    from app.drona import live_session_ws
    src = inspect.getsource(live_session_ws)
    idx = src.index("_unsupported = unsupported_language_in(")
    # Scope to the `if _unsupported:` arm only. A fixed-size window runs past
    # the `elif` into the branch that SHOULD launch a turn, and then asserts
    # the opposite of what it means — the test failed on correct code before
    # this was tightened.
    block = src[idx:src.index("elif norm_t.strip():", idx)]
    assert "launch_background_turn" not in block, "an unsupported language must not reach the tutor"
    assert "unsupported_language_reply" in block
    assert "resume_parked_lesson" in block, "the lesson must resume rather than hang"


def test_devanagari_is_absent_from_the_unsupported_list():
    # Guarded explicitly: adding it would be an easy, plausible, and totally
    # session-breaking mistake.
    for _name, lo, hi in UNSUPPORTED_SCRIPTS:
        assert not (lo <= 0x0915 <= hi), "Devanagari must never be listed as unsupported"
