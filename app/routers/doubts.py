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
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.auth import get_current_user_id
from app.db import supabase
from app.snap import (
    ALLOWED_MIME,
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
        result = solve_snapped_image(image_bytes, mime, submission_id)
    except SnapError as err:
        # Store the failure honestly against the submission, then tell the
        # client which stage failed. The photo stays so the student can see what
        # was rejected and retake it.
        row = {
            "id": submission_id,
            "user_id": user_id,
            "submission_id": submission_id,
            "question_index": 1,
            "image_key": key,
            "legible": err.stage != "transcribe",
            "legibility_note": str(err) if err.stage == "transcribe" else None,
            "status": "illegible" if err.stage == "transcribe" else "failed",
            "solved": False,
            "concept": "Unreadable photo" if err.stage == "transcribe" else "Unsolved question",
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
            detail={"message": str(err), "stage": err.stage, "doubt_id": submission_id},
        )
    except Exception as err:
        logger.error("[SNAP UNEXPECTED] doubt=%s user=%s: %s",
                     submission_id[:8], user_id[:8], err)
        raise HTTPException(
            status_code=500, detail="Something went wrong while reading that question."
        )

    rows: List[Dict[str, Any]] = []
    for question in result["questions"][:MAX_QUESTIONS]:
        solution = question.get("solution") or {}
        withheld_reason = None
        if not question["legible"]:
            status = "illegible"
        elif question.get("solve_error"):
            status = "failed"
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

        rows.append({
            "id": str(uuid.uuid4()),
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

    return {
        "submission_id": submission_id,
        "note": result.get("note"),
        "solved_count": result["solved_count"],
        "questions": [
            {
                "id": row["id"],
                "question_index": row["question_index"],
                "question_text": row["question_text"],
                "subject": row["subject"],
                "chapter": row["chapter"],
                "concept": row["concept"],
                "legible": row["legible"],
                "legibility_note": row["legibility_note"],
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
