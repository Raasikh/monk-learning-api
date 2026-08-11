import json
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from app.auth import get_current_user_id
from app.db import supabase
from app.drona.scoping import scope_student_session
from app.drona.tutor import process_tutor_turn_stream
from app.drona.persona import (
    SCOPING_PROMPT,
    copy_for,
    normalize_language,
    normalize_voice,
    tutor_name,
)

logger = logging.getLogger("drona.router")

router = APIRouter(prefix="/drona", tags=["drona"])

@router.get("/catalogue")
def get_catalogue(user_id: str = Depends(get_current_user_id)):
    """GET /drona/catalogue — returns subject groups, chapters, and subtopics from subtopic_index."""
    # Fetch chapters from DB
    chap_res = supabase.table("chapters").select("id, name, subject, class_level").execute()
    chapters_data = chap_res.data or []

    # Fetch subtopics from subtopic_index (canonical scoping unit)
    sub_res = supabase.table("subtopic_index").select("id, chapter_id, subtopic").execute()
    sub_data = sub_res.data or []

    # Map subtopics by chapter_id
    subtopics_by_chap: Dict[str, List[Dict[str, Any]]] = {}
    for s in sub_data:
        cid = s["chapter_id"]
        if cid not in subtopics_by_chap:
            subtopics_by_chap[cid] = []
        subtopics_by_chap[cid].append({
            "id": s["id"],
            "name": s["subtopic"],
            "grounding_status": "grounded"
        })

    # Group chapters by subject
    subjects_map: Dict[str, List[Dict[str, Any]]] = {}
    for c in chapters_data:
        subj = c.get("subject", "General Physics")
        if subj not in subjects_map:
            subjects_map[subj] = []
        
        cid = c["id"]
        c_name = c["name"]
        subs = subtopics_by_chap.get(cid, [])
        if not subs:
            subs = [{"id": f"{cid}-sec1", "name": "General Overview", "grounding_status": "sections_only"}]

        subjects_map[subj].append({
            "id": cid,
            "name": c_name,
            "class_level": c.get("class_level"),
            "subtopics": subs
        })

    catalogue = []
    for subj_name, chaps in subjects_map.items():
        catalogue.append({
            "subject": subj_name,
            "chapters": chaps
        })

    return catalogue

@router.post("/topic/check")
def check_topic_endpoint(payload: Dict[str, Any], user_id: str = Depends(get_current_user_id)):
    """POST /drona/topic/check — validates a topic BEFORE any session is created.

    Lets the UI show a loading card and then either open the lesson or say
    "that's in Gravitation" with a link, instead of dropping the student into a
    session that was never going to work. Creates no rows.
    """
    from app.drona.topic_router import route_topic
    chapter_id = payload.get("chapter_id") or None
    if chapter_id and len(str(chapter_id)) != 36:
        chapter_id = None  # 'free_text' and friends are not chapter ids
    try:
        return route_topic(payload.get("utterance", ""), chapter_id)
    except Exception as e:
        logger.error(f"Topic check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/session/start")
def start_session_endpoint(payload: Dict[str, Any], user_id: str = Depends(get_current_user_id)):
    """POST /drona/session/start — initializes session and returns initial scoping speech."""
    chapter_id = payload.get("chapter_id", "custom")
    # Both axes are student-selectable and arrive from the picker. Normalize
    # rather than trust: `language` is CHECK-constrained in the DB, and an
    # unknown `voice` would leave the tutor with no persona at all.
    language = normalize_language(payload.get("language"))
    voice = normalize_voice(payload.get("voice"))

    valid_chap_id = None
    chapter_name = "this topic"

    if len(chapter_id) == 36:
        chap_data = supabase.table("chapters").select("id, name, subject, class_level").eq("id", chapter_id).execute()
        if chap_data.data:
            c = chap_data.data[0]
            valid_chap_id = c["id"]
            subj = (c.get("subject") or "").capitalize()
            cls = c.get("class_level")
            chapter_name = f"{c['name']}, Class {cls} {subj}" if cls and subj else c['name']
        else:
            sub_res = supabase.table("subtopic_index").select("chapter_id, subtopic").eq("id", chapter_id).execute()
            if sub_res.data:
                valid_chap_id = sub_res.data[0]["chapter_id"]
                chapter_name = sub_res.data[0]["subtopic"]

    session_row = {
        "user_id": user_id,
        "chapter_id": valid_chap_id,
        "mode": "chapter" if valid_chap_id else "free_text",
        "language": language,
        "tutor_voice": voice,
        "phase": "scoping",
        "prompt_version": "v1.0"
    }

    try:
        sess_res = supabase.table("drona_sessions").insert([session_row]).execute()
    except Exception as insert_err:
        # migrations/0011 adds drona_sessions.tutor_voice. If it has not been
        # applied yet, fall back to the pre-0011 shape so sessions still start —
        # but say so loudly. Silently degrading is how 0007 and 0008 went
        # unnoticed for days.
        if "tutor_voice" not in str(insert_err):
            raise
        logger.error(
            "❌ [MIGRATION 0011 NOT APPLIED] drona_sessions.tutor_voice is missing; "
            "falling back to the default '%s' persona for this session. Apply "
            "migrations/0011_drona_tutor_voice.sql — the student's tutor choice is "
            "being ignored until you do.",
            voice,
        )
        session_row.pop("tutor_voice")
        sess_res = supabase.table("drona_sessions").insert([session_row]).execute()

    if not sess_res.data:
        raise HTTPException(status_code=500, detail="Failed to create Drona session")

    session_id = sess_res.data[0]["id"]
    confirmation_speech = copy_for(SCOPING_PROMPT, language, chapter=chapter_name)

    return {
        "session_id": session_id,
        "phase": "scoping",
        "speech": confirmation_speech,
        "language": language,
        "tutor_voice": voice,
        "tutor_name": tutor_name(voice)
    }

@router.post("/session/{session_id}/scope")
def scope_session_endpoint(session_id: str, payload: Dict[str, Any], user_id: str = Depends(get_current_user_id)):
    """POST /drona/session/{session_id}/scope — resolves subtopic and triggers planner service."""
    utterance = payload.get("utterance", "")
    try:
        return scope_student_session(session_id, user_id, utterance)
    except Exception as e:
        logger.error(f"Scoping endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/session/{session_id}/turn")
async def turn_session_endpoint(session_id: str, payload: Dict[str, Any], user_id: str = Depends(get_current_user_id)):
    """POST /drona/session/{session_id}/turn — streams SSE events (`speech`, `board`, `meta`, `state`, `done`)."""
    logger.warning(
        f"🚨 [DUAL TRANSPORT GUARD WARNING] POST /drona/session/{session_id}/turn called! "
        f"Frontend must use WebSocket /drona/session/{session_id}/live exclusively for live turns."
    )
    utterance = payload.get("utterance")
    turn_type = payload.get("turn_type", "answer")

    return StreamingResponse(
        process_tutor_turn_stream(session_id, user_id, utterance, turn_type),
        media_type="text/event-stream"
    )

@router.post("/session/{session_id}/end")
def end_session_endpoint(session_id: str, user_id: str = Depends(get_current_user_id)):
    """POST /drona/session/{session_id}/end — closes session and returns summary."""
    supabase.table("drona_sessions").update({
        "phase": "complete",
        "completed_at": "now()"
    }).eq("id", session_id).execute()

    # Load session & plan data for real summary
    sess_res = supabase.table("drona_sessions").select(
        "plan_id, current_segment, segments_completed, chapter_id, created_at"
    ).eq("id", session_id).execute()
    session_row = sess_res.data[0] if sess_res.data else {}
    plan_id = session_row.get("plan_id")

    # Real session length: created_at -> now. The summary card used to show a
    # hardcoded "~10m" for every session regardless of length.
    duration_minutes = 0
    try:
        from datetime import datetime, timezone
        started = datetime.fromisoformat(str(session_row.get("created_at", "")).replace("Z", "+00:00"))
        duration_minutes = max(1, round((datetime.now(timezone.utc) - started).total_seconds() / 60))
    except Exception:
        pass

    # Checkpoint questions actually ANSWERED (graded turns). The summary card
    # used to display the misconception count under this label, so a clean
    # session always read "0 checkpoint questions".
    questions_answered = 0
    try:
        graded = supabase.table("drona_turns").select("grade").eq("session_id", session_id).execute()
        questions_answered = sum(1 for t in (graded.data or []) if t.get("grade") in ("correct", "partial", "incorrect"))
    except Exception:
        pass

    chapter_name = None
    if session_row.get("chapter_id"):
        try:
            ch_res = supabase.table("chapters").select("name").eq("id", session_row["chapter_id"]).execute()
            chapter_name = ch_res.data[0]["name"] if ch_res.data else None
        except Exception:
            pass

    summary_points = []
    if plan_id:
        p_res = supabase.table("lesson_plans").select("plan_json").eq("id", plan_id).execute()
        if p_res.data:
            pj = p_res.data[0].get("plan_json") or {}
            all_points = pj.get("wrapup_points") or [s.get("objective") for s in pj.get("segments", []) if s.get("objective")]
            # Summarise only what was actually TAUGHT. Returning every wrapup
            # point meant a student who stopped at segment 2 of 9 was handed
            # takeaways for seven segments they never saw.
            covered = session_row.get("segments_completed") or 0
            if not covered:
                covered = max(0, (session_row.get("current_segment") or 1) - 1)
            covered = max(1, min(covered, len(all_points))) if all_points else 0
            summary_points = all_points[:covered]

    if not summary_points:
        summary_points = ["Reviewed core concept step-by-step", "Solved checkpoint question on the board"]

    misc_res = supabase.table("student_misconceptions").select("id").eq("session_id", session_id).execute()
    mistakes_count = len(misc_res.data or [])

    return {
        "summary_points": summary_points,
        "mistakes_count": mistakes_count,
        "duration_minutes": duration_minutes,
        "questions_answered": questions_answered,
        "chapter_name": chapter_name,
    }
