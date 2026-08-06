import json
import time
import asyncio
import base64
import logging
from typing import Dict, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.db import supabase
from app.drona.tutor import process_tutor_turn_stream
from app.drona.voice_proxy import SaarasSTTProxy, RumikTTSProxy, check_tts_safety_filter, split_into_sentences

logger = logging.getLogger("drona.live_session_ws")
router = APIRouter(prefix="/drona", tags=["drona_voice"])

FORBIDDEN_WS_KEYS = {"model_answer", "rubric", "expected_misconceptions", "grade", "mistake_tag", "phase_request", "segment_complete"}

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
    res_s = supabase.table('drona_sessions').select('id, user_id, phase, current_segment, mode, grounded').eq('id', session_id).execute()
    if not res_s.data:
        await websocket.send_json({"type": "error", "message": f"Session {session_id} not found."})
        await websocket.close(code=4004)
        return

    session_data = res_s.data[0]
    user_id = session_data['user_id']
    state = LiveSessionState(session_id, user_id)
    tts_proxy = RumikTTSProxy(voice_preset="Ira", model="mulberry")
    stt_proxy = SaarasSTTProxy(mode="codemix", latency_profile="Fast")

    # Queue for incoming client binary PCM audio frames
    pcm_queue: asyncio.Queue[bytes] = asyncio.Queue()

    # Initial state handshake
    await websocket.send_json({
        "type": "state",
        "phase": session_data['phase'],
        "current_segment": session_data['current_segment'],
        "is_muted": False,
        "message": "Connected to Drona Live Session WebSocket"
    })

    async def execute_turn_pipeline(utterance_text: str, turn_type: str = "answer"):
        """Executes process_tutor_turn_stream and synthesizes TTS sentence-by-sentence over WebSocket."""
        speech_buffer = ""
        chunks_sent = 0
        total_audio_bytes = 0

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
                    except Exception:
                        pass

            if event_type == "speech":
                delta = data_payload.get("delta", "")
                speech_buffer += delta

                # Synthesize TTS sentence-by-sentence as speech completes
                sentences = split_into_sentences(speech_buffer)
                if len(sentences) > 1:
                    for sentence in sentences[:-1]:
                        t1_v, t2_v, clean_text = check_tts_safety_filter(sentence)
                        if clean_text:
                            state.tts_characters += len(clean_text)
                            try:
                                audio_bytes = await tts_proxy.synthesize_text(clean_text)
                                b64_audio = base64.b64encode(audio_bytes).decode('utf-8')
                                out_msg = {
                                    "type": "audio_chunk",
                                    "audio": b64_audio,
                                    "speech": clean_text
                                }
                                assert_no_forbidden_keys(out_msg)
                                chunks_sent += 1
                                total_audio_bytes += len(audio_bytes)
                                await websocket.send_json(out_msg)

                                # Pace synthesis delivery so client lead time stays strictly under 3.0s
                                duration_sec = len(audio_bytes) / 48000.0
                                if chunks_sent > 1:
                                    sleep_dur = max(0.0, duration_sec - 1.5)
                                    logger.info(f"[AUDIO PACING] Sentence #{chunks_sent} ({duration_sec:.2f}s audio). Pacing next chunk by {sleep_dur:.2f}s...")
                                    await asyncio.sleep(sleep_dur)
                            except Exception as tts_err:
                                logger.error(f"TTS synthesis error on sentence: {tts_err}")
                    speech_buffer = sentences[-1]

                out_msg = {"type": "speech_delta", "delta": delta}
                assert_no_forbidden_keys(out_msg)
                await websocket.send_json(out_msg)

            elif event_type == "board":
                latex = data_payload.get("latex", "")
                out_msg = {"type": "board", "board": latex}
                assert_no_forbidden_keys(out_msg)
                await websocket.send_json(out_msg)

            elif event_type == "meta":
                out_msg = {"type": "meta", **data_payload}
                assert_no_forbidden_keys(out_msg)
                await websocket.send_json(out_msg)

            elif event_type == "state":
                out_msg = {"type": "state", **data_payload}
                assert_no_forbidden_keys(out_msg)
                await websocket.send_json(out_msg)
                if data_payload.get("phase") == "complete":
                    state.is_active = False

        # Synthesize remaining sentence buffer
        if speech_buffer.strip():
            t1_v, t2_v, clean_text = check_tts_safety_filter(speech_buffer)
            if clean_text:
                state.tts_characters += len(clean_text)
                try:
                    audio_bytes = await tts_proxy.synthesize_text(clean_text)
                    b64_audio = base64.b64encode(audio_bytes).decode('utf-8')
                    out_msg = {
                        "type": "audio_chunk",
                        "audio": b64_audio,
                        "speech": clean_text
                    }
                    assert_no_forbidden_keys(out_msg)
                    chunks_sent += 1
                    total_audio_bytes += len(audio_bytes)
                    await websocket.send_json(out_msg)

                    duration_sec = len(audio_bytes) / 48000.0
                    if chunks_sent > 1:
                        sleep_dur = max(0.0, duration_sec - 1.5)
                        logger.info(f"[AUDIO PACING FINAL] Sentence #{chunks_sent} ({duration_sec:.2f}s audio). Pacing by {sleep_dur:.2f}s...")
                        await asyncio.sleep(sleep_dur)
                except Exception as tts_err:
                    logger.error(f"TTS synthesis error on final sentence: {tts_err}")

        if chunks_sent == 0 and speech_buffer.strip():
            logger.error(f"[SERVER TURN AUDIO FAILURE] Emitted 0 audio_chunk frames (0 total PCM bytes) for session {session_id}")
            await websocket.send_json({
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

        await websocket.send_json({"type": "turn_complete"})

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
            asyncio.create_task(execute_turn_pipeline(utterance_text=norm_t, turn_type="answer"))

    # W2 Fix: Audio stream generator feeding SaarasSTTProxy
    async def audio_stream_generator():
        while state.is_active:
            try:
                chunk = await asyncio.wait_for(pcm_queue.get(), timeout=1.0)
                yield chunk
            except asyncio.TimeoutError:
                continue

    # Start background Saaras STT streaming task
    stt_task = asyncio.create_task(stt_proxy.connect_and_stream(
        audio_stream=audio_stream_generator(),
        on_transcript=handle_stt_transcript,
        on_barge_in=lambda: asyncio.create_task(execute_turn_pipeline(utterance_text="", turn_type="interruption"))
    ))

    # PTT PCM Buffer state
    is_ptt_active = False
    ptt_pcm_chunks = []

    try:
        while state.is_active:
            message = await websocket.receive()

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
                            asyncio.create_task(execute_turn_pipeline(utterance_text=norm_t, turn_type="answer"))

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
                    await execute_turn_pipeline(utterance_text="", turn_type="interruption")

                elif control_type == "playback_position":
                    state.current_playback_pos = data.get("position", 0)

                elif control_type == "utterance":
                    utterance_text = data.get("text", "").strip()

                    if state.is_muted and session_data['phase'] == 'awaiting_answer':
                        mute_dur = state.get_total_mute_sec()
                        if mute_dur > 5:
                            await websocket.send_json({
                                "type": "error",
                                "message": "You're muted — unmute to answer",
                                "is_muted": True
                            })
                            continue

                    if utterance_text:
                        await execute_turn_pipeline(utterance_text=utterance_text, turn_type="answer")

    except (WebSocketDisconnect, RuntimeError) as disconnect_err:
        logger.info(f"[WS DISCONNECT CLEANUP] Session {session_id} WebSocket client disconnected cleanly: {disconnect_err}")
        state.is_active = False
        stt_task.cancel()
        stt_proxy.close()
        total_mute = state.get_total_mute_sec()
        try:
            supabase.table('drona_sessions').update({
                'stt_seconds': round(state.stt_seconds, 2),
                'tts_characters': state.tts_characters,
                'reconnect_count': state.reconnect_count + 1
            }).eq('id', session_id).execute()
        except Exception as e:
            logger.warning(f"Telemetry update on disconnect: {e}")
            logger.error(f"Telemetry update error on disconnect: {e}")
    finally:
        stt_task.cancel()
        stt_proxy.close()
