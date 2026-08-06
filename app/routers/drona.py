import json
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from app.auth import get_current_user_id
from app.db import supabase
from app.drona.scoping import scope_student_session
from app.drona.tutor import process_tutor_turn_stream

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

@router.post("/session/start")
def start_session_endpoint(payload: Dict[str, Any], user_id: str = Depends(get_current_user_id)):
    """POST /drona/session/start — initializes session and returns initial scoping speech."""
    chapter_id = payload.get("chapter_id", "custom")
    language = payload.get("language", "hinglish")

    chapter_name = "this topic"
    if len(chapter_id) == 36:
        chap_data = supabase.table("chapters").select("name, subject, class_level").eq("id", chapter_id).execute()
        if chap_data.data:
            c = chap_data.data[0]
            subj = (c.get("subject") or "").capitalize()
            cls = c.get("class_level")
            chapter_name = f"{c['name']}, Class {cls} {subj}" if cls and subj else c['name']

    sess_res = supabase.table("drona_sessions").insert([{
        "user_id": user_id,
        "chapter_id": chapter_id if len(chapter_id) == 36 else None,
        "mode": "chapter" if len(chapter_id) == 36 else "free_text",
        "language": language,
        "phase": "scoping",
        "prompt_version": "v1.0"
    }]).execute()

    if not sess_res.data:
        raise HTTPException(status_code=500, detail="Failed to create Drona session")

    session_id = sess_res.data[0]["id"]
    confirmation_speech = f"Oh, so you want to learn {chapter_name}? What specific topic or concept do you want to focus on today?"

    return {
        "session_id": session_id,
        "phase": "scoping",
        "speech": confirmation_speech
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
    sess_res = supabase.table("drona_sessions").select("plan_id").eq("id", session_id).execute()
    plan_id = sess_res.data[0].get("plan_id") if sess_res.data else None

    summary_points = []
    if plan_id:
        p_res = supabase.table("lesson_plans").select("plan_json").eq("id", plan_id).execute()
        if p_res.data:
            pj = p_res.data[0].get("plan_json") or {}
            summary_points = pj.get("wrapup_points") or [s.get("objective") for s in pj.get("segments", []) if s.get("objective")]

    if not summary_points:
        summary_points = ["Reviewed core concept step-by-step", "Solved checkpoint question on the board"]

    misc_res = supabase.table("student_misconceptions").select("id").eq("session_id", session_id).execute()
    mistakes_count = len(misc_res.data or [])

    return {
        "summary_points": summary_points,
        "mistakes_count": mistakes_count
    }
