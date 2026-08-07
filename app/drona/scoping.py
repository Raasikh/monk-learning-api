import json
import logging
from typing import Dict, Any, List
from app.db import supabase
from app.drona.models import get_drona_client, get_model_name
from app.drona.prompt_loader import load_prompt
from app.drona.planner import get_or_create_plan

logger = logging.getLogger("drona.scoping")

def scope_student_session(session_id: str, user_id: str, utterance: str) -> Dict[str, Any]:
    """Scoping service layer (§2): resolves subtopic, invokes planner lazy cache, updates session state."""
    # 1. Load session row
    sess_res = supabase.table("drona_sessions").select("*").eq("id", session_id).eq("user_id", user_id).execute()
    if not sess_res.data:
        raise ValueError(f"Session '{session_id}' not found for user '{user_id}'")
    session = sess_res.data[0]
    chapter_id = session.get("chapter_id")

    # 2. Load chapter name & subtopics from subtopic_index
    chap_name = "this chapter"
    if chapter_id:
        c_res = supabase.table("chapters").select("name").eq("id", chapter_id).execute()
        if c_res.data:
            chap_name = c_res.data[0]["name"]

    sub_res = supabase.table("subtopic_index").select("id, subtopic, subtopic_key").eq("chapter_id", chapter_id).execute() if chapter_id else None
    subtopics = sub_res.data if sub_res and sub_res.data else []
    
    valid_keys = {s["subtopic_key"]: s["subtopic"] for s in subtopics if "subtopic_key" in s}

    # Format numbered list of subtopics for prompt
    subtopic_list_text = "\n".join([f"- {s['subtopic']} (key: {s['subtopic_key']})" for s in subtopics]) if subtopics else "- General Overview (key: general-overview)"

    # Track scoping rounds
    history = session.get("history_summary") or []
    scoping_round = sum(1 for h in history if "scoping:" in str(h)) + 1

    subtopic_key = None

    # Fast path: if utterance directly matches a subtopic key or name, skip LLM scoping latency
    norm_utt = utterance.strip().lower().replace("-", " ")
    for s in subtopics:
        s_key = s.get("subtopic_key", "")
        s_name = s.get("subtopic", "").lower().replace("-", " ")
        s_key_norm = s_key.lower().replace("-", " ")
        if norm_utt == s_key_norm or norm_utt == s_name or (len(norm_utt) > 3 and (norm_utt in s_name or s_name in norm_utt or norm_utt in s_key_norm or s_key_norm in norm_utt)):
            subtopic_key = s_key
            logger.info(f"Fast-path direct match for subtopic_key: '{subtopic_key}'")
            break

    # Max two rounds check: on 3rd round, default to first subtopic
    if subtopic_key:
        pass
    elif scoping_round >= 3 and subtopics:
        subtopic_key = subtopics[0]["subtopic_key"]
        logger.info(f"Max scoping rounds (3) reached. Defaulting to first subtopic: '{subtopic_key}'")
    else:
        # Call deepseek-v4-flash with scoping.md
        scoping_prompt = load_prompt("scoping.md")
        model_name = get_model_name("scoping")

        user_content = f"""
Chapter: {chap_name}
Available Subtopics:
{subtopic_list_text}

Student Utterance: "{utterance}"
"""

        client = get_drona_client()
        res = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": scoping_prompt},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )

        content = res.choices[0].message.content or ""
        try:
            parsed = json.loads(content)
            key_cand = parsed.get("subtopic_key")
            if key_cand in valid_keys:
                subtopic_key = key_cand
        except Exception as e:
            logger.warning(f"Failed to parse scoping LLM response: {e}")

    # Case A: Subtopic resolved
    if subtopic_key:
        sub_title = valid_keys.get(subtopic_key, subtopic_key.replace("-", " ").title())

        # Call get_or_create_plan (§3)
        plan_row = get_or_create_plan(chapter_id, subtopic_key)
        plan_id = plan_row["id"]

        new_history = history + [f"scoping: resolved to '{subtopic_key}'"]

        # Update drona_sessions: subtopic_key, plan_id, phase = 'teaching'
        supabase.table("drona_sessions").update({
            "subtopic_key": subtopic_key,
            "plan_id": plan_id,
            "phase": "teaching",
            "current_segment": 1,
            "attempts_on_current_question": 0,
            "history_summary": new_history
        }).eq("id", session_id).execute()

        tutor_speech = f"Awesome! Let's dive into {sub_title}. I'll guide you step-by-step on the board."

        return {
            "phase": "teaching",
            "speech": tutor_speech,
            "subtopic": sub_title,
            "subtopic_key": subtopic_key,
            "plan_ready": True
        }

    # Case B: Subtopic ambiguous / null -> return options[]
    new_history = history + [f"scoping: ambiguous input '{utterance[:30]}'"]
    supabase.table("drona_sessions").update({
        "history_summary": new_history
    }).eq("id", session_id).execute()

    options = [s["subtopic"] for s in subtopics] if subtopics else ["General Overview"]
    tutor_speech = f"Got it! Which of these subtopics in {chap_name} would you like to cover?"

    return {
        "phase": "scoping",
        "speech": tutor_speech,
        "options": options,
        "plan_ready": False
    }
