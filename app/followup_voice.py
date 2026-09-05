"""Speaking one follow-up answer aloud.

Separate from `drona/voice_proxy`, which is built for a classroom: a lease
pool, per-turn prewarming, barge-in, sentence-level scheduling. None of that
applies to one short explanation read once, and borrowing the pool would mean a
follow-up could take a connection a live lesson is waiting on.

So this opens its own socket, says the sentence, and closes. Same Rumik
endpoint, same voice presets, same 24kHz PCM — wrapped as a WAV on the way out
because the phone plays a file here rather than a stream of frames.
"""
import asyncio
import io
import json
import logging
import os
import struct
import time
from typing import Optional

logger = logging.getLogger("snap.followup_voice")

RUMIK_TTS_ENDPOINT = os.getenv("RUMIK_TTS_ENDPOINT", "https://silk-api.rumik.ai")
RUMIK_MODEL = "mulberry"
SAMPLE_RATE = 24000
BYTES_PER_SAMPLE = 2
CHANNELS = 1
# A follow-up is two or three sentences. Past this something has gone wrong and
# waiting longer only makes it worse.
SYNTH_TIMEOUT_S = 25.0
# The voice a student picked, by the names persona.py already uses for them.
VOICE_PRESETS = {"female": "Ira", "male": "Lucas"}
DEFAULT_VOICE = "female"


def preset_for(tutor_voice: Optional[str]) -> str:
    """Rumik's name for the teacher this student chose."""
    return VOICE_PRESETS.get((tutor_voice or DEFAULT_VOICE).lower(),
                             VOICE_PRESETS[DEFAULT_VOICE])


def wav_from_pcm(pcm: bytes) -> bytes:
    """A RIFF header around raw PCM.

    Rumik streams headerless 24kHz mono 16-bit, which is right for a player
    being fed frames and useless to one being handed a file.
    """
    byte_rate = SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE
    return b"".join([
        b"RIFF", struct.pack("<I", 36 + len(pcm)), b"WAVEfmt ",
        struct.pack("<IHHIIHH", 16, 1, CHANNELS, SAMPLE_RATE, byte_rate,
                    CHANNELS * BYTES_PER_SAMPLE, BYTES_PER_SAMPLE * 8),
        b"data", struct.pack("<I", len(pcm)), pcm,
    ])


async def _synthesize(text: str, voice_preset: str) -> bytes:
    import websockets
    import requests

    key = os.getenv("RUMIK_API_KEY")
    if not key:
        raise RuntimeError("RUMIK_API_KEY is not set")

    def _mint():
        return requests.post(
            f"{RUMIK_TTS_ENDPOINT}/v1/tts/ws-connect",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"model": RUMIK_MODEL, "text": "Init"},
            timeout=8,
        ).json()

    loop = asyncio.get_event_loop()
    handshake = await loop.run_in_executor(None, _mint)
    ws_url, token = handshake.get("ws_url"), handshake.get("token")
    if not ws_url or not token:
        raise RuntimeError("Rumik would not hand out a socket")

    ws = await websockets.connect(f"{ws_url}?token={token}",
                                  ping_interval=None, close_timeout=5.0)
    try:
        await ws.send(json.dumps({"text": text, "speaker": voice_preset}))
        buf = bytearray()
        deadline = time.time() + SYNTH_TIMEOUT_S
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                logger.warning("[FOLLOWUP TTS] timed out with %d bytes", len(buf))
                break
            msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
            if isinstance(msg, bytes):
                buf.extend(msg)
            elif isinstance(msg, str):
                payload = json.loads(msg)
                if payload.get("type") in ("done", "complete", "finish", "end"):
                    break
                if payload.get("error") or payload.get("code") == "RATE_LIMITED":
                    logger.warning("[FOLLOWUP TTS] refused: %s",
                                   payload.get("message") or payload.get("code"))
                    break
        return bytes(buf)
    finally:
        try:
            await ws.close()
        except Exception:
            pass


async def speak(text: str, tutor_voice: Optional[str] = None) -> bytes:
    """One explanation as a WAV, in the student's own teacher's voice.

    Returns b"" when it could not be synthesized. Silence is not returned as
    audio: the screen has the steps either way, and a file that plays nothing
    is worse than no file at all, which the app can simply not play.
    """
    said = (text or "").strip()
    if not said:
        return b""
    preset = preset_for(tutor_voice)
    started = time.time()
    try:
        pcm = await _synthesize(said, preset)
    except Exception as err:
        logger.error("[FOLLOWUP TTS] failed for %s: %s", preset, err)
        return b""
    if not pcm:
        return b""
    logger.info("[FOLLOWUP TTS] %s spoke %d chars as %.1fs of audio in %dms",
                preset, len(said),
                len(pcm) / (SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS),
                int((time.time() - started) * 1000))
    return wav_from_pcm(pcm)
