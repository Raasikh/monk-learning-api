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
from typing import Any, Optional, Tuple

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


# How much audio to hold before handing a piece over, in bytes of PCM.
#
# Rumik STREAMS its output — the binary frames below arrive while it is still
# speaking the sentence — so waiting for its "done" was a choice, not a
# constraint, and it cost the whole synthesis before a single sound. Measured
# at ~4s for the first sentence, which is the pause the student heard after
# the board had already filled.
#
# 0.7s of audio at 24kHz/16-bit/mono: small enough that speech starts almost
# as soon as Rumik does, large enough that the player is never handed a clip
# too short to cover the gap before the next one arrives.
FLUSH_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS * 0.7)


async def _open_socket():
    """A fresh Rumik socket, minted and connected."""
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
    return await websockets.connect(f"{ws_url}?token={token}",
                                    ping_interval=None, close_timeout=5.0)


# One socket, opened early and parked until there is something to say.
#
# Measured breakdown of the 2.9s before the first sound: 0.42s to mint, 1.34s
# to connect, 0.63s for Rumik's first byte, 0.54s to gather a flush. The
# handshake is 1.76s of that — paid on every request, after the answer already
# exists, with the student watching a finished board in silence.
#
# It does not have to be paid then. `prewarm()` is called the moment a
# follow-up is ASKED, so the socket opens while Deepgram transcribes and the
# model writes; by the time there is a sentence to speak it is already there.
_WARM_TTL_S = 45.0
_warm: Optional[Tuple[Any, float]] = None
_warming: Optional[asyncio.Task] = None


def prewarm() -> None:
    """Open a socket in the background, if one is not already waiting.

    Fire and forget: a socket that fails to open costs nothing, because
    `_take_socket` falls back to opening one the usual way.
    """
    global _warming
    if _warm is not None or (_warming is not None and not _warming.done()):
        return

    async def _fill():
        global _warm
        try:
            ws = await _open_socket()
            _warm = (ws, time.time())
            logger.info("[FOLLOWUP TTS] socket warmed ahead of the answer")
        except Exception as err:
            logger.info("[FOLLOWUP TTS] could not warm a socket (%s) — the "
                        "next synthesis opens its own", err)

    try:
        _warming = asyncio.get_event_loop().create_task(_fill())
    except RuntimeError:
        # No running loop (a sync caller). Warming is an optimisation, and
        # skipping it only costs the handshake it was meant to save.
        pass


async def _take_socket():
    """The warmed socket if one is waiting and still fresh, else a new one."""
    global _warm
    if _warm is not None:
        ws, opened = _warm
        _warm = None
        if time.time() - opened < _WARM_TTL_S and not getattr(ws, "closed", False):
            return ws
        # Past its welcome: Rumik drops an idle socket, and finding that out by
        # sending a sentence down it costs more than opening a new one.
        try:
            await ws.close()
        except Exception:
            pass
    return await _open_socket()


async def _synthesize_stream(text: str, voice_preset: str):
    """PCM in pieces as Rumik produces it, rather than all of it at the end.

    Same protocol as `_synthesize` below; the differences are that this hands
    back what has arrived instead of accumulating it, and that it will use a
    socket opened earlier rather than paying for one here.
    """
    ws = await _take_socket()
    try:
        await ws.send(json.dumps({"text": text, "speaker": voice_preset}))
        buf = bytearray()
        deadline = time.time() + SYNTH_TIMEOUT_S
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                logger.warning("[FOLLOWUP TTS] timed out holding %d bytes", len(buf))
                break
            msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
            if isinstance(msg, bytes):
                buf.extend(msg)
                while len(buf) >= FLUSH_BYTES:
                    piece, buf = buf[:FLUSH_BYTES], buf[FLUSH_BYTES:]
                    yield bytes(piece)
            elif isinstance(msg, str):
                payload = json.loads(msg)
                if payload.get("type") in ("done", "complete", "finish", "end"):
                    break
                if payload.get("error") or payload.get("code") == "RATE_LIMITED":
                    logger.warning("[FOLLOWUP TTS] refused: %s",
                                   payload.get("message") or payload.get("code"))
                    break
        # The tail is never a whole flush, and dropping it would clip the last
        # word off every utterance.
        if buf:
            yield bytes(buf)
    finally:
        try:
            await ws.close()
        except Exception:
            pass


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


# Rumik stops at about 25 seconds of audio per request, whatever it was given.
# Measured: 588 characters and 704 characters both came back as exactly 24.7s
# and 1,156KB — so a long answer was not slow, it was CUT, mid-sentence, and
# the student heard it stop. Anything past roughly this many characters has to
# be sent as more than one request.
MAX_CHARS_PER_REQUEST = 320


def _speakable_chunks(text: str) -> list:
    """`text` split so no single request can hit Rumik's ceiling.

    Sentence boundaries first, because that is where a join is inaudible. A
    single sentence longer than the cap — rare, but a run-on derivation can do
    it — is broken at the last space that fits rather than mid-word.
    """
    from app.drona.voice_proxy import split_into_sentences

    chunks: list = []
    for sentence in split_into_sentences(text, min_chars=0) or [text]:
        sentence = sentence.strip()
        while len(sentence) > MAX_CHARS_PER_REQUEST:
            cut = sentence.rfind(" ", 0, MAX_CHARS_PER_REQUEST)
            if cut <= 0:
                cut = MAX_CHARS_PER_REQUEST
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            chunks.append(sentence)
    return chunks


async def speak_chunks(text: str, tutor_voice: Optional[str] = None):
    """Yields (index, total, wav_bytes) per sentence, as each is ready.

    The reason this exists rather than `speak` being enough: an answer read in
    one piece cannot start until all of it is synthesised. Measured, that is
    9.4s of silence for a 588-character answer — and 24.7s once the answer is
    split into six requests to escape Rumik's ceiling. The student has been
    reading the steps that whole time, which is what makes the wait feel wrong.

    Sent a sentence at a time, the first one plays at ~4s and the rest
    synthesise while it is playing: each chunk is ~5-7s of audio and takes ~4s
    to make, so the voice stays ahead of the ear without any of it being
    buffered up front.

    Each chunk is its own WAV so the player can treat it as a file, which is
    the one thing a browser will play without MediaSource plumbing.
    """
    said = (text or "").strip()
    if not said:
        return
    preset = preset_for(tutor_voice)
    chunks = _speakable_chunks(said)
    started = time.time()
    sent = 0
    for idx, chunk in enumerate(chunks, 1):
        heard = 0
        try:
            # A piece at a time, not a sentence at a time. Rumik streams while
            # it speaks, so the first piece is playable long before the
            # sentence is finished — which is the difference between the voice
            # starting with the board and starting after it.
            async for pcm in _synthesize_stream(chunk, preset):
                if not pcm:
                    continue
                sent += 1
                heard += len(pcm)
                if sent == 1:
                    logger.info("[FOLLOWUP TTS] %s first audio at t+%dms",
                                preset, int((time.time() - started) * 1000))
                # `total` is not known while a sentence is still arriving, and
                # the client does not use it to decide anything — it plays what
                # it is given, in order, until the stream ends.
                yield sent, 0, wav_from_pcm(pcm)
        except Exception as err:
            logger.error("[FOLLOWUP TTS] chunk %d/%d failed for %s: %s",
                         idx, len(chunks), preset, err)
            return
        if not heard:
            logger.warning("[FOLLOWUP TTS] chunk %d/%d came back empty — stopping "
                           "here rather than skipping a sentence", idx, len(chunks))
            return
        logger.info("[FOLLOWUP TTS] %s chunk %d/%d: %d chars -> %.1fs of audio "
                    "by t+%dms", preset, idx, len(chunks), len(chunk),
                    heard / (SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS),
                    int((time.time() - started) * 1000))


async def speak(text: str, tutor_voice: Optional[str] = None) -> bytes:
    """One explanation as a WAV, in the student's own teacher's voice.

    Long answers are synthesised a sentence at a time and joined, because one
    request cannot hold them: Rumik stops at ~25s of audio and returns what it
    has, so a 600-character answer arrived complete-looking and silently
    missing its ending.

    Returns b"" when it could not be synthesized. Silence is not returned as
    audio: the screen has the steps either way, and a file that plays nothing
    is worse than no file at all, which the app can simply not play.
    """
    said = (text or "").strip()
    if not said:
        return b""
    preset = preset_for(tutor_voice)
    started = time.time()
    chunks = _speakable_chunks(said)

    pcm = bytearray()
    for idx, chunk in enumerate(chunks, 1):
        try:
            part = await _synthesize(chunk, preset)
        except Exception as err:
            logger.error("[FOLLOWUP TTS] chunk %d/%d failed for %s: %s",
                         idx, len(chunks), preset, err)
            part = b""
        if not part:
            # Keep what was said rather than losing the whole answer to one bad
            # chunk. A partial read is still better than silence, and the steps
            # are on screen regardless.
            logger.warning("[FOLLOWUP TTS] chunk %d/%d came back empty", idx, len(chunks))
            break
        pcm.extend(part)

    if not pcm:
        return b""
    seconds = len(pcm) / (SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS)
    logger.info("[FOLLOWUP TTS] %s spoke %d chars in %d request(s) as %.1fs of "
                "audio in %dms", preset, len(said), len(chunks), seconds,
                int((time.time() - started) * 1000))
    return wav_from_pcm(bytes(pcm))
