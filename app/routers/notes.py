"""Notes — a Drona session's board, kept by the student.

The board a session produced is backed up with the session itself; a note is the
student's decision to keep it. Writes go through FastAPI only (Rule 9), and
every read is scoped to the caller's user_id rather than trusting RLS alone,
because this service holds the service role key.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import get_current_user_id
from app.db import supabase
from app.drona.note_assembly import (
    NoteAssemblyError,
    assemble_session_note,
    build_mistakes_section,
    structure_note_content,
    weave_mistakes_into_content,
)

logger = logging.getLogger("notes")

router = APIRouter(prefix="/notes", tags=["notes"])

# Columns for the list view. board_items is deliberately excluded — a shelf of
# 60 notes should not ship 60 full boards to render six-line cards.
LIST_COLUMNS = (
    "id, session_id, chapter_id, subject, chapter, concept, "
    "segments_covered, total_segments, item_count, created_at"
)
DETAIL_COLUMNS = LIST_COLUMNS + ", content, board_items, session_started_at"


class SaveNoteRequest(BaseModel):
    session_id: str


def _preview(note: Dict[str, Any]) -> str:
    """The one-line subtitle on a note card."""
    covered = note.get("segments_covered") or 0
    total = note.get("total_segments") or 0
    items = note.get("item_count") or 0
    parts = [f"{items} board item{'s' if items != 1 else ''}"]
    if total:
        parts.append(f"{covered} of {total} parts")
    return " · ".join(parts)


@router.post("", status_code=201)
def save_note(payload: SaveNoteRequest, user_id: str = Depends(get_current_user_id)):
    """POST /notes — assembles the session's board and keeps it.

    Idempotent per session: saving the same session again refreshes the note
    rather than creating a second copy of one class.
    """
    try:
        note = assemble_session_note(payload.session_id, user_id)
    except NoteAssemblyError as err:
        # A note that cannot be assembled is a 422 with the reason, not a 200
        # with an empty board.
        logger.warning("Note assembly refused for session %s: %s", payload.session_id, err)
        raise HTTPException(status_code=422, detail=str(err))
    except Exception as err:
        logger.error("Note assembly failed for session %s: %s", payload.session_id, err)
        raise HTTPException(status_code=500, detail="Could not assemble this session's board.")

    # Reorganise the raw board transcript into revision-ready notes. Best
    # effort by design: on any failure the note saves with the flat board,
    # which is always honest — just less organised.
    structured = structure_note_content(note)
    if structured:
        note["content"] = structured

    # Personal rework section from this session's graded answers. Placed with
    # the class material (before self-study) since these are answers the
    # student gave in class. Best effort like the structuring pass — and it
    # runs AFTER it, so the student's quoted answers are never fed through a
    # model rewrite. Every student on the same topic gets the same QUICK
    # REVISION; this section is the only part of the note that is theirs.
    mistakes = build_mistakes_section(payload.session_id)
    if mistakes:
        note["content"] = weave_mistakes_into_content(note["content"], mistakes)

    existing = (
        supabase.table("notes")
        .select("id")
        .eq("session_id", payload.session_id)
        .eq("user_id", user_id)
        .execute()
    )

    try:
        if existing.data:
            note_id = existing.data[0]["id"]
            res = (
                supabase.table("notes")
                .update(note)
                .eq("id", note_id)
                .eq("user_id", user_id)
                .execute()
            )
            already_saved = True
        else:
            res = supabase.table("notes").insert([note]).execute()
            already_saved = False
    except Exception as err:
        logger.error("Note write failed for session %s: %s", payload.session_id, err)
        raise HTTPException(status_code=500, detail="Could not save this note.")

    if not res.data:
        raise HTTPException(status_code=500, detail="Could not save this note.")

    saved = res.data[0]
    return {
        "id": saved["id"],
        "concept": saved.get("concept"),
        "already_saved": already_saved,
        "item_count": saved.get("item_count"),
        "segments_covered": saved.get("segments_covered"),
        "total_segments": saved.get("total_segments"),
    }


@router.get("")
def list_notes(
    q: Optional[str] = Query(None, description="Search by concept or chapter"),
    subject: Optional[str] = Query(None, description="Subject filter; omit or 'all' for everything"),
    limit: int = Query(60, ge=1, le=200),
    user_id: str = Depends(get_current_user_id),
):
    """GET /notes — the shelf, newest first."""
    query = supabase.table("notes").select(LIST_COLUMNS).eq("user_id", user_id)

    if subject and subject.lower() != "all":
        query = query.eq("subject", subject)
    if q and q.strip():
        term = q.strip().replace(",", " ")
        query = query.or_(
            f"concept.ilike.%{term}%,chapter.ilike.%{term}%,content.ilike.%{term}%"
        )

    try:
        res = query.order("created_at", desc=True).limit(limit).execute()
        rows: List[Dict[str, Any]] = res.data or []

        # Subject tabs are built from what the student actually has, so a tab
        # never leads to an empty shelf. Computed over all their notes, not the
        # filtered page.
        all_subjects_res = (
            supabase.table("notes").select("subject").eq("user_id", user_id).execute()
        )
    except Exception as err:
        # Most likely cause: migration 0012 has not been applied. A bare 500
        # tells the student nothing and hides the reason from the logs.
        logger.error("Could not read notes (is migration 0012 applied?): %s", err)
        raise HTTPException(
            status_code=503,
            detail="Notes are not available right now.",
        )

    subjects = sorted({
        (r.get("subject") or "").strip()
        for r in (all_subjects_res.data or [])
        if (r.get("subject") or "").strip()
    })

    return {
        "notes": [{**row, "preview": _preview(row)} for row in rows],
        "count": len(rows),
        "subjects": subjects,
    }


@router.get("/{note_id}")
def get_note(note_id: str, user_id: str = Depends(get_current_user_id)):
    """GET /notes/{id} — the full saved board."""
    try:
        res = (
            supabase.table("notes")
            .select(DETAIL_COLUMNS)
            .eq("id", note_id)
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as err:
        logger.error("Could not read notes (is migration 0012 applied?): %s", err)
        raise HTTPException(status_code=503, detail="Notes are not available right now.")

    if not res.data:
        raise HTTPException(status_code=404, detail="Note not found")
    return res.data[0]


@router.delete("/{note_id}", status_code=204)
def delete_note(note_id: str, user_id: str = Depends(get_current_user_id)):
    """DELETE /notes/{id} — the student drops a note from their shelf."""
    existing = (
        supabase.table("notes")
        .select("id")
        .eq("id", note_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Note not found")

    supabase.table("notes").delete().eq("id", note_id).eq("user_id", user_id).execute()
    return None
