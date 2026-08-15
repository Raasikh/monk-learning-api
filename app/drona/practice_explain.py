"""Turn processor for practice_explain Drona sessions.

A practice_explain session is a disposable, question-scoped "talk to the
teacher" conversation launched from the Practice page after a student answers
a question — not a lesson. It has no segments, no board-pacing, no quiz
cadence, and no rubric grading, so it deliberately does NOT reuse tutor.py's
process_tutor_turn_stream() or state.py's compute_next_session_state(): both
are built entirely around the multi-segment authored lesson_plans pedagogy.
Instead this module emits the same SSE event contract (board_events, speech,
meta, state, done) that tutor.py emits, so app/drona/live_session_ws.py can
forward it without any changes — it already just parses whatever event/data
lines a turn generator yields, mode-agnostic.
"""
import json
import logging
import re
import time
from typing import Any, AsyncGenerator, Dict

from app.db import supabase
from app.drona.models import get_drona_client, get_drona_async_client, get_model_name, TUTOR_TIMEOUT_S
from app.drona.prompt_loader import load_prompt
from app.drona.json_utils import assert_no_forbidden_keys, parse_tutor_json, strip_fences
from app.drona.persona import AUDIO_UNCLEAR, UNDERSTANDING_CHIPS, chips_for, copy_for, normalize_language, persona_for

logger = logging.getLogger("drona.practice_explain")


async def process_practice_explain_turn_stream(
    session: Dict[str, Any],
    user_id: str,
    utterance: str | None,
    turn_type: str,
) -> AsyncGenerator[str, None]:
    session_id = session["id"]
    phase_in = session.get("phase", "teaching")
    seed = session.get("practice_seed") or {}
    language = normalize_language(session.get("language"))
    persona = persona_for(session.get("tutor_voice"))
    is_opening_turn = turn_type == "teaching"

    stag = f"[s:{session_id[:8]}][practice_explain]"
    logger.info(f"{stag} TURN START  phase={phase_in} turn_type={turn_type} opening={is_opening_turn}")

    system_content = f"{load_prompt('tutor_practice_explain.md')}\n\n[PRACTICE QUESTION]\n{json.dumps(seed, sort_keys=True)}"
    session_state_ctx = {
        "language": language,
        "tutor_gender": persona["gender"],
        "tutor_name": persona["name"],
        "is_opening_turn": is_opening_turn,
        "turn_type": turn_type,
    }
    user_content = f"""[SESSION STATE]
{json.dumps(session_state_ctx, sort_keys=True)}

[STUDENT UTTERANCE]
"{utterance or ''}"
"""
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]

    model_name = get_model_name("tutor")
    client = get_drona_client()
    async_client = get_drona_async_client()

    raw_response_text = ""
    input_tokens = 0
    output_tokens = 0
    cache_hit_tokens = 0
    turn_failed = False
    llm_t0 = time.time()

    try:
        resp = await async_client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=1024,
            timeout=TUTOR_TIMEOUT_S,
            extra_body={"thinking": {"type": "disabled"}},
        )
        raw_response_text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        if usage:
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0
            details = getattr(usage, "prompt_tokens_details", None)
            if details:
                cache_hit_tokens = getattr(details, "cached_tokens", 0) or 0
    except Exception as e:
        logger.error(f"{stag} Error during LLM turn: {e}")
        turn_failed = True
        raw_response_text = json.dumps({
            "speech": copy_for(AUDIO_UNCLEAR, language),
            "board_events": [],
            "phase_request": phase_in,
            "turn_failed": True,
        })

    logger.info(f"{stag} LLM model={model_name} in={input_tokens} cache={cache_hit_tokens} out={output_tokens} ({time.time() - llm_t0:.1f}s)")

    parsed_json: Dict[str, Any] = {}
    try:
        parsed_json = parse_tutor_json(raw_response_text)
    except Exception as e:
        logger.error(f"{stag} JSON parse failure: {e}. Retrying with a strict follow-up.")
        try:
            retry_res = client.chat.completions.create(
                model=model_name,
                messages=messages + [
                    {"role": "assistant", "content": raw_response_text or "{}"},
                    {"role": "user", "content": "Return only valid JSON object. No prose, no markdown fences."},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                timeout=TUTOR_TIMEOUT_S,
                extra_body={"thinking": {"type": "disabled"}},
            )
            parsed_json = json.loads(strip_fences(retry_res.choices[0].message.content or "{}"))
        except Exception as retry_err:
            logger.error(f"{stag} Second JSON parse failure: {retry_err}")
            turn_failed = True
            parsed_json = {
                "speech": copy_for(AUDIO_UNCLEAR, language),
                "board_events": [],
                "phase_request": phase_in,
                "turn_failed": True,
            }

    speech_out = parsed_json.get("speech") or copy_for(AUDIO_UNCLEAR, language)
    offtopic_tier = parsed_json.get("offtopic_tier")
    phase_request = parsed_json.get("phase_request")

    # Crisis hard-stop (Tier 5a) ends the session; every other outcome moves to
    # awaiting_answer and never back to "teaching" — that phase only exists to
    # trigger the WS's turn-1 auto-fire on connect (live_session_ws.py:871),
    # and returning to it would re-trigger that same auto-advance after every
    # turn (live_session_ws.py:645-647).
    if phase_request == "end_session":
        next_phase = "complete"
    else:
        next_phase = "awaiting_answer"

    question_type = parsed_json.get("question_type")
    check_options = parsed_json.get("check_options") or []

    # Guardrail mirrored from tutor.py: any spoken question must mount chips.
    speech_asks_question = "?" in speech_out
    if next_phase != "complete" and speech_asks_question and not check_options:
        logger.warning(f"{stag} Speech asked a question but emitted 0 check_options; auto-populating.")
        question_type = "understanding"
        check_options = chips_for(UNDERSTANDING_CHIPS, language)
    elif not speech_asks_question and next_phase != "complete":
        # A pure transition/explanation — nothing to answer, no chips to mount.
        question_type = None
        check_options = []

    if turn_failed:
        err_payload = {"type": "turn_error", "message": "Something went wrong — retrying turn", "turn_failed": True}
        assert_no_forbidden_keys(err_payload)
        yield f"event: turn_error\ndata: {json.dumps(err_payload)}\n\n"

    # 1. Board events (before speech, so the whiteboard isn't a beat behind audio)
    board_events = _sanitize_board_events(parsed_json.get("board_events"))
    if board_events:
        board_payload = {"events": board_events}
        assert_no_forbidden_keys(board_payload)
        yield f"event: board_events\ndata: {json.dumps(board_payload)}\n\n"

    # 2. Speech — always voiced in full; this mode has no silent-caption
    # checkpoint convention, every question is spoken.
    speech_payload = {"delta": speech_out, "ends_in_checkpoint": False}
    assert_no_forbidden_keys(speech_payload)
    yield f"event: speech\ndata: {json.dumps(speech_payload)}\n\n"

    # 3. Meta — always "segment 1 of 1" for this mode.
    meta_payload = {
        "segment_index": 1,
        "total_segments": 1,
        "session_complete": next_phase == "complete",
    }
    assert_no_forbidden_keys(meta_payload)
    yield f"event: meta\ndata: {json.dumps(meta_payload)}\n\n"

    # The Ask Sheet needs the QUESTION, not the last thing that was said.
    question_text = None
    if check_options:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", speech_out) if s.strip()]
        asked = [s for s in sentences if s.endswith("?")]
        question_text = asked[-1] if asked else (sentences[-1] if sentences else None)

    # 4. Persist. Not safe to swallow: the next turn reads phase fresh from the
    # DB to decide where to resume, so a failed write would leave the client
    # and the DB disagreeing about session state. One retry, then propagate.
    session_update = {
        "phase": next_phase,
        "completed_at": "now()" if next_phase == "complete" else None,
    }
    try:
        supabase.table("drona_sessions").update(session_update).eq("id", session_id).execute()
    except Exception as session_update_err:
        logger.warning(f"{stag} drona_sessions update failed, retrying once: {session_update_err}")
        supabase.table("drona_sessions").update(session_update).eq("id", session_id).execute()

    # 5. Audit row — no grade/mistake_tag concept in this mode.
    try:
        turns_res = supabase.table("drona_turns").select("turn_index").eq("session_id", session_id).execute()
        turn_index = len(turns_res.data or []) + 1
        supabase.table("drona_turns").insert([{
            "session_id": session_id,
            "turn_index": turn_index,
            "segment_index": 1,
            "phase_in": phase_in,
            "utterance": utterance,
            "raw_response": json.dumps(parsed_json),
            "grade": None,
            "input_tokens": input_tokens,
            "cache_hit_tokens": cache_hit_tokens,
            "output_tokens": output_tokens,
            "board_event_count": len(board_events),
        }]).execute()
    except Exception as db_ins_err:
        logger.warning(f"{stag} Insert into drona_turns warning: {db_ins_err}")

    if offtopic_tier == 5:
        try:
            supabase.table("drona_wellbeing_flags").insert([{
                "session_id": session_id,
                "user_id": user_id,
                "utterance": utterance,
            }]).execute()
        except Exception as e:
            logger.warning(f"{stag} Optional insert into drona_wellbeing_flags skipped: {e}")

    state_payload = {
        "phase": next_phase,
        "question_type": question_type,
        "check_options": check_options,
        "question_text": question_text,
        "answer_result": None,
    }
    assert_no_forbidden_keys(state_payload)
    yield f"event: state\ndata: {json.dumps(state_payload)}\n\n"
    if next_phase == "complete":
        state_payload["reason"] = "session_ended"
        assert_no_forbidden_keys(state_payload)
        yield f"event: state\ndata: {json.dumps(state_payload)}\n\n"

    yield "event: done\ndata: {}\n\n"


def _sanitize_board_events(raw_events) -> list:
    """Mirrors tutor.py's board-event cleanup: drops empty/duplicate content,
    keeps `text` and `latex` events cleanly separated."""
    if not raw_events:
        return []
    sanitized = []
    seen = set()
    for idx, evt in enumerate(raw_events, 1):
        if not isinstance(evt, dict):
            continue
        e_type = evt.get("type", "text")
        raw_text = evt.get("text") or ""
        raw_latex = evt.get("latex") or ""

        clean_evt = {
            "seq": evt.get("seq", idx),
            "type": e_type,
            "emphasis": evt.get("emphasis", "normal"),
        }
        if e_type == "formula":
            content_key = (raw_latex or raw_text).strip()
            clean_evt["latex"] = content_key
        else:
            content_key = (raw_text or raw_latex).strip()
            clean_evt["text"] = content_key

        if content_key and content_key.lower() not in seen:
            seen.add(content_key.lower())
            sanitized.append(clean_evt)
    return sanitized
