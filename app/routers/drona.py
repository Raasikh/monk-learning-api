import json
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from app.auth import get_current_user_id
from app.db import supabase
from app.drona.prompt_loader import load_prompt
from app.drona.retrieval import evaluate_free_text_gate, retrieve_pdf_chunks
from openai import OpenAI
import os

router = APIRouter(prefix="/drona", tags=["drona"])

def get_llm_client() -> OpenAI:
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_key:
        return OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        return OpenAI(api_key=openai_key)
    raise RuntimeError("Neither DEEPSEEK_API_KEY nor OPENAI_API_KEY is set in environment")

def get_llm_model() -> str:
    if os.getenv("DEEPSEEK_API_KEY"):
        return os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    return "gpt-4o-mini"

@router.get("/catalogue")
def get_catalogue(user_id: str = Depends(get_current_user_id)):
    """GET /drona/catalogue — returns subject groups, chapters, and subtopics."""
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

    if not catalogue:
        catalogue = [{
            "subject": "Physics",
            "chapters": [{
                "id": "c11-ch01",
                "name": "Units and Measurement",
                "class_level": 11,
                "subtopics": [
                    {"id": "s1", "name": "SI Units & Standards", "grounding_status": "grounded"},
                    {"id": "s2", "name": "Dimensional Analysis", "grounding_status": "grounded"}
                ]
            }]
        }]

    return catalogue

@router.post("/session/start")
def start_session_endpoint(payload: Dict[str, Any], user_id: str = Depends(get_current_user_id)):
    """POST /drona/session/start — initializes session."""
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
    """POST /drona/session/{session_id}/scope — handles scoping student input."""
    utterance = payload.get("utterance", "")

    # Perform scoping call
    scoping_prompt = load_prompt("scoping.md")
    res = get_llm_client().chat.completions.create(
        model=get_llm_model(),
        messages=[
            {"role": "system", "content": scoping_prompt},
            {"role": "user", "content": f"Student scoping input: '{utterance}'"}
        ],
        temperature=0.0
    )

    tutor_speech = f"Awesome, let's start with {utterance}! I'll walk you through it step-by-step."

    # Update session phase to teaching
    supabase.table("drona_sessions").update({
        "phase": "teaching"
    }).eq("id", session_id).execute()

    return {
        "phase": "teaching",
        "speech": tutor_speech,
        "subtopic": utterance,
        "plan_ready": True
    }

@router.post("/session/{session_id}/turn")
async def turn_session_endpoint(session_id: str, payload: Dict[str, Any], user_id: str = Depends(get_current_user_id)):
    """POST /drona/session/{session_id}/turn — streams SSE events (`speech`, `board`, `meta`, `state`, `done`)."""
    utterance = payload.get("utterance")
    turn_type = payload.get("turn_type", "answer")

    tutor_prompt = load_prompt("tutor.md")

    async def sse_generator():
        messages = [
            {"role": "system", "content": tutor_prompt},
            {"role": "user", "content": f"Context: Current Segment = 1. Phase = 'teaching'. Student Utterance: '{utterance or ''}'"}
        ]

        # Call OpenAI with JSON response format
        res = get_llm_client().chat.completions.create(
            model=get_llm_model(),
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0
        )

        data = json.loads(res.choices[0].message.content)
        speech_text = data.get("speech", "")
        board_latex = data.get("board", "")
        offtopic_tier = data.get("offtopic_tier")
        phase_req = data.get("phase_request", "teaching")

        # Stream speech in small deltas
        words = speech_text.split()
        for i in range(0, len(words), 3):
            delta = " ".join(words[i:i+3]) + " "
            event_payload = json.dumps({"delta": delta})
            yield f"event: speech\ndata: {event_payload}\n\n"
            await asyncio.sleep(0.05)

        # Stream board event (Rule F3: Replaces board content)
        if board_latex:
            yield f"event: board\ndata: {json.dumps({'latex': board_latex})}\n\n"

        # Stream meta event
        yield f"event: meta\ndata: {json.dumps({'segment_index': 1, 'total_segments': 5, 'session_complete': False})}\n\n"

        # Stream state event
        if phase_req == "end_session" or offtopic_tier == 5:
            yield f"event: state\ndata: {json.dumps({'phase': 'complete', 'reason': 'session_ended'})}\n\n"
        else:
            yield f"event: state\ndata: {json.dumps({'phase': phase_req})}\n\n"

        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")

@router.post("/session/{session_id}/end")
def end_session_endpoint(session_id: str, user_id: str = Depends(get_current_user_id)):
    """POST /drona/session/{session_id}/end — closes session and returns summary."""
    supabase.table("drona_sessions").update({
        "phase": "complete",
        "completed_at": "now()"
    }).eq("id", session_id).execute()

    return {
        "summary_points": [
            "Understood vector components and resolution",
            "Mastered coordinate projection formulas",
            "Solved sample checkpoint problem cleanly"
        ],
        "mistakes_count": 0,
        "next_suggestion": {
            "chapter_id": "c11-ch02",
            "chapter_name": "Kinematics & Motion in a Straight Line"
        }
    }
