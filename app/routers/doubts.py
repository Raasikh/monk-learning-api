"""Snap a Doubt (write) and My Doubts (read).

A submission is: photo in → R2 → transcribe → solve each legible question →
one row per question. The row holds the R2 object KEY; the photo is only ever
handed back through a short-lived presigned URL.

Nothing fails silently. An illegible question is stored as 'illegible' with what
the transcriber said was unclear, a failed solve is stored as 'failed' with its
reason, and both are reported to the client with the stage that failed.
"""
import logging
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
    REMEDY_NOT_PHOTO,
    REMEDY_OUR_SIDE,
    REMEDY_RETAKE,
    MAX_IMAGE_BYTES,
    MAX_QUESTIONS,
    SnapError,
    solve_snapped_image,
)
from app.storage_r2 import (
    R2NotConfigured,
    delete_image,
    object_key,
    signed_url,
    upload_image,
)

logger = logging.getLogger("doubts")

router = APIRouter(prefix="/doubts", tags=["doubts"])

LIST_COLUMNS = (
    "id, submission_id, question_index, question_text, subject, chapter, concept, "
    "question_type, legible, legibility_note, answer, key_idea, option_labels, "
    "solved, status, failure_reason, created_at"
)
DETAIL_COLUMNS = LIST_COLUMNS + ", explanation, steps, image_key"

EXT_BY_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
}


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


def _questions_used_today(user_id: str) -> int:
    """Questions this student has had read in the last rolling 24 hours.

    Counts answers delivered and photos we could not read, because both are
    about the student's own input and both cost an OCR read. Does NOT count
    'failed' — that is where the page was read fine and we still could not
    answer, or the question needed a diagram. Charging a student for our
    inability to solve a question they photographed perfectly is not a quota,
    it is a penalty.
    """
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    res = (
        supabase.table("doubts")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .gte("created_at", since)
        .in_("status", ["solved", "unsure", "illegible"])
        .execute()
    )
    return res.count if res.count is not None else len(res.data or [])


def _scrap(question_text: Optional[str]) -> str:
    """The few words shown on the little notepad thumbnail in the list."""
    words = (question_text or "").split()
    return " ".join(words[:7]) + ("…" if len(words) > 7 else "")


@router.post("", status_code=201)
async def snap_doubt(
    file: UploadFile = File(..., description="Photo of up to 2 questions"),
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
    key = object_key(user_id, submission_id, EXT_BY_MIME.get(mime, "jpg"))

    # Upload first. A photo we could not keep is not a doubt we should solve —
    # the student would get an explanation attached to nothing.
    try:
        upload_image(key, image_bytes, mime)
    except R2NotConfigured as err:
        logger.error("[SNAP] R2 not configured: %s", err)
        raise HTTPException(
            status_code=503,
            detail="Snap a Doubt is not available right now.",
        )
    except Exception as err:
        logger.error("[SNAP] R2 upload failed for user %s: %s", user_id[:8], err)
        raise HTTPException(status_code=502, detail="Could not save that photo. Try again.")

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
            "image_key": key,
            "legible": not student_fixable,
            "legibility_note": str(err) if student_fixable else None,
            "status": "illegible" if student_fixable else "failed",
            "solved": False,
            "concept": "Unreadable photo" if student_fixable else "Unsolved question",
            "failure_reason": str(err),
        }
        try:
            supabase.table("doubts").insert([row]).execute()
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
            "image_key": key,
            "question_text": question.get("text") or None,
            "subject": solution.get("subject") or (
                question.get("subject") if question.get("subject") != "unknown" else None
            ),
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
        res = supabase.table("doubts").insert(rows).execute()
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
        "questions_used_today": used_today + len(rows),
        "daily_limit": DAILY_QUESTION_LIMIT,
        "questions": [
            {
                "id": row["id"],
                "question_index": row["question_index"],
                "question_text": row["question_text"],
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
                       image_key: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """One `doubts` row, and the remedy the client should act on."""
    solution = question.get("solution") or {}
    withheld_reason = None
    remedy = (question.get("solve_remedy") if question.get("solve_error")
              else question.get("remedy")) or REMEDY_OUR_SIDE

    if not question["legible"]:
        status = "illegible" if remedy == REMEDY_RETAKE else "failed"
    elif question.get("solve_error"):
        status = "failed"
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
        "image_key": image_key,
        "question_text": question.get("text") or None,
        "subject": solution.get("subject") or (
            question.get("subject") if question.get("subject") != "unknown" else None
        ),
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
    key = object_key(user_id, submission_id, EXT_BY_MIME.get(mime, "jpg"))

    try:
        upload_image(key, image_bytes, mime)
    except R2NotConfigured:
        raise HTTPException(status_code=503, detail="Snap a Doubt is not available right now.")
    except Exception as err:
        logger.error("[SNAP] R2 upload failed for %s: %s", user_id[:8], err)
        raise HTTPException(status_code=502, detail="Could not save that photo. Try again.")

    def event(name: str, payload: Dict[str, Any]) -> str:
        return f"event: {name}\ndata: {json.dumps(payload)}\n\n"

    def stream():
        meta: Dict[str, Any] = {}
        emitted = 0
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
                elif kind == "question":
                    row = _row_from_question(item, user_id, submission_id, key, meta)
                    remedy = row.pop("_remedy")
                    try:
                        supabase.table("doubts").insert([row]).execute()
                    except Exception as err:
                        logger.error("Doubt insert failed for %s: %s",
                                     submission_id[:8], err)
                    emitted += 1
                    yield event("question", {
                        **{k: row[k] for k in (
                            "id", "question_index", "question_text", "subject",
                            "chapter", "concept", "question_type", "legible",
                            "legibility_note", "answer", "steps", "key_idea",
                            "option_labels", "status", "failure_reason")},
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
                    "image_key": key, "legible": not student_fixable,
                    "legibility_note": str(err) if student_fixable else None,
                    "status": "illegible" if student_fixable else "failed",
                    "solved": False, "failure_reason": str(err),
                    "concept": "Unreadable photo" if student_fixable else "Unsolved question",
                }]).execute()
            except Exception as db_err:
                logger.error("Failed to record failed doubt: %s", db_err)
            logger.warning("[SNAP FAILED stage=%s] doubt=%s: %s",
                           err.stage, submission_id[:8], err)
            yield event("error", {
                "message": str(err), "stage": err.stage, "reason": err.reason,
                "remedy": err.remedy, "retake_helps": err.remedy == REMEDY_RETAKE,
                "doubt_id": submission_id,
            })
            return
        except Exception as err:
            logger.error("[SNAP UNEXPECTED] doubt=%s: %s", submission_id[:8], err)
            yield event("error", {
                "message": "Something went wrong while reading that question.",
                "stage": "unknown", "remedy": REMEDY_OUR_SIDE,
                "retake_helps": False,
            })
            return

        yield event("done", {
            "submission_id": submission_id,
            "solved_count": meta.get("solved_count", 0),
            "questions_used_today": used_today + emitted,
            "daily_limit": DAILY_QUESTION_LIMIT,
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

    if subject and subject.lower() != "all":
        query = query.eq("subject", subject)
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

    subjects = sorted({
        (r.get("subject") or "").strip()
        for r in (all_subjects_res.data or [])
        if (r.get("subject") or "").strip()
    })

    return {
        "doubts": [{**row, "scrap": _scrap(row.get("question_text"))} for row in rows],
        "count": len(rows),
        "subjects": subjects,
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

    report = (
        supabase.table("doubt_reports")
        .select("id, comment, created_at")
        .eq("doubt_id", doubt_id)
        .eq("user_id", user_id)
        .execute()
    )
    doubt["reported"] = bool(report.data)
    return doubt


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
        .select("id, image_key, submission_id")
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
    return None
