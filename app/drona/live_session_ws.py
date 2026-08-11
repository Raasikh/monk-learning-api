import re
import json
import time
import asyncio
import base64
import logging
from typing import Dict, List, Optional, Tuple
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.db import supabase
from app.drona.tutor import process_tutor_turn_stream
from app.drona.voice_proxy import SaarasSTTProxy, RumikTTSProxy, RumikConnectionPool, check_tts_safety_filter, split_into_sentences
from app.drona.persona import normalize_language, persona_for

logger = logging.getLogger("drona.live_session_ws")
router = APIRouter(prefix="/drona", tags=["drona_voice"])

FORBIDDEN_WS_KEYS = {"model_answer", "rubric", "expected_misconceptions", "grade", "mistake_tag", "phase_request", "segment_complete"}

# Ceiling for one complete turn: LLM (capped at TUTOR_TIMEOUT_S) plus
# sentence-by-sentence TTS, which can legitimately retry on a Rumik rate limit.
# Set above that worst case so it only fires on a genuine wedge, not on a slow
# but healthy turn.
TURN_WATCHDOG_S = 180.0

def assert_no_forbidden_keys(payload: dict):
    for k in FORBIDDEN_WS_KEYS:
        if k in payload:
            raise ValueError(f"R3 VIOLATION: Forbidden server-side key '{k}' in client WebSocket payload: {payload}")

class LiveSessionState:
    """In-memory session state manager for a live WebSocket voice session."""
    def __init__(self, session_id: str, user_id: str):
        self.session_id = session_id
        self.user_id = user_id
        self.is_muted = False
        self.mute_start_time: Optional[float] = None
        self.cumulative_mute_sec = 0
        self.last_audio_at = time.time()
        self.current_playback_pos = 0
        self.playback_cutoff_point: Optional[str] = None
        self.stt_seconds = 0.0
        self.tts_characters = 0
        self.reconnect_count = 0
        self.is_active = True
        self.current_segment: int = 1
        # Refreshed from every "state" SSE event a turn emits — the mute gate
        # used to check the phase snapshot fetched once at connect time, which
        # goes stale the moment the first turn changes it.
        self.current_phase: Optional[str] = None

    def on_mute(self):
        if not self.is_muted:
            self.is_muted = True
            self.mute_start_time = time.time()

    def on_unmute(self):
        if self.is_muted:
            if self.mute_start_time:
                self.cumulative_mute_sec += int(time.time() - self.mute_start_time)
            self.is_muted = False
            self.mute_start_time = None

    def get_total_mute_sec(self) -> int:
        total = self.cumulative_mute_sec
        if self.is_muted and self.mute_start_time:
            total += int(time.time() - self.mute_start_time)
        return total

    def add_pcm_bytes(self, byte_count: int):
        duration = byte_count / 32000.0
        self.stt_seconds += duration

@router.websocket("/session/{session_id}/live")
async def drona_live_session_ws(websocket: WebSocket, session_id: str):
    """Unified WebSocket endpoint streaming binary PCM, Saaras STT transcripts, sentence-level TTS synthesis, board events, and state updates."""
    await websocket.accept()

    # 1. Authenticate & fetch session
    # select('*') rather than a column list: tutor_voice only exists once
    # migrations/0011 is applied, and naming a missing column here 42703s the
    # whole connection (the same failure documented further down this file).
    res_s = supabase.table('drona_sessions').select('*').eq('id', session_id).execute()
    if not res_s.data:
        await websocket.send_json({"type": "error", "message": f"Session {session_id} not found."})
        await websocket.close(code=4004)
        return

    session_data = res_s.data[0]
    user_id = session_data['user_id']
    state = LiveSessionState(session_id, user_id)
    state.current_segment = session_data.get('current_segment') or 1
    state.current_phase = session_data.get('phase')
    skip_tts_flag = websocket.query_params.get("skip_tts") == "1"

    persona = persona_for(session_data.get('tutor_voice'))
    session_language = normalize_language(session_data.get('language'))
    # session_id must be passed: RumikConnectionPool keys leases by it and
    # returns an existing lease on a key match *without* checking the requested
    # preset. Left at the "default_session" default, every concurrent student
    # shares one connection and inherits whichever voice opened it first.
    tts_proxy = RumikTTSProxy(voice_preset=persona['voice_preset'], model="mulberry", session_id=session_id, language=session_language)
    stt_proxy = SaarasSTTProxy(mode="codemix", latency_profile="Fast", language=session_language)
    logger.info(
        f"🎙️ [SESSION PERSONA] session={session_id[:8]} tutor={persona['name']} "
        f"voice_preset={persona['voice_preset']} language={session_language}"
    )

    # Queue for incoming client binary PCM audio frames
    pcm_queue: asyncio.Queue[bytes] = asyncio.Queue()

    ws_send_lock = asyncio.Lock()

    async def safe_send_json(data: dict):
        """Task-safe WebSocket JSON sender guarded by asyncio.Lock to prevent concurrent send collisions."""
        if not state.is_active:
            return
        async with ws_send_lock:
            try:
                await websocket.send_json(data)
            except (WebSocketDisconnect, RuntimeError):
                state.is_active = False
            except Exception as send_err:
                logger.warning(f"WebSocket send error: {send_err}")

    # Initial state handshake
    await safe_send_json({
        "type": "state",
        "phase": session_data['phase'],
        "current_segment": session_data['current_segment'],
        "is_muted": False,
        "tutor_name": persona['name'],
        "tutor_voice": persona['gender'],
        "language": session_language,
        "message": "Connected to Drona Live Session WebSocket"
    })

    # Resume an interrupted question. If the connection died mid-turn (backend
    # restart, network drop) after the turn had already advanced the DB to
    # awaiting_answer, the question and its chips died with the old socket —
    # the reconnecting client sat idle ("Ready") with nothing on screen and
    # nothing ever arriving. Re-send them from the last turn's record so the
    # student can simply answer and continue.
    if session_data['phase'] == 'awaiting_answer':
        try:
            last_turn_res = supabase.table('drona_turns').select('raw_response') \
                .eq('session_id', session_id).order('turn_index', desc=True).limit(1).execute()
            if last_turn_res.data:
                last_parsed = json.loads(last_turn_res.data[0].get('raw_response') or '{}')
                resume_options = last_parsed.get('check_options') or []
                speech_text = last_parsed.get('speech') or ''
                sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", speech_text) if s.strip()]
                asked = [s for s in sentences if s.endswith('?')]
                resume_question = asked[-1] if asked else (sentences[-1] if sentences else None)
                if resume_options:
                    resume_frame = {
                        "type": "state",
                        "phase": "awaiting_answer",
                        "question_type": last_parsed.get('question_type'),
                        "check_options": resume_options,
                        "question_text": resume_question,
                        "answer_result": None,
                    }
                    assert_no_forbidden_keys(resume_frame)
                    await safe_send_json(resume_frame)
                    logger.info(f"🔁 [RESUME QUESTION] Re-sent pending question + {len(resume_options)} chips on reconnect for session {session_id[:8]}")
        except Exception as resume_err:
            logger.warning(f"Question resume on reconnect skipped: {resume_err}")

    # Board replay: a page refresh used to blank the whiteboard for good — the
    # session lived on server-side but every line already written was gone from
    # the client. Re-send everything the board has shown so far; the client
    # paints it immediately (no reveal timing — it's history, not narration).
    # appendBoardEvent dedupes by content, so a same-tab auto-reconnect that
    # still has the board is unaffected.
    try:
        prior_turns = supabase.table('drona_turns').select('raw_response') \
            .eq('session_id', session_id).order('turn_index').execute()
        replay_events: List[Dict] = []
        seen_replay = set()
        for t in (prior_turns.data or []):
            raw = t.get('raw_response')
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = {}
            if isinstance(raw, dict):
                for evt in raw.get('board_events', []):
                    key = ((evt.get('text') or evt.get('latex') or '').strip().lower())
                    if key and key not in seen_replay:
                        seen_replay.add(key)
                        replay_events.append(evt)
        if replay_events:
            await safe_send_json({"type": "board_replay", "events": replay_events})
            logger.info(f"🧾 [BOARD REPLAY] Re-sent {len(replay_events)} board items on connect for session {session_id[:8]}")
    except Exception as replay_err:
        logger.warning(f"Board replay on connect skipped: {replay_err}")

    async def execute_turn_pipeline(utterance_text: str, turn_type: str = "answer"):
        """Executes process_tutor_turn_stream and synthesizes TTS sentence-by-sentence over WebSocket."""
        # Pre-warm Rumik TTS concurrently in background while LLM generates tokens
        asyncio.create_task(tts_proxy.prewarm())

        turn_id = f"t_{int(time.time() * 1000)}"
        speech_buffer = ""
        chunks_sent = 0
        total_audio_bytes = 0
        turn_board_events = []
        state_data = {}
        segment_complete_flag = False
        ends_in_checkpoint = False
        session_ending = False

        async def _on_filler(filler_pcm: bytes):
            b64_f = base64.b64encode(filler_pcm).decode('utf-8')
            f_msg = {
                "type": "audio_chunk",
                "sentence_id": f"{turn_id}_filler_{int(time.time()*1000)}",
                "audio": b64_f,
                "speech": "One moment…" if session_language == "english" else "Ek second…",
                "board_event": None
            }
            await safe_send_json(f_msg)
            logger.info(f"🔊 [FILLER AUDIO TRANSMITTED] Sent pre-synthesized filler chunk ({len(filler_pcm)} bytes) over WebSocket.")

        async def send_sentence_streamed(clean_text: str):
            """Synthesizes one sentence, forwarding audio to the client in ~1s
            parts AS RUMIK PRODUCES IT. The old flow buffered the whole
            sentence (4-6s) before the first byte left the server — dead air
            the student sat through on every single sentence. Part 1 carries
            the caption text and board event; continuation parts are audio
            only so the client doesn't re-arm reveals."""
            nonlocal chunks_sent, total_audio_bytes
            chunks_sent += 1
            sentence_id = f"{turn_id}_s{chunks_sent}"
            matching_evt = next((e for e in turn_board_events if e.get("seq") == chunks_sent), None)
            if not matching_evt and chunks_sent <= len(turn_board_events):
                matching_evt = turn_board_events[chunks_sent - 1]

            part_count = 0

            async def _on_part(pcm: bytes):
                nonlocal part_count, total_audio_bytes
                part_count += 1
                out = {
                    "type": "audio_chunk",
                    "sentence_id": sentence_id,
                    "audio": base64.b64encode(pcm).decode('utf-8'),
                    "speech": clean_text if part_count == 1 else "",
                    "board_event": matching_evt if part_count == 1 else None,
                    "continuation": part_count > 1,
                }
                assert_no_forbidden_keys(out)
                total_audio_bytes += len(pcm)
                await safe_send_json(out)

            if skip_tts_flag:
                audio_bytes = b"\x00" * 3200
            else:
                audio_bytes = await tts_proxy.synthesize_text(
                    clean_text, on_filler_cb=_on_filler, segment_index=state.current_segment,
                    on_audio_part=_on_part,
                )

            if part_count > 0:
                logger.info(f"🔊 [AUDIO STREAMED] sentence_id={sentence_id} ({len(clean_text)} chars, {part_count} parts)")
            elif audio_bytes:
                # Fallback single frame: skip_tts, a pool-exhaustion filler, or
                # a synthesis path that produced no streamed parts.
                out_msg = {
                    "type": "audio_chunk",
                    "sentence_id": sentence_id,
                    "audio": base64.b64encode(audio_bytes).decode('utf-8'),
                    "speech": clean_text,
                    "board_event": matching_evt
                }
                assert_no_forbidden_keys(out_msg)
                total_audio_bytes += len(audio_bytes)
                await safe_send_json(out_msg)
                logger.info(f"🔊 [AUDIO SYNTHESIZED] sentence_id={sentence_id} ({len(clean_text)} chars, single frame)")

        # Instant acknowledgment: the student just answered and the LLM +
        # first TTS are still 6-10s away — a short pre-synthesized "let me
        # think" fills the void the moment their words land, like a teacher
        # nodding before responding.
        if turn_type == "answer" and utterance_text.strip() and not skip_tts_flag:
            try:
                from app.drona.voice_proxy import FillerAudioCache
                _, ack_pcm = FillerAudioCache.get_instance().get_random_filler(
                    persona['voice_preset'], session_language
                )
                if ack_pcm:
                    await _on_filler(ack_pcm)
            except Exception as ack_err:
                logger.warning(f"Acknowledgment filler skipped: {ack_err}")

        async for sse_chunk in process_tutor_turn_stream(session_id, user_id, utterance_text, turn_type):
            lines = sse_chunk.strip().split("\n")
            event_type = None
            data_payload = {}

            for line in lines:
                if line.startswith("event:"):
                    event_type = line.replace("event:", "").strip()
                elif line.startswith("data:"):
                    try:
                        data_payload = json.loads(line.replace("data:", "").strip())
                    except Exception as parse_err:
                        logger.warning(f"Failed to parse SSE data line '{line[:50]}...': {parse_err}")

            if event_type == "board_events":
                turn_board_events = data_payload.get("events", [])
                out_msg = {"type": "board_events", "events": turn_board_events}
                assert_no_forbidden_keys(out_msg)
                await safe_send_json(out_msg)

            elif event_type == "turn_error":
                out_msg = {"type": "turn_error", **data_payload}
                assert_no_forbidden_keys(out_msg)
                await safe_send_json(out_msg)

            elif event_type == "speech":
                delta = data_payload.get("delta", "")
                speech_buffer += delta
                ends_in_checkpoint = bool(data_payload.get("ends_in_checkpoint"))

                # Synthesize TTS sentence-by-sentence as speech completes
                sentences = split_into_sentences(speech_buffer)
                if len(sentences) > 1:
                    for sentence in sentences[:-1]:
                        t1_v, t2_v, clean_text = check_tts_safety_filter(sentence)
                        if clean_text:
                            state.tts_characters += len(clean_text)
                            try:
                                await send_sentence_streamed(clean_text)
                            except Exception as tts_err:
                                logger.error(f"TTS synthesis error on sentence: {tts_err}")
                    speech_buffer = sentences[-1]

                out_msg = {"type": "speech_delta", "delta": delta}
                assert_no_forbidden_keys(out_msg)
                await safe_send_json(out_msg)

            elif event_type == "board":
                latex = data_payload.get("latex", "")
                out_msg = {"type": "board", "board": latex}
                assert_no_forbidden_keys(out_msg)
                await safe_send_json(out_msg)

            elif event_type == "meta":
                if data_payload.get("segment_index"):
                    state.current_segment = data_payload["segment_index"]
                out_msg = {"type": "meta", **data_payload}
                assert_no_forbidden_keys(out_msg)
                await safe_send_json(out_msg)

            elif event_type == "state":
                state_data = data_payload
                if data_payload.get("phase"):
                    state.current_phase = data_payload["phase"]
                if data_payload.get("segment_complete"):
                    segment_complete_flag = True
                out_msg = {"type": "state", **data_payload}
                assert_no_forbidden_keys(out_msg)
                await safe_send_json(out_msg)
                if data_payload.get("phase") == "complete":
                    # Deferred, not set here: the trailing sentence buffer and
                    # turn_complete are still to come after this loop ends, and
                    # safe_send_json no-ops once is_active is False — flipping
                    # it here silently dropped the turn's last spoken line and
                    # the turn_complete signal for every session that reaches
                    # a natural end.
                    session_ending = True

        # Synthesize remaining sentence buffer
        if speech_buffer.strip():
            t1_v, t2_v, clean_text = check_tts_safety_filter(speech_buffer)
            if clean_text:
                # Checkpoint questions used to be delivered as text only, never
                # voiced — a real teacher asks the question out loud, and
                # silently popping a question onto the sheet with nothing said
                # felt abrupt and broken. Now attempted like any other
                # sentence; only genuine TTS failure falls back to a silent
                # caption, so the question still reaches the student either way.
                state.tts_characters += len(clean_text)
                try:
                    await send_sentence_streamed(clean_text)
                except Exception as tts_err:
                    if ends_in_checkpoint:
                        # The question must still reach the student even when
                        # its audio can't: silent caption fallback.
                        logger.warning(f"TTS synthesis failed on checkpoint question, falling back to silent caption: {tts_err}")
                        sentence_id = f"{turn_id}_s{chunks_sent}"
                        matching_evt = next((e for e in turn_board_events if e.get("seq") == chunks_sent), None)
                        if not matching_evt and chunks_sent <= len(turn_board_events):
                            matching_evt = turn_board_events[chunks_sent - 1]
                        out_msg = {
                            "type": "audio_chunk",
                            "sentence_id": sentence_id,
                            "audio": None,
                            "speech": clean_text,
                            "board_event": matching_evt
                        }
                        assert_no_forbidden_keys(out_msg)
                        logger.info(f"🔇 [CHECKPOINT QUESTION - TTS FAILED] sentence_id={sentence_id} sent as silent caption ({len(clean_text)} chars)")
                        await safe_send_json(out_msg)
                    else:
                        logger.error(f"TTS synthesis error on final sentence: {tts_err}")

        if chunks_sent == 0 and speech_buffer.strip():
            logger.error(f"[SERVER TURN AUDIO FAILURE] Emitted 0 audio_chunk frames (0 total PCM bytes) for session {session_id}")
            await safe_send_json({
                "type": "error",
                "message": "TTS Synthesis Failed: zero audio frames generated for turn."
            })
            try:
                # Track tts_failure_count in DB if turn exists
                turns = supabase.table('drona_turns').select('id, tts_failure_count').eq('session_id', session_id).order('turn_index', desc=True).limit(1).execute()
                if turns.data:
                    curr_fail = turns.data[0].get('tts_failure_count') or 0
                    supabase.table('drona_turns').update({'tts_failure_count': curr_fail + 1}).eq('id', turns.data[0]['id']).execute()
            except Exception as db_err:
                logger.warning(f"Failed to increment tts_failure_count in drona_turns: {db_err}")
        else:
            logger.info(f"[SERVER TURN AUDIO SUMMARY] Emitted {chunks_sent} audio_chunk frames ({total_audio_bytes} total PCM bytes) for session {session_id}")

        # Hand the Rumik slot back. Without this the lease is held for the life
        # of the process and the pool runs out after max_slots sessions have
        # ever started.
        #
        # Keep the grace only when another teaching turn auto-advances straight
        # after this one — that turn's prewarm() reuses the socket. If we are
        # stopping on a question, the student is about to think for 20-60s and
        # the slot should go back now.
        next_turn_is_immediate = state_data.get("phase") == "teaching"
        try:
            await tts_proxy.end_turn(next_turn_is_immediate=next_turn_is_immediate)
        except Exception as release_err:
            logger.warning(f"Rumik lease release at turn end failed: {release_err}")

        await safe_send_json({"type": "turn_complete"})

        # Emit updated state frame & auto-advance if next segment is in teaching phase
        try:
            # NOTE: drona_sessions has no check_options column — check_options is
            # computed fresh per-turn in tutor.py and already delivered to the
            # client via the primary "state" SSE event earlier in this stream.
            # This re-fetch is only for the post-turn_complete state frame and
            # the auto-advance decision below; selecting check_options here
            # threw (42703) on every turn, aborting before auto-advance ever ran.
            sess_res = supabase.table('drona_sessions').select('phase, current_segment').eq('id', session_id).single().execute()
            if sess_res.data:
                curr_phase = sess_res.data.get('phase')
                curr_seg = sess_res.data.get('current_segment')

                state_frame = {
                    "type": "state",
                    "phase": curr_phase,
                    "current_segment": curr_seg,
                }
                assert_no_forbidden_keys(state_frame)
                await safe_send_json(state_frame)
                logger.info(f"📡 [STATE FRAME EMITTED] phase='{curr_phase}', segment={curr_seg}")

                if curr_phase == 'teaching':
                    logger.info(f"🚀 [AUTO SEGMENT ADVANCE] Phase is teaching for Segment #{curr_seg}. Automatically firing teaching turn...")
                    launch_background_turn(utterance_text="", turn_type="teaching")
        except Exception as auto_adv_err:
            logger.warning(f"Auto-segment advance check skipped: {auto_adv_err}")

        # Now that the trailing sentence, turn_complete, and the post-turn
        # state frame have all actually been sent, it's safe to stop the loop.
        if session_ending:
            state.is_active = False

    # W2 Fix: Callback for Saaras STT transcript streaming
    def handle_stt_transcript(raw_t: str, norm_t: str, is_final: bool, confidence: float):
        if not norm_t.strip():
            return

        if not is_final:
            asyncio.create_task(websocket.send_json({
                "type": "transcript_partial",
                "transcript": norm_t
            }))
        else:
            asyncio.create_task(websocket.send_json({
                "type": "transcript_final",
                "transcript": norm_t,
                "confidence": confidence
            }))
            # Automatically fire turn pipeline on final STT transcript
            launch_background_turn(utterance_text=norm_t, turn_type="answer")

    # W2 Fix: Audio stream generator feeding SaarasSTTProxy
    async def audio_stream_generator():
        while state.is_active:
            try:
                chunk = await asyncio.wait_for(pcm_queue.get(), timeout=1.0)
                yield chunk
            except asyncio.TimeoutError:
                continue

    # Start background Saaras STT streaming task (barge-in disabled to prevent premature audio cutoffs)
    stt_task = asyncio.create_task(stt_proxy.connect_and_stream(
        audio_stream=audio_stream_generator(),
        on_transcript=handle_stt_transcript,
        on_barge_in=lambda: None
    ))

    active_turn_tasks = set()
    pending_turn_queue: List[Tuple[str, str]] = []
    # Explicit in-flight flag rather than len(active_turn_tasks). The task is
    # only discarded from that set by its done-callback, which fires *after*
    # the runner's finally block — so a set-based guard is still truthy while
    # the finishing turn tries to drain the queue, and nothing ever starts.
    turn_in_flight = {"value": False}
    MAX_QUEUED_TURNS = 4

    def launch_background_turn(utterance_text: str, turn_type: str = "answer"):
        """Launches execute_turn_pipeline as a background task with turn queueing and 20s heartbeat."""
        if turn_in_flight["value"]:
            # Queue teaching turns too. Auto-advance calls this with an empty
            # utterance, and the old `if utterance_text.strip()` guard dropped
            # those on the floor: the segment logged "AUTO SEGMENT ADVANCE" and
            # then simply never produced a turn, stalling the session after
            # turn 1 until the student typed something.
            if len(pending_turn_queue) >= MAX_QUEUED_TURNS:
                logger.warning(f"⚠️ [TURN QUEUE FULL] Dropping {turn_type} turn for session {session_id}; {len(pending_turn_queue)} already queued.")
                # Previously just logged and returned — the student's input
                # (an interrupt, an answer, an auto-advance) vanished with no
                # on-screen sign anything was lost.
                if turn_type != "teaching":
                    asyncio.create_task(safe_send_json({
                        "type": "error",
                        "message": "That's a lot at once — give the current turn a moment to finish.",
                    }))
                return None
            logger.info(f"📥 [TURN QUEUED] Turn active for session {session_id}. Queueing {turn_type} turn utterance='{utterance_text[:30]}'")
            pending_turn_queue.append((utterance_text, turn_type))
            return None

        turn_in_flight["value"] = True

        async def _turn_runner():
            hb_task = None
            try:
                async def _heartbeat_loop():
                    try:
                        while True:
                            await asyncio.sleep(20.0)
                            if state.is_active:
                                logger.info(f"💓 [APPLICATION HEARTBEAT] Sending 20s ping frame for session {session_id}...")
                                await safe_send_json({"type": "ping", "heartbeat": True})
                    except asyncio.CancelledError:
                        pass

                hb_task = asyncio.create_task(_heartbeat_loop())
                # Hard ceiling on a turn. Per-call timeouts cover a slow LLM or
                # TTS response, but anything that wedges between them would
                # otherwise hang forever: the heartbeat keeps pinging, the
                # socket stays open, and the student watches nothing happen with
                # no error and no recovery. Observed as a 12-minute silence.
                await asyncio.wait_for(
                    execute_turn_pipeline(utterance_text=utterance_text, turn_type=turn_type),
                    timeout=TURN_WATCHDOG_S,
                )
            except asyncio.TimeoutError:
                logger.error(
                    f"❌ [TURN WATCHDOG FIRED] Session {session_id} exceeded {TURN_WATCHDOG_S}s. "
                    f"Aborting the turn and returning the Rumik slot."
                )
                await safe_send_json({
                    "type": "error",
                    "message": "That took too long on our side — tap the mic or an option to continue.",
                })
                await safe_send_json({"type": "turn_complete"})
                try:
                    await tts_proxy.abandon()
                except Exception:
                    pass
            except Exception as turn_err:
                # This used to just log — unlike the TimeoutError branch above,
                # it never told the client anything or sent turn_complete, so
                # any unhandled exception (a DB write failing mid-turn, a bad
                # Supabase response) left the student staring at a screen that
                # would never move again, with no error and nothing to retry.
                logger.error(f"❌ [BACKGROUND TURN ERROR] Session {session_id}: {turn_err}", exc_info=True)
                await safe_send_json({
                    "type": "error",
                    "message": "Something went wrong on our side — tap the mic or an option to continue.",
                })
                await safe_send_json({"type": "turn_complete"})
                try:
                    await tts_proxy.abandon()
                except Exception:
                    pass
            finally:
                if hb_task and not hb_task.done():
                    hb_task.cancel()
                # Clear before draining, or the next turn hits its own guard.
                turn_in_flight["value"] = False
                if pending_turn_queue and state.is_active:
                    next_utt, next_ttype = pending_turn_queue.pop(0)
                    logger.info(f"🚀 [DRAINING TURN QUEUE] Executing queued {next_ttype} turn: utterance='{next_utt[:30]}'")
                    launch_background_turn(utterance_text=next_utt, turn_type=next_ttype)

        t_task = asyncio.create_task(_turn_runner())
        active_turn_tasks.add(t_task)
        t_task.add_done_callback(active_turn_tasks.discard)
        return t_task

    async def abort_active_turn(reason: str):
        """True barge-in: kill the in-flight turn's generation and TTS.

        Before this, taking the floor (holding the mic, typing) only flushed
        the CLIENT's audio queue — the server kept synthesizing and sending
        the rest of the turn, so the teacher talked over the student and then
        resumed the stale explanation. A real teacher stops mid-sentence when
        a student speaks up; this makes the pipeline do the same.
        """
        if not turn_in_flight["value"] and not pending_turn_queue:
            return
        # Queued turns die with the interrupted one — they were reactions to a
        # world the student just changed.
        pending_turn_queue.clear()
        tasks = [t for t in list(active_turn_tasks) if not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            try:
                await asyncio.wait(tasks, timeout=3.0)
            except Exception:
                pass
        turn_in_flight["value"] = False
        # The cancelled synthesize call cannot release its own lease.
        try:
            await tts_proxy.abandon()
        except Exception:
            pass
        logger.info(f"✋ [TURN ABORTED] reason={reason} — student took the floor for session {session_id[:8]}")

    # Auto-trigger turn 1 teaching if session is in teaching phase upon connect
    if session_data['phase'] == 'teaching':
        logger.info(f"🚀 [WS CONNECT AUTO-START] Triggering turn 1 teaching for Segment #{session_data['current_segment']}...")
        launch_background_turn(utterance_text="", turn_type="teaching")

    is_ptt_active = False
    ptt_pcm_chunks: List[bytes] = []

    try:
        while state.is_active:
            try:
                message = await websocket.receive()
            except (WebSocketDisconnect, RuntimeError):
                state.is_active = False
                break

            # BINARY PCM AUDIO FRAME FORWARDED TO STT BUFFER
            if "bytes" in message and message["bytes"]:
                pcm_bytes = message["bytes"]
                state.add_pcm_bytes(len(pcm_bytes))
                state.last_audio_at = time.time()

                if is_ptt_active:
                    ptt_pcm_chunks.append(pcm_bytes)
                    total_bytes = sum(len(x) for x in ptt_pcm_chunks)
                    logger.info(f"[SARVAM STT PCM FORWARDED] Chunk #{len(ptt_pcm_chunks)}: {len(pcm_bytes)} bytes (Total: {total_bytes} bytes)")
                continue

            # B. TEXT JSON CONTROL MESSAGES
            elif "text" in message and message["text"]:
                try:
                    data = json.loads(message["text"])
                except Exception:
                    continue

                control_type = data.get("type")

                if control_type == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": time.time()})

                elif control_type == "ptt_start":
                    is_ptt_active = True
                    ptt_pcm_chunks = []
                    # Student took the floor — the teacher stops mid-thought.
                    await abort_active_turn("barge_in_mic")
                    logger.info("[SARVAM STT PTT START] Microphone active. Buffering PCM audio frames...")

                elif control_type == "ptt_stop":
                    is_ptt_active = False
                    full_pcm = b"".join(ptt_pcm_chunks)
                    ptt_pcm_chunks = []
                    duration_s = len(full_pcm) / 32000.0

                    logger.info(f"[SARVAM STT PTT STOP] Captured {len(full_pcm)} total bytes ({duration_s:.2f}s audio)")

                    if duration_s < 0.5:
                        logger.info(f"[SARVAM STT PTT TOO SHORT] Duration {duration_s:.2f}s < 0.5s. Skipping STT.")
                        await websocket.send_json({
                            "type": "stt_too_short",
                            "message": "Hold the button while you speak"
                        })
                    else:
                        raw_t, norm_t = await stt_proxy.transcribe_audio_rest(full_pcm)
                        if norm_t.strip():
                            logger.info(f"🎯 [SARVAM STT TRANSCRIPT] raw='{raw_t}', norm='{norm_t}'")
                            await websocket.send_json({
                                "type": "transcript_final",
                                "transcript": norm_t
                            })
                            launch_background_turn(utterance_text=norm_t, turn_type="answer")
                        else:
                            logger.warning(f"[SARVAM STT REST EMPTY] No transcript recovered from {duration_s:.2f}s of PTT audio for session {session_id}")
                            await websocket.send_json({
                                "type": "error",
                                "message": "Couldn't catch that — try holding the mic a little longer, or type your answer instead."
                            })

                elif control_type == "mute":
                    state.on_mute()
                    await websocket.send_json({"type": "state", "is_muted": True, "no_response_timer_paused": True})

                elif control_type == "unmute":
                    state.on_unmute()
                    await websocket.send_json({"type": "state", "is_muted": False, "no_response_timer_paused": False})

                elif control_type == "interrupt":
                    state.current_playback_pos = data.get("playback_position", 0)
                    cutoff_text = data.get("cutoff_text", "")
                    state.playback_cutoff_point = cutoff_text
                    launch_background_turn(utterance_text="", turn_type="interruption")

                elif control_type == "playback_position":
                    state.current_playback_pos = data.get("position", 0)

                elif control_type == "utterance":
                    utterance_text = data.get("text", "").strip()

                    if state.is_muted and state.current_phase == 'awaiting_answer':
                        mute_dur = state.get_total_mute_sec()
                        if mute_dur > 5:
                            await websocket.send_json({
                                "type": "error",
                                "message": "You're muted — unmute to answer",
                                "is_muted": True
                            })
                            continue

                    if utterance_text:
                        # A typed message mid-explanation is a hand raised in
                        # class: stop teaching, read it, respond.
                        await abort_active_turn("barge_in_text")
                        launch_background_turn(utterance_text=utterance_text, turn_type="answer")

    except WebSocketDisconnect as disconnect_err:
        logger.info(f"[WS DISCONNECT CLEANUP] Session {session_id} WebSocket client disconnected cleanly: {disconnect_err}")
        state.is_active = False
        stt_task.cancel()
        stt_proxy.close()
    except Exception as unhandled_err:
        logger.error(f"❌ [UNHANDLED ASGI WEBSOCKET EXCEPTION] Session {session_id}: {unhandled_err}", exc_info=True)
        state.is_active = False
        stt_task.cancel()
        stt_proxy.close()
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Server Error: {str(unhandled_err)}"
            })
        except Exception:
            pass
    finally:
        stt_task.cancel()
        stt_proxy.close()
        # Only stt_task was ever cancelled here — any turn still generating
        # (LLM call, TTS synthesis, DB writes) for a student who just left
        # kept running to completion regardless, burning LLM/TTS spend and
        # writing turns to a session nobody will read.
        for t_task in list(active_turn_tasks):
            if not t_task.done():
                t_task.cancel()
        # The student is gone — there is no next sentence to reuse the socket
        # for, so skip the grace period and return the slot now. Omitting this
        # leaks one of max_slots per session that ever connected.
        try:
            await tts_proxy.abandon()
        except Exception as abandon_err:
            logger.warning(f"Rumik lease release on disconnect failed: {abandon_err}")
        pool = RumikConnectionPool.get_instance()
        opens_60s, sends_60s = pool.get_rate_usage()
        logger.info(
            f"🔚 [SESSION CLOSED] session={session_id[:8]} | open_leases={len(pool.active_leases)}/{pool.max_slots} "
            f"| rumik_opens_60s={opens_60s} | rumik_sends_60s={sends_60s} | pool_exhaustions={pool.pool_exhaustion_count}"
        )
