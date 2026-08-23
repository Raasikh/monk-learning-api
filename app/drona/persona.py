"""Tutor persona and session-language constants.

Single source of truth for the two student-selectable axes:

  tutor_voice: 'female' -> Rumik preset "Ira",   display name "Veda"
               'male'   -> Rumik preset "Lucas", display name "Drona"

  language:    'hinglish' | 'english'

The display names here must stay in step with getTutorName() in the web repo
(src/lib/drona/tutor.ts) and with Rule 12 of prompts/tutor.md, which keys Hindi
verb-form agreement off tutor_gender.
"""
from typing import Dict, Literal

TutorVoice = Literal["male", "female"]
SessionLanguage = Literal["english", "hinglish"]

DEFAULT_VOICE: TutorVoice = "female"
DEFAULT_LANGUAGE: SessionLanguage = "hinglish"

# Rumik presets pre-warmed by FillerAudioCache: Ira/Veda (female), Lucas/Drona (male).
PERSONAS: Dict[str, Dict[str, str]] = {
    "female": {"name": "Veda", "voice_preset": "Ira", "gender": "female"},
    "male": {"name": "Drona", "voice_preset": "Lucas", "gender": "male"},
}


def normalize_voice(value: object) -> str:
    """Coerces any client-supplied voice to a known persona key."""
    v = str(value or "").strip().lower()
    return v if v in PERSONAS else DEFAULT_VOICE


def normalize_language(value: object) -> str:
    """Coerces any client-supplied language to a value the DB check allows."""
    lang = str(value or "").strip().lower()
    return lang if lang in ("english", "hinglish") else DEFAULT_LANGUAGE


def persona_for(voice: object) -> Dict[str, str]:
    return PERSONAS[normalize_voice(voice)]


def tutor_name(voice: object) -> str:
    return persona_for(voice)["name"]


def voice_preset(voice: object) -> str:
    return persona_for(voice)["voice_preset"]


# ── Server-authored speech, per language ────────────────────────────────────
# These strings are spoken or shown verbatim, so they must follow the session
# language rather than defaulting to Hinglish the way they used to.

SCOPING_PROMPT = {
    "hinglish": "Arre waah, {chapter} padhna hai? Aaj exactly kis topic ya concept pe focus karein?",
    "english": "So you'd like to learn {chapter}? Which specific topic or concept should we focus on today?",
}

SCOPING_RESOLVED = {
    "hinglish": "Bahut badhiya! Chalo {subtopic} shuru karte hain. Main board pe step-by-step samjhaungi.",
    "english": "Great choice. Let's dive into {subtopic} — I'll walk you through it step by step on the board.",
}

# Same line, but addressed to the student by name — a real teacher opens a class
# by naming who they are teaching. Used whenever profiles.display_name gives us
# a usable first name; SCOPING_RESOLVED stays the fallback for accounts that
# have none, so the greeting degrades to the unnamed version instead of an
# awkward empty slot.
SCOPING_RESOLVED_NAMED = {
    "hinglish": "Bahut badhiya, {name}! Chalo aaj {subtopic} padhte hain. Main board pe step-by-step samjhaungi.",
    "english": "All right, {name} — today we're studying {subtopic}. I'll walk you through it step by step on the board.",
}


def first_name_of(display_name: object) -> str:
    """First word of a display name, cleaned for speech.

    TTS reads a full name stiffly ("All right, Raasikh Ahmed Naveed —"), and a
    name that is an email local-part or a handle reads worse. Anything that
    doesn't look like a spoken name returns "", which sends the caller back to
    the unnamed greeting.
    """
    raw = str(display_name or "").strip()
    if not raw:
        return ""
    first = raw.split()[0].strip()
    # Reject handles/emails/numbers — "raasikh_92", "user123", "a@b.com".
    if not first or not first.replace("'", "").replace("-", "").isalpha():
        return ""
    if len(first) < 2 or len(first) > 20:
        return ""
    return first[:1].upper() + first[1:]

SCOPING_AMBIGUOUS = {
    "hinglish": "Theek hai! {chapter} mein se kaun sa subtopic karna chahoge?",
    "english": "Got it! Which of these subtopics in {chapter} would you like to cover?",
}

AUDIO_UNCLEAR = {
    "hinglish": "Aapki awaaz thodi clear nahi aayi — kya aap ek baar dubara bol sakte hain?",
    "english": "I didn't quite catch that — could you say it once more?",
}

# For a turn the SERVER failed on, where the student said nothing to mishear.
#
# A teaching turn is auto-started: the student is listening, not talking. Using
# AUDIO_UNCLEAR there told them their audio was unclear when they had not
# spoken — blaming them for a server-side failure, and inviting them to repeat
# something they never said. This owns the failure instead and moves on, which
# is also what a real teacher does when they lose their place.
TURN_INTERRUPTED = {
    "hinglish": "Ek second — main apni baat ka sira chhod baitha. Chalo, wahin se dubara shuru karte hain.",
    "english": "One moment — I lost my thread there. Let me pick that up again.",
}


def failure_speech(language: object, utterance: object) -> str:
    """The right apology for whichever thing actually failed.

    Only blame the audio when there WAS audio: if the student said something we
    could not parse, asking them to repeat it is correct. If they said nothing,
    the failure is ours and the message should say so.
    """
    table = AUDIO_UNCLEAR if str(utterance or "").strip() else TURN_INTERRUPTED
    return copy_for(table, language)

# Last-resort stem when the tutor offers answer chips but never voices a
# question. Better a generic question than three orphaned options on screen.
QUESTION_STEM = {
    "hinglish": "Toh bataiye, in mein se kaun sa sahi hai?",
    "english": "So, which of these is correct?",
}

UNDERSTANDING_CHIPS = {
    "hinglish": ["Haan, samajh aaya", "Thoda dubara samjhao"],
    "english": ["Yes, that's clear", "Explain that again"],
}

PROCEDURAL_CHIPS = {
    "hinglish": ["Haan, aage badho", "Ek baar dubara samjhao"],
    "english": ["Yes, let's move on", "Go over that again"],
}

# Doubt-of-the-day opening turn. The teacher asks for the student's own guess
# before revealing anything, so the two options are "I'll try" and "just tell
# me" -- an understanding check-in ("Yes, that's clear") makes no sense there
# because nothing has been explained yet.
GUESS_CHIPS = {
    "hinglish": ["Mujhe lagta hai mujhe pata hai", "Pata nahi, aap bataiye"],
    "english": ["I think I know this", "No idea — tell me"],
}


def copy_for(table: Dict[str, str], language: object, **fmt) -> str:
    """Picks a language variant and formats it. Falls back to the default language."""
    lang = normalize_language(language)
    return table.get(lang, table[DEFAULT_LANGUAGE]).format(**fmt)


def chips_for(table: Dict[str, list], language: object) -> list:
    lang = normalize_language(language)
    return list(table.get(lang, table[DEFAULT_LANGUAGE]))
