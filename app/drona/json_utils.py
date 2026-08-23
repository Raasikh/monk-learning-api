"""Shared JSON-robustness helpers for parsing streamed tutor LLM output.

Extracted from tutor.py so app/drona/practice_explain.py can reuse them
without a circular import between the two turn-processing modules.
"""
import json
import re
from typing import Any, Dict


# LaTeX commands whose first letter collides with a JSON string escape.
#
# A model writing `\neq` inside a JSON string produces VALID JSON — `\n` is a
# legal escape — so json.loads silently turns it into a newline followed by
# "eq". Nothing downstream can tell that apart from a real line break, and the
# note renders as a broken line with a stray "eq" on it, which is exactly what
# a saved Integrals note showed. The same trap catches \theta and \times (tab),
# \rho (carriage return), \beta and \bar (backspace), \frac and \forall (form
# feed), \vec (vertical tab), \alpha and \angle (bell).
#
# Keyed by control character; each value is (original letter, surviving tails).
# The escape EATS the first letter, so `\theta` leaves a tab plus "heta" — the
# tails below are the command minus its initial letter, not the whole name.
#
# \b \f \v \a \r never occur in legitimate lesson text, so those are repaired
# on sight. \n and \t are ordinary whitespace, so only distinctive maths tails
# are listed for them and a following letter blocks the match — tab+"ext{"
# becomes \text{ while tab+"extra" is left alone.
_ESCAPE_VICTIMS = {
    "\n": ("n", ["eq", "abla", "otin"]),
    "\t": ("t", ["heta", "imes", "ext", "riangle"]),
    "\r": ("r", ["ightarrow", "angle", "ho", "ightlangle"]),
    "\b": ("b", ["eta", "inom", "ar", "egin", "matrix", "ullet"]),
    "\f": ("f", ["rac", "orall", "loor"]),
    "\v": ("v", ["ec", "arphi", "arepsilon", "arnothing"]),
    "\a": ("a", ["lpha", "pprox", "ngle", "rccos", "rcsin", "rctan"]),
}
_ESCAPE_REPAIRS = [
    (
        re.compile(
            re.escape(ctrl)
            + "(" + "|".join(sorted(tails, key=len, reverse=True)) + ")"
            # The tail must END the command: a trailing letter means this was
            # ordinary prose that happened to start with those characters.
            + "(?![A-Za-z])"
        ),
        "\\" + letter,
    )
    for ctrl, (letter, tails) in _ESCAPE_VICTIMS.items()
]


def repair_latex_control_escapes(text: str) -> str:
    r"""Puts back LaTeX commands that json.loads ate as string escapes.

    `\neq` inside a JSON string is VALID JSON — `\n` is a legal escape — so the
    parser yields a newline and "eq", and nothing downstream can distinguish
    that from a real line break. A saved Integrals note rendered exactly that
    way: a broken line with a stray "eq" sitting on it.

    Conservative by construction: the control character must be followed by the
    complete tail of a known command and nothing alphabetic after it, so a
    genuine newline before prose survives ("\n" + "next we look at" is not
    touched, because "ext" is followed by a letter).
    """
    if not text:
        return text
    for pattern, letter in _ESCAPE_REPAIRS:
        text = pattern.sub(lambda m, l=letter: l + m.group(1), text)
    return text

# R3 — Server-side consumed keys (never emitted to SSE stream)
FORBIDDEN_SSE_KEYS = {
    "model_answer",
    "rubric",
    "expected_misconceptions",
    "grade",
    "mistake_tag",
    "phase_request",
    "segment_complete",
    # The answer key for the question currently on screen. Persisted to
    # drona_turns so the NEXT turn can grade against what was actually
    # intended, but it must never travel to the client with the question.
    "correct_option",
}

def assert_no_forbidden_keys(payload: dict):
    """Strict R3 assertion: server-side-only fields must never reach the client."""
    for k in FORBIDDEN_SSE_KEYS:
        if k in payload:
            raise ValueError(f"R3 VIOLATION: Forbidden server-side key '{k}' in client payload: {payload}")

def strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Extract JSON object substring between first { and last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        return text[first_brace:last_brace + 1]
    return text

def parse_tutor_json(raw_text: str) -> Dict[str, Any]:
    """Robust JSON parsing with fence stripping."""
    cleaned = strip_fences(raw_text)
    return json.loads(cleaned)

def parse_partial_json(raw_text: str) -> Dict[str, Any] | None:
    """Best-effort parse of a JSON object that is still being streamed.

    Closes whatever strings/brackets are still open at the point `raw_text`
    was cut off, then parses. Any field whose closing token was already
    present in `raw_text` decodes to its real, complete value; a field still
    mid-generation decodes to a truncated value (or is dropped if it hadn't
    started). Returns None if even that can't be parsed.
    """
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in raw_text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if stack:
                    stack.pop()

    closed = raw_text
    if in_string:
        closed += '"'
    for opener in reversed(stack):
        closed += "}" if opener == "{" else "]"

    try:
        result = json.loads(closed)
        return result if isinstance(result, dict) else None
    except Exception:
        return None

def top_level_key_complete(raw_text: str, key: str) -> bool | None:
    """Whether `key`'s value is fully, literally present in a streamed JSON
    object — independent of what order the model actually emits keys in.

    The early-flush check below used to gate on a LATER key's substring
    ("grade") appearing, reasoning that the schema lists check_options before
    grade. That only holds if the model's output always matches the example
    order in the prompt — the prompt only actually mandates that `speech` is
    first, nothing else. A model that grades before it re-teaches could
    plausibly emit `grade` before `check_options`, at which point
    parse_partial_json's `check_options` reads as absent-or-empty (not simply
    "not yet true") and the flush decision would be made on data that hadn't
    been generated yet.

    Returns True if `key`'s value is closed in the raw source (safe to trust),
    False if `key` hasn't appeared at all, None if it's present but its value
    is still mid-generation (also not safe to trust).
    """
    marker = f'"{key}"'
    idx = raw_text.find(marker)
    if idx == -1:
        return False

    i = idx + len(marker)
    while i < len(raw_text) and raw_text[i] in " \t\n\r":
        i += 1
    if i >= len(raw_text) or raw_text[i] != ":":
        return None
    i += 1
    while i < len(raw_text) and raw_text[i] in " \t\n\r":
        i += 1
    if i >= len(raw_text):
        return None

    first_ch = raw_text[i]
    if first_ch == '"':
        i += 1
        escape = False
        while i < len(raw_text):
            ch = raw_text[i]
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                return True
            i += 1
        return None

    if first_ch in "{[":
        depth = 0
        in_string = False
        escape = False
        while i < len(raw_text):
            ch = raw_text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch in "{[":
                    depth += 1
                elif ch in "}]":
                    depth -= 1
                    if depth == 0:
                        return True
            i += 1
        return None

    # Bare literal (null / true / false / a number) — closed once we hit
    # whatever terminates it.
    j = i
    while j < len(raw_text) and raw_text[j] not in ",}] \t\n\r":
        j += 1
    return True if j < len(raw_text) else None
