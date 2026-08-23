"""Turn processor shared by the question-scoped Drona modes.

A scoped session is a disposable, single-subject "talk to the teacher"
conversation — practice_explain (launched from a question the student just
answered) and doubt_of_day (launched from the dashboard's doubt card). Neither
is a lesson: no segments, no board-pacing, no quiz cadence, no rubric grading.
So neither reuses tutor.py's process_tutor_turn_stream() or state.py's
compute_next_session_state(), both of which are built entirely around the
multi-segment authored lesson_plans pedagogy.

What every scoped mode does share is the whole turn mechanic: one LLM call
against a mode-specific prompt plus a frozen JSON seed, the same JSON-repair
retry, the same chips guardrail, the same persistence, and the same SSE event
contract (board_events, speech, meta, state, done) that tutor.py emits — so
app/drona/live_session_ws.py forwards it unchanged, already being
mode-agnostic about whatever event/data lines a turn generator yields.

The modes differ in exactly four things, which is what this module takes as
parameters: which prompt file to load, which session column holds the seed,
what to label that seed in the prompt, and which two chips to fall back on
when the tutor asks a question without offering any.
"""
import json
import logging
import re
import time
from typing import Any, AsyncGenerator, Dict, List

from app.db import supabase
from app.drona.models import get_drona_client, get_drona_async_client, get_model_name, TUTOR_TIMEOUT_S
from app.drona.prompt_loader import load_prompt
from app.drona.json_utils import assert_no_forbidden_keys, parse_tutor_json, strip_fences
from app.drona.persona import AUDIO_UNCLEAR, UNDERSTANDING_CHIPS, chips_for, copy_for, normalize_language, persona_for

logger = logging.getLogger("drona.scoped_turn")

# Chunks are retrieved once per scoped session and reused for every follow-up.
# A scoped session is about ONE question, so the passages relevant on turn 1 are
# still the relevant ones on turn 4 — and re-embedding the student's utterance
# every turn would add an OpenAI round trip to each reply for no new grounding.
# session_id -> reference block (or "" when the chapter could not be resolved).
_GROUNDING_CACHE: Dict[str, str] = {}
GROUNDING_CHUNKS = 5


def _resolve_chapter_id(session: Dict[str, Any]) -> str | None:
    """The chapter whose master PDF should ground this doubt.

    Scoped sessions carry no chapter_id of their own — they are launched from a
    question, not a chapter — so it comes from the question they were seeded
    with. match_pdf_chunks requires a chapter filter (a null filter returns
    nothing), so without this there is no retrieval at all.
    """
    if session.get("chapter_id"):
        return session["chapter_id"]
    qid = session.get("question_id")
    if not qid:
        return None
    try:
        rows = (
            supabase.table("questions")
            .select("chapter_id, chapter_name, subject")
            .eq("id", qid).limit(1).execute().data
        ) or []
        if not rows:
            return None
        q = rows[0]
        if q.get("chapter_id"):
            return q["chapter_id"]

        # questions.chapter_id is populated on only ~2% of the bank, but
        # chapter_name is set on ~98% — so the name is the usable link. Matched
        # with subject because chapter names are not unique on their own
        # ("Probability" exists in both Class 11 and Class 12 maths).
        name = (q.get("chapter_name") or "").strip().lower()
        subject = (q.get("subject") or "").strip().lower()
        if not name:
            return None
        for c in _chapters_by_name():
            if c["_name"] == name and (not subject or c["_subject"] == subject):
                return c["id"]
        return None
    except Exception as err:
        logger.warning(f"Could not resolve chapter for grounding: {err}")
        return None


_CHAPTERS_CACHE: List[Dict[str, Any]] = []


def _chapters_by_name() -> List[Dict[str, Any]]:
    """All 106 chapters, normalised for name matching. Cached — this list is
    static relative to a process lifetime and is read on every ungrounded
    doubt."""
    global _CHAPTERS_CACHE
    if not _CHAPTERS_CACHE:
        rows = supabase.table("chapters").select("id, name, subject").execute().data or []
        _CHAPTERS_CACHE = [
            {**r, "_name": (r.get("name") or "").strip().lower(),
             "_subject": (r.get("subject") or "").strip().lower()}
            for r in rows
        ]
    return _CHAPTERS_CACHE


def _grounding_block(session: Dict[str, Any], seed: Dict[str, Any]) -> str:
    """Passages from the master PDF for the question this session is about.

    Doubt answers used to come from the model's own knowledge alone — the
    pdf_chunks corpus was wired into the planner and nowhere else, so improving
    the master content made lessons better and did nothing for doubts. This
    puts the same corpus behind the doubt paths.

    Returns "" and never raises: an ungrounded answer is the previous
    behaviour, whereas an exception here would cost the student their reply.
    """
    sid = session["id"]
    if sid in _GROUNDING_CACHE:
        return _GROUNDING_CACHE[sid]

    block = ""
    try:
        chapter_id = _resolve_chapter_id(session)
        if chapter_id:
            # The question itself is the query, not the student's utterance:
            # follow-ups like "why?" or "explain again" carry no retrievable
            # content, and the passages that matter are the ones about the
            # question the whole session is scoped to.
            query = " ".join(str(seed.get(k) or "") for k in
                             ("question_text", "doubt_text", "stem")).strip()
            if query:
                from app.drona.retrieval import retrieve_pdf_chunks
                chunks = retrieve_pdf_chunks(chapter_id, query, top_k=GROUNDING_CHUNKS)
                if chunks:
                    lines = ["[REFERENCE — master PDF for this chapter. Use it for accuracy;",
                             " prefer it over recall when the two disagree. Never read it aloud verbatim.]"]
                    for i, c in enumerate(chunks, 1):
                        lines.append(f"Passage {i}: {(c.get('content') or '').strip()[:1200]}")
                    block = "\n".join(lines)
                    logger.info(f"📚 [DOUBT GROUNDED] {len(chunks)} chunks from chapter {str(chapter_id)[:8]}")
        if not block:
            logger.info("📚 [DOUBT UNGROUNDED] no chapter/chunks resolved — answering from model knowledge")
    except Exception as err:
        logger.warning(f"⚠️ [DOUBT GROUNDING FAILED] {err} — answering ungrounded")
        block = ""

    _GROUNDING_CACHE[sid] = block
    return block


async def process_scoped_turn_stream(
    session: Dict[str, Any],
    user_id: str,
    utterance: str | None,
    turn_type: str,
    *,
    mode_label: str,
    prompt_file: str,
    seed_key: str,
    seed_header: str,
    opening_chips: Dict[str, list] | None = None,
    extra_state: Dict[str, Any] | None = None,
) -> AsyncGenerator[str, None]:
    session_id = session["id"]
    phase_in = session.get("phase", "teaching")
    seed = session.get(seed_key) or {}
    language = normalize_language(session.get("language"))
    persona = persona_for(session.get("tutor_voice"))
    is_opening_turn = turn_type == "teaching"

    stag = f"[s:{session_id[:8]}][{mode_label}]"
    logger.info(f"{stag} TURN START  phase={phase_in} turn_type={turn_type} opening={is_opening_turn}")

    # The chips the tutor is told to use on turn 1, and the ones we fall back
    # to if it asks a question and offers none. A mode that withholds the
    # answer on turn 1 (doubt_of_day) needs "I'll guess"/"just tell me" there,
    # not "that's clear" — nothing has been explained yet for it to be clear.
    turn_chips: List[str] = chips_for(
        opening_chips if (opening_chips and is_opening_turn) else UNDERSTANDING_CHIPS,
        language,
    )

    system_content = f"{load_prompt(prompt_file)}\n\n[{seed_header}]\n{json.dumps(seed, sort_keys=True)}"
    grounding = _grounding_block(session, seed)
    if grounding:
        system_content = f"{system_content}\n\n{grounding}"
    session_state_ctx = {
        "language": language,
        "tutor_gender": persona["gender"],
        "tutor_name": persona["name"],
        "is_opening_turn": is_opening_turn,
        "turn_type": turn_type,
        **(extra_state or {}),
    }
    if opening_chips:
        session_state_ctx["opening_chips"] = chips_for(opening_chips, language)

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
        check_options = turn_chips
    elif not speech_asks_question and next_phase != "complete":
        # A pure transition/explanation — nothing to answer, no chips to mount.
        question_type = None
        check_options = []

    if turn_failed:
        err_payload = {"type": "turn_error", "message": "Something went wrong — retrying turn", "turn_failed": True}
        assert_no_forbidden_keys(err_payload)
        yield f"event: turn_error\ndata: {json.dumps(err_payload)}\n\n"

    # 1. Board events (before speech, so the whiteboard isn't a beat behind audio)
    board_events = sanitize_board_events(parsed_json.get("board_events"))
    if board_events:
        board_payload = {"events": board_events}
        assert_no_forbidden_keys(board_payload)
        yield f"event: board_events\ndata: {json.dumps(board_payload)}\n\n"

    # 2. Speech — always voiced in full; these modes have no silent-caption
    # checkpoint convention, every question is spoken.
    speech_payload = {"delta": speech_out, "ends_in_checkpoint": False}
    assert_no_forbidden_keys(speech_payload)
    yield f"event: speech\ndata: {json.dumps(speech_payload)}\n\n"

    # 3. Meta — always "segment 1 of 1" for these modes.
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

    # 5. Audit row — no grade/mistake_tag concept in these modes.
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


def sanitize_board_events(raw_events) -> list:
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
