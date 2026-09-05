"""Bare ^ / _ notation and ASCII arrows reaching Rumik verbatim.

_latex_to_speech only walks commands beginning with a backslash, so `v^2`,
`x_1` and `2H2 -> 2H2O` slipped past it untouched — they were classified as
"Tier 2: warn, don't rewrite". None of ^, _ or -> has a pronunciation, so the
voice improvised and the student heard noise mid-sentence.

These assert the rewrite happens AND that ordinary prose is left alone, since
the failure mode of an over-eager rule (mangling "x-axis" or "-5 degrees")
would be worse than the bug it fixes.
"""

from app.drona.voice_proxy import check_tts_safety_filter


def speech(text: str) -> str:
    return check_tts_safety_filter(text)[2]


def test_superscript_two_and_three_get_english_names():
    assert speech("v^2 hoga") == "v squared hoga"
    assert speech("Volume V^3 nikalo") == "Volume V cubed nikalo"


def test_negative_exponent_is_spoken_not_symbolised():
    # The reported case: \text{MLT}^{-2} used to survive as "MLT ^-2".
    assert speech(r"force ka \text{MLT}^{-2} hota hai") == (
        "force ka MLT to the power minus 2 hota hai"
    )


def test_multi_character_exponent_keeps_its_spacing():
    # 'n+1' must not collapse to "nplus 1".
    assert speech("r^{n+1} dekho") == "r to the power n plus 1 dekho"
    assert speech("x^{n-1} dekho") == "x to the power n minus 1 dekho"


def test_subscript_is_spoken_as_a_trailing_qualifier():
    assert speech("Iska value x_1 hoga") == "Iska value x 1 hoga"
    assert speech("a_{net} nikalo") == "a net nikalo"


def test_ascii_arrows_become_words():
    assert "gives" in speech("2H2 + O2 -> 2H2O")
    assert "in equilibrium with" in speech("N2 + 3H2 <=> 2NH3")
    assert "->" not in speech("A -> B")
    assert "<=>" not in speech("A <=> B")


def test_longest_arrow_wins_over_its_substring():
    # "<->" must not be matched as "<-" followed by a stray ">".
    out = speech("A <-> B")
    assert "in equilibrium with" in out
    assert ">" not in out


def test_plain_prose_is_untouched():
    # An over-eager rule mangling ordinary text would be worse than the bug.
    for line in [
        "All right, Raasikh — today we are studying Dimensional Analysis.",
        "Temperature is -5 degrees and x-axis is horizontal.",
        "Force ka dimensional formula M L T to the power minus 2 hota hai.",
    ]:
        assert speech(line) == line


def test_latex_fraction_still_works_alongside_notation():
    # The two passes must compose, not fight: fraction handled by
    # _latex_to_speech, exponent by _notation_to_speech.
    assert speech(r"\dfrac{L}{T} aur v^2") == "L over T aur v squared"


# ── Single-letter phonetics scoping ──────────────────────────────────────────
# The map that spells letters for Rumik used to run unscoped over the whole
# sentence, and was half-populated: M/L/T had entries, A and K did not. A live
# session sent "M, L, T, A aur K" to the voice as "em, el, tee, A aur K" —
# three spelled, two raw, in one breath. Completing the map unscoped is unsafe
# because bare "A" and "I" are ordinary English words.

from app.drona.voice_proxy import sanitize_tts_phonetics


def test_dimension_list_is_spelled_consistently():
    # The exact sentence from the reported session.
    out = sanitize_tts_phonetics("Inhe hum likhte hain square brackets mein: M, L, T, A aur K.")
    assert "em, el, tee, ay aur kay" in out
    # No letter may survive raw next to spelled ones.
    assert " A " not in out and " K." not in out


def test_letter_run_is_spelled():
    assert "el tee" in sanitize_tts_phonetics("formula hoga L T to the power minus 1.")
    assert "em el tee" in sanitize_tts_phonetics("formula hoga M L T to the power minus 2.")


def test_letters_inside_brackets_are_spelled_and_brackets_dropped():
    # Brackets are visual notation. Spoken they are at best an odd pause and at
    # worst read aloud, so the letters are kept and the brackets are not.
    out = sanitize_tts_phonetics("dimension [L T] hota hai")
    assert "el tee" in out
    assert "[" not in out and "]" not in out


def test_glued_dimension_cluster_sounds_the_same_as_the_spaced_one():
    # "[LT]" used to say nothing recognisable while "[L T]" said "el tee",
    # because a 2-char token is not a single letter. Both must match.
    assert "el tee" in sanitize_tts_phonetics("formula is [LT]")
    assert "em el tee" in sanitize_tts_phonetics("dimensions [MLT]")


def test_contraction_next_to_an_article_is_not_a_letter_run():
    # "That's a" -> the "s" after the apostrophe and the article "a" looked
    # like a two-letter run and both got spelled: "That'es ay", heard as
    # "thatsa". A letter touching an apostrophe is never a variable.
    for line in [
        "That's a good question.",
        "It's a formula.",
        "Here's a check.",
        "What's a vector?",
    ]:
        assert sanitize_tts_phonetics(line) == line


def test_no_space_is_left_before_punctuation():
    # Dropping brackets used to leave " em , el ," which nudges the phrasing.
    out = sanitize_tts_phonetics("We write these as [M], [L], and [K].")
    assert " ," not in out and " ." not in out


def test_letter_beside_a_formula_word_is_spelled():
    assert "vee squared" in sanitize_tts_phonetics("Yahan v squared hota hai")
    assert "ef equals" in sanitize_tts_phonetics("F equals ma")


def test_prose_letters_are_never_spelled():
    # The reason the map cannot simply be completed and left unscoped.
    for line in [
        "A ball rolls down the incline.",
        "I think you should try again.",
        "A student asked a question about I and me.",
    ]:
        assert sanitize_tts_phonetics(line) == line


def test_lone_letter_in_prose_is_left_alone():
    # One letter with no formula neighbour and no run is not a variable.
    assert sanitize_tts_phonetics("Temperature 300 K hota hai.") == "Temperature 300 K hota hai."


# ── Rumik inline performance tags ────────────────────────────────────────────
# Rumik PERFORMS <laugh>/<sigh>/<sing> as sounds rather than reading them
# (voice.md). Nothing in the tutor prompt asks for one, so any tag that appears
# is the model improvising — and a teacher who laughs or sings mid-derivation
# is worse than one who just reads the line.

from app.drona.voice_proxy import strip_inline_performance_tags


def test_performance_tags_are_stripped():
    for line, expected in [
        ("<laugh> Dekho, yeh simple hai.", "Dekho, yeh simple hai."),
        ("Achha <sigh> chalo aage badhte hain.", "Achha chalo aage badhte hain."),
        ("<laugh_harder> arre wah!", "arre wah!"),
    ]:
        assert sanitize_tts_phonetics(line) == expected


def test_paired_tags_keep_the_words_between_them():
    # The content is real speech; only the wrapper is a performance instruction.
    assert sanitize_tts_phonetics("<whisper>secret</whisper> formula") == "secret formula"
    assert sanitize_tts_phonetics("Yeh <excited>bahut</excited> important hai.") == (
        "Yeh bahut important hai."
    )


def test_maths_comparisons_are_not_mistaken_for_tags():
    # The reason the pattern forbids internal spaces: "<" is also less-than.
    for line in [
        "Agar x < 5 hai toh",
        "Compare 2 < 3 > 1 dekho",
        "Value a < b hoti hai",
    ]:
        assert sanitize_tts_phonetics(line) == line


def test_stripped_tags_are_reported_for_logging():
    # Silently dropping them would hide a prompt regression.
    _, dropped = strip_inline_performance_tags("<laugh> hi <sigh> there")
    assert dropped == ["laugh", "sigh"]


def test_text_without_tags_is_untouched_and_cheap():
    assert strip_inline_performance_tags("plain speech")[1] == []


def test_letters_joined_by_operators_are_spelled_together():
    # Found by rendering a real Trigonometry turn: "sine of A plus B" was
    # voiced "sine of ay plus B" — the letter with a formula word AFTER it was
    # spelled, its partner was not. Half-spelled is worse than either choice.
    out = sanitize_tts_phonetics("sine of A plus B")
    assert "ay plus bee" in out
    assert sanitize_tts_phonetics("F equals m times a") == "ef equals em times ay"


def test_letters_separated_by_trig_names_are_one_run():
    out = sanitize_tts_phonetics("sine A cosine B plus cosine A sine B")
    # Every letter spelled, or none — never a mix.
    assert "A" not in out and "B" not in out
    assert "ay" in out and "bee" in out


def test_an_operator_between_a_word_and_a_letter_is_not_a_run():
    # The guard that keeps prose safe: a run needs a single letter on BOTH
    # sides of the separator, so the article here is untouched.
    for line in [
        "Take the medicine three times a day.",
        "This happens once or twice a week.",
        "Divide the work per a fixed rule.",
    ]:
        assert sanitize_tts_phonetics(line) == line


# ---------------------------------------------------------------------------
# Spoken maths: commands that USED to be dropped silently.
#
# _latex_to_speech dropped any command it did not recognise, and the
# unrecognised set included every big operator and every function name. The
# damage was not garbled audio -- it was a changed statement:
#
#     \log_{10} 100 = 2              was spoken "10 100 = 2"
#     \lim_{x \to 0}\frac{\sin x}{x} was spoken "x gives 0 x over x"
#
# The second asserts x/x. A student hears a false claim in a confident voice,
# and nothing anywhere logs that a token went missing.
# ---------------------------------------------------------------------------
import re
from app.drona.voice_proxy import _latex_to_speech, _notation_to_speech


def _spoken(text: str) -> str:
    """The real pipeline order, as check_tts_safety_filter runs it."""
    out = _notation_to_speech(_latex_to_speech(text))
    return re.sub(r"\s+", " ", out).strip()


def test_function_names_are_never_dropped():
    # Dropping \sin changes sin(x)/x into x/x -- a different, false statement.
    assert "sine" in _spoken(r"\lim_{x \to 0} \frac{\sin x}{x}")
    assert "log" in _spoken(r"\log_{10} 100 = 2")
    assert "natural log" in _spoken(r"\ln e = 1")
    assert "cosine" in _spoken(r"\cos 0 = 1")


def test_big_operator_scripts_are_limits_not_powers():
    # \int_0^t means "from 0 to t". The generic superscript rule claimed a
    # power the notation never stated.
    spoken = _spoken(r"\int_0^t a\,dt")
    assert "the integral" in spoken
    assert "from 0 to t" in spoken
    assert "to the power" not in spoken

    assert "the sum from i=1 to n" in _spoken(r"\sum_{i=1}^{n} x_i")


def test_latex_spacing_commands_do_not_become_punctuation():
    # `a\,dt` was spoken "a comma d t" -- the backslash was dropped and the
    # comma survived.
    assert "," not in _spoken(r"\int_0^t a\,dt")
    assert _spoken(r"a \quad b") == "a b"


def test_unknown_command_says_its_name_rather_than_vanishing():
    # A dropped token is indistinguishable from one that was never there, so
    # the gap cannot be found by listening. Saying the bare name is at worst
    # clumsy; vanishing is unmeasurable.
    assert "widehat" in _spoken(r"\widehat{AB}") or "AB" in _spoken(r"\widehat{AB}")
    assert _spoken(r"\zzzunknown") != ""


def test_working_cases_did_not_regress():
    assert _spoken(r"v^2 = u^2 + 2as") == "v squared = u squared + 2as"
    assert _spoken(r"\ce{2H2 + O2 -> 2H2O}") == "2H2 + O2 gives 2H2O"
    assert _spoken(r"\frac{1}{2}mv^2") == "1 over 2 mv squared"
