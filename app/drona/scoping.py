import json
import logging
from typing import Dict, Any, List
import time
from typing import List, Tuple

from app.db import supabase, fetch_all
from app.drona.models import get_drona_client, get_model_name, SCOPING_TIMEOUT_S
from app.drona.prompt_loader import load_prompt
from app.drona.planner import get_or_create_plan
from app.drona.persona import (
    SCOPING_AMBIGUOUS,
    SCOPING_RESOLVED,
    SCOPING_RESOLVED_NAMED,
    copy_for,
    first_name_of,
    normalize_language,
    normalize_voice,
    tutor_name,
)

logger = logging.getLogger("drona.scoping")

def scope_student_session(session_id: str, user_id: str, utterance: str) -> Dict[str, Any]:
    """Scoping service layer (§2): resolves subtopic, invokes planner lazy cache, updates session state.

    Every stage is timed, because this is the single longest thing between a
    student and their first spoken word and it was previously a black box. A
    report of "scope takes 2.5 minutes" could not be confirmed or refuted from
    the logs: the endpoint line gives a total and nothing inside it is
    attributed, and the scoping model call is not metered in llm_calls at all.
    A number nobody can decompose is a number nobody can fix.
    """
    _t0 = time.time()
    _marks: List[Tuple[str, float]] = []

    def _mark(stage: str) -> None:
        _marks.append((stage, time.time() - _t0))
    # 1. Load session row
    sess_res = supabase.table("drona_sessions").select("*").eq("id", session_id).eq("user_id", user_id).execute()
    if not sess_res.data:
        raise ValueError(f"Session '{session_id}' not found for user '{user_id}'")
    session = sess_res.data[0]
    chapter_id = session.get("chapter_id")
    language = normalize_language(session.get("language"))
    voice = normalize_voice(session.get("tutor_voice"))

    # 2. Load chapter name & subtopics from subtopic_index
    chap_name = "this chapter"
    if chapter_id:
        c_res = supabase.table("chapters").select("name").eq("id", chapter_id).execute()
        if c_res.data:
            chap_name = c_res.data[0]["name"]

    # Concepts are the teaching unit now, matching what /drona/catalogue offers
    # and what Progress scores. The local variables keep the "subtopic" naming
    # because subtopic_key is the plan cache's column and the scoping prompt's
    # vocabulary — only the source table and the meaning of a key changed.
    #
    # Ordered by teach_order so the prompt lists them the way they are taught;
    # the model reads this list top-down when a student's request is vague, and
    # an exam-frequency ordering made it suggest the hardest concept first.
    concept_rows = fetch_all(
        "concepts", "id, name, key, teach_order, display_order, active",
        chapter_id=chapter_id,
    ) if chapter_id else []
    _mark("db_reads")
    concept_rows = [r for r in concept_rows if r.get("active") is not False]
    concept_rows.sort(key=lambda x: (
        x.get("teach_order") is None,
        x.get("teach_order") or 0,
        x.get("display_order") or 0,
        x.get("name") or "",
    ))
    subtopics = [{"id": r["id"], "subtopic": r["name"], "subtopic_key": r["key"]} for r in concept_rows]

    valid_keys = {s["subtopic_key"]: s["subtopic"] for s in subtopics if "subtopic_key" in s}

    # Format numbered list of subtopics for prompt
    subtopic_list_text = "\n".join([f"- {s['subtopic']} (key: {s['subtopic_key']})" for s in subtopics]) if subtopics else "- General Overview (key: general-overview)"

    # Track scoping rounds
    history = session.get("history_summary") or []
    scoping_round = sum(1 for h in history if "scoping:" in str(h)) + 1

    subtopic_key = None

    # Fast path: if utterance directly matches a subtopic key or name, skip LLM scoping latency
    norm_utt = utterance.strip().lower().replace("-", " ")
    # Pass 1: Exact match on key or title
    for s in subtopics:
        s_key = s.get("subtopic_key", "")
        s_name = s.get("subtopic", "").lower().replace("-", " ")
        s_key_norm = s_key.lower().replace("-", " ")
        if norm_utt == s_key_norm or norm_utt == s_name:
            subtopic_key = s_key
            logger.info(f"Fast-path exact match for subtopic_key: '{subtopic_key}'")
            break

    # Pass 2: Substring fallback if no exact match
    if not subtopic_key:
        for s in subtopics:
            s_key = s.get("subtopic_key", "")
            s_name = s.get("subtopic", "").lower().replace("-", " ")
            s_key_norm = s_key.lower().replace("-", " ")
            if len(norm_utt) > 3 and (norm_utt in s_name or s_name in norm_utt or norm_utt in s_key_norm or s_key_norm in norm_utt):
                subtopic_key = s_key
                logger.info(f"Fast-path substring match for subtopic_key: '{subtopic_key}'")
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
            temperature=0.0,
            timeout=SCOPING_TIMEOUT_S
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

        _mark("llm_scoping")
        # Call get_or_create_plan (§3). On a cache miss this authors an outline
        # plus segment 1 synchronously — measured at ~22s and ~6s — so it
        # dominates the endpoint whenever the plan is new.
        plan_row = get_or_create_plan(chapter_id, subtopic_key)
        _mark("plan")
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

        # Open the class by name when we have one. Failure here must never cost
        # the student their lesson, so any profile-lookup problem falls through
        # to the unnamed greeting.
        student_name = ""
        try:
            prof = (
                supabase.table("profiles")
                .select("display_name")
                .eq("id", user_id)
                .limit(1)
                .execute()
            )
            rows = prof.data or []
            student_name = first_name_of(rows[0].get("display_name") if rows else "")
        except Exception as name_err:
            logger.warning(f"Could not read display_name for greeting: {name_err}")

        if student_name:
            tutor_speech = copy_for(
                SCOPING_RESOLVED_NAMED, language, name=student_name, subtopic=sub_title
            )
        else:
            tutor_speech = copy_for(SCOPING_RESOLVED, language, subtopic=sub_title)

        _mark("done")
        logger.info("⏱️ [SCOPE TIMING] " + "  ".join(
            f"{name}={dt:.1f}s" for name, dt in _marks))
        return {
            "phase": "teaching",
            "speech": tutor_speech,
            "subtopic": sub_title,
            "subtopic_key": subtopic_key,
            "plan_ready": True,
            "language": language,
            "tutor_voice": voice,
            "tutor_name": tutor_name(voice)
        }

    # Case B: Subtopic ambiguous / null -> return options[]
    new_history = history + [f"scoping: ambiguous input '{utterance[:30]}'"]
    supabase.table("drona_sessions").update({
        "history_summary": new_history
    }).eq("id", session_id).execute()

    options = [s["subtopic"] for s in subtopics] if subtopics else ["General Overview"]
    tutor_speech = copy_for(SCOPING_AMBIGUOUS, language, chapter=chap_name)

    return {
        "phase": "scoping",
        "speech": tutor_speech,
        "options": options,
        "plan_ready": False,
        "language": language,
        "tutor_voice": voice,
        "tutor_name": tutor_name(voice)
    }
