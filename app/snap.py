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
import io
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from app import mathpix, storage_r2
from app.image_prep import crop_to_content
from app.exam_scope import canonical_subject
from app.drona.prompt_loader import load_prompt
# The repair path the rest of the codebase already uses: json.loads first,
# repair only on failure. Imported, not reimplemented, and not modified.
from app.drona.planner import repair_json_escapes, strip_fences
# The _bg variant: recording must never add a PostgREST round-trip to a live
# student turn. Aliased so tests can stub one name.
from app.drona.usage import record_call_bg as record_call

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
#
# 75, not 120. Measured across real submissions, a solve that works lands in
# 9-35s, so 120 was never protecting a slow success — it was the ceiling a
# WEDGED solve ran to. One diagram question spent 2m13s producing an empty
# response (Rule 5's failure: v4 spends the whole budget thinking and emits
# nothing), and because that reads as a parse failure it earned a second full
# attempt. The student waits for the slowest question, so one wedge cost them
# four minutes. 75s still leaves better than 2x headroom over the slowest
# solve ever recorded.
SOLVE_TIMEOUT_S = 75.0
# A retry is for a solve that came back WRONG, not one that never came back.
# When an attempt burns most of its budget it did not fail fast — it wedged,
# and repeating it with identical inputs wedges again for the same duration.
# Past this share of the timeout, stop and report honestly instead.
RETRY_IF_UNDER_FRACTION = 0.6
# Reasoning tokens are spent from the SAME allowance as the answer, so this
# ceiling is not "how long may the answer be" — it is "how long may the
# thinking plus the answer be". Measured on a figure question that returned
# nothing: 8000 in, 8000 spent, zero of it content. The model reasoned until
# the allowance was gone and had none left to write the JSON with, which
# surfaces as an empty response rather than as an error.
#
# A figure question is the expensive case — it reasons about a described
# diagram on top of the physics — and it is the one that has actually wedged,
# twice. So the allowance is generous, and generous again when a diagram is in
# play. It costs nothing when unused: only tokens actually generated are
# billed.
THINKING_MAX_TOKENS = 16000
THINKING_MAX_TOKENS_DIAGRAM = 24000

# Per-submission cap: how many questions are read from ONE photo.
#
# Measured: a solve takes ~23-30s (thinking-on), so this is a latency ceiling
# as much as a quality one. At 3, a full page is ~90s streamed live (steps
# print as each question is worked, so the wait is never silent) — 5 pushed
# past what a synchronous HTTP request through Vercel and Railway comfortably
# tolerates. Raising it further needs a job queue, not a bigger number.
MAX_QUESTIONS = 3

# Per-student daily cap, counted over a rolling 24 hours. This is the cost and
# abuse control; MAX_QUESTIONS above is the per-photo one. They are different
# axes and both are needed.
DAILY_QUESTION_LIMIT = 50

# Question shapes the transcriber may report. Anything else is treated as
# single_correct when options exist, subjective when they do not.
CHOICE_TYPES = {"single_correct", "multi_correct"}
# How many choices a JEE or NEET paper prints. Both are standardised on four,
# across single-correct, multi-correct, assertion-reason and match-the-column.
# Fewer than this in frame means the rest were cropped out.
EXPECTED_CHOICE_OPTIONS = 4
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
                         expect_model: Optional[str] = None,
                         service: str = "snap") -> Dict[str, Any]:
    """Runs `call()` and parses its JSON, retrying once on a parse failure.

    Every failure is logged with the stage that produced it. After the retry the
    error is visible to the student — there is no canned answer.

    Token usage accumulates into `usage_acc` including retries, so the cost of a
    snap is measured rather than estimated. Every attempt is also recorded to
    `llm_calls` under `service`. ok=False means the attempt billed and its
    result was discarded — an API error, a substituted model, or unparseable
    JSON — matching the column's meaning in migrations/0018_llm_calls.sql.
    """
    model = expect_model or (MODEL_TRANSCRIBE if stage == "transcribe" else MODEL_SOLVE)
    last_raw = ""
    for attempt in (1, 2):
        # The retry says WHY the first attempt failed. Repeating the identical
        # prompt just produced the identical unusable response: a diagram
        # question rambled into a 5,445-character step and broke its own JSON
        # twice in a row.
        t0 = time.time()
        try:
            res = call(_PARSE_CORRECTIVE if attempt == 2 else None)
        except Exception as exc:
            record_call(model, service, ok=False, attempt=attempt,
                        latency_ms=int((time.time() - t0) * 1000),
                        subtopic_key=describe, error=str(exc))
            raise
        latency_ms = int((time.time() - t0) * 1000)

        def _record(ok: bool, error: Optional[str] = None,
                    _attempt: int = attempt) -> None:
            record_call(model, service, ok=ok, attempt=_attempt, res=res,
                        latency_ms=latency_ms, subtopic_key=describe,
                        error=error)

        if usage_acc is not None:
            counted = _usage_of(res)
            usage_acc["input"] = usage_acc.get("input", 0) + counted["input"]
            usage_acc["output"] = usage_acc.get("output", 0) + counted["output"]
        try:
            _assert_model(getattr(res, "model", None), model, stage)
        except SnapError as err:
            _record(False, f"model mismatch: {err}")
            raise
        message = res.choices[0].message
        last_raw = message.content or ""
        if not last_raw.strip() and getattr(message, "reasoning_content", None):
            logger.warning(
                "[SNAP %s] response was ALL reasoning, no content (%d chars of "
                "thinking) — the Rule 5 failure mode, observed live",
                stage.upper(), len(message.reasoning_content or ""),
            )
        try:
            parsed = _parse_json(last_raw, stage)
        except (json.JSONDecodeError, SnapError) as err:
            _record(False, f"unparseable JSON: {err}")
            logger.warning(
                "[SNAP %s] unparseable JSON on attempt %d/2 (%s): %s | raw=%r",
                stage.upper(), attempt, describe, err, last_raw[:400],
            )
        else:
            _record(True)
            return parsed
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


# Comparison form for the fidelity gate. Keeps signs and structure — snap._norm
# strips '+'/'-', which would let a 3+e/3-e mutation pass as identical.
_LATEX_NOISE = ("\\mathrm", "\\text", "\\left", "\\right", "\\operatorname",
                "\\dfrac", "\\frac", "\\;", "\\,")


def _canon_fidelity(text: str) -> str:
    t = (text or "").lower()
    for cmd in _LATEX_NOISE:
        t = t.replace(cmd, "")
    return re.sub(r"[${}\\ ,_~]", "", t)


def _options_found_in_ocr(options: List[Dict[str, str]], ocr_text: str) -> List[str]:
    """Labels of options whose text does NOT appear in the OCR page.

    The structuring model is told to copy options verbatim; this is the check
    that it did. An option it invented, completed, or sign-flipped is not on
    the page — measured failures include a fabricated fourth option and
    "3-e" arriving as "3+e".
    """
    page = _canon_fidelity(ocr_text)
    missing = []
    for opt in options:
        body = _canon_fidelity(opt["text"])
        if body and body not in page:
            missing.append(opt["label"])
    return missing


def options_missing_for_choice(is_choice: bool, options: List[Dict[str, str]],
                               item: Dict[str, Any]) -> bool:
    """Whether a CHOICE question is missing choices it genuinely needs.

    The one refusal that must survive every "let it through" override below: a
    multiple-choice question without its options reached the solver once and it
    invented an answer that was not among them.
    """
    if not is_choice:
        return False
    return len(options) < 2 or item.get("options_complete") is False


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

    # The confidence floor is gone, deliberately. Watermarked scans — exactly
    # what students photograph — scored 0.8177 while reading perfectly (1,748
    # clean chars), so the floor produced false refusals. Bad reads are caught
    # downstream instead, where they actually show: an answer matching no
    # option is flagged 'unsure', a bare MCQ stem is refused, and the score is
    # logged so drift stays measurable.
    if not mathpix.confidence_is_usable(page["confidence"]):
        logger.warning(
            "[SNAP TRANSCRIBE] doubt=%s low confidence_rate %.4f — proceeding, "
            "downstream gates will judge the read",
            doubt_id[:8], page["confidence"],
        )

    # `page_confidence` is Mathpix's verdict on the read AS A WHOLE. It is worth
    # logging and it is NOT worth acting on: measured against pages built to
    # match a real submission, the tiled "mathongo" watermarks a coaching PDF
    # carries drag it to 0.15 while the read is perfect — all six questions,
    # 2,016 characters. Treating it as a partial-read signal told students to
    # crop a photo that had been read correctly, so it is diagnostic only.
    if page.get("page_confidence") is not None and page["page_confidence"] < 0.25:
        logger.info(
            "[SNAP TRANSCRIBE] doubt=%s low page_confidence %.4f (confidence_rate "
            "%.4f, %d chars) — normal on a watermarked page; logged, not acted on",
            doubt_id[:8], page["page_confidence"], page["confidence"] or -1,
            len(page["text"]),
        )

    # 2. Structure. Text only — no image — so the maths cannot be re-read wrong.
    # Timed separately from the OCR above: `transcribe_ms` used to be the sum of
    # both, so a slow submission gave no clue whether Mathpix or the structuring
    # model was responsible. On a dense JEE page the two are the same order of
    # magnitude, and only one of them is ours to tune.
    structure_t0 = time.time()
    client = _openai_client()
    system_prompt = load_prompt("snap_structure.md")

    # "The FIRST N, top to bottom" was still only a request, and the model
    # ignored it twice on real pages: Q11-Q19 came back as Q16-Q18, and
    # Q62-Q66 came back as Q64-Q66. When the page prints its question numbers
    # — every JEE paper does — we can stop asking and start naming: the numbers
    # are read out of the OCR text in code, and the model is told exactly which
    # ones to return. That converts a preference into a checkable instruction,
    # and the check below is what makes it stick.
    page_numbers = _question_numbers_in(page["text"])
    wanted_numbers = page_numbers[:max_questions]
    if wanted_numbers:
        logger.info(
            "[SNAP STRUCTURE] doubt=%s page prints questions %s -> asking for %s",
            doubt_id[:8], page_numbers, wanted_numbers,
        )

    def _selection_instruction(extra: str = "") -> str:
        if wanted_numbers:
            listed = ", ".join(f"Q{n}" for n in wanted_numbers)
            return (
                f"This page prints questions numbered "
                f"{', '.join(f'Q{n}' for n in page_numbers)}.\n"
                f"Return EXACTLY these {len(wanted_numbers)}: {listed}. They are "
                f"the first ones on the page. Do NOT return any other question, "
                f"and do not skip one because it looks hard, has a diagram, or "
                f"has options you cannot read — a question you cannot fully read "
                f"is still returned, with `legible: false` and a `note` saying "
                f"what was unclear. Only mention unread questions in the "
                f"top-level `note` if the text below actually contains more than "
                f"these {len(wanted_numbers)}.{extra}"
            )
        return (
            f"Return the FIRST {max_questions} question(s) on this page, "
            f"reading top to bottom — not whichever {max_questions} look "
            f"clearest or easiest. A question you cannot fully read is still "
            f"returned, with `legible: false` and a `note`; do not silently skip "
            f"it and take a later one instead. If the page holds more, return "
            f"the first {max_questions} in page order and say so in the "
            f"top-level `note`.{extra}"
        )

    def _make_call(extra: str = ""):
        def call(corrective: Optional[str] = None):
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": (
                    f"{_selection_instruction(extra)}\n\n"
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
        return call

    # One call per question, in parallel, when the page is numbered and holds
    # more than one of them. The single whole-page call is dominated by how
    # many output tokens it has to generate — 10.5s for three questions on a
    # real submission — and that work divides cleanly: each slice of the OCR
    # text between two question numbers contains exactly one question and its
    # options. Three ~1/3-size calls run concurrently instead of one long one.
    #
    # Falls back to the whole-page call whenever the split is not obviously
    # safe: an unnumbered page, a single question, or slices that came out
    # empty. A mis-split would hand the model half a question.
    parsed = None
    slices = _slice_by_question(page["text"], wanted_numbers) if len(wanted_numbers) > 1 else {}
    if slices and len(slices) == len(wanted_numbers):
        parsed = _structure_in_parallel(
            client, system_prompt, slices, wanted_numbers, doubt_id, usage_acc)

    if parsed is None:
        parsed = _call_with_one_retry("transcribe", _make_call(), f"doubt={doubt_id[:8]}",
                                      usage_acc, service="snap_transcribe")

    # Verify the model returned the questions it was told to. Costs nothing when
    # it complied, and when it did not, the student otherwise silently gets the
    # wrong three — which also breaks "reframe to the next three", since they
    # cannot tell which ones were used.
    if wanted_numbers:
        got = _returned_numbers(parsed.get("questions"))
        if got and got != wanted_numbers:
            logger.warning(
                "[SNAP STRUCTURE] doubt=%s asked for %s but got %s — correcting once",
                doubt_id[:8], wanted_numbers, got,
            )
            missing = [n for n in wanted_numbers if n not in got]
            retry_extra = (
                f"\n\nYou returned {got}. That is wrong: you were asked for "
                f"{wanted_numbers} and you skipped {missing}. Return "
                f"{wanted_numbers} this time, in that order. If one of them "
                f"cannot be fully read, return it anyway with `legible: false` "
                f"and explain in its `note` — skipping it is not an option."
            )
            try:
                retried = _call_with_one_retry(
                    "transcribe", _make_call(retry_extra),
                    f"doubt={doubt_id[:8]} selection", usage_acc,
                    service="snap_transcribe",
                )
                retried_numbers = _returned_numbers(retried.get("questions"))
                if retried_numbers == wanted_numbers:
                    parsed = retried
                    logger.info("[SNAP STRUCTURE] doubt=%s correction worked -> %s",
                                doubt_id[:8], retried_numbers)
                else:
                    # Keep the first result rather than lose the submission; the
                    # student still gets three real answers, just not the three
                    # they framed. Loud, because it means the model is ignoring
                    # an explicit, numbered instruction twice over.
                    logger.error(
                        "[SNAP STRUCTURE] doubt=%s correction FAILED too (got %s, "
                        "wanted %s) — serving the original read",
                        doubt_id[:8], retried_numbers, wanted_numbers,
                    )
            except SnapError as err:
                logger.error("[SNAP STRUCTURE] doubt=%s correction call failed: %s",
                             doubt_id[:8], err)

    structure_ms = int((time.time() - structure_t0) * 1000)
    ocr_ms = page.get("ocr_ms") or 0
    logger.info(
        "[SNAP STRUCTURE] doubt=%s structure_ms=%d model=%s ocr_chars=%d "
        "asked_for=%d (ocr_ms=%d, so transcribe = %d + %d = %dms)",
        doubt_id[:8], structure_ms, MODEL_TRANSCRIBE, len(page["text"]),
        max_questions, ocr_ms, ocr_ms, structure_ms, ocr_ms + structure_ms,
    )
    parsed["_ocr_confidence"] = page["confidence"]
    parsed["_ocr_text"] = page["text"]
    parsed["_diagram_regions"] = page.get("diagram_regions", 0)
    # Carried out of transcription so the pipeline can crop the figures it
    # already located, without asking the OCR twice.
    parsed["_diagram_spans"] = page.get("diagram_spans") or []
    parsed["_ocr_ms"] = ocr_ms
    parsed["_structure_ms"] = structure_ms

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

    # Deliberately NOT warning the student here about a possibly-partial read.
    # There is no signal that separates "the photo held one question" from "six
    # were there and Mathpix found one": page_confidence looked like one until
    # it was measured (see above), and a student who cropped to a single
    # question on a watermarked paper would have been told to crop tighter. The
    # fix for a half-read page is to stop feeding it browser furniture in the
    # first place — see crop_to_content at the top of the pipeline.

    # Which questions actually have a figure, from the OCR's own geometry.
    # Empty means the page gave no usable coordinates, and the text model's
    # `requires_diagram` stays in charge.
    figure_counts = figures_by_question(page, _returned_numbers(raw_questions))
    figure_spans = figure_spans_by_question(page, _returned_numbers(raw_questions))
    # The page's own figure count, as a floor for the drawn-options gate when
    # per-question attribution comes up empty. Counted from the SPANS when
    # there are any: those are the same geometry attribution reads, so if the
    # two ever disagree the spans are the ones that matter here.
    page_diagram_regions = (len(page.get("diagram_spans") or [])
                            or (page.get("diagram_regions") or 0))
    if figure_counts:
        logger.info("[SNAP TRANSCRIBE] doubt=%s figures located by question: %s",
                    doubt_id[:8], figure_counts)

    questions: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw_questions, 1):
        if not isinstance(item, dict):
            continue
        # `stem` is the source of truth now. The structurer used to ALSO return
        # `text` (stem and options concatenated), which is the same content a
        # second time — measured at 47% of everything it emitted on a real
        # 3-question page, and output tokens are what the ~10s structuring call
        # spends its time generating. `text` is rebuilt from stem + options
        # below instead, which is exactly what the model was writing out by
        # hand. Older responses that still send `text` are honoured as a
        # fallback, so a stale prompt cannot break the read.
        stem_text, stripped_key = _strip_printed_answer(
            (item.get("stem") or item.get("text") or "").strip()
        )
        legible = bool(item.get("legible", True))
        # Deliberately NOT named `note`: that is the response-level note above,
        # and shadowing it here silently replaced "a 3rd question was cut off"
        # with the last question's own note.
        q_note = (item.get("note") or "").strip() or None
        q_remedy, q_reason = REMEDY_RETAKE, "illegible"

        # A question with nothing in it is not legible, whatever the flag says.
        if not stem_text:
            legible = False

        options = _clean_options(item.get("options"))

        # The display/search form: the stem with its options underneath, which
        # is what `text` always held. Built here so it is derived from the same
        # strings the solver and the fidelity gate use, rather than a separate
        # transcription of them that could disagree.
        if options:
            text = stem_text + "\n" + "\n".join(
                f"({o['label']}) {o['text']}" for o in options
            )
        else:
            text = stem_text

        q_type = (item.get("question_type") or "").strip().lower()
        if q_type not in QUESTION_TYPES:
            # Legacy/loose responses: infer from what actually came back.
            q_type = "single_correct" if len(options) >= 2 else "subjective"
        is_choice = q_type in CHOICE_TYPES

        # How many figures the OCR located inside THIS question's span. None
        # means the page gave no usable geometry, which is "no opinion" — never
        # "no figures". Read before the option gate below, which needs it to
        # tell a question whose options are pictures from one whose options
        # were simply cut off.
        printed_number = _returned_numbers([item])
        located = (figure_counts.get(printed_number[0])
                   if (figure_counts and printed_number) else None)

        # A NUMERICAL question has no options, by design — JEE prints a blank:
        # "the value of alpha is ____". The structurer read one correctly, as
        # `numerical` with `options: []`, and then set `legible: false` because
        # the options were "missing", with a note that literally began "The
        # question is legible, but...". A whole page of three came back solved
        # 0/3 that way, and the student was told to retake a photo that had
        # been read perfectly.
        #
        # Not a prompt fix alone: the pipeline already knows the option count
        # is only evidence for a CHOICE question, so it decides that here
        # rather than trusting the flag. Genuine illegibility still stands —
        # an empty stem is caught above, and a truncated one keeps its flag,
        # because this only overrides when there is a substantial stem to
        # solve from.
        # Same guard as the figure override below: only when the MODEL set the
        # flag, never when one of this function's own gates did. It is
        # unreachable for a non-choice question today — every option gate is
        # choice-only — but stating it keeps the two overrides honest if a
        # future gate stops being choice-only.
        if (not legible and not is_choice and not options
                and q_reason == "illegible"
                and len(stem_text) >= 40):
            logger.info(
                "[SNAP TRANSCRIBE] doubt=%s q%d marked illegible for having no "
                "options, but it is %s — options are not expected. Solving it. "
                "(model note: %r)",
                doubt_id[:8], idx, q_type, (q_note or "")[:100],
            )
            legible = True
            q_note = None

        # A multiple-choice question without its choices is not answerable, and
        # the prompt saying so is not enough — a bare stem reached the solver
        # once and it invented an answer that was not among the options. This is
        # the gate that makes that impossible.
        #
        # ...unless the options are PICTURES. A JEE page routinely asks "which
        # of these curves" and prints four graphs labelled (1)-(4). There is no
        # text for the OCR to read, so this gate fired and told the student to
        # "retake the photo with all the choices in frame" — advice that cannot
        # work, because no photograph of a graph turns it into text. When the
        # OCR's geometry shows several figures inside this question's span,
        # that is what has happened: mark it for the option-reading pass rather
        # than refusing, and let THAT decide whether they can be told apart.
        options_are_drawn = False
        if is_choice and len(options) < 2:
            # Prefer the per-question attribution, but do not REQUIRE it.
            #
            # Attribution needs the OCR's question numbers to slice the page,
            # and when that slicing comes up empty every question reports zero
            # figures — so a page with four circuits on it refused a circuit
            # question for having "unreadable options", with the four figures
            # sitting right there unlooked-at. Measured on the same photo
            # twice: once attributed (4 in span, read fine), once not (refused).
            #
            # A choice question with no readable options, on a page that has
            # figures at all, is the shape this pass exists for. Send it. The
            # pass itself refuses honestly when the figures cannot be told
            # apart, which is the right place for that judgement — here we only
            # decide whether it is worth looking.
            drawn_here = located if located else page_diagram_regions
            if drawn_here >= 2:
                options_are_drawn = True
                logger.info(
                    "[SNAP TRANSCRIBE] doubt=%s q%d %s with no readable options "
                    "but %d figures %s — the options are drawn, not written. "
                    "Will read them from the image.",
                    doubt_id[:8], idx, q_type, drawn_here,
                    "inside its span" if located else "on the page",
                )
            else:
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

        # A SHORT option list is a cut-off option list. JEE and NEET print four
        # choices — every single-correct, multi-correct, assertion-reason and
        # match-the-column question on both papers — so two or three means the
        # rest were out of frame, whatever `options_complete` claims. Caught
        # only by that flag before, which the model sets optimistically: a
        # 4-option question cropped to 2 came back "complete", and the solver
        # would then pick the best of a list that may not contain the answer.
        #
        # The cost of being wrong here is a retake prompt on a genuinely
        # 2-option question, which these exams do not print. The cost of not
        # having it is a confident answer chosen from half a list.
        if (is_choice and not options_are_drawn
                and 2 <= len(options) < EXPECTED_CHOICE_OPTIONS):
            legible = False
            q_note = q_note or (
                f"Only {len(options)} of the answer choices are in frame — these "
                f"papers print {EXPECTED_CHOICE_OPTIONS}. Retake the photo with "
                f"the whole list of options visible."
            )
            q_remedy, q_reason = REMEDY_RETAKE, "options_cut_off"
            logger.warning(
                "[SNAP TRANSCRIBE] doubt=%s q%d %s read only %d of %d options — "
                "the list is cut off, refusing rather than solving from part of it",
                doubt_id[:8], idx, q_type, len(options), EXPECTED_CHOICE_OPTIONS,
            )

        # Fidelity gate: every option must exist, verbatim, in what the OCR
        # read. The structuring model is INSTRUCTED to copy; this enforces it.
        # An option it invented or mutated is not on the page, and a solver
        # picking from a corrupted list produces a confident wrong answer no
        # later gate can catch.
        if is_choice and options and not options_are_drawn and parsed.get("_ocr_text"):
            missing = _options_found_in_ocr(options, parsed["_ocr_text"])
            if missing:
                legible = False
                q_note = q_note or (
                    "Monk could not match all the answer choices it read to the "
                    "photo, so it is not solving from a possibly-garbled list. "
                    "Retake the photo with the options sharp and fully in frame."
                )
                q_remedy, q_reason = REMEDY_RETAKE, "options_fidelity"
                logger.error(
                    "[SNAP TRANSCRIBE] doubt=%s q%d option(s) %s not found in the "
                    "OCR text — structured output does not match the page",
                    doubt_id[:8], idx, missing,
                )

        # A truncated option list is the same defect one step later: the solver
        # picks from a list that is missing the right answer. Measured on a real
        # page whose fourth option was out of frame and got invented.
        # `not options_are_drawn` for the same reason the gate above carries
        # it: a question whose options are FIGURES has no text option list to
        # be complete, so "incomplete" is the expected reading and refusing on
        # it sends the student to retake a photo that was never the problem.
        if is_choice and not options_are_drawn and item.get("options_complete") is False:
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
        # Geometry beats prose. When the OCR located the figures, its verdict
        # for THIS question replaces the text model's guess in both directions:
        # a figure it inferred from wording that is not actually on the page is
        # dropped, and one it missed is added. Only ever an override when the
        # two disagree, and only when there was geometry to judge from.
        if located is not None and bool(located) != needs_diagram:
            logger.info(
                "[SNAP TRANSCRIBE] doubt=%s q%d requires_diagram %s -> %s "
                "(the OCR found %s inside this question's span; the text model "
                "only had the wording to go on)",
                doubt_id[:8], idx, needs_diagram, bool(located),
                f"{located} figure(s)" if located else "no figure",
            )
            needs_diagram = bool(located)

        if needs_diagram:
            logger.info(
                "[SNAP TRANSCRIBE] doubt=%s q%d needs a diagram — will describe it",
                doubt_id[:8], idx,
            )

        # ...but only if it survives to the describing pass, which runs on
        # legible questions. A P-V graph question came back `requires_diagram:
        # true` AND `legible: false`, its note citing "the reference to the
        # figure" — so it was refused for the exact reason that pass exists to
        # handle, and the figure was never even looked at. The describing pass
        # is the thing that decides whether a figure can be worked from; it
        # refuses honestly ("could not work reliably from the figure") when it
        # cannot. Deciding that here, from the text alone, pre-empts it.
        # `q_reason == "illegible"` is the load-bearing condition: that is the
        # untouched default, meaning the MODEL set legible:false on its own
        # judgement. Every gate in this function stamps its own reason
        # (options_unreadable, options_fidelity, options_cut_off), and those
        # are refusals this override must never reach. Without that check it
        # swallowed the fidelity gate — options that do not appear on the page
        # are a possibly-garbled list, and solving from one produces a
        # confident wrong answer no later gate can catch.
        if (needs_diagram and not legible and stem_text
                and q_reason == "illegible"
                and not options_missing_for_choice(is_choice, options, item)):
            logger.info(
                "[SNAP TRANSCRIBE] doubt=%s q%d marked illegible for needing its "
                "figure — that is what the describing pass is for. Letting it "
                "through. (model note: %r)",
                doubt_id[:8], idx, (q_note or "")[:100],
            )
            legible = True
            q_note = None

        questions.append({
            "n": idx,
            "text": text,
            "subject": canonical_subject(item.get("subject")) or "unknown",
            "topic": item.get("topic") or None,
            # The printed-answer strip applies here too: `stem` is what the
            # solver reasons from, so a key left in it is the exact leak
            # _strip_printed_answer exists to prevent.
            "stem": stem_text,
            # Options are withheld from the solver unless they ARE the question.
            "self_contained": item.get("self_contained") is not False,
            "question_type": q_type,
            "is_multiple_choice": is_choice,
            "options": options,
            "options_complete": item.get("options_complete") is not False,
            # The options are printed as figures, so they still have to be read
            # off the image — see describe_option_figures in the pipeline.
            "options_are_drawn": options_are_drawn,
            # The figures this question owns, so the pipeline can keep them
            # without re-deriving the geometry.
            "figure_spans": (figure_spans.get(printed_number[0]) or []
                             if (figure_spans and printed_number) else []),
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
    # One line per question, so a production log says exactly what was read and
    # what will happen to it — which questions go to the solver, which are held
    # back and why, and whether the options are being withheld from the solver.
    for q in questions:
        logger.info(
            "[SNAP QUESTION] doubt=%s q%d subject=%s topic=%s type=%s "
            "options=%d complete=%s self_contained=%s diagram=%s legible=%s%s "
            "printed_key=%s stem=%r",
            doubt_id[:8], q["n"], q.get("subject"), q.get("topic"),
            q.get("question_type"), len(q.get("options") or []),
            q.get("options_complete"), q.get("self_contained"),
            q.get("requires_diagram"), q["legible"],
            f" reason={q.get('reason')} remedy={q.get('remedy')}" if not q["legible"] else "",
            q.get("printed_answer"), (q.get("stem") or "")[:100],
        )
    _warn_if_not_page_order(questions, parsed.get("_ocr_text") or "", doubt_id)
    return {"questions": questions, "note": note,
            "ocr_confidence": parsed.get("_ocr_confidence"),
            "diagram_spans": parsed.get("_diagram_spans") or [],
            "ocr_ms": parsed.get("_ocr_ms") or 0,
            "structure_ms": parsed.get("_structure_ms") or 0}


# A printed question number at the start of a line: "Q62.", "Q 62)", "62.".
# Anchored to a line start so an option label "(1)" or a mid-sentence number
# cannot masquerade as one.
_QUESTION_NUMBER_RE = re.compile(r"(?m)^[\s*_#>]*Q\s*\.?\s*(\d{1,3})\s*[.):]")


def _question_numbers_in(ocr_text: str) -> List[int]:
    """The question numbers the page prints, in the order they appear.

    Requires the "Q" prefix: without it, "(1) 1.660 g" and stray figures in the
    maths would be read as question numbers, which is worse than having none —
    a wrong number list would send the selection instruction after questions
    that do not exist. Returns [] for an unnumbered page, and the caller falls
    back to asking for "the first N".
    """
    seen: List[int] = []
    for match in _QUESTION_NUMBER_RE.finditer(ocr_text or ""):
        n = int(match.group(1))
        if n not in seen:
            seen.append(n)
    return seen


def figures_by_question(page: Dict[str, Any], wanted: List[int]) -> Dict[int, int]:
    """How many figures sit inside each question's vertical span on the page.

    Mathpix reports every line's bounding box, so a figure belongs to the
    question whose printed number is the last one ABOVE it. That is geometry
    from the OCR engine, and it replaces a text-only model inferring a figure
    from wording — which failed both ways: it missed one whose stem said "two
    arrangements of wires" without "as shown", and on another it flagged the
    figure and simultaneously marked the question illegible, so the describing
    pass was skipped and the picture never looked at.

    Returns {} when the OCR gave no geometry, or when the question numbers
    cannot be located in it. {} means "no opinion" and leaves the text model's
    judgement in charge — NOT "there are no figures", which would reintroduce
    the failure this exists to prevent.
    """
    spans = page.get("diagram_spans") or []
    lines = page.get("text_lines") or []
    if not spans or not lines or not wanted:
        return {}

    # Where each wanted question starts, vertically: the topmost line whose
    # text begins with its printed number.
    starts: Dict[int, float] = {}
    for line in lines:
        match = _QUESTION_NUMBER_RE.match((line.get("text") or "").lstrip())
        if not match:
            continue
        num = int(match.group(1))
        if num in wanted and num not in starts:
            starts[num] = line["top"]
    if len(starts) != len(wanted):
        return {}

    ordered = sorted(starts.items(), key=lambda kv: kv[1])
    counts = {num: 0 for num in wanted}
    for span in spans:
        centre = (span["top"] + span["bottom"]) / 2.0
        owner = None
        for num, top in ordered:
            # The last question that starts above this figure owns it.
            if top <= centre:
                owner = num
            else:
                break
        if owner is not None:
            counts[owner] += 1
    return counts


def figure_spans_by_question(page: Dict[str, Any],
                             wanted: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    """The same attribution, keeping the figures themselves rather than a count.

    Counting was enough while the only question was "are the options drawn?".
    Keeping the picture needs the box it sits in.
    """
    spans = page.get("diagram_spans") or []
    if not spans or not figures_by_question(page, wanted):
        return {}
    lines = page.get("text_lines") or []
    starts: Dict[int, float] = {}
    for line in lines:
        match = _QUESTION_NUMBER_RE.match((line.get("text") or "").lstrip())
        if not match:
            continue
        num = int(match.group(1))
        if num in wanted and num not in starts:
            starts[num] = line["top"]
    ordered = sorted(starts.items(), key=lambda kv: kv[1])
    owned: Dict[int, List[Dict[str, Any]]] = {num: [] for num in wanted}
    for span in spans:
        centre = (span["top"] + span["bottom"]) / 2.0
        owner = None
        for num, top in ordered:
            if top <= centre:
                owner = num
            else:
                break
        if owner is not None:
            owned[owner].append(span)
    return owned


# A shared passage above a set of questions. Long enough to be prose rather
# than a running header ("JEE Main 2026 (24 January Shift 2)"), and capped so a
# whole previous page cannot ride along.
_PREAMBLE_MIN_CHARS = 120
_PREAMBLE_MAX_CHARS = 1500


def _slice_by_question(ocr_text: str, wanted: List[int]) -> Dict[int, str]:
    """The slice of OCR text belonging to each wanted question number.

    Each slice runs from that question's printed number to the start of the
    next one, so it carries the stem and its options. Returns {} if any wanted
    number is missing or a slice comes out too short to be a question — the
    caller then structures the whole page in one call rather than risk handing
    the model half a question.

    A COMPREHENSION passage is prepended to every slice. JEE prints one block
    of context — "A particle of mass m moves in a circular path…" — above a run
    of questions that are meaningless without it, and it sits ABOVE the first
    question number, so slicing from that number dropped it entirely and each
    question arrived as "The time period of revolution is proportional to:"
    with nothing to reason about. Only prose long enough not to be a running
    header is carried, and only up to a cap, so a page banner costs nothing and
    a previous page cannot ride along.
    """
    if not ocr_text or not wanted:
        return {}
    marks = [(int(m.group(1)), m.start()) for m in _QUESTION_NUMBER_RE.finditer(ocr_text)]
    if not marks:
        return {}
    starts = {}
    for num, pos in marks:
        starts.setdefault(num, pos)
    ordered = sorted(starts.values())

    preamble = ocr_text[:ordered[0]].strip()
    if len(preamble) < _PREAMBLE_MIN_CHARS:
        preamble = ""
    elif len(preamble) > _PREAMBLE_MAX_CHARS:
        # Keep the END of it: a passage sits directly above its questions, so
        # the nearest text is the relevant text.
        preamble = preamble[-_PREAMBLE_MAX_CHARS:]

    out: Dict[int, str] = {}
    for num in wanted:
        if num not in starts:
            return {}
        begin = starts[num]
        after = [p for p in ordered if p > begin]
        chunk = ocr_text[begin:after[0]] if after else ocr_text[begin:]
        if preamble:
            chunk = (f"[SHARED CONTEXT printed above this question — it may be a "
                     f"comprehension passage this question depends on, or it may "
                     f"just be a page header. Use it only if this question needs "
                     f"it.]\n{preamble}\n\n[THE QUESTION]\n{chunk}")
        if len(chunk.strip()) < 25:
            return {}
        out[num] = chunk.strip()
    return out


def _structure_in_parallel(client, system_prompt: str, slices: Dict[int, str],
                           wanted: List[int], doubt_id: str,
                           usage_acc: Optional[Dict[str, int]]) -> Optional[Dict[str, Any]]:
    """Structures each question's own slice concurrently; merges in page order.

    Returns None if any one of them fails, so the caller falls back to the
    single whole-page call rather than serving the student a partial page.
    """
    results: Dict[int, Any] = {}
    usages = {n: {"input": 0, "output": 0} for n in wanted}
    t0 = time.time()

    def one(num: int) -> None:
        def call(corrective: Optional[str] = None):
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": (
                    f"Return EXACTLY ONE question: Q{num}, with `number` set to "
                    f"{num}. The text below is that question and, if it is a "
                    f"choice question, its options — a numerical or subjective "
                    f"question has none, and that is its shape, not a failure "
                    f"to read it. Use `legible: false` ONLY when the words "
                    f"themselves are truncated or unreadable; return it either "
                    f"way, never an empty list.\n\nOCR TEXT:\n{slices[num]}"
                )},
            ]
            if corrective:
                messages.append({"role": "user", "content": corrective})
            return client.chat.completions.create(
                model=MODEL_TRANSCRIBE,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=2048,
                timeout=TRANSCRIBE_TIMEOUT_S,
            )
        try:
            got = _call_with_one_retry("transcribe", call,
                                       f"doubt={doubt_id[:8]} q{num}", usages[num],
                                       service="snap_transcribe")
            qs = got.get("questions")
            if isinstance(qs, list) and qs:
                item = qs[0]
                if isinstance(item, dict):
                    item.setdefault("number", num)
                    results[num] = item
        except SnapError as err:
            logger.warning("[SNAP STRUCTURE] doubt=%s q%d slice failed: %s",
                           doubt_id[:8], num, err)

    with ThreadPoolExecutor(max_workers=len(wanted)) as pool:
        list(pool.map(one, wanted))

    if usage_acc is not None:
        for u in usages.values():
            usage_acc["input"] = usage_acc.get("input", 0) + u["input"]
            usage_acc["output"] = usage_acc.get("output", 0) + u["output"]

    if len(results) != len(wanted):
        logger.warning(
            "[SNAP STRUCTURE] doubt=%s parallel structuring got %d/%d — falling "
            "back to one whole-page call",
            doubt_id[:8], len(results), len(wanted),
        )
        return None

    logger.info(
        "[SNAP STRUCTURE] doubt=%s structured %d questions in parallel in %dms "
        "(one call each, instead of one call for the page)",
        doubt_id[:8], len(wanted), int((time.time() - t0) * 1000),
    )
    return {"questions": [results[n] for n in wanted]}


def _returned_numbers(raw_questions: Any) -> List[int]:
    """The question numbers the structurer actually returned, in its own order.

    Prefers the explicit `number` field. Reading it off the stem instead was a
    silent hole: the structurer strips the printed "Q51." label from the stem —
    correctly, it is not part of the question — so this returned [] on every
    real response, and the caller's `if got and got != wanted` check could
    never fire. The selection worked in production because the INSTRUCTION
    names the questions, not because anything verified it.

    Still falls back to the stem for a response that predates the field.
    [] when the page carries no numbers at all, which the caller reads as
    "nothing to compare" and lets the read stand.
    """
    if not isinstance(raw_questions, list):
        return []
    numbers: List[int] = []
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        raw = item.get("number")
        if isinstance(raw, bool):
            raw = None
        if isinstance(raw, (int, float)):
            numbers.append(int(raw))
            continue
        if isinstance(raw, str) and raw.strip().lstrip("Qq.").strip().isdigit():
            numbers.append(int(raw.strip().lstrip("Qq.").strip()))
            continue
        head = ((item.get("stem") or item.get("text") or "") or "").lstrip()
        match = _QUESTION_NUMBER_RE.match(head) or _QUESTION_NUMBER_RE.search(head[:40])
        if match:
            numbers.append(int(match.group(1)))
    return numbers


def _warn_if_not_page_order(questions: List[Dict[str, Any]], ocr_text: str,
                            doubt_id: str) -> None:
    """Logs when the structurer did not return the questions the page starts with.

    The prompt asks for the first N top-to-bottom, and a prompt is not a
    constraint: on a real JEE page holding Q11-Q19 it returned Q16-Q18. The
    student had framed the top of the page and got its middle back, which also
    breaks "reframe to the next three" — they cannot tell which three they
    already used.

    Nothing here can repair it (the skipped questions were never returned, so
    there is nothing to reorder), but a silent recurrence is worse than a noisy
    one. Warning only — never raises, never changes what the student sees.
    """
    if not ocr_text or not questions:
        return
    page = _canon_fidelity(ocr_text)
    if not page:
        return

    positions = []
    for q in questions:
        needle = _canon_fidelity(q.get("stem") or q.get("text") or "")[:40]
        positions.append(page.find(needle) if needle else -1)

    located = [p for p in positions if p >= 0]
    if len(located) < 2:
        return

    if located != sorted(located):
        logger.warning(
            "[SNAP TRANSCRIBE] doubt=%s questions came back OUT of page order "
            "(positions %s) — the student's 'next three' will overlap or skip",
            doubt_id[:8], positions,
        )

    # How much of the page sits above the first question we returned. A large
    # fraction means whole questions were skipped over, not merely a header.
    skipped_fraction = located[0] / len(page)
    if skipped_fraction > 0.25:
        logger.warning(
            "[SNAP TRANSCRIBE] doubt=%s SKIPPED AHEAD: the first returned "
            "question starts %.0f%% into the page — questions above it were "
            "read and dropped",
            doubt_id[:8], skipped_fraction * 100,
        )


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
                                      usage_acc, expect_model=MODEL_DIAGRAM,
                                      service="snap_diagram")
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


def describe_option_figures(image_bytes: bytes, mime_type: str,
                            question_text: str, doubt_id: str = "-",
                            usage_acc: Optional[Dict[str, int]] = None
                            ) -> List[Dict[str, str]]:
    """Reads options that are DRAWN rather than written, into [{label, text}].

    A JEE page routinely asks "which of these curves…" and prints four graphs
    labelled (1)-(4). There is no text for the OCR to read, so the structurer
    returns a choice question with zero options and the gate refuses it as
    "the options could not be read. Retake the photo with all the choices in
    frame" — advice that cannot work, because no photograph of a graph turns it
    into text.

    Same contract as describe_diagram: the describing model may not solve, and
    the solver never sees the image. Returns [] when the options could not be
    told apart or matched to their labels, which the caller treats as an honest
    refusal rather than guessing a pairing — a mislabelled option silently
    renames the answer.
    """
    client = _openai_client()
    data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"

    def call(corrective: Optional[str] = None):
        messages = [
            {"role": "system", "content": load_prompt("snap_options.md")},
            {"role": "user", "content": [
                {"type": "text",
                 "text": f"The question whose options are drawn:\n{question_text}"},
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
            max_tokens=1400,
            timeout=TRANSCRIBE_TIMEOUT_S,
        )

    try:
        parsed = _call_with_one_retry("transcribe", call, f"options={doubt_id[:8]}",
                                      usage_acc, expect_model=MODEL_DIAGRAM,
                                      service="snap_options")
    except SnapError as err:
        logger.warning("[SNAP OPTIONS] doubt=%s read failed: %s", doubt_id[:8], err)
        return []

    if parsed.get("sufficient") is False:
        logger.warning("[SNAP OPTIONS] doubt=%s options not clear enough: %s",
                       doubt_id[:8], (parsed.get("note") or "")[:160])
        return []

    options = _clean_options(parsed.get("options"))
    if len(options) < 2:
        logger.warning("[SNAP OPTIONS] doubt=%s only %d option(s) described",
                       doubt_id[:8], len(options))
        return []

    # Descriptions that are near-identical mean the model could not tell the
    # figures apart, and the difference between them IS the question. Solving
    # against a list whose entries all say the same thing picks at random.
    canon = {_canon_fidelity(o["text"]) for o in options}
    if len(canon) < len(options):
        logger.warning(
            "[SNAP OPTIONS] doubt=%s described options are not distinct "
            "(%d unique of %d) — refusing rather than guessing between them",
            doubt_id[:8], len(canon), len(options),
        )
        return []

    logger.info("[SNAP OPTIONS] doubt=%s read %d drawn option(s): %s",
                doubt_id[:8], len(options),
                ", ".join(f"({o['label']}) {o['text'][:40]}" for o in options))
    return options


# A question that asks the student to PICK, rather than to compute. "Which of
# the following", "identify the ... that cannot", "choose the correct".
#
# Solving blind is right for a question with an answer of its own: derive it,
# then match, and nothing can talk itself into an option. It is wrong for a
# question whose options ARE the question. Asked "identify the physical
# quantity that cannot be measured using a spherometer" with the choices
# withheld, v4 answered "Mass" — true, unmatchable, and no use to a student
# picking between four printed options. The answer to a selection question is
# not a quantity, it is one of the four things on the page.
#
# Deliberately narrow. A computational MCQ ("the value of 15C13 is") keeps its
# blind solve, because there the derivation stands on its own and showing the
# options only invites the model to reason backwards from them.
_SELECTION_STEM = re.compile(
    r"\bwhich (?:one )?of the (?:following|these)\b"
    r"|\bidentify the\b"
    r"|\bchoose the\b"
    r"|\bselect the\b"
    r"|\bwhich (?:graph|curve|circuit|figure|diagram|option|statement)\b",
    re.I,
)


def _options_are_the_question(stem: Optional[str]) -> bool:
    return bool(stem) and bool(_SELECTION_STEM.search(stem))


# ─── Keeping the figures a question was printed with ─────────────────────────
#
# The photo is discarded after OCR — the transcript is the record. That is
# right for the page, and wrong for a question whose OPTIONS are pictures:
# "which of these circuits is reverse-biased" reduced to four sentences of
# description is a question the student can no longer read. Those figures are
# the only part of the page worth keeping, so they are the part we keep.
#
# Cropped from the geometry the OCR already reported, one object per option,
# and paired to a label only when the pairing is certain (see `pair_figures`).

FIGURE_PAD_PX = 10
FIGURE_MAX_EDGE = 1400
FIGURE_JPEG_QUALITY = 82


def _reading_order(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sorts figures the way a page is read: rows down, then across each row.

    Two figures belong to the same ROW when their vertical spans overlap — a
    2x2 option grid gives spans like 498-589 and 508-745, side by side, which
    a plain sort by `top` would interleave with the row beneath.
    """
    rows: List[List[Dict[str, Any]]] = []
    for span in sorted(spans, key=lambda s: (s.get("top") or 0)):
        placed = False
        for row in rows:
            if any(span.get("top", 0) <= s.get("bottom", 0)
                   and s.get("top", 0) <= span.get("bottom", 0) for s in row):
                row.append(span)
                placed = True
                break
        if not placed:
            rows.append([span])
    ordered: List[Dict[str, Any]] = []
    for row in rows:
        ordered.extend(sorted(row, key=lambda s: (s.get("left") if s.get("left") is not None else 0)))
    return ordered


def pair_figures(options: List[Dict[str, str]],
                 spans: List[Dict[str, Any]],
                 doubt_id: str = "-") -> Optional[List[Dict[str, Any]]]:
    """One figure per option, in reading order — or None when that is a guess.

    The pairing is positional, which is exactly as reliable as the page's own
    layout when there is one figure per option, and not reliable at all when
    the counts disagree. This module already refuses to guess a label-to-option
    pairing for text, on the grounds that a mislabelled option silently renames
    the answer; a mislabelled PICTURE does the same thing more convincingly.
    So: pair when the counts match, and otherwise return nothing.
    """
    usable = [s for s in spans
              if s.get("left") is not None and s.get("right") is not None]
    if not options or len(usable) != len(options):
        logger.info(
            "[SNAP FIGURES] doubt=%s not pairing: %d option(s) against %d "
            "usable figure(s) — a positional guess would rename an answer",
            doubt_id[:8], len(options), len(usable),
        )
        return None
    return _reading_order(usable)


def crop_figure(image_bytes: bytes, span: Dict[str, Any]) -> Optional[bytes]:
    """One figure, cut from the page with a little air around it."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow ships with image_prep
        return None
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img = img.convert("RGB")
            width, height = img.size
            left = max(0, int(span["left"]) - FIGURE_PAD_PX)
            top = max(0, int(span["top"]) - FIGURE_PAD_PX)
            right = min(width, int(span["right"]) + FIGURE_PAD_PX)
            bottom = min(height, int(span["bottom"]) + FIGURE_PAD_PX)
            if right - left < 8 or bottom - top < 8:
                return None
            piece = img.crop((left, top, right, bottom))
            piece.thumbnail((FIGURE_MAX_EDGE, FIGURE_MAX_EDGE), Image.LANCZOS)
            out = io.BytesIO()
            piece.save(out, format="JPEG", quality=FIGURE_JPEG_QUALITY)
            return out.getvalue()
    except Exception as err:
        logger.warning("[SNAP FIGURES] crop failed: %s", err)
        return None


def keep_question_figures(spans: List[Dict[str, Any]],
                          image_bytes: bytes,
                          doubt_id: str,
                          question_index: int) -> List[str]:
    """Stores the figures a QUESTION was printed with, in reading order.

    Not its options — those ride on the options themselves. This is the beaker
    in "the apparent depth of the coin is", the two wires in "the field at a
    point P midway between them". The solver works from a written description
    of them; the student should see the thing itself.

    Best effort, like the option figures: no bucket or a failed crop costs the
    picture, not the answer.
    """
    usable = [s for s in spans
              if s.get("left") is not None and s.get("right") is not None]
    if not usable or not storage_r2.is_configured():
        return []

    keys: List[str] = []
    for position, span in enumerate(_reading_order(usable)):
        piece = crop_figure(image_bytes, span)
        if not piece:
            continue
        key = f"doubts/{doubt_id}/q{question_index}/fig-{position}.jpg"
        try:
            storage_r2.upload_image(key, piece, "image/jpeg")
        except Exception as err:
            logger.warning("[SNAP FIGURES] doubt=%s upload failed for %s: %s",
                           doubt_id[:8], key, err)
            continue
        keys.append(key)

    logger.info("[SNAP FIGURES] doubt=%s q%d kept %d question figure(s)",
                doubt_id[:8], question_index, len(keys))
    return keys


def keep_option_figures(options: List[Dict[str, str]],
                        spans: List[Dict[str, Any]],
                        image_bytes: bytes,
                        doubt_id: str,
                        question_index: int) -> List[Dict[str, str]]:
    """Stores one figure per option and hands back the options carrying keys.

    Best effort throughout: a question that cannot be cropped, or a bucket that
    is not configured, still returns its options with the descriptions that
    were already read. Losing the picture is a worse answer, not a broken one.
    """
    paired = pair_figures(options, spans, doubt_id)
    if not paired or not storage_r2.is_configured():
        return options

    kept = 0
    out: List[Dict[str, str]] = []
    for option, span in zip(options, paired):
        piece = crop_figure(image_bytes, span)
        if not piece:
            out.append(option)
            continue
        key = f"doubts/{doubt_id}/q{question_index}/opt-{option['label']}.jpg"
        try:
            storage_r2.upload_image(key, piece, "image/jpeg")
        except Exception as err:
            logger.warning("[SNAP FIGURES] doubt=%s upload failed for %s: %s",
                           doubt_id[:8], key, err)
            out.append(option)
            continue
        kept += 1
        out.append({**option, "figure_key": key})

    logger.info("[SNAP FIGURES] doubt=%s q%d kept %d of %d option figure(s)",
                doubt_id[:8], question_index, kept, len(options))
    return out


# A completed step object inside a *partial* JSON buffer. Streaming shows the
# student each step as the solver writes it; the answer is never streamed — it
# waits for the validated final card.
_STREAM_STEP_RE = re.compile(
    r'\{\s*"n"\s*:\s*(\d+)\s*,\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
)


def _emit_new_steps(buffer: str, emitted: set, on_event) -> None:
    """Fires on_event('step', ...) for every step object now complete in buffer."""
    for match in _STREAM_STEP_RE.finditer(buffer):
        n = int(match.group(1))
        if n in emitted:
            continue
        try:
            text = json.loads(f'"{match.group(2)}"')
        except json.JSONDecodeError:
            continue
        emitted.add(n)
        on_event("step", {"n": n, "text": _repair_latex(text)})


def _streamed_solve(make_kwargs, on_event, doubt_id: str,
                    usage_acc: Optional[Dict[str, int]]) -> Dict[str, Any]:
    """One solve, streamed: thinking ticks and steps go out live, the parsed
    JSON comes back for the same validation as the non-streamed path.

    Same one-retry contract as _call_with_one_retry; a retry resets the
    student's view first so attempt 2 does not append to attempt 1's steps.
    """
    client_kwargs = make_kwargs()
    client_kwargs["stream"] = True
    client_kwargs["stream_options"] = {"include_usage": True}
    solve_client = client_kwargs.pop("_client")
    model = client_kwargs.get("model") or MODEL_SOLVE

    last_err = None
    budget_s = client_kwargs.get("timeout") or SOLVE_TIMEOUT_S
    # True when attempt 1 produced no content at all — it thought until the
    # allowance ran out rather than answering. Repeating that verbatim wedges
    # verbatim, so attempt 2 changes the one variable that causes it.
    wedged = False
    for attempt in (1, 2):
        if attempt == 2:
            client_kwargs["messages"] = client_kwargs["messages"] + [
                {"role": "user", "content": _PARSE_CORRECTIVE}]
            if wedged:
                # Thinking is what spends the allowance, so the second attempt
                # goes without it. That is a genuinely different call — it
                # cannot fail the same way — and it is fast, which is what
                # makes a retry affordable at all when the student is already
                # waiting on the slowest question of the page.
                extra = dict(client_kwargs.get("extra_body") or {})
                extra["thinking"] = {"type": "disabled"}
                client_kwargs["extra_body"] = extra
                client_kwargs["max_tokens"] = 2200
                logger.warning(
                    "[SNAP SOLVE] doubt=%s attempt 1 answered nothing; "
                    "retrying once with thinking OFF rather than repeating a "
                    "call that spends its whole allowance reasoning.",
                    doubt_id[:8],
                )
            on_event("steps_reset", {})
        buffer, emitted = "", set()
        attempt_started = time.time()
        thinking_chars, last_tick = 0, time.time()
        started = time.time()
        # Per-attempt counts for llm_calls: a stream that dies mid-way still
        # billed whatever it generated, and must be recorded like any other.
        # The usage object arrives only on the terminal chunk, so a dead stream
        # usually has no counts at all — that is recorded as NULLs ("billed an
        # unknown amount"), never as zeros ("free").
        att_in = att_cached = att_out = 0
        saw_usage = False
        try:
            for chunk in solve_client.chat.completions.create(**client_kwargs):
                # The SDK's `timeout` bounds the GAP between chunks, not the
                # length of the stream, so a model that keeps emitting
                # reasoning runs past the budget unchallenged: the wedge that
                # prompted all this ran 111s against a 75s ceiling. This is the
                # wall clock the ceiling was always supposed to mean.
                if time.time() - attempt_started > budget_s:
                    logger.warning(
                        "[SNAP SOLVE] doubt=%s attempt %d hit the %.0fs budget "
                        "with %d chars of thinking and %d of answer — stopping "
                        "the stream rather than letting it run on.",
                        doubt_id[:8], attempt, budget_s, thinking_chars, len(buffer),
                    )
                    break
                usage = getattr(chunk, "usage", None)
                if usage:
                    saw_usage = True
                    att_in += int(usage.prompt_tokens or 0)
                    att_out += int(usage.completion_tokens or 0)
                    details = getattr(usage, "prompt_tokens_details", None)
                    if details:
                        att_cached += int(getattr(details, "cached_tokens", 0) or 0)
                    if usage_acc is not None:
                        usage_acc["input"] = usage_acc.get("input", 0) + int(usage.prompt_tokens or 0)
                        usage_acc["output"] = usage_acc.get("output", 0) + int(usage.completion_tokens or 0)
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    thinking_chars += len(reasoning)
                    if time.time() - last_tick >= 2.5:
                        last_tick = time.time()
                        on_event("thinking", {
                            "seconds": int(time.time() - started),
                        })
                if delta.content:
                    buffer += delta.content
                    _emit_new_steps(buffer, emitted, on_event)
        except Exception as err:
            record_call(model, "snap_solve", ok=False, attempt=attempt,
                        tokens={"input_tokens": att_in, "cache_hit_tokens": att_cached,
                                "output_tokens": att_out} if saw_usage else
                               {"input_tokens": None, "cache_hit_tokens": None,
                                "output_tokens": None},
                        latency_ms=int((time.time() - started) * 1000),
                        subtopic_key=f"doubt={doubt_id[:8]} stream", error=str(err))
            last_err = err
            logger.warning("[SNAP SOLVE] stream attempt %d/2 failed (%s): %s",
                           attempt, doubt_id[:8], str(err)[:160])
            continue
        tokens = {"input_tokens": att_in, "cache_hit_tokens": att_cached,
                  "output_tokens": att_out}
        latency_ms = int((time.time() - started) * 1000)
        try:
            parsed = _parse_json(buffer, "solve")
        except (json.JSONDecodeError, SnapError) as err:
            record_call(model, "snap_solve", ok=False, attempt=attempt,
                        tokens=tokens, latency_ms=latency_ms,
                        subtopic_key=f"doubt={doubt_id[:8]} stream",
                        error=f"unparseable JSON: {err}")
            last_err = err
            logger.warning(
                "[SNAP SOLVE] streamed JSON unparseable on attempt %d/2 (%s): %s",
                attempt, doubt_id[:8], err,
            )
            # An attempt that burned its budget did not fail fast — it wedged,
            # and the same call with the same inputs wedges for the same
            # duration again. Measured: a diagram question spent 2m13s
            # returning an empty response, and the retry made the student wait
            # for a second one. The student is waiting on the SLOWEST question,
            # so this is the difference between a slow answer and no answer at
            # roughly four minutes.
            spent = time.time() - attempt_started
            if attempt == 1 and spent > budget_s * RETRY_IF_UNDER_FRACTION:
                # It wedged rather than failed. Retrying the SAME call would
                # cost the student the same wait for the same nothing — but a
                # call with thinking off is a different call, and a fast one,
                # so it is worth the one attempt. Only a wedge that produced
                # some content is treated as a slow success and left alone.
                if not buffer.strip():
                    wedged = True
                    logger.error(
                        "[SNAP SOLVE] doubt=%s attempt 1 used %.0fs of a %.0fs "
                        "budget and produced nothing — it spent the allowance "
                        "thinking. Retrying without thinking.",
                        doubt_id[:8], spent, budget_s,
                    )
                    continue
                logger.error(
                    "[SNAP SOLVE] doubt=%s attempt 1 used %.0fs of a %.0fs "
                    "budget and came back unparseable. Not retrying; a second "
                    "attempt would cost the student the same wait again.",
                    doubt_id[:8], spent, budget_s,
                )
                break
        else:
            record_call(model, "snap_solve", ok=True, attempt=attempt,
                        tokens=tokens, latency_ms=latency_ms,
                        subtopic_key=f"doubt={doubt_id[:8]} stream")
            return parsed
    raise SnapError(
        "Something went wrong at Monk's end reading that back. Please try again.",
        "solve", REMEDY_OUR_SIDE, "model_unparseable",
    )


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
                                      usage_acc, service="snap_match")
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
# A step is one line of working, not a paragraph. The ceiling is what stops a
# step becoming scratch paper: an earlier, higher one let the model write a
# single 5,445-character step that broke its own JSON, and the rambling and the
# parse failures were the same problem. It is the enforcement — raise it, don't
# remove it.
#
# 320 was roughly three short sentences, which turned out to be the binding
# constraint on whether a step could say WHY a move is valid rather than only
# what the move is. 700 buys that room and is still an order of magnitude below
# the failure it guards against. Note this is not a truncation: a step over the
# ceiling is sent back to be rewritten (see `_step_problems`), so a student
# never sees a sentence cut off mid-word — they see a solution that was made to
# fit.
MAX_STEP_CHARS = 700
MAX_STEPS = 7

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
    # cannot pass. _canon_fidelity, not _norm: _norm strips '+'/'-' entirely,
    # which would let "3-e" and "3+e" collide as the same key — exactly the
    # sign-collapsing _canon_fidelity's own docstring warns about, and which a
    # first version of this fallback (using _norm) hit immediately below.
    # Compare the value, not the sentence around it. Either side may carry a
    # "<name> =" prefix, and which side has it is a coin toss:
    #
    #   answer "$x(1/2)=3-e$"   option "3 - e"       -> prefix on the ANSWER
    #   answer "$2a_0$"         option "r = 2a_0"    -> prefix on the OPTION
    #
    # Both were seen on real pages, and both flagged a CORRECT answer as
    # "matches no option" — the second one after the first had been fixed, so
    # this now strips symmetrically rather than one side at a time.
    def _forms(text: str) -> List[str]:
        out = [_canon_fidelity(text)]
        if "=" in text:
            out.append(_canon_fidelity(text.rsplit("=", 1)[-1]))
        return [f for f in out if f]

    answer_forms = _forms(parsed.get("answer") or "")
    for opt in options:
        if set(answer_forms) & set(_forms(opt["text"])):
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


# ─── Solver configuration ────────────────────────────────────────────────────
# The snap solver runs with thinking ENABLED — a measured exception to the
# blanket Rule 5 default, sanctioned 2026-08-11 after a harness A/B:
#
#     thinking OFF   24/27 rounds correct (89%), a different question wobbling
#                    every run, and rambling steps triggering rewrite retries
#     thinking ON    53/54 rounds correct (98%), and CHEAPER on the hard case —
#                    1,487/878 tokens in 9s where OFF spent 4,124/1,288 in 16s
#                    failing (the reasoning pass replaces the retry machinery)
#
# Rule 5's rationale (thinking eats the budget, returns an empty string) is
# about the tutor's live per-turn latency; a ~10-20s async solve is a different
# workload. Tutor, planner and scoping remain thinking-OFF.
#
# The env knobs remain for the eval harness; anything other than the sanctioned
# configuration logs loudly on every solve.
SOLVE_MODEL_OVERRIDE = os.getenv("SNAP_SOLVE_MODEL_OVERRIDE", "").strip()
SOLVE_THINKING = os.getenv("SNAP_SOLVE_THINKING", "enabled").strip()
SANCTIONED_THINKING = "enabled"

# How many independent solves to run per question, majority-voted. Measured
# need: an identical photo produced 13 on one run and 14 on the next at
# temperature 0 — a single sample asserts a coin flip as fact. 1 = old
# behaviour; the default is set by eval results, not taste.
SOLVE_SAMPLES = max(1, int(os.getenv("SNAP_SOLVE_SAMPLES", "1")))
# Diversity for the extra samples. The first sample stays at 0.0.
CONSENSUS_TEMP = 0.5


def _answer_key_of(parsed: Dict[str, Any]) -> str:
    """The vote a sample casts: its normalised answer."""
    if parsed.get("answerable") is False:
        return "__unanswerable__"
    return _norm(parsed.get("answer") or "") or "__empty__"


def _solve_with_consensus(make_call, doubt_id: str,
                          usage_acc: Optional[Dict[str, int]],
                          samples: Optional[int] = None,
                          expect_model: Optional[str] = None) -> Dict[str, Any]:
    """Runs N independent solves in parallel and majority-votes the answer.

    The winning parse is returned for validation/step-checking; losers are
    logged. If every sample disagrees, the temp-0 parse is returned carrying
    `_no_consensus`, which downstream turns into an 'unsure' doubt — an
    unstable answer is flagged, not asserted.
    """
    n = samples if samples is not None else SOLVE_SAMPLES
    if n <= 1:
        return _call_with_one_retry("solve", make_call(0.0),
                                    f"doubt={doubt_id[:8]}", usage_acc,
                                    expect_model=expect_model,
                                    service="snap_solve")

    temps = [0.0] + [CONSENSUS_TEMP] * (n - 1)
    results: List[Optional[Dict[str, Any]]] = [None] * n
    usages = [{"input": 0, "output": 0} for _ in range(n)]

    def run(i: int) -> None:
        try:
            results[i] = _call_with_one_retry(
                "solve", make_call(temps[i]), f"doubt={doubt_id[:8]} s{i + 1}",
                usages[i], expect_model=expect_model, service="snap_solve",
            )
        except SnapError as err:
            logger.warning("[SNAP CONSENSUS] doubt=%s sample %d failed: %s",
                           doubt_id[:8], i + 1, err)

    with ThreadPoolExecutor(max_workers=n) as pool:
        list(pool.map(run, range(n)))

    if usage_acc is not None:
        for u in usages:
            usage_acc["input"] = usage_acc.get("input", 0) + u["input"]
            usage_acc["output"] = usage_acc.get("output", 0) + u["output"]

    ok = [(i, p) for i, p in enumerate(results) if p is not None]
    if not ok:
        raise SnapError("Monk could not produce a solution for this one. "
                        "Please try again.", "solve")

    groups: Dict[str, List] = {}
    for i, parsed in ok:
        groups.setdefault(_answer_key_of(parsed), []).append((i, parsed))
    votes = {k: len(v) for k, v in groups.items()}

    # Largest group wins; the earliest (lowest-temperature) sample breaks ties.
    best_key = max(groups, key=lambda k: (len(groups[k]), -groups[k][0][0]))
    best = groups[best_key]
    winner = next((p for i, p in best if i == 0), best[0][1])
    winner["_consensus_votes"] = votes

    if len(best) < 2 and len(ok) >= 2:
        winner["_no_consensus"] = True
        logger.warning("[SNAP CONSENSUS] doubt=%s NO MAJORITY across %d samples: %s",
                       doubt_id[:8], len(ok), votes)
    elif len(votes) > 1:
        logger.info("[SNAP CONSENSUS] doubt=%s votes=%s -> %r",
                    doubt_id[:8], votes, (winner.get("answer") or "")[:60])
    return winner


def solve_question(question: Dict[str, Any], doubt_id: str = "-",
                   usage_acc: Optional[Dict[str, int]] = None,
                   on_event=None) -> Dict[str, Any]:
    """Solves ONE transcribed question. The solver never sees the image.

    With `on_event`, thinking progress and each completed step are emitted live
    ("thinking" / "step" / "steps_reset") while the solve runs. The ANSWER is
    never emitted this way: it goes through the same validation as ever and
    arrives only in the returned, gated solution.
    """
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
    solve_blind = (bool(options) and question.get("self_contained", True)
                   and not _options_are_the_question(question.get("stem")
                                                     or question.get("text")))

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

    solve_model = SOLVE_MODEL_OVERRIDE or MODEL_SOLVE
    use_openai = solve_model.startswith("gpt")
    solve_client = _openai_client() if use_openai else client
    if SOLVE_MODEL_OVERRIDE or SOLVE_THINKING != SANCTIONED_THINKING:
        logger.warning(
            "[SNAP SOLVE] EXPERIMENT CONFIG ACTIVE: model=%s thinking=%s — "
            "differs from the sanctioned configuration; eval use only",
            solve_model, SOLVE_THINKING,
        )

    def make_call(temperature: float):
        def call(corrective: Optional[str] = None):
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": payload + "\n\nProduce the solution JSON."},
            ]
            if corrective:
                messages.append({"role": "user", "content": corrective})
            kwargs: Dict[str, Any] = dict(
                model=solve_model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=temperature,
                max_tokens=2200,
                timeout=SOLVE_TIMEOUT_S,
            )
            if not use_openai:
                # Rule 5 — V4 defaults to chain-of-thought and will spend the
                # whole budget thinking, returning an empty string. The
                # experiment arm re-enables it WITH a budget big enough that the
                # answer still fits after the reasoning.
                kwargs["extra_body"] = {"thinking": {"type": SOLVE_THINKING}}
                if SOLVE_THINKING != "disabled":
                    kwargs["max_tokens"] = (
                        THINKING_MAX_TOKENS_DIAGRAM
                        if question.get("diagram_description")
                        else THINKING_MAX_TOKENS
                    )
            return solve_client.chat.completions.create(**kwargs)
        return call

    # Every knob this solve actually ran with, stated up front. When a solve
    # behaves oddly in production the first question is always "what config was
    # it on?" — blind or option-shown, thinking on or off, streamed or voted.
    logger.info(
        "[SNAP SOLVE START] doubt=%s q%s model=%s thinking=%s samples=%d "
        "streamed=%s blind=%s type=%s options=%d diagram=%s payload_chars=%d",
        doubt_id[:8], question.get("n"), solve_model, SOLVE_THINKING,
        SOLVE_SAMPLES, on_event is not None and SOLVE_SAMPLES <= 1, solve_blind,
        q_type, len(options), bool(question.get("diagram_description")),
        len(payload),
    )
    solve_t0 = time.time()

    if on_event is not None and SOLVE_SAMPLES <= 1:
        def make_kwargs():
            kwargs: Dict[str, Any] = dict(
                model=solve_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": payload + "\n\nProduce the solution JSON."},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=2200,
                timeout=SOLVE_TIMEOUT_S,
                _client=solve_client,
            )
            if not use_openai:
                kwargs["extra_body"] = {"thinking": {"type": SOLVE_THINKING}}
                if SOLVE_THINKING != "disabled":
                    kwargs["max_tokens"] = 8000
            return kwargs
        parsed = _streamed_solve(make_kwargs, on_event, doubt_id, usage_acc)
    else:
        parsed = _solve_with_consensus(make_call, doubt_id, usage_acc,
                                       expect_model=solve_model)
    llm_ms = int((time.time() - solve_t0) * 1000)
    logger.info(
        "[SNAP SOLVE LLM] doubt=%s q%s llm_ms=%d steps=%d answerable=%s",
        doubt_id[:8], question.get("n"), llm_ms, len(parsed.get("steps") or []),
        parsed.get("answerable", True),
    )

    # Steps are what the student reads. A rambling one is both unreadable and
    # the thing that breaks the JSON, so it earns one corrective retry.
    rewrite_ms = 0
    problems = _step_problems(parsed.get("steps") or [])
    if problems:
        rewrite_t0 = time.time()
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
            kwargs: Dict[str, Any] = dict(
                model=solve_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": payload + "\n\nProduce the solution JSON."},
                    {"role": "assistant", "content": json.dumps(parsed)[:6000]},
                    {"role": "user", "content": corrective},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=2200,
                timeout=SOLVE_TIMEOUT_S,
            )
            if not use_openai:
                kwargs["extra_body"] = {"thinking": {"type": SOLVE_THINKING}}
                if SOLVE_THINKING != "disabled":
                    kwargs["max_tokens"] = 8000
            return solve_client.chat.completions.create(**kwargs)

        try:
            retried = _call_with_one_retry("solve", retry_call,
                                           f"doubt={doubt_id[:8]} steps", usage_acc,
                                           expect_model=solve_model,
                                           service="snap_solve")
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
        rewrite_ms = int((time.time() - rewrite_t0) * 1000)
        logger.info("[SNAP SOLVE REWRITE] doubt=%s q%s rewrite_ms=%d "
                    "(a second full LLM call, on top of the solve)",
                    doubt_id[:8], question.get("n"), rewrite_ms)
    solution = _validate_solution(
        parsed,
        # A blind solve has no options to validate against; the matcher below
        # does that instead.
        options=[] if solve_blind else options,
        question_type=q_type,
        had_diagram=bool(question.get("diagram_description")),
    )
    if parsed.get("_consensus_votes"):
        solution["consensus_votes"] = parsed["_consensus_votes"]
    if parsed.get("_no_consensus"):
        # Repeated attempts, different answers. Flag it rather than assert one.
        solution["no_consensus"] = True
        solution["consensus_note"] = (
            "Monk tried this question several times and reached different "
            "answers, so it is not stating one as fact \u2014 the most likely "
            "working is below. Worth checking in a live session."
        )

    stepcheck_ms = match_ms = 0
    if not solve_blind and options and solution.get("option_labels"):
        # This solve SAW its options, which is where answers detach from their
        # own reasoning. Cross-check: the steps must conclude the same option.
        stepcheck_t0 = time.time()
        steps_say = _steps_support_label(solution, options, doubt_id, usage_acc)
        stepcheck_ms = int((time.time() - stepcheck_t0) * 1000)
        logger.info("[SNAP STEPCHECK] doubt=%s q%s stepcheck_ms=%d steps_conclude=%s",
                    doubt_id[:8], question.get("n"), stepcheck_ms, steps_say)
        if steps_say and set(steps_say) != set(solution["option_labels"]):
            logger.warning(
                "[SNAP STEPCHECK] doubt=%s answer says %s but the steps conclude "
                "%s — trusting the derivation",
                doubt_id[:8], solution["option_labels"], steps_say,
            )
            chosen = [o for o in options if o["label"] in steps_say]
            solution["option_labels"] = steps_say
            solution["answer"] = " and ".join(o["text"] for o in chosen)
            solution["answer_from_steps"] = True

    if solve_blind:
        match_t0 = time.time()
        derived_answer = solution["answer"]
        labels = match_answer_to_options(solution["answer"], options, q_type,
                                         doubt_id, usage_acc)
        match_ms = int((time.time() - match_t0) * 1000)
        logger.info(
            "[SNAP MATCH] doubt=%s q%s match_ms=%d derived=%r -> labels=%s",
            doubt_id[:8], question.get("n"), match_ms, derived_answer[:80], labels,
        )
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
    #
    # Normalised HERE, not only where the transcriber's value is read: the
    # solver's own answer is preferred, so its raw string went to the database
    # untouched. It writes whatever it likes — "Mathematics", "mathematics" and
    # "Maths" all appeared across 18 real rows for the same subject, as did
    # "Chemistry" and "chemistry". The subject filter on /doubts is an equality
    # match against a fixed list, so those rows were correctly classified and
    # still invisible under their own subject. `unknown` becomes NULL, which is
    # what "no subject read" already means in that column.
    solution["subject"] = canonical_subject(
        solution["subject"] or question.get("subject"))
    solution["topic"] = solution["topic"] or question.get("topic")

    # The whole solve on one greppable line: where the time went, and what came
    # out. `llm` is the model actually reasoning; everything after it is a gate
    # we added, so this shows what our own checking costs on top of the answer.
    total_ms = int((time.time() - solve_t0) * 1000)
    solution["timings"] = {
        "llm_ms": llm_ms, "rewrite_ms": rewrite_ms,
        "stepcheck_ms": stepcheck_ms, "match_ms": match_ms, "total_ms": total_ms,
    }
    logger.info(
        "[SNAP SOLVE DONE] doubt=%s q%s total_ms=%d (llm=%d rewrite=%d "
        "stepcheck=%d match=%d overhead=%d) answer=%r labels=%s "
        "unmatched=%s no_consensus=%s from_steps=%s printed_agrees=%s",
        doubt_id[:8], question.get("n"), total_ms, llm_ms, rewrite_ms,
        stepcheck_ms, match_ms, total_ms - llm_ms,
        (solution.get("answer") or "")[:60], solution.get("option_labels"),
        solution.get("unmatched", False), solution.get("no_consensus", False),
        solution.get("answer_from_steps", False),
        solution.get("agrees_with_printed_answer"),
    )
    return solution


def _steps_support_label(solution: Dict[str, Any],
                         options: List[Dict[str, str]],
                         doubt_id: str,
                         usage_acc: Optional[Dict[str, int]]) -> Optional[List[str]]:
    """Which option the STEPS conclude, judged by a model that sees only them.

    Exists because a solver that was shown its options returned an answer
    contradicting its own reasoning: steps derived tetrahedral / square planar /
    octahedral (option B) and the answer said option D. The steps are the
    derivation; an answer at odds with them is the back-fitting failure in a
    new coat. Returns the steps-supported labels, or None when unclear.
    """
    client = _openai_client()

    def call(corrective: Optional[str] = None):
        messages = [
            {"role": "system", "content": (
                "You are given the worked steps of a solution and a list of "
                "options. Say which option the STEPS conclude. Judge only from "
                "the steps — do not solve the question yourself, and do not "
                "judge whether the steps are correct. Return ONLY JSON: "
                '{"option_labels": ["B"], "clear": true}. If the steps do not '
                'clearly conclude any option, return {"option_labels": [], '
                '"clear": false}.'
            )},
            {"role": "user", "content": json.dumps({
                "steps": [st["text"] for st in solution.get("steps") or []],
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
            max_tokens=200,
            timeout=TRANSCRIBE_TIMEOUT_S,
        )

    try:
        parsed = _call_with_one_retry("transcribe", call,
                                      f"stepcheck={doubt_id[:8]}", usage_acc,
                                      service="snap_stepcheck")
    except SnapError:
        return None
    if not parsed.get("clear"):
        return None
    valid = {o["label"] for o in options}
    labels = [str(l).strip().strip(".)(").upper()
              for l in (parsed.get("option_labels") or [])]
    labels = [l for l in labels if l in valid]
    return labels or None


# ─── The pipeline ────────────────────────────────────────────────────────────

def iter_snapped_questions(image_bytes: bytes, mime_type: str,
                           doubt_id: str = "-",
                           max_questions: int = MAX_QUESTIONS):
    """Yields each question as soon as IT is done, rather than after all of them.

    A solve takes ~25s. Every legible question's solve is launched CONCURRENTLY
    (the loop below that starts one thread per question) rather than one after
    another, so a page of three no longer costs 3x one solve's time — it costs
    roughly 1x, the slowest of the three. Live thinking/step events are still
    only forwarded for the question currently "in front" (matching the
    single-panel UI), but the others are already solving in the background, so
    their card tends to appear moments after the previous one instead of
    another full 20-30s later.

    Yields ("meta", {...}) first, then ("question", {...}) per question, then
    ("summary", {...}). Raises SnapError if the page cannot be read at all —
    that failure happens before any question exists.
    """
    import queue as _queue
    import threading as _threading

    started = time.time()
    tx_usage: Dict[str, int] = {"input": 0, "output": 0}
    sv_usage: Dict[str, int] = {"input": 0, "output": 0}

    logger.info("[SNAP PIPELINE] doubt=%s START streamed image=%.1fKB mime=%s cap=%d",
                doubt_id[:8], len(image_bytes) / 1024, mime_type, max_questions)

    # Trim browser furniture before anything reads the image. Applied here, at
    # the entry point, so the OCR and the diagram-describing pass both work
    # from the same trimmed page rather than disagreeing about what was sent.
    image_bytes, crop_note = crop_to_content(image_bytes, doubt_id)
    if crop_note:
        mime_type = "image/png"

    read = transcribe_questions(image_bytes, mime_type, doubt_id, tx_usage,
                                max_questions)
    transcribe_ms = int((time.time() - started) * 1000)
    logger.info(
        "[SNAP PIPELINE] doubt=%s transcribe_ms=%d (ocr=%d structure=%d) "
        "questions=%d legible=%d — the student can see their question NOW",
        doubt_id[:8], transcribe_ms, read.get("ocr_ms", 0),
        read.get("structure_ms", 0), len(read["questions"]),
        sum(1 for q in read["questions"] if q["legible"]),
    )

    yield "meta", {
        "question_count": len(read["questions"]),
        "note": read["note"],
        "ocr_confidence": read.get("ocr_confidence"),
        "transcribe_ms": transcribe_ms,
        "ocr_ms": read.get("ocr_ms", 0),
        "structure_ms": read.get("structure_ms", 0),
    }

    questions = read["questions"]

    # The student's own question is fully known NOW — transcription is done and
    # no solve has started. Send it immediately rather than holding it until the
    # solve finishes: the page used to have nothing to show for the whole
    # ~20-30s solve, then painted the question and its answer together at the
    # end. The question is what the student is waiting to see confirmed ("did it
    # read my page right?"), and it costs nothing extra to show it ~20s sooner.
    # No solution fields here — nothing about an ANSWER is ever streamed early;
    # the validated "question" event below stays authoritative for that.
    yield "questions_read", {
        "questions": [
            {
                "question_index": q["n"],
                "question_text": q.get("text"),
                "stem": q.get("stem") or q.get("text"),
                "options": q.get("options") or [],
                "subject": (q.get("subject")
                            if q.get("subject") != "unknown" else None),
                "chapter": q.get("topic"),
                "question_type": q.get("question_type"),
                "legible": q["legible"],
                "legibility_note": q.get("note"),
            }
            for q in questions
        ],
    }

    # Diagram description must finish before its question can be solved — the
    # solver reads diagram_description off the question dict — so this stays
    # sequential. It is per-page rare (only figure questions) and fast next to
    # a solve.
    diagram_ms = options_ms = 0
    for question in questions:
        if question.get("requires_diagram") and question["legible"]:
            diagram_t0 = time.time()
            description = describe_diagram(
                image_bytes, mime_type, question.get("text") or "", doubt_id, tx_usage
            )
            q_diagram_ms = int((time.time() - diagram_t0) * 1000)
            diagram_ms += q_diagram_ms
            # This pass sits between the student seeing their question and any
            # solve starting, so its cost is worth seeing on its own.
            logger.info(
                "[SNAP DIAGRAM] doubt=%s q%s diagram_ms=%d model=%s described=%s",
                doubt_id[:8], question["n"], q_diagram_ms, MODEL_DIAGRAM,
                bool(description),
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

    # Launch every legible question's solve now, all at once. Each gets its own
    # event queue and its own usage accumulator — solve_question mutates
    # usage_acc with plain (non-atomic) dict reads+writes, so sharing sv_usage
    # directly across concurrent threads would race and silently drop token
    # counts. Merged into sv_usage below, after that question's None sentinel
    # confirms its thread is done (Queue's internal lock makes that write
    # visible here, the same guarantee the outcome dict below already relied
    # on before this change).
    # ONE queue for every solve, not one each. The delivery loop below has to
    # take whichever question finishes FIRST, and it cannot do that while
    # blocked on a particular question's queue.
    # Options that are printed as figures, read off the image the same way a
    # question's own figure is. Without this the question was refused with
    # "retake the photo with all the choices in frame", which cannot work: no
    # photograph of a graph turns it into text.
    # A choice question whose options were READ as text can still have been
    # printed as pictures. Mathpix transcribes a chemical structure into a
    # SMILES string, so "which is the strongest Bronsted base?" came back with
    # four perfectly real text options — `<smiles>C1CCNC1</smiles>` and
    # friends — which never reach the drawn-options gate below, and a student
    # was shown "structure: C1CCNC1" where the paper showed a ring.
    #
    # The figures are already attributed to the question and the counts match,
    # so the same keeping applies. `keep_option_figures` declines whenever they
    # do not, which is what makes this safe to try on every choice question
    # rather than only the ones we guessed were drawn.
    for question in questions:
        if not question["legible"] or question.get("options_are_drawn"):
            continue
        options = question.get("options") or []
        spans = question.get("figure_spans") or []
        if len(options) >= 2 and len(spans) == len(options):
            question["options"] = keep_option_figures(
                options, spans, image_bytes, doubt_id, question["n"]
            )

    for question in questions:
        if not question.get("options_are_drawn") or not question["legible"]:
            continue
        opts_t0 = time.time()
        drawn = describe_option_figures(
            image_bytes, mime_type, question.get("stem") or "", doubt_id, tx_usage
        )
        options_ms += int((time.time() - opts_t0) * 1000)
        if drawn:
            # Keep the pictures, not only the sentences describing them. A
            # question whose options are circuits is unreadable as four
            # descriptions; the figures are the only part of this page worth
            # storing, so they are the part stored.
            question["options"] = keep_option_figures(
                drawn, question.get("figure_spans") or read.get("diagram_spans") or [],
                image_bytes, doubt_id, question["n"]
            )
            # The options ARE the question here — the student is choosing
            # between curves — so the solver must see them rather than deriving
            # blind and matching afterwards.
            question["self_contained"] = False
            question["text"] = (question.get("stem") or "") + "\n" + "\n".join(
                f"({o['label']}) {o['text']}" for o in drawn)
        else:
            question["legible"] = False
            question["remedy"] = REMEDY_NOT_PHOTO
            question["reason"] = "options_are_figures"
            question["note"] = (
                "The answer choices for this one are diagrams, and Monk could "
                "not tell them apart well enough to choose between them. "
                "Retaking the photo will not change that \u2014 ask this one in a "
                "live session, where the options can be drawn on the board."
            )

    # And the figures the QUESTION itself was printed with — the beaker, the
    # graph, the pair of wires. Skipped when this question's figures were
    # already kept as its options, so a picture is stored once and belongs to
    # one thing.
    for question in questions:
        if not question["legible"]:
            continue
        if any((o or {}).get("figure_key") for o in question.get("options") or []):
            continue
        spans = question.get("figure_spans") or []
        if spans:
            question["figure_keys"] = keep_question_figures(
                spans, image_bytes, doubt_id, question["n"]
            )

    inbox: "_queue.Queue" = _queue.Queue()
    outcomes: Dict[int, Dict[str, Any]] = {}
    usages: Dict[int, Dict[str, int]] = {}
    threads: List[_threading.Thread] = []

    for question in questions:
        if not question["legible"]:
            continue
        n = question["n"]
        outcomes[n] = {}
        usages[n] = {"input": 0, "output": 0}

        def _run(q=question, num=n, outcome=outcomes[n], usage=usages[n]):
            try:
                outcome["solution"] = solve_question(
                    q, doubt_id, usage,
                    on_event=lambda kind, data: inbox.put(("event", num, kind, data)),
                )
            except SnapError as err:
                outcome["error"] = err
            finally:
                inbox.put(("done", num, None, None))

        worker = _threading.Thread(target=_run, daemon=True)
        worker.start()
        threads.append(worker)


    logger.info(
        "[SNAP PIPELINE] doubt=%s launched %d concurrent solve(s) at t+%dms "
        "(diagram_ms=%d) — wall time from here is the SLOWEST solve, not the sum",
        doubt_id[:8], len(threads), int((time.time() - started) * 1000), diagram_ms,
    )

    solved_count = 0
    by_number = {q["n"]: q for q in questions}

    def _deliver(question):
        """Log and hand one finished question to the student."""
        logger.info(
            "[SNAP DELIVERED] doubt=%s q%s at t+%dms status=%s",
            doubt_id[:8], question["n"], int((time.time() - started) * 1000),
            "solved" if question.get("solution") else
            ("solve_failed" if question.get("solve_error") else "not_legible"),
        )

    # Nothing is being solved for these, so there is nothing to wait for.
    for question in questions:
        if not question["legible"]:
            logger.info("[SNAP] doubt=%s q%d not solvable: %s",
                        doubt_id[:8], question["n"], question.get("note"))
            _deliver(question)
            yield "question", question

    # Answers go out in the order they FINISH, not the order they sit on the
    # page. Delivering in page order meant one slow question held every answer
    # behind it: on a real submission q5 was ready at 8.9s and q4 at 23.5s,
    # and the student saw neither until q3 — which had wedged — gave up at
    # 2m13s, so all three appeared at once, two minutes late.
    #
    # The page keeps its own order regardless: each card is rendered from the
    # question list sent before any solving, and fills in when its answer
    # arrives, so out-of-order delivery is invisible.
    pending = [q["n"] for q in questions if q["legible"]]
    outstanding = set(pending)
    # Steps stream for ONE question at a time, matching the single live panel.
    # The featured question is whichever is earliest on the page and still
    # running; the rest solve quietly and their working is not shown.
    featured = pending[0] if pending else None

    while outstanding:
        kind, n, ev_kind, data = inbox.get()

        if kind == "event":
            # Only the featured question's working is forwarded. Another
            # question's steps arriving mid-stream would swap the panel's
            # contents under the student mid-sentence.
            if n == featured:
                yield ev_kind, {**data, "question_index": n}
            continue

        outstanding.discard(n)
        question = by_number[n]
        sv_usage["input"] += usages[n]["input"]
        sv_usage["output"] += usages[n]["output"]

        outcome = outcomes[n]
        if "solution" in outcome:
            question["solution"] = outcome["solution"]
            solved_count += 1
        elif "error" in outcome:
            err = outcome["error"]
            logger.error("[SNAP SOLVE FAILED] doubt=%s q%d: %s",
                         doubt_id[:8], question["n"], err)
            question["solve_error"] = str(err)
            question["solve_remedy"] = err.remedy
            question["solve_reason"] = err.reason

        _deliver(question)
        yield "question", question

        if n == featured:
            # Hand the panel to the next question still working. Its earlier
            # steps are deliberately NOT replayed — flushing a backlog would
            # flash seconds of working past in an instant, which reads as a
            # glitch rather than as speed.
            featured = next((m for m in pending if m in outstanding), None)
            if featured is not None:
                logger.info(
                    "[SNAP PIPELINE] doubt=%s live panel moves to q%d "
                    "(%d still solving)",
                    doubt_id[:8], featured, len(outstanding),
                )

    for worker in threads:
        worker.join()

    latency_ms = int((time.time() - started) * 1000)
    solve_span_ms = latency_ms - transcribe_ms - diagram_ms - options_ms
    logger.info(
        "[SNAP] doubt=%s solved %d/%d in %dms (transcribe %dms)",
        doubt_id[:8], solved_count, len(read["questions"]), latency_ms, transcribe_ms,
    )
    # The whole submission on one line. Read left to right, this is exactly
    # where a student's wait went — and the three parts are independently
    # actionable: ocr is Mathpix, structure and solve are ours.
    logger.info(
        "[SNAP BREAKDOWN] doubt=%s total=%dms = ocr %dms + structure %dms "
        "+ diagram %dms + options %dms + solve %dms | questions=%d solved=%d | "
        "tokens transcribe(in=%d out=%d) solve(in=%d out=%d)",
        doubt_id[:8], latency_ms, read.get("ocr_ms", 0),
        read.get("structure_ms", 0), diagram_ms, options_ms, solve_span_ms,
        len(read["questions"]), solved_count,
        tx_usage["input"], tx_usage["output"],
        sv_usage["input"], sv_usage["output"],
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
        "ocr_ms": read.get("ocr_ms", 0),
        "structure_ms": read.get("structure_ms", 0),
        "diagram_ms": diagram_ms,
        "solve_ms": solve_span_ms,
        "latency_ms": latency_ms,
        "usage": {"transcribe": tx_usage, "solve": sv_usage},
    }


def solve_snapped_image(image_bytes: bytes, mime_type: str,
                        doubt_id: str = "-",
                        max_questions: int = MAX_QUESTIONS) -> Dict[str, Any]:
    """Transcribe, then solve every legible question CONCURRENTLY.

    Returns {"questions": [...], "note": str|None, ...timings}. Each entry has
    `legible`; legible ones also carry `solution`. Illegible ones carry the
    transcriber's `note` saying what was unclear and are never solved.

    Solves run in parallel (see iter_snapped_questions's docstring for why), so
    a multi-question page's wall time is roughly its slowest single solve
    rather than their sum.
    """
    started = time.time()
    tx_usage: Dict[str, int] = {"input": 0, "output": 0}
    sv_usage: Dict[str, int] = {"input": 0, "output": 0}
    logger.info("[SNAP PIPELINE] doubt=%s START non-streamed image=%.1fKB mime=%s cap=%d",
                doubt_id[:8], len(image_bytes) / 1024, mime_type, max_questions)
    image_bytes, crop_note = crop_to_content(image_bytes, doubt_id)
    if crop_note:
        mime_type = "image/png"
    read = transcribe_questions(image_bytes, mime_type, doubt_id, tx_usage,
                                max_questions)
    transcribe_ms = int((time.time() - started) * 1000)

    questions = read["questions"]

    # A figure question gets its diagram put into words first. Only if that
    # fails is it refused — and then honestly, as "the figure could not be made
    # out", not as "your photo is bad". Sequential: per-page rare and fast next
    # to a solve, and must finish before that question can be dispatched below.
    diagram_ms = options_ms = 0
    for question in questions:
        if question.get("requires_diagram") and question["legible"]:
            diagram_t0 = time.time()
            description = describe_diagram(
                image_bytes, mime_type, question.get("text") or "", doubt_id, tx_usage
            )
            q_diagram_ms = int((time.time() - diagram_t0) * 1000)
            diagram_ms += q_diagram_ms
            logger.info(
                "[SNAP DIAGRAM] doubt=%s q%s diagram_ms=%d model=%s described=%s",
                doubt_id[:8], question["n"], q_diagram_ms, MODEL_DIAGRAM,
                bool(description),
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


    # Options that are printed as figures, read off the image the same way a
    # question's own figure is. Without this the question was refused with
    # "retake the photo with all the choices in frame", which cannot work: no
    # photograph of a graph turns it into text.
    # A choice question whose options were READ as text can still have been
    # printed as pictures. Mathpix transcribes a chemical structure into a
    # SMILES string, so "which is the strongest Bronsted base?" came back with
    # four perfectly real text options — `<smiles>C1CCNC1</smiles>` and
    # friends — which never reach the drawn-options gate below, and a student
    # was shown "structure: C1CCNC1" where the paper showed a ring.
    #
    # The figures are already attributed to the question and the counts match,
    # so the same keeping applies. `keep_option_figures` declines whenever they
    # do not, which is what makes this safe to try on every choice question
    # rather than only the ones we guessed were drawn.
    for question in questions:
        if not question["legible"] or question.get("options_are_drawn"):
            continue
        options = question.get("options") or []
        spans = question.get("figure_spans") or []
        if len(options) >= 2 and len(spans) == len(options):
            question["options"] = keep_option_figures(
                options, spans, image_bytes, doubt_id, question["n"]
            )

    for question in questions:
        if not question.get("options_are_drawn") or not question["legible"]:
            continue
        opts_t0 = time.time()
        drawn = describe_option_figures(
            image_bytes, mime_type, question.get("stem") or "", doubt_id, tx_usage
        )
        options_ms += int((time.time() - opts_t0) * 1000)
        if drawn:
            # Keep the pictures, not only the sentences describing them. A
            # question whose options are circuits is unreadable as four
            # descriptions; the figures are the only part of this page worth
            # storing, so they are the part stored.
            question["options"] = keep_option_figures(
                drawn, question.get("figure_spans") or read.get("diagram_spans") or [],
                image_bytes, doubt_id, question["n"]
            )
            # The options ARE the question here — the student is choosing
            # between curves — so the solver must see them rather than deriving
            # blind and matching afterwards.
            question["self_contained"] = False
            question["text"] = (question.get("stem") or "") + "\n" + "\n".join(
                f"({o['label']}) {o['text']}" for o in drawn)
        else:
            question["legible"] = False
            question["remedy"] = REMEDY_NOT_PHOTO
            question["reason"] = "options_are_figures"
            question["note"] = (
                "The answer choices for this one are diagrams, and Monk could "
                "not tell them apart well enough to choose between them. "
                "Retaking the photo will not change that \u2014 ask this one in a "
                "live session, where the options can be drawn on the board."
            )

    # And the figures the QUESTION itself was printed with — the beaker, the
    # graph, the pair of wires. Skipped when this question's figures were
    # already kept as its options, so a picture is stored once and belongs to
    # one thing.
    for question in questions:
        if not question["legible"]:
            continue
        if any((o or {}).get("figure_key") for o in question.get("options") or []):
            continue
        spans = question.get("figure_spans") or []
        if spans:
            question["figure_keys"] = keep_question_figures(
                spans, image_bytes, doubt_id, question["n"]
            )

    to_solve: List[Dict[str, Any]] = []
    for question in questions:
        if not question["legible"]:
            logger.info(
                "[SNAP] doubt=%s q%d illegible, not sent to solver: %s",
                doubt_id[:8], question["n"], question.get("note"),
            )
            continue
        to_solve.append(question)

    # One usage dict per solve, not the shared sv_usage — solve_question
    # mutates it with plain (non-atomic) dict reads+writes, which would race
    # across threads. Summed into sv_usage once every solve has returned.
    solve_usages = [{"input": 0, "output": 0} for _ in to_solve]
    solve_results: List[Optional[Dict[str, Any]]] = [None] * len(to_solve)
    solve_errors: List[Optional[SnapError]] = [None] * len(to_solve)

    def _solve_one(i: int) -> None:
        try:
            solve_results[i] = solve_question(to_solve[i], doubt_id, solve_usages[i])
        except SnapError as err:
            solve_errors[i] = err

    if to_solve:
        with ThreadPoolExecutor(max_workers=len(to_solve)) as pool:
            list(pool.map(_solve_one, range(len(to_solve))))

    solved_count = 0
    for i, question in enumerate(to_solve):
        sv_usage["input"] += solve_usages[i]["input"]
        sv_usage["output"] += solve_usages[i]["output"]
        if solve_results[i] is not None:
            question["solution"] = solve_results[i]
            solved_count += 1
        else:
            # One question failing must not lose the others.
            err = solve_errors[i]
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
    solve_span_ms = latency_ms - transcribe_ms - diagram_ms - options_ms
    logger.info(
        "[SNAP] doubt=%s solved %d/%d in %dms (transcribe %dms)",
        doubt_id[:8], solved_count, len(read["questions"]), latency_ms, transcribe_ms,
    )
    logger.info(
        "[SNAP BREAKDOWN] doubt=%s total=%dms = ocr %dms + structure %dms "
        "+ diagram %dms + options %dms + solve %dms | questions=%d solved=%d | "
        "tokens transcribe(in=%d out=%d) solve(in=%d out=%d)",
        doubt_id[:8], latency_ms, read.get("ocr_ms", 0),
        read.get("structure_ms", 0), diagram_ms, options_ms, solve_span_ms,
        len(read["questions"]), solved_count,
        tx_usage["input"], tx_usage["output"],
        sv_usage["input"], sv_usage["output"],
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
        "ocr_ms": read.get("ocr_ms", 0),
        "structure_ms": read.get("structure_ms", 0),
        "diagram_ms": diagram_ms,
        "solve_ms": solve_span_ms,
        "latency_ms": latency_ms,
        "usage": {"transcribe": tx_usage, "solve": sv_usage},
    }
