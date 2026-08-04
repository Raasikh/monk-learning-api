import json
import asyncio
import logging
from typing import Dict, Any, AsyncGenerator
from app.db import supabase
from app.drona.models import get_drona_client, get_model_name
from app.drona.prompt_loader import load_prompt
from app.drona.state import compute_next_session_state

logger = logging.getLogger("drona.tutor")

# R3 — Server-side consumed keys (never emitted to SSE stream)
FORBIDDEN_SSE_KEYS = {
    "model_answer",
    "rubric",
    "expected_misconceptions",
    "grade",
    "mistake_tag",
    "phase_request",
    "segment_complete",
}

def strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text

def parse_tutor_json(raw_text: str) -> Dict[str, Any]:
    """Robust JSON parsing with fence stripping."""
    cleaned = strip_fences(raw_text)
    return json.loads(cleaned)

async def process_tutor_turn_stream(
    session_id: str,
    user_id: str,
    utterance: str | None,
    turn_type: str
) -> AsyncGenerator[str, None]:
    """
    Complete production Drona tutor turn pipeline (§4):
    1. Reads session & plan state
    2. Assembles context in fixed R4 prefix order for DeepSeek caching
    3. Streams LLM response with JSON robustness
    4. Applies state machine & updates drona_sessions
    5. Inserts audit records into drona_turns, student_misconceptions, and drona_wellbeing_flags
    6. Emits sanitized SSE events (R3)
    """

    # 1. SELECT * FROM drona_sessions
    sess_res = supabase.table("drona_sessions").select("*").eq("id", session_id).eq("user_id", user_id).execute()
    if not sess_res.data:
        yield f"event: state\ndata: {json.dumps({'phase': 'complete', 'reason': 'session_not_found'})}\n\n"
        yield "event: done\ndata: {}\n\n"
        return

    session = sess_res.data[0]
    phase_in = session.get("phase", "teaching")
    curr_seg_idx = session.get("current_segment") or 1
    attempts = session.get("attempts_on_current_question") or 0
    history = session.get("history_summary") or []
    plan_id = session.get("plan_id")
    language = session.get("language") or "hinglish"

    # 2. SELECT plan_json FROM lesson_plans
    plan_row = None
    if plan_id:
        plan_res = supabase.table("lesson_plans").select("*").eq("id", plan_id).execute()
        if plan_res.data:
            plan_row = plan_res.data[0]

    plan_json = plan_row.get("plan_json") if plan_row else {}
    segments = plan_json.get("segments") or []
    total_segments = len(segments) if segments else 1

    # Clamp current segment index
    curr_seg_idx = max(1, min(curr_seg_idx, total_segments))
    curr_segment = segments[curr_seg_idx - 1] if segments else {
        "objective": "General Overview",
        "teaching_notes": "Introduce the topic and key concepts.",
        "board_content": r"\text{Overview}",
        "checkpoint": {"question": "Ready to move forward?", "model_answer": "Yes", "rubric": "Confirm understanding"}
    }

    # 3. Assemble R4 prefix order: [1] tutor.md [2] plan [3] current segment [4] state [5] utterance
    tutor_prompt = load_prompt("tutor.md")

    session_state_ctx = {
        "language": language,
        "phase": phase_in,
        "current_segment": curr_seg_idx,
        "total_segments": total_segments,
        "attempts_on_current_question": attempts,
        "history_summary": history[-10:],
        "turn_type": turn_type
    }

    system_content = f"{tutor_prompt}\n\n[LESSON PLAN]\n{json.dumps(plan_json, indent=2)}"
    user_content = f"""[CURRENT SEGMENT]
{json.dumps(curr_segment, indent=2)}

[SESSION STATE]
{json.dumps(session_state_ctx, indent=2)}

[STUDENT UTTERANCE]
"{utterance or ''}"
"""

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content}
    ]

    model_name = get_model_name("tutor")
    client = get_drona_client()

    # 4. LLM call with JSON robustness (§4.4)
    raw_response_text = ""
    input_tokens = 0
    output_tokens = 0
    cache_hit_tokens = 0

    try:
        res = client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            stream=False
        )

        if res.choices and res.choices[0].message.content:
            raw_response_text = res.choices[0].message.content

        if hasattr(res, "usage") and res.usage:
            input_tokens = getattr(res.usage, "prompt_tokens", 0)
            output_tokens = getattr(res.usage, "completion_tokens", 0)
            details = getattr(res.usage, "prompt_tokens_details", None)
            if details:
                cache_hit_tokens = getattr(details, "cached_tokens", 0)

    except Exception as e:
        logger.error(f"Error during LLM turn: {e}")
        raw_response_text = json.dumps({
            "speech": "Let's pause for a moment and review what we've covered on the board.",
            "board": curr_segment.get("board_content", ""),
            "phase_request": phase_in
        })

    # Log cache hit tokens (§R4)
    logger.info(f"TURN LLM CALL: model={model_name}, input={input_tokens}, cache_hit={cache_hit_tokens}, output={output_tokens}")

    # 5. Parse complete JSON with robustness (§4.4)
    parsed_json = {}
    try:
        parsed_json = parse_tutor_json(raw_response_text)
    except Exception as e:
        logger.warning(f"Failed to parse LLM response JSON on first try: {e}. Executing retry...")
        try:
            retry_res = client.chat.completions.create(
                model=model_name,
                messages=messages + [
                    {"role": "assistant", "content": raw_response_text},
                    {"role": "user", "content": "Return only valid JSON. No prose, no fences."}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            parsed_json = json.loads(strip_fences(retry_res.choices[0].message.content or "{}"))
        except Exception as retry_err:
            logger.error(f"Second JSON parse failure: {retry_err}")
            parsed_json = {
                "speech": "Let's focus on the step on the board.",
                "board": curr_segment.get("board_content", r"\text{Focus}"),
                "phase_request": phase_in
            }

    speech_out = parsed_json.get("speech") or "Let me explain this step."
    board_out = parsed_json.get("board") or curr_segment.get("board_content", "")
    grade_out = parsed_json.get("grade")
    mistake_tag = parsed_json.get("mistake_tag")
    offtopic_tier = parsed_json.get("offtopic_tier")

    # 6. Apply State Machine (§5)
    next_phase, next_seg, next_attempts, seg_advanced, is_mistake = compute_next_session_state(
        current_phase=phase_in,
        current_segment=curr_seg_idx,
        total_segments=total_segments,
        attempts=attempts,
        tutor_output=parsed_json,
        turn_type=turn_type
    )

    # 7. Update history summary
    first_words = " ".join(speech_out.split()[:12])
    history_entry = f"S{curr_seg_idx} {phase_in}: {first_words}"
    updated_history = (history + [history_entry])[-10:]

    # 8. UPDATE drona_sessions
    supabase.table("drona_sessions").update({
        "phase": next_phase,
        "current_segment": next_seg,
        "attempts_on_current_question": next_attempts,
        "history_summary": updated_history
    }).eq("id", session_id).execute()

    # 9. Get turn count and INSERT into drona_turns
    turns_res = supabase.table("drona_turns").select("turn_index").eq("session_id", session_id).execute()
    turn_index = len(turns_res.data or []) + 1

    supabase.table("drona_turns").insert([{
        "session_id": session_id,
        "turn_index": turn_index,
        "segment_index": curr_seg_idx,
        "phase_in": phase_in,
        "utterance": utterance,
        "raw_response": raw_response_text,
        "grade": grade_out,
        "input_tokens": input_tokens,
        "cache_hit_tokens": cache_hit_tokens,
        "output_tokens": output_tokens
    }]).execute()

    # 10. INSERT into student_misconceptions if mistake logged (§4.1 #12)
    if is_mistake and mistake_tag:
        try:
            supabase.table("student_misconceptions").insert([{
                "session_id": session_id,
                "user_id": user_id,
                "subtopic_key": session.get("subtopic_key", "unknown")
            }]).execute()
        except Exception as e:
            logger.warning(f"Optional insert into student_misconceptions skipped: {e}")

    # 11. INSERT into drona_wellbeing_flags if offtopic_tier == 5 (§4.1 #13)
    if offtopic_tier == 5:
        try:
            supabase.table("drona_wellbeing_flags").insert([{
                "session_id": session_id,
                "user_id": user_id,
                "utterance": utterance
            }]).execute()
        except Exception as e:
            logger.warning(f"Optional insert into drona_wellbeing_flags skipped: {e}")

    # 12. Strict R3 assertion helper
    def assert_no_forbidden_keys(payload: dict):
        for k in FORBIDDEN_SSE_KEYS:
            if k in payload:
                raise ValueError(f"R3 VIOLATION: Forbidden server-side key '{k}' in client payload: {payload}")

    # 13. Emit sanitized SSE events (R3)
    speech_payload = {"delta": speech_out}
    assert_no_forbidden_keys(speech_payload)
    yield f"event: speech\ndata: {json.dumps(speech_payload)}\n\n"

    if board_out:
        board_payload = {"latex": board_out}
        assert_no_forbidden_keys(board_payload)
        yield f"event: board\ndata: {json.dumps(board_payload)}\n\n"

    meta_payload = {
        "segment_index": next_seg if next_phase != "complete" else total_segments,
        "total_segments": total_segments,
        "session_complete": (next_phase == "complete")
    }
    assert_no_forbidden_keys(meta_payload)
    yield f"event: meta\ndata: {json.dumps(meta_payload)}\n\n"

    state_payload = {
        "phase": next_phase
    }
    if next_phase == "complete":
        state_payload["reason"] = "session_ended"
    assert_no_forbidden_keys(state_payload)
    yield f"event: state\ndata: {json.dumps(state_payload)}\n\n"

    yield "event: done\ndata: {}\n\n"
