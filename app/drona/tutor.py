import re
import math
import json
import time
import asyncio
import logging
from typing import Dict, Any, AsyncGenerator
from app.db import supabase
from app.drona.models import get_drona_client, get_model_name
from app.drona.prompt_loader import load_prompt
from app.drona.state import compute_next_session_state
from app.drona.voice_proxy import RumikConnectionPool, split_into_sentences

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

    # Calculate elapsed_minutes from session created_at
    created_at_str = session.get("created_at")
    elapsed_minutes = 0.0
    if created_at_str:
        try:
            from datetime import datetime, timezone
            created_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            elapsed_minutes = round((now_dt - created_dt).total_seconds() / 60.0, 1)
        except Exception:
            elapsed_minutes = 0.0

    # Calculate rolling understanding_signal from drona_turns
    correct_first_attempt = 0
    partial_count = 0
    incorrect_count = 0
    hints_used = 0
    try:
        turns_res = supabase.table("drona_turns").select("segment_index, grade").eq("session_id", session_id).execute()
        turns = turns_res.data or []
        seg_grades = {}
        for t in turns:
            g = (t.get("grade") or "").lower().strip()
            s_idx = t.get("segment_index")
            if g in ("correct", "partial", "incorrect"):
                if s_idx not in seg_grades:
                    seg_grades[s_idx] = []
                seg_grades[s_idx].append(g)
        
        for s_idx, g_list in seg_grades.items():
            if g_list[0] == "correct":
                correct_first_attempt += 1
            elif "correct" in g_list:
                partial_count += 1
                hints_used += 1
            elif "partial" in g_list:
                partial_count += 1
            elif "incorrect" in g_list:
                incorrect_count += 1
    except Exception as sig_err:
        logger.warning(f"Failed to calculate understanding_signal: {sig_err}")

    total_graded = max(1, correct_first_attempt + partial_count + incorrect_count)
    mastery_rate = correct_first_attempt / total_graded
    overall_mastery = "high" if mastery_rate >= 0.8 else ("moderate" if mastery_rate >= 0.5 else "needs_practice")

    # In-memory plan extension: append consolidation segment if weak understanding at end of plan
    if curr_seg_idx == total_segments and overall_mastery in ("moderate", "needs_practice") and len(segments) > 0:
        if not any(s.get("is_consolidation") for s in segments):
            consolidation_seg = {
                "objective": "Consolidation & Worked Examples",
                "teaching_notes": "Review weakest graded concepts with extra worked examples.",
                "board_content": r"\text{Consolidation}",
                "checkpoint": {"question": "Are you confident with these concepts?", "model_answer": "Yes", "rubric": "Confirm understanding"},
                "is_consolidation": True
            }
            segments.append(consolidation_seg)
            total_segments = len(segments)

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

    # Collect board events emitted so far in current segment to enforce progressive arc
    current_segment_board_events = []
    turn_within_segment = 1
    try:
        seg_turns_res = supabase.table("drona_turns").select("raw_response").eq("session_id", session_id).eq("segment_index", curr_seg_idx).execute()
        turn_within_segment = len(seg_turns_res.data or []) + 1  # This will be the Nth turn in segment
        for t in (seg_turns_res.data or []):
            raw = t.get("raw_response")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = {}
            if isinstance(raw, dict):
                for b in raw.get("board_events", []):
                    txt = (b.get("text") or b.get("latex") or "").strip()
                    if txt and txt not in current_segment_board_events:
                        current_segment_board_events.append(txt)
    except Exception as b_err:
        logger.warning(f"Failed to load segment board events: {b_err}")

    # Compute exact board item assignment for this turn
    board_content_raw = curr_segment.get("board_content", [])
    if isinstance(board_content_raw, str):
        board_content_list = [line.strip() for line in board_content_raw.split("\n") if line.strip()]
    elif isinstance(board_content_raw, list):
        board_content_list = board_content_raw
    else:
        board_content_list = []

    N = len(board_content_list)
    items_per_turn = math.ceil(N / 3) if N > 0 else 0
    
    if turn_within_segment == 1:
        assigned_start = 0
        assigned_end = min(items_per_turn, N)
    elif turn_within_segment == 2:
        assigned_start = min(items_per_turn, N)
        assigned_end = min(2 * items_per_turn, N)
    else:
        assigned_start = min(2 * items_per_turn, N)
        assigned_end = N
    
    assigned_items = board_content_list[assigned_start:assigned_end]
    assigned_items_text = []
    for item in assigned_items:
        if isinstance(item, dict):
            assigned_items_text.append(item.get("text") or item.get("latex", ""))
        else:
            assigned_items_text.append(str(item))

    session_state_ctx = {
        "language": language,
        "phase": phase_in,
        "current_segment": curr_seg_idx,
        "total_segments": total_segments,
        "attempts_on_current_question": attempts,
        "history_summary": history[-10:],
        "turn_type": turn_type,
        "elapsed_minutes": elapsed_minutes,
        "understanding_signal": {
            "correct_first_attempt": correct_first_attempt,
            "partial": partial_count,
            "incorrect": incorrect_count,
            "hints_used": hints_used,
            "overall_mastery": overall_mastery
        },
        "tutor_gender": "female",
        "tutor_name": "Veda"
    }

    system_content = f"{tutor_prompt}\n\n[LESSON PLAN]\n{json.dumps(plan_json, sort_keys=True)}"
    user_content = f"""[CURRENT SEGMENT]
{json.dumps(curr_segment, sort_keys=True)}

[TURN WITHIN SEGMENT]
This is Turn {turn_within_segment} of 3 in this segment.

[BOARD EVENTS ALREADY EMITTED IN THIS SEGMENT]
{json.dumps(current_segment_board_events, indent=2)}

[YOUR ASSIGNED BOARD ITEMS FOR THIS TURN]
You MUST emit EXACTLY these {len(assigned_items)} board items in this turn — no more, no fewer, no substitutions:
{json.dumps(assigned_items_text, indent=2)}

[PROGRESSIVE ARC DIRECTIVE]
1. Emit ONLY the items listed in [YOUR ASSIGNED BOARD ITEMS FOR THIS TURN]. Do NOT emit items assigned to other turns.
2. DO NOT re-emit any items from [BOARD EVENTS ALREADY EMITTED IN THIS SEGMENT].
3. Teach ONLY the sub-concept(s) covered by your assigned board items.
4. If student answered correctly, give 1 short sentence of praise, then teach your assigned sub-concept(s).
5. Any check must test ONLY concepts explained in THIS turn or previous turns of this segment.

[SESSION STATE]
{json.dumps(session_state_ctx, sort_keys=True)}

[STUDENT UTTERANCE]
"{utterance or ''}"
"""

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content}
    ]

    stag = f"[s:{session_id[:8]}]"
    logger.info(f"{stag} TURN START   seg={curr_seg_idx}/{total_segments}  turn_in_seg={turn_within_segment}/3  phase={phase_in}")

    model_name = get_model_name("tutor")
    client = get_drona_client()

    # 4. LLM call with JSON robustness (§4.4)
    raw_response_text = ""
    input_tokens = 0
    output_tokens = 0
    cache_hit_tokens = 0

    turn_failed = False
    llm_t0 = time.time()

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
        logger.error(f"{stag} Error during LLM turn: {e}")
        turn_failed = True
        raw_response_text = json.dumps({
            "speech": "Aapki awaaz thodi kat gayi thi — kya aap ek baar dubara bol sakte hain?",
            "board_events": [],
            "phase_request": phase_in,
            "turn_failed": True
        })

    llm_dur = time.time() - llm_t0
    logger.info(f"{stag}   LLM          model={model_name} in={input_tokens} cache={cache_hit_tokens} out={output_tokens} ({llm_dur:.1f}s)")
    logger.info(f"{stag}   ASSIGNED     {len(assigned_items_text)} board items: {assigned_items_text}")

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

    # 5b. First-Turn Teaching Rule Enforcement & Board Content Fallback
    if turn_within_segment == 1:
        if parsed_json.get("phase_request") == "awaiting_answer":
            logger.warning(f"⚠️ [FIRST TURN HARD OVERRIDE] Turn 1 cannot ask a question. Forcing phase_request='teaching'.")
        parsed_json["phase_request"] = "teaching"
        parsed_json["question_type"] = None
        parsed_json["check_options"] = []

    # If board_events is empty in a teaching turn, auto-populate from assigned items
    did_fallback_board = False
    if not parsed_json.get("board_events") and assigned_items_text:
        logger.warning(f"⚠️ [VIOLATION: ZERO BOARD EVENTS EMITTED] Tutor emitted 0 events despite assigned items. Auto-populating {len(assigned_items_text)} board items.")
        did_fallback_board = True
        auto_events = []
        for idx, text_str in enumerate(assigned_items_text, 1):
            event_type = "heading" if idx == 1 and turn_within_segment == 1 else "text"
            if "\\" in text_str or "{" in text_str or "^" in text_str:
                event_type = "formula"
                auto_events.append({"seq": idx, "type": event_type, "latex": text_str, "emphasis": "normal"})
            else:
                auto_events.append({"seq": idx, "type": event_type, "text": text_str, "emphasis": "normal"})
        parsed_json["board_events"] = auto_events

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

    # Evaluate turn violations for persistence in drona_turns.violations
    board_events = parsed_json.get("board_events", [])
    board_cnt = len(board_events)
    word_cnt = len(speech_out.split())
    opts_cnt = len(parsed_json.get("check_options") or [])

    match_symbol = "✓ matches assignment" if board_cnt == len(assigned_items_text) else f"❌ mismatch (assigned {len(assigned_items_text)}, emitted {board_cnt})"
    logger.info(f"{stag}   EMITTED      {board_cnt} board events  {match_symbol}")
    logger.info(f"{stag}   PHASE REQ    phase_request={parsed_json.get('phase_request')} | question_type={parsed_json.get('question_type')} | check_options={opts_cnt}")
    logger.info(f"{stag}   SPEECH       ({word_cnt} words) \"{speech_out[:60]}...\"")

    rule_violations = {
        "zero_board_events": 1 if (board_cnt == 0 and phase_in == "teaching") or did_fallback_board else 0,
        "fallback_board_events": 1 if did_fallback_board else 0,
        "under_density": 1 if board_cnt > 0 and board_cnt < 6 else 0,
        "over_density": 1 if board_cnt > 12 else 0,
        "missing_options": 1 if parsed_json.get("phase_request") == "awaiting_answer" and not parsed_json.get("check_options") else 0,
        "word_count_exceeded": 1 if word_cnt > 120 else 0,
        "raw_latex_in_text": 1 if any(pat in speech_out for pat in ["\\frac", "\\sqrt", "$$", "^", "_"]) else 0
    }

    # 8. UPDATE drona_sessions with persistent telemetry
    pool = RumikConnectionPool.get_instance()
    ended_reason_val = "complete" if next_phase in ("wrapup", "complete") else None

    supabase.table("drona_sessions").update({
        "phase": next_phase,
        "current_segment": next_seg,
        "attempts_on_current_question": next_attempts,
        "history_summary": updated_history,
        "segments_completed": curr_seg_idx if seg_advanced else curr_seg_idx - 1,
        "pool_exhaustion_count": pool.pool_exhaustion_count,
        "ended_reason": ended_reason_val
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
        "raw_response": json.dumps(parsed_json),
        "grade": grade_out,
        "input_tokens": input_tokens,
        "cache_hit_tokens": cache_hit_tokens,
        "output_tokens": output_tokens,
        "board_event_count": board_cnt,
        "rumik_requests": len(split_into_sentences(speech_out)),
        "rumik_chars": len(speech_out),
        "violations": rule_violations
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

    # Word count bounds validation (60-120 words)
    speech_words = [w for w in speech_out.split() if w.strip()]
    word_count = len(speech_words)
    if turn_type in ("teaching", "answer") and not (45 <= word_count <= 135):
        logger.warning(f"⚠️ [PROMPT VIOLATION] Turn speech word count out of target range: {word_count} words (Target: 60-120 words).")

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
    elif turn_type in ("teaching", "answer"):
        logger.warning(f"⚠️ [PROMPT VIOLATION] Teaching turn in session {session_id} emitted 0 board_events! Tutor LLM omitted board_events array.")

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
