"""Snap a Doubt — photograph of a question in, worked explanation out.

Two models, two prompts, one direction of travel:

  transcribe  gpt-4o-mini (vision)   reads the image. NEVER solves.
  solve       deepseek-v4-pro        solves the text. NEVER sees the image.

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

from app.drona.prompt_loader import load_prompt
# The repair path the rest of the codebase already uses: json.loads first,
# repair only on failure. Imported, not reimplemented, and not modified.
from app.drona.planner import repair_json_escapes, strip_fences

logger = logging.getLogger("snap")

# AGENTS.md Rule 5 — non-negotiable model strings.
MODEL_TRANSCRIBE = "gpt-4o-mini"
# V4-Pro, not Flash: a snap is one shot with no second chance, and a wrong solve
# is silently wrong. Accuracy beats latency here — it is one call per question,
# not one per turn.
MODEL_SOLVE = "deepseek-v4-pro"

TRANSCRIBE_TIMEOUT_S = 45.0
# Pro is slower than Flash; the budget follows the planner's shape rather than
# the tutor's, since nothing here has to feel live.
SOLVE_TIMEOUT_S = 120.0

MAX_QUESTIONS = 2                    # enforced server-side, per the directive
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/heic"}


class SnapError(Exception):
    """A snap that cannot be completed. Carries student-facing text and a stage."""

    def __init__(self, message: str, stage: str):
        super().__init__(message)
        self.stage = stage


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


def _parse_json(raw: str, stage: str) -> Dict[str, Any]:
    """json.loads first; repair only on failure. Raises if both fail."""
    text = strip_fences(raw or "")
    if not text.strip():
        raise SnapError("The model returned an empty response.", stage)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(repair_json_escapes(text), strict=False)


def _call_with_one_retry(stage: str, call, describe: str) -> Dict[str, Any]:
    """Runs `call()` and parses its JSON, retrying once on a parse failure.

    Every failure is logged with the stage that produced it. After the retry the
    error is visible to the student — there is no canned answer.
    """
    last_raw = ""
    for attempt in (1, 2):
        res = call()
        _assert_model(getattr(res, "model", None),
                      MODEL_TRANSCRIBE if stage == "transcribe" else MODEL_SOLVE,
                      stage)
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
        "Monk could not read that back properly. Please try again.", stage
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
                         doubt_id: str = "-") -> Dict[str, Any]:
    """Reads up to MAX_QUESTIONS questions off the photo.

    Returns {"questions": [...], "note": str|None}. Each question carries
    `text`, `subject`, `topic`, `legible`, and `note`. Illegible questions are
    returned as-is — the caller decides what to show — and are never solved.
    """
    client = _openai_client()
    data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"
    system_prompt = load_prompt("snap_transcribe.md")

    def call():
        return client.chat.completions.create(
            model=MODEL_TRANSCRIBE,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": "Transcribe the question(s) in this image."},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                ]},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=1500,
            timeout=TRANSCRIBE_TIMEOUT_S,
        )

    parsed = _call_with_one_retry("transcribe", call, f"doubt={doubt_id[:8]}")

    raw_questions = parsed.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        logger.error("[SNAP TRANSCRIBE] no questions array | doubt=%s", doubt_id[:8])
        raise SnapError(
            "Monk could not find a question in that photo. Try a clearer, "
            "well-lit shot.",
            "transcribe",
        )

    note = (parsed.get("note") or "").strip() or None
    if len(raw_questions) > MAX_QUESTIONS:
        # Rule 4 is enforced here as well as in the prompt — a prompt is not a
        # constraint.
        note = note or (
            f"More than {MAX_QUESTIONS} questions were visible. Monk read the "
            f"first {MAX_QUESTIONS}."
        )
        raw_questions = raw_questions[:MAX_QUESTIONS]

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

        # A question with nothing in it is not legible, whatever the flag says.
        if not text:
            legible = False

        options = _clean_options(item.get("options"))
        is_mcq = bool(item.get("is_multiple_choice")) or len(options) >= 2

        # A multiple-choice question without its choices is not answerable, and
        # the prompt saying so is not enough — a bare stem reached the solver
        # once and it invented an answer that was not among the options. This is
        # the gate that makes that impossible.
        if is_mcq and len(options) < 2:
            legible = False
            q_note = q_note or (
                "This looks like a multiple-choice question, but the options "
                "could not be read. Retake the photo with all the choices in frame."
            )
            logger.warning(
                "[SNAP TRANSCRIBE] doubt=%s q%d MCQ with %d option(s) — refusing to solve",
                doubt_id[:8], idx, len(options),
            )

        questions.append({
            "n": idx,
            "text": text,
            "subject": (item.get("subject") or "unknown"),
            "topic": item.get("topic") or None,
            "is_multiple_choice": is_mcq,
            "options": options,
            # Held back from the solver on purpose; used to check it afterwards.
            # `stripped_key` is what the code removed from the text, which is
            # authoritative over the model's own `printed_answer` field.
            "printed_answer": stripped_key or (item.get("printed_answer") or "").strip() or None,
            "legible": legible,
            "note": q_note,
        })

    if not questions:
        raise SnapError(
            "Monk could not find a question in that photo. Try a clearer, "
            "well-lit shot.",
            "transcribe",
        )

    logger.info(
        "[SNAP TRANSCRIBE] doubt=%s read %d question(s), %d legible",
        doubt_id[:8], len(questions), sum(1 for q in questions if q["legible"]),
    )
    return {"questions": questions, "note": note}


# ─── Pass 2: solve ───────────────────────────────────────────────────────────

def _match_option(parsed: Dict[str, Any],
                  options: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """The option the solver chose, by label or by answer text. None if neither."""
    label = str(parsed.get("option_label") or "").strip().strip(".)(").upper()
    if label:
        for opt in options:
            if opt["label"] == label:
                return opt

    answer_key = _norm(parsed.get("answer") or "")
    if answer_key:
        for opt in options:
            opt_key = _norm(opt["text"])
            if opt_key and (opt_key == answer_key or opt_key in answer_key):
                return opt
    return None


def _validate_solution(parsed: Dict[str, Any], stage: str = "solve",
                       options: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """A solution without an answer or steps is not a solution.

    When the question is multiple-choice, the answer must be one of the given
    options. A solve that lands outside them is recorded as a failure rather
    than shown to the student as though it were the answer — that exact case
    (a bare stem, an invented answer, stored as 'solved') is why this check
    exists.
    """
    answer = (parsed.get("answer") or "").strip()
    if not answer:
        raise SnapError("The explanation came back without an answer.", stage)

    # The solver saying "this question is incomplete" is an honest outcome, but
    # it is NOT a solved doubt. Stored as one, the student sees a green "Solved"
    # chip above a non-answer — measured on a cropped photo whose options were
    # out of frame.
    if parsed.get("answerable") is False:
        logger.warning("[SNAP SOLVE] marked unanswerable: %s", answer[:160])
        raise SnapError(
            answer if len(answer) < 300 else
            "That question is incomplete — some of it is missing from the photo.",
            stage,
        )

    chosen: Optional[Dict[str, str]] = None
    if options:
        chosen = _match_option(parsed, options)
        if chosen is None:
            labels = ", ".join(o["label"] for o in options)
            logger.error(
                "[SNAP SOLVE] answer %r matches none of the options (%s)",
                answer[:120], labels,
            )
            raise SnapError(
                "Monk worked through this one but could not settle on any of "
                "the given options. Rather than guess, it is flagged for review.",
                stage,
            )

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
        # For an MCQ the stored answer is the option's own text, so it always
        # reads as one of the printed choices.
        "answer": chosen["text"] if chosen else answer,
        "option_label": chosen["label"] if chosen else None,
        "steps": steps,
        "key_idea": (parsed.get("key_idea") or "").strip() or None,
        "subject": (parsed.get("subject") or "").strip() or None,
        "topic": (parsed.get("topic") or "").strip() or None,
    }


def solve_question(question: Dict[str, Any], doubt_id: str = "-") -> Dict[str, Any]:
    """Solves ONE transcribed question. The solver never sees the image."""
    if not question.get("legible"):
        # Belt and braces: the caller already filters these out.
        raise SnapError("That question was not legible enough to solve.", "solve")

    client = _deepseek_client()
    system_prompt = load_prompt("snap_solve.md")

    # The solver receives the transcription as JSON, exactly as the directive
    # specifies — not a prose paraphrase of it.
    #
    # `printed_answer` is deliberately NOT included. When the page carries an
    # answer key, handing it over turns solving into copying and makes a wrong
    # solve indistinguishable from a right one.
    payload = json.dumps({
        "text": question.get("text"),
        "subject": question.get("subject"),
        "topic": question.get("topic"),
        "is_multiple_choice": question.get("is_multiple_choice", False),
        "options": question.get("options") or [],
    }, ensure_ascii=False)

    def call():
        return client.chat.completions.create(
            model=MODEL_SOLVE,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": payload + "\n\nProduce the solution JSON."},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=2048,
            timeout=SOLVE_TIMEOUT_S,
            # Rule 5 — V4 defaults to chain-of-thought and will spend the
            # whole budget thinking, returning an empty string.
            extra_body={"thinking": {"type": "disabled"}},
        )

    parsed = _call_with_one_retry("solve", call, f"doubt={doubt_id[:8]}")
    solution = _validate_solution(parsed, options=question.get("options") or [])

    # Free correctness signal: the page's own answer key, which the solver never
    # saw. A disagreement does not change what the student is shown — the key
    # itself may have been misread — but it must be countable, not invisible.
    printed = question.get("printed_answer")
    if printed:
        printed_key = _norm(printed)
        chosen_label = _norm(solution.get("option_label") or "")
        agrees = bool(chosen_label) and printed_key == chosen_label
        if not agrees:
            agrees = printed_key in _norm(solution["answer"]) or _norm(solution["answer"]) in printed_key
        solution["printed_answer"] = printed
        solution["agrees_with_printed_answer"] = agrees
        logger.log(
            logging.WARNING if not agrees else logging.INFO,
            "[SNAP ANSWER CHECK] doubt=%s printed=%r solver=%r (%s) -> %s",
            doubt_id[:8], printed, solution.get("option_label"),
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

def solve_snapped_image(image_bytes: bytes, mime_type: str,
                        doubt_id: str = "-") -> Dict[str, Any]:
    """Transcribe, then solve each legible question.

    Returns {"questions": [...], "note": str|None, ...timings}. Each entry has
    `legible`; legible ones also carry `solution`. Illegible ones carry the
    transcriber's `note` saying what was unclear and are never solved.
    """
    started = time.time()
    read = transcribe_questions(image_bytes, mime_type, doubt_id)
    transcribe_ms = int((time.time() - started) * 1000)

    solved_count = 0
    for question in read["questions"]:
        if not question["legible"]:
            logger.info(
                "[SNAP] doubt=%s q%d illegible, not sent to solver: %s",
                doubt_id[:8], question["n"], question.get("note"),
            )
            continue
        try:
            question["solution"] = solve_question(question, doubt_id)
            solved_count += 1
        except SnapError as err:
            # One question failing must not lose the other one.
            logger.error(
                "[SNAP SOLVE FAILED] doubt=%s q%d: %s", doubt_id[:8], question["n"], err
            )
            question["legible"] = True
            question["solve_error"] = str(err)

    if solved_count == 0:
        # Nothing was solved. Surface the most specific reason we have rather
        # than storing a doubt that shows the student an empty panel.
        first = read["questions"][0]
        reason = (
            first.get("solve_error")
            or first.get("note")
            or "Monk could not read that question clearly enough to solve it."
        )
        raise SnapError(reason, "solve" if first.get("solve_error") else "transcribe")

    latency_ms = int((time.time() - started) * 1000)
    logger.info(
        "[SNAP] doubt=%s solved %d/%d in %dms (transcribe %dms)",
        doubt_id[:8], solved_count, len(read["questions"]), latency_ms, transcribe_ms,
    )

    return {
        "questions": read["questions"],
        "note": read["note"],
        "solved_count": solved_count,
        "transcriber_model": MODEL_TRANSCRIBE,
        "solver_model": MODEL_SOLVE,
        "transcribe_ms": transcribe_ms,
        "latency_ms": latency_ms,
    }
