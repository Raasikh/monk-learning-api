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

SCOPING_AMBIGUOUS = {
    "hinglish": "Theek hai! {chapter} mein se kaun sa subtopic karna chahoge?",
    "english": "Got it! Which of these subtopics in {chapter} would you like to cover?",
}

AUDIO_UNCLEAR = {
    "hinglish": "Aapki awaaz thodi clear nahi aayi — kya aap ek baar dubara bol sakte hain?",
    "english": "I didn't quite catch that — could you say it once more?",
}

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


def copy_for(table: Dict[str, str], language: object, **fmt) -> str:
    """Picks a language variant and formats it. Falls back to the default language."""
    lang = normalize_language(language)
    return table.get(lang, table[DEFAULT_LANGUAGE]).format(**fmt)


def chips_for(table: Dict[str, list], language: object) -> list:
    lang = normalize_language(language)
    return list(table.get(lang, table[DEFAULT_LANGUAGE]))
