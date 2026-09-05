import os
import re
import json
from urllib.parse import quote_plus
import time
import asyncio
import base64
import logging
import requests
from typing import AsyncGenerator, Callable, Dict, List, Optional, Tuple, Any
import websockets
from app.db import supabase

logger = logging.getLogger("drona.voice_proxy")

# Fixed Base Endpoints (Constant across environments)
RUMIK_TTS_ENDPOINT = "https://silk-api.rumik.ai"

# --- Rumik TTS PCM geometry -------------------------------------------------
# Rumik Silk returns raw PCM over the WS with NO duration and NO timestamp
# field — only binary frames plus a {"type":"done"} control frame. A duration
# is therefore never received; it is COMPUTED from the byte count, exactly as
# the batch pipeline does (dronav1project/scripts/synth_rumik.py:
# `dur = len(all_pcm_samples) / float(RUMIK_SAMPLE_RATE)`).
#
# 24000 Hz, 16-bit, mono. Evidence, mutually independent:
#   * synth_rumik.py sets RUMIK_SAMPLE_RATE = 24000 and hard-refuses to encode
#     if a Rumik WAV header ever comes back at a different rate, bit depth, or
#     channel count.
#   * This file's own live path sizes its progressive flush at
#     `PART_BYTES = 48000`, documented there as "~1s of 24kHz 16-bit mono per
#     part" — 24000 * 2 * 1 = 48000 bytes/s.
#   * The mobile client plays every audio_chunk at TTS_SAMPLE_RATE = 24000
#     (drona-voice-client.ts) and Drona does not sound pitch-shifted, which a
#     16000-vs-24000 mismatch would make unmistakable.
#
# NOT 16000. DeepgramSTTProxy.SAMPLE_RATE = 16000 and SaarasSTTProxy's
# `len(pcm_bytes) / 32000.0` describe the STT *uplink* — the rate the client
# mic sends at, as their own comments say ("what the browser sends"). They say
# nothing about what Rumik synthesizes. Using 16000 here would report every
# narration 1.5x longer than it really is.
RUMIK_TTS_SAMPLE_RATE = 24000
RUMIK_TTS_BYTES_PER_SAMPLE = 2  # 16-bit
RUMIK_TTS_CHANNELS = 1          # mono
RUMIK_TTS_BYTES_PER_SECOND = (
    RUMIK_TTS_SAMPLE_RATE * RUMIK_TTS_BYTES_PER_SAMPLE * RUMIK_TTS_CHANNELS
)  # 48000


def pcm_duration_ms(pcm: Optional[bytes]) -> int:
    """Playback length of a Rumik PCM buffer, in whole milliseconds.

        duration_ms = len(pcm) / (24000 * 2 * 1) * 1000

    Measured, not estimated: it is the byte count of the audio that was
    actually synthesized, so it stays correct for a sentence Rumik truncated,
    a cached filler, or the partial tail of a timed-out stream.
    """
    if not pcm:
        return 0
    return int(len(pcm) * 1000 / RUMIK_TTS_BYTES_PER_SECOND)


SARVAM_STT_ENDPOINT = "wss://api.sarvam.ai/speech-to-text-ws"
SARVAM_STT_REST_ENDPOINT = "https://api.sarvam.ai/speech-to-text"

# Read API Keys strictly without silent fallbacks
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "").strip("\"'")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "").strip("\"'")
RUMIK_API_KEY = os.environ.get("RUMIK_API_KEY", "").strip("\"'")

# Secret Redacting Regular Expressions
SECRET_PATTERNS = [
    re.compile(r'rk_live_[A-Za-z0-9_\-]+'),
    re.compile(r'sk_[A-Za-z0-9_\-]+'),
    re.compile(r'Bearer\s+[A-Za-z0-9_\-\.\=]+', re.IGNORECASE),
]

def sanitize_secret(text: str) -> str:
    """Sanitizes sensitive keys and bearer tokens from logs and exception messages."""
    if not text:
        return ""
    res = str(text)
    for pat in SECRET_PATTERNS:
        res = pat.sub("***REDACTED***", res)
    return res

# Spoken names for single-letter variables and dimension symbols.
#
# Applied ONLY inside formula context — see _apply_letter_phonetics. The old
# map was unscoped and half-populated: it spelled M, L and T but had no entry
# for A or K, so "M, L, T, A aur K" reached Rumik as "em, el, tee, A aur K" —
# three letters spelled, two raw, in one breath. Completing it unscoped is not
# an option either, because a bare "A" and "I" are ordinary English words and
# "A ball rolls" must never become "ay ball rolls".
_LETTER_NAMES = {
    'a': 'ay', 'b': 'bee', 'c': 'see', 'd': 'dee', 'e': 'ee', 'f': 'ef',
    'g': 'jee', 'h': 'aitch', 'i': 'eye', 'j': 'jay', 'k': 'kay', 'l': 'el',
    'm': 'em', 'n': 'en', 'o': 'oh', 'p': 'pee', 'q': 'cue', 'r': 'ar',
    's': 'es', 't': 'tee', 'u': 'yoo', 'v': 'vee', 'w': 'double-yoo',
    'x': 'ex', 'y': 'why', 'z': 'zed',
}

# Words that mark the letter beside them as a variable rather than prose.
_FORMULA_NEIGHBOUR = (
    r"equals|squared|cubed|over|times|plus|minus|divided\s+by|"
    r"to\s+the\s+power|per|upon"
)

# A standalone letter, explicitly NOT one glued to an apostrophe.
#
# `\b` treats an apostrophe as a word boundary, so the "s" in "That's" looked
# like a lone letter. Paired with the article in "That's a", that read as a
# two-letter run and both got spelled — "That'es ay", which is heard as
# "thatsa". A letter touching an apostrophe is always a contraction fragment
# ('s, 't, 'd, 're), never a variable.
_SINGLE = r"(?<![A-Za-z0-9'’])[A-Za-z](?![A-Za-z0-9'’])"

# Two or more single letters in a row, separated only by spaces, commas or a
# conjunction: "M, L, T, A aur K" or "L T". A lone letter followed by a real
# word is prose and is left alone.
#
# Operator words count as separators, so "A plus B" and "F equals m times a"
# are single runs. Without that, only the letter with a formula word AFTER it
# was spelled and its partner was not: "sine of A plus B" was voiced as "sine
# of ay plus B", and "F equals m times a" as "ef equals em times a" — the same
# half-spelled inconsistency as the original M/L/T versus A/K bug, one clause
# later. Requiring a single letter on BOTH sides is what keeps ordinary prose
# safe: in "three times a day" the token before the operator is a word, so no
# run starts and the article is left alone.
#
# Trig and log names join a run too: in "sine A cosine B" the letters are both
# variables of the same identity, and spelling only the one next to an operator
# gave "sine A cosine bee". These words are technical enough not to appear
# between two lone letters in ordinary speech.
_RUN_SEPARATOR = (
    r"\s*,\s*"
    r"|\s+(?:aur|and|or|ya|plus|minus|times|over|equals|by|per|upon"
    r"|sine|sin|cosine|cos|tan|tangent|log|ln)\s+"
    r"|\s+"
)
_LETTER_RUN = re.compile(
    rf"{_SINGLE}(?:(?:{_RUN_SEPARATOR}){_SINGLE})+"
)
# A single letter that is unambiguously a variable because of what sits next
# to it: "v squared", "F equals", "[M]".
_LETTER_BESIDE_MATH = re.compile(
    rf"({_SINGLE})(?=\s+(?:{_FORMULA_NEIGHBOUR})\b)"
)
_LETTER_IN_BRACKETS = re.compile(r"\[([^\]]{1,40})\]")


def _spell(letter: str) -> str:
    return _LETTER_NAMES.get(letter.lower(), letter)


def _spell_all_letters(fragment: str) -> str:
    return re.sub(r"\b([A-Za-z])\b", lambda m: _spell(m.group(1)), fragment)


def _apply_letter_phonetics(text: str) -> str:
    """Spells out single-letter variables, but only where they are variables.

    Rumik mangles bare letters, so they do need help — but the help has to be
    scoped. Three contexts qualify, and nothing else does:
      1. a run of 2+ single letters   -> "M, L, T, A aur K", "L T"
      2. inside square brackets       -> "[M L T]"
      3. adjacent to a formula word   -> "v squared", "F equals"
    Prose keeps its letters, so "A ball rolls" and "I think" are untouched.
    """
    if not text:
        return text

    def _bracket(m: re.Match) -> str:
        inner = m.group(1)
        # "[MLT]" is a dimension cluster, not a word — spell every letter. The
        # glued form was being skipped entirely because \b[A-Za-z]\b only sees
        # ONE-character tokens, so "[L T]" said "el tee" while "[LT]" said
        # nothing recognisable. Both must sound the same.
        inner = re.sub(r"\b[A-Z]{2,5}\b",
                       lambda c: " ".join(_spell(ch) for ch in c.group(0)), inner)
        inner = _spell_all_letters(inner)
        # The brackets themselves are visual notation. Spoken, they are at best
        # an odd pause and at worst read aloud, so they go.
        return " " + inner + " "

    text = _LETTER_IN_BRACKETS.sub(_bracket, text)
    text = _LETTER_RUN.sub(lambda m: _spell_all_letters(m.group(0)), text)
    text = _LETTER_BESIDE_MATH.sub(lambda m: _spell(m.group(1)), text)
    return text

# The prompt forbids LaTeX in speech, but the model still emits plain-notation
# formulas ("H = u² sin²θ / (2g)") — and raw math symbols reach the TTS engine,
# which reads them unpredictably ("=" swallowed, "E" + subscript "k" rendered
# as "eek"). Spell them out before synthesis. Ordered: multi-char first.
MATH_SYMBOL_PRONUNCIATIONS = [
    (r"\s*≈\s*", " approximately "),
    (r"\s*±\s*", " plus or minus "),
    (r"\s*=\s*", " equals "),
    (r"\s*×\s*", " times "),
    (r"\s+/\s+", " over "),
    (r"\^2\b", " squared"),
    (r"\^3\b", " cubed"),
    (r"²", " squared"),
    (r"³", " cubed"),
    (r"√\s*", " root "),
    (r"θ", " theta"),
    (r"π", " pi"),
    (r"Δ", " delta "),
    (r"μ", " mu"),
    (r"λ", " lambda"),
    (r"ω", " omega"),
    (r"α", " alpha"),
    (r"β", " beta"),
    (r"°", " degrees"),
    # Subscripts: "a_x" / "E_k" → "a x" / "E k" so the letters are spoken
    # separately instead of fused into a nonsense word.
    (r"(\w)_(\w)", r"\1 \2"),
]

# Rumik performs these inline — they render as a SOUND, not as words (see
# voice.md). Nothing in the tutor prompt ever asks for one, so any that appears
# is the model improvising, and a teacher who randomly screams, sings or cries
# mid-derivation is worse than one who simply reads the line. Stripped rather
# than voiced: leaving "<laugh>" in would make Rumik actually laugh.
#
# Matches any bare <word> — the known 17 plus anything Rumik adds later — but
# only with no internal spaces, so "x < 5" and "a < b > c" in maths are safe.
_RUMIK_INLINE_TAG = re.compile(r"<\s*/?\s*[A-Za-z][A-Za-z0-9_]{1,19}\s*>")

# If a tag is ever wanted deliberately, add it here and it will survive.
_ALLOWED_INLINE_TAGS: set = set()


def strip_inline_performance_tags(text: str) -> Tuple[str, List[str]]:
    """Removes Rumik performance tags from TTS-bound text.

    Returns (clean_text, tags_removed) so the caller can log what the model
    tried to perform — silently dropping them would hide a prompt problem.
    """
    if not text or "<" not in text:
        return text, []
    found: List[str] = []

    def _drop(m: re.Match) -> str:
        tag = m.group(0)
        name = re.sub(r"[<>/\s]", "", tag).lower()
        if name in _ALLOWED_INLINE_TAGS:
            return tag
        found.append(name)
        return " "

    return _RUMIK_INLINE_TAG.sub(_drop, text), found


def sanitize_tts_phonetics(text: str) -> str:
    """Substitutes math symbols and single Latin letter variable names with explicit phonetic spellings for Rumik TTS."""
    if not text:
        return ""
    res, dropped = strip_inline_performance_tags(text)
    if dropped:
        logger.warning(
            f"🎭 [INLINE TAG STRIPPED] Model emitted performance tag(s) {dropped} — "
            f"Rumik would have performed these as sounds. Removed before synthesis."
        )
    for pattern, replacement in MATH_SYMBOL_PRONUNCIATIONS:
        res = re.sub(pattern, replacement, res)
    res = _apply_letter_phonetics(res)
    res = re.sub(r"\s{2,}", " ", res)
    # Dropping brackets leaves " em , el ," — a space before punctuation, which
    # nudges the engine's phrasing and reads as a stumble.
    res = re.sub(r"\s+([,.!?;:])", r"\1", res)
    return res.strip()

# Startup Assertion Checks
#
# SARVAM_API_KEY is no longer required: Sarvam's WebSocket returned HTTP 403 on
# every endpoint and every auth variant while its REST returned 200, which is an
# account entitlement we could not resolve. Streaming STT was therefore dead and
# every hold paid a full upload-and-wait. Deepgram nova-3 connects in ~220ms and
# is the STT now. The Sarvam class is kept below, unused, until the swap has
# been exercised in real sessions.
if not DEEPGRAM_API_KEY:
    raise RuntimeError("FATAL BOOT FAILURE: DEEPGRAM_API_KEY environment variable is not set!")

if not RUMIK_API_KEY:
    raise RuntimeError("FATAL BOOT FAILURE: RUMIK_API_KEY environment variable is not set!")

if SARVAM_API_KEY.startswith("http://") or SARVAM_API_KEY.startswith("https://") or SARVAM_API_KEY.startswith("wss://"):
    raise RuntimeError("FATAL BOOT FAILURE: SARVAM_API_KEY appears to be a URL string, not an API key!")

if RUMIK_API_KEY.startswith("http://") or RUMIK_API_KEY.startswith("https://") or RUMIK_API_KEY.startswith("wss://"):
    raise RuntimeError("FATAL BOOT FAILURE: RUMIK_API_KEY appears to be a URL string, not an API key!")

if not RUMIK_TTS_ENDPOINT.startswith("https://"):
    raise RuntimeError("FATAL BOOT FAILURE: RUMIK_TTS_ENDPOINT must start with https://")

if not (SARVAM_STT_ENDPOINT.startswith("wss://") or SARVAM_STT_ENDPOINT.startswith("https://")):
    raise RuntimeError("FATAL BOOT FAILURE: SARVAM_STT_ENDPOINT must start with wss:// or https://")

# Technical Terms & Common Hinglish Words Devanagari Mapping Dictionary
TECHNICAL_TERMS_MAP = {
    'इंटीग्रेशन': 'integration', 'डिफरेंशियल': 'differential', 'डिफरेंसिएशन': 'differentiation',
    'इक्वेशन': 'equation', 'डेरिवेटिव': 'derivative', 'वेक्टर': 'vector', 'कैपेसिटर': 'capacitor',
    'इलेक्ट्रॉन': 'electron', 'प्रोटॉन': 'proton', 'न्यूट्रॉन': 'neutron', 'न्यूक्लियस': 'nucleus',
    'ऑक्सीडेशन': 'oxidation', 'रिडक्शन': 'reduction', 'इलेक्ट्रोस्टैटिक्स': 'electrostatics',
    'थर्मोडायनामिक्स': 'thermodynamics', 'इक्विलिब्रियम': 'equilibrium', 'हाइब्रिडाइजेशन': 'hybridisation',
    'फ्रीक्वेंसी': 'frequency', 'वेवलेंth': 'wavelength', 'रेजिस्टेंस': 'resistance', 'इंडक्टेंस': 'inductance',
    'कैपेसिटेंस': 'capacitance', 'ग्रेविटेशन': 'gravitation', 'वेलोसिटी': 'velocity', 'एक्सीलरेशन': 'acceleration',
    'मोमेंटम': 'momentum', 'पोटेंशियल': 'potential', 'मैग्नेटिक': 'magnetic', 'फील्ड': 'field',
    'फोटोसिंथेसिस': 'photosynthesis', 'लाइट': 'light', 'रिएक्शन': 'reaction', 'मैकेनिज्म': 'mechanism',
    'डिफरेंस': 'difference', 'करेंट': 'current', 'इलेक्ट्रिसिटी': 'electricity', 'ओहम्स': 'ohms', 'लॉ': 'law',
    'इक्वल': 'equals', 'ऑफ': 'of', 'पावर': 'power', 'लिमिट': 'limit', 'टेंड्स': 'tends', 'टु': 'to', 'जीरो': 'zero',
    'साइन': 'sine', 'बाय': 'by', 'मैट्रिक्स': 'matrix', 'मल्टीप्लिकेशन': 'multiplication', 'रो': 'row', 'इंतु': 'into',
    'कॉलम': 'column', 'बायोलॉजिकल': 'biological', 'क्लासिफिकेशन': 'classification', 'फाइव': 'five', 'किंगडम': 'kingdom',
    'सिस्टम': 'system', 'प्लांट': 'plant', 'एंजियोस्पर्म्स': 'angiosperms', 'जिम्नोस्पर्म्स': 'gymnosperms',
    'ह्यूमन': 'human', 'फिजियोलॉजी': 'physiology', 'डाइजेशन': 'digestion', 'स्टमक': 'stomach',
    'फर्स्ट': 'first', 'डेल्टा': 'delta', 'प्लस': 'plus', 'एटॉमिक': 'atomic', 'स्ट्रक्चर': 'structure',
    'बोहर': 'bohr', 'रेडियस': 'radius', 'केमिकल': 'chemical', 'बॉन्डिंग': 'bonding', 'सॉल्यूशंस': 'solutions',
    'राउल्ट्स': 'raoults', 'वेपर': 'vapor', 'प्रेशर': 'pressure', 'हेलोएल्केन्स': 'haloalkanes',
    'न्यूक्लियोफिलिक': 'nucleophilic', 'सबस्टिट्यूशन': 'substitution', 'प्रोबेबिलिटी': 'probability',
    'यूनियन': 'union', 'डायरेक्शन': 'direction', 'कोसाइन': 'cosines', 'यूनिवर्सल': 'universal', 'फोर्स': 'force',
    'वेव': 'waves', 'डॉपलर': 'doppler', 'इफेक्ट': 'effect', 'शिफ्ट': 'shift', 'कूलम्ब': 'coulomb',
    'हाँ': 'haan', 'है': 'hai', 'हैं': 'hain', 'कया': 'kya', 'क्या': 'kya', 'कैसे': 'kaise', 'करें': 'karein', 'इसका': 'iska',
    'भाई': 'bhai', 'नेक्स्ट': 'next', 'टॉपिक': 'topic', 'कांसेप्ट': 'concept', 'कंटिन्यू': 'continue', 'डाउट': 'doubt',
    'क्लियर': 'clear', 'चलो': 'chalo', 'आगे': 'aage', 'बढ़ो': 'badho', 'समझ': 'samajh', 'बताओ': 'batao', 'फिर': 'fir',
    'लोग': 'log', 'हम': 'ham', 'उत्तर': 'answer', 'प्रश्न': 'question', 'डिफरेंशियल': 'differential', 'प्रेशर': 'pressure',
    'इक्वेशन': 'equation'
}

# Devanagari Unicode Phonetic Mapping Tables
DEV_VOWELS = {
    'अ': 'a', 'आ': 'aa', 'इ': 'i', 'ई': 'ee', 'उ': 'u', 'ऊ': 'oo', 'ऋ': 'ri',
    'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au', 'अं': 'am', 'अः': 'ah'
}
DEV_MATRAS = {
    'ा': 'a', 'ि': 'i', 'ी': 'ee', 'ु': 'u', 'ू': 'oo', 'ृ': 'ri',
    'े': 'e', 'ै': 'ai', 'ो': 'o', 'ौ': 'au', 'ं': 'n', 'ँ': 'n', 'ः': 'h', '्': ''
}
DEV_CONSONANTS = {
    'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'ng',
    'च': 'ch', 'छ': 'chh', 'ज': 'j', 'झ': 'jh', 'ञ': 'ny',
    'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n',
    'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
    'प': 'p', 'फ': 'f', 'ब': 'b', 'भ': 'bh', 'म': 'm',
    'य': 'y', 'र': 'r', 'ल': 'l', 'व': 'v', 'श': 'sh',
    'ष': 'sh', 'स': 's', 'ह': 'h', 'क्ष': 'ksh', 'त्र': 'tr', 'ज्ञ': 'gy'
}

def transliterate_devanagari_word(word: str) -> str:
    import re
    clean_w = re.sub(r'[^\u0900-\u097F]', '', word)
    if not clean_w:
        return word

    if clean_w in TECHNICAL_TERMS_MAP:
        return TECHNICAL_TERMS_MAP[clean_w]

    res = []
    i = 0
    n = len(clean_w)
    while i < n:
        char = clean_w[i]
        next_char = clean_w[i+1] if i + 1 < n else ""

        if char in DEV_CONSONANTS:
            base = DEV_CONSONANTS[char]
            if next_char in DEV_MATRAS:
                res.append(base + DEV_MATRAS[next_char])
                i += 2
            else:
                if next_char in DEV_CONSONANTS or not next_char:
                    res.append(base + ("a" if i + 1 < n else ""))
                else:
                    res.append(base)
                i += 1
        elif char in DEV_VOWELS:
            res.append(DEV_VOWELS[char])
            i += 1
        elif char in DEV_MATRAS:
            res.append(DEV_MATRAS[char])
            i += 1
        else:
            res.append(char)
            i += 1

    out = "".join(res)
    return out if out else word

def normalize_devanagari_to_roman(text: str) -> str:
    """Normalizes Devanagari script returned by Saaras STT into Romanized Hinglish."""
    import re
    if not text:
        return ""
    words = text.split()
    norm_words = []
    for w in words:
        if re.search(r'[\u0900-\u097F]', w):
            norm_words.append(transliterate_devanagari_word(w))
        else:
            norm_words.append(w)
    return " ".join(norm_words)

# Tier-1 and Tier-2 TTS Safety Filters
TIER1_FORBIDDEN_PATTERNS = [
    r'\\dfrac', r'\\sqrt', r'\\begin', r'\\end', r'\\frac',
    r'\$\$', r'\$', r'\*\*', r'```', r'#{1,6}\s',
    r'\\[a-zA-Z]+',  # any other leaked LaTeX/mhchem command: \ce, \vec, \times, \alpha, \rightarrow, ...
]

TIER2_WARNED_PATTERNS = [
    r'[a-zA-Z0-9_]+_[a-zA-Z0-9_]+',  # subscript notation like x_1
    r'[a-zA-Z0-9_]+\^[a-zA-Z0-9_]+'   # superscript notation like x^2
]

def _skip_balanced_brace_group(text: str, start: int) -> int:
    """text[start] is assumed to be '{'. Returns the index just past its
    matching '}', scanning past any nested braces rather than stopping at
    the first '}' encountered."""
    depth = 0
    i = start
    n = len(text)
    while i < n:
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n

# Commands that carry meaning a student needs to hear. Anything not listed
# gets its command name dropped and its braces unwrapped, so the argument is
# still spoken rather than thrown away.
_LATEX_SYMBOL_WORDS = {
    'times': ' times ', 'cdot': ' times ', 'div': ' divided by ',
    'pm': ' plus or minus ', 'mp': ' minus or plus ',
    'approx': ' approximately ', 'neq': ' not equal to ',
    'leq': ' less than or equal to ', 'geq': ' greater than or equal to ',
    'lt': ' less than ', 'gt': ' greater than ',
    'rightarrow': ' gives ', 'to': ' gives ', 'leftarrow': ' from ',
    'rightleftharpoons': ' in equilibrium with ',
    'infty': ' infinity ', 'degree': ' degrees ', 'circ': ' degrees ',
    'alpha': ' alpha ', 'beta': ' beta ', 'gamma': ' gamma ',
    'delta': ' delta ', 'theta': ' theta ', 'lambda': ' lambda ',
    'mu': ' mu ', 'pi': ' pi ', 'omega': ' omega ', 'rho': ' rho ',
    'sigma': ' sigma ', 'phi': ' phi ', 'epsilon': ' epsilon ', 'nu': ' nu ',
    'eta': ' eta ', 'zeta': ' zeta ', 'kappa': ' kappa ', 'tau': ' tau ',
    'chi': ' chi ', 'psi': ' psi ', 'xi': ' xi ', 'upsilon': ' upsilon ',
    'Delta': ' delta ', 'Omega': ' omega ', 'Sigma': ' sigma ',
    'Phi': ' phi ', 'Lambda': ' lambda ', 'Gamma': ' gamma ',
    'Theta': ' theta ', 'Pi': ' pi ', 'Psi': ' psi ',
    'partial': ' partial ', 'nabla': ' del ', 'propto': ' proportional to ',
    'equiv': ' is identical to ', 'sim': ' similar to ',
    'perp': ' perpendicular to ', 'parallel': ' parallel to ',
    'angle': ' angle ', 'therefore': ' therefore ', 'because': ' because ',
    'cup': ' union ', 'cap': ' intersect ', 'subset': ' is a subset of ',
    'in': ' in ', 'notin': ' not in ', 'forall': ' for all ',
    'exists': ' there exists ', 'll': ' much less than ',
    'gg': ' much greater than ', 'ne': ' not equal to ',
    'le': ' less than or equal to ', 'ge': ' greater than or equal to ',
    'longrightarrow': ' gives ', 'Rightarrow': ' implies ',
    'Leftrightarrow': ' if and only if ', 'ldots': ' and so on ',
    'dots': ' and so on ', 'cdots': ' and so on ',
}
# Function names. These MUST be spoken: dropping one changes the statement
# rather than merely garbling it. Measured before this existed:
#   \log_{10} 100 = 2            ->  "10 100 = 2"
#   \lim_{x \to 0}\frac{\sin x}{x} ->  "x gives 0 x over x"
# The first is read to a student as nonsense; the second asserts x/x, which is
# a different and false claim.
_LATEX_FUNCTIONS = {
    'sin': ' sine ', 'cos': ' cosine ', 'tan': ' tan ',
    'sec': ' secant ', 'csc': ' cosec ', 'cot': ' cot ',
    'arcsin': ' arc sine ', 'arccos': ' arc cosine ', 'arctan': ' arc tan ',
    'sinh': ' hyperbolic sine ', 'cosh': ' hyperbolic cosine ',
    'tanh': ' hyperbolic tan ',
    'log': ' log ', 'ln': ' natural log ', 'lg': ' log ',
    'exp': ' exp ', 'det': ' determinant of ', 'gcd': ' gcd ',
    'max': ' maximum of ', 'min': ' minimum of ',
}

# Big operators. Their sub/superscripts are LIMITS, not powers — without this
# \int_0^t was spoken as "0 to the power t", which is not what the notation
# says. _consume_limits below reads them and says "from 0 to t".
_LATEX_BIG_OPERATORS = {
    'int': ' the integral ', 'iint': ' the double integral ',
    'iiint': ' the triple integral ', 'oint': ' the closed integral ',
    'sum': ' the sum ', 'prod': ' the product ',
    'lim': ' the limit ', 'limsup': ' the limit superior ',
    'liminf': ' the limit inferior ',
}

# Wrappers whose argument is the content itself — the command is pure markup.
_LATEX_SPACING = {'quad', 'qquad', 'thinspace', 'medspace', 'thickspace'}
_LATEX_UNWRAP = {'ce', 'text', 'textbf', 'textit', 'mathrm', 'mathbf', 'mathit',
                 'vec', 'hat', 'bar', 'overline', 'underline', 'left', 'right'}

# Exponents that have a real English name. Anything outside this map falls back
# to "to the power N", which is still sayable.
_POWER_WORDS = {'2': ' squared ', '3': ' cubed '}

# ASCII arrows and comparators the model writes directly, with no backslash for
# _latex_to_speech to key off. Longest-first so "->" never matches inside "<->".
_ASCII_OPERATORS = [
    ('<=>', ' in equilibrium with '),
    ('<->', ' in equilibrium with '),
    ('-->', ' gives '),
    ('->', ' gives '),
    ('<-', ' from '),
    ('>=', ' greater than or equal to '),
    ('<=', ' less than or equal to '),
    ('!=', ' not equal to '),
]


def _notation_to_speech(text: str) -> str:
    """Rewrites bare ^ and _ notation, and ASCII arrows, into spoken words.

    These reach TTS with no backslash on them, so _latex_to_speech never sees
    them — it only walks commands starting at '\\'. They were classified TIER 2
    ("warn, don't touch"), which meant `v^2`, `x_1` and `2H2 -> 2H2O` were
    handed to Rumik verbatim. None of ^, _ or -> has a pronunciation, so the
    engine improvises and the student hears noise mid-sentence. Rewriting is
    strictly better than stripping: "v squared" teaches, "v" is wrong physics.

    Runs AFTER _latex_to_speech, so it also catches the residue that command
    handling leaves behind — \\text{MLT}^{-2} unwraps to "MLT^{-2}" and only
    then becomes "MLT to the power minus 2".
    """
    if not text:
        return text

    for src, word in _ASCII_OPERATORS:
        text = text.replace(src, word)

    # Superscripts: v^2, v^{2}, x^{-2}, r^{n+1}
    def _sup(m: re.Match) -> str:
        body = (m.group(1) or m.group(2) or '').strip()
        if body in _POWER_WORDS:
            return _POWER_WORDS[body]
        # Spaced on both sides: 'n+1' must become "n plus 1", not "nplus 1".
        # The caller collapses runs of whitespace afterwards, so over-spacing
        # here is free and under-spacing is not recoverable.
        body = body.replace('-', ' minus ').replace('+', ' plus ')
        return f' to the power {body} '

    text = re.sub(r'\^\{([^{}]*)\}|\^(-?\w+)', _sup, text)

    # Subscripts: x_1, a_{net}. Spoken as a trailing qualifier the way a
    # teacher says it aloud — "x one", "a net" — not "x underscore one".
    text = re.sub(r'_\{([^{}]*)\}|_(\w+)',
                  lambda m: ' ' + (m.group(1) or m.group(2) or '').strip() + ' ',
                  text)

    return text

def _consume_limits(text: str, k: int) -> Tuple[str, int]:
    """Read a big operator's sub/superscript as LIMITS and return them spoken.

    `\int_0^t` means "from 0 to t", not "0 to the power t". Without this the
    generic superscript rule downstream claimed a power that the notation never
    said. Returns ('', k) when there are no limits, so \sum on its own is
    still just "the sum".
    """
    lo = hi = None
    while k < len(text) and text[k] in '_^':
        marker = text[k]
        k += 1
        if k < len(text) and text[k] == '{':
            end = _skip_balanced_brace_group(text, k)
            inner = end - 1 if text[end - 1:end] == '}' else end
            body, k = text[k + 1:inner], end
        else:
            j = k
            while j < len(text) and (text[j].isalnum() or text[j] in '+-.\\'):
                j += 1
            body, k = text[k:j], j
        body = _latex_to_speech(body).strip()
        if marker == '_':
            lo = body
        else:
            hi = body
    if lo and hi:
        return f' from {lo} to {hi} ', k
    if lo:
        return f' as {lo} ' if lo else '', k
    if hi:
        return f' to {hi} ', k
    return '', k

def _latex_to_speech(text: str) -> str:
    """Rewrites LaTeX/mhchem that leaked into TTS-bound speech into words a
    voice can actually say. The tutor prompt forbids markup in `speech`, but
    the model still emits it on formula-heavy segments, and Rumik reads raw
    backslashes and unmatched braces as garbled noise — the reported "glitch".

    Formulas are spoken, not deleted: \\dfrac{1}{2}mv^2 becomes "1 over 2 mv^2"
    so the student still gets the physics, rather than a sentence with a hole
    in it."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '\\':
            j = i + 1
            while j < n and text[j].isalpha():
                j += 1
            name = text[i + 1:j]
            if not name:
                # A non-alphabetic escape. The LaTeX spacing commands are the
                # common case and they mean WHITESPACE -- dropping only the
                # backslash left the punctuation behind, so `a\,dt` was spoken
                # as "a comma d t". Emit a space and swallow the character.
                if i + 1 < n and text[i + 1] in ',;:!> ':
                    out.append(' ')
                    i += 2
                else:
                    i += 1  # stray backslash: drop it, never voice it
                continue

            args = []
            k = j
            while k < n and text[k] == '{':
                end = _skip_balanced_brace_group(text, k)
                # An unclosed group runs to end-of-string and has no '}' to
                # trim — chopping one anyway would eat a real character.
                inner_end = end - 1 if text[end - 1:end] == '}' else end
                args.append(text[k + 1:inner_end])
                k = end

            if name in ('frac', 'dfrac', 'tfrac') and len(args) >= 2:
                out.append(f" {_latex_to_speech(args[0])} over {_latex_to_speech(args[1])} ")
                for extra in args[2:]:
                    out.append(_latex_to_speech(extra))
            elif name == 'sqrt' and args:
                out.append(f" root {_latex_to_speech(args[0])} ")
                for extra in args[1:]:
                    out.append(_latex_to_speech(extra))
            elif name in _LATEX_BIG_OPERATORS:
                out.append(_LATEX_BIG_OPERATORS[name])
                limits, k = _consume_limits(text, k)
                out.append(limits)
                for arg in args:
                    out.append(' ' + _latex_to_speech(arg) + ' ')
            elif name in _LATEX_FUNCTIONS:
                out.append(_LATEX_FUNCTIONS[name])
                for arg in args:
                    out.append(' ' + _latex_to_speech(arg) + ' ')
            elif name in _LATEX_SYMBOL_WORDS:
                out.append(_LATEX_SYMBOL_WORDS[name])
                for arg in args:
                    out.append(_latex_to_speech(arg))
            elif name in _LATEX_SPACING:
                out.append(' ')
                for arg in args:
                    out.append(' ' + _latex_to_speech(arg) + ' ')
            elif name in _LATEX_UNWRAP:
                # Pure markup wrapper: drop the command, keep what it wrapped.
                for arg in args:
                    out.append(' ' + _latex_to_speech(arg) + ' ')
            else:
                # UNKNOWN COMMAND. Previously this fell through to `pass` and
                # the command vanished without trace, which is how \int, \sum
                # and \log came to be silently deleted from spoken maths --
                # \log_{10} 100 = 2 was read aloud as "10 100 = 2". A dropped
                # token is indistinguishable from a token that was never there,
                # so the gap could not be found by listening.
                #
                # Now: say the bare name, which is at worst clumsy and at best
                # exactly right (\theta -> "theta"), and LOG it so the gap is
                # discoverable instead of silent.
                logger.warning(
                    "[TTS UNKNOWN LATEX] no spoken form for '\\%s' — saying the "
                    "bare name. Add it to _LATEX_FUNCTIONS, _LATEX_BIG_OPERATORS "
                    "or _LATEX_SYMBOL_WORDS.", name
                )
                out.append(f' {name} ')
                for arg in args:
                    out.append(' ' + _latex_to_speech(arg) + ' ')
            i = k
            continue
        out.append(ch)
        i += 1
    return ''.join(out)

def check_tts_safety_filter(text: str) -> Tuple[bool, bool, str]:
    """Returns (tier1_violation, tier2_violation, sanitized_text)."""
    if not text:
        return False, False, ""

    tier1_viol = any(re.search(pat, text) for pat in TIER1_FORBIDDEN_PATTERNS)
    tier2_viol = any(re.search(pat, text) for pat in TIER2_WARNED_PATTERNS)

    if tier1_viol:
        # The prompt forbids markup in speech; when it leaks anyway this is the
        # only place that knows. Logged here rather than at the call sites so
        # every synthesis path is covered.
        logger.warning(f"[TTS MARKUP LEAK] Forbidden markup reached TTS text: '{text[:120]}'")

    clean = _latex_to_speech(text)
    # Must run before the brace strip below: _notation_to_speech reads the
    # braces in x^{-2} to find the exponent's extent. Stripping first would
    # leave "x^-2" and lose the grouping on multi-character exponents.
    clean = _notation_to_speech(clean)
    clean = re.sub(r'[\{\}\$\*\#\`]', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()

    return tier1_viol, tier2_viol, clean

def split_into_sentences(text: str, min_chars: int = 100) -> List[str]:
    """Splits incoming streaming text into sentence chunks for sentence-by-sentence TTS.
    Batches short leading fragments (<100 chars) together so short phrases join
    the next sentence rather than wasting a full TTS roundtrip and RPM quota.

    A question is the one thing that is never batched. The client mounts the
    answer chips against the chunk carrying the question, so gluing the
    checkpoint question onto the statement before it (the batching rule did
    exactly that: "...free fall under g. Now, here's a quick check: ...?"
    arrived as ONE 226-char chunk) put the question on screen 14 seconds before
    it was spoken and left the chips with no sentence of their own to fire on.
    One extra TTS roundtrip per turn is the price; rumik_requests already
    accounts for the trailing question chunk separately."""
    if not text:
        return []
    raw = re.split(r'(?<=[.!?|\n])\s+', text)
    chunks = []
    buf = ""
    for s in raw:
        s_clean = s.strip()
        if not s_clean:
            continue
        if s_clean.endswith("?"):
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(s_clean)
            continue
        if buf:
            buf += " " + s_clean
        else:
            buf = s_clean

        if len(buf) >= min_chars:
            chunks.append(buf)
            buf = ""
    if buf:
        if chunks and len(buf) < min_chars and not chunks[-1].endswith("?"):
            chunks[-1] += " " + buf
        else:
            chunks.append(buf)
    return chunks

class DeepgramSTTProxy:
    """Deepgram nova-3 streaming STT. Drop-in for SaarasSTTProxy.

    WHY THIS REPLACED SARVAM
    ------------------------
    Sarvam's WebSocket returned HTTP 403 on every endpoint and auth variant we
    tried while its REST endpoint returned 200 — an account entitlement, not a
    code fault. Streaming was therefore never available, so every push-to-talk
    release paid a full upload-and-wait round trip. Deepgram's WS connects in
    ~220ms and streams interim results at ~0.9s.

    WHY `language=multi` AND NOT `en`
    ---------------------------------
    Measured on the same code-mixed utterance, "Dekho, yahan par net force zero
    hai, isliye acceleration bhi zero hoga":

        multi -> "देखो, यहाँ पर net force जीरो है, इसलिए acceleration भी जीरो होगा"
        en    -> "Dikho, Yahapar Net four-zero Hai, Isliye acceleration d zero hoga"

    Forcing roman output does not merely change the script, it destroys the
    physics: "net force zero" became "net four-zero". Hindi phonemes have no
    stable English spelling, so a roman-forced model has to guess one AND is
    biased toward English words. Transcribing in Devanagari removes the guess,
    and romanisation becomes a deterministic transform we own — the existing
    normalize_devanagari_to_roman(), which was written for Sarvam and needs no
    change. `multi` also keeps the spoken word "जीरो" rather than collapsing it
    to the digit 0, which reads better in a spoken transcript.

    KEYTERMS
    --------
    nova-3 accepts `keyterm` prompts, and a subject tutor knows exactly what
    vocabulary is coming. Measured on the same audio:

        without: "In the Born Harbor cycle, the lattice enthalpy of..."
        with:    "In the Born-Haber cycle, the lattice enthalpy of..."

    The session's concept names are passed in, so the terms being boosted are
    the ones the lesson is actually about.
    """

    # 16-bit mono at 16kHz — what the browser sends and what the REST fallback
    # already assumed (`duration_s = len(pcm) / 32000`).
    SAMPLE_RATE = 16000
    MODEL = "nova-3"
    # Deepgram caps keyterms per request; the cap here is ours, to keep the
    # connect URL a sane length.
    MAX_KEYTERMS = 40

    def __init__(self, mode: str = "codemix", latency_profile: str = "Fast",
                 language: str = "hinglish", keyterms: Optional[List[str]] = None):
        # mode/latency_profile are accepted and ignored: they are Sarvam's
        # vocabulary, kept so the construction site did not have to change.
        self.mode = mode
        self.latency_profile = latency_profile
        self.model = self.MODEL
        # `multi` for both languages. An English session still benefits: a
        # student answering in English inside an English session transcribes as
        # English, and one who slips into Hindi mid-sentence is not mangled.
        self.language_code = "multi"
        self.keyterms = [k for k in (keyterms or []) if k][: self.MAX_KEYTERMS]
        self.is_connected = False
        self.active_ws = None

    def _url(self, interim: bool = True) -> str:
        parts = [
            f"model={self.model}",
            f"language={self.language_code}",
            "encoding=linear16",
            f"sample_rate={self.SAMPLE_RATE}",
            "channels=1",
            "punctuate=true",
            "smart_format=true",
            # 300ms of silence ends an utterance. The student is holding a
            # button, so ptt_stop is the real boundary — this only decides when
            # a final is emitted mid-hold.
            "endpointing=300",
            # SpeechStarted frames, mapped onto the barge-in callback that
            # Sarvam drove from its own speech_onset field.
            "vad_events=true",
        ]
        if interim:
            parts.append("interim_results=true")
        parts += [f"keyterm={quote_plus(k)}" for k in self.keyterms]
        return "wss://api.deepgram.com/v1/listen?" + "&".join(parts)

    def close(self):
        """Closes the active Deepgram WebSocket cleanly."""
        if self.active_ws:
            try:
                asyncio.create_task(self.active_ws.close())
            except Exception:
                pass
            self.active_ws = None
        self.is_connected = False

    async def transcribe_audio_rest(self, pcm_bytes: bytes) -> Tuple[str, str]:
        """One-shot fallback for a hold whose stream produced nothing.

        Kept because the streaming path can still miss — a socket that dropped
        mid-hold, or a hold shorter than the endpointing window.
        """
        if not pcm_bytes or len(pcm_bytes) < 3200:
            return "", ""
        duration_s = len(pcm_bytes) / (self.SAMPLE_RATE * 2.0)
        logger.info(f"[DEEPGRAM STT REST REQUEST] {len(pcm_bytes)} PCM bytes ({duration_s:.2f}s)")

        import requests
        params = [f"model={self.model}", f"language={self.language_code}",
                  "encoding=linear16", f"sample_rate={self.SAMPLE_RATE}",
                  "channels=1", "punctuate=true", "smart_format=true"]
        params += [f"keyterm={quote_plus(k)}" for k in self.keyterms]
        url = "https://api.deepgram.com/v1/listen?" + "&".join(params)
        headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}",
                   "Content-Type": "audio/raw"}
        try:
            loop = asyncio.get_event_loop()

            def _do_rest_call():
                record_stt_request()
                return requests.post(url, headers=headers, data=pcm_bytes, timeout=12)

            resp = await loop.run_in_executor(None, _do_rest_call)
            if resp.status_code != 200:
                logger.error(f"❌ [DEEPGRAM STT REST ERROR] HTTP {resp.status_code}: {resp.text[:300]}")
                return "", ""
            alts = (resp.json().get("results", {}).get("channels") or [{}])[0].get("alternatives") or [{}]
            raw_transcript = (alts[0].get("transcript") or "").strip()
            norm_transcript = normalize_devanagari_to_roman(raw_transcript)
            logger.info(f"🎯 [DEEPGRAM STT TRANSCRIPT] raw='{raw_transcript}', norm='{norm_transcript}'")
            return raw_transcript, norm_transcript
        except Exception as err:
            logger.error(f"❌ [DEEPGRAM STT REST EXCEPTION] {err}")
            return "", ""

    async def connect_and_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        on_transcript: Callable[[str, str, bool, float], None],
        on_barge_in: Callable[[], None],
    ):
        """Streams mic PCM to Deepgram and forwards transcripts as they arrive."""
        uri = self._url()
        logger.info(f"[DEEPGRAM STT CONNECTING] {self.model}/{self.language_code} "
                    f"keyterms={len(self.keyterms)}")
        try:
            headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
            try:
                ws_ctx = websockets.connect(uri, additional_headers=headers)
            except TypeError:  # websockets < 14
                ws_ctx = websockets.connect(uri, extra_headers=headers)

            async with ws_ctx as ws:
                self.is_connected = True
                self.active_ws = ws
                logger.info(f"✅ [DEEPGRAM STT CONNECTED] {self.model} "
                            f"({len(self.keyterms)} keyterms boosted)")

                async def send_audio():
                    chunk_count = 0
                    total_bytes = 0
                    async for chunk in audio_stream:
                        if not chunk:
                            continue
                        chunk_count += 1
                        total_bytes += len(chunk)
                        await ws.send(chunk)
                    # Tell Deepgram the utterance is over so it flushes its
                    # last final rather than waiting on the endpointing timer.
                    try:
                        await ws.send(json.dumps({"type": "CloseStream"}))
                    except Exception:
                        pass
                    logger.info(f"[DEEPGRAM STT PCM SENT] {chunk_count} chunks, {total_bytes} bytes")

                async def receive_transcripts():
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                        except Exception:
                            continue
                        kind = data.get("type")
                        if kind == "SpeechStarted":
                            on_barge_in()
                            continue
                        if kind != "Results":
                            continue
                        alts = (data.get("channel") or {}).get("alternatives") or [{}]
                        raw_transcript = (alts[0].get("transcript") or "").strip()
                        if not raw_transcript:
                            continue
                        norm_transcript = normalize_devanagari_to_roman(raw_transcript)
                        is_final = bool(data.get("is_final"))
                        confidence = float(alts[0].get("confidence") or 0.95)
                        logger.info(f"🎯 [DEEPGRAM STT TRANSCRIPT] raw='{raw_transcript}', "
                                    f"norm='{norm_transcript}', is_final={is_final}")
                        on_transcript(raw_transcript, norm_transcript, is_final, confidence)

                await asyncio.gather(send_audio(), receive_transcripts())
        except Exception as e:
            self.is_connected = False
            # No REST fallback loop here, unlike the Sarvam class. That existed
            # because Sarvam's WS ALWAYS failed, so the fallback was the real
            # path. Here the release handler already calls transcribe_audio_rest
            # when the stream produced nothing, so a second one would transcribe
            # the same audio twice.
            logger.warning(f"⚠️ [DEEPGRAM STT WS FAILURE] {e} — the hold will fall back to REST at release.")
        finally:
            self.is_connected = False


class SaarasSTTProxy:
    """Proxies Sarvam Saaras v3 STT stream over backend WebSocket connection."""
    def __init__(self, mode: str = "codemix", latency_profile: str = "Fast", language: str = "hinglish"):
        self.mode = "codemix"  # Non-negotiable Rule V2
        self.model = "saaras:v3"  # Non-negotiable Rule V1
        self.latency_profile = latency_profile
        # language_code was hardcoded to hi-IN for every session, so a student
        # speaking English in an English session got their answer transcribed
        # into Devanagari Hindi — the tutor then graded a transliteration of
        # what they never said. Hinglish keeps hi-IN (codemix handles the mix);
        # English sessions transcribe as Indian English.
        self.language_code = "en-IN" if language == "english" else "hi-IN"
        self.is_connected = False
        self.active_ws = None

    def close(self):
        """Closes active Sarvam WebSocket connection cleanly."""
        if self.active_ws:
            try:
                asyncio.create_task(self.active_ws.close())
            except Exception:
                pass
            self.active_ws = None
        self.is_connected = False

    async def transcribe_audio_rest(self, pcm_bytes: bytes) -> Tuple[str, str]:
        """Sends accumulated 16kHz PCM audio bytes directly to Sarvam REST STT API."""
        if not pcm_bytes or len(pcm_bytes) < 3200:
            return "", ""

        duration_s = len(pcm_bytes) / 32000.0
        logger.info(f"[SARVAM STT REST REQUEST] Sending {len(pcm_bytes)} PCM bytes ({duration_s:.2f}s audio) to https://api.sarvam.ai/speech-to-text...")

        import io, wave, requests
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(pcm_bytes)
        buf.seek(0)

        headers = {"api-subscription-key": SARVAM_API_KEY}
        files = {'file': ('speech.wav', buf, 'audio/wav')}
        data = {'model': self.model, 'mode': self.mode, 'language_code': self.language_code}

        try:
            loop = asyncio.get_event_loop()
            def _do_rest_call():
                record_stt_request()
                return requests.post("https://api.sarvam.ai/speech-to-text", headers=headers, data=data, files=files, timeout=12)

            resp = await loop.run_in_executor(None, _do_rest_call)
            logger.info(f"[SARVAM STT REST HTTP RESPONSE] Status: {resp.status_code}, Body: {resp.text[:300]}")

            if resp.status_code == 200:
                res_data = resp.json()
                raw_transcript = res_data.get("transcript", "")
                norm_transcript = normalize_devanagari_to_roman(raw_transcript)
                logger.info(f"🎯 [SARVAM STT TRANSCRIPT] raw='{raw_transcript}', norm='{norm_transcript}'")
                return raw_transcript, norm_transcript
            else:
                logger.error(f"❌ [SARVAM STT REST ERROR] HTTP {resp.status_code}: {resp.text}")
                return "", ""
        except Exception as err:
            logger.error(f"❌ [SARVAM STT REST EXCEPTION] {err}")
            return "", ""

    async def connect_and_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        on_transcript: Callable[[str, str, bool, float], None],
        on_barge_in: Callable[[], None]
    ):
        """Connects to Sarvam Saaras v3 endpoint and streams audio PCM chunks."""
        backoff = 1.0
        max_backoff = 15.0

        headers = {"api-subscription-key": SARVAM_API_KEY}
        endpoint = "wss://api.sarvam.ai/speech-to-text-ws"
        params = f"?model={self.model}&mode={self.mode}&latency={self.latency_profile}"
        uri = f"{endpoint}{params}"

        logger.info(f"[SARVAM STT CONNECTING] Establishing stream to {endpoint} (Headers: {list(headers.keys())})...")

        while True:
            try:
                if SARVAM_API_KEY == "mock-sarvam-key" or "mock" in endpoint:
                    self.is_connected = True
                    async for chunk in audio_stream:
                        if len(chunk) > 0:
                            on_barge_in()
                            await asyncio.sleep(0.01)
                    break

                try:
                    ws_ctx = websockets.connect(uri, additional_headers=headers)
                except TypeError:
                    ws_ctx = websockets.connect(uri, extra_headers=headers)

                async with ws_ctx as ws:
                    self.is_connected = True
                    self.active_ws = ws
                    logger.info(f"✅ [SARVAM STT CONNECTED] Successfully connected to api.sarvam.ai ({self.model}, mode={self.mode})")
                    backoff = 1.0

                    async def send_audio():
                        chunk_count = 0
                        total_bytes = 0
                        async for chunk in audio_stream:
                            if chunk:
                                chunk_count += 1
                                total_bytes += len(chunk)
                                logger.info(f"[SARVAM STT PCM FORWARDED] Chunk #{chunk_count}: {len(chunk)} bytes (Total: {total_bytes} bytes)")
                                await ws.send(chunk)

                    async def receive_transcripts():
                        async for msg in ws:
                            logger.info(f"[SARVAM STT FRAME RECEIVED] {repr(msg[:200])}")
                            data = json.loads(msg)
                            raw_transcript = data.get("transcript", "")
                            norm_transcript = normalize_devanagari_to_roman(raw_transcript)
                            is_final = data.get("is_final", False)
                            confidence = data.get("confidence", 0.95)

                            if raw_transcript.strip():
                                logger.info(f"🎯 [SARVAM STT TRANSCRIPT] raw='{raw_transcript}', norm='{norm_transcript}', is_final={is_final}")

                            if data.get("speech_onset"):
                                on_barge_in()

                            on_transcript(raw_transcript, norm_transcript, is_final, confidence)

                    await asyncio.gather(send_audio(), receive_transcripts())
                    break

                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2.0, max_backoff)
            except Exception as e:
                self.is_connected = False
                logger.warning(f"⚠️ [SARVAM STT WS CONNECTION FAILURE] {e}. Switching to REST STT audio buffer pipeline...")
                
                # Buffer incoming PCM audio chunks and send to Sarvam REST STT
                pcm_chunks = []
                chunk_count = 0
                total_bytes = 0
                async for chunk in audio_stream:
                    if chunk:
                        chunk_count += 1
                        total_bytes += len(chunk)
                        pcm_chunks.append(chunk)
                        logger.info(f"[SARVAM STT PCM FORWARDED] Chunk #{chunk_count}: {len(chunk)} bytes (Total: {total_bytes} bytes)")

                if pcm_chunks and total_bytes >= 3200:
                    import io, wave, requests
                    all_bytes = b"".join(pcm_chunks)
                    buf = io.BytesIO()
                    with wave.open(buf, 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(16000)
                        wf.writeframes(all_bytes)
                    buf.seek(0)

                    files = {'file': ('speech.wav', buf, 'audio/wav')}
                    data = {'model': self.model, 'mode': self.mode, 'language_code': self.language_code}

                    try:
                        loop = asyncio.get_event_loop()
                        def _do_rest_call():
                            record_stt_request()
                            return requests.post("https://api.sarvam.ai/speech-to-text", headers=headers, data=data, files=files, timeout=10)
                        
                        resp = await loop.run_in_executor(None, _do_rest_call)
                        if resp.status_code == 200:
                            res_data = resp.json()
                            raw_transcript = res_data.get("transcript", "")
                            norm_transcript = normalize_devanagari_to_roman(raw_transcript)
                            logger.info(f"🎯 [SARVAM STT TRANSCRIPT] raw='{raw_transcript}', norm='{norm_transcript}', is_final=True")
                            on_transcript(raw_transcript, norm_transcript, True, 0.98)
                        else:
                            logger.error(f"❌ [SARVAM STT REST ERROR] HTTP {resp.status_code}: {resp.text}")
                    except Exception as rest_err:
                        logger.error(f"❌ [SARVAM STT REST EXCEPTION] {rest_err}")
                break

class RumikTurnLease:
    """Turn-scoped lease wrapping an active Rumik Silk WebSocket connection."""
    def __init__(self, pool: "RumikConnectionPool", session_id: str, ws: websockets.WebSocketClientProtocol, voice_preset: str, model: str):
        self.pool = pool
        self.session_id = session_id
        self.ws = ws
        self.voice_preset = voice_preset
        self.model = model
        self.start_time = time.time()
        self.idle_task: Optional[asyncio.Task] = None

    def cancel_idle_timer(self):
        if self.idle_task and not self.idle_task.done():
            self.idle_task.cancel()
            self.idle_task = None

    def start_idle_timer(self, delay_seconds: float = 4.0):
        self.cancel_idle_timer()
        self.idle_task = asyncio.create_task(self._idle_timer_coro(delay_seconds))

    async def _idle_timer_coro(self, delay_seconds: float):
        try:
            await asyncio.sleep(delay_seconds)
            logger.info(f"⏳ [RUMIK 4S GRACE EXPIRED] 4.0s idle timer expired for session '{self.session_id[:8]}'. Closing socket...")
            await self.pool._close_and_remove_lease(self.session_id)
        except asyncio.CancelledError:
            pass

    def get_lease_duration(self) -> float:
        return time.time() - self.start_time


# Filler phrases must follow the SESSION LANGUAGE. These played as hardcoded
# Hinglish in English sessions — an English-speaking student suddenly heard
# "Ek second, soch rahi hoon…" mid-lesson.
#
# Keyed (gender, language). Only Ira and Lucas are prewarmed because those are
# the only two presets a persona ever maps to, so the boot cost is unchanged.
# Pool key the boot-time filler prewarm leases under. Distinct from any real
# session id so live-session accounting can tell the two apart.
PREWARM_SESSION_KEY = "boot_prewarm"

# Sarvam STT calls, for the platform metrics sampler. The sampler used to
# report the count of DB rows in phase='teaching' as its "Sarvam requests",
# which measured nothing of the sort.
_STT_REQUEST_TIMESTAMPS: List[float] = []


def record_stt_request():
    _STT_REQUEST_TIMESTAMPS.append(time.time())


def stt_requests_last_60s() -> int:
    cutoff = time.time() - 60.0
    recent = [t for t in _STT_REQUEST_TIMESTAMPS if t >= cutoff]
    if len(_STT_REQUEST_TIMESTAMPS) > 5000:
        _STT_REQUEST_TIMESTAMPS[:] = recent
    return len(recent)

# No trailing ellipses and no leading "Hmm" — measured, Rumik renders both as
# long drawn-out pauses ("Hmm, ek minute…" came back 4.6s for 15 characters,
# four times its natural length), which is exactly the dragged, stretched
# delivery these clips were criticised for. Plain short sentences instead.
FILLER_PHRASES = {
    ("female", "hinglish"): [
        "Ek second, soch rahi hoon.",
        "Ruko zara, main dekh rahi hoon.",
        "Ek minute.",
    ],
    ("male", "hinglish"): [
        "Ek second, soch raha hoon.",
        "Ruko zara, main dekh raha hoon.",
        "Ek minute.",
    ],
    ("female", "english"): [
        "One moment, let me think.",
        "Just a second.",
        "Give me a moment.",
    ],
    ("male", "english"): [
        "One moment, let me think.",
        "Just a second.",
        "Give me a moment.",
    ],
}

PRESET_GENDER = {"Ira": "female", "Veda": "female", "Lucas": "male", "Drona": "male"}


def filler_cache_key(voice_preset: str, language: str) -> str:
    return f"{voice_preset}:{(language or 'hinglish').lower()}"

class FillerAudioCache:
    """Pre-synthesizes filler audio phrases at startup and caches raw PCM bytes in memory.
    Zero runtime synthesis requests for filler audio."""
    _instance = None
    _lock = asyncio.Lock()

    def __init__(self):
        self.cache: Dict[str, List[bytes]] = {}
        self.is_prewarmed = False
        self._synth_in_flight: set = set()

    @classmethod
    def get_instance(cls) -> "FillerAudioCache":
        if cls._instance is None:
            cls._instance = FillerAudioCache()
        return cls._instance

    def _live_lease_count(self) -> int:
        """Student sessions currently holding a Rumik connection."""
        pool = RumikConnectionPool.get_instance()
        return sum(1 for sid in list(pool.active_leases) if sid != PREWARM_SESSION_KEY)

    async def _wait_for_idle_pool(self, max_wait_s: float = 900.0) -> bool:
        """Blocks until no student session holds a connection."""
        t0 = time.time()
        announced = False
        while time.time() - t0 < max_wait_s:
            if self._live_lease_count() == 0:
                return True
            if not announced:
                logger.info("⏸️ [FILLER PREWARM DEFERRED] A live session is using the pool — waiting for it to finish.")
                announced = True
            await asyncio.sleep(2.0)
        return False

    async def prewarm_all(self, presets: Tuple[str, ...] = ("Ira", "Lucas"),
                          languages: Tuple[str, ...] = ("hinglish", "english")):
        """Synthesizes filler phrases for the given voices/languages.

        No longer runs at boot — see app/main.py. Called lazily by
        ensure_cached() the first time a filler is actually wanted, and by
        then usually for ONE voice and ONE language rather than all four
        combinations.

        Two rules, both learned from a live session sharing a container with a
        fresh deploy's prewarm:

        1. ONE connection for all phrases. This used to open and close a
           connection per phrase — 12 opens against Rumik's rate budget, and
           the churn showed up as a second concurrent slot right through a
           student's turn.
        2. Never run while a student is being taught. A live class always gets
           the pool to itself, so one session means exactly one connection.
        """
        if not await self._wait_for_idle_pool():
            logger.warning("⚠️ [FILLER SYNTH SKIPPED] Pool stayed busy with live sessions; fillers stay uncached.")
            return

        t_start = time.time()
        jobs: List[Tuple[str, str, str]] = []
        for preset in presets:
            gender = PRESET_GENDER[preset]
            for lang in languages:
                key = filler_cache_key(preset, lang)
                if self.cache.get(key):
                    continue  # already have this voice/language
                self.cache.setdefault(key, [])
                for phrase in FILLER_PHRASES[(gender, lang)]:
                    jobs.append((key, preset, phrase))
        if not jobs:
            return

        pool = RumikConnectionPool.get_instance()
        synthesized = 0
        try:
            for key, preset, phrase in jobs:
                # A student who arrives mid-synthesis takes priority: hand the
                # connection back, wait them out, then pick up where we left off.
                if self._live_lease_count() > 0:
                    await pool.release_lease(PREWARM_SESSION_KEY, immediate=True)
                    if not await self._wait_for_idle_pool():
                        break

                lease, is_exhausted = await pool.acquire_lease(PREWARM_SESSION_KEY, preset, "mulberry")
                if is_exhausted or lease is None or not lease.ws:
                    logger.warning("⚠️ [FILLER SYNTH WARN] No connection available; stopping.")
                    break
                pcm = await self._synthesize_on_ws(lease.ws, phrase, preset)
                if pcm:
                    self.cache[key].append(pcm)
                    synthesized += 1
        finally:
            try:
                await pool.release_lease(PREWARM_SESSION_KEY, immediate=True)
            except Exception:
                pass

        if synthesized:
            self.is_prewarmed = True
        elapsed = time.time() - t_start
        logger.info(
            f"✅ [FILLER CACHED] {synthesized}/{len(jobs)} phrases synthesized "
            f"in {elapsed:.1f}s (1 connection, lazy)"
        )

    def ensure_cached(self, voice_preset: str, language: str):
        """Kicks off background synthesis for this voice/language if missing.

        Fire-and-forget by design: the caller needing a filler RIGHT NOW is
        usually mid-rate-limit, when synthesizing is exactly what we cannot
        do. That first occurrence degrades to a brief silence; this makes
        sure the next one has a real phrase.
        """
        key = filler_cache_key(voice_preset, language)
        if self.cache.get(key) or key in self._synth_in_flight:
            return
        self._synth_in_flight.add(key)

        async def _run():
            try:
                await self.prewarm_all(presets=(voice_preset,), languages=(language,))
            except Exception as err:
                logger.warning(f"Lazy filler synthesis failed for {key}: {err}")
            finally:
                self._synth_in_flight.discard(key)

        try:
            asyncio.create_task(_run())
        except RuntimeError:
            self._synth_in_flight.discard(key)

    async def _synthesize_on_ws(self, ws, text: str, voice_preset: str) -> bytes:
        """Synthesizes one phrase over an already-open connection.

        Returns b"" on failure — an uncached filler is simply absent, never a
        block of silence pretending to be speech.
        """
        try:
            await ws.send(json.dumps({"text": text, "speaker": voice_preset}))
            buf = bytearray()
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=6.0)
                if isinstance(msg, bytes):
                    buf.extend(msg)
                elif isinstance(msg, str):
                    d = json.loads(msg)
                    if d.get("type") in ("done", "complete", "finish", "end"):
                        break
                    if d.get("code") == "RATE_LIMITED" or d.get("error"):
                        logger.warning(f"⚠️ [FILLER PREWARM WARN] Rumik refused '{text[:24]}…': {d.get('message') or d.get('code')}")
                        return b""
            return bytes(buf)
        except Exception as e:
            logger.warning(f"⚠️ [FILLER PREWARM WARN] Could not pre-synthesize '{text[:24]}…' for '{voice_preset}': {e}")
            return b""

    def has_cached_fillers(self, voice_preset: str, language: str = "hinglish") -> bool:
        """Whether a REAL filler exists for this voice/language.

        get_random_filler() falls back to two seconds of silence so a
        rate-limit gap is never dead air. That is wrong for the answer
        acknowledgment, where silence would just delay the real reply — those
        callers check here first.
        """
        if self.cache.get(filler_cache_key(voice_preset, language)):
            return True
        fallback_preset = "Lucas" if PRESET_GENDER.get(voice_preset) == "male" else "Ira"
        return bool(
            self.cache.get(filler_cache_key(fallback_preset, language))
            or self.cache.get(filler_cache_key(fallback_preset, "hinglish"))
        )

    def get_random_filler(self, voice_preset: str, language: str = "hinglish",
                          exclude_idx: Optional[int] = None) -> Tuple[int, bytes]:
        """Returns (index, pcm_bytes) of a cached filler for this voice AND language."""
        import random
        phrases_pcm = self.cache.get(filler_cache_key(voice_preset, language))
        if not phrases_pcm:
            fallback_preset = "Lucas" if PRESET_GENDER.get(voice_preset) == "male" else "Ira"
            phrases_pcm = (self.cache.get(filler_cache_key(fallback_preset, language))
                           or self.cache.get(filler_cache_key(fallback_preset, "hinglish")))

        if not phrases_pcm:
            # Nothing cached yet (fillers are synthesized lazily now). Cover
            # this gap with silence and get the clips made for next time.
            self.ensure_cached(voice_preset, language)
            return 0, b"\x00" * 48000

        indices = [i for i in range(len(phrases_pcm)) if i != exclude_idx]
        if not indices:
            indices = list(range(len(phrases_pcm)))

        chosen_idx = random.choice(indices)
        return chosen_idx, phrases_pcm[chosen_idx]


class RumikConnectionPool:
    """Connection Pool for Rumik Silk TTS with Per-Turn Leases & 4s Grace Period."""
    _instance = None

    def __init__(self, max_slots: int = 50):
        self.max_slots = max_slots
        self.semaphore = asyncio.Semaphore(max_slots)
        self.active_leases: Dict[str, RumikTurnLease] = {}
        
        self.concurrent_held_history: List[int] = []
        self.connections_opened_timestamps: List[float] = []
        # Two different things can count against Rumik's 100 RPM: opening a
        # connection (one POST to /v1/tts/ws-connect) and sending text down an
        # already-open socket. We do not know which one Rumik meters, and they
        # differ by roughly 6x per turn, so track both and plan against the
        # larger. See get_rate_usage().
        self.synthesis_requests_timestamps: List[float] = []
        self.lease_durations: List[float] = []
        self.acquisition_wait_times: List[float] = []
        self.pool_exhaustion_count: int = 0
        self.lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "RumikConnectionPool":
        if cls._instance is None:
            cls._instance = RumikConnectionPool(max_slots=50)
        return cls._instance

    def record_synthesis_request(self):
        """One text frame sent down an open socket. Counted separately from opens."""
        self.synthesis_requests_timestamps.append(time.time())

    def get_rate_usage(self) -> Tuple[int, int]:
        """Returns (connection_opens, synthesis_sends) in the trailing 60s."""
        cutoff = time.time() - 60.0
        opens = sum(1 for ts in self.connections_opened_timestamps if ts >= cutoff)
        sends = sum(1 for ts in self.synthesis_requests_timestamps if ts >= cutoff)
        # Keep the windows from growing without bound over a long-lived process.
        if len(self.connections_opened_timestamps) > 5000:
            self.connections_opened_timestamps = [t for t in self.connections_opened_timestamps if t >= cutoff]
        if len(self.synthesis_requests_timestamps) > 5000:
            self.synthesis_requests_timestamps = [t for t in self.synthesis_requests_timestamps if t >= cutoff]
        return opens, sends

    def get_requests_in_last_60s(self) -> int:
        """Worst-case RPM against Rumik's 100/min cap.

        Deliberately the max of the two counters rather than opens alone: if
        Rumik meters text frames we would otherwise under-report by ~6x and
        only find out via RATE_LIMITED frames.
        """
        opens, sends = self.get_rate_usage()
        return max(opens, sends)

    async def acquire_lease(self, session_id: str, voice_preset: str = "Ira", model: str = "mulberry") -> Tuple[Optional[RumikTurnLease], bool]:
        t0 = time.time()
        
        async with self.lock:
            if session_id in self.active_leases:
                lease = self.active_leases[session_id]
                lease.cancel_idle_timer()
                logger.info(f"🔄 [RUMIK POOL REUSE] Reusing connection lease for session '{session_id[:8]}'")
                return lease, False

        acquired = False
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=3.0)
            acquired = True
        except asyncio.TimeoutError:
            async with self.lock:
                self.pool_exhaustion_count += 1
                concurrent_now = self.max_slots - self.semaphore._value
                logger.error(f"❌ [RUMIK POOL EXHAUSTION] Timeout 3.0s waiting for connection slot! Active concurrent slots: {concurrent_now}/{self.max_slots}")
            return None, True

        wait_ms = round((time.time() - t0) * 1000, 2)
        async with self.lock:
            self.acquisition_wait_times.append(wait_ms)
            self.connections_opened_timestamps.append(time.time())

        ws = await self._open_connection_with_jitter(voice_preset, model)
        if ws is None:
            self.semaphore.release()
            return None, True

        lease = RumikTurnLease(
            pool=self,
            session_id=session_id,
            ws=ws,
            voice_preset=voice_preset,
            model=model
        )

        async with self.lock:
            self.active_leases[session_id] = lease
            concurrent_now = len(self.active_leases)
            self.concurrent_held_history.append(concurrent_now)
            logger.info(f"🔑 [RUMIK POOL ACQUIRE] Lease acquired for session '{session_id[:8]}'. Wait={wait_ms}ms | Concurrent slots: {concurrent_now}/{self.max_slots}")

        return lease, False

    async def _open_connection_with_jitter(self, voice_preset: str, model: str) -> Optional[websockets.WebSocketClientProtocol]:
        import random, requests
        jitter = random.uniform(0.1, 0.3)
        await asyncio.sleep(jitter)

        rumik_key = RUMIK_API_KEY
        if not rumik_key:
            return None

        base_url = RUMIK_TTS_ENDPOINT
        backoff = 0.5

        for attempt in range(1, 4):
            try:
                def _mint():
                    return requests.post(
                        f"{base_url}/v1/tts/ws-connect",
                        headers={"Authorization": f"Bearer {rumik_key}", "Content-Type": "application/json"},
                        json={"model": model, "text": "Init"},
                        timeout=8
                    ).json()

                loop = asyncio.get_event_loop()
                handshake = await loop.run_in_executor(None, _mint)
                ws_url = handshake.get("ws_url")
                token = handshake.get("token")
                if ws_url and token:
                    ws = await websockets.connect(
                        f"{ws_url}?token={token}",
                        ping_interval=None,
                        close_timeout=5.0
                    )
                    return ws
            except Exception as err:
                logger.warning(f"⚠️ [RUMIK CONNECT RETRY #{attempt}] {err}. Sleeping {backoff}s...")
                await asyncio.sleep(backoff)
                backoff *= 2.0

        return None

    async def release_lease(self, session_id: str, immediate: bool = False):
        async with self.lock:
            if session_id not in self.active_leases:
                return
            lease = self.active_leases[session_id]

        if immediate:
            await self._close_and_remove_lease(session_id)
        else:
            lease.start_idle_timer(4.0)

    async def _close_and_remove_lease(self, session_id: str):
        async with self.lock:
            if session_id in self.active_leases:
                lease = self.active_leases.pop(session_id)
                dur = lease.get_lease_duration()
                self.lease_durations.append(dur)
                try:
                    await lease.ws.close()
                except Exception:
                    pass
                self.semaphore.release()
                concurrent_now = len(self.active_leases)
                logger.info(f"🔓 [RUMIK POOL RELEASE] Released lease for session '{session_id[:8]}' after {dur:.2f}s. Concurrent slots: {concurrent_now}/{self.max_slots}")


class RumikTTSProxy:
    """Streaming TTS synthesis via Rumik Silk WebSocket API using Per-Turn Connection Pool."""
    def __init__(self, voice_preset: str = "Ira", model: str = "mulberry", session_id: str = "default_session",
                 language: str = "hinglish", pool_key: Optional[str] = None):
        self.voice_preset = voice_preset
        self.language = language
        self.model = model
        self.session_id = session_id
        # Pool leases are keyed separately from the DB session id. Two
        # connections can briefly exist for ONE session (a refresh or resume
        # taking over), and with a shared key the retiring connection's
        # release closed the very socket the new one was synthesizing on —
        # "sent 1000 (OK); then received 1000 (OK)" mid-sentence. session_id
        # stays the DB identity (rate_limit_hits writes use it).
        self.pool_key = pool_key or session_id
        self.connection_count = 0
        self.lock = asyncio.Lock()

    async def prewarm(self):
        pool = RumikConnectionPool.get_instance()
        await pool.acquire_lease(self.pool_key, self.voice_preset, self.model)

    async def end_turn(self, next_turn_is_immediate: bool = False):
        """Hand the slot back once a turn's last sentence has been synthesized.

        Sentences *within* a turn already reuse the lease, so at a turn boundary
        the grace period only pays for itself if another turn is about to start
        right now — i.e. an auto-advanced teaching turn, whose prewarm() lands
        within a second or two and reuses the socket instead of re-handshaking.

        When the turn ends on a checkpoint the student is about to spend 20-60s
        reading and answering. Holding the slot through that is pure waste, so
        release immediately and let someone else have it.
        """
        pool = RumikConnectionPool.get_instance()
        await pool.release_lease(self.pool_key, immediate=not next_turn_is_immediate)

    async def abandon(self):
        """Drop the slot immediately — student disconnected, nothing to reuse."""
        pool = RumikConnectionPool.get_instance()
        await pool.release_lease(self.pool_key, immediate=True)

    async def synthesize_text(
        self,
        text: str,
        on_filler_cb: Optional[Any] = None,
        segment_index: int = 1,
        on_audio_part: Optional[Any] = None,
    ) -> bytes:
        """Synthesizes text using per-turn leased WebSocket from pool with zero-gap rate-limit fillers.

        With `on_audio_part`, PCM is flushed to the callback in ~1s batches AS
        RUMIK SYNTHESIZES instead of buffered until the sentence is done —
        the student hears the first second of a sentence while the rest is
        still being generated. When anything was emitted through the callback
        the return value is b"" so the caller doesn't send the audio twice.
        """
        text = sanitize_tts_phonetics(text)
        async with self.lock:
            return await self._synthesize_text_locked(
                text, attempt=1, on_filler_cb=on_filler_cb, segment_index=segment_index,
                on_audio_part=on_audio_part,
            )

    def _record_rate_limit_hit_async(self):
        """Asynchronously increments rate_limit_hits in drona_sessions."""
        try:
            async def _update():
                s_res = supabase.table("drona_sessions").select("rate_limit_hits").eq("id", self.session_id).execute()
                current_hits = 0
                if s_res.data and len(s_res.data) > 0 and s_res.data[0].get("rate_limit_hits") is not None:
                    current_hits = s_res.data[0]["rate_limit_hits"]
                supabase.table("drona_sessions").update({
                    "rate_limit_hits": current_hits + 1
                }).eq("id", self.session_id).execute()
            asyncio.create_task(_update())
        except Exception as e:
            logger.warning(f"Failed to record rate limit hit in drona_sessions: {e}")

    async def _synthesize_text_locked(
        self,
        text: str,
        attempt: int = 1,
        on_filler_cb: Optional[Any] = None,
        segment_index: int = 1,
        on_audio_part: Optional[Any] = None,
    ) -> bytes:
        self.connection_count += 1
        t0 = time.time()

        pool = RumikConnectionPool.get_instance()
        lease, is_exhausted = await pool.acquire_lease(self.pool_key, self.voice_preset, self.model)

        if is_exhausted or lease is None:
            logger.warning(f"⚠️ [RUMIK POOL EXHAUSTION FALLBACK] Surfacing cached filler phrase for text='{text[:30]}...'")
            filler_cache = FillerAudioCache.get_instance()
            _, filler_pcm = filler_cache.get_random_filler(self.voice_preset, self.language)
            if on_filler_cb:
                try:
                    await on_filler_cb(filler_pcm)
                except Exception:
                    pass
            return filler_pcm

        ws = lease.ws
        pcm_bytes = bytearray()
        t_first_byte = None

        # Progressive flush state. ~1s of 24kHz 16-bit mono per part: small
        # enough that the first part reaches the student seconds before the
        # sentence finishes synthesizing, big enough not to spam frames.
        PART_BYTES = RUMIK_TTS_BYTES_PER_SECOND  # 48000
        part_buf = bytearray()
        emitted_parts = 0
        # Milliseconds of audio already handed to on_audio_part. Each part's
        # own measured duration accumulates here, so this doubles as the
        # start offset of the NEXT part within the sentence.
        emitted_duration_ms = 0

        async def _flush_part(force: bool = False):
            nonlocal emitted_parts, emitted_duration_ms
            if on_audio_part is None:
                return
            if len(part_buf) >= PART_BYTES or (force and part_buf):
                chunk = bytes(part_buf)
                part_buf.clear()
                emitted_parts += 1
                # Measured playback length of THIS part, from its own bytes —
                # see pcm_duration_ms. The caller forwards it to the client so
                # narration-synced board cues have a real millisecond track
                # instead of a guess.
                part_duration_ms = pcm_duration_ms(chunk)
                emitted_duration_ms += part_duration_ms
                if emitted_parts == 1:
                    logger.info(f"⚡ [RUMIK FIRST PART] Sentence #{self.connection_count}: first {len(chunk)} bytes ({part_duration_ms}ms) flushed {time.time() - t0:.2f}s in (sentence still synthesizing)")
                try:
                    await on_audio_part(chunk)
                except Exception as part_err:
                    logger.warning(f"on_audio_part callback failed: {part_err}")

        try:
            payload = {"text": text, "speaker": self.voice_preset}
            logger.info(f"[RUMIK WS PAYLOAD] session={self.session_id[:8]} | sentence={self.connection_count} | payload={json.dumps(payload)}")
            pool.record_synthesis_request()
            await ws.send(json.dumps(payload))

            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    if isinstance(msg, bytes):
                        if t_first_byte is None:
                            t_first_byte = time.time()
                        pcm_bytes.extend(msg)
                        if on_audio_part is not None:
                            part_buf.extend(msg)
                            await _flush_part()
                    elif isinstance(msg, str):
                        data = json.loads(msg)
                        msg_type = data.get("type") or data.get("event") or data.get("status")
                        if msg_type in ("done", "complete", "finish", "end"):
                            logger.info(f"[RUMIK WS DONE FRAME] Sentence #{self.connection_count} complete")
                            await _flush_part(force=True)
                            break
                        elif data.get("code") == "RATE_LIMITED" or data.get("error"):
                            if emitted_parts > 0:
                                # Part of this sentence has already PLAYED —
                                # retrying would speak its opening twice. Keep
                                # what was delivered and move on.
                                logger.warning(f"🚨 [RUMIK ERROR MID-STREAM] Sentence #{self.connection_count} errored after {emitted_parts} parts played — not retrying to avoid double speech.")
                                await pool.release_lease(self.pool_key, immediate=True)
                                return b""
                            retry_after = float(data.get("retry_after", 5.0))
                            opens_60s, sends_60s = pool.get_rate_usage()

                            logger.warning(
                                f"🚨 [RUMIK RATE LIMITED] session={self.session_id} | seg={segment_index} | "
                                f"retry_after={retry_after}s | opens_last_60s={opens_60s} | "
                                f"sends_last_60s={sends_60s} | open_leases={len(pool.active_leases)}/{pool.max_slots} | "
                                f"attempt={attempt}/3"
                            )

                            self._record_rate_limit_hit_async()
                            filler_cache = FillerAudioCache.get_instance()

                            # 1. Play first cached filler immediately (0 requests, no gap!)
                            idx1, filler1_pcm = filler_cache.get_random_filler(self.voice_preset, self.language)
                            if on_filler_cb:
                                try:
                                    await on_filler_cb(filler1_pcm)
                                except Exception:
                                    pass

                            # 2. Smart mid-wait filler: if retry_after > 15s, play second filler mid-way
                            if retry_after > 15.0:
                                await asyncio.sleep(10.0)
                                idx2, filler2_pcm = filler_cache.get_random_filler(self.voice_preset, self.language, exclude_idx=idx1)
                                logger.info(f"⏳ [RUMIK MID-WAIT FILLER] Playing 2nd filler for session {self.session_id[:8]} (retry_after={retry_after}s)")
                                if on_filler_cb:
                                    try:
                                        await on_filler_cb(filler2_pcm)
                                    except Exception:
                                        pass
                                await asyncio.sleep(max(0.1, retry_after - 10.0 + 0.5))
                            else:
                                await asyncio.sleep(retry_after + 0.5)

                            # 3. Retry synthesis (up to 3 attempts)
                            if attempt < 3:
                                await pool.release_lease(self.pool_key, immediate=True)
                                return await self._synthesize_text_locked(
                                    text, attempt=attempt + 1, on_filler_cb=on_filler_cb, segment_index=segment_index,
                                    on_audio_part=on_audio_part,
                                )

                            raise RuntimeError(f"Rumik TTS Rate Limited (Attempt {attempt}/3): {data.get('message') or 'Rate limit exceeded'}")
                except asyncio.TimeoutError:
                    logger.warning(f"[RUMIK WS TIMEOUT] ws.recv() timed out for text='{text[:30]}...'")
                    # Whatever was already synthesized still belongs to the
                    # student — without this the tail sitting in part_buf is
                    # dropped and the sentence cuts off mid-word.
                    await _flush_part(force=True)
                    break

        except Exception as ws_err:
            logger.warning(f"[RUMIK WS ERROR] Exception during synthesis: {ws_err}")
            await pool.release_lease(self.pool_key, immediate=True)
            if emitted_parts > 0:
                # Same double-speech guard as the rate-limit path.
                logger.warning(f"[RUMIK WS ERROR MID-STREAM] Sentence #{self.connection_count} died after {emitted_parts} parts played — not retrying.")
                return b""
            if attempt < 3:
                return await self._synthesize_text_locked(
                    text, attempt=attempt + 1, on_filler_cb=on_filler_cb, segment_index=segment_index,
                    on_audio_part=on_audio_part,
                )
            raise RuntimeError(sanitize_secret(str(ws_err)))

        if len(pcm_bytes) == 0:
            if attempt < 3:
                return await self._synthesize_text_locked(
                    text, attempt=attempt + 1, on_filler_cb=on_filler_cb, segment_index=segment_index,
                    on_audio_part=on_audio_part,
                )
            return b"\x00" * 24000

        t_total = time.time() - t0
        # Whole-sentence measured duration, over every byte Rumik produced —
        # equal to the sum of the parts when streaming, and the length of the
        # single returned buffer when not.
        sentence_duration_ms = pcm_duration_ms(bytes(pcm_bytes))
        logger.info(
            f"[RUMIK SYNTHESIS COMPLETE] Sentence #{self.connection_count}: {len(text)} chars -> "
            f"{len(pcm_bytes)} PCM bytes ({sentence_duration_ms}ms audio) in {t_total:.2f}s wall"
        )
        if emitted_parts > 0:
            if emitted_duration_ms != sentence_duration_ms:
                # Only reachable if a part was dropped; the two are the same
                # bytes counted two ways.
                logger.warning(
                    f"[RUMIK DURATION MISMATCH] Sentence #{self.connection_count}: streamed "
                    f"{emitted_duration_ms}ms across {emitted_parts} parts but synthesized "
                    f"{sentence_duration_ms}ms"
                )
            # Everything already went out through on_audio_part.
            return b""
        return bytes(pcm_bytes)

    async def stream_tts(self, text_stream: AsyncGenerator[str, None]) -> AsyncGenerator[bytes, None]:
        buffer = ""
        async for chunk in text_stream:
            buffer += chunk
            sentences = split_into_sentences(buffer)
            if len(sentences) > 1:
                for sentence in sentences[:-1]:
                    t1_viol, t2_viol, clean_text = check_tts_safety_filter(sentence)
                    if clean_text:
                        audio_pcm = await self.synthesize_text(clean_text)
                        yield audio_pcm
                buffer = sentences[-1]

        if buffer.strip():
            t1_viol, t2_viol, clean_text = check_tts_safety_filter(buffer)
            if clean_text:
                audio_pcm = await self.synthesize_text(clean_text)
                yield audio_pcm

        pool = RumikConnectionPool.get_instance()
        await pool.release_lease(self.pool_key, immediate=False)


