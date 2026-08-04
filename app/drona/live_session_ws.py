import json
import time
import asyncio
from typing import Dict, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.db import supabase
from app.drona.voice_proxy import check_tts_safety_filter, split_into_sentences

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

@router.websocket("/session/{session_id}/live")
async def drona_live_session_ws(websocket: WebSocket, session_id: str):
    """Unified WebSocket endpoint carrying PCM audio, transcripts, TTS streams, board events, and state updates."""
    await websocket.accept()

    # Authenticate / fetch session
    res_s = supabase.table('drona_sessions').select('id, user_id, phase, current_segment, mode, grounded').eq('id', session_id).execute()
    if not res_s.data:
        await websocket.send_json({"type": "error", "message": f"Session {session_id} not found."})
        await websocket.close(code=4004)
        return

    session_data = res_s.data[0]
    user_id = session_data['user_id']
    state = LiveSessionState(session_id, user_id)

    # Initial state handshake
    await websocket.send_json({
        "type": "state",
        "phase": session_data['phase'],
        "current_segment": session_data['current_segment'],
        "is_muted": False,
        "message": "Connected to Drona Live Session WebSocket"
    })

    try:
        while state.is_active:
            msg_raw = await websocket.receive_text()
            try:
                data = json.loads(msg_raw)
            except Exception:
                continue

            msg_type = data.get("type")

            # 1. PING / HEARTBEAT
            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "timestamp": time.time()})

            # 2. STUDENT MUTE
            elif msg_type == "mute":
                state.on_mute()
                await websocket.send_json({"type": "state", "is_muted": True, "no_response_timer_paused": True})

            # 3. STUDENT UNMUTE
            elif msg_type == "unmute":
                state.on_unmute()
                await websocket.send_json({"type": "state", "is_muted": False, "no_response_timer_paused": False})

            # 4. TAP-TO-INTERRUPT / BARGE-IN
            elif msg_type == "interrupt":
                state.current_playback_pos = data.get("playback_position", 0)
                cutoff_text = data.get("cutoff_text", "")
                state.playback_cutoff_point = cutoff_text

                # Truncate playback & emit interruption metadata
                await websocket.send_json({
                    "type": "meta",
                    "turn_type": "interruption",
                    "grade": None,  # Rule 5: Tutor emits grade: null on interruption turns
                    "playback_cutoff_point": cutoff_text,
                    "message": "Playback halted by student interruption"
                })

            # 5. PLAYBACK POSITION UPDATE
            elif msg_type == "playback_position":
                state.current_playback_pos = data.get("position", 0)

            # 6. AUDIO PCM / TRANSCRIPT TURN PROCESSOR
            elif msg_type == "utterance":
                utterance_text = data.get("text", "").strip()

                # If student is muted for > 5 seconds in awaiting_answer
                if state.is_muted and session_data['phase'] == 'awaiting_answer':
                    mute_dur = state.get_total_mute_sec()
                    if mute_dur > 5:
                        await websocket.send_json({
                            "type": "error",
                            "message": "You're muted — unmute to answer",
                            "is_muted": True
                        })
                        continue

                # Process turn utterance
                if utterance_text:
                    state.stt_seconds += round(len(utterance_text.split()) * 0.4, 2)

                    # Simple distress intercept check for Tier 5 / Tier 5a
                    distress_keywords = ["can't do this anymore", "mera kuch nahi hoga", "papa maar denge", "haven't slept", "kill myself", "hurt myself"]
                    is_distress = any(kw in utterance_text.lower() for kw in distress_keywords)
                    is_self_harm = any(kw in utterance_text.lower() for kw in ["kill myself", "hurt myself", "end my life"])

                    if is_distress or is_self_harm:
                        tier_label = "explicit_self_harm" if is_self_harm else "distress"
                        offtopic_tier = 5

                        # Insert into drona_wellbeing_flags (Server-only RLS)
                        # Fetch last turn id or create flag entry
                        try:
                            # Fetch last turn for this session
                            res_t = supabase.table('drona_turns').select('id').eq('session_id', session_id).order('turn_index', desc=True).limit(1).execute()
                            last_turn_id = res_t.data[0]['id'] if res_t.data else None

                            if last_turn_id:
                                supabase.table('drona_wellbeing_flags').insert([{
                                    'session_id': session_id,
                                    'turn_id': last_turn_id,
                                    'user_id': user_id,
                                    'tier': tier_label,
                                    'utterance': utterance_text
                                }]).execute()
                        except Exception as e:
                            print("Wellbeing flag insert error:", e)

                        # Form Tier 5 response
                        response_speech = "Padhai ruk sakti hai. Tum zyada important ho. Apne mummy-papa, bade bhai-behen, ya teacher se baat karo."
                        if is_self_harm:
                            response_speech += " Kripya kisi trusted adult ya doctor se abhi baat karein."

                        await websocket.send_json({
                            "type": "meta",
                            "offtopic_tier": 5,
                            "grade": None,
                            "segment_complete": False,
                            "phase": "complete" if is_self_harm else session_data['phase']
                        })
                        await websocket.send_json({
                            "type": "audio_chunk",
                            "speech": response_speech,
                            "board": ""
                        })

                        if is_self_harm or data.get("phase_request") == "end_session":
                            # End lesson immediately: no wrapup, no lesson summary, no mistake review
                            supabase.table('drona_sessions').update({'phase': 'complete', 'completed_at': 'now()'}).eq('id', session_id).execute()
                            state.is_active = False
                            await websocket.send_json({
                                "type": "meta",
                                "phase": "complete",
                                "offtopic_tier": 5,
                                "grade": None,
                                "segment_complete": False
                            })
                            await websocket.close()
                            break
                    else:
                        # Standard turn response
                        p1_viol, p2_viol, clean_speech = check_tts_safety_filter(f"Aapne kaha: {utterance_text}. Sahi direction mein ja rahe ho!")
                        state.tts_characters += len(clean_speech)

                        await websocket.send_json({
                            "type": "transcript_final",
                            "transcript": utterance_text,
                            "confidence": 0.96
                        })
                        await websocket.send_json({
                            "type": "board",
                            "board": "\\text{Current Topic: Vector Resolution}"
                        })
                        await websocket.send_json({
                            "type": "audio_chunk",
                            "speech": clean_speech
                        })

    except WebSocketDisconnect:
        # Client disconnected
        state.is_active = False
        # Save cumulative telemetry to drona_sessions
        total_mute = state.get_total_mute_sec()
        try:
            supabase.table('drona_sessions').update({
                'mute_duration_sec': total_mute,
                'stt_seconds': round(state.stt_seconds, 2),
                'tts_characters': state.tts_characters,
                'reconnect_count': state.reconnect_count + 1
            }).eq('id', session_id).execute()
        except Exception as e:
            print("Telemetry update error on disconnect:", e)
