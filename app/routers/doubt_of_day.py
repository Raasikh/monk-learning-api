from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import get_current_user_id
from app.db import supabase
from app.drona.persona import normalize_language, normalize_voice, tutor_name

router = APIRouter(prefix="/doubt-of-day", tags=["doubt-of-day"])


class DoubtChatRequest(BaseModel):
    doubt_id: str
    language: Optional[str] = None
    voice: Optional[str] = None


@router.post("/chat")
def chat_about_doubt(
    req: DoubtChatRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Creates a doubt_of_day Drona session seeded with one curated doubt's full
    context (the question, its verified answer, the explanation behind it).
    The live tutor turn itself is generated over the WebSocket
    (POST /drona/session/{id}/live), not here — this endpoint only creates the
    session row and returns the session_id the frontend needs to open it.

    The client sends only a doubt_id; the answer and explanation are read from
    the table here rather than accepted from the request, so a tampered client
    can't put words in the teacher's mouth.
    """
    d_res = (
        supabase.table("doubt_of_the_day")
        .select("id, subject, chapter, concept, question_text, answer, explanation, difficulty")
        .eq("id", req.doubt_id)
        .eq("active", True)
        .limit(1)
        .execute()
    )
    if not d_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Doubt with ID '{req.doubt_id}' not found.",
        )

    d = d_res.data[0]

    language = normalize_language(req.language)
    voice = normalize_voice(req.voice)

    # Frozen at session-creation time, matching practice_seed: a turn's prompt
    # stays reproducible even if the doubt row is later edited or retired.
    doubt_seed = {
        "subject": d.get("subject"),
        "chapter": d.get("chapter"),
        "concept": d.get("concept"),
        "question_text": d.get("question_text"),
        "answer": d.get("answer"),
        "explanation": d.get("explanation"),
    }

    session_row = {
        "user_id": user_id,
        "mode": "doubt_of_day",
        "doubt_id": d["id"],
        "doubt_seed": doubt_seed,
        "language": language,
        "tutor_voice": voice,
        "phase": "teaching",  # WS auto-fires turn 1 on connect when phase == "teaching"
        "prompt_version": "doubt_of_day_v1",
    }

    sess_res = supabase.table("drona_sessions").insert([session_row]).execute()
    if not sess_res.data:
        raise HTTPException(status_code=500, detail="Failed to create doubt-of-day session")

    return {
        "session_id": sess_res.data[0]["id"],
        "phase": "teaching",
        "language": language,
        "tutor_voice": voice,
        "tutor_name": tutor_name(voice),
        "subject": d.get("subject"),
        "concept": d.get("concept"),
    }
