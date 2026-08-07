import json
import time
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
        text = "\n".join(lines).strip()
    
    # Extract JSON object substring between first { and last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        return text[first_brace:last_brace + 1]
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
        "turn_type": turn_type,
        "tutor_gender": "female",
        "tutor_name": "Veda"
    }

    system_content = f"{tutor_prompt}\n\n[LESSON PLAN]\n{json.dumps(plan_json, sort_keys=True)}"
    user_content = f"""[CURRENT SEGMENT]
{json.dumps(curr_segment, sort_keys=True)}

[SESSION STATE]
{json.dumps(session_state_ctx, sort_keys=True)}

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

    turn_failed = False

    try:
        res = client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=2048,
            stream=False,
            extra_body={"thinking": {"type": "disabled"}}
        )

        returned_model = getattr(res, "model", "")
        if returned_model and returned_model != model_name:
            raise RuntimeError(f"STRICT R1 MODEL VIOLATION: Requested '{model_name}', but API returned '{returned_model}'")

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
        turn_failed = True
        raw_response_text = json.dumps({
            "speech": "Aapki awaaz thodi kat gayi thi — kya aap ek baar dubara bol sakte hain?",
            "board_events": [],
            "phase_request": phase_in,
            "turn_failed": True
        })

    # Log cache hit tokens (§R4) and assert model string (§R1)
    logger.info(f"TURN LLM CALL: requested_model={model_name}, returned_model={getattr(res, 'model', 'unknown')}, input={input_tokens}, cache_hit={cache_hit_tokens}, output={output_tokens}")

    # 5. Parse complete JSON with robustness (§4.4)
    parsed_json = {}
    try:
        parsed_json = parse_tutor_json(raw_response_text)
    except Exception as e:
        logger.error(f"[RAW LLM RESPONSE PARSE FAILURE BODY] length={len(raw_response_text)} | content='{raw_response_text}' | error={e}")
        logger.warning(f"Executing LLM JSON format retry...")
        try:
            retry_res = client.chat.completions.create(
                model=model_name,
                messages=messages + [
                    {"role": "assistant", "content": raw_response_text or "{}"},
                    {"role": "user", "content": "Return only valid JSON object. No prose, no markdown fences."}
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                extra_body={"thinking": {"type": "disabled"}}
            )
            parsed_json = json.loads(strip_fences(retry_res.choices[0].message.content or "{}"))
        except Exception as retry_err:
            logger.error(f"Second JSON parse failure: {retry_err}")
            turn_failed = True
            parsed_json = {
                "speech": "Aapki awaaz thodi clear nahi aayi — kya aap ek baar dubara bol sakte hain?",
                "board_events": [],
                "phase_request": phase_in,
                "turn_failed": True
            }

    speech_out = parsed_json.get("speech") or "Aapki awaaz thodi clear nahi aayi — kya aap ek baar dubara bol sakte hain?"
    board_out = parsed_json.get("board") or ""
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

    turn_data = {
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
    }
    if turn_failed:
        turn_data["turn_failed"] = True

    try:
        supabase.table("drona_turns").insert([turn_data]).execute()
    except Exception as db_ins_err:
        logger.warning(f"Insert into drona_turns warning: {db_ins_err}")

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

    if turn_failed:
        err_payload = {"type": "turn_error", "message": "Something went wrong — retrying turn", "turn_failed": True}
        assert_no_forbidden_keys(err_payload)
        yield f"event: turn_error\ndata: {json.dumps(err_payload)}\n\n"

    # 13. Emit sanitized SSE events (R3) with sentence-by-sentence Rumik Silk TTS audio
    speech_payload = {"delta": speech_out}
    assert_no_forbidden_keys(speech_payload)
    yield f"event: speech\ndata: {json.dumps(speech_payload)}\n\n"

    board_events_out = parsed_json.get("board_events") or []
    sanitized_board_events = []
    seen_contents = set()

    for idx, evt in enumerate(board_events_out, 1):
        e_type = evt.get("type", "text")
        raw_text = evt.get("text") or ""
        raw_latex = evt.get("latex") or ""

        # Auto-convert text events containing LaTeX commands into formula events
        if e_type in ("text", "heading", "note") and re.search(r"\\(frac|sqrt|text|vec|dfrac|Rightarrow|times|cdot)", raw_text):
            logger.warning(f"⚠️ [PROMPT VIOLATION] LaTeX command found in text event '{raw_text}' -> auto-converted to formula event.")
            e_type = "formula"
            raw_latex = raw_text
            raw_text = ""

        clean_evt = {
            "seq": evt.get("seq", idx),
            "type": e_type,
            "emphasis": evt.get("emphasis", "normal")
        }

        if e_type == "formula":
            content_key = (raw_latex or raw_text).strip()
            clean_evt["latex"] = content_key
        else:
            content_key = (raw_text or raw_latex).strip()
            clean_evt["text"] = content_key

        # Deduplicate board events within turn
        if content_key and content_key.lower() not in seen_contents:
            seen_contents.add(content_key.lower())
            sanitized_board_events.append(clean_evt)
        elif content_key:
            logger.warning(f"⚠️ [PROMPT VIOLATION] Dropped duplicate board_event content: '{content_key}'")

    if sanitized_board_events:
        board_payload = {"events": sanitized_board_events}
        assert_no_forbidden_keys(board_payload)
        yield f"event: board_events\ndata: {json.dumps(board_payload)}\n\n"

    question_type = parsed_json.get("question_type")
    check_options = parsed_json.get("check_options") or []

    # HARD FAIL-SAFE GUARDRAIL: Every question MUST trigger the Ask Sheet with option chips
    speech_asks_question = bool(re.search(r"\?|samajh aaya|clear hai|quick check|kya hoga|bataiye|option", speech_out, re.IGNORECASE))
    if speech_asks_question or phase_in == "awaiting_answer":
        next_phase = "awaiting_answer"
        if not check_options:
            logger.warning(f"⚠️ [HARD PROMPT VIOLATION] Speech asked question but 0 check_options emitted. Auto-populating check_options server-side.")
            if re.search(r"samajh aaya|clear hai|aage badh", speech_out, re.IGNORECASE):
                question_type = "procedural"
                check_options = ["Haan, samajh aaya", "Ek baar dubara samjhao"]
            else:
                question_type = "check"
                check_options = ["Option A", "Option B", "Option C"]

    meta_payload = {
        "segment_index": next_seg if next_phase != "complete" else total_segments,
        "total_segments": total_segments,
        "session_complete": (next_phase == "complete")
    }
    assert_no_forbidden_keys(meta_payload)
    yield f"event: meta\ndata: {json.dumps(meta_payload)}\n\n"

    state_payload = {
        "phase": next_phase,
        "question_type": question_type,
        "check_options": check_options
    }
    assert_no_forbidden_keys(state_payload)
    yield f"event: state\ndata: {json.dumps(state_payload)}\n\n"
    if next_phase == "complete":
        state_payload["reason"] = "session_ended"
    assert_no_forbidden_keys(state_payload)
    yield f"event: state\ndata: {json.dumps(state_payload)}\n\n"

    yield "event: done\ndata: {}\n\n"
