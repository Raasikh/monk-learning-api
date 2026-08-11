import re
import math
import json
import time
import asyncio
import logging
from typing import Dict, Any, AsyncGenerator
from app.db import supabase
from app.drona.models import get_drona_client, get_drona_async_client, get_model_name, TUTOR_TIMEOUT_S
from app.drona.prompt_loader import load_prompt
from app.drona.state import compute_next_session_state
from app.drona.voice_proxy import RumikConnectionPool, split_into_sentences
from app.drona.persona import (
    AUDIO_UNCLEAR,
    QUESTION_STEM,
    PROCEDURAL_CHIPS,
    UNDERSTANDING_CHIPS,
    chips_for,
    copy_for,
    normalize_language,
    normalize_voice,
    persona_for,
)

logger = logging.getLogger("drona.tutor")

# A segment ends with a short quiz on what was just taught. Every answer moves
# on — right or wrong — and only the last question closes the segment.
QUIZ_QUESTIONS_PER_SEGMENT = 3

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

def assert_no_forbidden_keys(payload: dict):
    """Strict R3 assertion: server-side-only fields must never reach the client."""
    for k in FORBIDDEN_SSE_KEYS:
        if k in payload:
            raise ValueError(f"R3 VIOLATION: Forbidden server-side key '{k}' in client payload: {payload}")

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

def parse_partial_json(raw_text: str) -> Dict[str, Any] | None:
    """Best-effort parse of a JSON object that is still being streamed.

    Closes whatever strings/brackets are still open at the point `raw_text`
    was cut off, then parses. Any field whose closing token was already
    present in `raw_text` decodes to its real, complete value; a field still
    mid-generation decodes to a truncated value (or is dropped if it hadn't
    started). Returns None if even that can't be parsed.
    """
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in raw_text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if stack:
                    stack.pop()

    closed = raw_text
    if in_string:
        closed += '"'
    for opener in reversed(stack):
        closed += "}" if opener == "{" else "]"

    try:
        result = json.loads(closed)
        return result if isinstance(result, dict) else None
    except Exception:
        return None

def top_level_key_complete(raw_text: str, key: str) -> bool | None:
    """Whether `key`'s value is fully, literally present in a streamed JSON
    object — independent of what order the model actually emits keys in.

    The early-flush check below used to gate on a LATER key's substring
    ("grade") appearing, reasoning that the schema lists check_options before
    grade. That only holds if the model's output always matches the example
    order in the prompt — the prompt only actually mandates that `speech` is
    first, nothing else. A model that grades before it re-teaches could
    plausibly emit `grade` before `check_options`, at which point
    parse_partial_json's `check_options` reads as absent-or-empty (not simply
    "not yet true") and the flush decision would be made on data that hadn't
    been generated yet.

    Returns True if `key`'s value is closed in the raw source (safe to trust),
    False if `key` hasn't appeared at all, None if it's present but its value
    is still mid-generation (also not safe to trust).
    """
    marker = f'"{key}"'
    idx = raw_text.find(marker)
    if idx == -1:
        return False

    i = idx + len(marker)
    while i < len(raw_text) and raw_text[i] in " \t\n\r":
        i += 1
    if i >= len(raw_text) or raw_text[i] != ":":
        return None
    i += 1
    while i < len(raw_text) and raw_text[i] in " \t\n\r":
        i += 1
    if i >= len(raw_text):
        return None

    first_ch = raw_text[i]
    if first_ch == '"':
        i += 1
        escape = False
        while i < len(raw_text):
            ch = raw_text[i]
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                return True
            i += 1
        return None

    if first_ch in "{[":
        depth = 0
        in_string = False
        escape = False
        while i < len(raw_text):
            ch = raw_text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch in "{[":
                    depth += 1
                elif ch in "}]":
                    depth -= 1
                    if depth == 0:
                        return True
            i += 1
        return None

    # Bare literal (null / true / false / a number) — closed once we hit
    # whatever terminates it.
    j = i
    while j < len(raw_text) and raw_text[j] not in ",}] \t\n\r":
        j += 1
    return True if j < len(raw_text) else None

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
    language = normalize_language(session.get("language"))
    # Persona is chosen by the student at session start (migrations/0011). Pre-0011
    # rows have no tutor_voice, so normalize_voice() falls back to the 'female'
    # default this used to hardcode.
    persona = persona_for(session.get("tutor_voice"))

    # 2. SELECT plan_json FROM lesson_plans
    plan_row = None
    if plan_id:
        plan_res = supabase.table("lesson_plans").select("*").eq("id", plan_id).execute()
        if plan_res.data:
            plan_row = plan_res.data[0]

    plan_json = plan_row.get("plan_json") if plan_row else {}
    segments = plan_json.get("segments") or []

    # With streaming authoring, segments 2..N land while segment 1 is being
    # taught. total_segments must come from the PLANNED count, not the count
    # authored so far — otherwise the state machine sees "segment 1 of 1" and
    # jumps to wrapup the moment the first checkpoint is graded.
    planned_total = plan_json.get("_expected_segments")
    total_segments = int(planned_total) if planned_total else (len(segments) if segments else 1)

    if plan_id and curr_seg_idx > len(segments) and curr_seg_idx <= total_segments:
        # The student has outrun the background author. Re-read once — the fill
        # runs 4-wide and normally finishes long before segment 1 is over.
        time.sleep(3.0)
        refetch = supabase.table("lesson_plans").select("plan_json").eq("id", plan_id).execute()
        if refetch.data:
            plan_json = refetch.data[0].get("plan_json") or plan_json
            segments = plan_json.get("segments") or segments
        if curr_seg_idx > len(segments):
            logger.error(
                f"❌ [SEGMENT NOT AUTHORED YET] session={session_id[:8]} wants segment {curr_seg_idx} "
                f"but only {len(segments)} of {total_segments} are written. Holding on the last "
                f"available segment rather than failing the turn."
            )

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

    # DISABLED — in-memory plan extension (consolidation segment on weak mastery).
    #
    # This appended a 10th segment to a 9-segment plan in memory only. The
    # session row then persisted current_segment=10, but the next turn re-read
    # the 9-segment plan from the DB, the condition above no longer matched
    # (10 != 9), the clamp below pulled the index back to 9, its checkpoint
    # advanced to 10 again — and the session flapped 9/10/9/10 forever without
    # ever reaching wrapup. Measured end-to-end: turns 28-35 of a 9-segment run.
    #
    # Re-implement as a persisted plan extension (write the extra segment into
    # lesson_plans.plan_json) if the pedagogy is wanted; it cannot work as
    # per-turn in-memory state.
    #
    # if curr_seg_idx == total_segments and overall_mastery in ("moderate", "needs_practice"):
    #     ... append consolidation_seg ...

    # Clamp current segment index. Overshoot is now impossible from the block
    # above, but a stale session row can still point past a regenerated plan.
    if curr_seg_idx > total_segments:
        logger.warning(
            f"⚠️ [SEGMENT OVERSHOOT] session={session_id[:8]} current_segment={curr_seg_idx} "
            f"exceeds plan segment count {total_segments}; clamping to final segment."
        )
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
    questions_already_asked = []
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
                # Every question sentence already voiced this segment. The
                # prompt's "never re-ask a checkpoint question" rule had no
                # data to check against — the model can't avoid repeating a
                # question it was never shown. Measured: turn 2 re-asking turn
                # 1's bullet-drop question in fresh words.
                prior_speech = raw.get("speech") or ""
                for sent in re.split(r"(?<=[.!?])\s+", prior_speech):
                    sent = sent.strip()
                    if sent.endswith("?") and sent not in questions_already_asked:
                        questions_already_asked.append(sent)
    except Exception as b_err:
        logger.warning(f"Failed to load segment board events: {b_err}")

    # ── Re-teach handling ──────────────────────────────────────────────────
    # "Teach me again" must re-explain the SAME sub-concept differently. Two
    # things follow from that: the board slice must NOT advance (otherwise the
    # student is shown the next items while asking to revisit the last ones),
    # and the turn must not carry a quiz — the only question allowed is "did
    # that land?". Capped at two re-explanations, then the lesson moves on.
    RETEACH_RE = re.compile(
        r"dubara samjh|dobara samjh|phir se samjh|teach me again|explain (that |it )?again|"
        r"go over (that|it) again|didn'?t (get|understand)|samajh nahi",
        re.IGNORECASE,
    )
    MAX_RETEACHES_PER_SEGMENT = 2

    is_reteach_request = bool(utterance and RETEACH_RE.search(utterance))
    prior_reteaches = 0
    try:
        for t in (seg_turns_res.data or []):
            prior_utt = t.get("utterance") or ""
            if prior_utt and RETEACH_RE.search(prior_utt):
                prior_reteaches += 1
    except Exception:
        prior_reteaches = 0

    reteach_exhausted = prior_reteaches >= MAX_RETEACHES_PER_SEGMENT
    do_reteach = is_reteach_request and not reteach_exhausted

    # Hold the slice steady across re-teach turns so the same items are revisited.
    effective_turn = max(1, turn_within_segment - prior_reteaches - (1 if is_reteach_request else 0))
    if is_reteach_request:
        logger.info(
            f"{stag}   RETEACH      request #{prior_reteaches + 1}/{MAX_RETEACHES_PER_SEGMENT} "
            f"| holding slice at turn {effective_turn} | exhausted={reteach_exhausted}"
        )

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
    
    # effective_turn, not turn_within_segment: a re-teach revisits the slice it
    # already showed rather than advancing to the next one.
    if effective_turn == 1:
        assigned_start = 0
        assigned_end = min(items_per_turn, N)
    elif effective_turn == 2:
        assigned_start = min(items_per_turn, N)
        assigned_end = min(2 * items_per_turn, N)
    else:
        assigned_start = min(2 * items_per_turn, N)
        assigned_end = N
    
    assigned_items = board_content_list[assigned_start:assigned_end]
    # The turn that grades the final question only wraps up; re-emitting the last
    # slice there would redraw board lines the student already has.
    if phase_in == "awaiting_answer" and effective_turn > QUIZ_QUESTIONS_PER_SEGMENT:
        assigned_items = []
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
        "tutor_gender": persona["gender"],
        "tutor_name": persona["name"]
    }

    # A segment only advances when its authored checkpoint is GRADED. Two
    # distinct failure modes had to be closed here:
    #   1. Left alone the tutor posts lightweight check after lightweight check
    #      — all ungraded by design — and never reaches the checkpoint.
    #   2. Once it does ask the checkpoint, it must grade the reply rather than
    #      re-ask. Prompting for the question on every late turn made it re-ask
    #      forever and the segment never ended.
    # So: ask when we are not waiting on an answer, grade when we are.
    checkpoint = curr_segment.get("checkpoint") or {}
    # wrapup_points is authored as one key takeaway per segment and was only
    # being used at end-of-session. It is exactly the per-segment recap line.
    wrapup_points = plan_json.get("wrapup_points") or []
    segment_takeaway = (
        wrapup_points[curr_seg_idx - 1]
        if 0 <= curr_seg_idx - 1 < len(wrapup_points)
        else curr_segment.get("objective") or "what we just covered"
    )
    checkpoint_directive = ""
    if do_reteach:
        checkpoint_directive = f"""
[RE-TEACH — THE STUDENT ASKED YOU TO EXPLAIN THIS AGAIN]
Re-explain the SAME material you just covered. Do not move on to new content.

  - Use a DIFFERENT route than last time: a different analogy, a more concrete
    example, smaller steps, or a worked instance instead of the abstract statement.
    Never repeat your previous wording or your previous analogy.
  - Emit the SAME board items again — they are already on the board, so reinforce
    them; do not invent new ones and do not pull items from the next sub-concept.
  - Ask NO quiz and NO checkpoint question this turn. Set "grade": null.
  - End with exactly one question: whether it makes sense now.
    Set "question_type": "understanding", "phase_request": "awaiting_answer".

This is re-explanation {prior_reteaches + 1} of {MAX_RETEACHES_PER_SEGMENT}.
"""
    elif is_reteach_request and reteach_exhausted:
        checkpoint_directive = f"""
[RE-TEACH LIMIT REACHED — MOVE ON GENTLY]
You have already re-explained this {MAX_RETEACHES_PER_SEGMENT} times. Do not re-explain a third time.
Give the single clearest one-line summary of the idea, reassure the student that it will
click as they see it used, and then continue to the next sub-concept of this segment.
Set "grade": null.
"""
    elif phase_in == "awaiting_answer":
        # One question per turn. Turn N asks question N, so this turn grades
        # question (N-1) and then either teaches the next slice and asks the
        # next question, or closes the segment.
        #
        # Three questions in a row at the end of a segment was overwhelming;
        # a single question after each explanation is easier to sit through.
        grading_index = max(1, effective_turn - 1)
        is_final = grading_index >= QUIZ_QUESTIONS_PER_SEGMENT

        verdict_rules = f"""
[GRADE THE ANSWER TO QUESTION {grading_index} OF {QUIZ_QUESTIONS_PER_SEGMENT} — MANDATORY]
Set "grade" to "correct", "partial" or "incorrect" — never null.
  - Correct -> one short line of praise ("That's very good.") and move straight on.
  - Wrong   -> say plainly that it is not correct, then give the right answer in ONE
               sentence. Never re-ask the question and never labour the point.
  - Never call a wrong answer correct. An irrelevant or nonsense reply is "incorrect".
    Do not award "correct" for confidence, length, or technical words — check the content.
"""

        if is_final:
            checkpoint_directive = verdict_rules + f"""
[THEN CLOSE THE SEGMENT — NO FURTHER QUESTION]
That was the last question of this segment. After the verdict, give ONE sentence tying
the segment together, built around: "{segment_takeaway}"

Then STOP. Do not ask anything — not a quiz question, not "shall we move on", not
"would you like me to explain again". Answering the last question is itself the signal
that the student is ready, and the next segment follows automatically.
Set "question_type": null and "check_options": [].
"""
        else:
            checkpoint_directive = verdict_rules + f"""
[THEN TEACH THE NEXT PART AND ASK QUESTION {grading_index + 1} OF {QUIZ_QUESTIONS_PER_SEGMENT}]
After the verdict, teach your assigned board items for this turn, then close with ONE
quick question on what you just explained.

Keep it easy — straight recall of something now written on the board, answerable in a
couple of words with almost no working. Set "question_type": "checkpoint" and emit 3
short option chips, exactly one of which is right. Ask ONE question only.

SPEAK THE QUESTION. Your `speech` must literally contain the question, phrased as a
question and ending in a question mark. Do NOT end the turn on a transition line such
as 'Next, we will see...' or 'Let us move on...' — the question is the LAST thing the
student hears this turn. Options on screen with no spoken question are meaningless.

MAKE THE QUESTION EARN ITS PLACE. Do not simply turn the sentence you just said back
into a question — if you just said 'the horizontal acceleration is zero', do not ask
'what is the horizontal acceleration?'. Ask something that makes the student USE the
idea: apply it to a small concrete case, compare two situations, or spot the
consequence. It must still be answerable in a couple of words with no working.
"""
    else:
        checkpoint_directive = f"""
[TEACH, THEN ASK QUESTION 1 OF {QUIZ_QUESTIONS_PER_SEGMENT}]
Open the segment and explain your assigned board items in full. THEN, once the
explanation is complete, close with ONE quick question on what you just taught.

Never open with the question — teach first, ask second.
Keep the question easy: straight recall of something now written on the board,
answerable in a couple of words with almost no working. Set "question_type":
"checkpoint" and emit 3 short option chips, exactly one of which is right.

SPEAK THE QUESTION. Your `speech` must literally contain the question, phrased as a
question and ending in a question mark. Do NOT end the turn on a transition line such
as 'Next, we will see...' or 'Let us move on...' — the question is the LAST thing the
student hears this turn. Options on screen with no spoken question are meaningless.

MAKE THE QUESTION EARN ITS PLACE. Do not simply turn the sentence you just said back
into a question — if you just said 'the horizontal acceleration is zero', do not ask
'what is the horizontal acceleration?'. Ask something that makes the student USE the
idea: apply it to a small concrete case, compare two situations, or spot the
consequence. It must still be answerable in a couple of words with no working.

For reference, this segment's authored checkpoint is:
  "{checkpoint.get('question') or ''}"
You may use it as one of the questions if it is genuinely quick to answer.
"""


    system_content = f"{tutor_prompt}\n\n[LESSON PLAN]\n{json.dumps(plan_json, sort_keys=True)}"
    user_content = f"""[CURRENT SEGMENT]
{json.dumps(curr_segment, sort_keys=True)}

[TURN WITHIN SEGMENT]
This is Turn {turn_within_segment} of 3 in this segment.

[BOARD EVENTS ALREADY EMITTED IN THIS SEGMENT]
{json.dumps(current_segment_board_events, indent=2)}

[QUESTIONS ALREADY ASKED IN THIS SEGMENT — NEVER RE-ASK THESE]
{json.dumps(questions_already_asked, indent=2)}
Your question this turn must test something NOT covered by any question above —
not the same fact reworded, not the same scenario with new objects. If the list
already covers your assigned sub-concept, ask about a different consequence or
application of it.

[YOUR ASSIGNED BOARD ITEMS FOR THIS TURN]
You MUST emit EXACTLY these {len(assigned_items)} board items in this turn — no more, no fewer, no substitutions:
{json.dumps(assigned_items_text, indent=2)}

[TEACHING TURN — ASK NOTHING]
Explain your assigned board items and stop. Do NOT ask a question, a check, or a
check-in this turn. No question marks in `speech`. All questions for this segment
are asked at the end of the segment, not between explanations.
End with a short bridging line into the next idea.

[PROGRESSIVE ARC DIRECTIVE]
1. Emit ONLY the items listed in [YOUR ASSIGNED BOARD ITEMS FOR THIS TURN]. Do NOT emit items assigned to other turns.
2. DO NOT re-emit any items from [BOARD EVENTS ALREADY EMITTED IN THIS SEGMENT].
3. Teach ONLY the sub-concept(s) covered by your assigned board items.
4. If student answered correctly, give 1 short sentence of praise, then teach your assigned sub-concept(s).
5. Any check must test ONLY concepts explained in THIS turn or previous turns of this segment.

{checkpoint_directive}
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
    async_client = get_drona_async_client()

    def _sanitize_board_events(model_board_events_raw):
        """Builds the client-facing board_events. When the turn has assigned
        plan items, those authored objects are emitted verbatim — the model's
        own board_events are never sent — so this needs nothing from the LLM
        response and can run before the turn's LLM call has even finished."""
        if assigned_items:
            board_events_out = []
            for i, item in enumerate(assigned_items, 1):
                if isinstance(item, dict):
                    evt = {
                        "seq": i,
                        "type": item.get("type") or ("formula" if item.get("latex") else "text"),
                        "emphasis": item.get("emphasis", "normal"),
                    }
                    if item.get("latex"):
                        evt["latex"] = item["latex"]
                    else:
                        evt["text"] = item.get("text", "")
                    board_events_out.append(evt)
                else:
                    board_events_out.append({"seq": i, "type": "text", "text": str(item), "emphasis": "normal"})
        else:
            board_events_out = model_board_events_raw or []

        sanitized = []
        seen = set()
        for idx, evt in enumerate(board_events_out, 1):
            e_type = evt.get("type", "text")
            raw_text = evt.get("text") or ""
            raw_latex = evt.get("latex") or ""

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

            if content_key and content_key.lower() not in seen:
                seen.add(content_key.lower())
                sanitized.append(clean_evt)
            elif content_key:
                logger.warning(f"⚠️ [PROMPT VIOLATION] Dropped duplicate board_event content: '{content_key}'")
        return sanitized

    # 4. LLM call with JSON robustness (§4.4), streamed so speech and board
    # events can reach the client the moment they're SAFE to send, instead of
    # after the model also finishes grading/phase-transition fields and the
    # turn's DB writes run.
    #
    # "speech" is always the JSON's first key (enforced in prompts/tutor.md) and
    # board_events for an assigned-items turn don't depend on the model at all,
    # so both are knowable well before the response is complete. The one thing
    # that can still rewrite `speech` after the fact is the chips-without-a-
    # question repair below, which needs `check_options` — checked via
    # top_level_key_complete() rather than assuming it precedes some later key
    # in generation order, since the prompt only actually mandates that
    # `speech` comes first. If the check wouldn't fire, speech/board_events are
    # flushed right there; if it would, nothing is flushed and the existing
    # post-stream repair path runs exactly as before. Restricted to turns with
    # assigned plan items: that's the only case where board_events don't need
    # anything from the model, so nothing here depends on unverified model
    # output.
    raw_response_text = ""
    input_tokens = 0
    output_tokens = 0
    cache_hit_tokens = 0
    streamed_speech = ""
    early_flushed = False
    board_events_flushed = False

    turn_failed = False
    llm_t0 = time.time()

    try:
        stream = await async_client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=2048,
            stream=True,
            stream_options={"include_usage": True},
            timeout=TUTOR_TIMEOUT_S,
            extra_body={"thinking": {"type": "disabled"}}
        )

        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage:
                input_tokens = getattr(usage, "prompt_tokens", 0) or input_tokens
                output_tokens = getattr(usage, "completion_tokens", 0) or output_tokens
                details = getattr(usage, "prompt_tokens_details", None)
                if details:
                    cache_hit_tokens = getattr(details, "cached_tokens", 0) or cache_hit_tokens

            if not chunk.choices:
                continue

            returned_model = getattr(chunk, "model", "")
            if returned_model and returned_model != model_name:
                raise RuntimeError(f"STRICT R1 MODEL VIOLATION: Requested '{model_name}', but API returned '{returned_model}'")

            delta_text = chunk.choices[0].delta.content or ""
            if not delta_text:
                continue
            raw_response_text += delta_text

            if (
                not early_flushed
                and assigned_items
                and top_level_key_complete(raw_response_text, "speech") is True
                and top_level_key_complete(raw_response_text, "check_options") is True
            ):
                partial = parse_partial_json(raw_response_text)
                speech_so_far = partial.get("speech") if partial else None
                if partial is not None and isinstance(speech_so_far, str):
                    check_options_so_far = partial.get("check_options") or []
                    needs_retry = bool(check_options_so_far) and "?" not in speech_so_far
                    if not needs_retry:
                        # Logged before yielding: a yield suspends this generator
                        # until the consumer (which synthesizes+sends TTS audio,
                        # several seconds of work) asks for the next item, so a
                        # timestamp taken after the yields would measure that
                        # consumer work, not how far into the LLM call this is.
                        logger.info(f"{stag}   EARLY FLUSH  speech+board_events ready {time.time() - llm_t0:.1f}s into the LLM call")

                        board_payload = {"events": _sanitize_board_events(partial.get("board_events"))}
                        assert_no_forbidden_keys(board_payload)
                        yield f"event: board_events\ndata: {json.dumps(board_payload)}\n\n"
                        board_events_flushed = True

                        streamed_speech = speech_so_far
                        speech_payload = {"delta": streamed_speech, "ends_in_checkpoint": False}
                        assert_no_forbidden_keys(speech_payload)
                        yield f"event: speech\ndata: {json.dumps(speech_payload)}\n\n"
                        early_flushed = True

    except Exception as e:
        logger.error(f"{stag} Error during LLM turn: {e}")
        turn_failed = True
        if early_flushed:
            # The client already has streamed_speech playing as real audio.
            # Falling back to the generic AUDIO_UNCLEAR phrase here used to
            # send that as a SECOND, non-delta speech event — a jarring
            # non-sequitur voiced right after real content, blamed on the
            # student ("didn't catch that") for a server-side failure. Reusing
            # streamed_speech as the fallback's `speech` means the final delta
            # computed further down comes out empty — nothing more gets said.
            logger.error(f"{stag}   ⚠️ Stream failed AFTER an early flush already reached the client — the client already has '{streamed_speech[:60]}...' playing. Falling back to that text instead of a contradictory generic message.")
            raw_response_text = json.dumps({
                "speech": streamed_speech,
                "board_events": [],
                "phase_request": phase_in,
                "turn_failed": True
            })
        else:
            raw_response_text = json.dumps({
                "speech": copy_for(AUDIO_UNCLEAR, language),
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
                timeout=TUTOR_TIMEOUT_S,
                extra_body={"thinking": {"type": "disabled"}}
            )
            parsed_json = json.loads(strip_fences(retry_res.choices[0].message.content or "{}"))
        except Exception as retry_err:
            logger.error(f"Second JSON parse failure: {retry_err}")
            turn_failed = True
            parsed_json = {
                "speech": copy_for(AUDIO_UNCLEAR, language),
                "board_events": [],
                "phase_request": phase_in,
                "turn_failed": True
            }

    # 5b. First-Turn Teaching Rule Enforcement & Board Content Fallback
    # Teaching turns before the segment's final turn must not ask anything. The
    # lesson explains straight through, and all questions come at the end of the
    # segment. Previously only turn 1 was guarded, so turn 2 popped a quiz mid-
    # explanation and the Ask Sheet sat over the board the whole lesson.
    #
    # Skipped on a re-teach: that turn is *supposed* to end with "did that make
    # sense now?", which this rule would otherwise strip.
    # Every teaching turn now ends with one question, so there is no
    # teaching-only override any more. The closing turn (after the last
    # question is graded) is the only one that must stay silent.
    is_teaching_only_turn = False
    is_segment_closing_turn = phase_in == "awaiting_answer" and effective_turn > QUIZ_QUESTIONS_PER_SEGMENT
    if is_segment_closing_turn:
        if parsed_json.get("check_options"):
            logger.warning(
                f"⚠️ [CLOSING TURN HARD OVERRIDE] Segment is finished; suppressing a trailing question. "
                f"Answering the last quiz question is itself the signal to move on."
            )
        parsed_json["question_type"] = None
        parsed_json["check_options"] = []
        parsed_json["phase_request"] = "teaching"

    # Re-teach hard override: one understanding question, never a quiz, never a
    # grade. Enforced in code because the prompt alone let the model slip a
    # checkpoint question into a re-explanation.
    if do_reteach:
        if parsed_json.get("grade"):
            logger.warning(f"⚠️ [RETEACH HARD OVERRIDE] Model graded a re-teach turn. Forcing grade=null.")
        parsed_json["grade"] = None
        parsed_json["phase_request"] = "awaiting_answer"
        parsed_json["question_type"] = "understanding"
        if not parsed_json.get("check_options"):
            parsed_json["check_options"] = chips_for(UNDERSTANDING_CHIPS, language)
    elif is_reteach_request and reteach_exhausted:
        parsed_json["grade"] = None

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

    speech_out = parsed_json.get("speech") or copy_for(AUDIO_UNCLEAR, language)

    # A turn that offers answer chips MUST voice the question they answer.
    # Measured failure: turns ended on a transition ("Next, we'll see how this
    # shapes the path.") while three options appeared on screen, so the student
    # was shown answers to a question nobody had asked.
    if parsed_json.get("check_options") and "?" not in speech_out:
        logger.warning(f"{stag}   ⚠️ [CHIPS WITHOUT A QUESTION] Speech offers options but asks nothing. Retrying turn.")
        try:
            fix_res = client.chat.completions.create(
                model=model_name,
                messages=messages + [
                    {"role": "assistant", "content": json.dumps(parsed_json)},
                    {"role": "user", "content": (
                        "Your speech offered answer options but never asked the question they answer. "
                        "Re-emit the SAME JSON — same board_events, same check_options — but rewrite "
                        "`speech` so it ENDS with the actual question, phrased as a question and ending "
                        "in '?'. Replace any trailing transition sentence (\"Next, we'll see...\", "
                        "\"Let's move on...\") with that question. Change nothing else."
                    )},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=2048,
                timeout=TUTOR_TIMEOUT_S,
                extra_body={"thinking": {"type": "disabled"}},
            )
            fixed = parse_tutor_json(fix_res.choices[0].message.content or "{}")
            if fixed.get("speech") and "?" in fixed["speech"]:
                parsed_json["speech"] = fixed["speech"]
                if fixed.get("check_options"):
                    parsed_json["check_options"] = fixed["check_options"]
                speech_out = parsed_json["speech"]
                logger.info(f"{stag}   ✅ [QUESTION RESTORED] Retry produced a spoken question.")
            else:
                raise ValueError("retry still contained no question")
        except Exception as q_err:
            # Never leave orphaned chips on screen. A generic stem at least makes
            # the options answerable, and the violation is recorded below.
            logger.error(f"{stag}   ❌ [QUESTION STILL MISSING] {q_err}. Appending an explicit stem.")
            speech_out = speech_out.rstrip() + " " + QUESTION_STEM[normalize_language(language)]
            parsed_json["speech"] = speech_out
    board_out = parsed_json.get("board") or ""
    grade_out = parsed_json.get("grade")
    mistake_tag = parsed_json.get("mistake_tag")
    offtopic_tier = parsed_json.get("offtopic_tier")

    # Tell the state machine whether this was the LAST quiz question. Backend
    # controlled, never the model's to decide — the segment must not close while
    # questions 2 and 3 are still to come.
    if phase_in == "awaiting_answer":
        graded_q = max(1, effective_turn - 1)
        parsed_json["_final_quiz_question"] = graded_q >= QUIZ_QUESTIONS_PER_SEGMENT
        logger.info(
            f"{stag}   QUIZ         grading Q{graded_q}/{QUIZ_QUESTIONS_PER_SEGMENT} "
            f"| final={parsed_json['_final_quiz_question']}"
        )

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
        # Compare against what THIS turn was assigned, not a flat 6. The flat
        # threshold predates per-turn slicing: a segment's 6-9 items are split
        # ceil(N/3) across three turns, so a correct turn emits 2-3 items and
        # was being flagged every single time (34 false positives in one run).
        "under_density": 1 if assigned_items_text and board_cnt < len(assigned_items_text) else 0,
        "over_density": 1 if board_cnt > 12 else 0,
        "missing_options": 1 if parsed_json.get("phase_request") == "awaiting_answer" and not parsed_json.get("check_options") else 0,
        "word_count_exceeded": 1 if word_cnt > 120 else 0,
        "raw_latex_in_text": 1 if any(pat in speech_out for pat in ["\\frac", "\\sqrt", "$$", "^", "_"]) else 0,
        # Segment ran past its 3 authored turns — the checkpoint was asked late
        # or not at all, and the board items are being re-served.
        "segment_overrun": 1 if effective_turn > 3 else 0,
        # Chips offered without the question being spoken (repaired above).
        "chips_without_question": 1 if (parsed_json.get("check_options") and "?" not in (parsed_json.get("speech") or "")) else 0,
    }

    # 7b. HARD FAIL-SAFE GUARDRAIL: every spoken question must mount the Ask
    # Sheet with option chips.
    #
    # This runs BEFORE the drona_sessions write below, and must stay there. It
    # can flip next_phase to 'awaiting_answer', and when it ran after the write
    # the DB kept the pre-guardrail phase: the client mounted the Ask Sheet
    # while the session row still said 'teaching', so the WS post-turn
    # auto-advance re-read 'teaching' and fired another teaching turn straight
    # over the student's unanswered question.
    question_type = parsed_json.get("question_type")
    check_options = parsed_json.get("check_options") or []

    # Detection spans both languages regardless of the session setting — an
    # english session still says "samajh aaya?" occasionally, and a hinglish one
    # routinely mixes in "is that clear?".
    ASKS_QUESTION_RE = (
        r"\?|samajh aaya|clear hai|quick check|kya hoga|bataiye|option"
        r"|make sense|is that clear|shall we|what would|which one|tell me"
    )
    UNDERSTANDING_RE = r"samajh aaya|clear hai|theek hai na|make sense|is that clear"
    PROCEDURAL_RE = r"aage badh|next topic pe|shall we move|shall we continue|ready to move"

    # Suppress only when the lesson is genuinely over. A segment advance must
    # NOT suppress this: the recap turn advances the segment and then asks
    # "ready for the next part?", and that question still needs its chips. The
    # earlier pinning bug came from keying off phase_in rather than next_phase,
    # which is already fixed — seg_advanced does not need to suppress too.
    finished = next_phase in ("wrapup", "complete")

    speech_asks_question = bool(re.search(ASKS_QUESTION_RE, speech_out, re.IGNORECASE))

    # On a teaching-only turn the two guards were fighting: the turn override
    # cleared the question, then this guardrail saw a "?" still in speech and
    # mounted chips again — so turn 2 popped a quiz mid-explanation. The turn
    # override wins; a stray rhetorical "?" just goes unanswered and the lesson
    # auto-advances, which is the intended behaviour there.
    if is_teaching_only_turn:
        if speech_asks_question:
            logger.warning(
                f"{stag}   ⚠️ [TEACHING TURN ASKED A QUESTION] Model put a question in a teach-only "
                f"turn; suppressing the Ask Sheet rather than interrupting the explanation."
            )
        next_phase = "teaching" if next_phase == "awaiting_answer" else next_phase
        question_type = None
        check_options = []
    elif not finished and (speech_asks_question or next_phase == "awaiting_answer"):
        next_phase = "awaiting_answer"
        if not check_options:
            logger.warning(f"⚠️ [HARD PROMPT VIOLATION] Speech asked question but 0 check_options emitted. Auto-populating check_options server-side.")
            if re.search(UNDERSTANDING_RE, speech_out, re.IGNORECASE):
                question_type = "understanding"
                check_options = chips_for(UNDERSTANDING_CHIPS, language)
            elif re.search(PROCEDURAL_RE, speech_out, re.IGNORECASE):
                question_type = "procedural"
                check_options = chips_for(PROCEDURAL_CHIPS, language)
            else:
                question_type = "check"
                check_options = ["Option A", "Option B", "Option C"]

    # 8. UPDATE drona_sessions with persistent telemetry
    #
    # Unlike the turns/misconceptions/wellbeing inserts below, this one is not
    # safe to swallow: it's what actually persists next_phase/next_seg, and
    # the NEXT turn reads the session row fresh from the DB to decide where to
    # resume. Silently continuing on failure would let this turn hand out
    # next_phase to the client while the DB still has the old phase — the
    # client and the DB would disagree about where the session is. One retry
    # for a transient blip; if it still fails, let it propagate so the caller
    # treats this as the failed turn it is, rather than pretending it worked.
    pool = RumikConnectionPool.get_instance()
    ended_reason_val = "complete" if next_phase in ("wrapup", "complete") else None
    session_update = {
        "phase": next_phase,
        "current_segment": next_seg,
        "attempts_on_current_question": next_attempts,
        "history_summary": updated_history,
        "segments_completed": curr_seg_idx if seg_advanced else curr_seg_idx - 1,
        "pool_exhaustion_count": pool.pool_exhaustion_count,
        "ended_reason": ended_reason_val
    }
    try:
        supabase.table("drona_sessions").update(session_update).eq("id", session_id).execute()
    except Exception as session_update_err:
        logger.warning(f"{stag}   ⚠️ drona_sessions update failed, retrying once: {session_update_err}")
        supabase.table("drona_sessions").update(session_update).eq("id", session_id).execute()

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
        # Synthesis frames this turn will actually send to Rumik. The trailing
        # chunk is the checkpoint question, which the WS layer delivers as a
        # silent caption — counting it overstated our RPM usage by one per
        # checkpoint turn and disagreed with the pool's own counter.
        "rumik_requests": max(0, len(split_into_sentences(speech_out)) - (1 if next_phase == "awaiting_answer" else 0)),
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

    if turn_failed:
        err_payload = {"type": "turn_error", "message": "Something went wrong — retrying turn", "turn_failed": True}
        assert_no_forbidden_keys(err_payload)
        yield f"event: turn_error\ndata: {json.dumps(err_payload)}\n\n"

    # 13. Compute board events and finalize phase/check_options BEFORE emitting
    # anything. board_events must reach the client before speech/audio so the
    # whiteboard isn't a beat behind the voice, and ends_in_checkpoint (below)
    # needs the FINAL next_phase, not the pre-guardrail one.
    # The board is authored content that already exists in the plan, with the
    # right type and clean LaTeX. Asking the model to retype it was corrupting
    # it: assigned items were flattened to bare strings, so a formula came back
    # as a `text` event and the board printed "a_x = 0, \quad a_y = -g"
    # literally — or reworded it into LaTeX that KaTeX then rendered in red.
    #
    # So emit the plan's own objects verbatim and let the model own only speech.
    #
    # Both are already on their way to the client if the early-flush path fired
    # above (assigned_items present, chips-without-question repair not needed).
    if not board_events_flushed:
        if assigned_items:
            model_events = parsed_json.get("board_events") or []
            if len(model_events) != len(assigned_items):
                logger.info(
                    f"{stag}   BOARD        using {len(assigned_items)} authored items "
                    f"(model offered {len(model_events)})"
                )
        sanitized_board_events = _sanitize_board_events(parsed_json.get("board_events"))
        if sanitized_board_events:
            board_payload = {"events": sanitized_board_events}
            assert_no_forbidden_keys(board_payload)
            yield f"event: board_events\ndata: {json.dumps(board_payload)}\n\n"
        elif turn_type in ("teaching", "answer"):
            logger.warning(f"⚠️ [PROMPT VIOLATION] Teaching turn in session {session_id} emitted 0 board_events! Tutor LLM omitted board_events array.")

    # ends_in_checkpoint tells the WS layer to skip TTS for the trailing question
    # sentence — the checkpoint question is shown as text only, never voiced.
    #
    # If speech was already streamed early, send only whatever's left beyond
    # what the client already has (normally nothing — the chips-without-
    # question repair, the only thing that can still change `speech`, didn't
    # fire, or the early flush wouldn't have happened). A mismatch here would
    # mean the repair fired anyway or streaming diverged some other way; fall
    # back to resending the full text so the client stays correct, logged
    # since it means this path needs a second look.
    speech_delta = speech_out
    if early_flushed:
        if speech_out.startswith(streamed_speech):
            speech_delta = speech_out[len(streamed_speech):]
        else:
            logger.warning(f"{stag}   ⚠️ [EARLY FLUSH MISMATCH] Final speech diverged from the streamed prefix — resending in full.")
    speech_payload = {"delta": speech_delta, "ends_in_checkpoint": next_phase == "awaiting_answer"}
    assert_no_forbidden_keys(speech_payload)
    yield f"event: speech\ndata: {json.dumps(speech_payload)}\n\n"

    # Word count bounds validation (60-120 words)
    speech_words = [w for w in speech_out.split() if w.strip()]
    word_count = len(speech_words)
    if turn_type in ("teaching", "answer") and not (45 <= word_count <= 135):
        logger.warning(f"⚠️ [PROMPT VIOLATION] Turn speech word count out of target range: {word_count} words (Target: 60-120 words).")

    meta_payload = {
        "segment_index": next_seg if next_phase != "complete" else total_segments,
        "total_segments": total_segments,
        "session_complete": (next_phase == "complete")
    }
    assert_no_forbidden_keys(meta_payload)
    yield f"event: meta\ndata: {json.dumps(meta_payload)}\n\n"

    # answer_result is a deliberate, narrow disclosure: the outcome of the
    # student's OWN answer, which the tutor already states aloud ("Bilkul
    # sahi!"). It lets the UI colour the chip they tapped green or red. It is
    # NOT `grade` — the R3 forbidden key stays out of every client payload, as
    # do model_answer, rubric and expected_misconceptions. Nothing here reveals
    # the answer key for a question the student has not yet answered.
    answer_result = None
    if phase_in == "awaiting_answer" and grade_out in ("correct", "partial", "incorrect"):
        answer_result = grade_out

    # The Ask Sheet needs the QUESTION, not the last thing that was said. It was
    # rendering the live caption, so the panel showed a statement ("...so we
    # write a_x equals zero...") above three answer chips, with the actual
    # question nowhere on screen. Pull the interrogative sentence out of speech.
    question_text = None
    if check_options:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", speech_out) if s.strip()]
        asked = [s for s in sentences if s.endswith("?")]
        question_text = asked[-1] if asked else (sentences[-1] if sentences else None)

    state_payload = {
        "phase": next_phase,
        "question_type": question_type,
        "check_options": check_options,
        "question_text": question_text,
        "answer_result": answer_result
    }
    assert_no_forbidden_keys(state_payload)
    yield f"event: state\ndata: {json.dumps(state_payload)}\n\n"
    if next_phase == "complete":
        state_payload["reason"] = "session_ended"
    assert_no_forbidden_keys(state_payload)
    yield f"event: state\ndata: {json.dumps(state_payload)}\n\n"

    yield "event: done\ndata: {}\n\n"
