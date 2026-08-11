"""Snap a Doubt — photograph of a question in, worked explanation out.

Two models, two prompts, one direction of travel:

  read        Mathpix OCR            reads the image. Cannot invent anything.
  structure   gpt-4o-mini (TEXT)     splits the OCR text into questions/options.
  describe    gpt-4o (VISION)        only for figure questions: puts the diagram
                                     into words. Describes, never solves.
  solve       deepseek-v4-pro        solves the text. NEVER sees the image.

Mathpix goes first because the failures were math-OCR failures, not reasoning
failures: a vision model flattened `(pi+3)/(pi-1)` into `pi+3`, invented a
fourth option, and turned `3 - e` into `3 + e`. OCR cannot invent an option, and
the structuring model works from its text rather than from pixels.

Mixing those two roles is what produced the original LaTeX bug, so they share
no prompt, no call, and no state beyond the transcribed JSON.

Neither stage may fail quietly. Unparseable JSON gets exactly one retry and then
a visible error — never a canned answer. An illegible question is reported to
the student with what was unclear, and is never handed to the solver.
"""
import base64
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from app import mathpix
from app.drona.prompt_loader import load_prompt
# The repair path the rest of the codebase already uses: json.loads first,
# repair only on failure. Imported, not reimplemented, and not modified.
from app.drona.planner import repair_json_escapes, strip_fences

logger = logging.getLogger("snap")

# AGENTS.md Rule 5 — non-negotiable model strings.
MODEL_TRANSCRIBE = "gpt-4o-mini"
# Diagram description is the one job gpt-4o-mini measurably cannot do. On a real
# two-arrangement figure it called the arc's centre "a straight wire labeled C1",
# merged the two arrangements, and invented a current direction. gpt-4o read the
# same figure correctly, including the structural difference the question turns
# on.
#
# It is not the cost jump it looks like: mini spent 14,871 input tokens on that
# image against gpt-4o's 1,129, so the calls land within ~2x of each other. It
# is also paid only on figure questions, not on every snap.
MODEL_DIAGRAM = "gpt-4o"
# V4-Pro, not Flash: a snap is one shot with no second chance, and a wrong solve
# is silently wrong. Accuracy beats latency here — it is one call per question,
# not one per turn.
MODEL_SOLVE = "deepseek-v4-pro"

TRANSCRIBE_TIMEOUT_S = 45.0
# Pro is slower than Flash; the budget follows the planner's shape rather than
# the tutor's, since nothing here has to feel live.
SOLVE_TIMEOUT_S = 120.0

# Per-submission cap: how many questions are read from ONE photo.
#
# Measured: a solve takes ~23s, so this is a latency ceiling as much as a
# quality one. At 5 a request is ~2 minutes, which is already near what a
# synchronous HTTP request through Vercel and Railway will tolerate. Raising it
# further needs a job queue, not a bigger number.
MAX_QUESTIONS = 5

# Per-student daily cap, counted over a rolling 24 hours. This is the cost and
# abuse control; MAX_QUESTIONS above is the per-photo one. They are different
# axes and both are needed.
DAILY_QUESTION_LIMIT = 50

# Question shapes the transcriber may report. Anything else is treated as
# single_correct when options exist, subjective when they do not.
CHOICE_TYPES = {"single_correct", "multi_correct"}
QUESTION_TYPES = CHOICE_TYPES | {"numerical", "subjective"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/heic"}


# What the student should actually DO about a refusal. Telling someone to
# retake a photo that was already read perfectly sends them round a loop they
# cannot win — measured: two JEE questions were refused on a page Mathpix read
# at confidence_rate 0.9936, where the photo was never the problem.
#
#   retake        their photo — a better one fixes it
#   not_photo     the question needs a figure; no photo fixes it
#   our_side      we read it fine and still could not answer
REMEDY_RETAKE = "retake"
REMEDY_NOT_PHOTO = "not_photo"
REMEDY_OUR_SIDE = "our_side"


class SnapError(Exception):
    """A snap that cannot be completed.

    Carries student-facing text, the stage that failed, and — the part the UI
    needs — what the student can actually do about it.
    """

    def __init__(self, message: str, stage: str, remedy: str = REMEDY_OUR_SIDE,
                 reason: str = "unknown"):
        super().__init__(message)
        self.stage = stage
        self.remedy = remedy
        self.reason = reason


def _openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SnapError("Snap a Doubt is not configured on this server.", "config")
    return OpenAI(api_key=api_key, timeout=TRANSCRIBE_TIMEOUT_S, max_retries=1)


def _deepseek_client() -> OpenAI:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise SnapError("Snap a Doubt is not configured on this server.", "config")
    return OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
        timeout=SOLVE_TIMEOUT_S,
        max_retries=1,
    )


def _assert_model(returned: Optional[str], expected: str, stage: str) -> None:
    """Rule 5 — assert the model string the provider actually served.

    Providers version-suffix their ids (`gpt-4o-mini-2024-07-18`), so a prefix
    match is the honest check. A different family is a hard stop: `deepseek-chat`
    or `deepseek-reasoner` silently served in place of v4-pro is exactly the
    failure Rule 5 exists to catch.
    """
    if not returned:
        logger.warning("[SNAP %s] provider returned no model string", stage.upper())
        return
    if not returned.startswith(expected):
        logger.error(
            "[SNAP %s] MODEL MISMATCH: asked for %s, served %s",
            stage.upper(), expected, returned,
        )
        raise SnapError("Snap a Doubt is misconfigured on this server.", stage)


# LaTeX commands that begin with a JSON escape letter get eaten by json.loads:
#   "\\text{e}"  written as "\text{e}"  -> TAB + "ext{e}"
#   "\\frac{1}{y}" written as "\frac..." -> FORM FEED + "rac{1}{y}"
#   "\\bigg("     written as "\bigg("    -> BACKSPACE + "igg("
# The JSON parses cleanly, so the existing repair path never fires — the damage
# is in the value, not the syntax. Measured on a real page: `$3-<TAB>ext{e}$`,
# which KaTeX cannot render.
#
# Newline is deliberately excluded: it separates options legitimately.
# The escape swallowed BOTH the backslash and the command's first letter, so
# each control character restores to backslash + the letter it came from:
#   TAB -> "\t", giving "\text", "\times", "\theta", "\tan"
#   FF  -> "\f", giving "\frac"
#   BS  -> "\b", giving "\bigg", "\beta"
_CONTROL_TO_LETTER = {
    "\x08": "b", "\x09": "t", "\x0b": "v", "\x0c": "f", "\x0d": "r",
}
_MANGLED_LATEX_RE = re.compile(r"[\x08\x09\x0b\x0c\x0d](?=[a-zA-Z])")


def _repair_latex(value: Any) -> Any:
    """Restores backslashes that JSON escaping ate out of LaTeX commands."""
    if isinstance(value, str):
        return _MANGLED_LATEX_RE.sub(
            lambda m: "\\" + _CONTROL_TO_LETTER[m.group(0)], value
        )
    if isinstance(value, list):
        return [_repair_latex(v) for v in value]
    if isinstance(value, dict):
        return {k: _repair_latex(v) for k, v in value.items()}
    return value


def _parse_json(raw: str, stage: str) -> Dict[str, Any]:
    """json.loads first; repair only on failure. Raises if both fail."""
    text = strip_fences(raw or "")
    if not text.strip():
        raise SnapError("The model returned an empty response.", stage)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = json.loads(repair_json_escapes(text), strict=False)
    return _repair_latex(parsed)


_PARSE_CORRECTIVE = (
    "Your previous response was not valid JSON — it ran on and broke its own "
    "escaping. Answer the same question again, but keep every step under 400 "
    "characters and use at most 6 steps. One move per step, no thinking out "
    "loud. Escape every backslash as \\\\ and every quote inside a string. "
    "Return only the JSON object."
)


def _usage_of(res: Any) -> Dict[str, int]:
    """Token counts as the provider reported them. Zeros when absent."""
    usage = getattr(res, "usage", None)
    return {
        "input": int(getattr(usage, "prompt_tokens", 0) or 0),
        "output": int(getattr(usage, "completion_tokens", 0) or 0),
    }


def _call_with_one_retry(stage: str, call, describe: str,
                         usage_acc: Optional[Dict[str, int]] = None,
                         expect_model: Optional[str] = None) -> Dict[str, Any]:
    """Runs `call()` and parses its JSON, retrying once on a parse failure.

    Every failure is logged with the stage that produced it. After the retry the
    error is visible to the student — there is no canned answer.

    Token usage accumulates into `usage_acc` including retries, so the cost of a
    snap is measured rather than estimated.
    """
    last_raw = ""
    for attempt in (1, 2):
        # The retry says WHY the first attempt failed. Repeating the identical
        # prompt just produced the identical unusable response: a diagram
        # question rambled into a 5,445-character step and broke its own JSON
        # twice in a row.
        res = call(_PARSE_CORRECTIVE if attempt == 2 else None)
        if usage_acc is not None:
            counted = _usage_of(res)
            usage_acc["input"] = usage_acc.get("input", 0) + counted["input"]
            usage_acc["output"] = usage_acc.get("output", 0) + counted["output"]
        _assert_model(
            getattr(res, "model", None),
            expect_model or (MODEL_TRANSCRIBE if stage == "transcribe" else MODEL_SOLVE),
            stage,
        )
        last_raw = res.choices[0].message.content or ""
        try:
            return _parse_json(last_raw, stage)
        except (json.JSONDecodeError, SnapError) as err:
            logger.warning(
                "[SNAP %s] unparseable JSON on attempt %d/2 (%s): %s | raw=%r",
                stage.upper(), attempt, describe, err, last_raw[:400],
            )
    logger.error("[SNAP %s] gave up after 2 attempts (%s)", stage.upper(), describe)
    raise SnapError(
        "Something went wrong at Monk's end reading that back. Please try again.",
        stage, REMEDY_OUR_SIDE, "model_unparseable",
    )


def _norm(text: str) -> str:
    """Loose comparison key: case, spacing and punctuation are noise here."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


# A printed answer key, as exam pages and solution books write it:
#   "ANSWER : D"  "Ans. (B)"  "Answer - 3"  "Correct answer: D"
# Anchored to a line of its own, so a sentence that merely contains the word
# "answer" is left alone.
_PRINTED_ANSWER_RE = re.compile(
    r"(?im)^[\s\*_]*(?:correct\s+)?ans(?:wer)?\s*\.?\s*[:\-–—]?\s*\(?\s*"
    r"([A-Da-d1-4])\s*\)?\s*[\.\)]?\s*$"
)


def _strip_printed_answer(text: str) -> Tuple[str, Optional[str]]:
    """Removes a printed answer key from the question text.

    The transcribe prompt asks for this, but a prompt is not a constraint: the
    key reached the solver anyway on a real exam page, which turns solving into
    copying and makes a wrong solve indistinguishable from a right one. This is
    the enforcement.

    Returns (text without the key, the key that was found or None).
    """
    if not text:
        return text, None

    found: Optional[str] = None

    def _capture(match: "re.Match[str]") -> str:
        nonlocal found
        if found is None:
            found = match.group(1).upper()
        return ""

    cleaned = _PRINTED_ANSWER_RE.sub(_capture, text)
    # Collapse the blank lines the removal leaves behind.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, found


def _clean_options(raw: Any) -> List[Dict[str, str]]:
    """Normalises the transcriber's `options` into [{label, text}].

    Accepts the documented object form and the bare-string form some responses
    fall back to, labelling those A, B, C, … in order.
    """
    if not isinstance(raw, list):
        return []

    options: List[Dict[str, str]] = []
    for idx, item in enumerate(raw):
        if isinstance(item, dict):
            label = str(item.get("label") or "").strip().strip(".)(")
            text = (item.get("text") or "").strip()
        elif isinstance(item, str):
            label, text = "", item.strip()
        else:
            continue
        if not text:
            continue
        if not label:
            label = chr(ord("A") + idx)
        options.append({"label": label.upper(), "text": text})
    return options


# ─── Pass 1: transcribe ──────────────────────────────────────────────────────

def transcribe_questions(image_bytes: bytes, mime_type: str,
                         doubt_id: str = "-",
                         usage_acc: Optional[Dict[str, int]] = None,
                         max_questions: int = MAX_QUESTIONS) -> Dict[str, Any]:
    """Reads up to MAX_QUESTIONS questions off the photo.

    Returns {"questions": [...], "note": str|None}. Each question carries
    `text`, `subject`, `topic`, `legible`, and `note`. Illegible questions are
    returned as-is — the caller decides what to show — and are never solved.
    """
    # 1. OCR. A bad read is detectable here, before any model reasons on it.
    try:
        page = mathpix.read_page(image_bytes, mime_type, doubt_id)
    except mathpix.MathpixNotConfigured as err:
        logger.error("[SNAP] %s", err)
        raise SnapError("Snap a Doubt is not configured on this server.", "config")
    except mathpix.MathpixError as err:
        logger.error("[SNAP TRANSCRIBE] doubt=%s OCR failed: %s", doubt_id[:8], err)
        raise SnapError(
            "Could not read that photo. Try a clearer, well-lit shot.",
            "transcribe", REMEDY_RETAKE, "ocr_failed",
        )

    if not mathpix.confidence_is_usable(page["confidence"]):
        logger.warning(
            "[SNAP TRANSCRIBE] doubt=%s confidence_rate %.4f below %.2f — refusing",
            doubt_id[:8], page["confidence"], mathpix.MIN_CONFIDENCE_RATE,
        )
        raise SnapError(
            "That photo came out too unclear to read reliably. Try again with "
            "more light, the page flat, and the question filling the frame.",
            "transcribe", REMEDY_RETAKE, "photo_unclear",
        )

    # 2. Structure. Text only — no image — so the maths cannot be re-read wrong.
    client = _openai_client()
    system_prompt = load_prompt("snap_structure.md")

    def call(corrective: Optional[str] = None):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"Return at most {max_questions} question(s).\n\n"
                f"OCR TEXT OF THE PAGE:\n{page['text']}"
            )},
        ]
        if corrective:
            messages.append({"role": "user", "content": corrective})
        return client.chat.completions.create(
            model=MODEL_TRANSCRIBE,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=4096,
            timeout=TRANSCRIBE_TIMEOUT_S,
        )

    parsed = _call_with_one_retry("transcribe", call, f"doubt={doubt_id[:8]}", usage_acc)
    parsed["_ocr_confidence"] = page["confidence"]
    parsed["_diagram_regions"] = page.get("diagram_regions", 0)

    raw_questions = parsed.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        logger.error("[SNAP TRANSCRIBE] no questions array | doubt=%s", doubt_id[:8])
        raise SnapError(
            "Monk could not find a question in that photo. Try a clearer, "
            "well-lit shot.",
            "transcribe", REMEDY_RETAKE, "no_question_found",
        )

    note = (parsed.get("note") or "").strip() or None
    if len(raw_questions) > max_questions:
        # Rule 4 is enforced here as well as in the prompt — a prompt is not a
        # constraint.
        note = note or (
            f"More than {max_questions} questions were visible. Monk read the "
            f"first {max_questions}."
        )
        raw_questions = raw_questions[:max_questions]

    questions: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw_questions, 1):
        if not isinstance(item, dict):
            continue
        text, stripped_key = _strip_printed_answer((item.get("text") or "").strip())
        legible = bool(item.get("legible", True))
        # Deliberately NOT named `note`: that is the response-level note above,
        # and shadowing it here silently replaced "a 3rd question was cut off"
        # with the last question's own note.
        q_note = (item.get("note") or "").strip() or None
        q_remedy, q_reason = REMEDY_RETAKE, "illegible"

        # A question with nothing in it is not legible, whatever the flag says.
        if not text:
            legible = False

        options = _clean_options(item.get("options"))

        q_type = (item.get("question_type") or "").strip().lower()
        if q_type not in QUESTION_TYPES:
            # Legacy/loose responses: infer from what actually came back.
            q_type = "single_correct" if len(options) >= 2 else "subjective"
        is_choice = q_type in CHOICE_TYPES

        # A multiple-choice question without its choices is not answerable, and
        # the prompt saying so is not enough — a bare stem reached the solver
        # once and it invented an answer that was not among the options. This is
        # the gate that makes that impossible.
        if is_choice and len(options) < 2:
            legible = False
            q_note = q_note or (
                "This looks like a multiple-choice question, but the options "
                "could not be read. Retake the photo with all the choices in frame."
            )
            q_remedy, q_reason = REMEDY_RETAKE, "options_unreadable"
            logger.warning(
                "[SNAP TRANSCRIBE] doubt=%s q%d %s with %d option(s) — refusing to solve",
                doubt_id[:8], idx, q_type, len(options),
            )

        # A truncated option list is the same defect one step later: the solver
        # picks from a list that is missing the right answer. Measured on a real
        # page whose fourth option was out of frame and got invented.
        if is_choice and item.get("options_complete") is False:
            legible = False
            q_note = q_note or (
                "Some of the answer choices are cut off. Retake the photo with "
                "the whole list of options in frame."
            )
            q_remedy, q_reason = REMEDY_RETAKE, "options_cut_off"
            logger.warning(
                "[SNAP TRANSCRIBE] doubt=%s q%d option list incomplete (%d read)",
                doubt_id[:8], idx, len(options),
            )

        # The solver never sees the image. A question that depends on a figure
        # cannot be answered from its transcription, however complete the words
        # look — one was answered blind from the words "two arrangements".
        # Figure questions are no longer refused here. They go to the describing
        # pass, which puts the diagram into words for the solver. If that pass
        # cannot make the figure out, THEN they are refused — see
        # solve_snapped_image below.
        # The structuring model reads text only, so it cannot see a figure and
        # has to infer one from wording — which it missed on a real page whose
        # stem said "two arrangements of wires" without saying "as shown".
        # Mathpix reporting a diagram region is the authoritative signal.
        # Per-question, from the question's own text. The page-level count is a
        # hint to the structuring model, NOT a verdict on every question: a page
        # with one figure was OR'ing `requires_diagram` onto all of them, so a
        # thermodynamics question and a de Broglie ratio were both refused as
        # "needs the board" because a bob-on-a-string question shared the page.
        needs_diagram = item.get("requires_diagram") is True
        if needs_diagram:
            logger.info(
                "[SNAP TRANSCRIBE] doubt=%s q%d needs a diagram — will describe it",
                doubt_id[:8], idx,
            )

        questions.append({
            "n": idx,
            "text": text,
            "subject": (item.get("subject") or "unknown"),
            "topic": item.get("topic") or None,
            "stem": (item.get("stem") or "").strip() or text,
            # Options are withheld from the solver unless they ARE the question.
            "self_contained": item.get("self_contained") is not False,
            "question_type": q_type,
            "is_multiple_choice": is_choice,
            "options": options,
            "options_complete": item.get("options_complete") is not False,
            "requires_diagram": needs_diagram,
            # Held back from the solver on purpose; used to check it afterwards.
            # `stripped_key` is what the code removed from the text, which is
            # authoritative over the model's own `printed_answer` field.
            "printed_answer": stripped_key or (item.get("printed_answer") or "").strip() or None,
            "legible": legible,
            "note": q_note,
            "remedy": q_remedy,
            "reason": q_reason,
        })

    if not questions:
        raise SnapError(
            "Monk could not find a question in that photo. Try a clearer, "
            "well-lit shot.",
            "transcribe", REMEDY_RETAKE, "no_question_found",
        )

    logger.info(
        "[SNAP TRANSCRIBE] doubt=%s read %d question(s), %d legible",
        doubt_id[:8], len(questions), sum(1 for q in questions if q["legible"]),
    )
    return {"questions": questions, "note": note,
            "ocr_confidence": parsed.get("_ocr_confidence")}


# ─── Pass 1c: describe the figure ────────────────────────────────────────────

def describe_diagram(image_bytes: bytes, mime_type: str, question_text: str,
                     doubt_id: str = "-",
                     usage_acc: Optional[Dict[str, int]] = None) -> Optional[str]:
    """Puts a figure into words so the solver can use it.

    The solver still never sees the image — this is transcription extended to
    the diagram, exactly as the OCR pass is transcription extended to the maths.
    The describing model is told not to solve, for the same reason the OCR pass
    exists: a model that both reads and answers cannot be checked.

    Returns the description, or None when the figure could not be made out well
    enough to solve from. None is a refusal, not an empty string.
    """
    client = _openai_client()
    data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"

    def call(corrective: Optional[str] = None):
        messages = [
            {"role": "system", "content": load_prompt("snap_diagram.md")},
            {"role": "user", "content": [
                {"type": "text",
                 "text": f"The question that needs this figure:\n{question_text}"},
                {"type": "image_url",
                 "image_url": {"url": data_url, "detail": "high"}},
            ]},
        ]
        if corrective:
            messages.append({"role": "user", "content": corrective})
        return client.chat.completions.create(
            model=MODEL_DIAGRAM,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=1200,
            timeout=TRANSCRIBE_TIMEOUT_S,
        )

    try:
        parsed = _call_with_one_retry("transcribe", call, f"diagram={doubt_id[:8]}",
                                      usage_acc, expect_model=MODEL_DIAGRAM)
    except SnapError as err:
        logger.warning("[SNAP DIAGRAM] doubt=%s describe failed: %s", doubt_id[:8], err)
        return None

    if not parsed.get("has_diagram", True):
        logger.info("[SNAP DIAGRAM] doubt=%s no figure found in the image", doubt_id[:8])
        return None
    if parsed.get("sufficient") is False:
        logger.warning("[SNAP DIAGRAM] doubt=%s figure not clear enough: %s",
                       doubt_id[:8], (parsed.get("note") or "")[:160])
        return None

    description = (parsed.get("description") or "").strip()
    if len(description) < 40:
        # A one-line description of a physics figure is not something to solve
        # from; treat it as a failed read rather than pass it on.
        logger.warning("[SNAP DIAGRAM] doubt=%s description too thin (%d chars)",
                       doubt_id[:8], len(description))
        return None

    logger.info("[SNAP DIAGRAM] doubt=%s described in %d chars",
                doubt_id[:8], len(description))
    return description


# ─── Pass 3: match a blind answer to the options ─────────────────────────────

def match_answer_to_options(answer: str, options: List[Dict[str, str]],
                            question_type: str, doubt_id: str = "-",
                            usage_acc: Optional[Dict[str, int]] = None) -> List[str]:
    """Which options equal `answer`. [] when none do.

    Runs only after a blind solve, and only ever compares — it does not solve,
    and it never sees the working. Splitting equality from reasoning is what
    stops a solver bending its result to fit a choice.
    """
    exact = _match_options({"answer": answer}, options)
    if exact:
        return [o["label"] for o in exact]

    client = _openai_client()

    def call(corrective: Optional[str] = None):
        messages = [
            {"role": "system", "content": load_prompt("snap_match.md")},
            {"role": "user", "content": json.dumps({
                "solver_answer": answer,
                "question_type": question_type,
                "options": options,
            }, ensure_ascii=False)},
        ]
        if corrective:
            messages.append({"role": "user", "content": corrective})
        return client.chat.completions.create(
            model=MODEL_TRANSCRIBE,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=500,
            timeout=TRANSCRIBE_TIMEOUT_S,
        )

    try:
        parsed = _call_with_one_retry("transcribe", call, f"match={doubt_id[:8]}",
                                      usage_acc)
    except SnapError as err:
        logger.warning("[SNAP MATCH] doubt=%s matcher failed: %s", doubt_id[:8], err)
        return []

    if parsed.get("equivalent") is False:
        logger.info("[SNAP MATCH] doubt=%s answer %r matches no option: %s",
                    doubt_id[:8], answer[:80], (parsed.get("note") or "")[:120])
        return []

    valid = {o["label"] for o in options}
    labels = [str(l).strip().strip(".)(").upper()
              for l in (parsed.get("option_labels") or [])]
    labels = [l for l in labels if l in valid]
    logger.info("[SNAP MATCH] doubt=%s %r -> %s", doubt_id[:8], answer[:60], labels)
    return labels


# ─── Pass 2: solve ───────────────────────────────────────────────────────────

# A step is one move on a board, not a paragraph of thinking. Measured: a
# 1,062-character step that argued with itself, and a 5,445-character one that
# broke the JSON outright — the rambling and the parse failures are the same
# problem.
# A step is one line on a board. 220 characters is roughly two short sentences,
# which is all a student needs per move — and the ceiling is what stops the
# model using the steps as scratch paper.
MAX_STEP_CHARS = 220
MAX_STEPS = 5

# Phrases that only appear when a model is thinking out loud rather than
# explaining. A student should not be able to tell it was ever uncertain.
_DELIBERATION_MARKERS = (
    "however,", "re-evaluat", "perhaps", "let's check", "let me check",
    "not among the options", "matches option", "wait,", "actually,",
    "on second thought", "this suggests the answer is", "looking at the options",
    # Seen leaking through on a real page: "The ratio is undefined, but
    # interpreting the question as ... The only plausible answer among the
    # options is 2." That is the model reasoning towards a choice, in front of
    # the student.
    "plausible answer", "among the options", "the only option", "closest option",
    "interpreting the question as", "if we assume the question means",
    "which is impossible", "but if we", "assuming instead",
)


def _step_problems(steps: List[Dict[str, Any]]) -> List[str]:
    """What is wrong with these steps, student-readability-wise. [] if nothing."""
    problems: List[str] = []
    if len(steps) > MAX_STEPS:
        problems.append(f"{len(steps)} steps; use at most {MAX_STEPS}")
    for step in steps:
        text = step.get("text") or ""
        if len(text) > MAX_STEP_CHARS:
            problems.append(
                f"step {step.get('n')} is {len(text)} characters; keep each under "
                f"{MAX_STEP_CHARS}"
            )
        lowered = text.lower()
        found = [m for m in _DELIBERATION_MARKERS if m in lowered]
        if found:
            problems.append(
                f"step {step.get('n')} thinks out loud ({', '.join(found[:2])})"
            )
    return problems


def _match_options(parsed: Dict[str, Any],
                   options: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Every option the solver chose, by label or by answer text.

    Returns [] when nothing matches — which is a refusal, not a near miss. A
    ratio that came out as (pi+2)/pi was once stored as the option `pi + 2`
    because they shared a numerator; matching is exact-ish on purpose.
    """
    raw_labels = parsed.get("option_labels")
    if raw_labels is None and parsed.get("option_label") is not None:
        raw_labels = [parsed.get("option_label")]        # older single-label shape
    if isinstance(raw_labels, str):
        raw_labels = [raw_labels]
    if not isinstance(raw_labels, list):
        raw_labels = []

    by_label = {o["label"]: o for o in options}
    chosen: List[Dict[str, str]] = []
    for raw in raw_labels:
        label = str(raw or "").strip().strip(".)(").upper()
        opt = by_label.get(label)
        if opt and opt not in chosen:
            chosen.append(opt)
    if chosen:
        return chosen

    # No usable labels — fall back to matching the answer text against an
    # option, requiring equality rather than containment so a shared fragment
    # cannot pass.
    answer_key = _norm(parsed.get("answer") or "")
    if answer_key:
        for opt in options:
            if _norm(opt["text"]) == answer_key:
                return [opt]
    return []


def _validate_solution(parsed: Dict[str, Any], stage: str = "solve",
                       options: Optional[List[Dict[str, str]]] = None,
                       question_type: str = "subjective",
                       had_diagram: bool = False) -> Dict[str, Any]:
    """A solution without an answer or steps is not a solution.

    For a choice question the answer must be one of the given options, and for
    `single_correct` exactly one of them. A solve that lands outside the list is
    recorded as a failure rather than shown as the answer — picking the
    closest-looking option is the specific behaviour this blocks.
    """
    answer = (parsed.get("answer") or "").strip()
    if not answer:
        raise SnapError("The explanation came back without an answer.", stage)

    # The solver saying "this question is incomplete" is an honest outcome, but
    # it is NOT a solved doubt. Stored as one, the student sees a green "Solved"
    # chip above a non-answer.
    if parsed.get("answerable") is False:
        logger.warning("[SNAP SOLVE] marked unanswerable: %s", answer[:160])
        if had_diagram:
            # The figure was described and the solver still could not use it.
            # Blaming the photo would send the student to retake a picture that
            # was read correctly.
            raise SnapError(
                "Monk could read this question but could not work reliably from "
                "the figure, so it is not guessing. Ask this one in a live "
                "session, where the diagram can be worked through on the board.",
                stage, REMEDY_NOT_PHOTO, "diagram_insufficient",
            )
        raise SnapError(
            answer if len(answer) < 300 else
            "That question is incomplete — some of it is missing from the photo.",
            stage, REMEDY_RETAKE, "question_incomplete",
        )

    chosen: List[Dict[str, str]] = []
    if options and question_type in CHOICE_TYPES:
        chosen = _match_options(parsed, options)
        if not chosen:
            labels = ", ".join(o["label"] for o in options)
            logger.error(
                "[SNAP SOLVE] answer %r matches none of the options (%s)",
                answer[:120], labels,
            )
            raise SnapError(
                "Monk worked through this one and its answer did not match any "
                "of the options, so it is not showing you a guess. Retaking the "
                "photo will not change this — the question is worth asking in a "
                "live session.",
                stage, REMEDY_OUR_SIDE, "no_matching_option",
            )
        if question_type == "single_correct" and len(chosen) > 1:
            logger.warning(
                "[SNAP SOLVE] %d options chosen for a single_correct question; keeping the first",
                len(chosen),
            )
            chosen = chosen[:1]

    raw_steps = parsed.get("steps")
    if not isinstance(raw_steps, list):
        raise SnapError("The explanation came back without steps.", stage)

    steps: List[Dict[str, Any]] = []
    for idx, step in enumerate(raw_steps, 1):
        if isinstance(step, dict):
            text = (step.get("text") or "").strip()
            n = step.get("n") if isinstance(step.get("n"), int) else idx
        elif isinstance(step, str):
            text, n = step.strip(), idx
        else:
            continue
        if text:
            steps.append({"n": n, "text": text})

    if not steps:
        raise SnapError("The explanation came back without steps.", stage)
    if len(steps) > 6:
        logger.warning("[SNAP SOLVE] %d steps returned, target is 3-6", len(steps))

    return {
        # For a choice question the stored answer is the option text itself, so
        # it always reads as one of the printed choices.
        "answer": " and ".join(o["text"] for o in chosen) if chosen else answer,
        "option_labels": [o["label"] for o in chosen],
        "steps": steps,
        "key_idea": (parsed.get("key_idea") or "").strip() or None,
        "subject": (parsed.get("subject") or "").strip() or None,
        "topic": (parsed.get("topic") or "").strip() or None,
    }


def solve_question(question: Dict[str, Any], doubt_id: str = "-",
                   usage_acc: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """Solves ONE transcribed question. The solver never sees the image."""
    if not question.get("legible"):
        # Belt and braces: the caller already filters these out.
        raise SnapError("That question was not legible enough to solve.",
                        "solve", REMEDY_RETAKE, "illegible")

    client = _deepseek_client()
    system_prompt = load_prompt("snap_solve.md")


    # The solver receives the transcription as JSON, exactly as the directive
    # specifies — not a prose paraphrase of it.
    #
    # `printed_answer` is deliberately NOT included. When the page carries an
    # answer key, handing it over turns solving into copying and makes a wrong
    # solve indistinguishable from a right one.
    options = question.get("options") or []
    q_type = question.get("question_type") or "subjective"
    # Options reach the solver ONLY when they are the question itself. For
    # everything else it derives blind and a separate pass matches the result,
    # so there is nothing to talk itself into.
    solve_blind = bool(options) and question.get("self_contained", True)

    payload_obj = {
        "text": question.get("stem") if solve_blind else question.get("text"),
        "subject": question.get("subject"),
        "topic": question.get("topic"),
        "question_type": q_type,
        "options": [] if solve_blind else options,
    }
    if question.get("diagram_description"):
        # Words, not pixels: the solver still never sees the image.
        payload_obj["diagram_description"] = question["diagram_description"]
    payload = json.dumps(payload_obj, ensure_ascii=False)

    def call(corrective: Optional[str] = None):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": payload + "\n\nProduce the solution JSON."},
        ]
        if corrective:
            messages.append({"role": "user", "content": corrective})
        return client.chat.completions.create(
            model=MODEL_SOLVE,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            # 5 steps of 220 characters plus the answer and key idea is well
            # under 700 tokens. The budget is the enforcement: given 4096 the
            # model wrote a single 5,445-character step, broke its own JSON, and
            # failed the question twice. It cannot do that in 1500.
            max_tokens=1500,
            timeout=SOLVE_TIMEOUT_S,
            # Rule 5 — V4 defaults to chain-of-thought and will spend the
            # whole budget thinking, returning an empty string.
            extra_body={"thinking": {"type": "disabled"}},
        )

    parsed = _call_with_one_retry("solve", call, f"doubt={doubt_id[:8]}", usage_acc)

    # Steps are what the student reads. A rambling one is both unreadable and
    # the thing that breaks the JSON, so it earns one corrective retry.
    problems = _step_problems(parsed.get("steps") or [])
    if problems:
        logger.warning("[SNAP SOLVE] doubt=%s poor steps: %s — retrying once",
                       doubt_id[:8], "; ".join(problems[:3]))
        corrective = (
            "Your steps are not usable by a student: " + "; ".join(problems) + ". "
            "Rewrite the SAME solution with the same answer, as at most "
            f"{MAX_STEPS} steps of under {MAX_STEP_CHARS} characters each. Each "
            "step is one move on a board. Remove every trace of deliberation — "
            "no weighing readings, no corrections, no mention of the options. "
            "Return the full JSON again."
        )

        def retry_call(_corrective: Optional[str] = None):
            return client.chat.completions.create(
                model=MODEL_SOLVE,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": payload + "\n\nProduce the solution JSON."},
                    {"role": "assistant", "content": json.dumps(parsed)[:6000]},
                    {"role": "user", "content": corrective},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=1500,
                timeout=SOLVE_TIMEOUT_S,
                extra_body={"thinking": {"type": "disabled"}},
            )

        try:
            retried = _call_with_one_retry("solve", retry_call,
                                           f"doubt={doubt_id[:8]} steps", usage_acc)
            still = _step_problems(retried.get("steps") or [])
            if len(still) < len(problems):
                parsed = retried
                logger.info("[SNAP SOLVE] doubt=%s steps rewritten (%d problems left)",
                            doubt_id[:8], len(still))
            else:
                logger.warning("[SNAP SOLVE] doubt=%s rewrite did not improve the steps",
                               doubt_id[:8])
        except SnapError as err:
            # The first answer is still good; keep it rather than lose the solve.
            logger.warning("[SNAP SOLVE] doubt=%s step rewrite failed: %s",
                           doubt_id[:8], err)
    solution = _validate_solution(
        parsed,
        # A blind solve has no options to validate against; the matcher below
        # does that instead.
        options=[] if solve_blind else options,
        question_type=q_type,
        had_diagram=bool(question.get("diagram_description")),
    )

    if solve_blind:
        labels = match_answer_to_options(solution["answer"], options, q_type,
                                         doubt_id, usage_acc)
        if not labels:
            # Not a refusal. The student gets the working and the result, clearly
            # flagged as not matching — that is more useful than nothing, and it
            # is honest in a way that silently picking the nearest option is not.
            # Throwing away a correct derivation because the OCR mangled an
            # option would be the worst of both.
            logger.warning(
                "[SNAP SOLVE] doubt=%s derived %r matches no option — flagging, not refusing",
                doubt_id[:8], solution["answer"][:100],
            )
            solution["option_labels"] = []
            solution["unmatched"] = True
            solution["unmatched_note"] = (
                f"Monk worked this out as \u201c{solution['answer']}\u201d, which is not "
                "one of the options on the page. Either an option was misread from "
                "the photo, or Monk has this one wrong \u2014 the working is below so "
                "you can judge, and it is worth checking in a session."
            )
        if q_type == "single_correct":
            labels = labels[:1]
        chosen = [o for o in options if o["label"] in labels]
        solution["option_labels"] = labels
        solution["answer"] = " and ".join(o["text"] for o in chosen) or solution["answer"]

    # Free correctness signal: the page's own answer key, which the solver never
    # saw. A disagreement does not change what the student is shown — the key
    # itself may have been misread — but it must be countable, not invisible.
    printed = question.get("printed_answer")
    if printed:
        printed_key = _norm(printed)
        chosen_label = _norm("".join(solution.get("option_labels") or []))
        agrees = bool(chosen_label) and printed_key == chosen_label
        if not agrees:
            agrees = printed_key in _norm(solution["answer"]) or _norm(solution["answer"]) in printed_key
        solution["printed_answer"] = printed
        solution["agrees_with_printed_answer"] = agrees
        logger.log(
            logging.WARNING if not agrees else logging.INFO,
            "[SNAP ANSWER CHECK] doubt=%s printed=%r solver=%r (%s) -> %s",
            doubt_id[:8], printed, solution.get("option_labels"),
            solution["answer"][:60],
            "AGREES" if agrees else "DISAGREES",
        )

    # The transcriber saw the page; it wins on subject/topic when the solver is
    # vague, but the solver's own reading is preferred when it has one.
    solution["subject"] = solution["subject"] or (
        question.get("subject") if question.get("subject") != "unknown" else None
    )
    solution["topic"] = solution["topic"] or question.get("topic")
    return solution


# ─── The pipeline ────────────────────────────────────────────────────────────

def iter_snapped_questions(image_bytes: bytes, mime_type: str,
                           doubt_id: str = "-",
                           max_questions: int = MAX_QUESTIONS):
    """Yields each question as soon as IT is done, rather than after all of them.

    A solve takes ~25s, so a page of five kept the student watching a spinner for
    over two minutes before anything appeared. The work is identical; only the
    delivery changes.

    Yields ("meta", {...}) first, then ("question", {...}) per question, then
    ("summary", {...}). Raises SnapError if the page cannot be read at all —
    that failure happens before any question exists.
    """
    started = time.time()
    tx_usage: Dict[str, int] = {"input": 0, "output": 0}
    sv_usage: Dict[str, int] = {"input": 0, "output": 0}

    read = transcribe_questions(image_bytes, mime_type, doubt_id, tx_usage,
                                max_questions)
    transcribe_ms = int((time.time() - started) * 1000)

    yield "meta", {
        "question_count": len(read["questions"]),
        "note": read["note"],
        "ocr_confidence": read.get("ocr_confidence"),
        "transcribe_ms": transcribe_ms,
    }

    solved_count = 0
    for question in read["questions"]:
        if question.get("requires_diagram") and question["legible"]:
            description = describe_diagram(
                image_bytes, mime_type, question.get("text") or "", doubt_id, tx_usage
            )
            if description:
                question["diagram_description"] = description
            else:
                question["legible"] = False
                question["remedy"] = REMEDY_NOT_PHOTO
                question["reason"] = "diagram_unreadable"
                question["note"] = (
                    "This question needs its diagram, and Monk could not make the "
                    "figure out clearly enough to solve from. If the figure is cut "
                    "off, retake the photo with all of it in frame — otherwise ask "
                    "this one in a live session, where the board can be used."
                )

        if question["legible"]:
            try:
                question["solution"] = solve_question(question, doubt_id, sv_usage)
                solved_count += 1
            except SnapError as err:
                logger.error("[SNAP SOLVE FAILED] doubt=%s q%d: %s",
                             doubt_id[:8], question["n"], err)
                question["solve_error"] = str(err)
                question["solve_remedy"] = err.remedy
                question["solve_reason"] = err.reason
        else:
            logger.info("[SNAP] doubt=%s q%d not solvable: %s",
                        doubt_id[:8], question["n"], question.get("note"))

        yield "question", question

    latency_ms = int((time.time() - started) * 1000)
    logger.info(
        "[SNAP] doubt=%s solved %d/%d in %dms (transcribe %dms)",
        doubt_id[:8], solved_count, len(read["questions"]), latency_ms, transcribe_ms,
    )
    logger.info(
        "[SNAP TOKENS] doubt=%s transcribe in=%d out=%d | solve in=%d out=%d",
        doubt_id[:8], tx_usage["input"], tx_usage["output"],
        sv_usage["input"], sv_usage["output"],
    )
    yield "summary", {
        "solved_count": solved_count,
        "note": read["note"],
        "transcriber_model": MODEL_TRANSCRIBE,
        "solver_model": MODEL_SOLVE,
        "transcribe_ms": transcribe_ms,
        "latency_ms": latency_ms,
        "usage": {"transcribe": tx_usage, "solve": sv_usage},
    }


def solve_snapped_image(image_bytes: bytes, mime_type: str,
                        doubt_id: str = "-",
                        max_questions: int = MAX_QUESTIONS) -> Dict[str, Any]:
    """Transcribe, then solve each legible question.

    Returns {"questions": [...], "note": str|None, ...timings}. Each entry has
    `legible`; legible ones also carry `solution`. Illegible ones carry the
    transcriber's `note` saying what was unclear and are never solved.
    """
    started = time.time()
    tx_usage: Dict[str, int] = {"input": 0, "output": 0}
    sv_usage: Dict[str, int] = {"input": 0, "output": 0}
    read = transcribe_questions(image_bytes, mime_type, doubt_id, tx_usage,
                                max_questions)
    transcribe_ms = int((time.time() - started) * 1000)

    solved_count = 0
    for question in read["questions"]:
        # A figure question gets its diagram put into words first. Only if that
        # fails is it refused — and then honestly, as "the figure could not be
        # made out", not as "your photo is bad".
        if question.get("requires_diagram") and question["legible"]:
            description = describe_diagram(
                image_bytes, mime_type, question.get("text") or "", doubt_id, tx_usage
            )
            if description:
                question["diagram_description"] = description
            else:
                question["legible"] = False
                question["remedy"] = REMEDY_NOT_PHOTO
                question["reason"] = "diagram_unreadable"
                question["note"] = (
                    "This question needs its diagram, and Monk could not make the "
                    "figure out clearly enough to solve from. If the figure is cut "
                    "off, retake the photo with all of it in frame — otherwise ask "
                    "this one in a live session, where the board can be used."
                )

        if not question["legible"]:
            logger.info(
                "[SNAP] doubt=%s q%d illegible, not sent to solver: %s",
                doubt_id[:8], question["n"], question.get("note"),
            )
            continue
        try:
            question["solution"] = solve_question(question, doubt_id, sv_usage)
            solved_count += 1
        except SnapError as err:
            # One question failing must not lose the other one.
            logger.error(
                "[SNAP SOLVE FAILED] doubt=%s q%d: %s", doubt_id[:8], question["n"], err
            )
            question["legible"] = True
            question["solve_error"] = str(err)
            question["solve_remedy"] = err.remedy
            question["solve_reason"] = err.reason

    if solved_count == 0:
        # Nothing was solved. Surface the most specific reason we have rather
        # than storing a doubt that shows the student an empty panel.
        first = read["questions"][0]
        reason = (
            first.get("solve_error")
            or first.get("note")
            or "Monk could not read that question clearly enough to solve it."
        )
        # Carry the question's own remedy through. Defaulting to our_side here
        # threw away "retake the photo" and "this needs a diagram", so the
        # client saw a generic failure for every cause.
        if first.get("solve_error"):
            # The solve failed: its remedy describes the cause, not the
            # question's transcribe-time default.
            raise SnapError(reason, "solve",
                            first.get("solve_remedy") or REMEDY_OUR_SIDE,
                            first.get("solve_reason") or "unknown")
        raise SnapError(reason, "transcribe",
                        first.get("remedy") or REMEDY_OUR_SIDE,
                        first.get("reason") or "unknown")

    latency_ms = int((time.time() - started) * 1000)
    logger.info(
        "[SNAP] doubt=%s solved %d/%d in %dms (transcribe %dms)",
        doubt_id[:8], solved_count, len(read["questions"]), latency_ms, transcribe_ms,
    )
    logger.info(
        "[SNAP TOKENS] doubt=%s transcribe in=%d out=%d | solve in=%d out=%d",
        doubt_id[:8], tx_usage["input"], tx_usage["output"],
        sv_usage["input"], sv_usage["output"],
    )

    return {
        "questions": read["questions"],
        "note": read["note"],
        "ocr_confidence": read.get("ocr_confidence"),
        "solved_count": solved_count,
        "transcriber_model": MODEL_TRANSCRIBE,
        "solver_model": MODEL_SOLVE,
        "transcribe_ms": transcribe_ms,
        "latency_ms": latency_ms,
        "usage": {"transcribe": tx_usage, "solve": sv_usage},
    }
