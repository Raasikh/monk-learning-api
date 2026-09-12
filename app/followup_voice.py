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
from typing import Any, Dict, List, Optional, Tuple

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
# Rumik STREAMS its output — the binary frames arrive while it is still
# speaking — so waiting for its "done" was a choice, not a constraint, and it
# cost the whole synthesis before a single sound.
#
# 0.8s. This was 2.5s while the phone played these through the classroom's
# AudioPlaybackQueue, which nudges a playhead that has not moved and shares one
# player across clips — on a short clip that means replaying it, and starting
# the next while it still sounds. The follow-up has its own player now
# (lib/followup-audio.ts) which advances on the clip's OWN known length and
# never nudges, so pieces can be small again.
#
# Not smaller than this: each piece is a file written and opened on the phone,
# and below roughly half a second the per-clip cost starts to matter more than
# the latency it saves.
FLUSH_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS * 0.8)
# A flush is held back until this much would still be left behind it, so the
# LAST clip of an answer is never a sliver.
MIN_TAIL_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS * 0.4)


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


def prewarm(tutor_voice: Optional[str] = None,
            language: Optional[str] = None) -> None:
    """Open a socket in the background, and cache this voice's filler lines.

    Fire and forget: a socket that fails to open costs nothing, because
    `_take_socket` falls back to opening one the usual way.
    """
    global _warming
    # The filler is per-voice and synthesised once for the life of the
    # process: the first follow-up pays for it, every later one opens
    # instantly.
    _warm_filler(tutor_voice, language)
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
                # Raw, exactly as it arrives. All the sizing is done by
                # `speak_chunks`, which is the only place that can see across
                # sentence boundaries — flushing a remainder here produced one
                # stub clip per sentence, and a 0.38s clip is precisely what
                # the player cannot handle.
                yield bytes(msg)
            elif isinstance(msg, str):
                payload = json.loads(msg)
                if payload.get("type") in ("done", "complete", "finish", "end"):
                    break
                if payload.get("error") or payload.get("code") == "RATE_LIMITED":
                    logger.warning("[FOLLOWUP TTS] refused: %s",
                                   payload.get("message") or payload.get("code"))
                    break
    finally:
        try:
            await ws.close()
        except Exception:
            pass


async def _synthesize(text: str, voice_preset: str) -> bytes:
    # The warmed socket, same as the streaming path: the handshake is 1.76s of
    # the wait and it does not have to be paid after the answer exists.
    ws = await _take_socket()
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
# Measured: 588 and 704 characters both came back as exactly 24.7s, i.e. cut.
# 450 leaves real headroom under that while letting an ordinary two or three
# sentence follow-up go as ONE request, which is the only way to be sure there
# is no seam in the middle of it.
MAX_CHARS_PER_REQUEST = 450


# A sentence below this is too short to be its own clip: a two-word
# interjection becomes a file the player opens, starts and closes almost at
# once, and the join around it is heard as a stumble rather than a pause. Such
# a sentence is carried into the next one.
MIN_SPOKEN_CHARS = 40


def _spoken_sentences(text: str) -> list:
    """`text` as the units a voice actually pauses between.

    Different from `_speakable_chunks`, which packs as much as Rumik will take
    per request so a whole-file answer needs the fewest calls. Here the point
    is the opposite: the SMALLEST piece that can be spoken on its own, so the
    first one is ready soonest — and split where a speaker would pause anyway,
    so the gap between files lands on a break that was already there.

    That last part is the whole reason this exists. Slicing the audio every
    0.8s put the joins mid-WORD, and sequential file playback has a
    load-and-start gap at every join, so the voice broke twice a second no
    matter how cleanly the clips were sequenced.
    """
    from app.drona.voice_proxy import split_into_sentences

    out: list = []
    for sentence in split_into_sentences(text, min_chars=0) or [text]:
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > MAX_CHARS_PER_REQUEST:
            cut = sentence.rfind(" ", 0, MAX_CHARS_PER_REQUEST)
            if cut <= 0:
                cut = MAX_CHARS_PER_REQUEST
            out.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if not sentence:
            continue
        # Too short to stand alone, and there is something in front of it to
        # join onto: a stub is a stumble, not a pause.
        #
        # `len(out) > 1` keeps the FIRST sentence out of this. A short opener
        # is not a stub, it is the point — it is spoken as its own clip while
        # the rest is still being synthesised, and synthesis runs at roughly
        # the speed of speech, so a ten-word opener is heard in about two
        # seconds where a twenty-five-word one takes nearly five. Merging it
        # forward collapsed a three-sentence answer into one 166-character
        # clip and put the first sound back at 5.2s.
        if len(out) > 1 and len(out[-1]) < MIN_SPOKEN_CHARS:
            joined = f"{out[-1]} {sentence}".strip()
            if len(joined) <= MAX_CHARS_PER_REQUEST:
                out[-1] = joined
                continue
        out.append(sentence)
    # A trailing stub has nothing after it, so it goes backwards instead.
    if len(out) > 1 and len(out[-1]) < MIN_SPOKEN_CHARS:
        joined = f"{out[-2]} {out[-1]}".strip()
        if len(joined) <= MAX_CHARS_PER_REQUEST:
            out[-2] = joined
            out.pop()
    return out


def _speakable_chunks(text: str) -> list:
    """`text` split so no single request can hit Rumik's ceiling.

    Sentence boundaries first, because that is where a join is inaudible. A
    single sentence longer than the cap — rare, but a run-on derivation can do
    it — is broken at the last space that fits rather than mid-word.
    """
    from app.drona.voice_proxy import split_into_sentences

    chunks: list = []
    # PACKED, not one per sentence. Splitting at every boundary made a
    # three-sentence answer into three separate requests — three sockets,
    # three start-ups, and an audible seam at each join — while Rumik will
    # take the whole thing in one. The cap is the only reason to split at all.
    current = ""
    for sentence in split_into_sentences(text, min_chars=0) or [text]:
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > MAX_CHARS_PER_REQUEST:
            cut = sentence.rfind(" ", 0, MAX_CHARS_PER_REQUEST)
            if cut <= 0:
                cut = MAX_CHARS_PER_REQUEST
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if not sentence:
            continue
        joined = f"{current} {sentence}".strip() if current else sentence
        if len(joined) <= MAX_CHARS_PER_REQUEST:
            current = joined
        else:
            chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


# A short line, already spoken, to cover Rumik's start-up.
#
# Measured, synthesis time barely tracks length: 25 characters took 1.94s, 32
# took 4.15s and 54 took 2.36s. What it tracks is Rumik's own first-byte time,
# which ranged 0.61s to 2.30s across identical calls — so no amount of
# shortening the first sentence makes the first sound reliably quick.
#
# Cached audio has no synthesis time at all, so it sidesteps that variance
# instead of fighting it: the student hears a voice immediately and the real
# first sentence lands behind it.
#
# Deliberately content-free. A filler that commits to anything ("So the answer
# is—") is a claim made before the model has written one, and it would have to
# be right by luck.
# Short, already-spoken lines to cover Rumik's start-up.
#
# Measured, synthesis time barely tracks length: 25 characters took 1.94s, 32
# took 4.15s and 54 took 2.36s. What it tracks is Rumik's own first-byte time,
# which ranged 0.61s to 2.30s across identical calls — so no amount of
# shortening the first sentence makes the first sound reliably quick. Cached
# audio has no synthesis time at all, so it sidesteps that rather than
# fighting it.
#
# Several per voice and language, and ROTATED, because one line played before
# every single follow-up stops being speech and becomes a noise the app makes.
# The classroom learned this first — FILLER_PHRASES is a list per
# (gender, language) for the same reason — and an earlier version of this
# declared two lines and then only ever synthesised the first.
#
# Deliberately content-free. A filler that commits to anything ("So the answer
# is—") is a claim made before the model has written one, and would be right
# only by luck.
FILLER_LINES = {
    ("female", "english"): [
        "Right, let's look at that.",
        "Okay, one moment.",
        "Let me see.",
        "Sure — let's go through it.",
    ],
    ("male", "english"): [
        "Right, let's look at that.",
        "Okay, one moment.",
        "Let me see.",
        "Sure — let's go through it.",
    ],
    ("female", "hinglish"): [
        "Haan, dekhte hain.",
        "Ek second.",
        "Theek hai, chalo dekhte hain.",
        "Ruko, main dekh rahi hoon.",
    ],
    ("male", "hinglish"): [
        "Haan, dekhte hain.",
        "Ek second.",
        "Theek hai, chalo dekhte hain.",
        "Ruko, main dekh raha hoon.",
    ],
}
DEFAULT_LANGUAGE = "hinglish"

# In memory, for the life of the process — never written to disk. They are a
# few seconds of audio each, they cost one synthesis apiece to rebuild, and a
# deploy is exactly when a stale voice or a changed line should be dropped.
_fillers: Dict[str, List[bytes]] = {}
_filler_tasks: Dict[str, asyncio.Task] = {}
# Which line each voice said last, so the next one is the NEXT one. Positional
# rather than random: random repeats, and the same line twice running is
# precisely what makes it obvious.
_filler_turn: Dict[str, int] = {}


def _filler_key(tutor_voice: Optional[str], language: Optional[str]) -> str:
    gender = (tutor_voice or DEFAULT_VOICE).lower()
    if gender not in ("male", "female"):
        gender = DEFAULT_VOICE
    lang = (language or DEFAULT_LANGUAGE).lower()
    if lang not in ("english", "hinglish"):
        lang = DEFAULT_LANGUAGE
    return f"{gender}:{lang}"


def _warm_filler(tutor_voice: Optional[str], language: Optional[str]) -> None:
    """Synthesise this voice and language's lines once, in the background."""
    key = _filler_key(tutor_voice, language)
    if key in _fillers:
        return
    running = _filler_tasks.get(key)
    if running is not None and not running.done():
        return
    gender, lang = key.split(":")
    lines = FILLER_LINES.get((gender, lang)) or []
    preset = preset_for(gender)

    async def _fill():
        made: List[bytes] = []
        for line in lines:
            try:
                pcm = await _synthesize(line, preset)
            except Exception as err:
                logger.info("[FOLLOWUP TTS] no filler for %s (%s) — answers "
                            "simply start when they start", key, err)
                break
            if pcm:
                made.append(pcm)
        if made:
            _fillers[key] = made
            logger.info("[FOLLOWUP TTS] cached %d filler line(s) for %s",
                        len(made), key)

    try:
        _filler_tasks[key] = asyncio.get_event_loop().create_task(_fill())
    except RuntimeError:
        pass


def _next_filler(tutor_voice: Optional[str], language: Optional[str]) -> Optional[bytes]:
    """The next line for this voice, or None if they are not cached yet."""
    key = _filler_key(tutor_voice, language)
    lines = _fillers.get(key)
    if not lines:
        return None
    turn = _filler_turn.get(key, -1) + 1
    _filler_turn[key] = turn
    return lines[turn % len(lines)]


async def speak_chunks(text: str, tutor_voice: Optional[str] = None,
                       language: Optional[str] = None):
    """Yields (index, total, wav) — ONE WHOLE SENTENCE per clip, as each is ready.

    A sentence, not a slice. The audio was previously cut every 0.8s by byte
    count, which lands mid-word, and each piece was played as its own file on
    the phone — where sequential playback has a load-and-start gap at every
    join. The voice broke twice a second and no amount of sequencing repaired
    it, because the split itself was in the wrong place.

    Split where a speaker pauses and the gap falls on a break that was already
    there, which is why the classroom's own sentence-level clips sound
    continuous. Each clip is also seconds long rather than milliseconds, so
    there is time to open the next file before this one runs out.

    The cost is that the first clip waits for a whole sentence rather than
    0.8s of audio — and that is the right trade, since 0.8s pieces could not be
    played smoothly at all.
    """
    said = (text or "").strip()
    if not said:
        return
    preset = preset_for(tutor_voice)
    sentences = _spoken_sentences(said)
    started = time.time()

    # The cached line first, if there is one. Streaming only: the whole-file
    # path has nothing to cover, since by the time it returns the answer is
    # already complete.
    filler = _next_filler(tutor_voice, language)
    if filler:
        logger.info("[FOLLOWUP TTS] %s opened with a cached filler at t+%dms",
                    preset, int((time.time() - started) * 1000))
        yield 0, len(sentences), wav_from_pcm(filler)

    for idx, sentence in enumerate(sentences, 1):
        try:
            pcm = await _synthesize(sentence, preset)
        except Exception as err:
            logger.error("[FOLLOWUP TTS] sentence %d/%d failed for %s: %s",
                         idx, len(sentences), preset, err)
            return
        if not pcm:
            logger.warning("[FOLLOWUP TTS] sentence %d/%d came back empty — "
                           "stopping rather than skipping it", idx, len(sentences))
            return
        logger.info("[FOLLOWUP TTS] %s sentence %d/%d: %d chars -> %.1fs of "
                    "audio at t+%dms", preset, idx, len(sentences), len(sentence),
                    len(pcm) / (SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS),
                    int((time.time() - started) * 1000))
        yield idx, len(sentences), wav_from_pcm(pcm)


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
