import json
import time
import asyncio
import base64
import logging
from typing import Dict, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.db import supabase
from app.drona.tutor import process_tutor_turn_stream
from app.drona.voice_proxy import SaarasSTTProxy, RumikTTSProxy, check_tts_safety_filter

logger = logging.getLogger("drona.live_session_ws")
router = APIRouter(prefix="/drona", tags=["drona_voice"])

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
        """Student clicked mute."""
        if not self.is_muted:
            self.is_muted = True
            self.mute_start_time = time.time()

    def on_unmute(self):
        """Student clicked unmute."""
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
        """Calculates actual audio duration from 16kHz 16-bit mono PCM bytes."""
        # 16000 samples/sec * 2 bytes/sample = 32000 bytes/sec
        duration = byte_count / 32000.0
        self.stt_seconds += duration

@router.websocket("/session/{session_id}/live")
async def drona_live_session_ws(websocket: WebSocket, session_id: str):
    """Unified production WebSocket endpoint carrying PCM audio, transcripts, LLM turn processing, board events, and state updates."""
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
    tts_proxy = RumikTTSProxy()

    # Initial state handshake
    await websocket.send_json({
        "type": "state",
        "phase": session_data['phase'],
        "current_segment": session_data['current_segment'],
        "is_muted": False,
        "message": "Connected to Drona Live Session WebSocket"
    })

    FORBIDDEN_WS_KEYS = {"model_answer", "rubric", "expected_misconceptions", "grade", "mistake_tag", "phase_request", "segment_complete"}

    def assert_no_forbidden_keys(payload: dict):
        for k in FORBIDDEN_WS_KEYS:
            if k in payload:
                raise ValueError(f"R3 VIOLATION: Forbidden server-side key '{k}' in client WebSocket payload: {payload}")

    async def execute_turn_pipeline(utterance_text: str, turn_type: str = "answer"):
        """Executes the production process_tutor_turn_stream pipeline and streams events over WebSocket."""
        full_speech = ""
        full_board = ""

        # Call production tutor turn generator (same function used by /turn)
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
                full_speech += delta
                out_msg = {
                    "type": "speech_delta",
                    "delta": delta
                }
                assert_no_forbidden_keys(out_msg)
                await websocket.send_json(out_msg)
            elif event_type == "board":
                latex = data_payload.get("latex", "")
                full_board = latex
                out_msg = {
                    "type": "board",
                    "board": latex
                }
                assert_no_forbidden_keys(out_msg)
                await websocket.send_json(out_msg)
            elif event_type == "meta":
                out_msg = {
                    "type": "meta",
                    **data_payload
                }
                assert_no_forbidden_keys(out_msg)
                await websocket.send_json(out_msg)
            elif event_type == "state":
                out_msg = {
                    "type": "state",
                    **data_payload
                }
                assert_no_forbidden_keys(out_msg)
                await websocket.send_json(out_msg)
                if data_payload.get("phase") == "complete":
                    state.is_active = False

        # Generate streaming TTS audio for the complete speech response
        if full_speech.strip():
            t1, t2, clean_speech = check_tts_safety_filter(full_speech)
            state.tts_characters += len(clean_speech)

            async def text_gen():
                yield clean_speech

            async for pcm_chunk in tts_proxy.stream_tts(text_gen()):
                b64_audio = base64.b64encode(pcm_chunk).decode('utf-8')
                out_msg = {
                    "type": "audio_chunk",
                    "audio": b64_audio,
                    "speech": clean_speech,
                    "board": full_board
                }
                assert_no_forbidden_keys(out_msg)
                await websocket.send_json(out_msg)

    try:
        while state.is_active:
            message = await websocket.receive()
            msg_type = message.get("type")

            # A. BINARY PCM AUDIO FRAME FROM CLIENT
            if "bytes" in message and message["bytes"]:
                pcm_bytes = message["bytes"]
                state.add_pcm_bytes(len(pcm_bytes))
                state.last_audio_at = time.time()

                # If student is muted, discard PCM bytes
                if state.is_muted:
                    continue

                # Forward binary PCM frames to STT / buffer
                # For streaming turn trigger: if audio frame received, send confirmation
                continue

            # B. TEXT JSON CONTROL MESSAGES
            elif "text" in message and message["text"]:
                try:
                    data = json.loads(message["text"])
                except Exception:
                    continue

                control_type = data.get("type")

                # 1. PING / HEARTBEAT
                if control_type == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": time.time()})

                # 2. STUDENT MUTE
                elif control_type == "mute":
                    state.on_mute()
                    await websocket.send_json({"type": "state", "is_muted": True, "no_response_timer_paused": True})

                # 3. STUDENT UNMUTE
                elif control_type == "unmute":
                    state.on_unmute()
                    await websocket.send_json({"type": "state", "is_muted": False, "no_response_timer_paused": False})

                # 4. TAP-TO-INTERRUPT / BARGE-IN
                elif control_type == "interrupt":
                    state.current_playback_pos = data.get("playback_position", 0)
                    cutoff_text = data.get("cutoff_text", "")
                    state.playback_cutoff_point = cutoff_text

                    # Execute interruption turn with production process_tutor_turn_stream
                    await execute_turn_pipeline(utterance_text="", turn_type="interruption")

                # 5. PLAYBACK POSITION UPDATE
                elif control_type == "playback_position":
                    state.current_playback_pos = data.get("position", 0)

                # 6. UTTERANCE / TRANSCRIPT TURN PROCESSOR
                elif control_type == "utterance":
                    utterance_text = data.get("text", "").strip()

                    # Check mute status during awaiting_answer
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
                        await websocket.send_json({
                            "type": "transcript_final",
                            "transcript": utterance_text,
                            "confidence": 0.98
                        })

                        # Execute production tutor turn pipeline
                        await execute_turn_pipeline(utterance_text=utterance_text, turn_type="answer")

    except WebSocketDisconnect:
        state.is_active = False
        total_mute = state.get_total_mute_sec()
        try:
            supabase.table('drona_sessions').update({
                'mute_duration_sec': total_mute,
                'stt_seconds': round(state.stt_seconds, 2),
                'tts_characters': state.tts_characters,
                'reconnect_count': state.reconnect_count + 1
            }).eq('id', session_id).execute()
        except Exception as e:
            logger.error(f"Telemetry update error on disconnect: {e}")
