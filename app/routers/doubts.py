"""Snap a Doubt (write) and My Doubts (read).

A submission is: photo in → R2 → transcribe → solve each legible question →
one row per question. The row holds the R2 object KEY; the photo is only ever
handed back through a short-lived presigned URL.

Nothing fails silently. An illegible question is stored as 'illegible' with what
the transcriber said was unclear, a failed solve is stored as 'failed' with its
reason, and both are reported to the client with the stage that failed.
"""
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth import get_current_user_id
from app.db import supabase
import json

from app.snap import (
    ALLOWED_MIME,
    iter_snapped_questions,
    DAILY_QUESTION_LIMIT,
    REMEDY_OUR_SIDE,
    REMEDY_RETAKE,
    MAX_IMAGE_BYTES,
    MAX_QUESTIONS,
    SnapError,
    solve_snapped_image,
    stream_followup,
)
from app import exam_scope
from app.exam_scope import canonical_subject
from app.storage_r2 import delete_image, signed_url


# `doubts.figures` arrives with migration 0030. Code and schema deploy
# separately, so for the window between them — and for any environment where
# the migration has not been run — an insert that mentions the column is
# retried without it. A snap that loses its figures is a worse answer; a snap
# that cannot write its row at all is no answer, and that is not a trade worth
# making on deploy ordering.
_HAS_FIGURES_COLUMN = True


def _insert_doubt_rows(rows):
    """Inserts doubt rows, surviving a `figures` column that is not there yet."""
    global _HAS_FIGURES_COLUMN

    def without_figures(items):
        return [{k: v for k, v in item.items() if k != "figures"} for item in items]

    if not _HAS_FIGURES_COLUMN:
        return supabase.table("doubts").insert(without_figures(rows)).execute()
    try:
        return supabase.table("doubts").insert(rows).execute()
    except Exception as err:
        if "figures" not in str(err):
            raise
        _HAS_FIGURES_COLUMN = False
        logger.error(
            "doubts.figures is missing — migration 0030 has not been applied. "
            "Writing without it; question figures are not kept until it is."
        )
        return supabase.table("doubts").insert(without_figures(rows)).execute()


def _figure_urls(keys):
    """Signed URLs for a question's own figures, in the order they were kept.

    A key that cannot be signed is dropped rather than sent: a broken image is
    worse than one fewer, and the written description is still there.
    """
    out = []
    for key in keys or []:
        url = signed_url(key) if isinstance(key, str) else None
        if url:
            out.append(url)
    return out


def _options_with_figures(options):
    """Swaps each stored figure key for a URL the app can actually load.

    An option whose choice is a picture carries `figure_key`; the key itself is
    private and useless to a client, so it never leaves the server. A key that
    cannot be signed drops back to the description that was always there.
    """
    out = []
    for option in options or []:
        if not isinstance(option, dict):
            continue
        key = option.get("figure_key")
        clean = {k: v for k, v in option.items() if k != "figure_key"}
        if key:
            url = signed_url(key)
            if url:
                clean["image_url"] = url
        out.append(clean)
    return out

logger = logging.getLogger("doubts")

router = APIRouter(prefix="/doubts", tags=["doubts"])

LIST_COLUMNS = (
    "id, submission_id, question_index, question_text, stem, options, subject, "
    "chapter, concept, question_type, legible, legibility_note, answer, key_idea, "
    "option_labels, solved, status, failure_reason, created_at"
)
# image_key is selected only for legacy doubts saved before images stopped being
# stored; signed_url() below returns None for a row that never had one.
DETAIL_COLUMNS = LIST_COLUMNS + ", explanation, steps, image_key, figures"


class ReportRequest(BaseModel):
    comment: Optional[str] = None


def _flatten_solution(solution: Dict[str, Any],
                      withheld: bool = False) -> Optional[str]:
    """Renders the solution as readable text for `doubts.explanation`.

    The doubt page shows `explanation` as a plain string, so the structured
    solution needs a readable form alongside `steps`. Math keeps its $…$
    delimiters so the same text renders correctly through KaTeX.
    """
    steps = solution.get("steps") or []
    if not steps and not solution.get("answer") and not withheld:
        return None

    lines = [f"{step.get('n', i)}. {step.get('text', '')}".strip()
             for i, step in enumerate(steps, 1)]
    if withheld:
        lines.append(
            "Answer: withheld \u2014 Monk's working disagrees with the answer "
            "printed on the page, so it is not stating one it might have wrong."
        )
    elif solution.get("answer"):
        lines.append(f"Answer: {solution['answer']}")
    if solution.get("key_idea"):
        lines.append(f"Key idea: {solution['key_idea']}")
    return "\n".join(lines)


def _subject_for_row(solution: Dict[str, Any],
                     question: Dict[str, Any]) -> Optional[str]:
    """The subject to store, in the one spelling the filter matches.

    The models classify accurately and label inconsistently. Across 18 real
    rows the same subject was written "Maths", "Mathematics" and "mathematics",
    and "Chemistry" alongside "chemistry". /doubts filters with an equality
    match against a fixed list, so four of seven maths doubts were correctly
    classified and still invisible when a student filtered for Maths.
    """
    return canonical_subject(
        solution.get("subject") or question.get("subject"))


def _concept(solution: Dict[str, Any], question: Dict[str, Any]) -> Optional[str]:
    """The short title the list and detail pages show as the doubt's name."""
    return (solution.get("topic") or question.get("topic")
            or solution.get("subject") or question.get("subject") or None)


def _quota_resets_in(user_id: str) -> Optional[Dict[str, Any]]:
    """When the next question comes back, on a rolling 24-hour window.

    The allowance is not a midnight reset — each question frees its own slot 24
    hours after it was asked, so a student who used everything at 9pm gets one
    back at 9pm tomorrow, then the rest as they age out. This returns the wait
    until the OLDEST question in the window expires, which is the first slot to
    return.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    res = (
        supabase.table("doubts")
        .select("created_at")
        .eq("user_id", user_id)
        .gte("created_at", since.isoformat())
        .order("created_at")
        .limit(1)
        .execute()
    )
    if not res.data:
        return None

    oldest = datetime.fromisoformat(res.data[0]["created_at"].replace("Z", "+00:00"))
    frees_at = oldest + timedelta(hours=24)
    seconds = max(0, int((frees_at - datetime.now(timezone.utc)).total_seconds()))
    hours, minutes = divmod(seconds // 60, 60)
    if hours >= 1:
        human = f"about {hours} hour{'s' if hours != 1 else ''}"
    elif minutes >= 1:
        human = f"about {minutes} minute{'s' if minutes != 1 else ''}"
    else:
        human = "a moment"
    return {"seconds": seconds, "hours": hours, "human": human,
            "at": frees_at.isoformat()}


# What the allowance actually pays for: an ANSWER.
#
# 'illegible' used to count too, on the reasoning that a bad photo is the
# student's own input and still costs an OCR read. That held right up until our
# own bugs started producing it — numerical questions refused for "missing"
# options they never have, and figure questions refused before their figure was
# looked at. Students were charged nine slots for questions the pipeline was
# built to answer and briefly could not. A quota that bills for our defects is
# not a quota, and the OCR read it is defending costs $0.002.
#
# So: a student is charged when they got an answer, and not otherwise.
#
# 'unsure' used to count, on the reasoning that the question WAS solved, the
# working is shown, and only the final certainty is withheld — a real answer,
# and the expensive solve really was spent. That reasoning describes our side of
# the exchange rather than theirs. What a student receives for an 'unsure' is
# working they have been told not to trust the end of: the one case where we
# cannot say what the answer is. Billing a question for that asks them to pay
# for our uncertainty, and the triggers are all ours — a disagreement with the
# printed key, an answer outside the printed options, two solves that disagree.
# None of them is anything the student did to their photo.
#
# So the line is now the plainest one available: a slot is spent when a student
# is given an answer. The solve cost is real and unbilled, which is a cost we
# carry rather than one we pass on for a result we would not stand behind.
CHARGEABLE_STATUSES = ("solved",)


def _questions_used_today(user_id: str) -> int:
    """Questions this student has been ANSWERED in the last rolling 24 hours.

    Nothing else is billed: not a photo we could not read, not a question we
    read perfectly and failed to solve, and not one we solved but would not
    stand behind the answer to.
    """
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    res = (
        supabase.table("doubts")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .gte("created_at", since)
        .in_("status", list(CHARGEABLE_STATUSES))
        .execute()
    )
    return res.count if res.count is not None else len(res.data or [])


def _scrap(question_text: Optional[str]) -> str:
    """The few words shown on the little notepad thumbnail in the list."""
    words = (question_text or "").split()
    return " ".join(words[:7]) + ("…" if len(words) > 7 else "")


@router.post("", status_code=201)
async def snap_doubt(
    file: UploadFile = File(..., description="Photo of up to 3 questions"),
    user_id: str = Depends(get_current_user_id),
):
    """POST /doubts — snap a photo, get its questions read and solved."""
    mime = (file.content_type or "").lower().split(";")[0].strip()
    if mime not in ALLOWED_MIME:
        raise HTTPException(
            status_code=415,
            detail="That file type is not supported. Send a JPEG, PNG, WebP or HEIC photo.",
        )

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="That file was empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"That photo is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
        )

    # Daily quota, checked before anything is spent — no OCR, no upload, no
    # model call. 429 is the honest status: the request is fine, the allowance
    # is not.
    try:
        used_today = _questions_used_today(user_id)
    except Exception as err:
        logger.error("Could not read the daily quota for %s: %s", user_id[:8], err)
        raise HTTPException(
            status_code=503, detail="Snap a Doubt is not available right now."
        )

    remaining = DAILY_QUESTION_LIMIT - used_today
    if remaining <= 0:
        resets = _quota_resets_in(user_id)
        wait = f" Your next one unlocks in {resets['human']}." if resets else ""
        logger.info("[SNAP QUOTA] user=%s used %d/%d — refusing, next slot in %s",
                    user_id[:8], used_today, DAILY_QUESTION_LIMIT,
                    resets["human"] if resets else "n/a")
        raise HTTPException(
            status_code=429,
            detail={
                "message": (
                    f"You have used all {DAILY_QUESTION_LIMIT} of today's questions."
                    f"{wait} The allowance is rolling, so questions come back "
                    "through the day rather than all at once."
                ),
                "stage": "quota",
                "used_today": used_today,
                "daily_limit": DAILY_QUESTION_LIMIT,
                "retry_after_seconds": resets["seconds"] if resets else None,
                "resets_at": resets["at"] if resets else None,
            },
            headers={"Retry-After": str(resets["seconds"])} if resets else None,
        )

    # Never read more than the student has left — a page of 8 with 2 remaining
    # reads 2, rather than solving 8 and billing for questions over the cap.
    allowed_this_submission = min(MAX_QUESTIONS, remaining)

    submission_id = str(uuid.uuid4())

    # The photo itself is NOT kept. Once it is read, the question text and
    # options ARE the stored record — a second copy of the image is redundant
    # storage that also means a student's photographed page sits on a server
    # indefinitely for no benefit the transcript does not already provide.
    try:
        result = solve_snapped_image(image_bytes, mime, submission_id,
                                     allowed_this_submission)
    except SnapError as err:
        # Store the failure honestly against the submission, then tell the
        # client which stage failed. The photo stays so the student can see what
        # was rejected and retake it.
        # 'illegible' means the student's photo was the problem and counts
        # against their quota; 'failed' means it was ours and does not.
        student_fixable = err.remedy == REMEDY_RETAKE
        row = {
            "id": submission_id,
            "user_id": user_id,
            "submission_id": submission_id,
            "question_index": 1,
            "legible": not student_fixable,
            "legibility_note": str(err) if student_fixable else None,
            "status": "illegible" if student_fixable else "failed",
            "solved": False,
            "concept": "Unreadable photo" if student_fixable else "Unsolved question",
            "failure_reason": str(err),
        }
        try:
            _insert_doubt_rows([row])
        except Exception as db_err:
            logger.error("Failed to record failed doubt %s: %s", submission_id[:8], db_err)
        logger.warning(
            "[SNAP FAILED stage=%s] doubt=%s user=%s: %s",
            err.stage, submission_id[:8], user_id[:8], err,
        )
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(err),
                "stage": err.stage,
                "reason": err.reason,
                # What the student should DO: retake / not_photo / our_side.
                "remedy": err.remedy,
                "retake_helps": err.remedy == REMEDY_RETAKE,
                "doubt_id": submission_id,
            },
        )
    except Exception as err:
        logger.error("[SNAP UNEXPECTED] doubt=%s user=%s: %s",
                     submission_id[:8], user_id[:8], err)
        raise HTTPException(
            status_code=500, detail="Something went wrong while reading that question."
        )

    rows: List[Dict[str, Any]] = []
    question_remedies: Dict[str, str] = {}
    for question in result["questions"][:allowed_this_submission]:
        solution = question.get("solution") or {}
        withheld_reason = None
        # A failed solve reports its own cause; the question-level remedy only
        # describes how it was read.
        remedy = (question.get("solve_remedy") if question.get("solve_error")
                  else question.get("remedy")) or REMEDY_OUR_SIDE
        if not question["legible"]:
            # A diagram question was read perfectly; the photo is not at fault,
            # so it is 'failed' (ours) rather than 'illegible' (theirs).
            status = "illegible" if remedy == REMEDY_RETAKE else "failed"
        elif question.get("solve_error"):
            status = "failed"
        elif solution.get("no_consensus"):
            # Unstable across repeated solves: show the working, withhold
            # certainty.
            status = "unsure"
            withheld_reason = solution.get("consensus_note")
        elif solution.get("unmatched"):
            # Derived an answer that is not on the list: show the working,
            # withhold the answer, say why. Refusing would throw away a
            # correct derivation whenever an option was misread.
            status = "unsure"
            withheld_reason = solution.get("unmatched_note")
        elif solution.get("agrees_with_printed_answer") is False:
            # The page printed an answer key, the solver never saw it, and the
            # two disagree. One of them is wrong and we cannot tell which, so
            # the answer is withheld rather than shown as fact. The reasoning is
            # still worth reading, so the steps stay.
            status = "unsure"
            withheld_reason = (
                f"Monk worked this out as \u201c{solution.get('answer')}\u201d, but the "
                f"answer printed on the page is \u201c{solution.get('printed_answer')}\u201d. "
                "Since they disagree, Monk is not showing an answer it might have "
                "wrong \u2014 check the working below and ask in a session if unsure."
            )
            logger.warning(
                "[DOUBT UNSURE] doubt=%s printed=%r solver=%r — answer withheld",
                submission_id[:8], solution.get("printed_answer"),
                solution.get("answer"),
            )
        else:
            status = "solved"

        row_id = str(uuid.uuid4())
        question_remedies[row_id] = remedy
        rows.append({
            "id": row_id,
            "user_id": user_id,
            "submission_id": submission_id,
            "question_index": question["n"],
            "question_text": question.get("text") or None,
            # Stored separately so the detail page can render "Q: <stem>" and a
            # clean options list, instead of one run-on paragraph. `text`
            # (stem + options concatenated) is kept for search/legacy display.
            "stem": question.get("stem") or question.get("text") or None,
            "options": question.get("options") or [],
            # Normalised, not taken raw: a row whose subject reads
            # "Mathematics" is invisible to a filter matching "Maths".
            "subject": _subject_for_row(solution, question),
            # `chapter` and `concept` are what the web pages render; `steps`,
            # `answer` and `key_idea` keep the structure for the rich panel.
            "chapter": solution.get("topic") or question.get("topic"),
            "concept": _concept(solution, question),
            "question_type": question.get("question_type"),
            "printed_answer": question.get("printed_answer"),
            "option_labels": solution.get("option_labels") or [],
            "legible": question["legible"],
            "legibility_note": question.get("note"),
            # Withheld on disagreement: the working stays, the answer does not.
            "answer": None if status == "unsure" else solution.get("answer"),
            "steps": solution.get("steps") or [],
            "key_idea": solution.get("key_idea"),
            "explanation": _flatten_solution(solution, withheld=status == "unsure"),
            "solved": status == "solved",
            "status": status,
            "failure_reason": withheld_reason or question.get("solve_error"),
            "transcriber_model": result["transcriber_model"],
            "solver_model": result["solver_model"],
            "transcribe_ms": result["transcribe_ms"],
            "latency_ms": result["latency_ms"],
        })

    try:
        res = _insert_doubt_rows(rows)
    except Exception as err:
        # A missing column here means a migration has not been applied. Saying
        # so beats "Could not save that doubt", which sent me looking at the
        # pipeline when the schema was the problem.
        missing_column = "PGRST204" in str(err) or "schema cache" in str(err)
        logger.error(
            "Doubt insert failed for %s%s: %s",
            submission_id[:8],
            " (is migration 0013 applied?)" if missing_column else "",
            err,
        )
        raise HTTPException(
            status_code=503 if missing_column else 500,
            detail=("Snap a Doubt is not fully set up on this server yet."
                    if missing_column else "Could not save that doubt."),
        )

    if not res.data:
        raise HTTPException(status_code=500, detail="Could not save that doubt.")

    note = result.get("note")
    if allowed_this_submission < MAX_QUESTIONS:
        note = (note + " " if note else "") + (
            f"Only {allowed_this_submission} of today's {DAILY_QUESTION_LIMIT} "
            "questions were left, so that many were read."
        )

    return {
        "submission_id": submission_id,
        "note": note,
        "solved_count": result["solved_count"],
        # Chargeable rows, not every row. The streaming path was corrected for
        # this — "a page with one unbilled question once showed 2/50 while the
        # student was actually charged 1" — and the blocking one, which the
        # mobile client still falls back to when the stream cannot be reached,
        # kept the old arithmetic. It overstates by every unreadable or
        # unsure question on the page.
        "questions_used_today": used_today + sum(
            1 for row in rows if row["status"] in CHARGEABLE_STATUSES
        ),
        "daily_limit": DAILY_QUESTION_LIMIT,
        "questions": [
            {
                "id": row["id"],
                "question_index": row["question_index"],
                "question_text": row["question_text"],
                "stem": row["stem"],
                "options": _options_with_figures(row["options"]),
                "figure_urls": _figure_urls(row.get("figures")),
                "subject": row["subject"],
                "chapter": row["chapter"],
                "concept": row["concept"],
                "question_type": row["question_type"],
                "option_labels": row["option_labels"],
                "legible": row["legible"],
                "legibility_note": row["legibility_note"],
                "remedy": question_remedies.get(row["id"], REMEDY_OUR_SIDE),
                "retake_helps": question_remedies.get(row["id"]) == REMEDY_RETAKE,
                "answer": row["answer"],
                "steps": row["steps"],
                "key_idea": row["key_idea"],
                "explanation": row["explanation"],
                "solved": row["solved"],
                "status": row["status"],
                "failure_reason": row["failure_reason"],
            }
            for row in rows
        ],
    }


def _row_from_question(question: Dict[str, Any], user_id: str, submission_id: str,
                       meta: Dict[str, Any]) -> Dict[str, Any]:
    """One `doubts` row, and the remedy the client should act on."""
    solution = question.get("solution") or {}
    withheld_reason = None
    remedy = (question.get("solve_remedy") if question.get("solve_error")
              else question.get("remedy")) or REMEDY_OUR_SIDE

    if not question["legible"]:
        status = "illegible" if remedy == REMEDY_RETAKE else "failed"
    elif question.get("solve_error"):
        status = "failed"
    elif solution.get("no_consensus"):
        # Unstable across repeated solves: show the working, withhold certainty.
        status = "unsure"
        withheld_reason = solution.get("consensus_note")
    elif solution.get("unmatched"):
        # Derived an answer that is not on the list. Same treatment as a
        # disagreement with a printed key: show the working, withhold the
        # answer, say why.
        status = "unsure"
        withheld_reason = solution.get("unmatched_note")
    elif solution.get("agrees_with_printed_answer") is False:
        status = "unsure"
        withheld_reason = (
            f"Monk worked this out as \u201c{solution.get('answer')}\u201d, but the "
            f"answer printed on the page is \u201c{solution.get('printed_answer')}\u201d. "
            "Since they disagree, Monk is not showing an answer it might have "
            "wrong \u2014 check the working below and ask in a session if unsure."
        )
    else:
        status = "solved"

    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "submission_id": submission_id,
        "question_index": question["n"],
        "question_text": question.get("text") or None,
        "stem": question.get("stem") or question.get("text") or None,
        "options": question.get("options") or [],
        # The figures this question was printed with. Keys only — a client is
        # given signed URLs, never a key.
        "figures": question.get("figure_keys") or [],
        "subject": _subject_for_row(solution, question),
        "chapter": solution.get("topic") or question.get("topic"),
        "concept": _concept(solution, question),
        "question_type": question.get("question_type"),
        "printed_answer": question.get("printed_answer"),
        "option_labels": solution.get("option_labels") or [],
        "legible": question["legible"],
        "legibility_note": question.get("note"),
        "answer": None if status == "unsure" else solution.get("answer"),
        "steps": solution.get("steps") or [],
        "key_idea": solution.get("key_idea"),
        "explanation": _flatten_solution(solution, withheld=status == "unsure"),
        "solved": status == "solved",
        "status": status,
        "failure_reason": withheld_reason or question.get("solve_error"),
        "transcriber_model": meta.get("transcriber_model"),
        "solver_model": meta.get("solver_model"),
        "transcribe_ms": meta.get("transcribe_ms"),
        "latency_ms": meta.get("latency_ms"),
        "_remedy": remedy,
    }


@router.post("/stream")
async def snap_doubt_stream(
    file: UploadFile = File(..., description="Photo of up to 5 questions"),
    user_id: str = Depends(get_current_user_id),
):
    """POST /doubts/stream — same pipeline, delivered question by question.

    A solve takes ~25s. Waiting for a page of five meant two minutes of spinner
    before anything appeared; this sends each answer the moment it exists.
    Events: `meta`, `question` (one per question), `done`, or `error`.
    """
    mime = (file.content_type or "").lower().split(";")[0].strip()
    if mime not in ALLOWED_MIME:
        raise HTTPException(
            status_code=415,
            detail="That file type is not supported. Send a JPEG, PNG, WebP or HEIC photo.",
        )
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="That file was empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"That photo is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
        )

    used_today = _questions_used_today(user_id)
    remaining = DAILY_QUESTION_LIMIT - used_today
    if remaining <= 0:
        resets = _quota_resets_in(user_id)
        raise HTTPException(status_code=429, detail={
            "message": (
                f"You have used all {DAILY_QUESTION_LIMIT} of today's questions."
                + (f" Your next one unlocks in {resets['human']}." if resets else "")
            ),
            "stage": "quota", "used_today": used_today,
            "daily_limit": DAILY_QUESTION_LIMIT,
            "retry_after_seconds": resets["seconds"] if resets else None,
        })

    allowed = min(MAX_QUESTIONS, remaining)
    submission_id = str(uuid.uuid4())
    logger.info(
        "[SNAP REQUEST] doubt=%s user=%s STREAM upload=%.1fKB mime=%s "
        "quota %d/%d used, %d left -> reading %d",
        submission_id[:8], user_id[:8], len(image_bytes) / 1024, mime,
        used_today, DAILY_QUESTION_LIMIT, remaining, allowed,
    )
    # No upload: the photo is read (Mathpix, then gpt-4o for any diagram) and
    # then discarded. The transcript IS the record; a second copy of the image
    # adds storage cost with no benefit once the question is captured as text.

    def event(name: str, payload: Dict[str, Any]) -> str:
        return f"event: {name}\ndata: {json.dumps(payload)}\n\n"

    def stream():
        meta: Dict[str, Any] = {}
        emitted = 0
        # Rows are inserted on each "question" event, which all arrive BEFORE
        # the "summary" that carries the submission's latency — so reading it
        # off `meta` wrote NULL into every streamed row, and the streaming path
        # (the one students actually use) had no latency recorded at all. This
        # stamps each row with how long the student actually waited to see THAT
        # question answered, which is the number worth having per row anyway.
        started_at = time.time()
        try:
            for kind, item in iter_snapped_questions(image_bytes, mime,
                                                     submission_id, allowed):
                if kind == "meta":
                    meta.update(item)
                    yield event("meta", {
                        "submission_id": submission_id,
                        "question_count": item["question_count"],
                        "note": item.get("note"),
                        "daily_limit": DAILY_QUESTION_LIMIT,
                        "questions_used_today": used_today,
                    })
                elif kind == "questions_read":
                    # What was read off the photo, before any solving. Lets the
                    # page show the student their question ~20s earlier than
                    # waiting for the first solve. Carries no answer.
                    yield event("questions_read", item)
                elif kind in ("thinking", "step", "steps_reset"):
                    # Live progress while a solve runs. Steps only — never an
                    # answer, which waits for the validated "question" event.
                    yield event(kind, item)
                elif kind == "question":
                    row = _row_from_question(item, user_id, submission_id, meta)
                    row["latency_ms"] = int((time.time() - started_at) * 1000)
                    remedy = row.pop("_remedy")
                    # The DB write is on the path between the answer existing
                    # and the student seeing it, so it is timed too — a slow
                    # Supabase would otherwise look like a slow solve.
                    insert_t0 = time.time()
                    try:
                        _insert_doubt_rows([row])
                        logger.info(
                            "[SNAP DB] doubt=%s q%s row=%s insert_ms=%d status=%s",
                            submission_id[:8], row["question_index"], row["id"][:8],
                            int((time.time() - insert_t0) * 1000), row["status"],
                        )
                    except Exception as err:
                        logger.error("Doubt insert failed for %s (after %dms): %s",
                                     submission_id[:8],
                                     int((time.time() - insert_t0) * 1000), err)
                    # Count against the quota exactly what _questions_used_today
                    # counts, or the number on screen is not the real one: a
                    # page with one unbilled question once showed 2/50 while the
                    # student was actually charged 1.
                    if row["status"] in CHARGEABLE_STATUSES:
                        emitted += 1
                    yield event("question", {
                        **{k: row[k] for k in (
                            "id", "question_index", "question_text", "stem",
                            "subject", "chapter", "concept",
                            "question_type", "legible", "legibility_note",
                            "answer", "steps", "key_idea", "option_labels",
                            "status", "failure_reason")},
                        "options": _options_with_figures(row["options"]),
                        "figure_urls": _figure_urls(row.get("figures")),
                        "remedy": remedy,
                        "retake_helps": remedy == REMEDY_RETAKE,
                    })
                elif kind == "summary":
                    meta.update(item)
        except SnapError as err:
            # Nothing could be read at all: record it and say which stage failed.
            student_fixable = err.remedy == REMEDY_RETAKE
            try:
                supabase.table("doubts").insert([{
                    "id": submission_id, "user_id": user_id,
                    "submission_id": submission_id, "question_index": 1,
                    "legible": not student_fixable,
                    "legibility_note": str(err) if student_fixable else None,
                    "status": "illegible" if student_fixable else "failed",
                    "solved": False, "failure_reason": str(err),
                    "concept": "Unreadable photo" if student_fixable else "Unsolved question",
                }]).execute()
            except Exception as db_err:
                logger.error("Failed to record failed doubt: %s", db_err)
            logger.warning("[SNAP FAILED stage=%s reason=%s remedy=%s] doubt=%s "
                           "after %dms: %s",
                           err.stage, err.reason, err.remedy, submission_id[:8],
                           int((time.time() - started_at) * 1000), err)
            yield event("error", {
                "message": str(err), "stage": err.stage, "reason": err.reason,
                "remedy": err.remedy, "retake_helps": err.remedy == REMEDY_RETAKE,
                "doubt_id": submission_id,
            })
            return
        except Exception as err:
            # exc_info: an unexpected error is the one case where the traceback
            # is the whole story, and it was being thrown away.
            logger.error("[SNAP UNEXPECTED] doubt=%s after %dms: %s",
                         submission_id[:8],
                         int((time.time() - started_at) * 1000), err,
                         exc_info=True)
            yield event("error", {
                "message": "Something went wrong while reading that question.",
                "stage": "unknown", "remedy": REMEDY_OUR_SIDE,
                "retake_helps": False,
            })
            return

        total_ms = int((time.time() - started_at) * 1000)
        logger.info(
            "[SNAP REQUEST] doubt=%s user=%s DONE total_ms=%d solved=%d "
            "charged=%d quota_now=%d/%d",
            submission_id[:8], user_id[:8], total_ms,
            meta.get("solved_count", 0), emitted, used_today + emitted,
            DAILY_QUESTION_LIMIT,
        )
        yield event("done", {
            "submission_id": submission_id,
            "solved_count": meta.get("solved_count", 0),
            "questions_used_today": used_today + emitted,
            "daily_limit": DAILY_QUESTION_LIMIT,
            "total_ms": total_ms,
        })

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.get("")
def list_doubts(
    q: Optional[str] = Query(None, description="Search the transcribed questions"),
    subject: Optional[str] = Query(None, description="Subject filter; omit or 'all' for everything"),
    limit: int = Query(60, ge=1, le=200),
    user_id: str = Depends(get_current_user_id),
):
    """GET /doubts — the snap history, newest first."""
    query = supabase.table("doubts").select(LIST_COLUMNS).eq("user_id", user_id)

    # Accept whatever spelling the caller sends -- "Math", "Maths", "mathematics"
    # -- and match on the one the column stores.
    if subject and subject.lower() != "all":
        wanted = canonical_subject(subject)
        if wanted is None:
            # An off-syllabus / unrecognised filter matches the rows that have
            # no subject rather than silently returning the whole list.
            query = query.is_("subject", "null")
        else:
            query = query.eq("subject", wanted)
    if q and q.strip():
        term = q.strip().replace(",", " ")
        query = query.or_(
            f"question_text.ilike.%{term}%,concept.ilike.%{term}%,chapter.ilike.%{term}%"
        )

    try:
        res = query.order("created_at", desc=True).limit(limit).execute()
        rows: List[Dict[str, Any]] = res.data or []

        all_subjects_res = (
            supabase.table("doubts").select("subject").eq("user_id", user_id).execute()
        )
    except Exception as err:
        # Most likely cause: migration 0012 has not been applied, or it ran
        # against the old `doubts` stub and skipped the new columns.
        logger.error("Could not read doubts (is migration 0012 applied?): %s", err)
        raise HTTPException(
            status_code=503, detail="My Doubts is not available right now."
        )

    # The chips the student sees. Their exam's syllabus comes first and always
    # shows, so a JEE student gets Physics / Chemistry / Math whether or not
    # they have snapped one yet; anything they HAVE snapped from outside it is
    # appended rather than hidden, because a doubt you cannot find is worse
    # than a chip you did not expect. Nothing is refused for being off-syllabus
    # -- the subject is a best-effort label from a model, and one real
    # stereochemistry question came back tagged Biology.
    try:
        prof = (supabase.table("profiles").select("target_exam")
                .eq("id", user_id).limit(1).execute().data)
    except Exception:
        prof = None
    exam = exam_scope.resolve_exam(prof[0] if prof else None)
    on_syllabus = list(exam_scope.subjects_for(exam))
    snapped = {r.get("subject") for r in (all_subjects_res.data or []) if r.get("subject")}
    extra = sorted(s for s in snapped if s not in on_syllabus)

    subjects = [
        {"key": s,
         "label": exam_scope.DISPLAY_LABEL.get(s, s.title()),
         "on_syllabus": s in on_syllabus}
        for s in on_syllabus + extra
    ]

    return {
        # `subject` stays the stored key so filtering round-trips; the label is
        # what the page prints, and `on_syllabus` lets it mark a doubt that is
        # not on this student's exam without hiding or refusing it.
        "doubts": [{
            **row,
            "scrap": _scrap(row.get("question_text")),
            "subject_label": exam_scope.DISPLAY_LABEL.get(row.get("subject") or ""),
            "on_syllabus": (row.get("subject") in on_syllabus
                            if row.get("subject") else None),
        } for row in rows],
        "count": len(rows),
        "subjects": subjects,
        "exam": exam,
    }


@router.get("/{doubt_id}")
def get_doubt(doubt_id: str, user_id: str = Depends(get_current_user_id)):
    """GET /doubts/{id} — the question, a signed photo URL, and the solution."""
    try:
        res = (
            supabase.table("doubts")
            .select(DETAIL_COLUMNS)
            .eq("id", doubt_id)
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as err:
        logger.error("Could not read doubts (is migration 0012 applied?): %s", err)
        raise HTTPException(
            status_code=503, detail="My Doubts is not available right now."
        )

    if not res.data:
        raise HTTPException(status_code=404, detail="Doubt not found")

    doubt = res.data[0]
    # The key never leaves the server; the client gets a short-lived signed URL.
    doubt["image_url"] = signed_url(doubt.pop("image_key", None))
    doubt["options"] = _options_with_figures(doubt.get("options"))
    doubt["figure_urls"] = _figure_urls(doubt.pop("figures", None))

    report = (
        supabase.table("doubt_reports")
        .select("id, comment, created_at")
        .eq("doubt_id", doubt_id)
        .eq("user_id", user_id)
        .execute()
    )
    doubt["reported"] = bool(report.data)
    return doubt


class FollowUpTurn(BaseModel):
    role: str
    content: str


class FollowUpRequest(BaseModel):
    question: str
    """The exchange so far. Held by the CLIENT, not by us.

    A follow-up lives as long as the student is looking at the solution and no
    longer. Persisting it would mean a table, a retention decision and a delete
    path for a conversation nobody asked to keep — so the phone carries it, and
    it goes when the screen does.
    """
    history: List[FollowUpTurn] = []


@router.post("/{doubt_id}/ask")
def ask_about_doubt(doubt_id: str, body: FollowUpRequest,
                    user_id: str = Depends(get_current_user_id)):
    """POST /doubts/{id}/ask — a question about a solution already on screen.

    Streams the reply a token at a time (`event: token`), because the student
    is mid-conversation and watching: first words inside a second reads as an
    answer arriving, four seconds of nothing reads as a hang.

    The solution is loaded HERE, from the row, rather than accepted from the
    request. The phone already has it, so sending it up would be simpler — and
    would let any caller claim any question and any answer and have the model
    explain it as fact.
    """
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Ask something first.")

    try:
        res = (
            supabase.table("doubts")
            .select(DETAIL_COLUMNS)
            .eq("id", doubt_id)
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as err:
        logger.error("Could not read doubt %s for follow-up: %s", doubt_id[:8], err)
        raise HTTPException(status_code=503, detail="That is not available right now.")
    if not res.data:
        raise HTTPException(status_code=404, detail="Doubt not found")
    doubt = res.data[0]

    def event(name: str, payload: Dict[str, Any]) -> str:
        return f"event: {name}\ndata: {json.dumps(payload)}\n\n"

    def stream():
        started = time.time()
        chars = 0
        logger.info("[FOLLOWUP] doubt=%s user=%s asked %r (%d prior turns)",
                    doubt_id[:8], user_id[:8], question[:80], len(body.history))
        try:
            for piece in stream_followup(
                doubt, question,
                [{"role": t.role, "content": t.content} for t in body.history],
            ):
                chars += len(piece)
                yield event("token", {"text": piece})
        except Exception as err:
            logger.error("[FOLLOWUP] doubt=%s failed after %dms: %s",
                         doubt_id[:8], int((time.time() - started) * 1000), err,
                         exc_info=True)
            yield event("error", {
                "message": "Monk could not answer that just now. Try again in a moment.",
            })
            return
        logger.info("[FOLLOWUP] doubt=%s done in %dms, %d chars",
                    doubt_id[:8], int((time.time() - started) * 1000), chars)
        yield event("done", {"total_ms": int((time.time() - started) * 1000)})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.post("/{doubt_id}/report", status_code=200)
def report_doubt(
    doubt_id: str,
    payload: Optional[ReportRequest] = None,
    user_id: str = Depends(get_current_user_id),
):
    """POST /doubts/{id}/report — the student says this answer is wrong.

    Read-only for now; it exists so wrong answers are countable rather than
    invisible. Reporting twice updates the comment instead of erroring.
    """
    existing_doubt = (
        supabase.table("doubts")
        .select("id")
        .eq("id", doubt_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not existing_doubt.data:
        raise HTTPException(status_code=404, detail="Doubt not found")

    comment = (payload.comment if payload else None) or None
    existing_report = (
        supabase.table("doubt_reports")
        .select("id")
        .eq("doubt_id", doubt_id)
        .eq("user_id", user_id)
        .execute()
    )

    try:
        if existing_report.data:
            supabase.table("doubt_reports").update({"comment": comment}).eq(
                "id", existing_report.data[0]["id"]
            ).execute()
        else:
            supabase.table("doubt_reports").insert([{
                "doubt_id": doubt_id,
                "user_id": user_id,
                "comment": comment,
            }]).execute()
    except Exception as err:
        logger.error("Could not record report for %s: %s", doubt_id[:8], err)
        raise HTTPException(status_code=500, detail="Could not record that report.")

    logger.warning("[DOUBT REPORTED] id=%s user=%s", doubt_id[:8], user_id[:8])
    return {"reported": True}


@router.delete("/{doubt_id}", status_code=204)
def delete_doubt(doubt_id: str, user_id: str = Depends(get_current_user_id)):
    """DELETE /doubts/{id} — drops the row, and the photo when nothing else uses it."""
    existing = (
        supabase.table("doubts")
        .select("id, image_key, submission_id, options, figures")
        .eq("id", doubt_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Doubt not found")

    row = existing.data[0]
    supabase.table("doubts").delete().eq("id", doubt_id).eq("user_id", user_id).execute()

    # Two questions can share one photo. Only remove the object once the last
    # row referencing it is gone.
    siblings = (
        supabase.table("doubts")
        .select("id")
        .eq("submission_id", row.get("submission_id"))
        .eq("user_id", user_id)
        .execute()
    )
    if not siblings.data:
        delete_image(row.get("image_key"))
        # The option figures belong to this question and nothing else refers
        # to them, so they go when it does.
        for option in row.get("options") or []:
            if isinstance(option, dict) and option.get("figure_key"):
                delete_image(option["figure_key"])
        for key in row.get("figures") or []:
            if isinstance(key, str):
                delete_image(key)
    return None
