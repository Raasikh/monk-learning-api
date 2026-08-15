"""Shared JSON-robustness helpers for parsing streamed tutor LLM output.

Extracted from tutor.py so app/drona/practice_explain.py can reuse them
without a circular import between the two turn-processing modules.
"""
import json
from typing import Dict, Any

# R3 — Server-side consumed keys (never emitted to SSE stream)
FORBIDDEN_SSE_KEYS = {
    "model_answer",
    "rubric",
    "expected_misconceptions",
    "grade",
    "mistake_tag",
    "phase_request",
    "segment_complete",
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
